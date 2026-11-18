"""Evidence retrieval service connecting template fields to timeline segments and audio clips.

Specification: Section 5 (F3) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

from meeting_pipeline.minutes.schemas import EvidenceRef, TemplateField

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Tokenize and normalize Vietnamese text into lowercased alphanumeric words."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return [w for w in cleaned.split() if len(w) > 1]


@dataclass
class IndexedTurn:
    """Indexed speaker turn from timeline schema 2.0."""

    turn_id: str
    speaker_label: str
    speaker_id: str | None
    start_sec: float
    end_sec: float
    text: str
    tokens: list[str]
    source_id: str
    clip_path: str | None
    asr_status: str
    needs_review: bool
    confidence: float | None
    meeting_speaker_id: str | None = None
    speaker_status: str = ""
    speaker_count: int = 1
    overlap_group_id: str | None = None
    clip_artifact_id: str | None = None
    clock_id: str | None = None
    session_id: str | None = None
    speech_region_id: str | None = None


class TurnSearchIndex:
    """Inverted index with BM25-like term scoring over meeting timeline turns."""

    def __init__(self, turns: list[IndexedTurn]) -> None:
        self.turns = turns
        self.doc_count = len(turns)
        self.avg_doc_len = sum(len(t.tokens) for t in turns) / max(1, self.doc_count)

        # Inverted index: token -> list of turn indices
        self.inverted: dict[str, list[int]] = {}
        # Document frequencies: token -> count of turns containing token
        self.df: dict[str, int] = {}

        for idx, turn in enumerate(turns):
            seen_in_doc: set[str] = set()
            for token in turn.tokens:
                if token not in seen_in_doc:
                    seen_in_doc.add(token)
                    self.df[token] = self.df.get(token, 0) + 1
                    self.inverted.setdefault(token, []).append(idx)

    def search(
        self,
        query: str | list[str],
        top_k: int = 3,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> list[tuple[IndexedTurn, float]]:
        """Rank turns using BM25 scoring for given query."""
        if isinstance(query, str):
            q_tokens = _tokenize(query)
        else:
            q_tokens = [t.lower() for t in query]

        if not q_tokens or not self.turns:
            return []

        scores: dict[int, float] = {}

        for token in q_tokens:
            if token not in self.df:
                continue
            df_val = self.df[token]
            idf = math.log((self.doc_count - df_val + 0.5) / (df_val + 0.5) + 1.0)

            for doc_idx in self.inverted[token]:
                turn = self.turns[doc_idx]
                tf = turn.tokens.count(token)
                norm_len = len(turn.tokens) / max(1.0, self.avg_doc_len)
                denom = tf + k1 * (1.0 - b + b * norm_len)
                term_score = idf * (tf * (k1 + 1.0) / max(1e-5, denom))
                scores[doc_idx] = scores.get(doc_idx, 0.0) + term_score

        sorted_indices = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)
        return [(self.turns[i], round(scores[i], 4)) for i in sorted_indices[:top_k]]


def load_indexed_turns(run_dir: Path) -> list[IndexedTurn]:
    """Load timeline segments from run_dir into IndexedTurn objects."""
    timeline_path = run_dir / "timeline.json"
    if not timeline_path.is_file():
        raise FileNotFoundError(f"Timeline not found: {timeline_path}")

    data = json.loads(timeline_path.read_text(encoding="utf-8"))
    segments = data.get("segments") or []
    if data.get("timing_complete") is False or any(
        row.get("time_status") == "unresolved" or row.get("timing_complete") is False
        for row in segments
    ):
        raise ValueError("Timeline clocks need review before generating meeting minutes")

    turns: list[IndexedTurn] = []
    for s in segments:
        turn_id = s.get("segment_id") or s.get("turn_id") or f"turn_{len(turns)}"
        text = str(s.get("text") or "").strip()
        asr_status = str(s.get("asr_status") or "transcribed")
        if s.get("excluded_from_minutes") or asr_status == "excluded":
            # Rule extractors and retrieval also consume this list. Removing
            # only writer eligibility would still leak excluded source text.
            text = ""
            asr_status = "excluded"
        elif s.get("user_edited") and text:
            asr_status = "user_edited"
        tokens = _tokenize(text)

        source_id = s.get("selected_source_id") or "source-1"

        # Prefer the resolved artifact from the backend. Legacy evidence paths
        # are retained only when they resolve to a real file.
        candidates = [s.get("clip_path"), s.get("evidence_clip_artifact_id")]
        candidates.extend(
            ev.get("evidence_clip_artifact_id")
            for ev in s.get("source_evidence") or []
            if ev.get("source_id") == source_id
        )
        clip_path_str = next(
            (str(path) for path in candidates if path and (run_dir / path).is_file()), None
        )

        conf = s.get("transcript_confidence")
        if conf is not None:
            try:
                conf = float(conf)
            except (ValueError, TypeError):
                conf = None

        turns.append(
            IndexedTurn(
                turn_id=turn_id,
                speaker_label=str(s.get("speaker_label") or "Chưa rõ"),
                speaker_id=s.get("speaker_id"),
                start_sec=float(s.get("start_sec") or 0.0),
                end_sec=float(s.get("end_sec") or 0.0),
                text=text,
                tokens=tokens,
                source_id=source_id,
                clip_path=clip_path_str,
                asr_status=asr_status,
                needs_review=bool(s.get("needs_review")),
                confidence=conf,
                meeting_speaker_id=s.get("meeting_speaker_id"),
                speaker_status=str(s.get("speaker_status") or ""),
                speaker_count=int(s.get("speaker_count") or 1),
                overlap_group_id=s.get("overlap_group_id"),
                clip_artifact_id=s.get("clip_artifact_id"),
                clock_id=s.get("clock_id"),
                session_id=s.get("session_id"),
                speech_region_id=s.get("speech_region_id"),
            )
        )

    return turns


def retrieve_evidence_for_field(
    field: TemplateField,
    index: TurnSearchIndex,
    run_id: str = "run-1",
    extra_keywords: list[str] | None = None,
) -> list[EvidenceRef]:
    """Search for relevant timeline turns providing evidence for a field."""
    queries = [field.raw_label, field.section]
    if extra_keywords:
        queries.extend(extra_keywords)

    search_text = " ".join(queries)
    matches = index.search(search_text, top_k=2)

    refs: list[EvidenceRef] = []
    for turn, score in matches:
        if score < 0.2:
            continue
        refs.append(
            EvidenceRef(
                run_id=run_id,
                turn_id=turn.turn_id,
                source_id=turn.source_id,
                start_sec=turn.start_sec,
                end_sec=turn.end_sec,
                clip_path=turn.clip_path,
                clip_artifact_id=turn.clip_artifact_id,
                source_kind="transcript",
                text_snippet=turn.text[:200],
                confidence=round(score, 4),
            )
        )
    return refs
