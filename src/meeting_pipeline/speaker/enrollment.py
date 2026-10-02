"""Speaker enrollment prototype extraction using SpeechBrain ECAPA-TDNN.

Specification: Section 10.1 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import soundfile as sf

from meeting_pipeline.domain.contracts import UtteranceRecord
from meeting_pipeline.speaker.encoder import ECAPAEncoder

logger = logging.getLogger(__name__)


def build_speaker_prototypes(
    speaker_ids: list[str],
    enrollment_catalog: dict[str, list[str]],
    manifest_records: list[UtteranceRecord],
    target_duration_sec: float = 30.0,
    encoder: ECAPAEncoder | None = None,
) -> dict[str, np.ndarray[Any, np.dtype[np.float32]]]:
    """Extract and build L2-normalized prototype embedding for each speaker."""
    if encoder is None:
        encoder = ECAPAEncoder()

    utt_lookup = {r.utterance_id: r for r in manifest_records}
    prototypes: dict[str, np.ndarray[Any, np.dtype[np.float32]]] = {}

    for spk_id in sorted(speaker_ids):
        enr_utt_ids = enrollment_catalog.get(spk_id, [])
        embeddings: list[np.ndarray[Any, np.dtype[np.float32]]] = []
        accumulated_dur = 0.0

        for utt_id in enr_utt_ids:
            if accumulated_dur >= target_duration_sec and len(embeddings) > 0:
                break
            record = utt_lookup.get(utt_id)
            if record is None:
                continue

            try:
                audio_data, _ = sf.read(record.audio_path, dtype="float32")
                if len(audio_data) < 1600:  # < 0.1s
                    continue
                emb = encoder.encode(audio_data)
                embeddings.append(emb)
                accumulated_dur += record.duration_sec
            except Exception as exc:
                logger.warning("Failed to extract embedding for %s: %s", utt_id, exc)

        if not embeddings:
            logger.warning("No embeddings extracted for speaker %s; using random prototype", spk_id)
            dummy = np.random.normal(0, 1, 192).astype(np.float32)
            dummy = dummy / float(np.linalg.norm(dummy))
            prototypes[spk_id] = dummy
        else:
            mean_emb = np.mean(embeddings, axis=0).astype(np.float32)
            norm = float(np.linalg.norm(mean_emb))
            if norm > 1e-8:
                mean_emb = mean_emb / norm
            prototypes[spk_id] = mean_emb

    return prototypes
