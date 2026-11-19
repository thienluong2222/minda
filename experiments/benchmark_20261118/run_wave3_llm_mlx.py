"""Wave 3C: LoRA B on local MLX 4-bit (Holdout v2.1 60 cases + full Editorial/Writer/Polish + Audio-to-DOCX E2E speed)."""

from __future__ import annotations

import csv
import gc
import json
import re
import shutil
import statistics
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT, ROOT, SEED, log, read_json, rss_mb, setup_root_src, write_csv, write_json


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")


class _TrackedModelSession:
    """Wraps root ModelSession to capture raw schema/retry stats identically to v2.1 benchmark harness."""

    def __init__(self, inner: Any, raw_checks_fn: Any) -> None:
        self.inner = inner
        self.settings = inner.settings
        self.raw_checks_fn = raw_checks_fn
        self.attempts: list[dict] = []

    @property
    def calls(self) -> list[dict]:
        return self.inner.calls

    def token_count(self, text: str) -> int:
        return self.inner.token_count(text)

    def _call_tracked(self, system: str, payload: Any) -> dict:
        from meeting_pipeline.minutes.model_runtime import adapter_active_for, task_for_prompt

        use_adapter = adapter_active_for(self.settings, system)
        raw_res = self.inner.request(
            "chat",
            system=system,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=self.settings.output_token_budget,
            use_adapter=use_adapter,
        )
        raw_res["task"] = task_for_prompt(system)
        chk = self.raw_checks_fn(raw_res, payload)
        attempt = {
            "step": "extract" if "units" in payload else "relations",
            "retry": "repair" in payload,
            "payload": payload,
            **{k: v for k, v in raw_res.items() if k != "text"},
            **chk,
            "accepted_by_parser": False,
            "format_repair": None,
        }
        self.attempts.append(attempt)
        # Pop the entry added by inner.request("chat") because inner.generate_json(_result=raw_res) appends it too
        if self.inner.calls:
            self.inner.calls.pop()
        obj = self.inner.generate_json(system, payload, _result=raw_res)
        self.inner.calls[-1]["task"] = raw_res["task"]
        self.inner.calls[-1]["adapter_active"] = bool(raw_res.get("adapter_active", use_adapter))
        self.inner.calls[-1]["cache_hit"] = False
        attempt["format_repair"] = self.inner.calls[-1].get("format_repair")
        attempt["accepted_by_parser"] = True
        return obj

    def generate_json(self, system: str, payload: Any) -> dict:
        return self._call_tracked(system, payload)

    def generate_json_many(self, system: str, payloads: list[Any]) -> list[Any]:
        from meeting_pipeline.minutes.model_runtime import ModelRuntimeError

        out = []
        for p in payloads:
            try:
                out.append(self._call_tracked(system, p))
            except (ModelRuntimeError, ValueError, TypeError, KeyError) as exc:
                out.append(exc)
        return out


def run_part1_holdout_v21_lora_b_mlx() -> dict:
    """Execute LoRA B on MLX 4-bit via root ModelSession on all 60 Holdout v2.1 cases + 70 oracle batches."""
    # Import root meeting_pipeline BEFORE minda_colab so minda_colab.common.add_vendor() cannot shadow root src/!
    from meeting_pipeline.minutes.graph_builder import build_graph, extract_events, validate_graph
    from meeting_pipeline.minutes.graph_relations import connect_events
    from meeting_pipeline.minutes.graph_topics import discover_topics, refine_topics
    from meeting_pipeline.minutes.model_runtime import ModelRuntimeError, ModelSession, load_model_settings

    proj_dir = ROOT / "web_app/artifacts/minda-colab-v21/LLMTraining"
    if str(proj_dir) not in sys.path:
        sys.path.insert(0, str(proj_dir))
    from minda_colab.common import experiment, read_jsonl, unpack_holdout
    from minda_colab.runtime import E5, raw_checks, units_for
    from minda_colab.score import score_oracle, summarize

    # Remove vendored src path added by minda_colab.common.add_vendor() and re-enforce root src/
    vendor_src = str(proj_dir / "vendor/src")
    if vendor_src in sys.path:
        sys.path.remove(vendor_src)
    setup_root_src()

    # Reuse exact bootstrap & paths from existing 20261118 holdout benchmark
    holdout_dir = ROOT / "reports/minutes_graph/20261118/llm_holdout_comparison"
    bundle = ROOT / "web_app/artifacts/minda-colab-v21"
    cfg_exp = experiment()
    protocol = read_json(holdout_dir / "protocol.json")

    out_dir = OUT / "wave3/llm_mlx/holdout_lora_b"
    out_dir.mkdir(parents=True, exist_ok=True)
    graphs_path = out_dir / "graphs.jsonl"
    oracle_path = out_dir / "gold_event_links.jsonl"

    with tempfile.TemporaryDirectory(prefix="wave3-holdout-") as tmpdir:
        test_dir = unpack_holdout(bundle / "Minda_graph_v21_test_holdout.zip", Path(tmpdir), protocol["test_files"])
        transcripts = read_jsonl(test_dir / "inputs/transcripts.jsonl")
        oracle_batches = read_jsonl(test_dir / "inputs/relations_gold_events_inputs.jsonl")
        references = read_jsonl(test_dir / "references/cases.jsonl")
        oracle_refs = read_jsonl(test_dir / "references/relations_targets.jsonl")

        if graphs_path.is_file() and oracle_path.is_file():
            preds = read_jsonl(graphs_path)
            oracle_preds = read_jsonl(oracle_path)
            if len(preds) == len(transcripts) and len(oracle_preds) == len(oracle_batches):
                log(f"[Wave3C Holdout] Reusing saved complete predictions ({len(preds)} graphs, {len(oracle_preds)} oracle links)")
                batch_by_key = {(b["case_id"], b["batch_index"]): b["user"] for b in oracle_batches}
                for g in preds:
                    for a in g.get("attempts", []):
                        a.setdefault("format_repair", None)
                for o in oracle_preds:
                    att = o.get("attempt", {})
                    att.setdefault("format_repair", None)
                    att.setdefault("payload", batch_by_key[(o["case_id"], o["batch_index"])])
                peak_mlx_gb = max(
                    [a.get("peak_mlx_gb", 0.0) for g in preds for a in g.get("attempts", [])]
                    + [o.get("attempt", {}).get("peak_mlx_gb", 0.0) for o in oracle_preds],
                    default=0.0,
                )
                elapsed_gen = sum(float(g.get("wall_sec", 0.0)) for g in preds) + sum(
                    float(o.get("attempt", {}).get("wall_sec", 0.0)) for o in oracle_preds
                )
            else:
                preds = []
                oracle_preds = []
        else:
            preds = []
            oracle_preds = []

        if not preds:
            # Precompute E5 topics/vectors identically
            e5_snap = ROOT / "data/model_cache/minutes/hub/models--intfloat--multilingual-e5-small/snapshots" / protocol["embedding"]["revision"]
            encoder = E5(cfg_exp, local_path=e5_snap)
            prepared = {}
            for case in transcripts:
                units, meta = units_for(case)
                topics, vectors = discover_topics(encoder, units)
                prepared[case["case_id"]] = (units, meta, topics, vectors)
            del encoder
            gc.collect()

            settings = load_model_settings().model_copy(update={"response_cache": False, "inference_batch_size": 1})
            log(
                f"[Wave3C Holdout] Running LoRA B MLX 4-bit on {len(transcripts)} transcripts + {len(oracle_batches)} oracle batches "
                f"(adapter={settings.adapter_path})"
            )

            t0 = time.perf_counter()
            with ModelSession(out_dir / "runtime.log", settings) as raw_sess:
                sess = _TrackedModelSession(raw_sess, raw_checks)
                for idx, case in enumerate(transcripts, start=1):
                    units, meta, topics, vectors = prepared[case["case_id"]]
                    sess.attempts.clear()
                    ts = time.perf_counter()
                    events, links, warnings = extract_events(sess, units, vectors)
                    links = connect_events(sess, events, links, units)
                    provisional = build_graph(case["case_id"], units, events, topics, links, metadata=meta)
                    refined = refine_topics(topics, units, provisional.events, provisional.edges)
                    graph = build_graph(case["case_id"], units, events, refined, links, metadata=meta, warnings=warnings)
                    preds.append(
                        {
                            "case_id": case["case_id"],
                            "family_id": case["family_id"],
                            "graph": graph.model_dump(mode="json"),
                            "errors": validate_graph(graph),
                            "attempts": list(sess.attempts),
                            "wall_sec": time.perf_counter() - ts,
                        }
                    )
                    if idx == 1 or idx % 10 == 0 or idx == len(transcripts):
                        log(f"[Wave3C Holdout] transcripts {idx}/{len(transcripts)} ({time.perf_counter() - t0:.1f}s)")

                for idx, batch in enumerate(oracle_batches, start=1):
                    sess.attempts.clear()
                    try:
                        parsed = sess.generate_json(batch["system"], batch["user"])
                    except ModelRuntimeError:
                        parsed = None
                    oracle_preds.append(
                        {
                            "case_id": batch["case_id"],
                            "batch_index": batch["batch_index"],
                            "parsed": parsed,
                            "attempt": sess.attempts[-1] if sess.attempts else {},
                        }
                    )
                    if idx == 1 or idx % 20 == 0 or idx == len(oracle_batches):
                        log(f"[Wave3C Holdout] oracle links {idx}/{len(oracle_batches)} ({time.perf_counter() - t0:.1f}s)")

                peak_mlx_gb = max((c.get("peak_mlx_gb", 0.0) for c in raw_sess.calls), default=0.0)

            elapsed_gen = time.perf_counter() - t0
            _write_jsonl(graphs_path, preds)
            _write_jsonl(oracle_path, oracle_preds)

        metrics, rows_case = summarize(references, preds)
        metrics["oracle_linker"] = score_oracle(oracle_preds, oracle_refs)

        # Schema & retry telemetry matching Colab BAO_CAO.md metrics (70 extract batches across 60 transcripts)
        extract_first = [a for g in preds for a in g["attempts"] if a["step"] == "extract" and not a["retry"]]
        extract_retries = [a for g in preds for a in g["attempts"] if a["step"] == "extract" and a["retry"]]
        first_schema_ok = sum(1 for a in extract_first if a.get("schema") and a.get("ids"))

        # Load existing comparison rows & run paired bootstrap vs Qwen3 MLX Base and Colab LoRA B NF4
        colab_b_graphs = read_jsonl(bundle / "LLMTraining/data/train/evaluation/AB/test/B/graphs.jsonl")
        colab_b_metrics, colab_b_rows = summarize(references, colab_b_graphs)
        qwen3_mlx_graphs = read_jsonl(holdout_dir / "qwen3_mlx/graphs.jsonl")
        qwen3_mlx_metrics, qwen3_mlx_rows = summarize(references, qwen3_mlx_graphs)

        # Family-clustered bootstrap identical to llm_holdout_comparison/benchmark.py
        import sys as _sys
        import importlib.util

        spec = importlib.util.spec_from_file_location("holdout_bench", holdout_dir / "benchmark.py")
        hb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hb)
        boot = hb.bootstrap(
            {"base": qwen3_mlx_rows, "colab_lora_b_nf4": colab_b_rows, "lora_b_mlx": rows_case},
            draws=10000,
            seed=cfg_exp["evaluation"]["bootstrap_seed"],
        )

        # Build comparison summary table
        comp_rows = [
            {
                "config": "Qwen3-4B-Instruct-2507 (MLX 4-bit Base)",
                "runtime": "MLX / Apple M4",
                "event_f1": round(qwen3_mlx_metrics["event"]["f1"], 4),
                "relation_f1": round(qwen3_mlx_metrics["relation_end_to_end"]["f1"], 4),
                "oracle_relation_f1": round(read_json(holdout_dir / "qwen3_mlx/metrics.json")["oracle_linker"]["relation_on_gold_events"]["f1"], 4),
                "state_exact": round(qwen3_mlx_metrics["state_exact"]["accuracy"], 4),
                "state_correct": qwen3_mlx_metrics["state_exact"]["correct"],
                "case_median_sec": round(qwen3_mlx_metrics["case_wall_sec_median"], 2),
            },
            {
                "config": "Qwen3 + LoRA B (Colab NF4 L4 reference)",
                "runtime": "NF4 / NVIDIA L4",
                "event_f1": round(colab_b_metrics["event"]["f1"], 4),
                "relation_f1": round(colab_b_metrics["relation_end_to_end"]["f1"], 4),
                "oracle_relation_f1": round(read_json(bundle / "LLMTraining/data/train/evaluation/AB/test/B/metrics.json")["oracle_linker"]["relation_on_gold_events"]["f1"], 4),
                "state_exact": round(colab_b_metrics["state_exact"]["accuracy"], 4),
                "state_correct": colab_b_metrics["state_exact"]["correct"],
                "case_median_sec": round(colab_b_metrics["case_wall_sec_median"], 2),
            },
            {
                "config": "Qwen3 + LoRA B (Local MLX 4-bit, configs/minutes.yaml)",
                "runtime": "MLX / Apple M4",
                "event_f1": round(metrics["event"]["f1"], 4),
                "relation_f1": round(metrics["relation_end_to_end"]["f1"], 4),
                "oracle_relation_f1": round(metrics["oracle_linker"]["relation_on_gold_events"]["f1"], 4),
                "state_exact": round(metrics["state_exact"]["accuracy"], 4),
                "state_correct": metrics["state_exact"]["correct"],
                "case_median_sec": round(metrics["case_wall_sec_median"], 2),
            },
        ]

        res = {
            "elapsed_sec": round(elapsed_gen, 2),
            "peak_mlx_gb": round(peak_mlx_gb, 3),
            "extract_first_pass_batches": len(extract_first),
            "extract_first_pass_schema_ok": first_schema_ok,
            "extract_retries": len(extract_retries),
            "lora_b_mlx_metrics": metrics,
            "comparison": comp_rows,
            "paired_bootstrap": boot,
        }
        write_csv(out_dir / "comparison.csv", comp_rows)
        write_json(out_dir / "results.json", res)
        log(f"[Wave3C Holdout] LoRA B MLX: event_f1={comp_rows[2]['event_f1']} rel_f1={comp_rows[2]['relation_f1']} state={comp_rows[2]['state_correct']}/42 median={comp_rows[2]['case_median_sec']}s")
        return res


def run_part2_downstream_writer_and_editorial() -> dict:
    """Benchmark full generate_graph_minutes (topics + name_topics + plan + write + polish + docx) on 12 stratified v2.1 test cases."""
    from docx import Document

    from meeting_pipeline.minutes.converter import normalize_template
    from meeting_pipeline.minutes.doc_parser import parse_template_document
    from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn, _tokenize
    from meeting_pipeline.minutes.fact_extractor import M2RuleFactExtractor
    from meeting_pipeline.minutes.graph_export import guard_graph_export
    from meeting_pipeline.minutes.graph_inputs import make_graph_units
    from meeting_pipeline.minutes.graph_pipeline import generate_graph_minutes, graph_narrative_values
    from meeting_pipeline.minutes.graph_writer import numeric_values
    from meeting_pipeline.minutes.model_runtime import ModelSession, load_model_settings
    from meeting_pipeline.minutes.renderer import render_completed_document
    from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper
    from meeting_pipeline.minutes.schemas import PlaceholderType, SemanticFieldType
    from meeting_pipeline.minutes.structured_fields import structured_facts

    v21_test = [
        json.loads(l)
        for l in (ROOT / "web_app/artifacts/graph-synthetic-v2.1/test/inputs/transcripts.jsonl").read_text().splitlines()
        if l.strip()
    ]
    # Pick 2 longest cases from each of the 6 meeting modes -> 12 realistic cases
    by_mode: dict[str, list[dict]] = {}
    for c in v21_test:
        by_mode.setdefault(c["meeting_mode"], []).append(c)
    selected_cases = []
    for mode in sorted(by_mode):
        ranked = sorted(by_mode[mode], key=lambda x: (-len(x["turns"]), x["case_id"]))
        selected_cases.extend(ranked[:2])

    tpl_path = ROOT / "tests/fixtures/templates/mau_bien_ban_hop_chung.doc"
    configs_to_test = [
        ("qwen3_base_sil022", {"adapter_path": None, "minimum_silhouette": 0.22}),
        ("lora_b_mlx_sil022", {"minimum_silhouette": 0.22}),
        ("lora_b_mlx_sil012", {"minimum_silhouette": 0.12}),
    ]

    rows_summary = []
    per_case_rows = []
    base_settings = load_model_settings()

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        conv = normalize_template(tpl_path, work / "tpl")
        doc_graph = parse_template_document(conv.normalized_docx_path, original_sha256=conv.original_sha256)
        schema = M0RuleSchemaMapper().propose_schema(doc_graph)
        anchors_map = {a.anchor_id: a for a in doc_graph.all_anchors}
        body_field_id = next(
            (
                f.field_id
                for f in schema.fields
                if f.semantic_type in {SemanticFieldType.DISCUSSION_SUMMARY, SemanticFieldType.MEETING_AGENDA}
                and anchors_map[f.anchor_id].placeholder_type
                not in {PlaceholderType.SIGNATURE_BLOCK, PlaceholderType.FIXED_TEXT}
            ),
            "discussion_summary",
        )
        extractor = M2RuleFactExtractor()

        for cfg_name, upd in configs_to_test:
            settings = base_settings.model_copy(update={"response_cache": False, **upd})
            out_cfg = work / cfg_name
            cfg_metrics = []
            with ModelSession(out_cfg / "runtime.log", settings) as session:
                for case in selected_cases:
                    turns = [
                        IndexedTurn(
                            turn_id=t["turn_id"],
                            speaker_label=t["speaker"],
                            speaker_id=t.get("speaker_id"),
                            start_sec=float(i * 10),
                            end_sec=float(i * 10 + 8),
                            text=t["text"],
                            tokens=_tokenize(t["text"]),
                            source_id="src-1",
                            clip_path=None,
                            asr_status=t["asr_status"],
                            needs_review=t.get("needs_review", False),
                            confidence=1.0,
                            session_id=t.get("session_id", "session_0"),
                        )
                        for i, t in enumerate(case["turns"])
                    ]
                    units, _ = make_graph_units(turns)
                    case_run_dir = out_cfg / case["case_id"]
                    case_min_dir = case_run_dir / "minutes"
                    start_calls = len(session.calls)
                    ts = time.perf_counter()
                    res = generate_graph_minutes(
                        session,
                        units,
                        meeting_id=case["case_id"],
                        output=case_min_dir,
                        metadata={"title": f"Cuộc họp {case['domain']}", "attendees": sorted({t["speaker"] for t in case["turns"]})},
                        mode="general",
                    )
                    total_sec = time.perf_counter() - ts
                    calls = session.calls[start_calls:]
                    rep = res["report"]
                    text_out = res["text"]
                    src_text = "\n".join(u.text for u in units)

                    # Check DOCX end-to-end export + ZipFile testzip integrity
                    facts_m2 = extractor.extract_facts(schema, turns, run_id=case["case_id"])
                    facts_s = structured_facts(schema, doc_graph, turns, case["case_id"])
                    by_id = {f.field_id: f for f in facts_m2}
                    for sf_item in facts_s:
                        if sf_item.value not in (None, "", []):
                            by_id[sf_item.field_id] = sf_item
                    narr = graph_narrative_values(
                        res["graph"], res["sections"], schema, turns, case["case_id"], body_field_id, text_out
                    )
                    by_id.update(narr)
                    guarded = guard_graph_export(case_run_dir, schema, doc_graph, list(by_id.values()), turns)
                    out_docx = case_run_dir / "rendered.docx"
                    render_completed_document(conv.normalized_docx_path, out_docx, doc_graph, schema, guarded)
                    with zipfile.ZipFile(out_docx, "r") as zf:
                        zip_ok = zf.testzip() is None

                    # Per-task timing breakdown
                    by_task_sec: dict[str, float] = {}
                    for c in calls:
                        tk = c.get("task", "default")
                        by_task_sec[tk] = by_task_sec.get(tk, 0.0) + float(c.get("wall_sec", 0.0))
                    intro_nums = sum((numeric_values(text_out) - numeric_values(src_text)).values())
                    sents = [s.strip() for s in re.split(r"[.!?]+", text_out) if s.strip()]
                    dup_rate = 1.0 - (len({s.casefold() for s in sents}) / max(len(sents), 1))
                    row = {
                        "config": cfg_name,
                        "case_id": case["case_id"],
                        "meeting_mode": case["meeting_mode"],
                        "units": len(units),
                        "clusters": rep["cluster_count"],
                        "events": rep["event_count"],
                        "edges": rep["edge_count"],
                        "sections": rep["outline_section_count"],
                        "total_sec": round(total_sec, 2),
                        "llm_calls": len(calls),
                        "out_tokens": sum(c.get("generation_tokens", 0) for c in calls),
                        "extract_sec": round(by_task_sec.get("extract", 0.0), 2),
                        "relations_sec": round(by_task_sec.get("relations", 0.0), 2),
                        "editorial_writer_polish_sec": round(by_task_sec.get("default", 0.0), 2),
                        "claim_coverage_complete": rep["coverage"]["claim_id_coverage_complete"],
                        "source_fallback_rate": round(rep["coverage"]["source_fallback_rate"], 4),
                        "introduced_numeric_count": intro_nums,
                        "duplicate_sentence_rate": round(dup_rate, 4),
                        "word_ratio": round(len(text_out.split()) / max(len(src_text.split()), 1), 3),
                        "zip_ok": zip_ok,
                        "peak_mlx_gb": round(rep["peak_mlx_gb"], 3),
                    }
                    cfg_metrics.append(row)
                    per_case_rows.append(row)

            import numpy as np

            rows_summary.append(
                {
                    "config": cfg_name,
                    "cases": len(cfg_metrics),
                    "mean_clusters": round(float(np.mean([r["clusters"] for r in cfg_metrics])), 3),
                    "multi_topic_rate": round(float(np.mean([r["clusters"] > 1 for r in cfg_metrics])), 4),
                    "mean_total_sec": round(float(np.mean([r["total_sec"] for r in cfg_metrics])), 2),
                    "mean_editorial_writer_sec": round(float(np.mean([r["editorial_writer_polish_sec"] for r in cfg_metrics])), 2),
                    "coverage_complete_rate": round(float(np.mean([r["claim_coverage_complete"] for r in cfg_metrics])), 4),
                    "mean_source_fallback_rate": round(float(np.mean([r["source_fallback_rate"] for r in cfg_metrics])), 4),
                    "total_introduced_numbers": int(sum(r["introduced_numeric_count"] for r in cfg_metrics)),
                    "mean_dup_sent_rate": round(float(np.mean([r["duplicate_sentence_rate"] for r in cfg_metrics])), 4),
                    "mean_word_ratio": round(float(np.mean([r["word_ratio"] for r in cfg_metrics])), 3),
                    "zip_integrity_rate": round(float(np.mean([r["zip_ok"] for r in cfg_metrics])), 4),
                    "peak_mlx_gb": round(max(r["peak_mlx_gb"] for r in cfg_metrics), 3),
                }
            )
            log(
                f"[Wave3C Downstream] {cfg_name}: mean_sec={rows_summary[-1]['mean_total_sec']} "
                f"clusters={rows_summary[-1]['mean_clusters']} fallback={rows_summary[-1]['mean_source_fallback_rate']} "
                f"new_nums={rows_summary[-1]['total_introduced_numbers']}"
            )
    return {"summary": rows_summary, "per_case": per_case_rows}


def run_part3_full_audio_to_docx_e2e() -> list[dict]:
    """Cold uncached full Audio -> Speaker -> MLX ASR -> Fusion -> Graph LoRA B MLX -> DOCX/ZIP speed replay on configs/default.yaml."""
    import jiwer
    import soundfile as sf

    from meeting_pipeline.config import load_config
    from meeting_pipeline.data.vivos import normalize_vietnamese_text
    from meeting_pipeline.minutes import graph_pipeline
    from meeting_pipeline.minutes.model_runtime import ModelSession, load_model_settings
    from meeting_pipeline.minutes.service import MinutesService
    from meeting_pipeline.minutes.text_engine import MinutesOptions
    from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

    class _UncachedSession(ModelSession):
        def __init__(self, log_path: Path, settings=None):
            super().__init__(log_path, (settings or load_model_settings()).model_copy(update={"response_cache": False}))

    orig_ms = graph_pipeline.ModelSession
    graph_pipeline.ModelSession = _UncachedSession

    pilot_dir = ROOT / "data/generated/fpt_tts_pilot_20261003/meeting_audio"
    ref_segs = read_json(pilot_dir / "reference_segments.json")
    ref_text = normalize_vietnamese_text(" ".join(r["reference_text"] for r in ref_segs))
    tpl_path = ROOT / "tests/fixtures/templates/mau_bien_ban_hop_chung.doc"

    scenarios = [
        ("pilot_1mic_clean_uncached", [pilot_dir / "clean_reference.wav"]),
        ("pilot_3mic_phones_uncached", [pilot_dir / "phone_huy.wav", pilot_dir / "phone_lan.wav", pilot_dir / "phone_minh.wav"]),
    ]

    e2e_rows = []
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for name, wavs in scenarios:
                run_root = tmp / name
                cfg = load_config(ROOT / "configs/default.yaml")
                cfg.paths.data_dir = run_root
                cfg.paths.database_path = run_root / "app.sqlite"
                cfg.paths.model_cache_dir = ROOT / "data/model_cache"
                cfg.asr.cache_enabled = False
                cfg.asr.runtime = "mlx"
                cfg.asr.auto_backend = "mlx"
                cfg.asr.mlx_runtime_python = str(ROOT / ".venv-asr-mlx/bin/python")

                audio_sec_dur = float(sf.info(wavs[0]).duration)
                t0 = time.perf_counter()
                pipeline = MultiSourceFusionPipeline(cfg)
                run_dir = pipeline.run(name, wavs, fusion_method="F5_RULE_WEIGHTED_CORRECTED")
                audio_wall = time.perf_counter() - t0
                del pipeline
                gc.collect()

                tl = read_json(run_dir / "timeline.json")
                hyp_text = normalize_vietnamese_text(" ".join(s.get("text", "") for s in tl.get("segments", [])))
                asr_wer = round(float(jiwer.wer([ref_text], [hyp_text])), 4) if ref_text else None

                t1 = time.perf_counter()
                min_res = MinutesService().process_template_for_run(
                    tpl_path,
                    run_dir,
                    meeting_metadata={"meeting_name": "Họp triển khai kho tài liệu Sao Khuê", "location": "B201"},
                    options=MinutesOptions(
                        use_model=True,
                        graph_enabled=True,
                        mode="general",
                        correct_transcript=True,
                        format_standard="minimal",
                    ),
                )
                minutes_wall = time.perf_counter() - t1
                total_wall = audio_wall + minutes_wall

                zip_path = min_res.get("zip_export")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zip_ok = zf.testzip() is None

                row = {
                    "scenario": name,
                    "sources": len(wavs),
                    "audio_duration_sec": round(audio_sec_dur, 2),
                    "audio_pipeline_sec": round(audio_wall, 2),
                    "minutes_graph_docx_sec": round(minutes_wall, 2),
                    "total_e2e_sec": round(total_wall, 2),
                    "total_rtf": round(total_wall / max(audio_sec_dur, 1e-6), 3),
                    "segments_count": len(tl.get("segments", [])),
                    "asr_wer_vs_ref": asr_wer,
                    "zip_integrity_ok": zip_ok,
                }
                e2e_rows.append(row)
                log(f"[Wave3C Full E2E] {name}: audio={audio_wall:.1f}s minutes={minutes_wall:.1f}s total={total_wall:.1f}s WER={asr_wer} zip={zip_ok}")
    finally:
        graph_pipeline.ModelSession = orig_ms
    return e2e_rows


def main() -> None:
    setup_root_src()
    t0 = time.perf_counter()
    out_dir = OUT / "wave3/llm_mlx"
    out_dir.mkdir(parents=True, exist_ok=True)

    p1 = run_part1_holdout_v21_lora_b_mlx()
    p2 = run_part2_downstream_writer_and_editorial()
    write_csv(out_dir / "downstream_summary.csv", p2["summary"])
    write_csv(out_dir / "downstream_per_case.csv", p2["per_case"])

    p3 = run_part3_full_audio_to_docx_e2e()
    write_csv(out_dir / "full_e2e_speed.csv", p3)

    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave3_llm_mlx_full",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "holdout_v21_lora_b_mlx": p1,
            "downstream_writer_editorial": p2,
            "full_audio_to_docx_e2e": p3,
        },
    )
    log(f"[Wave3C] ALL DONE in {time.perf_counter() - t0:.2f}s | peak_rss={rss_mb():.1f}MB")


if __name__ == "__main__":
    main()
