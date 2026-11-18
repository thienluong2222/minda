"""Agenda assignment plus residual fuzzy discovery; fuzzy weights are not truth scores."""

from __future__ import annotations

from typing import Any

import numpy as np

from meeting_pipeline.minutes.graph_contracts import GraphUnit
from meeting_pipeline.minutes.graph_editorial import PROCEDURAL_TITLES, editorial_role
from meeting_pipeline.minutes.graph_inputs import contextual_texts
from meeting_pipeline.minutes.model_runtime import ModelRuntimeError
from meeting_pipeline.minutes.topic_clustering import cluster_topics


def conditional_membership(x: np.ndarray, model: dict[str, Any]) -> np.ndarray:
    projected = x
    if model["projection_components"] is not None:
        projected = (x - np.asarray(model["projection_mean"])) @ np.asarray(
            model["projection_components"]
        ).T
    centers = np.asarray(model["centers"])
    if len(centers) == 1:
        return np.ones((len(x), 1))
    distances = np.linalg.norm(projected[:, None, :] - centers[None, :, :], axis=2)
    logits = -2 / (model["fuzziness"] - 1) * np.log(np.maximum(distances, 1e-12))
    weights = np.exp(logits - logits.max(axis=1, keepdims=True))
    return weights / weights.sum(axis=1, keepdims=True)


def hierarchical_topics(
    result: dict[str, Any], x: np.ndarray, settings: Any, fixed_clusters: int | None
) -> dict[str, Any]:
    if fixed_clusters or len(x) <= 80:
        return result
    parent = np.asarray(result["membership"])
    primary = np.asarray(result["primary"])
    matrices, titles, hierarchy = [], [], []
    offset = 0
    for k in range(result["cluster_count"]):
        subset = np.flatnonzero(primary == k)
        child = None
        if len(subset) > 40:
            child = cluster_topics(
                x[subset].tolist(),
                max_clusters=min(8, len(subset) // 8),
                fuzziness=settings.fuzziness,
                minimum_silhouette=settings.minimum_silhouette,
                include_model=True,
            )
        if child and child["cluster_count"] > 1:
            conditional = conditional_membership(x, child["model"])
            count = child["cluster_count"]
            matrices.append(parent[:, k : k + 1] * conditional)
            titles.extend(f"{result['titles'][k]} — phần {j + 1}" for j in range(count))
        else:
            count = 1
            matrices.append(parent[:, k : k + 1])
            titles.append(result["titles"][k])
        hierarchy.append(
            {
                "parent_id": f"topic_parent:{k}",
                "title": result["titles"][k],
                "children": list(range(offset, offset + count)),
                "diagnostics": child
                and {key: value for key, value in child.items() if key != "model"},
            }
        )
        offset += count
    membership = np.hstack(matrices)
    membership /= np.maximum(membership.sum(axis=1, keepdims=True), 1e-12)
    return {
        **result,
        "parent_membership": parent.tolist(),
        "hierarchy": hierarchy,
        "cluster_count": len(titles),
        "membership": membership.tolist(),
        "primary": membership.argmax(axis=1).tolist(),
        "titles": titles,
    }


def _discover_topics(
    session: Any,
    units: list[GraphUnit],
    *,
    agenda: list[str] | None = None,
    use_fcm: bool = True,
    fixed_clusters: int | None = None,
    vectors: np.ndarray | None = None,
) -> tuple[dict[str, Any], np.ndarray]:
    if vectors is None:
        texts = contextual_texts(units)
        embedded = []
        for start in range(0, len(texts), 16):
            embedded.extend(session.embed(texts[start : start + 16]))
        vectors = np.asarray(embedded, dtype=float)
    x = np.asarray(vectors, dtype=float).copy()
    x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
    if not use_fcm:
        episode_ids = list(dict.fromkeys(u.episode_id for u in units))
        primary = [episode_ids.index(u.episode_id) for u in units]
        result = {
            "algorithm": "chronological_episodes",
            "cluster_count": len(episode_ids),
            "primary": primary,
            "membership": np.eye(len(episode_ids))[primary].tolist(),
            "titles": ["Nội dung cuộc họp" for _ in episode_ids],
            "membership_is_probability": False,
        }
        return result, x
    settings = session.settings
    # Retain one-cluster fallback. Grow the search only as the input grows.
    cap = min(12, max(int(settings.max_clusters), int(np.ceil(np.sqrt(len(units) / 2)))))
    agenda = list(dict.fromkeys(s.strip() for s in (agenda or []) if s.strip()))
    if not agenda:
        result = cluster_topics(
            x.tolist(),
            max_clusters=cap,
            fixed_clusters=fixed_clusters
            if fixed_clusters is not None
            else (1 if len(units) < 10 else None),
            fuzziness=settings.fuzziness,
            minimum_silhouette=settings.minimum_silhouette,
        )
        result["titles"] = [f"Vấn đề {k + 1}" for k in range(result["cluster_count"])]
        result["strategy"] = "discovered_fcm"
        result["short_input_single_topic"] = fixed_clusters is None and len(units) < 10
        return hierarchical_topics(result, x, settings, fixed_clusters), x
    if len(agenda) > 64:
        raise ValueError("Chương trình có quá nhiều mục ở cùng một cấp; cần chia phiên.")
    a = np.asarray(session.embed(agenda), dtype=float)
    a /= np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    similarities = x @ a.T
    # Agenda mapping has an explicit unknown bucket; no forced nearest-topic match.
    residual = np.where(np.max(similarities, axis=1) < 0.78)[0]
    membership = np.zeros((len(units), len(agenda)))
    logits = np.exp((similarities - similarities.max(axis=1, keepdims=True)) / 0.06)
    membership[:] = logits / logits.sum(axis=1, keepdims=True)
    membership[residual] = 0
    titles = agenda.copy()
    residual_result = None
    if len(residual):
        residual_result = cluster_topics(
            x[residual].tolist(),
            max_clusters=cap,
            fuzziness=settings.fuzziness,
            minimum_silhouette=settings.minimum_silhouette,
        )
        extra = np.zeros((len(units), residual_result["cluster_count"]))
        extra[residual] = residual_result["membership"]
        membership = np.hstack([membership, extra])
        titles.extend(f"Nội dung phát sinh {k + 1}" for k in range(extra.shape[1]))
    result = {
        "algorithm": "agenda_with_residual_fcm",
        "strategy": "agenda_or_fcm",
        "cluster_count": len(titles),
        "primary": membership.argmax(axis=1).tolist(),
        "membership": membership.tolist(),
        "titles": titles,
        "membership_is_probability": False,
        "agenda_similarity_threshold": 0.78,
        "residual_indices": residual.tolist(),
        "residual_discovery": residual_result,
    }
    return hierarchical_topics(result, x, settings, fixed_clusters), x


def discover_topics(
    session: Any,
    units: list[GraphUnit],
    *,
    agenda: list[str] | None = None,
    use_fcm: bool = True,
    fixed_clusters: int | None = None,
) -> tuple[dict[str, Any], np.ndarray]:
    texts = contextual_texts(units)
    embedded = []
    for start in range(0, len(texts), 16):
        embedded.extend(session.embed(texts[start : start + 16]))
    x = np.asarray(embedded, dtype=float)
    if not np.isfinite(x).all() or np.any(np.linalg.norm(x, axis=1) <= 1e-12):
        raise ModelRuntimeError(
            "Embedding rỗng hoặc không hữu hạn; cần kiểm tra lại nguồn mô hình."
        )
    x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
    roles = [editorial_role(unit.original) for unit in units]
    discussion = [i for i, role in enumerate(roles) if role == "discussion"]
    if discussion:
        result, _ = _discover_topics(
            session,
            [units[i] for i in discussion],
            agenda=agenda,
            use_fcm=use_fcm,
            fixed_clusters=fixed_clusters,
            vectors=x[discussion],
        )
        count = result["cluster_count"]
        membership = np.zeros((len(units), count))
        membership[discussion] = result["membership"]
    else:
        result = {"algorithm": "procedural_sections", "titles": [], "cluster_count": 0}
        membership = np.zeros((len(units), 0))
    titles = list(result["titles"])
    procedural = {}
    for role in dict.fromkeys(role for role in roles if role != "discussion"):
        topic = len(titles)
        titles.append(PROCEDURAL_TITLES[role])
        column = np.asarray([float(value == role) for value in roles])[:, None]
        membership = np.hstack([membership, column])
        procedural[str(topic)] = role
    result = {
        **result,
        "titles": titles,
        "cluster_count": len(titles),
        "membership": membership.tolist(),
        "primary": membership.argmax(axis=1).tolist(),
        "procedural_topics": procedural,
        "unit_roles": roles,
        "agenda_count": len(list(dict.fromkeys(s.strip() for s in (agenda or []) if s.strip())))
        if discussion
        else 0,
        "membership_is_probability": False,
    }
    for key in ("ambiguous_indices", "residual_indices"):
        if key in result:
            result[key] = [discussion[i] for i in result[key]]
    # Parent weights must have the same row count after procedural rows are restored.
    if "parent_membership" in result:
        parents = np.zeros((len(units), len(result["parent_membership"][0])))
        parents[discussion] = result["parent_membership"]
        result["parent_membership"] = parents.tolist()
    return result, x


def refine_topics(topics: dict, units: list[GraphUnit], events: list, edges: list) -> dict:
    """A small graph regularisation of fuzzy candidates, never an event truth score."""
    membership = np.asarray(topics["membership"], dtype=float)
    positions = {unit.unit_id: i for i, unit in enumerate(units)}
    event_positions = {event.event_id: positions[event.unit_ids[0]] for event in events}
    totals = np.zeros_like(membership)
    degrees = np.zeros(len(units))
    links = 0
    roles = topics.get("unit_roles", ["discussion"] * len(units))
    for edge in edges:
        if not edge.asserted or edge.kind not in {
            "supports",
            "opposes",
            "amends",
            "withdraws",
            "supersedes",
            "accepts",
        }:
            continue
        a, b = event_positions.get(edge.source), event_positions.get(edge.target)
        if a is None or b is None or a == b or roles[a] != "discussion" or roles[b] != "discussion":
            continue
        totals[a] += membership[b]
        totals[b] += membership[a]
        degrees[a] += 1
        degrees[b] += 1
        links += 1
    selected = degrees > 0
    adjusted = membership.copy()
    adjusted[selected] = (
        0.8 * membership[selected] + 0.2 * totals[selected] / degrees[selected, None]
    )
    primary = adjusted.argmax(axis=1)
    # Empty discovered candidates are removed; explicit agenda items are retained.
    keep = sorted(set(primary.tolist()) | set(range(topics.get("agenda_count", 0))))
    mapping = {old: new for new, old in enumerate(keep)}
    adjusted = adjusted[:, keep]
    adjusted /= np.maximum(adjusted.sum(axis=1, keepdims=True), 1e-12)
    result = {
        **topics,
        "membership": adjusted.tolist(),
        "primary": [mapping[int(i)] for i in primary],
        "titles": [topics["titles"][i] for i in keep],
        "cluster_count": len(keep),
        "procedural_topics": {
            str(mapping[int(k)]): value
            for k, value in topics.get("procedural_topics", {}).items()
            if int(k) in mapping
        },
        "graph_refinement": {
            "coefficient": 0.2,
            "relation_count": links,
            "reassigned_units": int(np.count_nonzero(primary != np.asarray(topics["primary"]))),
        },
    }
    if "hierarchy" in result:
        result["hierarchy"] = [
            {**row, "children": [mapping[c] for c in row["children"] if c in mapping]}
            for row in result["hierarchy"]
            if any(c in mapping for c in row["children"])
        ]
    return result
