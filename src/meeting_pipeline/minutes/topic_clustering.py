"""Per-meeting fuzzy topic clustering with deterministic primary ownership."""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
from numpy.typing import NDArray
from skfuzzy.cluster import cmeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score


def cluster_topics(
    vectors: list[list[float]],
    *,
    max_clusters: int = 6,
    fixed_clusters: int | None = None,
    fuzziness: float = 2.0,
    minimum_silhouette: float = 0.08,
    include_model: bool = False,
) -> dict[str, Any]:
    """Membership is a similarity weight, never a factual confidence/probability.

    Try three initializations per c; reject tiny/unstable/collapsed partitions.
    One topic is the explicit fallback, including identical or too few samples.
    """
    x: NDArray[np.float64] = np.asarray(vectors, dtype=np.float64)
    if x.ndim != 2 or not len(x) or not np.isfinite(x).all():
        raise ValueError("Embedding phải là ma trận hữu hạn, không rỗng.")
    n = len(x)
    if fixed_clusters is not None and not 1 <= fixed_clusters <= n:
        raise ValueError("Số chủ đề phải nằm giữa 1 và số đơn vị ý nghĩa.")
    x = x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
    # Reduce dimensionality only for distance fitting; evaluate in original space.
    fit_x = x
    projection = None
    if min(x.shape) > 12:
        projection = PCA(n_components=min(12, n - 1), random_state=0)
        fit_x = projection.fit_transform(x)
    candidates: list[dict[str, Any]] = []
    best = None
    possible = (
        [fixed_clusters]
        if fixed_clusters and fixed_clusters > 1
        else range(2, min(max_clusters, n // 3) + 1)
    )
    if fixed_clusters != 1 and np.max(np.std(fit_x, axis=0)) > 1e-8:
        for c in possible:
            attempts = []
            for seed in (0, 17, 42):
                centers, membership, _, _, _, _, fpc = cmeans(
                    fit_x.T,
                    c,
                    fuzziness,
                    error=1e-5,
                    maxiter=300,
                    seed=seed,
                )
                labels = np.argmax(membership, axis=0).astype(np.int64)
                sizes = np.bincount(labels, minlength=c)
                if len(set(labels)) != c or min(sizes) < (1 if fixed_clusters else 2):
                    continue
                silhouette = (
                    float(
                        silhouette_score(
                            x, labels, metric="cosine", sample_size=min(n, 1500), random_state=0
                        )
                    )
                    if c < n
                    else -1.0
                )
                attempts.append((silhouette, membership, labels, float(fpc), centers))
            stability = (
                float(
                    np.mean([adjusted_rand_score(a[2], b[2]) for a, b in combinations(attempts, 2)])
                )
                if len(attempts) > 1
                else 0.0
            )
            if not attempts:
                candidates.append({"c": c, "accepted": False, "reason": "empty_or_tiny_cluster"})
                continue
            selected = max(attempts, key=lambda item: item[0])
            sil, membership, labels, fpc, centers = selected
            accepted = bool(fixed_clusters) or (
                len(attempts) == 3
                and stability >= 0.6
                and sil >= minimum_silhouette
                and float(np.mean(np.max(membership, axis=0))) >= 1 / c + 0.1
            )
            candidates.append(
                {
                    "c": c,
                    "silhouette": sil,
                    "stability": stability,
                    "fpc": fpc,
                    "accepted": accepted,
                }
            )
            score = sil + 0.1 * stability
            if accepted and (best is None or score > best[0]):
                best = score, membership, labels, centers
    if best is None:
        if fixed_clusters and fixed_clusters > 1:
            raise ValueError("FCM không tạo được số nhóm yêu cầu từ các embedding này.")
        membership = np.ones((1, n))
        labels = np.zeros(n, dtype=np.int64)
        centers = np.mean(fit_x, axis=0, keepdims=True)
    else:
        _, membership, labels, centers = best
    # Stable names ordered by first occurrence, independent of FCM centroid IDs.
    order = sorted(set(labels.tolist()), key=lambda label: labels.tolist().index(label))
    remap = {old: new for new, old in enumerate(order)}
    primary = [remap[int(label)] for label in labels]
    membership = membership[order]
    ambiguous = []
    for i in range(n):
        values = sorted(membership[:, i], reverse=True)
        if len(values) > 1 and (values[0] < 0.55 or values[0] - values[1] < 0.15):
            ambiguous.append(i)
    result = {
        "algorithm": "fuzzy_c_means",
        "cluster_count": len(order),
        "primary": primary,
        "membership": membership.T.tolist(),
        "ambiguous_indices": ambiguous,
        "candidates": candidates,
        "fit_dimensions": fit_x.shape[1],
        "embedding_dimensions": x.shape[1],
        "membership_is_probability": False,
    }
    if include_model:
        result["model"] = {
            "centers": centers[order].tolist(),
            "projection_mean": projection.mean_.tolist() if projection is not None else None,
            "projection_components": projection.components_.tolist()
            if projection is not None
            else None,
            "fuzziness": fuzziness,
        }
    return result
