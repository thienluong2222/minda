"""Full corpus source-contract checks, four clusterers and derived long-input stress."""
# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web_app/src"))
sys.path.insert(0, str(ROOT))

from experiments.comparative_benchmark.text import cluster
from experiments.minutes_graph.run import DATA, OUT, read_rows, source_payload, turns_for
from meeting_pipeline.minutes.graph_builder import build_graph, fallback_event, validate_graph
from meeting_pipeline.minutes.graph_contracts import digest
from meeting_pipeline.minutes.graph_inputs import make_graph_units
from meeting_pipeline.minutes.graph_pipeline import save_json
from meeting_pipeline.minutes.graph_topics import hierarchical_topics
from meeting_pipeline.minutes.graph_writer import plan_sections
from meeting_pipeline.minutes.topic_clustering import cluster_topics


def main():
    output = OUT / "structural"
    output.mkdir(parents=True, exist_ok=True)
    source_checks = []
    for row in read_rows(DATA / "test.jsonl"):
        turns = turns_for(source_payload(row))
        units, excluded = make_graph_units(turns)
        by_turn = {t.turn_id: t.text for t in turns}
        assert not excluded
        assert len({u.unit_id for u in units}) == len(units)
        for unit in units:
            for span in unit.sources:
                assert by_turn[span.turn_id][span.start_char : span.end_char] == span.text
        # These are structural checks only, explicitly not a stand-in for model extraction.
        topics = {
            "cluster_count": 1,
            "membership": [[1.0]] * len(units),
            "primary": [0] * len(units),
            "titles": ["Nội dung"],
        }
        graph = build_graph(row["id"], units, [fallback_event(u) for u in units], topics, [])
        assert not validate_graph(graph)
        sections, _ledger = plan_sections(graph)
        assert {cid for s in sections for cid in s.claim_ids} == {e.event_id for e in graph.events}
        source_checks.append(
            {
                "id": row["id"],
                "group_id": row["group_id"],
                "units": len(units),
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "exact_source_spans": True,
                "all_source_units_accounted": True,
                "model_inference": False,
            }
        )
    save_json(output / "source_contract_checks.json", source_checks)
    base = ROOT / "reports/comparative_benchmark/20261104/text"
    documents = json.loads((base / "manifest.json").read_text())
    results = []
    for encoder in ("e5_small", "minilm"):
        vectors = np.load(base / encoder / "vectors.npy")
        cursor = 0
        for document in documents:
            count = len(document["units"])
            x = vectors[cursor : cursor + count]
            cursor += count
            labels = [u["topic"] for u in document["units"]]
            for method in ("fcm", "kmeans", "agglomerative", "hdbscan"):
                started = time.perf_counter()
                predicted = cluster(x, method)
                results.append(
                    {
                        "id": document["id"],
                        "split": document["split"],
                        "encoder": encoder,
                        "method": method,
                        "ARI": adjusted_rand_score(labels, predicted),
                        "NMI": normalized_mutual_info_score(labels, predicted),
                        "clusters": len(set(predicted)),
                        "wall_sec": time.perf_counter() - started,
                    }
                )
        assert cursor == len(vectors)
    save_json(output / "clustering_per_document.json", results)
    grouped = defaultdict(list)
    for result in results:
        grouped[(result["split"], result["encoder"], result["method"])].append(result)
    summary = [
        {
            "split": split,
            "encoder": encoder,
            "method": method,
            "n": len(values),
            "ARI": float(np.mean([v["ARI"] for v in values])),
            "NMI": float(np.mean([v["NMI"] for v in values])),
        }
        for (split, encoder, method), values in grouped.items()
    ]
    save_json(output / "clustering_summary.json", summary)
    # Repeated held-out topic records exercise memory, hierarchy and provenance;
    # they are not claimed to be a new independent or realistic multi-day meeting.
    source_vectors = np.load(base / "e5_small/vectors.npy")
    indices, texts = [], []
    offset = 0
    for document in documents:
        if document["split"] == "test":
            for i, unit in enumerate(document["units"]):
                indices.append(offset + i)
                texts.append(unit["text"])
        offset += len(document["units"])
    long_texts = texts * 4
    payload = {
        "units": [
            {"unit_id": f"long_{i}", "speaker_label": f"Người {i % 4}", "text": text}
            for i, text in enumerate(long_texts)
        ]
    }
    units, _ = make_graph_units(turns_for(payload))
    x = np.tile(source_vectors[indices], (4, 1))
    assert len(x) == len(units)
    x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
    started = time.perf_counter()
    topics = cluster_topics(x.tolist(), max_clusters=6, fuzziness=1.3, minimum_silhouette=0.08)
    topics["titles"] = [f"Chủ đề {i}" for i in range(topics["cluster_count"])]
    topics = hierarchical_topics(
        topics, x, SimpleNamespace(fuzziness=1.3, minimum_silhouette=0.08), None
    )
    graph = build_graph(
        "derived_long_records", units, [fallback_event(u) for u in units], topics, []
    )
    assert not validate_graph(graph)
    assert np.allclose(np.sum(topics["membership"], axis=1), 1)
    save_json(
        output / "long_stress.json",
        {
            "units": len(units),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "topics": topics["cluster_count"],
            "parent_topics": len(topics.get("hierarchy", [])),
            "wall_sec": time.perf_counter() - started,
            "graph_validation_pass": True,
            "membership_mass_preserved": True,
            "source": "four repetitions of the existing 30 held-out topic documents",
            "LLM_long_meeting_semantics_evaluated": False,
            "not_an_independent_new_meeting": True,
        },
    )
    save_json(
        output / "protocol.json",
        {
            "test_source_sha256": digest(read_rows(DATA / "test.jsonl")),
            "text_manifest_sha256": digest(documents),
            "existing_embedding_reuse": True,
            "embedding_input_protocol": str(base / "protocol.json"),
            "source_contract_cases": len(source_checks),
            "clustering_runs": len(results),
            "structural_checks_are_not_semantic_scores": True,
        },
    )
    print(
        json.dumps(
            {
                "source_cases": len(source_checks),
                "clustering_runs": len(results),
                "long_units": len(units),
                "status": "passed",
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
