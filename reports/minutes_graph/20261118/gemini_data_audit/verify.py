"""Replay Minda's current Gemini pilot against the production graph contracts."""

import argparse
from copy import deepcopy
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
from statistics import median
import subprocess
from tempfile import TemporaryDirectory

import numpy as np
from transformers import AutoTokenizer

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.graph_builder import COMPACT_EXTRACTION_PROMPT, RELATIONS, build_graph, extract_events, validate_graph, unit_row
from meeting_pipeline.minutes.graph_contracts import FACT_FIELDS, digest
from meeting_pipeline.minutes.graph_inputs import contextual_texts, make_graph_units
from meeting_pipeline.minutes.graph_relations import RELATION_PROMPT, connect_events
from meeting_pipeline.minutes.graph_state import STATE_RELATIONS
from meeting_pipeline.minutes.model_runtime import ModelSession, ROOT, load_model_settings


PROMPTS = {"extract": COMPACT_EXTRACTION_PROMPT, "relations": RELATION_PROMPT}
SPLITS = ("train", "dev", "test")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def tokenize_stats(messages, tokenizer):
    prefix = tokenizer.apply_chat_template(messages[:2], tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    prompt_ids = tokenizer.encode(prefix, add_special_tokens=False)
    full_ids = tokenizer.encode(full, add_special_tokens=False)
    assert full_ids[:len(prompt_ids)] == prompt_ids
    answer_ids = full_ids[len(prompt_ids):]
    assert answer_ids and tokenizer.eos_token_id in answer_ids
    return {"prompt": len(prompt_ids), "assistant": len(answer_ids), "total": len(full_ids)}


def normalized_payload(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def read_export(source, cases, families, tokenizer, settings):
    index = read_jsonl(source / "export_index.jsonl")
    manifest = json.loads((source / "split_manifest.json").read_text())
    files = {f"{split}/{step}.jsonl": read_jsonl(source / f"{split}/{step}.jsonl")
             for split in SPLITS for step in PROMPTS}
    expected_keys = {(path, i) for path, rows in files.items() for i in range(1, len(rows) + 1)}
    visible_keys = [(entry["file"], entry["line_number"]) for entry in index]
    assert len(visible_keys) == len(set(visible_keys))
    assert manifest["prompts"]["extract_sha256"] == digest(PROMPTS["extract"])[:16]
    assert manifest["prompts"]["relations_sha256"] == digest(PROMPTS["relations"])[:16]
    assert set(visible_keys) == expected_keys

    for split in SPLITS:
        declared = manifest["splits"][split]
        assert set(declared["families"]) == {k for k, f in families.items() if f["split"] == split}
        assert set(declared["accepted_cases"]) == {k for k, c in cases.items() if c["split"] == split}
        assert declared["extract_samples"] == len(files[f"{split}/extract.jsonl"])
        assert declared["relation_samples"] == len(files[f"{split}/relations.jsonl"])

    grouped = defaultdict(list)
    identical_inputs = defaultdict(list)
    tokens_by_step = defaultdict(list)
    for row in sorted(index, key=lambda e: (e["case_id"], e["step"], e["batch_index"])):
        case = cases[row["case_id"]]
        step = row["step"]
        stored_samples = case["extract_samples" if step == "extract" else "relation_samples"]
        assert row["family_id"] == case["family_id"] and row["split"] == case["split"]
        assert row["file"] == f"{case['split']}/{step}.jsonl"
        assert len(grouped[(row["case_id"], step)]) == row["batch_index"]
        saved = stored_samples[row["batch_index"]]
        stored_line = files[row["file"]][row["line_number"] - 1]
        assert set(stored_line) == {"messages"}
        messages = stored_line["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "assistant"]
        assert all(set(m) == {"role", "content"} and isinstance(m["content"], str) for m in messages)
        assert messages[0]["content"] == PROMPTS[step]
        payload = json.loads(messages[1]["content"])
        target = json.loads(messages[2]["content"])
        assert payload == saved["payload"] and target == saved["target"]
        assert set(payload) == ({"units", "context"} if step == "extract" else {"events", "context"})
        assert set(target) == ({"items"} if step == "extract" else {"relations"})
        token_data = tokenize_stats(messages, tokenizer)
        assert token_data["prompt"] <= settings.input_token_budget
        assert token_data["assistant"] <= settings.output_token_budget
        tokens_by_step[step].append(token_data)
        grouped[(row["case_id"], step)].append((messages, saved))
        identical_inputs[(step, normalized_payload(payload))].append((row, target))

    duplicate_groups = []
    conflicting_duplicate_groups = []
    cross_split_duplicates = []
    for copies in identical_inputs.values():
        if len(copies) == 1:
            continue
        entries = [r for r, _ in copies]
        duplicate_groups.append(entries)
        if len({r["split"] for r in entries}) > 1:
            cross_split_duplicates.append(entries)
        if any(y != copies[0][1] for _, y in copies):
            conflicting_duplicate_groups.append(entries)

    for case_id, case in cases.items():
        assert len(grouped[(case_id, "extract")]) == len(case["extract_samples"])
        assert len(grouped[(case_id, "relations")]) == len(case["relation_samples"])

    return grouped, {
        "rows": {name: len(rows) for name, rows in files.items()},
        "duplicate_groups": duplicate_groups,
        "cross_split_duplicate_groups": cross_split_duplicates,
        "conflicting_duplicate_groups": conflicting_duplicate_groups,
        "token_counts": {
            step: {field: [min(x[field] for x in rows), median(x[field] for x in rows), max(x[field] for x in rows)]
                   for field in ("prompt", "assistant", "total")}
            for step, rows in tokens_by_step.items()
        },
        "assistant_templates_passed": len(index),
    }


def units_from_case(case):
    turns, sessions = [], {}
    for i, turn in enumerate(case["turns"]):
        uid = turn["turn_id"]
        assert uid not in sessions
        sessions[uid] = turn["session_id"]
        turns.append(IndexedTurn(
            turn_id=uid, speaker_label=turn["speaker"], speaker_id=turn.get("speaker_id"),
            start_sec=turn.get("start_sec", i * 12.0), end_sec=turn.get("end_sec", i * 12.0 + 10.0),
            text=turn["text"], tokens=[], source_id=turn.get("source_id", "primary"), clip_path=None,
            asr_status=turn["asr_status"], needs_review=turn.get("needs_review", False), confidence=None,
            session_id=turn["session_id"],
        ))
    units, excluded = make_graph_units(turns, {"turn_sessions": sessions})
    return units, excluded


class Replay:
    def __init__(self, settings, tokenizer, temp):
        self.settings = settings
        self.tokenizer = tokenizer
        self.parser = ModelSession(temp / "parser.log", settings)
        self.packets = iter(())
        self.saw = 0

    def load_packets(self, packets):
        self.packets = iter(packets)

    def token_count(self, text):
        return len(self.tokenizer.encode(text))

    def generate_json(self, prompt, payload):
        messages, _ = next(self.packets)
        assert prompt == messages[0]["content"] and payload == json.loads(messages[1]["content"])
        self.saw += 1
        return self.parser.generate_json(
            prompt, payload, _result={"text": messages[2]["content"], "finish_reason": "stop"}
        )

    def check_consumed(self):
        assert next(self.packets, None) is None


def verify_states(case, events_by_key):
    checks = 0
    for row in case["expected_state"]:
        event = events_by_key[row["event_key"]]
        for k, expected in row.items():
            if k in {"note", "event_key"}:
                continue
            checks += 1
            if k.startswith("effective_") and k.endswith("_source_key"):
                field = k.removeprefix("effective_").removesuffix("_source_key")
                source = events_by_key[expected]
                anchor = event.current_evidence(field)
                assert anchor and anchor.unit_id == source.unit_ids[0], (case["case_id"], row)
                if field in event.amendments:
                    assert event.amendments[field].source_event_id == source.event_id
                continue
            if k.startswith("effective_"):
                actual = event.current_value(k.removeprefix("effective_"))
            else:
                actual = getattr(event, k.removeprefix("original_") if k != "session" else "session_id")
            assert actual == expected, (case["case_id"], k, actual, expected)
    return checks


def make_graph(case_id, units, events, relations):
    return build_graph(
        case_id, units, events, {"titles": ["Nội dung"], "primary": [0] * len(units),
        "membership": [[1.0]] * len(units)}, relations,
    )


def replay_case(case, grouped, session):
    case_id = case["case_id"]
    units, excluded = units_from_case(case)
    assert not excluded and len(units) == case["unit_count"], case_id
    source_by_id = {t["turn_id"]: t["text"] for t in case["turns"]}
    by_unit = {unit.unit_id: unit for unit in units}
    for u in units:
        for span in u.sources:
            assert source_by_id[span.turn_id][span.start_char:span.end_char] == span.text
    session.load_packets(grouped[(case_id, "extract")])
    events, inline, warnings = extract_events(session, units)
    session.check_consumed()
    assert not warnings and not inline and len(events) == case["event_count"], case_id
    observed = {(e.unit_ids[0], e.text): e for e in events}
    event_id_by_key = {}
    for expected in case["mapped_events"]:
        unit = by_unit[expected["unit_id"]]
        assert unit.turn_id == expected["turn_id"]
        start, end = expected["start_char_in_unit"], expected["end_char_in_unit"]
        assert unit.original[start:end] == expected["text"]
        event = observed[(unit.unit_id, expected["text"])]
        assert event.extraction == "model" and not event.warnings
        assert event.kind == expected["kind"] and event.issue == expected["issue"]
        assert event.anchor and event.anchor.start_char == start and event.anchor.end_char == end
        for field in FACT_FIELDS:
            assert getattr(event, field) == expected[field]
            if expected[field] is not None:
                anchor = event.field_evidence[field]
                assert unit.original[anchor.start_char:anchor.end_char] == anchor.quote
        event_id_by_key[expected["event_key"]] = event.event_id

    packets = grouped[(case_id, "relations")]
    session.load_packets(packets)
    relations = connect_events(session, events, inline, units)
    session.check_consumed()
    assert len(relations) == case["relation_count"]
    expected_edges = Counter()
    for messages, saved in packets:
        reverse = {alias: event_id for event_id, alias in saved["aliases"].items()}
        for r in json.loads(messages[2]["content"])["relations"]:
            expected_edges[reverse[r["source"]], reverse[r["target"]], r["kind"], r["field"]] += 1
    assert Counter((r["source"], r["target"], r["kind"], r["field"]) for r in relations) == expected_edges
    graph = make_graph(case_id, units, events, relations)
    assert not validate_graph(graph) and not graph.warnings, case_id
    actual_edges = Counter((r.source, r.target, r.kind, r.field) for r in graph.edges
                           if r.asserted and r.kind in RELATIONS)
    assert actual_edges == expected_edges, case_id
    events_by_id = {e.event_id: e for e in graph.events}
    events_by_key = {key: events_by_id[event_id] for key, event_id in event_id_by_key.items()}
    counts = {
        "events": len(events), "facts": sum(len(event.field_evidence) for event in events),
        "relations": len(relations), "state_edges": sum(r.kind in STATE_RELATIONS and r.asserted for r in graph.edges),
        "state_rows": len(case["expected_state"]), "checks": verify_states(case, events_by_key),
        "multi_event_units": sum(count > 1 for count in Counter(e.unit_ids[0] for e in events).values()),
    }
    graph_events = {event.event_id: event for event in graph.events}
    conditional_edges = []
    for relation in relations:
        source = graph_events[relation["source"]]
        if relation["kind"] in STATE_RELATIONS and source.condition:
            target = graph_events[relation["target"]]
            conditional_edges.append({
                "case_id": case_id, "kind": relation["kind"],
                "condition": source.condition, "source_quote": relation["anchors"][0]["quote"],
                "target_lifecycle": target.lifecycle,
            })
    return counts, units, events, events_by_key, conditional_edges


class Capture:
    def __init__(self, replay):
        self.settings = replay.settings
        self.token_count = replay.token_count
        self.payloads = []

    def generate_json(self, system, payload):
        self.payloads.append(payload)
        if system == COMPACT_EXTRACTION_PROMPT:
            return {"items":[[unit["unit_id"], "information"] for unit in payload["units"]]}
        return {"relations": []}


def production_vectors(long_cases, settings):
    job = [{"op": "embed", "texts": contextual_texts(units)} for _, units in long_cases]
    script = ROOT / "scripts/minutes_model_worker.py"
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
               HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
    proc = subprocess.run([
        str(ROOT / settings.runtime_python), str(script), "--config", str(ROOT / "configs/minutes.yaml"),
    ], input="".join(json.dumps(j, ensure_ascii=False) + "\n" for j in job),
        text=True, capture_output=True, env=env, cwd=ROOT, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(f'Embedding worker exited {proc.returncode}: {proc.stderr[-1500:]}')
    ready, *responses = map(json.loads, proc.stdout.splitlines())
    assert ready["ready"] and len(responses) == len(job), (ready, responses)
    vectors = {}
    for (case_id, units), response in zip(long_cases, responses, strict=True):
        assert "vectors" in response, response
        x = np.asarray(response["vectors"], dtype=float)
        assert x.shape[0] == len(units) and np.isfinite(x).all()
        norm = np.linalg.norm(x, axis=1, keepdims=True)
        assert np.all(norm > 1e-12)
        vectors[case_id] = x / norm
    return vectors


def turn_ids(payload, key, units):
    ids = {normalized_payload({k:v for k,v in unit_row(unit).items() if k != "unit_id"}): unit.turn_id
           for unit in units}
    return [ids[normalized_payload({k: v for k, v in row.items() if k != "unit_id"})] for row in payload[key]]


def audit_production_context(cases, long_cases, replay):
    vectors = production_vectors([(case_id, units) for case_id, units, _ in long_cases], load_model_settings())
    changes = []
    for case_id, units, expected_events in long_cases:
        capture = Capture(replay)
        extract_events(capture, units, vectors[case_id])
        exported = cases[case_id]["extract_samples"]
        remapped_packets = []
        for batch_num, (saved, actual) in enumerate(zip(exported, capture.payloads, strict=True)):
            previous = saved["payload"]
            assert turn_ids(previous, "units", units) == turn_ids(actual, "units", units)
            old_ids = [row["unit_id"] for row in previous["units"]]
            new_ids = [row["unit_id"] for row in actual["units"]]
            aliases = dict(zip(old_ids, new_ids, strict=True))
            target = deepcopy(saved["target"])
            for item in target["items"]:
                assert len(item) == 2 or not {"relations", "evidence_unit_ids"} & item[2].keys()
                item[0] = aliases[item[0]]
            messages = [
                {"role": "system", "content": COMPACT_EXTRACTION_PROMPT},
                {"role": "user", "content": json.dumps(actual, ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
            ]
            remapped_packets.append((messages, None))
            if previous == actual:
                continue
            changes.append({
                "case_id": case_id, "batch": batch_num,
                "exported_context": turn_ids(previous, "context", units),
                "production_context": turn_ids(actual, "context", units),
                "exported_aliases": old_ids, "production_aliases": new_ids,
            })
        replay.load_packets(remapped_packets)
        repacked_events, inline, warnings = extract_events(replay, units, vectors[case_id])
        replay.check_consumed()
        assert repacked_events == expected_events and not inline and not warnings, case_id
    return changes


def issue_anchor_counterfactual(case_id, units, events, keyed, replay):
    source, target = (keyed[key] for key in ("e13", "e1"))
    original = Capture(replay)
    connect_events(original, events, [], units)
    changes = {source.event_id, target.event_id}
    titled = [e.model_copy(update={"issue": "gửi biên bản bàn giao kho"}) if e.event_id in changes else e
              for e in events]
    case_labels = Capture(replay)
    connect_events(case_labels, titled, [], units)

    def target_present(payload):
        return any(row["text"] == target.text for row in payload["context"])

    assert not target_present(original.payloads[-1]) and target_present(case_labels.payloads[-1])
    return {
        "case_id": case_id, "old_task_in_final_relation_context_with_exported_issues": False,
        "old_task_in_final_relation_context_with_grounded_issues": True,
    }


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("data", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    source = args.data.resolve()
    case_rows = read_jsonl(source / "cases.jsonl")
    cases = {r["case_id"]: r for r in case_rows}
    rejected = read_jsonl(source / "rejected.jsonl")
    family_rows = read_jsonl(source / "scenarios.jsonl")
    families = {f["family_id"]: f for f in family_rows}
    assert len(cases) == len(case_rows) and len(families) == len(family_rows)
    all_rows = {c["case_id"]: c for c in [*case_rows, *rejected]}
    for case in all_rows.values():
        assert case["split"] == families[case["family_id"]]["split"]
        if case["variant_of"]:
            assert all_rows[case["variant_of"]]["family_id"] == case["family_id"]
    split_counts = {
        split: {"families": sum(row["split"] == split for row in families.values()),
                "cases": sum(row["split"] == split for row in cases.values())}
        for split in SPLITS
    }

    settings = load_model_settings()
    tokenizer = AutoTokenizer.from_pretrained(settings.snapshot(), local_files_only=True)
    packets, export = read_export(source, cases, families, tokenizer, settings)
    total = Counter()
    details, long_cases, conditional_edges = {}, [], []
    with TemporaryDirectory(prefix="minda-data-replay-") as directory:
        temp = Path(directory)
        replay = Replay(settings.model_copy(update={"cache_dir": str(temp), "response_cache": False}),
                        tokenizer, temp)
        for case_id, case in cases.items():
            counts, units, events, keyed, conditions = replay_case(case, packets, replay)
            conditional_edges.extend(conditions)
            total.update(counts)
            details[case_id] = counts
            if len(units) > settings.extraction_batch_size:
                long_cases.append((case_id, units, events))
            if case_id == "case_mm_02_out_of_window":
                counterfactual = issue_anchor_counterfactual(case_id, units, events, keyed, replay)
            print(case_id, json.dumps(counts), flush=True)
        assert replay.saw == sum(export["rows"].values())
        context_changes = audit_production_context(cases, long_cases, replay)

    units_per_case = [len(c["turns"]) for c in case_rows]
    texts = [len(t["text"].split()) for c in case_rows for t in c["turns"]]
    conclusions = {
        "splits": split_counts, "export": export,
        "runtime_replay": {"cases": len(cases), "total": dict(total), "each_case": details},
        "production_context_mismatches": context_changes,
        "issue_anchor_counterfactual": counterfactual,
        "changed_extract_batches_replayed_after_alias_remap": len(context_changes),
        "conditional_state_edge_quotes": conditional_edges,
        "stored_timestamps": sum("start_sec" in t and "end_sec" in t for c in case_rows for t in c["turns"]),
        "turns_per_case_min_median_max": [min(units_per_case), median(units_per_case), max(units_per_case)],
        "max_whitespace_words_per_turn": max(texts),
        "rejected": [r["case_id"] for r in rejected],
        "sha256": {filename: sha256((source / filename).read_bytes()).hexdigest()
                   for filename in ("cases.jsonl", "scenarios.jsonl", "split_manifest.json", "export_index.jsonl", "rejected.jsonl", *export["rows"])},
    }
    args.output.write_text(json.dumps(conclusions, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"runtime": dict(total), "rows": export["rows"], "tokens": export["token_counts"],
                     "context_changes": context_changes, "anchor_test": counterfactual}, ensure_ascii=False))


if __name__ == "__main__":
    main()
