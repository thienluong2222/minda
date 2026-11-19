"""Focused regression tests for audio ingest/sync/fusion, ASR, and minutes graph fixes."""

from __future__ import annotations

import json
import subprocess

import docx
import numpy as np

from meeting_pipeline.adapters import audio_io
from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
from meeting_pipeline.audio.signal_fusion import fuse_sources
from meeting_pipeline.audio.synchronization import _estimate_windowed_drift
from meeting_pipeline.config import AsrConfig
from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.graph_builder import build_graph, fallback_event
from meeting_pipeline.minutes.graph_contracts import EvidenceAnchor, Paragraph
from meeting_pipeline.minutes.graph_editorial import editorial_role
from meeting_pipeline.minutes.graph_export import guard_graph_export
from meeting_pipeline.minutes.graph_inputs import make_graph_units
from meeting_pipeline.minutes.graph_pipeline import graph_narrative_values
from meeting_pipeline.minutes.graph_plan import ContentPlan, PlannedSectionEdit, revise_plan
from meeting_pipeline.minutes.graph_writer import (
    deterministic_risks,
    event_source_text,
    plan_sections,
)
from meeting_pipeline.minutes.renderer import _replace_text_in_paragraph
from meeting_pipeline.minutes.schemas import (
    CandidateAnchor,
    DocBlock,
    DocGraph,
    MeetingFact,
    SemanticFieldType,
    TemplateField,
    TemplateSchema,
)


def test_probe_audio_marks_unindexed_adts_aac_as_estimate(monkeypatch, tmp_path) -> None:
    sample = tmp_path / "mic.aac"
    sample.write_bytes(b"fake")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "streams": [
                        {
                            "codec_name": "aac",
                            "sample_rate": "44100",
                            "channels": "1",
                            "duration": "33.872699",
                        }
                    ],
                    "format": {"duration": "33.872699", "format_name": "aac"},
                }
            ).encode(),
        )

    monkeypatch.setattr(audio_io.subprocess, "run", fake_run)
    meta = audio_io.probe_audio(sample)
    assert meta.duration_is_estimate is True
    assert meta.duration_source == "stream"


def test_windowed_drift_adapts_step_on_medium_overlap() -> None:
    sr = 16000
    rng = np.random.default_rng(7)
    # 25s speech-like modulated noise with 1.5s pauses; longer than 8s window, < 30s default step.
    t = np.arange(25 * sr, dtype=np.float32) / sr
    envelope = (0.3 + 0.7 * np.abs(np.sin(2 * np.pi * 0.4 * t))).astype(np.float32)
    ref = (rng.normal(0, 0.1, size=len(t)) * envelope).astype(np.float32)
    drift_ppm, residual_ms, status = _estimate_windowed_drift(
        ref, ref.copy(), sr, base_offset_sec=0.0, window_sec=8.0, step_sec=30.0
    )
    assert status == "aligned"
    assert residual_ms < 20.0
    assert abs(drift_ppm) < 50.0


def test_fuse_sources_supports_three_mics_with_mild_sro_and_rejects_noise() -> None:
    sr = 16000
    rng = np.random.default_rng(11)
    ref = rng.normal(0, 0.15, size=3 * sr).astype(np.float32)
    # Construct reverberant/filtered room mics (similarity ~0.4-0.6) with 25-sample delay + drift.
    room = np.convolve(ref, [0.55, 0.3, 0.15, -0.08], mode="same").astype(np.float32)
    grid = np.arange(len(room), dtype=np.float64)
    sec1 = np.interp(grid + 25.0 + 1.0 * (grid / sr), grid, room).astype(np.float32)
    sec2 = np.interp(grid - 18.0 - 0.5 * (grid / sr), grid, room).astype(np.float32)
    uncorr = rng.normal(0, 0.1, size=len(ref)).astype(np.float32)

    mixed, details = fuse_sources(
        [
            ("source-1", ref, {"status": "reference"}, 0.9),
            ("source-2", sec1, {"status": "aligned"}, 0.85),
            ("source-3", uncorr, {"status": "aligned"}, 0.8),
            ("source-4", sec2, {"status": "aligned"}, 0.75),
        ],
        clip_start=0,
        core=(0, len(ref)),
        sample_rate=sr,
    )
    assert mixed.shape == ref.shape
    assert set(details["contributors"]) == {"source-1", "source-2", "source-4"}
    assert details["rejected_secondary_reasons"] == {"source-3": "uncertain_local_delay"}


def test_phowhisper_preserves_word_confidence_and_skips_short_cpu_fallback(tmp_path) -> None:
    text, words, warnings = PhoWhisperAsrAdapter._parse_output(
        {
            "text": "xin chào",
            "chunks": [
                {"text": "xin", "timestamp": [0.0, 0.2], "confidence": 0.91},
                {"text": "chào", "timestamp": [0.2, 0.5]},
            ],
        }
    )
    assert text == "xin chào"
    assert not warnings
    assert [w.confidence for w in words] == [0.91, None]

    class EmptyMlxPipe:
        device = "mlx"

        def __call__(self, *_a, **_kw):
            return {"text": "", "chunks": []}

    cfg = AsrConfig(model_id="same", model_revision="same", runtime="auto", max_decode_attempts=1)
    adapter = PhoWhisperAsrAdapter(cfg, tmp_path)
    adapter._pipeline = EmptyMlxPipe()
    # Micro-fragment < 0.8s with empty output must not spawn expensive CPU fallback.
    res = adapter.transcribe(np.ones(round(0.4 * 16000), dtype=np.float32), 16000)
    assert res.status == "empty"
    assert "asr_cpu_fallback" not in res.warnings


def test_minutes_editorial_verifier_plan_and_renderer_regressions(tmp_path) -> None:
    assert editorial_role("Nếu là.") == "review"
    assert editorial_role("Tức là.") == "review"
    assert "dropped_date_day" in deterministic_risks(
        "Hạn nộp ngày tháng mười.", "Hạn nộp ngày năm tháng mười."
    )
    assert "introduced_recurrence:mỗi ngày" in deterministic_risks(
        "Kiểm tra báo cáo mỗi ngày.", "Thảo luận ngày gửi báo cáo."
    )

    doc = docx.Document()
    p = doc.add_paragraph("Về việc)........")
    assert _replace_text_in_paragraph(p, "........", "triển khai kế hoạch mới")
    assert p.text == "Về việc) triển khai kế hoạch mới"

    # event_source_text prefers corrected unit.text when unit was safely cleaned.
    u_turn = IndexedTurn(
        turn_id="t0",
        speaker_label="Huy",
        speaker_id="Huy",
        text="kho thời liệu",
        start_sec=0.0,
        end_sec=2.0,
        tokens=[],
        source_id="mic",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=0.9,
    )
    units, _ = make_graph_units([u_turn])
    units[0].text = "Tạo kho tài liệu chung."
    ev = fallback_event(units[0]).model_copy(
        update={
            "anchor": EvidenceAnchor(
                unit_id=units[0].unit_id,
                start_char=0,
                end_char=len(units[0].original),
                quote=units[0].original,
            )
        }
    )
    rendered_src = event_source_text(ev, {units[0].unit_id: units[0]}, {ev.event_id: ev})
    assert "kho tài liệu chung" in rendered_src

    # Title-only edit in revise_plan keeps verified paragraphs without marking section changed.
    graph = build_graph(
        "m",
        units,
        [ev],
        {"primary": [0], "membership": [[1.0]], "titles": ["Nội dung"], "cluster_count": 1},
        [],
    )
    sections, ledger = plan_sections(graph)
    sections[0].paragraphs = [
        Paragraph(text="Huy đề xuất tạo kho tài liệu chung.", claim_ids=[ev.event_id])
    ]
    plan = ContentPlan(graph_id=graph.graph_id, sections=sections, ledger=ledger)
    plan.seal()
    edits = [
        PlannedSectionEdit(
            section_id=plan.sections[0].section_id,
            title="Tiêu đề mới",
            items=[
                {
                    "item_id": item.item_id,
                    "priority": item.priority,
                    "included": item.included,
                }
                for item in plan.sections[0].outline
            ],
        )
    ]
    revised, changed = revise_plan(plan, graph, edits)
    assert changed == set()
    assert revised.sections[0].title == "Tiêu đề mới"
    assert revised.sections[0].paragraphs == plan.sections[0].paragraphs


def test_decision_list_excludes_vote_in_graph_2_0(tmp_path) -> None:
    t_dec = IndexedTurn(
        turn_id="t0",
        speaker_label="Lan",
        speaker_id="Lan",
        text="Nhóm thống nhất dùng kho tài liệu chung.",
        start_sec=0.0,
        end_sec=2.0,
        tokens=[],
        source_id="mic",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=0.9,
    )
    t_vote = IndexedTurn(
        turn_id="t1",
        speaker_label="Minh",
        speaker_id="Minh",
        text="Ai tán thành xin giơ tay biểu quyết.",
        start_sec=2.0,
        end_sec=4.0,
        tokens=[],
        source_id="mic",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=0.9,
    )
    units, _ = make_graph_units([t_dec, t_vote])
    ev_dec = fallback_event(units[0]).model_copy(
        update={"kind": "decision", "text": "Nhóm thống nhất dùng kho tài liệu chung."}
    )
    ev_vote = fallback_event(units[1]).model_copy(
        update={"kind": "vote", "text": "Ai tán thành xin giơ tay biểu quyết."}
    )
    graph = build_graph(
        "m",
        units,
        [ev_dec, ev_vote],
        {"primary": [0, 0], "membership": [[1.0], [1.0]], "titles": ["Chung"], "cluster_count": 1},
        [],
    )
    anchor_b = CandidateAnchor(
        anchor_id="a_body", block_id="b_body", element_path="p[0]", placeholder_text="..."
    )
    anchor_d = CandidateAnchor(
        anchor_id="a_dec", block_id="b_dec", element_path="p[1]", placeholder_text="..."
    )
    doc_graph = DocGraph(
        template_id="t",
        template_name="t",
        original_sha256="a",
        normalized_docx_sha256="b",
        blocks=[
            DocBlock(
                block_id="b_body",
                order=0,
                block_type="paragraph",
                raw_text="Nội dung: ...",
                element_path="p[0]",
                candidate_anchors=[anchor_b],
            ),
            DocBlock(
                block_id="b_dec",
                order=1,
                block_type="paragraph",
                raw_text="Kết luận: ...",
                element_path="p[1]",
                candidate_anchors=[anchor_d],
            ),
        ],
    )
    schema = TemplateSchema(
        template_id="t",
        template_name="t",
        template_hash="a",
        fields=[
            TemplateField(
                field_id="f_body",
                anchor_id="a_body",
                raw_label="Nội dung",
                semantic_type=SemanticFieldType.CUSTOM,
            ),
            TemplateField(
                field_id="f_dec",
                anchor_id="a_dec",
                raw_label="Kết luận",
                semantic_type=SemanticFieldType.DECISION_LIST,
            ),
        ],
    )
    sections, _ = plan_sections(graph)
    sections[0].paragraphs = [
        Paragraph(
            text="Nhóm thống nhất dùng kho tài liệu chung.",
            claim_ids=[ev_dec.event_id, ev_vote.event_id],
            verification="checked",
        )
    ]
    vals = graph_narrative_values(
        graph, sections, schema, [t_dec, t_vote], "m", "f_body", "Nội dung"
    )
    assert "giơ tay" not in (vals["f_dec"].value or "")
    assert "kho tài liệu" in (vals["f_dec"].value or "")

    # guard_graph_export must also enforce cleaned conclusion when schema_version == "2.0".
    minutes_dir = tmp_path / "minutes"
    minutes_dir.mkdir()
    (minutes_dir / "meeting_graph.json").write_text(json.dumps(graph.model_dump()))
    facts = [
        MeetingFact(field_id="f_body", value="Nội dung"),
        MeetingFact(field_id="f_dec", value="Ai tán thành xin giơ tay."),
    ]
    guarded = {f.field_id: f for f in guard_graph_export(tmp_path, schema, doc_graph, facts, [])}
    assert "giơ tay" not in (guarded["f_dec"].value or "")
    assert "kho tài liệu" in (guarded["f_dec"].value or "")


def test_lora_adapter_scoping_checksum_validation_and_cache_isolation(tmp_path) -> None:
    import hashlib

    import pytest

    from meeting_pipeline.minutes.graph_builder import COMPACT_EXTRACTION_PROMPT
    from meeting_pipeline.minutes.graph_relations import RELATION_PROMPT
    from meeting_pipeline.minutes.model_runtime import (
        ModelRuntimeError,
        ModelSession,
        ModelSettings,
        adapter_active_for,
        load_model_settings,
        model_status,
        task_for_prompt,
        verify_adapter_dir,
    )

    loaded = load_model_settings()
    assert loaded.adapter_scopes == ["extract", "relations"]
    status = model_status()
    assert "adapter_configured" in status and "adapter_cached" in status

    adapter_dir = tmp_path / "ckpt"
    adapter_dir.mkdir()
    cfg_bytes = b'{"peft_type": "LORA", "r": 8}'
    w_bytes = b"fake-safetensors-payload"
    (adapter_dir / "adapter_config.json").write_bytes(cfg_bytes)
    (adapter_dir / "adapter_model.safetensors").write_bytes(w_bytes)
    cfg_sha = hashlib.sha256(cfg_bytes).hexdigest()
    w_sha = hashlib.sha256(w_bytes).hexdigest()

    base_settings = ModelSettings(
        model_id="m",
        model_revision="r",
        embedding_id="e",
        embedding_revision="er",
        cache_dir=str(tmp_path / "cache"),
        adapter_path=str(adapter_dir),
        adapter_sha256=w_sha,
        adapter_config_sha256=cfg_sha,
        adapter_scopes=["extract", "relations"],
    )
    assert verify_adapter_dir(adapter_dir, base_settings) == (
        adapter_dir / "adapter_model.safetensors"
    )
    with pytest.raises(ModelRuntimeError):
        verify_adapter_dir(adapter_dir, base_settings.model_copy(update={"adapter_sha256": "bad"}))
    with pytest.raises(ModelRuntimeError):
        verify_adapter_dir(
            adapter_dir, base_settings.model_copy(update={"adapter_config_sha256": "bad"})
        )

    assert task_for_prompt(COMPACT_EXTRACTION_PROMPT) == "extract"
    assert task_for_prompt(RELATION_PROMPT) == "relations"
    assert task_for_prompt("other writer prompt") == "default"
    assert adapter_active_for(base_settings, COMPACT_EXTRACTION_PROMPT) is True
    assert adapter_active_for(base_settings, RELATION_PROMPT) is True
    assert adapter_active_for(base_settings, "other writer prompt") is False
    assert (
        adapter_active_for(
            base_settings.model_copy(update={"adapter_scopes": ["all"]}), "other writer prompt"
        )
        is True
    )

    no_adapter = base_settings.model_copy(
        update={"adapter_path": None, "adapter_sha256": None, "adapter_config_sha256": None}
    )
    s_with = ModelSession(tmp_path / "a.log", base_settings)
    s_without = ModelSession(tmp_path / "b.log", no_adapter)
    # Inactive task must resolve to identical base cache key; active task must stay isolated.
    assert s_with._cache_keys("other writer prompt", {"k": 1}, False) == s_without._cache_keys(
        "other writer prompt", {"k": 1}, False
    )
    assert s_with._cache_keys(COMPACT_EXTRACTION_PROMPT, {"k": 1}, True)[0] != (
        s_without._cache_keys(COMPACT_EXTRACTION_PROMPT, {"k": 1}, False)[0]
    )
