"""Unit tests for VIVOS text normalization, splitting and leakage audit (Milestone 2)."""

from pathlib import Path

from meeting_pipeline.data.leakage import audit_vivos_manifest
from meeting_pipeline.data.manifest import load_manifest_jsonl
from meeting_pipeline.data.vivos import normalize_vietnamese_text, parse_vivos_prompts


def test_vietnamese_text_normalization() -> None:
    # Test lowercase, accent preservation, punctuation removal, whitespace collapsing
    raw = "  ĐÂY LÀ VÍ DỤ: Tiếng Việt có dấu, 123...  "
    norm = normalize_vietnamese_text(raw)
    assert norm == "đây là ví dụ tiếng việt có dấu 123"

    # Test empty or none
    assert normalize_vietnamese_text("") == ""

    # Test all Vietnamese vowels with tones
    accents = (
        "Á À Ả Ã Ạ Ă Ắ Ằ Ẳ Ẵ Ặ Â Ấ Ầ Ẩ Ẫ Ậ É È Ẻ Ẽ Ẹ Ê Ế Ề Ể Ễ Ệ "
        "Í Ì Ỉ Ĩ Ị Ó Ò Ỏ Õ Ọ Ô Ố Ồ Ổ Ỗ Ộ Ơ Ớ Ờ Ở Ỡ Ợ Ú Ù Ủ Ũ Ụ "
        "Ư Ứ Ừ Sử Ữ Ự Ý Ỳ Ỷ Ỹ Ỵ Đ"
    )
    norm_accents = normalize_vietnamese_text(accents)
    assert "đ" in norm_accents
    assert "ă" in norm_accents
    assert "ư" in norm_accents
    assert "ê" in norm_accents


def test_parse_vivos_prompts_file(tmp_path: Path) -> None:
    p_file = tmp_path / "prompts.txt"
    p_file.write_text(
        "VIVOSSPK01_001 XIN CHÀO CÁC BẠN\nVIVOSSPK01_002 TÔI ĐI HỌC\n",
        encoding="utf-8",
    )
    prompts = parse_vivos_prompts(p_file)
    assert len(prompts) == 2
    assert prompts["VIVOSSPK01_001"] == "XIN CHÀO CÁC BẠN"
    assert prompts["VIVOSSPK01_002"] == "TÔI ĐI HỌC"


def test_vivos_manifest_on_disk() -> None:
    manifest_path = Path("data/manifests/vivos.jsonl")
    assert manifest_path.exists(), "vivos.jsonl should have been generated"
    records = load_manifest_jsonl(manifest_path)
    assert len(records) == 12420

    dev_records = [r for r in records if r.split == "development"]
    val_records = [r for r in records if r.split == "validation"]
    test_records = [r for r in records if r.split == "test"]

    assert len(dev_records) > 0
    assert len(val_records) > 0
    assert len(test_records) > 0

    # Verify speaker disjointness
    dev_spks = {r.speaker_id for r in dev_records}
    val_spks = {r.speaker_id for r in val_records}
    test_spks = {r.speaker_id for r in test_records}

    assert dev_spks.isdisjoint(val_spks)
    assert dev_spks.isdisjoint(test_spks)
    assert val_spks.isdisjoint(test_spks)


def test_audit_manifest_passes() -> None:
    manifest_path = Path("data/manifests/vivos.jsonl")
    res = audit_vivos_manifest(manifest_path, reports_dir="reports")
    assert res["passed"] is True
    assert res["violations_count"] == 0
