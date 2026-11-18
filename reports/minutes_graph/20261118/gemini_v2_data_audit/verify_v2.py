"""Audit frozen Gemini v2 data independently of its exporter."""

import argparse
import ast
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import median
from tempfile import TemporaryDirectory

import numpy as np
from transformers import AutoTokenizer

from verify import (
    Capture, Replay, make_graph, production_vectors, tokenize_stats, turn_ids, units_from_case, verify_states,
)
from meeting_pipeline.minutes.graph_builder import COMPACT_EXTRACTION_PROMPT, RELATIONS, extract_events, validate_graph
from meeting_pipeline.minutes.graph_contracts import FACT_FIELDS, digest
from meeting_pipeline.minutes.graph_relations import RELATION_PROMPT, connect_events
from meeting_pipeline.minutes.graph_state import STATE_RELATIONS
from meeting_pipeline.minutes.model_runtime import load_model_settings

SPLITS = ("train", "dev", "test")
PROMPTS = {"extract": COMPACT_EXTRACTION_PROMPT, "relations": RELATION_PROMPT}
TEST_BATCHES = {
    "extract": ("test/inputs/extract_inputs.jsonl", "test/references/extract_targets.jsonl"),
    "relations": ("test/inputs/relations_gold_events_inputs.jsonl", "test/references/relations_targets.jsonl"),
}
SLOT_KEYS = {
    "issue", "issue1", "issue2", "prop", "optA", "optB", "propA", "propB", "mgr",
    "a1", "a2", "a3", "owner", "d1", "d2", "d1_new", "d2_new", "ver1", "ver2",
    "cond", "cond1", "cond1_new", "t1", "t2", "reason_opp",
}


def key(row):
    return row["case_id"], row["batch_index"]


def packet_key(row):
    return row["case_id"], row["step"], row["batch_index"]


def canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def unique_by(rows, id_of):
    mapping = {id_of(row): row for row in rows}
    assert len(mapping) == len(rows)
    return mapping


def load_bundle(root):
    names = {
        "split_manifest.json", "train_manifest.json", "scenarios.jsonl", "export_index.jsonl",
        "rejected.jsonl", "review_requests.jsonl", "review_results.jsonl",
        "test/inputs/transcripts.jsonl", "test/references/cases.jsonl",
        *(f"{split}/cases.jsonl" for split in SPLITS),
        *(f"{split}/{step}.jsonl" for split in ("train", "dev") for step in PROMPTS),
        *(p for paths in TEST_BATCHES.values() for p in paths),
    }
    data, hashes = {}, {}
    for name in sorted(names):
        raw = (root / name).read_bytes()
        hashes[name] = sha256(raw).hexdigest()
        data[name] = ([json.loads(line) for line in raw.splitlines()]
                      if name.endswith(".jsonl") else json.loads(raw))
    return data, hashes


def audit_manifests(data, hashes):
    manifest, train = data["split_manifest.json"], data["train_manifest.json"]
    assert train["split"] == "train"
    assert {row["path"] for row in train["files"]} == {"train/extract.jsonl", "train/relations.jsonl"}
    for row in train["files"]:
        assert hashes[row["path"]] == row["sha256"]
        assert len(data[row["path"]]) == row["num_lines"]
    for filename, expected in manifest["locked_hashes"].items():
        assert hashes[filename] == expected, filename
    assert manifest["prompts"] == {
        "extract_sha256": digest(COMPACT_EXTRACTION_PROMPT)[:16],
        "relations_sha256": digest(RELATION_PROMPT)[:16],
    }
    cases = unique_by([c for split in SPLITS for c in data[f"{split}/cases.jsonl"]], lambda c: c["case_id"])
    families = unique_by(data["scenarios.jsonl"], lambda c: c["family_id"])
    ids_by_split = {split: set(ids) for split, ids in manifest["splits"].items()}
    assert sum(len(ids) for ids in ids_by_split.values()) == len(families)
    assert set.union(*ids_by_split.values()) == set(families)
    for split in SPLITS:
        assert ids_by_split[split] == {r["family_id"] for r in data[f"{split}/cases.jsonl"]}
        for case in data[f"{split}/cases.jsonl"]:
            fid = case["family_id"]
            assert case["split"] == families[fid]["split"] == split
            if case["variant_of"]:
                assert cases[case["variant_of"]]["family_id"] == fid
    assert len({row["meeting_id"] for row in cases.values()}) == len(cases)
    assert data["test/references/cases.jsonl"] == data["test/cases.jsonl"]
    test_source = unique_by(data["test/inputs/transcripts.jsonl"], lambda c: c["case_id"])
    assert set(test_source) == {c["case_id"] for c in data["test/cases.jsonl"]}
    for cid, transcript in test_source.items():
        assert set(transcript) == {"case_id", "family_id", "meeting_mode", "domain", "turns"}
        assert transcript["turns"] == cases[cid]["turns"]
        assert transcript["family_id"] == cases[cid]["family_id"]
    return cases


def inspect_packets(data, cases, tokenizer, settings):
    file_steps = {
        **{f"{s}/{t}.jsonl": t for s in ("train", "dev") for t in PROMPTS},
        **{paths[0]: step for step, paths in TEST_BATCHES.items()},
    }
    expected_positions = {(f, i) for f in file_steps for i in range(1, len(data[f]) + 1)}
    positions = unique_by(data["export_index.jsonl"], lambda x: (x["file"], x["line_number"]))
    assert set(positions) == expected_positions
    review_inputs = unique_by(data["review_requests.jsonl"], packet_key)
    review_outputs = unique_by(data["review_results.jsonl"], packet_key)
    test_refs = {step: unique_by(data[paths[1]], key) for step, paths in TEST_BATCHES.items()}
    assert all(set(rows) == {key(r) for r in data[TEST_BATCHES[step][0]]}
               for step, rows in test_refs.items())

    packets = defaultdict(list)
    identical = defaultdict(list)
    token_data = defaultdict(list)
    checked_reviews = set()
    for (filename, lineno), index in sorted(positions.items(), key=lambda item: (
            item[1]["case_id"], item[1]["step"], item[1]["batch_index"])):
        row = data[filename][lineno - 1]
        case = cases[index["case_id"]]
        step, batch = file_steps[filename], index["batch_index"]
        assert index["family_id"] == case["family_id"] and index["split"] == case["split"]
        assert filename.split("/")[0] == case["split"]
        assert len(packets[(case["case_id"], step)]) == batch
        sample = case["extract_samples" if step == "extract" else "relation_samples"][batch]
        assert sample["batch_index"] == batch
        if case["split"] == "test":
            assert key(row) == (index["case_id"], batch)
            assert set(row) == {"case_id", "batch_index", "mode", "system", "user"}
            assert row["mode"] == ("end_to_end_extract" if step == "extract" else "relations_from_gold_events")
            ref = test_refs[step][key(row)]
            assert set(ref) == {"case_id", "batch_index", "target"}
            messages = [
                {"role": "system", "content": row["system"]},
                {"role": "user", "content": json.dumps(row["user"], ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(ref["target"], ensure_ascii=False)},
            ]
        else:
            assert set(row) == {"messages"}
            messages = row["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "assistant"]
        assert all(set(m) == {"role", "content"} and isinstance(m["content"], str) for m in messages)
        assert messages[0]["content"] == PROMPTS[step]
        payload, target = (json.loads(m["content"]) for m in messages[1:])
        assert (payload, target) == (sample["payload"], sample["target"])
        assert set(payload) == ({"context", "units"} if step == "extract" else {"context", "events"})
        assert set(target) == ({"items"} if step == "extract" else {"relations"})
        tokens = tokenize_stats(messages, tokenizer)
        assert tokens["prompt"] <= settings.input_token_budget
        assert tokens["assistant"] <= settings.output_token_budget
        token_data[(case["split"], step)].append(tokens)
        packets[(case["case_id"], step)].append((messages, sample))
        identical[(step, canonical(payload))].append((index, target))
        review_key = (case["case_id"], step, batch)
        request, result = review_inputs[review_key], review_outputs[review_key]
        assert set(request) == {"case_id", "split", "step", "batch_index", "input"}
        assert request["input"] == payload and request["split"] == result["split"] == case["split"]
        checked_reviews.add(review_key)

    assert checked_reviews == set(review_inputs) == set(review_outputs)
    for case in cases.values():
        assert len(packets[(case["case_id"], "extract")]) == len(case["extract_samples"])
        assert len(packets[(case["case_id"], "relations")]) == len(case["relation_samples"])
    dup_groups = [group for group in identical.values() if len(group) > 1]
    conflicts = [group for group in dup_groups if any(target != group[0][1] for _, target in group)]
    cross = [group for group in dup_groups if len({idx["split"] for idx, _ in group}) > 1]
    return packets, {
        "rows": {n: len(data[n]) for n in file_steps},
        "verified_chat_templates": len(positions),
        "identical_payload_groups": len(dup_groups),
        "conflicting_identical_payload_groups": len(conflicts),
        "cross_split_identical_payload_groups": len(cross),
        "awaiting_independent_review_batches": sum(x["awaiting_independent_llm_review"] for x in review_outputs.values()),
        "token_counts": {
            f"{split}/{step}": {field: [min(d[field] for d in rows), median(d[field] for d in rows),
                                        max(d[field] for d in rows)]
                                for field in ("prompt", "assistant", "total")}
            for (split, step), rows in token_data.items()
        },
    }


def generated_vectors(root, units, settings):
    if len(units) <= settings.extraction_batch_size:
        return None
    query = json.dumps([unit.text for unit in units], ensure_ascii=False)
    path = root / "cache" / f"e5_{sha256(query.encode()).hexdigest()[:24]}.json"
    vectors = np.asarray(json.loads(path.read_text()), dtype=float)
    assert vectors.shape == (len(units), 384) and np.isfinite(vectors).all()
    return vectors


def cuts_a_word(quote, event_text):
    left = event_text.index(quote)
    right = left + len(quote)
    return (
        left > 0 and event_text[left - 1].isalnum() and quote[0].isalnum()
        or right < len(event_text) and event_text[right].isalnum() and quote[-1].isalnum()
    )


def replay_case(root, case, packs, session, production):
    cid = case["case_id"]
    units, excluded = units_from_case(case)
    assert not excluded and len(units) == case["unit_count"], cid
    by_turn = {turn["turn_id"]: turn["text"] for turn in case["turns"]}
    for unit in units:
        for span in unit.sources:
            assert by_turn[span.turn_id][span.start_char:span.end_char] == span.text, cid
    is_long = len(units) > session.settings.extraction_batch_size
    vectors = generated_vectors(root, units, session.settings)
    session.load_packets(packs[(cid, "extract")])
    events, inline, warnings = extract_events(session, units, vectors)
    session.check_consumed()
    assert len(events) == case["event_count"] and not inline and not warnings, cid

    unit_by_id = {u.unit_id: u for u in units}
    keyed = {}
    for ev in events:
        primary = unit_by_id[ev.unit_ids[0]]
        matches = [g for g in case["gold_events"]
                   if g["turn_id"] == primary.turn_id and ev.text == (g["excerpt"] or primary.text)]
        assert len(matches) == 1, (cid, ev)
        raw = matches[0]
        assert ev.kind == raw["kind"] and ev.issue == raw["issue"], (cid, ev)
        assert ev.extraction == "model" and not ev.warnings and ev.anchor, (cid, ev)
        for field in FACT_FIELDS:
            assert getattr(ev, field) == raw[field], (cid, ev, field)
            if raw[field] is not None:
                anchor = ev.field_evidence[field]
                assert primary.original[anchor.start_char:anchor.end_char] == anchor.quote, (cid, ev, field)
        keyed[raw["event_key"]] = ev
    assert set(keyed) == {g["event_key"] for g in case["gold_events"]}, cid
    by_id = {event.event_id: k for k, event in keyed.items()}

    session.load_packets(packs[(cid, "relations")])
    relations = connect_events(session, events, inline, units)
    session.check_consumed()
    assert len(relations) == case["relation_count"], cid
    missing = {(r["source_key"], r["target_key"], r["kind"]) for r in case["missing_target_in_window"]}
    expected = Counter()
    for r in case["gold_relations"]:
        if (r["source_key"], r["target_key"], r["kind"]) in missing:
            continue
        expected[(r["source_key"], r["target_key"], r["kind"], r["field"], r["source_quote"], r["target_quote"])] += 1
    actual = Counter((by_id[r["source"]], by_id[r["target"]], r["kind"], r.get("field"),
                      *[a["quote"] for a in r["anchors"]]) for r in relations)
    assert not actual - expected, (cid, actual - expected)
    unanchored = expected - actual
    bad_quotes = []
    for a, b, kind, field, sq, tq in unanchored.elements():
        bad_quotes.append({"case_id": cid, "split": case["split"], "kind": kind,
                           "source_quote": sq, "target_quote": tq,
                           "cut_inside_word": cuts_a_word(sq, keyed[a].text) or cuts_a_word(tq, keyed[b].text)})
    repaired_count, bad_batches = 0, 0
    if unanchored:
        needs_repair = {(kind, field, sq, tq) for _, _, kind, field, sq, tq in unanchored}
        fixed = []
        for msgs, _ in packs[(cid, "relations")]:
            payload, target = (json.loads(msg["content"]) for msg in msgs[1:])
            events_by_alias = {row["id"]: row for row in payload["context"] + payload["events"]}
            affected = False
            for r in target["relations"]:
                k = (r["kind"], r.get("field"), r["source_quote"], r["target_quote"])
                if k in needs_repair:
                    r["source_quote"] = events_by_alias[r["source"]]["text"]
                    r["target_quote"] = events_by_alias[r["target"]]["text"]
                    affected = True
            bad_batches += affected
            fixed.append(([msgs[0], msgs[1],
                           {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)}], None))
        repair = Replay(session.settings, session.tokenizer, Path(session.settings.cache_dir))
        repair.load_packets(fixed)
        restored = connect_events(repair, events, inline, units)
        repair.check_consumed()
        assert Counter((by_id[r["source"]], by_id[r["target"]], r["kind"], r.get("field"))
                       for r in restored) == Counter(k[:4] for k in expected.elements()), cid
        repaired_count = len(restored) - len(relations)
    graph = make_graph(cid, units, events, relations)
    assert not validate_graph(graph) and not graph.warnings, (cid, graph.warnings)
    final_edges = Counter((by_id[r.source], by_id[r.target], r.kind, r.field)
                          for r in graph.edges if r.asserted and r.kind in RELATIONS)
    assert final_edges == Counter(k[:4] for k in actual.elements()), cid
    final_nodes = {by_id[ev.event_id]: ev for ev in graph.events}

    partial_quotes = []
    condition_omissions = []
    for source, target, kind, field, sq, tq in actual.elements():
        s, t = final_nodes[source], final_nodes[target]
        if cuts_a_word(sq, s.text) or cuts_a_word(tq, t.text):
            partial_quotes.append({"case_id": cid, "split": case["split"], "kind": kind,
                                   "source_quote": sq, "target_quote": tq})
        if kind in STATE_RELATIONS and s.condition and s.condition not in sq:
            condition_omissions.append({"case_id": cid, "split": case["split"], "kind": kind,
                                        "condition": s.condition, "source_quote": sq, "target_lifecycle": t.lifecycle})

    context_changes, absent_visible = [], 0
    if is_long:
        assert cid in production, cid
        cap = Capture(session)
        extract_events(cap, units, production[cid])
        repacked = []
        for (msgs, sample), new in zip(packs[(cid, "extract")], cap.payloads, strict=True):
            old = sample["payload"]
            old_ids = [u["unit_id"] for u in old["units"]]
            new_ids = [u["unit_id"] for u in new["units"]]
            alias_map = dict(zip(old_ids, new_ids, strict=True))
            target = json.loads(msgs[2]["content"])
            for item in target["items"]:
                assert len(item) == 2 or not {"relations", "evidence_unit_ids"} & item[2].keys(), cid
                item[0] = alias_map[item[0]]
            repacked.append(([msgs[0], {"role": "user", "content": json.dumps(new, ensure_ascii=False)},
                              {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)}], None))
            if old != new:
                assert turn_ids(old, "units", units) == turn_ids(new, "units", units), cid
                context_changes.append({
                    "case_id": cid, "split": case["split"], "batch_index": sample["batch_index"],
                    "exported_context": turn_ids(old, "context", units),
                    "production_context": turn_ids(new, "context", units),
                    "aliases_changed": old_ids != new_ids,
                    "exported_aliases": old_ids, "production_aliases": new_ids,
                })
        if context_changes:
            repair = Replay(session.settings, session.tokenizer, Path(session.settings.cache_dir))
            repair.load_packets(repacked)
            after_events, after_inline, after_warnings = extract_events(repair, units, production[cid])
            repair.check_consumed()
            assert after_events == events and not after_inline and not after_warnings, cid
        for miss in case["missing_target_in_window"]:
            target_turn = unit_by_id[keyed[miss["target_key"]].unit_ids[0]].turn_id
            source_turn = unit_by_id[keyed[miss["source_key"]].unit_ids[0]].turn_id
            for payload in cap.payloads:
                if source_turn in turn_ids(payload, "units", units) and target_turn in turn_ids(payload, "context", units):
                    absent_visible += 1

    facts = sum(len(ev.field_evidence) for ev in events)
    counts = {
        "cases": 1, "units": len(units), "events": len(events), "facts": facts,
        "relations": len(relations), "state_edges": sum(r.kind in STATE_RELATIONS and r.asserted for r in graph.edges),
        "state_checks": verify_states(case, final_nodes),
        "multi_event_units": sum(k > 1 for k in Counter(e.unit_ids[0] for e in events).values()),
        "multi_batch_extraction_cases": int(is_long),
        "retrieved_missing_relation_targets_in_extraction": absent_visible,
        "relation_labels_exported": sum(expected.values()),
        "unanchored_relation_labels": sum(unanchored.values()),
        "unanchored_relation_cases": int(bool(unanchored)),
        "unanchored_relation_batches": bad_batches,
        "restored_relations_from_full_quotes": repaired_count,
    }
    return counts, context_changes, partial_quotes, condition_omissions, bad_quotes


def scenario_slot_values(root):
    tree = ast.parse((root / "scripts/scenarios_bank.py").read_text())
    rows = []
    for statement in tree.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.target.id.endswith("_SCENARIOS"):
                rows.extend(ast.literal_eval(statement.value))
    return unique_by(rows, lambda x: x["fid"])


def scaffold(case, spec):
    replacements = [(name, value) for name, value in spec.items() if name in SLOT_KEYS and value]
    replacements.extend(("speaker", s.split("—")[0].strip()) for s in spec.get("speakers", []))
    masked = sorted(replacements, key=lambda item: -len(item[1]))
    speakers, turns = {}, []
    for turn in case["turns"]:
        speaker = turn["speaker"]
        speakers.setdefault(speaker, len(speakers))
        text = turn["text"].casefold()
        for name, value in masked:
            text = re.sub(r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)", f"‹{name}›", text)
        turns.append((turn["session_id"], speakers[speaker], text))
    return (
        case["meeting_mode"], case["variant_type"], tuple(turns),
        tuple((e["turn_id"], e["kind"], tuple(f for f in FACT_FIELDS if e[f] is not None)) for e in case["gold_events"]),
        tuple((r["source_key"], r["target_key"], r["kind"], r["field"]) for r in case["gold_relations"]),
        tuple(tuple(sorted(k for k in s if k != "event_key")) for s in case["expected_state"]),
    )


def audit_scaffolds(root, cases):
    specs = scenario_slot_values(root)
    signatures = {c["case_id"]: scaffold(c, specs[c["family_id"]]) for c in cases.values()}
    train = defaultdict(list)
    train_designs = set()
    for case in cases.values():
        if case["split"] == "train":
            train[signatures[case["case_id"]]].append(case["case_id"])
            train_designs.add((case["meeting_mode"], case["variant_type"]))
    observed = Counter()
    examples = {}
    matched = {}
    for case in cases.values():
        if case["split"] == "train":
            continue
        cid, split = case["case_id"], case["split"]
        if (case["meeting_mode"], case["variant_type"]) in train_designs:
            observed[f"{split}_shared_variant"] += 1
        signature = signatures[cid]
        if signature in train:
            observed[f"{split}_exact_scaffold"] += 1
            matched[cid] = train[signature][0]
            if case["variant_type"] == "amends_owner_cross_trap":
                examples.setdefault(split, {"train": train[signature][0], "other": cid,
                                            "normalized_turns": signature[2], "relations": signature[4]})
    return {"counts": dict(observed), "matched_train_cases": matched, "examples": examples}


def summarize_coverage(cases):
    coverage = {}
    for split in SPLITS:
        items = [c for c in cases.values() if c["split"] == split]
        visible = [r for c in items for l in c["relation_samples"] for r in l["target"]["relations"]]
        turns = [len(c["turns"]) for c in items]
        coverage[split] = {
            "families": len({c["family_id"] for c in items}),
            "cases": len(items), "turns_min_median_max": [min(turns), median(turns), max(turns)],
            "relations": dict(Counter(r["kind"] for r in visible)),
            "visible_amends": dict(Counter(r["field"] for r in visible if r["kind"] == "amends")),
            "missing_target_cases": sum(bool(c["missing_target_in_window"]) for c in items),
            "missing_target_with_no_expected_state": sum(bool(c["missing_target_in_window"]) and not c["expected_state"]
                                                         for c in items),
            "asr_cases": sum("asr_noise" in c["tags"] for c in items),
            "source_only_case_status": dict(Counter(c["status"] for c in items)),
        }
    return coverage


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("root", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--production-vectors", type=Path, help="Use previously computed E5 vectors")
    args = cli.parse_args()
    root = args.root.resolve()
    data, hashes = load_bundle(root)
    cases = audit_manifests(data, hashes)
    settings = load_model_settings()
    tokenizer = AutoTokenizer.from_pretrained(settings.snapshot(), local_files_only=True)
    packets, packet_audit = inspect_packets(data, cases, tokenizer, settings)
    if args.production_vectors:
        stored = json.loads(args.production_vectors.read_text())
        vectors = {key: np.asarray(value, dtype=float) for key, value in stored.items()}
    else:
        units_by_case = [(key, units_from_case(case)[0]) for key, case in cases.items()]
        long_cases = [(key, units) for key, units in units_by_case
                      if len(units) > settings.extraction_batch_size]
        vectors = production_vectors(long_cases, settings)

    changes, partial, omissions, errors, bad_quotes = [], [], [], [], []
    totals = defaultdict(Counter)
    with TemporaryDirectory(prefix="minda-v2-replay-") as work:
        temp = Path(work)
        session = Replay(settings.model_copy(update={"cache_dir": str(temp), "response_cache": False}), tokenizer, temp)
        for index, (cid, case) in enumerate(cases.items(), 1):
            try:
                counts, diffs, quotes, conditions, rejected_quotes = replay_case(root, case, packets, session, vectors)
                bad_quotes.extend(rejected_quotes)
                totals[case["split"]].update(counts)
                changes.extend(diffs)
                partial.extend(quotes)
                omissions.extend(conditions)
            except (AssertionError, KeyError, StopIteration, ValueError) as exc:
                errors.append({"case_id": cid, "type": type(exc).__name__, "detail": str(exc)})
            if index % 50 == 0:
                print(f"Replayed {index}/{len(cases)} cases", flush=True)
        replayed = session.saw

    result = {
        "packet_audit": packet_audit, "replayed_packets": replayed, "replay_metrics": totals, "replay_errors": errors,
        "production_context_mismatches": changes, "conditional_quote_omissions": omissions,
        "partial_word_edge_quotes": partial, "dropped_relation_quotes": bad_quotes, "coverage": summarize_coverage(cases),
        "scaffold_audit": audit_scaffolds(root, cases), "sha256": hashes,
    }
    assert load_bundle(root)[1] == hashes, "The data changed while auditing it."
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "packets": packet_audit, "replayed": replayed, "replay_metrics": totals, "replay_errors": errors[:6],
        "context_mismatches": dict(Counter(r["split"] for r in changes)),
        "alias_changes": sum(r["aliases_changed"] for r in changes),
        "partial_word_quotes": dict(Counter(r["split"] for r in partial)),
        "condition_omissions": dict(Counter(r["split"] for r in omissions)),
        "scaffolds": result["scaffold_audit"]["counts"],
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
