"""VIVOS manifest builder and reader.

Specification: Section 5.1 & 6 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import soundfile as sf

from meeting_pipeline.data.vivos import normalize_vietnamese_text, parse_vivos_prompts
from meeting_pipeline.domain.contracts import UtteranceRecord

logger = logging.getLogger(__name__)


def compute_file_sha256(file_path: Path | str) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def scan_vivos_split(
    vivos_split_dir: Path,
    assigned_split: str,
    target_sample_rate: int = 16000,
) -> list[UtteranceRecord]:
    """Scan a VIVOS split directory (e.g. vivos/train or vivos/test)."""
    prompts_path = vivos_split_dir / "prompts.txt"
    waves_dir = vivos_split_dir / "waves"

    if not prompts_path.exists():
        raise FileNotFoundError(f"Missing prompts.txt in {vivos_split_dir}")
    if not waves_dir.exists():
        raise FileNotFoundError(f"Missing waves directory in {vivos_split_dir}")

    prompts = parse_vivos_prompts(prompts_path)
    records: list[UtteranceRecord] = []

    # Iterate over speaker directories
    speaker_dirs = sorted([d for d in waves_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])

    for spk_dir in speaker_dirs:
        speaker_id = spk_dir.name
        wav_files = sorted([w for w in spk_dir.glob("*.wav") if not w.name.startswith(".")])

        for wav_path in wav_files:
            utt_id = wav_path.stem
            text_raw = prompts.get(utt_id, "")
            text_norm = normalize_vietnamese_text(text_raw)

            # Read audio info via soundfile
            info = sf.info(str(wav_path))
            if info.samplerate != target_sample_rate:
                logger.warning(
                    "Utterance %s has sample rate %d != target %d",
                    utt_id,
                    info.samplerate,
                    target_sample_rate,
                )

            sha256 = compute_file_sha256(wav_path)

            record = UtteranceRecord(
                schema_version="1.0",
                utterance_id=utt_id,
                audio_path=str(wav_path),
                audio_sha256=sha256,
                speaker_id=speaker_id,
                text_raw=text_raw,
                text_normalized=text_norm,
                duration_sec=float(info.duration),
                sample_rate=info.samplerate,
                split=assigned_split,  # type: ignore[arg-type]
                is_enrollment=False,
            )
            records.append(record)

    return records


def save_manifest_jsonl(records: list[UtteranceRecord], output_path: Path | str) -> None:
    """Save utterance records to a JSONL file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(record.model_dump_json() + "\n")


def load_manifest_jsonl(manifest_path: Path | str) -> list[UtteranceRecord]:
    """Load utterance records from a JSONL file."""
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    records: list[UtteranceRecord] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            records.append(UtteranceRecord.model_validate(data))
    return records
