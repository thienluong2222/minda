"""Unit tests for Pydantic contracts and YAML config loading (Milestone 1)."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from meeting_pipeline.domain.contracts import (
    DeviceConfig,
    ExperimentConfig,
    FinalTimelineItem,
    FusionConfig,
    MeetingRecipe,
    MeetingSegment,
    ModelsConfig,
    RoomConfig,
    SimulationProfileConfig,
    TurnRecord,
    VivosDataConfig,
    WordProvenance,
)


def test_vivos_data_config_loading() -> None:
    path = Path("configs/data/vivos.yaml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = VivosDataConfig.model_validate(data)
    assert config.target_sample_rate == 16000
    assert config.development_speaker_count + config.validation_speaker_count == 46
    assert config.test_speaker_count == 19


@pytest.mark.parametrize("profile_name", ["smoke", "easy", "moderate", "stress"])
def test_simulation_profile_configs_loading(profile_name: str) -> None:
    path = Path(f"configs/simulation/{profile_name}.yaml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    profile = SimulationProfileConfig.model_validate(data)
    assert profile.profile_name == profile_name
    assert len(profile.room_dimensions) == 3
    assert profile.num_speakers >= 2
    assert profile.num_devices >= 2


def test_models_config_loading() -> None:
    path = Path("configs/models/default.yaml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = ModelsConfig.model_validate(data)
    assert cfg.asr.model_id == "vinai/PhoWhisper-medium"
    assert cfg.speaker_encoder.embedding_dim == 256


def test_fusion_config_loading() -> None:
    path = Path("configs/fusion/default.yaml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = FusionConfig.model_validate(data)
    expected_baselines = [
        "F0_FIXED",
        "F1_BEST_SEGMENT",
        "F2_ORACLE_BEST",
        "F3_ROVER",
        "F4_ASR_WEIGHTED",
        "F5_RULE_WEIGHTED",
        "F6_LEARNED",
    ]
    for b in expected_baselines:
        assert b in cfg.baselines


@pytest.mark.parametrize("exp_name", ["smoke", "full"])
def test_experiment_configs_loading(exp_name: str) -> None:
    path = Path(f"configs/experiment/{exp_name}.yaml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = ExperimentConfig.model_validate(data)
    assert cfg.seed == 42


def test_interval_validation_in_turn_and_segment() -> None:
    with pytest.raises(ValidationError):
        TurnRecord(
            turn_id="t1",
            speaker_id="spk1",
            utterance_id="u1",
            start_sec=10.0,
            end_sec=5.0,  # Invalid
            text_raw="test",
            text_normalized="test",
        )

    with pytest.raises(ValidationError):
        MeetingSegment(
            meeting_id="m1",
            segment_id="s1",
            start_sec=5.0,
            end_sec=5.0,  # Zero duration
        )

    valid_turn = TurnRecord(
        turn_id="t1",
        speaker_id="spk1",
        utterance_id="u1",
        start_sec=0.0,
        end_sec=3.5,
        text_raw="chào bạn",
        text_normalized="chào bạn",
    )
    assert valid_turn.start_sec == 0.0
    assert valid_turn.end_sec == 3.5


def test_meeting_recipe_validation() -> None:
    recipe = MeetingRecipe(
        meeting_id="meeting_test",
        split="development",
        seed=42,
        profile="smoke",
        speakers=["spk1", "spk2"],
        speaker_positions={"spk1": [1.0, 1.0, 1.2], "spk2": [2.0, 2.0, 1.2]},
        enrollment_utterances={"spk1": ["u1", "u2"], "spk2": ["u3", "u4"]},
        turns=[
            TurnRecord(
                turn_id="t1",
                speaker_id="spk1",
                utterance_id="u5",
                start_sec=0.0,
                end_sec=2.0,
                text_raw="xin chào",
                text_normalized="xin chào",
            )
        ],
        room=RoomConfig(dimensions=[5.0, 4.0, 2.8], rt60=0.3),
        devices={
            "d1": DeviceConfig(device_id="d1", position=[1.5, 1.5, 0.8]),
            "d2": DeviceConfig(device_id="d2", position=[2.5, 2.5, 0.8]),
        },
        canonical_duration_sec=3.0,
        manifest_hash="dummy_hash",
        config_hash="dummy_cfg_hash",
    )
    assert recipe.meeting_id == "meeting_test"
    assert len(recipe.turns) == 1
    assert "d1" in recipe.devices


def test_final_timeline_item_provenance() -> None:
    item = FinalTimelineItem(
        meeting_id="m1",
        segment_id="seg1",
        start_sec=1.0,
        end_sec=4.0,
        speaker_id="spk1",
        speaker_confidence=0.95,
        text="xin chào bạn",
        transcript_confidence=0.91,
        primary_source_id="d1",
        source_scores={"d1": 0.9, "d2": 0.6},
        word_provenance=[
            WordProvenance(
                output_word="xin",
                confidence=0.95,
                supporting_sources=["d1", "d2"],
                source_scores={"d1": 0.9, "d2": 0.6},
                representative_source_id="d1",
            )
        ],
        evidence_clips={"d1": "clips/seg1/d1.wav"},
    )
    assert item.speaker_id == "spk1"
    assert len(item.word_provenance) == 1
