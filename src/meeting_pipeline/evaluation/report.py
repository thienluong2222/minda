"""Evaluation reporting and markdown table generators.

Specification: Section 13.8 & 21 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_summary_report(
    summary_data: dict[str, Any],
    output_path: Path | str = "reports/metrics/summary.json",
) -> None:
    """Save comprehensive metrics summary JSON."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)


def generate_baseline_comparison_table(
    baseline_metrics: dict[str, dict[str, float]],
    output_path: Path | str = "reports/tables/baselines_comparison.md",
) -> str:
    """Generate Markdown comparison table for fusion baselines F0-F6."""
    lines = [
        "# Bảng So Sánh Các Baseline Dung Hợp Transcript (F0-F6)",
        "",
        "Đánh giá một lần duy nhất trên tập Test độc lập. CER là chỉ số đánh giá chính.",
        "",
        "| Baseline ID | Tên | Mô tả | CER (Chính) ↓ | WER (Phụ) ↓ | S | D | I |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]

    method_descriptions = {
        "F0_FIXED": ("Nguồn cố định", "Chọn transcript từ thiết bị cố định"),
        "F1_BEST_SEGMENT": ("Nguồn tốt nhất", "Chọn nguồn có transcript quality cao nhất"),
        "F2_ORACLE_BEST": ("Oracle cận trên", "Chọn nguồn có CER thấp nhất (tham chiếu)"),
        "F3_ROVER": ("ROVER cơ bản", "Bầu chọn đa số trên confusion network"),
        "F4_ASR_WEIGHTED": ("ASR Weighted", "Bầu chọn theo word confidence PhoWhisper"),
        "F5_RULE_WEIGHTED": ("Rule Weighted", "Bầu chọn kết hợp acoustic, VAD và ASR"),
        "F5_RULE_WEIGHTED_CORRECTED": (
            "Rule Weighted Sửa",
            "Bầu chọn có bảo vệ nguồn chính, chống ảo giác",
        ),
        "F6_LEARNED": ("Learned Fusion", "Logistic Regression dự đoán token chuẩn"),
    }

    for b_id in [
        "F0_FIXED",
        "F1_BEST_SEGMENT",
        "F2_ORACLE_BEST",
        "F3_ROVER",
        "F4_ASR_WEIGHTED",
        "F5_RULE_WEIGHTED",
        "F5_RULE_WEIGHTED_CORRECTED",
        "F6_LEARNED",
    ]:
        if b_id not in baseline_metrics:
            continue
        m = baseline_metrics[b_id]
        name, desc = method_descriptions.get(b_id, (b_id, ""))
        cer_str = f"**{m.get('cer', 0.0) * 100:.2f}%**"
        wer_str = f"{m.get('wer', 0.0) * 100:.2f}%"
        sub = int(m.get("substitutions", 0))
        dels = int(m.get("deletions", 0))
        ins = int(m.get("insertions", 0))
        lines.append(
            f"| `{b_id}` | **{name}** | {desc} | {cer_str} | {wer_str} | {sub} | {dels} | {ins} |"
        )

    content = "\n".join(lines) + "\n"
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return content


def generate_speaker_enrollment_table(
    enrollment_metrics: dict[str, dict[str, float]],
    output_path: Path | str = "reports/tables/speaker_id_by_enrollment.md",
) -> str:
    """Generate Markdown comparison table for speaker ID accuracy by enrollment duration."""
    lines = [
        "# Kết Quả Nhận Dạng Người Nói Theo Thời Lượng Enrollment",
        "",
        "Mô hình: WeSpeaker ResNet34-LM (256-dim) kết hợp Cosine và Quality-Weighting.",
        "",
        "| Enrollment | Accuracy (%) ↑ | Macro Precision ↑ | Macro Recall ↑ | Macro F1 ↑ |",
        "|---|---:|---:|---:|---:|",
    ]

    for dur in ["5s", "15s", "30s"]:
        if dur not in enrollment_metrics:
            continue
        m = enrollment_metrics[dur]
        acc = f"{m.get('accuracy', 0.0) * 100:.2f}%"
        prec = f"{m.get('macro_precision', 0.0):.4f}"
        rec = f"{m.get('macro_recall', 0.0):.4f}"
        f1 = f"**{m.get('macro_f1', 0.0):.4f}**"
        lines.append(f"| **{dur}** | {acc} | {prec} | {rec} | {f1} |")

    content = "\n".join(lines) + "\n"
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return content


def generate_failure_cases_report(
    failure_cases: list[dict[str, Any]],
    output_path: Path | str = "reports/failure_cases/failure_analysis.md",
) -> str:
    """Generate Markdown report analyzing representative failure cases."""
    lines = [
        "# Phân Tích Các Ca Lỗi Điển Hình (Failure Cases Analysis)",
        "",
        "Tập hợp các phân đoạn có CER cao hoặc nhầm lẫn người nói.",
        "",
    ]

    if not failure_cases:
        lines.append("Không có ca lỗi nghiêm trọng nào được ghi nhận.")
    else:
        for idx, case in enumerate(failure_cases[:10]):
            seg_id = case.get("segment_id", "")
            m_id = case.get("meeting_id", "")
            s_t = case.get("start_sec", 0.0)
            e_t = case.get("end_sec", 0.0)
            t_spk = case.get("true_speaker", "")
            p_spk = case.get("pred_speaker", "")
            spk_c = case.get("speaker_confidence", 0.0)
            ref_t = case.get("reference_text", "")
            fused_t = case.get("fused_text", "")
            seg_cer = case.get("cer", 0.0) * 100
            reason = case.get("reason", "Nhiễu nền hoặc tiếng nói ngắn dưới 1.5s")

            lines.extend(
                [
                    f"### Ca lỗi #{idx + 1}: Phân đoạn `{seg_id}`",
                    f"- **Cuộc họp**: `{m_id}`",
                    f"- **Thời gian**: {s_t:.2f}s - {e_t:.2f}s",
                    f"- **Người nói thật (Reference)**: `{t_spk}`",
                    f"- **Người nói dự đoán**: `{p_spk}` (Độ tin cậy: {spk_c:.2f})",
                    f'- **Văn bản chuẩn (Reference)**: "{ref_t}"',
                    f'- **Văn bản dung hợp (Hypothesis)**: "{fused_t}"',
                    f"- **CER của đoạn**: {seg_cer:.2f}%",
                    f"- **Nguyên nhân chính**: {reason}",
                    "",
                ]
            )

    content = "\n".join(lines) + "\n"
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return content
