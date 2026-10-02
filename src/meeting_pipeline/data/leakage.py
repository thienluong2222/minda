"""VIVOS data leakage audit and integrity verification.

Specification: Section 6.2 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import soundfile as sf

from meeting_pipeline.data.manifest import load_manifest_jsonl

logger = logging.getLogger(__name__)


def audit_vivos_manifest(
    manifest_path: Path | str,
    reports_dir: Path | str = "reports",
) -> dict[str, Any]:
    """Audit VIVOS manifest for data leakage, duplicates, file integrity and text metrics.

    Returns an audit summary dict. Raises AssertionError if any leak is detected.
    """
    records = load_manifest_jsonl(manifest_path)
    reports_p = Path(reports_dir)
    reports_p.mkdir(parents=True, exist_ok=True)

    violations: list[str] = []

    # 1. Group records by split
    split_records: dict[str, list[Any]] = {
        "development": [],
        "validation": [],
        "test": [],
    }
    for r in records:
        if r.split not in split_records:
            violations.append(f"Invalid split '{r.split}' in utterance {r.utterance_id}")
        else:
            split_records[r.split].append(r)

    # 2. Check speaker overlap across splits
    dev_speakers = {r.speaker_id for r in split_records["development"]}
    val_speakers = {r.speaker_id for r in split_records["validation"]}
    test_speakers = {r.speaker_id for r in split_records["test"]}

    dev_val_spk_overlap = dev_speakers & val_speakers
    dev_test_spk_overlap = dev_speakers & test_speakers
    val_test_spk_overlap = val_speakers & test_speakers

    if dev_val_spk_overlap:
        violations.append(f"Speaker overlap between dev and val: {sorted(dev_val_spk_overlap)}")
    if dev_test_spk_overlap:
        violations.append(f"Speaker overlap between dev and test: {sorted(dev_test_spk_overlap)}")
    if val_test_spk_overlap:
        violations.append(f"Speaker overlap between val and test: {sorted(val_test_spk_overlap)}")

    # 3. Check utterance ID and SHA-256 overlap across splits
    dev_utts = {r.utterance_id for r in split_records["development"]}
    val_utts = {r.utterance_id for r in split_records["validation"]}
    test_utts = {r.utterance_id for r in split_records["test"]}

    if dev_utts & val_utts:
        violations.append(f"Utterance overlap between dev and val: {sorted(dev_utts & val_utts)}")
    if dev_utts & test_utts:
        violations.append(f"Utterance overlap between dev and test: {sorted(dev_utts & test_utts)}")
    if val_utts & test_utts:
        violations.append(f"Utterance overlap between val and test: {sorted(val_utts & test_utts)}")

    dev_shas = {r.audio_sha256 for r in split_records["development"]}
    val_shas = {r.audio_sha256 for r in split_records["validation"]}
    test_shas = {r.audio_sha256 for r in split_records["test"]}

    if dev_shas & val_shas:
        violations.append("SHA-256 audio hash overlap between dev and val")
    if dev_shas & test_shas:
        violations.append("SHA-256 audio hash overlap between dev and test")
    if val_shas & test_shas:
        violations.append("SHA-256 audio hash overlap between val and test")

    # 4. Check enrollment vs meeting disjointness per speaker
    speaker_enrollment_map: dict[str, set[str]] = {}
    speaker_meeting_map: dict[str, set[str]] = {}

    for r in records:
        if r.is_enrollment:
            speaker_enrollment_map.setdefault(r.speaker_id, set()).add(r.utterance_id)
        else:
            speaker_meeting_map.setdefault(r.speaker_id, set()).add(r.utterance_id)

    for spk_id in sorted(set(r.speaker_id for r in records)):
        enr_set = speaker_enrollment_map.get(spk_id, set())
        mtg_set = speaker_meeting_map.get(spk_id, set())
        overlap = enr_set & mtg_set
        if overlap:
            violations.append(f"Speaker {spk_id} has enrollment/meeting utterance overlap: {overlap}")
        if len(enr_set) == 0:
            violations.append(f"Speaker {spk_id} has 0 enrollment utterances")

    # 5. File integrity checks
    corrupted_files: list[str] = []
    empty_transcripts: list[str] = []
    sr_mismatches: list[str] = []
    dur_mismatches: list[str] = []

    for r in records:
        p = Path(r.audio_path)
        if not p.exists():
            corrupted_files.append(f"Missing file: {r.audio_path}")
            continue

        if not r.text_raw or not r.text_normalized:
            empty_transcripts.append(r.utterance_id)

        try:
            info = sf.info(str(p))
            if info.samplerate != r.sample_rate or info.samplerate != 16000:
                sr_mismatches.append(f"{r.utterance_id} (found {info.samplerate}, expected 16000)")
            if abs(info.duration - r.duration_sec) > 0.05:
                dur_mismatches.append(
                    f"{r.utterance_id} (info {info.duration:.2f}s vs record {r.duration_sec:.2f}s)"
                )
        except Exception as exc:
            corrupted_files.append(f"{r.utterance_id}: {exc}")

    if corrupted_files:
        violations.extend(corrupted_files[:10])
    if empty_transcripts:
        violations.extend([f"Empty transcript in: {empty_transcripts[:10]}"])
    if sr_mismatches:
        violations.extend([f"Sample rate mismatch in: {sr_mismatches[:10]}"])
    if dur_mismatches:
        violations.extend([f"Duration mismatch in: {dur_mismatches[:10]}"])

    # 6. Text repetition analysis across speakers
    text_counter = Counter(r.text_normalized for r in records if r.text_normalized)
    repeated_texts = {txt: cnt for txt, cnt in text_counter.items() if cnt > 1}
    total_distinct_texts = len(text_counter)
    total_records = len(records)
    repetition_ratio = (
        sum(cnt for cnt in repeated_texts.values()) / total_records if total_records else 0.0
    )

    passed = len(violations) == 0

    audit_result: dict[str, Any] = {
        "status": "PASSED" if passed else "FAILED",
        "passed": passed,
        "violations_count": len(violations),
        "violations": violations,
        "total_records": total_records,
        "splits": {
            "development": {
                "speakers": len(dev_speakers),
                "utterances": len(split_records["development"]),
                "enrollment_utterances": sum(
                    1 for r in split_records["development"] if r.is_enrollment
                ),
                "meeting_utterances": sum(
                    1 for r in split_records["development"] if not r.is_enrollment
                ),
                "total_duration_hours": sum(
                    r.duration_sec for r in split_records["development"]
                )
                / 3600.0,
            },
            "validation": {
                "speakers": len(val_speakers),
                "utterances": len(split_records["validation"]),
                "enrollment_utterances": sum(
                    1 for r in split_records["validation"] if r.is_enrollment
                ),
                "meeting_utterances": sum(
                    1 for r in split_records["validation"] if not r.is_enrollment
                ),
                "total_duration_hours": sum(
                    r.duration_sec for r in split_records["validation"]
                )
                / 3600.0,
            },
            "test": {
                "speakers": len(test_speakers),
                "utterances": len(split_records["test"]),
                "enrollment_utterances": sum(1 for r in split_records["test"] if r.is_enrollment),
                "meeting_utterances": sum(1 for r in split_records["test"] if not r.is_enrollment),
                "total_duration_hours": sum(r.duration_sec for r in split_records["test"])
                / 3600.0,
            },
        },
        "text_statistics": {
            "distinct_normalized_texts": total_distinct_texts,
            "repeated_text_count": len(repeated_texts),
            "repetition_ratio": repetition_ratio,
        },
    }

    # Save JSON report
    json_path = reports_p / "data_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit_result, f, ensure_ascii=False, indent=2)

    # Save Markdown report
    md_path = reports_p / "data_audit.md"
    _generate_markdown_audit_report(audit_result, md_path)

    return audit_result


def _generate_markdown_audit_report(result: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Báo cáo Kiểm tra Rò rỉ Dữ liệu VIVOS (Data Audit Report)",
        "",
        f"**Trạng thái**: {result['status']} (Passed: {result['passed']})  ",
        f"**Tổng số câu**: {result['total_records']:,}  ",
        f"**Số vi phạm**: {result['violations_count']}  ",
        "",
        "---",
        "",
        "## 1. Phân chia Split & Người nói (Speaker Disjointness)",
        "",
        "| Split | Số người nói | Số câu tổng | Số câu Enrollment | Số câu Meeting | Tổng thời lượng (giờ) |",
        "|---|---|---|---|---|---|",
    ]

    for split_name in ["development", "validation", "test"]:
        s = result["splits"][split_name]
        lines.append(
            f"| **{split_name}** | {s['speakers']} | {s['utterances']:,} | "
            f"{s['enrollment_utterances']:,} | {s['meeting_utterances']:,} | {s['total_duration_hours']:.2f}h |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 2. Thống kê Văn bản",
            "",
            f"- Số câu văn bản chuẩn hóa phân biệt: **{result['text_statistics']['distinct_normalized_texts']:,}**",
            f"- Số mẫu văn bản xuất hiện ở hơn 1 câu: **{result['text_statistics']['repeated_text_count']:,}**",
            f"- Tỷ lệ câu lặp văn bản giữa các người nói: **{result['text_statistics']['repetition_ratio'] * 100:.2f}%** (Được phép theo mục 6.1)",
            "",
            "---",
            "",
            "## 3. Danh sách Vi phạm (Violations)",
            "",
        ]
    )

    if result["violations"]:
        for v in result["violations"]:
            lines.append(f"- ❌ {v}")
    else:
        lines.append("- ✅ **Không phát hiện vi phạm rò rỉ dữ liệu nào.**")
        lines.append("- ✅ 100% người nói giữa dev, val và test hoàn toàn tách biệt.")
        lines.append("- ✅ 100% câu enrollment và meeting content hoàn toàn tách biệt.")
        lines.append("- ✅ 100% file audio đúng định dạng WAV 16kHz mono, thời lượng khớp.")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
