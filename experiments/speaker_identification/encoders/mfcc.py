"""MFCC 120-dimensional baseline feature extractor."""

from __future__ import annotations

import librosa
import numpy as np

from experiments.speaker_identification.encoders.base import BaseSpeakerEncoder


class MFCCEncoder(BaseSpeakerEncoder):
    """Classical MFCC 120-dim speaker encoder baseline."""

    def __init__(
        self,
        encoder_id: str = "E0",
        sample_rate: int = 16000,
        n_mfcc: int = 20,
        n_fft: int = 512,
        hop_length: int = 160,
    ) -> None:
        self.encoder_id = encoder_id
        self.model_id = "internal/mfcc-120"
        self.model_revision = "internal-v1"
        self.sample_rate = sample_rate
        self.embedding_dimension = 120
        self.n_mfcc = n_mfcc
        self.n_fft = n_fft
        self.hop_length = hop_length

    def _encode_internal(self, waveform: np.ndarray) -> np.ndarray:
        min_samples = self.n_fft + 10 * self.hop_length
        if waveform.size < min_samples:
            waveform = np.pad(waveform, (0, min_samples - waveform.size), mode="constant")

        # Static MFCCs (20, T)
        mfcc = librosa.feature.mfcc(
            y=waveform,
            sr=self.sample_rate,
            n_mfcc=self.n_mfcc,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
        )

        delta_width = min(9, mfcc.shape[-1])
        if delta_width % 2 == 0:
            delta_width -= 1

        if delta_width >= 3:
            delta = librosa.feature.delta(mfcc, width=delta_width)
            delta2 = librosa.feature.delta(mfcc, order=2, width=delta_width)
        else:
            delta = np.zeros_like(mfcc)
            delta2 = np.zeros_like(mfcc)

        # Stack into (60, T)
        feats = np.vstack([mfcc, delta, delta2])
        mean = np.mean(feats, axis=1)  # 60
        std = np.std(feats, axis=1)  # 60
        return np.concatenate([mean, std])  # 120
