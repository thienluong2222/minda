"""Four text encoders x four clusterers on template-generated meeting topics."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    OUT,
    SEED,
    log,
    read_json,
    rss_mb,
    setup,
    snapshot,
    write_csv,
    write_json,
)

ENCODERS = {
    "e5_small": "intfloat/multilingual-e5-small",
    "e5_base": "intfloat/multilingual-e5-base",
    "minilm": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "bge_m3": "BAAI/bge-m3",
}
TEMPLATES = {
    "budget": [
        "Dự toán mua thiết bị cho {project} cần giảm xuống {amount} triệu đồng.",
        "Khoản thanh toán của {project} phải có hóa đơn trước ngày {day} tháng mười một.",
        "Phòng kế toán đề nghị kiểm tra lại nguồn kinh phí của {project} trong tháng này.",
        "Chi phí duy trì {project} đang vượt mức đã được phê duyệt trong quý trước.",
        "Đề nghị chuyển {amount} triệu đồng từ nguồn dự phòng sang khoản thuê dịch vụ của {project}.",
        "Nhóm thống nhất chỉ giải ngân cho {project} khi đã hoàn tất thủ tục đối chiếu công nợ.",
        "Đơn giá hợp đồng của {project} chưa bao gồm thuế nên cần tính lại tổng số phải trả.",
        "Chứng từ quyết toán của {project} còn thiếu phần xác nhận tiền tạm ứng từ đợt trước.",
        "Số dư tài khoản dành cho {project} chỉ còn {amount} triệu đồng, chưa đủ thanh toán nhà cung cấp.",
    ],
    "infrastructure": [
        "Máy chủ phục vụ {project} cần được sao lưu trước ngày {day} tháng mười một.",
        "Tổ kỹ thuật đề nghị thay ổ cứng bị lỗi để bảo đảm dữ liệu của {project} được an toàn.",
        "Đường truyền mạng của {project} thường mất kết nối vào giờ cao điểm sử dụng.",
        "Bản nâng cấp phần mềm của {project} phải được thử trên môi trường dự phòng trước khi cài đặt.",
        "Quyền truy cập hệ thống {project} cần được rà soát vì một số tài khoản vẫn dùng mật khẩu cũ.",
        "Bộ lưu điện tại phòng máy của {project} chỉ duy trì được nguồn trong mười phút.",
        "Nhật ký vận hành cho thấy cơ sở dữ liệu của {project} bị nghẽn khi có nhiều kết nối đồng thời.",
        "Nhóm đề xuất cấu hình bản sao dự phòng cho {project} để khôi phục khi máy chính gặp sự cố.",
        "Thiết bị định tuyến của {project} cần cập nhật bản vá trước khi mở lại cổng truy cập từ bên ngoài.",
    ],
    "staffing": [
        "Nhóm phụ trách {project} đang thiếu người trực hỗ trợ vào cuối tuần trong tháng này.",
        "Chị {person} sẽ tiếp nhận bàn giao nhân sự của {project} từ ngày {day} tháng mười một.",
        "Phòng tổ chức đề nghị bổ sung hai vị trí chuyên môn cho nhóm thực hiện {project}.",
        "Lịch nghỉ của các thành viên trong {project} bị trùng nhau nên cần sắp xếp lại ca trực.",
        "Anh {person} cần được hướng dẫn công việc trước khi thay người phụ trách liên hệ của {project}.",
        "Đề nghị tuyển thêm một cộng tác viên có kinh nghiệm để hỗ trợ nhóm {project} trong đợt cao điểm.",
        "Tổ thực hiện {project} cần phân công rõ người chịu trách nhiệm phản hồi yêu cầu vào buổi tối.",
        "Việc điều chuyển {person} sang bộ phận khác khiến nhóm {project} phải tìm người nhận bàn giao.",
        "Các thành viên mới tham gia {project} cần hoàn thành khóa hướng dẫn nghiệp vụ trước khi nhận nhiệm vụ.",
    ],
    "schedule": [
        "Mốc nghiệm thu {project} được chuyển sang ngày {day} tháng mười một theo đề nghị của các bên.",
        "Tiến độ hoàn thành {project} đang chậm hai tuần so với kế hoạch đã thống nhất trước đó.",
        "Nhóm cần gửi báo cáo kết quả của {project} trước phiên họp kiểm tra vào tuần tới.",
        "Giai đoạn thử nghiệm {project} chỉ bắt đầu sau khi toàn bộ hồ sơ bàn giao được xác nhận.",
        "Các bên thống nhất lùi buổi trình bày kết quả {project} để có thêm thời gian kiểm tra sản phẩm.",
        "Đề nghị tách {project} thành hai đợt nghiệm thu nhằm tránh chậm thời hạn hoàn thành chung.",
        "Hạng mục cuối của {project} phải được hoàn tất trước ngày {day} để kịp tổ chức cuộc họp tổng kết.",
        "Lịch kiểm tra {project} cần điều chỉnh vì đơn vị phối hợp chưa gửi kết quả thực hiện đúng hạn.",
        "Thời gian chạy thử {project} được kéo dài thêm một tuần trước khi chuyển sang giai đoạn bàn giao chính thức.",
    ],
}
QUERIES = {
    "budget": "Nguồn kinh phí, số tiền phải trả và thủ tục thanh toán được bàn như thế nào?",
    "infrastructure": "Máy chủ, kết nối mạng, sao lưu và bảo vệ hệ thống cần xử lý những việc gì?",
    "staffing": "Ai được phân công, cần bổ sung người nào và bố trí ca trực ra sao?",
    "schedule": "Thời hạn, tiến độ, mốc nghiệm thu và lịch bàn giao thay đổi như thế nào?",
}


def prepare():
    import numpy as np

    rng = np.random.default_rng(SEED)
    docs = []
    for split, count, offset in (("development", 3, 0), ("validation", 9, 3), ("test", 30, 6)):
        for index in range(count):
            project = (
                "cổng thông tin",
                "thư viện số",
                "phòng học thông minh",
                "hệ thống điều hành",
            )[index % 4]
            units = []
            for label, templates in TEMPLATES.items():
                for repeat in range(4):
                    template = templates[offset + repeat % 3]
                    text = template.format(
                        project=project,
                        amount=int(rng.integers(20, 150)),
                        day=int(rng.integers(5, 28)),
                        person=("Minh", "Lan", "Hà", "Dũng")[int(rng.integers(4))],
                    )
                    units.append(
                        {
                            "text": text,
                            "topic": label,
                            "template_id": f"{label}_{offset + repeat % 3}",
                        }
                    )
            rng.shuffle(units)
            for i, unit in enumerate(units):
                unit["id"] = f"{split}_{index:03d}_u{i:02d}"
            docs.append(
                {
                    "id": f"{split}_{index:03d}",
                    "split": split,
                    "units": units,
                    "queries": [{"text": text, "topic": label} for label, text in QUERIES.items()],
                }
            )
    write_json(OUT / "text/manifest.json", docs)
    write_json(
        OUT / "text/protocol.json",
        {
            "evidence": "scripted_meeting_units_with_topic_labels_known_by_construction",
            "not_human_annotated_meetings": True,
            "template_ids_disjoint_across_splits": True,
            "held_out_test_templates": True,
            "topics": list(TEMPLATES),
            "max_clusters": 4,
            "FCM_current": {"fuzziness": 1.3, "minimum_silhouette": 0.08},
            "fine_tuning_limit": "template performance is a diagnostic, not evidence that real-meeting fine-tuning is necessary",
            "retrieval_gold": "topic_relevance_not_fact_entailment",
            "retrieval_top_k": 2,
            "no_LLM_inference": True,
        },
    )


def encode(name, texts, retrieval_passages=False):
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    path = snapshot(ENCODERS[name])
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModel.from_pretrained(path, local_files_only=True).eval()
    vectors = []
    timing = []
    for index in range(0, len(texts), 16):
        batch_text = texts[index : index + 16]
        if name.startswith("e5"):
            prefix = "passage: " if retrieval_passages else "query: "
            batch_text = [prefix + text for text in batch_text]
        batch = tokenizer(batch_text, padding=True, truncation=False, return_tensors="pt")
        if batch["input_ids"].shape[1] > 128 and name == "minilm":
            raise ValueError(
                "MiniLM comparison input exceeds its native sentence-transformer limit"
            )
        if batch["input_ids"].shape[1] > 512:
            raise ValueError("Unexpected oversized synthetic text")
        start = time.perf_counter()
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
            if name == "bge_m3":
                embedding = hidden[:, 0]
            else:
                mask = batch["attention_mask"].unsqueeze(-1)
                embedding = (hidden * mask).sum(1) / mask.sum(1)
            embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)
        timing.append(time.perf_counter() - start)
        vectors.append(embedding.numpy())
    return np.concatenate(vectors), {
        "batch_seconds": sum(timing),
        "samples": len(texts),
        "peak_rss_mb": rss_mb(),
        "revision": path.name,
        "pooling": "CLS" if name == "bge_m3" else "attention_mask_mean",
        "prefix": "passage" if retrieval_passages else "query" if name.startswith("e5") else None,
    }


def cluster(vectors, method):
    import numpy as np
    from sklearn.cluster import HDBSCAN, AgglomerativeClustering, KMeans
    from sklearn.metrics import silhouette_score

    from meeting_pipeline.minutes.topic_clustering import cluster_topics

    if method == "fcm":
        return np.asarray(
            cluster_topics(
                vectors.tolist(), max_clusters=4, fuzziness=1.3, minimum_silhouette=0.08
            )["primary"]
        )
    if method == "hdbscan":
        labels = HDBSCAN(min_cluster_size=3, min_samples=2, metric="euclidean").fit_predict(vectors)
        keep = sorted(set(labels) - {-1})
        if not keep:
            return np.zeros(len(vectors), dtype=int)
        for index in np.where(labels == -1)[0]:
            centroids = np.stack([vectors[labels == label].mean(axis=0) for label in keep])
            labels[index] = keep[int(np.argmax(centroids @ vectors[index]))]
        return labels
    best = None
    for k in (2, 3, 4):
        labels = (
            KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(vectors)
            if method == "kmeans"
            else AgglomerativeClustering(
                n_clusters=k, metric="cosine", linkage="average"
            ).fit_predict(vectors)
        )
        sizes = np.bincount(labels)
        if min(sizes) < 2:
            continue
        silhouette = float(silhouette_score(vectors, labels, metric="cosine"))
        if silhouette >= 0.08 and (best is None or silhouette > best[0]):
            best = (silhouette, labels)
    return best[1] if best is not None else np.zeros(len(vectors), dtype=int)


def run(name):
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score

    docs = read_json(OUT / "text/manifest.json")
    texts = [u["text"] for d in docs for u in d["units"]]
    vectors, runtime = encode(name, texts)
    destination = OUT / "text" / name
    destination.mkdir(parents=True, exist_ok=True)
    np.save(destination / "vectors.npy", vectors)
    write_json(destination / "runtime.json", runtime)
    rows = []
    cursor = 0
    for doc in docs:
        matrix = vectors[cursor : cursor + len(doc["units"])]
        cursor += len(doc["units"])
        labels = [list(TEMPLATES).index(u["topic"]) for u in doc["units"]]
        oracle = KMeans(n_clusters=4, n_init=10, random_state=SEED).fit_predict(matrix)
        for method in ("fcm", "kmeans", "agglomerative", "hdbscan"):
            start = time.perf_counter()
            prediction = cluster(matrix, method)
            elapsed = time.perf_counter() - start
            n = len(set(prediction.tolist()))
            rows.append(
                {
                    "document": doc["id"],
                    "split": doc["split"],
                    "encoder": name,
                    "clusterer": method,
                    "ari": float(adjusted_rand_score(labels, prediction)),
                    "nmi": float(normalized_mutual_info_score(labels, prediction)),
                    "clusters": n,
                    "collapsed_to_one": n == 1,
                    "oracle_k4_ari_diagnostic": float(adjusted_rand_score(labels, oracle)),
                    "silhouette": float(silhouette_score(matrix, prediction, metric="cosine"))
                    if 1 < n < len(matrix)
                    else None,
                    "clustering_seconds": elapsed,
                }
            )
    write_csv(destination / "per_document.csv", rows)
    summaries = []
    for split in ("validation", "test"):
        for method in ("fcm", "kmeans", "agglomerative", "hdbscan"):
            selected = [r for r in rows if r["split"] == split and r["clusterer"] == method]
            summaries.append(
                {
                    "encoder": name,
                    "clusterer": method,
                    "split": split,
                    "documents": len(selected),
                    "ari": float(np.mean([r["ari"] for r in selected])),
                    "nmi": float(np.mean([r["nmi"] for r in selected])),
                    "collapse_rate": float(np.mean([r["collapsed_to_one"] for r in selected])),
                    "oracle_k4_ari_diagnostic": float(
                        np.mean([r["oracle_k4_ari_diagnostic"] for r in selected])
                    ),
                }
            )
    write_json(destination / "summary.json", summaries)
    write_csv(destination / "summary.csv", summaries)
    log(f"{name}: text encoder x four clusterers finished")
    if name == "e5_small":
        retrieval(docs)


def retrieval(docs):
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn, TurnSearchIndex

    texts = [u["text"] for d in docs for u in d["units"]]
    documents, _ = encode("e5_small", texts, retrieval_passages=True)
    queries, _ = encode("e5_small", [q["text"] for d in docs for q in d["queries"]])
    rows = []
    cursor = query_cursor = 0
    for doc in docs:
        matrix = documents[cursor : cursor + len(doc["units"])]
        cursor += len(doc["units"])
        turns = [
            IndexedTurn(
                turn_id=u["id"],
                speaker_label="simulated",
                speaker_id=None,
                start_sec=float(i),
                end_sec=float(i + 1),
                text=u["text"],
                tokens=u["text"].lower().split(),
                source_id="synthetic_text_only",
                clip_path=None,
                asr_status="transcribed",
                needs_review=False,
                confidence=None,
            )
            for i, u in enumerate(doc["units"])
        ]
        # Use the production tokenizer exactly for the BM25 baseline.
        from meeting_pipeline.minutes.evidence_retrieval import _tokenize

        for turn in turns:
            turn.tokens = _tokenize(turn.text)
        bm25 = TurnSearchIndex(turns)
        tfidf = TfidfVectorizer().fit([u["text"] for u in doc["units"]])
        sparse = tfidf.transform([u["text"] for u in doc["units"]])
        for query in doc["queries"]:
            vector = queries[query_cursor]
            query_cursor += 1
            dense = np.argsort(-(matrix @ vector)).tolist()
            lexical = [
                next(i for i, u in enumerate(doc["units"]) if u["id"] == t.turn_id)
                for t, _ in bm25.search(query["text"], top_k=len(turns))
            ]
            lexical += [i for i in range(len(turns)) if i not in lexical]
            tf_order = np.argsort(
                -(sparse @ tfidf.transform([query["text"]]).T).toarray().ravel()
            ).tolist()
            score = np.zeros(len(turns))
            for ranking in (lexical, dense):
                for rank, index in enumerate(ranking):
                    score[index] += 1 / (60 + rank + 1)
            hybrid = np.argsort(-score).tolist()
            gold = {i for i, u in enumerate(doc["units"]) if u["topic"] == query["topic"]}
            for method, ranking in (
                ("bm25", lexical),
                ("tfidf", tf_order),
                ("e5_dense", dense),
                ("hybrid_rrf", hybrid),
            ):
                relevant = [int(i in gold) for i in ranking]
                rows.append(
                    {
                        "document": doc["id"],
                        "split": doc["split"],
                        "method": method,
                        "topic": query["topic"],
                        "hit_at_2": float(any(relevant[:2])),
                        "recall_at_2": sum(relevant[:2]) / len(gold),
                        "mrr": 1 / (relevant.index(1) + 1),
                        "relevance_scope": "scripted_topic_not_fact_entailment",
                    }
                )
    summary = []
    for method in ("bm25", "tfidf", "e5_dense", "hybrid_rrf"):
        selected = [r for r in rows if r["method"] == method and r["split"] == "test"]
        summary.append(
            {
                "method": method,
                "queries": len(selected),
                **{
                    key: float(np.mean([r[key] for r in selected]))
                    for key in ("hit_at_2", "recall_at_2", "mrr")
                },
            }
        )
    write_json(OUT / "retrieval/summary.json", summary)
    write_csv(OUT / "retrieval/summary.csv", summary)
    write_csv(OUT / "retrieval/per_query.csv", rows)


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--encoder", choices=list(ENCODERS))
    args = parser.parse_args()
    prepare() if args.command == "prepare" else run(args.encoder)


if __name__ == "__main__":
    main()
