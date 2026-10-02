"""Model smoke test for end-to-end transcription using real PhoWhisper and Silero VAD."""

from __future__ import annotations

import json
from pathlib import Path

import jiwer
import numpy as np
import pytest
import soundfile as sf

from meeting_pipeline.config import load_config
from meeting_pipeline.domain.schemas import TimelineSegment
from meeting_pipeline.pipeline.prototype import PrototypePipeline


@pytest.mark.model_smoke
def test_vivos_composite_transcription_smoke(tmp_path: Path) -> None:
    vivos_dir = Path("data/external/vivos/extracted/vivos/test/waves/VIVOSDEV02")
    utt_a_path = vivos_dir / "VIVOSDEV02_R106.wav"
    utt_b_path = vivos_dir / "VIVOSDEV02_R122.wav"

    if not utt_a_path.is_file() or not utt_b_path.is_file():
        pytest.skip("VIVOS test samples not found at expected location")

    config = load_config(Path("configs/default.yaml"))
    asr_snapshot = (
        config.paths.model_cache_dir
        / f"models--{config.asr.model_id.replace('/', '--')}"
        / "snapshots"
        / config.asr.model_revision
    )
    if not asr_snapshot.is_dir():
        pytest.skip(f"PhoWhisper snapshot not found: {asr_snapshot}")

    # Build composite audio:
    # silence (2s) -> utterance A -> silence (2s) -> utterance B -> silence (2s)
    audio_a, _ = sf.read(utt_a_path, dtype="float32")
    audio_b, _ = sf.read(utt_b_path, dtype="float32")

    sr = config.audio.analysis_sample_rate
    silence = np.zeros(int(2.0 * sr), dtype=np.float32)
    composite = np.concatenate([silence, audio_a, silence, audio_b, silence])

    input_path = tmp_path / "vivos_composite.wav"
    sf.write(input_path, composite, sr, subtype="PCM_16")

    config.paths.data_dir = tmp_path / "data"
    config.paths.database_path = tmp_path / "data" / "app.sqlite"
    config.identity["method"] = "mfcc_knn"

    pipeline = PrototypePipeline(config)
    run_dir = pipeline.run("VIVOS Smoke Run", [input_path])

    # 1. Verify activity regions detected both utterances
    act_file = run_dir / "activity_regions.json"
    assert act_file.is_file()
    act_data = json.loads(act_file.read_text(encoding="utf-8"))
    assert len(act_data["regions"]) == 2

    # 2. Verify timeline segments
    timeline_file = run_dir / "timeline.json"
    assert timeline_file.is_file()
    timeline = json.loads(timeline_file.read_text(encoding="utf-8"))["segments"]
    assert len(timeline) == 2

    # 3. Verify monotonic timestamps and valid evidence clips
    prev_end = 0.0
    for seg_dict in timeline:
        seg = TimelineSegment.model_validate(seg_dict)
        assert seg.start_sec >= prev_end - 0.1
        prev_end = seg.end_sec

        # Check evidence clip exists and has audio
        assert seg.evidence_clip_artifact_id is not None
        ev_path = run_dir / seg.evidence_clip_artifact_id
        assert ev_path.is_file()
        info = sf.info(ev_path)
        assert info.samplerate == sr
        assert info.duration > 0.0

    # 4. Silence was not transcribed into phantom sentences
    for seg_dict in timeline:
        # Neither segment should span the silence windows [0, 2] or [9.5, 11]
        assert seg_dict["start_sec"] >= 1.5
        assert seg_dict["end_sec"] <= 10.0

    # 5. Measure WER and CER against ground truth reference
    ref_text = "trở nên thụ động cũng khiến cho họ dè dặt"
    hyp_text = " ".join(seg["text"] for seg in timeline).lower()
    ref_norm = jiwer.SubstituteRegexes({r"[^\w\s]": ""})(ref_text.lower()).strip()
    hyp_norm = jiwer.SubstituteRegexes({r"[^\w\s]": ""})(hyp_text.lower()).strip()

    wer = float(jiwer.wer(ref_norm, hyp_norm))
    cer = float(jiwer.cer(ref_norm, hyp_norm))

    # Expect good recognition on clear VIVOS speech (WER <= 0.35, CER <= 0.35)
    assert wer <= 0.35, f"WER too high: {wer:.4f}"
    assert cer <= 0.35, f"CER too high: {cer:.4f}"
