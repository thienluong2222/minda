"""Speaker identification classifiers: ECAPA-TDNN and MFCC + KNN."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import librosa
import numpy as np
from sklearn.neighbors import KNeighborsClassifier  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from meeting_pipeline.application.speakers import SpeakerProfileInput


class BaseSpeakerClassifier(ABC):
    """Abstract interface for meeting speaker classifiers."""

    @abstractmethod
    def assign_speaker(self, waveform: np.ndarray, excluded: set[str]) -> dict[str, object]:
        """Assign speaker identity or cluster to a speech waveform."""
        raise NotImplementedError


class ECAPASpeakerClassifier(BaseSpeakerClassifier):
    """Deep learning speaker verification using ECAPA-TDNN embeddings and Cosine similarity."""

    def __init__(
        self,
        encoder: Any,
        profiles: list[SpeakerProfileInput],
        identity_threshold: float = 0.25,
        identity_margin: float = 0.05,
        anonymous_cluster_threshold: float = 0.10,
        max_anonymous: int = 8,
        sample_rate: int = 16000,
    ) -> None:
        self.encoder = encoder
        self.profiles = profiles
        self.identity_threshold = identity_threshold
        self.identity_margin = identity_margin
        self.anonymous_cluster_threshold = anonymous_cluster_threshold
        self.max_anonymous = max_anonymous
        self.sample_rate = sample_rate

        self._anonymous_centroids: list[np.ndarray] = []
        self._anonymous_counts: list[int] = []

    def assign_speaker(self, waveform: np.ndarray, excluded: set[str]) -> dict[str, object]:
        if waveform.size < self.sample_rate:
            waveform = np.pad(waveform, (0, self.sample_rate - waveform.size))

        embedding = self.encoder.encode(waveform)
        ranked = sorted(
            (
                (profile, float(np.dot(embedding, profile.embedding)))
                for profile in self.profiles
                if profile.speaker_id not in excluded
            ),
            key=lambda item: item[1],
            reverse=True,
        )

        threshold = self.identity_threshold
        margin = self.identity_margin

        if ranked:
            best_profile, best_score = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
            if best_score >= threshold and best_score - runner_up >= margin:
                actual_margin = best_score - runner_up
                return {
                    "speaker_id": best_profile.speaker_id,
                    "profile_id": best_profile.speaker_id,
                    "speaker_label": best_profile.display_name,
                    "speaker_status": "identified",
                    "speaker_match_score": best_score,
                    "speaker_top_candidates": [
                        {"speaker_id": profile.speaker_id, "cosine_score": score}
                        for profile, score in ranked[:3]
                    ],
                    "identity_decision_reason": (
                        f"identified: score={best_score:.3f} >= threshold={threshold:.2f}, "
                        f"margin={actual_margin:.3f} >= min_margin={margin:.2f}"
                    ),
                    "warnings": [],
                }

        # Build reason for why enrollment failed (if profiles exist)
        if ranked:
            best_profile, best_score = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
            score_cmp = (
                f"< threshold={threshold:.2f}"
                if best_score < threshold
                else f">= threshold={threshold:.2f}"
            )
            margin_diff = best_score - runner_up
            margin_cmp = (
                f"< min_margin={margin:.2f}"
                if margin_diff < margin
                else f">= min_margin={margin:.2f}"
            )
            enrollment_reason = (
                f"enrollment_rejected: best_score={best_score:.3f} {score_cmp}, "
                f"margin={margin_diff:.3f} {margin_cmp}"
            )
        else:
            enrollment_reason = "no_enrollment_profiles"

        anonymous_scores = [
            float(np.dot(embedding, centroid)) if f"anonymous-{index + 1}" not in excluded else -1.0
            for index, centroid in enumerate(self._anonymous_centroids)
        ]
        best_anonymous = int(np.argmax(anonymous_scores)) if anonymous_scores else -1
        anonymous_threshold = self.anonymous_cluster_threshold
        should_reuse = best_anonymous >= 0 and (
            anonymous_scores[best_anonymous] >= anonymous_threshold
            or len(self._anonymous_centroids) >= self.max_anonymous
        )

        if should_reuse:
            count = self._anonymous_counts[best_anonymous]
            centroid = (self._anonymous_centroids[best_anonymous] * count + embedding) / (count + 1)
            self._anonymous_centroids[best_anonymous] = centroid / max(
                float(np.linalg.norm(centroid)), 1e-12
            )
            self._anonymous_counts[best_anonymous] += 1
            anonymous_index = best_anonymous
            score: float | None = anonymous_scores[best_anonymous]
            cluster_reason = (
                f"cluster_reuse: score={anonymous_scores[best_anonymous]:.3f} "
                f">= threshold={anonymous_threshold:.2f}"
            )
            if anonymous_scores[best_anonymous] < anonymous_threshold:
                cluster_reason = (
                    f"cluster_forced: score={anonymous_scores[best_anonymous]:.3f} "
                    f"< threshold={anonymous_threshold:.2f}, "
                    f"but max_clusters={self.max_anonymous} reached"
                )
        else:
            self._anonymous_centroids.append(embedding)
            self._anonymous_counts.append(1)
            anonymous_index = len(self._anonymous_centroids) - 1
            score = None
            if best_anonymous >= 0:
                cluster_reason = (
                    f"new_cluster: best_anonymous_score={anonymous_scores[best_anonymous]:.3f} "
                    f"< threshold={anonymous_threshold:.2f}"
                )
            else:
                cluster_reason = "new_cluster: first_speaker"

        anonymous_id = f"anonymous-{anonymous_index + 1}"
        return {
            "speaker_id": anonymous_id,
            "profile_id": None,
            "speaker_label": f"Speaker {anonymous_index + 1}",
            "speaker_status": "unknown",
            "speaker_match_score": score,
            "speaker_top_candidates": [
                {"speaker_id": profile.speaker_id, "cosine_score": profile_score}
                for profile, profile_score in ranked[:3]
            ],
            "identity_decision_reason": f"{enrollment_reason} → {cluster_reason}",
            "warnings": ["speaker_not_enrolled_or_below_threshold"],
        }


def extract_mfcc_feature_vector(
    waveform: np.ndarray,
    sr: int = 16000,
    n_mfcc: int = 20,
    n_fft: int = 512,
    hop_length: int = 160,
) -> np.ndarray:
    """Extract a 120-dim vector: MFCC, Delta, Delta-Delta pooled with Mean & Std."""
    if waveform.ndim > 1:
        waveform = waveform.squeeze()
    min_samples = n_fft + 10 * hop_length
    if waveform.size < min_samples:
        waveform = np.pad(waveform, (0, min_samples - waveform.size))

    # Compute static MFCCs (n_mfcc, T)
    mfcc = librosa.feature.mfcc(
        y=waveform, sr=sr, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop_length
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
    # Statistical segment pooling across time frames
    mean = np.mean(feats, axis=1)  # 60
    std = np.std(feats, axis=1)  # 60
    vec = np.concatenate([mean, std])  # 120

    norm = float(np.linalg.norm(vec))
    return vec / max(norm, 1e-12)


class MFCCKNNSpeakerClassifier(BaseSpeakerClassifier):
    """Classical speaker recognition using 120-dimensional MFCC features and K-Nearest Neighbors."""

    def __init__(
        self,
        profiles: list[SpeakerProfileInput],
        n_neighbors: int = 5,
        metric: str = "cosine",
        identity_threshold: float = 0.25,
        identity_margin: float = 0.05,
        anonymous_cluster_threshold: float = 0.10,
        max_anonymous: int = 8,
        sample_rate: int = 16000,
        n_mfcc: int = 20,
        window_sec: float = 1.5,
        step_sec: float = 0.5,
    ) -> None:
        self.profiles = profiles
        self.n_neighbors = n_neighbors
        self.metric = metric
        self.identity_threshold = identity_threshold
        self.identity_margin = identity_margin
        self.anonymous_cluster_threshold = anonymous_cluster_threshold
        self.max_anonymous = max_anonymous
        self.sample_rate = sample_rate
        self.n_mfcc = n_mfcc
        self.window_sec = window_sec
        self.step_sec = step_sec

        self._anonymous_centroids: list[np.ndarray] = []
        self._anonymous_counts: list[int] = []

        # Training data
        self._X_train: list[np.ndarray] = []
        self._y_train: list[str] = []
        self._profile_map: dict[str, SpeakerProfileInput] = {p.speaker_id: p for p in profiles}
        self._profile_centroids: dict[str, np.ndarray] = {}
        self._knn: KNeighborsClassifier | None = None

        self._fit()

    def _extract(self, waveform: np.ndarray) -> np.ndarray:
        return extract_mfcc_feature_vector(waveform, sr=self.sample_rate, n_mfcc=self.n_mfcc)

    def _fit(self) -> None:
        window_samples = max(1, round(self.window_sec * self.sample_rate))
        step_samples = max(1, round(self.step_sec * self.sample_rate))

        for profile in self.profiles:
            profile_vectors: list[np.ndarray] = []
            # Check if raw sample waveforms are available
            if profile.sample_waveforms:
                for wave in profile.sample_waveforms:
                    if wave.size <= window_samples:
                        vec = self._extract(wave)
                        profile_vectors.append(vec)
                        self._X_train.append(vec)
                        self._y_train.append(profile.speaker_id)
                    else:
                        for start in range(0, wave.size - window_samples + 1, step_samples):
                            chunk = wave[start : start + window_samples]
                            vec = self._extract(chunk)
                            profile_vectors.append(vec)
                            self._X_train.append(vec)
                            self._y_train.append(profile.speaker_id)

            if profile_vectors:
                centroid = np.mean(np.stack(profile_vectors), axis=0)
                centroid /= max(float(np.linalg.norm(centroid)), 1e-12)
                self._profile_centroids[profile.speaker_id] = centroid

        if self._X_train and len(self._X_train) >= 1:
            k = min(self.n_neighbors, len(self._X_train))
            self._knn = KNeighborsClassifier(n_neighbors=k, metric=self.metric, weights="distance")
            self._knn.fit(np.stack(self._X_train), self._y_train)

    def assign_speaker(self, waveform: np.ndarray, excluded: set[str]) -> dict[str, object]:
        if waveform.size < self.sample_rate:
            waveform = np.pad(waveform, (0, self.sample_rate - waveform.size))

        feat = self._extract(waveform)

        ranked: list[tuple[SpeakerProfileInput, float]] = []

        if self._knn is not None and self.profiles:
            probs = self._knn.predict_proba([feat])[0]
            classes = list(self._knn.classes_)
            prob_map = {cls: float(prob) for cls, prob in zip(classes, probs, strict=True)}

            for profile in self.profiles:
                if profile.speaker_id in excluded:
                    continue
                score = prob_map.get(profile.speaker_id, 0.0)
                ranked.append((profile, score))

            ranked.sort(key=lambda item: item[1], reverse=True)

        threshold = self.identity_threshold
        margin = self.identity_margin

        nearest_sim = -1.0
        if self._knn is not None and self._X_train:
            distances, _ = self._knn.kneighbors([feat], n_neighbors=1, return_distance=True)
            nearest_sim = 1.0 - float(distances[0][0])

        if ranked:
            best_profile, best_score = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
            actual_margin = best_score - runner_up
            if nearest_sim >= threshold and actual_margin >= margin:
                k_val = min(self.n_neighbors, len(self._X_train)) if self._X_train else 0
                return {
                    "speaker_id": best_profile.speaker_id,
                    "profile_id": best_profile.speaker_id,
                    "speaker_label": best_profile.display_name,
                    "speaker_status": "identified",
                    "speaker_match_score": best_score,
                    "speaker_top_candidates": [
                        {"speaker_id": profile.speaker_id, "cosine_score": score}
                        for profile, score in ranked[:3]
                    ],
                    "identity_decision_reason": (
                        f"knn_identified: prob={best_score:.3f}, "
                        f"sim={nearest_sim:.3f} >= threshold={threshold:.2f}, "
                        f"margin={actual_margin:.3f} >= min_margin={margin:.2f} (k={k_val})"
                    ),
                    "warnings": [],
                }

        # Build enrollment rejection reason
        if ranked:
            best_profile, best_score = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
            margin_diff = best_score - runner_up
            sim_cmp = (
                f"< threshold={threshold:.2f}"
                if nearest_sim < threshold
                else f">= threshold={threshold:.2f}"
            )
            margin_cmp = (
                f"< min_margin={margin:.2f}"
                if margin_diff < margin
                else f">= min_margin={margin:.2f}"
            )
            enrollment_reason = (
                f"knn_rejected: nearest_sim={nearest_sim:.3f} {sim_cmp}, "
                f"prob={best_score:.3f}, margin={margin_diff:.3f} {margin_cmp}"
            )
        else:
            enrollment_reason = (
                "no_mfcc_training_samples" if not self._X_train else "no_enrollment_profiles"
            )

        # Anonymous centroid clustering using 120-dim MFCC feature vectors
        anonymous_scores = [
            float(np.dot(feat, centroid)) if f"anonymous-{index + 1}" not in excluded else -1.0
            for index, centroid in enumerate(self._anonymous_centroids)
        ]
        best_anonymous = int(np.argmax(anonymous_scores)) if anonymous_scores else -1
        anonymous_threshold = self.anonymous_cluster_threshold
        should_reuse = best_anonymous >= 0 and (
            anonymous_scores[best_anonymous] >= anonymous_threshold
            or len(self._anonymous_centroids) >= self.max_anonymous
        )

        if should_reuse:
            count = self._anonymous_counts[best_anonymous]
            centroid = (self._anonymous_centroids[best_anonymous] * count + feat) / (count + 1)
            self._anonymous_centroids[best_anonymous] = centroid / max(
                float(np.linalg.norm(centroid)), 1e-12
            )
            self._anonymous_counts[best_anonymous] += 1
            anonymous_index = best_anonymous
            anon_score: float | None = anonymous_scores[best_anonymous]
            cluster_reason = (
                f"cluster_reuse: score={anonymous_scores[best_anonymous]:.3f} "
                f">= threshold={anonymous_threshold:.2f}"
            )
            if anonymous_scores[best_anonymous] < anonymous_threshold:
                cluster_reason = (
                    f"cluster_forced: score={anonymous_scores[best_anonymous]:.3f} "
                    f"< threshold={anonymous_threshold:.2f}, "
                    f"but max_clusters={self.max_anonymous} reached"
                )
        else:
            self._anonymous_centroids.append(feat)
            self._anonymous_counts.append(1)
            anonymous_index = len(self._anonymous_centroids) - 1
            anon_score = None
            if best_anonymous >= 0:
                cluster_reason = (
                    f"new_cluster: best_anonymous_score={anonymous_scores[best_anonymous]:.3f} "
                    f"< threshold={anonymous_threshold:.2f}"
                )
            else:
                cluster_reason = "new_cluster: first_speaker"

        anonymous_id = f"anonymous-{anonymous_index + 1}"
        return {
            "speaker_id": anonymous_id,
            "profile_id": None,
            "speaker_label": f"Speaker {anonymous_index + 1}",
            "speaker_status": "unknown",
            "speaker_match_score": anon_score,
            "speaker_top_candidates": [
                {"speaker_id": profile.speaker_id, "cosine_score": profile_score}
                for profile, profile_score in ranked[:3]
            ],
            "identity_decision_reason": f"{enrollment_reason} → {cluster_reason}",
            "warnings": ["speaker_not_enrolled_or_below_threshold"],
        }
