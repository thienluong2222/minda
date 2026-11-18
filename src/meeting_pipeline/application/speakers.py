"""Speaker enrollment with voice quality screening, outlier rejection and model compatibility."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from meeting_pipeline.adapters.audio_io import decode_mono
from meeting_pipeline.config import PipelineConfig
from meeting_pipeline.speaker.encoder import (
    DEFAULT_SPEAKER_MODEL_ID,
    DEFAULT_SPEAKER_MODEL_REVISION,
    ECAPAEncoder,
    WeSpeakerEncoder,
    create_speaker_encoder,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SpeakerProfileInput:
    """Named speaker prototype supplied to one pipeline run."""

    speaker_id: str
    display_name: str
    embedding: np.ndarray
    sample_waveforms: tuple[np.ndarray, ...] = ()


def evaluate_sample_quality(
    waveform: np.ndarray[Any, np.dtype[np.float32]],
    sample_rate: int = 16000,
) -> dict[str, Any]:
    """Measure speech duration, clipping, and signal contrast for enrollment samples."""
    total_sec = len(waveform) / sample_rate
    if total_sec == 0:
        return {
            "duration_sec": 0.0,
            "speech_sec": 0.0,
            "clipping_ratio": 0.0,
            "valid": False,
            "reason": "empty_audio",
        }

    # Frame energy contrast for speech detection
    frame_size = int(0.025 * sample_rate)
    hop_size = int(0.010 * sample_rate)
    frames = [
        waveform[i : i + frame_size] for i in range(0, len(waveform) - frame_size + 1, hop_size)
    ]
    if not frames:
        return {
            "duration_sec": total_sec,
            "speech_sec": 0.0,
            "clipping_ratio": 0.0,
            "valid": False,
            "reason": "too_short",
        }

    energies = np.array([float(np.sqrt(np.mean(f**2))) for f in frames])
    noise_floor = float(np.percentile(energies, 10))
    threshold = max(0.005, noise_floor * 3.0)
    speech_frames = energies > threshold
    speech_sec = float(np.sum(speech_frames) * hop_size / sample_rate)

    clipping_ratio = float(np.mean(np.abs(waveform) > 0.99))
    valid = speech_sec >= 0.5

    return {
        "duration_sec": round(total_sec, 3),
        "speech_sec": round(speech_sec, 3),
        "clipping_ratio": round(clipping_ratio, 4),
        "valid": valid,
        "reason": None if valid else "insufficient_speech",
    }


class SpeakerRegistry:
    """Create and load demo profiles with quality screening and cross-encoder migration."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.root = config.paths.data_dir / "speakers"
        self._encoder: ECAPAEncoder | WeSpeakerEncoder | None = None

    def _get_encoder(self) -> ECAPAEncoder | WeSpeakerEncoder:
        if self._encoder is None:
            model_id = str(self.config.identity.get("model_id", DEFAULT_SPEAKER_MODEL_ID))
            revision = str(
                self.config.identity.get("model_revision", DEFAULT_SPEAKER_MODEL_REVISION)
            )
            self._encoder = create_speaker_encoder(
                model_id=model_id,
                revision=revision,
                cache_dir=self.config.paths.model_cache_dir,
            )
        return self._encoder

    def list_profiles(self) -> list[dict[str, object]]:
        profiles = []
        for path in self.root.glob("*/profile.json"):
            try:
                profiles.append(dict(json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return sorted(profiles, key=lambda item: str(item.get("display_name", "")).casefold())

    def enroll(self, display_name: str, samples: list[Path]) -> dict[str, object]:
        name = display_name.strip()
        if not name:
            raise ValueError("Tên người tham gia không được để trống")
        if not samples:
            raise ValueError("Cần ít nhất một mẫu giọng")

        speaker_id = str(uuid.uuid4())
        speaker_dir = self.root / speaker_id
        decoded_dir = speaker_dir / "decoded"
        decoded_dir.mkdir(parents=True, exist_ok=False)

        sample_evals: list[dict[str, Any]] = []
        valid_waveforms: list[np.ndarray[Any, np.dtype[np.float32]]] = []
        embeddings: list[np.ndarray[Any, np.dtype[np.float32]]] = []
        total_seconds = 0.0
        total_speech_seconds = 0.0
        warnings: list[str] = []

        for index, sample in enumerate(samples, start=1):
            decoded = decoded_dir / f"sample-{index}.wav"
            decode_mono(sample, decoded, self.config.audio.analysis_sample_rate)
            waveform, rate = sf.read(decoded, dtype="float32")
            if rate != self.config.audio.analysis_sample_rate:
                continue

            quality = evaluate_sample_quality(waveform, rate)
            sample_evals.append({"sample_file": sample.name, **quality})

            if not quality["valid"]:
                logger.warning("Sample %s skipped: %s", sample.name, quality["reason"])
                continue

            if quality["speech_sec"] < 2.0:
                warnings.append(f"Mẫu {index} có ít hơn 2 giây tiếng nói thực")

            total_seconds += float(quality["duration_sec"])
            total_speech_seconds += float(quality["speech_sec"])
            valid_waveforms.append(waveform)
            embeddings.append(self.encode(waveform))

        if not embeddings:
            raise ValueError(
                "Không có mẫu nào đủ tiếng nói hợp lệ (tối thiểu 0.5 giây giọng nói thực)"
            )

        if len(embeddings) == 1:
            warnings.append("single_sample_low_evidence")

        # Robust centroid with outlier rejection for >= 3 samples
        if len(embeddings) >= 3:
            emb_matrix = np.stack(embeddings)
            sim_matrix = emb_matrix @ emb_matrix.T
            # Average similarity of each sample to others
            mean_sims = (np.sum(sim_matrix, axis=1) - 1.0) / (len(embeddings) - 1)
            keep_mask = mean_sims >= 0.30
            if np.any(keep_mask):
                kept_embeddings = [embeddings[i] for i in range(len(embeddings)) if keep_mask[i]]
            else:
                kept_embeddings = embeddings
        else:
            kept_embeddings = embeddings

        prototype = np.mean(np.stack(kept_embeddings), axis=0)
        prototype /= max(float(np.linalg.norm(prototype)), 1e-12)

        np.save(speaker_dir / "embedding.npy", prototype.astype(np.float32))

        encoder = self._get_encoder()
        profile: dict[str, object] = {
            "speaker_id": speaker_id,
            "display_name": name,
            "sample_count": len(valid_waveforms),
            "total_seconds": round(total_seconds, 3),
            "total_speech_seconds": round(total_speech_seconds, 3),
            "model_id": str(encoder.model_id),
            "model_revision": str(encoder.revision),
            "embedding_dimension": int(encoder.embedding_dimension),
            "sample_evaluations": sample_evals,
            "warnings": list(dict.fromkeys(warnings)),
        }
        (speaker_dir / "profile.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return profile

    def load(self, speaker_ids: list[str]) -> list[SpeakerProfileInput]:
        profiles = []
        encoder = self._get_encoder()
        target_dim = encoder.embedding_dimension

        for speaker_id in speaker_ids:
            speaker_dir = self.root / speaker_id
            metadata_path = speaker_dir / "profile.json"
            embedding_path = speaker_dir / "embedding.npy"
            if not metadata_path.is_file() or not embedding_path.is_file():
                continue

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            saved_emb = np.asarray(np.load(embedding_path), dtype=np.float32)

            samples: list[np.ndarray] = []
            decoded_dir = speaker_dir / "decoded"
            if decoded_dir.is_dir():
                for sample_path in sorted(decoded_dir.glob("sample-*.wav")):
                    try:
                        wave, rate = sf.read(sample_path, dtype="float32")
                        if rate == self.config.audio.analysis_sample_rate and wave.ndim == 1:
                            samples.append(wave)
                    except Exception:
                        pass

            # Equal dimensions do not imply the same model or embedding space.
            incompatible = (
                saved_emb.shape != (target_dim,)
                or metadata.get("model_id") != encoder.model_id
                or metadata.get("model_revision") != encoder.revision
            )
            if incompatible:
                valid_samples = [
                    wave
                    for wave in samples
                    if evaluate_sample_quality(wave, self.config.audio.analysis_sample_rate)[
                        "valid"
                    ]
                ]
                if valid_samples:
                    logger.info(
                        "Re-encoding speaker %s (%s) from raw audio for current encoder dimension"
                        " %d",
                        speaker_id,
                        metadata.get("display_name"),
                        target_dim,
                    )
                    re_embs = [self.encode(w) for w in valid_samples]
                    if len(re_embs) >= 3:
                        matrix = np.stack(re_embs)
                        keep = (np.sum(matrix @ matrix.T, axis=1) - 1.0) / (
                            len(re_embs) - 1
                        ) >= 0.30
                        if np.any(keep):
                            re_embs = [
                                emb for emb, accepted in zip(re_embs, keep, strict=True) if accepted
                            ]
                    prototype = np.mean(np.stack(re_embs), axis=0)
                    norm = float(np.linalg.norm(prototype))
                    if (
                        prototype.shape != (target_dim,)
                        or not np.all(np.isfinite(prototype))
                        or norm < 1e-8
                    ):
                        raise ValueError(
                            "Encoder trả về embedding không hợp lệ; hồ sơ gốc được giữ nguyên."
                        )
                    prototype /= norm
                    saved_emb = prototype.astype(np.float32)
                    old_metadata = metadata_path.read_bytes()
                    old_embedding = embedding_path.read_bytes()
                    fingerprint = hashlib.sha256(old_metadata + old_embedding).hexdigest()[:16]
                    backup = speaker_dir / "encoder_backups" / fingerprint
                    backup.mkdir(parents=True, exist_ok=True)
                    (backup / "profile.json").write_bytes(old_metadata)
                    (backup / "embedding.npy").write_bytes(old_embedding)
                    metadata.update(
                        model_id=encoder.model_id,
                        model_revision=encoder.revision,
                        embedding_dimension=target_dim,
                    )
                    token = uuid.uuid4().hex
                    temporary_embedding = embedding_path.with_suffix(f".npy.{token}.tmp")
                    temporary_metadata = metadata_path.with_suffix(f".json.{token}.tmp")
                    try:
                        with temporary_embedding.open("wb") as handle:
                            np.save(handle, saved_emb)
                        temporary_metadata.write_text(
                            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8",
                        )
                        temporary_embedding.replace(embedding_path)
                        temporary_metadata.replace(metadata_path)
                    finally:
                        temporary_embedding.unlink(missing_ok=True)
                        temporary_metadata.unlink(missing_ok=True)
                else:
                    d_name = metadata.get("display_name")
                    raise ValueError(
                        f"Hồ sơ '{d_name}' không khớp encoder hiện tại ({target_dim}D) "
                        "và thiếu mẫu âm thanh hợp lệ để tạo lại embedding. "
                        f"Vui lòng đăng ký lại mẫu cho model này."
                    )

            profiles.append(
                SpeakerProfileInput(
                    speaker_id,
                    str(metadata["display_name"]),
                    saved_emb,
                    sample_waveforms=tuple(samples),
                )
            )
        return profiles

    def encode(self, waveform: np.ndarray) -> np.ndarray:
        """Encode waveform using configured speaker encoder."""
        return self._get_encoder().encode(waveform)
