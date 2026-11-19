"""Wave 1-1: Topic clustering benchmark comparing old (0.08/min2) vs current (0.22/min3) FCM and baselines."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CB_DATA, OUT, ROOT, SEED, log, read_json, require_input, rss_mb, setup_root_src, snapshot, write_csv, write_json

ENCODERS = {
    "e5_small": "intfloat/multilingual-e5-small",
    "e5_base": "intfloat/multilingual-e5-base",
    "minilm": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "bge_m3": "BAAI/bge-m3",
}


def encode_texts(name: str, texts: list[str], *, max_length_policy: str = "safe") -> tuple:
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    path = snapshot(ENCODERS[name])
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModel.from_pretrained(path, local_files_only=True).eval()
    limit = 128 if name == "minilm" else 512
    vectors = []
    truncated = 0
    encode_sec = 0.0
    for idx in range(0, len(texts), 16):
        batch_text = texts[idx : idx + 16]
        if name.startswith("e5"):
            batch_text = ["query: " + t for t in batch_text]
        raw = tokenizer(batch_text, padding=False, truncation=False)
        truncated += sum(len(ids) > limit for ids in raw["input_ids"])
        batch = tokenizer(
            batch_text,
            padding=True,
            truncation=True,
            max_length=limit,
            return_tensors="pt",
        )
        t0 = time.perf_counter()
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
            if name == "bge_m3":
                emb = hidden[:, 0]
            else:
                mask = batch["attention_mask"].unsqueeze(-1)
                emb = (hidden * mask).sum(1) / mask.sum(1)
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)
        encode_sec += time.perf_counter() - t0
        vectors.append(emb.cpu().numpy())
    return np.concatenate(vectors, axis=0), {
        "encode_sec": round(encode_sec, 4),
        "truncated_count": truncated,
        "samples": len(texts),
        "revision": path.name,
    }


def legacy_fcm_cluster(vectors, *, max_clusters: int = 4, fuzziness: float = 1.3):
    """Legacy 2026-11-04 behavior: min_size=2, min_silhouette=0.08."""
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_score

    x = np.asarray(vectors, dtype=np.float64)
    n = len(x)
    if n < 4:
        return np.zeros(n, dtype=int)
    if x.shape[1] > min(16, n - 1):
        comps = min(16, n - 1, x.shape[1])
        x = PCA(n_components=comps, random_state=42).fit_transform(x)
    best = None
    for k in range(2, min(max_clusters, n - 1) + 1):
        # Match topic_clustering.py deterministic FCM loop
        centers = KMeans(n_clusters=k, n_init=5, random_state=42).fit(x).cluster_centers_
        exp = 2.0 / (fuzziness - 1.0)
        for _ in range(40):
            dists = np.linalg.norm(x[None, :, :] - centers[:, None, :], axis=2)
            dists = np.maximum(dists, 1e-6)
            ratios = dists[:, None, :] / dists[None, :, :]
            u = 1.0 / np.sum(ratios**exp, axis=1)
            u_m = u**fuzziness
            new_centers = (u_m @ x) / np.maximum(u_m.sum(axis=1, keepdims=True), 1e-8)
            if np.max(np.abs(new_centers - centers)) < 1e-4:
                centers = new_centers
                break
            centers = new_centers
        labels = np.argmax(u, axis=0)
        counts = np.bincount(labels, minlength=k)
        if counts.min() < 2 or len(set(labels.tolist())) < 2:
            continue
        sil = float(silhouette_score(x, labels, metric="cosine"))
        if sil >= 0.08 and (best is None or sil > best[0]):
            best = (sil, labels)
    return best[1] if best is not None else np.zeros(n, dtype=int)


def run_method(vectors, method: str):
    import numpy as np
    from sklearn.cluster import HDBSCAN, AgglomerativeClustering, KMeans
    from sklearn.metrics import silhouette_score
    from meeting_pipeline.minutes.topic_clustering import cluster_topics

    t0 = time.perf_counter()
    if method == "fcm_legacy_008":
        pred = legacy_fcm_cluster(vectors, max_clusters=4, fuzziness=1.3)
    elif method == "fcm_current_022":
        pred = np.asarray(
            cluster_topics(
                vectors.tolist(), max_clusters=4, fuzziness=1.3, minimum_silhouette=0.22
            )["primary"]
        )
    elif method in {"kmeans_008", "kmeans_022", "agg_008", "agg_022"}:
        thr = 0.22 if method.endswith("022") else 0.08
        min_sz = (3 if len(vectors) >= 12 else 2) if method.endswith("022") else 2
        best = None
        for k in (2, 3, 4):
            if k >= len(vectors):
                continue
            labels = (
                KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(vectors)
                if method.startswith("kmeans")
                else AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(vectors)
            )
            if min(np.bincount(labels)) < min_sz:
                continue
            sil = float(silhouette_score(vectors, labels, metric="cosine"))
            if sil >= thr and (best is None or sil > best[0]):
                best = (sil, labels)
        pred = best[1] if best is not None else np.zeros(len(vectors), dtype=int)
    elif method == "hdbscan":
        if len(vectors) < 5:
            pred = np.zeros(len(vectors), dtype=int)
        else:
            labels = HDBSCAN(min_cluster_size=3, min_samples=2, metric="euclidean").fit_predict(vectors)
            keep = sorted(set(labels) - {-1})
            if not keep:
                pred = np.zeros(len(vectors), dtype=int)
            else:
                for i in np.where(labels == -1)[0]:
                    cents = np.stack([vectors[labels == lb].mean(axis=0) for lb in keep])
                    labels[i] = keep[int(np.argmax(cents @ vectors[i]))]
                pred = labels
    else:
        raise ValueError(method)
    return pred, time.perf_counter() - t0


def _available_encoders(requested: list[str] | None) -> list[str]:
    if requested:
        return requested
    available = []
    for name, model_id in ENCODERS.items():
        try:
            snapshot(model_id)
            available.append(name)
        except FileNotFoundError:
            log(f"[Clustering] Skipping uncached optional baseline encoder: {name} ({model_id})")
    if not available:
        raise FileNotFoundError(
            "Không tìm thấy encoder embedding nào trong data/model_cache. "
            "Chạy: .venv-backend/bin/python scripts/prepare_minutes_models.py"
        )
    return available


def main() -> None:
    parser = argparse.ArgumentParser(description="Wave 1 Topic Clustering benchmark.")
    parser.add_argument(
        "--encoders",
        nargs="+",
        choices=list(ENCODERS),
        default=None,
        help="Optional subset of encoders to evaluate (defaults to all cached encoders).",
    )
    args = parser.parse_args()

    setup_root_src()
    import numpy as np
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score

    t_all = time.perf_counter()
    # Dataset 1: 42 synthetic topic docs (9 val, 30 test) — auto-generate if missing
    text_manifest = CB_DATA / "text/manifest.json"
    if not text_manifest.is_file():
        log("[Clustering] text/manifest.json missing; generating deterministically via comparative_benchmark.text.prepare() ...")
        from experiments.comparative_benchmark import text as cb_text

        cb_text.prepare()
    docs_42 = read_json(require_input(text_manifest))
    docs_42 = [d for d in docs_42 if d["split"] in {"validation", "test"}]

    # Dataset 2: 60 graph-synthetic-v2.1 test transcripts (turn counts variable)
    v21_path = require_input(ROOT / "artifacts/graph-synthetic-v2.1/test/inputs/transcripts.jsonl")
    v21_rows = [json.loads(line) for line in v21_path.read_text().splitlines() if line.strip()]
    # Dataset 3: 84 llm-next-round-v2 test transcripts
    nrv2_path = require_input(ROOT / "artifacts/llm-next-round-v2-20261026/data/test.jsonl")
    nrv2_rows = [json.loads(line) for line in nrv2_path.read_text().splitlines() if line.strip()]
    nrv2_docs = []
    for row in nrv2_rows:
        payload = json.loads(next(m["content"] for m in row["messages"] if m["role"] == "user"))
        nrv2_docs.append({"id": row["id"], "texts": [u["text"] for u in payload["units"]]})

    methods = ["fcm_legacy_008", "fcm_current_022", "kmeans_008", "kmeans_022", "agg_008", "agg_022", "hdbscan"]
    summary_rows = []
    structural_rows = []
    encoder_meta = {}

    selected_encoders = _available_encoders(args.encoders)
    for enc_name in selected_encoders:
        log(f"[Clustering] Encoding with {enc_name} ...")
        t_enc0 = time.perf_counter()

        # Encode Dataset 1 (42 docs)
        flat1 = [u["text"] for d in docs_42 for u in d["units"]]
        mat1, m1 = encode_texts(enc_name, flat1)

        # Encode Dataset 2 (v2.1 60 test cases)
        flat2 = [t["text"] for r in v21_rows for t in r["turns"]]
        mat2, m2 = encode_texts(enc_name, flat2)

        # Encode Dataset 3 (nrv2 84 test cases)
        flat3 = [t for d in nrv2_docs for t in d["texts"]]
        mat3, m3 = encode_texts(enc_name, flat3)

        encoder_meta[enc_name] = {
            "text_manifest": m1,
            "v21_test": m2,
            "nrv2_test": m3,
            "total_encode_wall_sec": round(time.perf_counter() - t_enc0, 2),
        }

        per_doc = []
        cursor = 0
        for d in docs_42:
            k = len(d["units"])
            vec = mat1[cursor : cursor + k]
            cursor += k
            labels = [u["topic"] for u in d["units"]]
            for meth in methods:
                pred, dt = run_method(vec, meth)
                n_cl = len(set(pred.tolist()))
                sil = float(silhouette_score(vec, pred, metric="cosine")) if 1 < n_cl < k else None
                per_doc.append(
                    {
                        "split": d["split"],
                        "doc_id": d["id"],
                        "encoder": enc_name,
                        "method": meth,
                        "ari": float(adjusted_rand_score(labels, pred)),
                        "nmi": float(normalized_mutual_info_score(labels, pred)),
                        "clusters": n_cl,
                        "collapsed_to_one": n_cl == 1,
                        "silhouette": sil,
                        "seconds": dt,
                    }
                )
        for split in ("validation", "test"):
            for meth in methods:
                sel = [r for r in per_doc if r["split"] == split and r["method"] == meth]
                sils = [r["silhouette"] for r in sel if r["silhouette"] is not None]
                summary_rows.append(
                    {
                        "encoder": enc_name,
                        "method": meth,
                        "split": split,
                        "docs": len(sel),
                        "ari": round(float(np.mean([r["ari"] for r in sel])), 4),
                        "nmi": round(float(np.mean([r["nmi"] for r in sel])), 4),
                        "collapse_rate": round(float(np.mean([r["collapsed_to_one"] for r in sel])), 4),
                        "mean_clusters": round(float(np.mean([r["clusters"] for r in sel])), 3),
                        "mean_silhouette_non_collapsed": round(float(np.mean(sils)), 4) if sils else None,
                    }
                )

        # Evaluate fallback/collapse behavior on realistic transcripts (v2.1 test + nrv2 test)
        for ds_name, docs_list, mat in [
            ("v21_test_60", [{"id": r["case_id"], "n": len(r["turns"])} for r in v21_rows], mat2),
            ("nrv2_test_84", [{"id": d["id"], "n": len(d["texts"])} for d in nrv2_docs], mat3),
        ]:
            for meth in ["fcm_legacy_008", "fcm_current_022", "kmeans_008", "kmeans_022", "hdbscan"]:
                cur = 0
                clusters_list = []
                collapsed = []
                for item in docs_list:
                    vec = mat[cur : cur + item["n"]]
                    cur += item["n"]
                    pred, _ = run_method(vec, meth)
                    n_cl = len(set(pred.tolist()))
                    clusters_list.append(n_cl)
                    collapsed.append(n_cl == 1)
                structural_rows.append(
                    {
                        "dataset": ds_name,
                        "encoder": enc_name,
                        "method": meth,
                        "docs": len(docs_list),
                        "collapse_rate": round(float(np.mean(collapsed)), 4),
                        "mean_clusters": round(float(np.mean(clusters_list)), 3),
                    }
                )

    out_dir = OUT / "wave1/clustering"
    write_csv(out_dir / "topic_summary.csv", summary_rows)
    write_csv(out_dir / "realistic_collapse_summary.csv", structural_rows)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave1_topic_clustering",
            "elapsed_sec": round(time.perf_counter() - t_all, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "encoder_meta": encoder_meta,
            "topic_summary": summary_rows,
            "realistic_collapse_summary": structural_rows,
        },
    )
    log(f"[Clustering] Done in {time.perf_counter() - t_all:.2f}s")


if __name__ == "__main__":
    main()

