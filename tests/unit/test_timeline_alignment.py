"""Known ground-truth capture clocks, including missing time and wrong anchors."""

import numpy as np
import pytest

from meeting_pipeline.audio.fingerprints import fingerprint, match_fingerprints, refine_maps
from meeting_pipeline.audio.timeline_alignment import resolve_clocks


def audio(seconds, seed=42, sr=8000):
    rng = np.random.default_rng(seed)
    return (
        rng.normal(size=sr * seconds)
        * np.repeat(
            rng.uniform(0.05, 0.6, seconds * 10),
            sr // 10,
        )
    ).astype(np.float32)


def layout_for(waves, placements=None, same_track=False):
    placements = placements or {}
    return {
        "clips": [
            {
                "id": key,
                "asset_id": key,
                "source_in_ms": 0,
                "source_out_ms": round(len(wave) / 8),
                "placement": placements.get(key, {"kind": "sequential", "gap_before_ms": None}),
            }
            for key, wave in waves.items()
        ],
        "tracks": (
            [{"id": "phone", "clip_ids": list(waves)}]
            if same_track
            else [{"id": key, "clip_ids": [key]} for key in waves]
        ),
        "intervals": [],
    }


def resolve(waves, layout=None):
    return resolve_clocks(
        layout or layout_for(waves),
        {key: len(value) / 8000 for key, value in waves.items()},
        {key: fingerprint(value, 8000) for key, value in waves.items()},
        waves.__getitem__,
        8000,
    )


def test_landmarks_find_late_source_and_reject_different_audio():
    reference = audio(36)
    query = reference[10 * 8000 : 30 * 8000] * 0.7
    maps = match_fingerprints(fingerprint(reference, 8000), fingerprint(query, 8000))
    assert len(maps) == 1
    assert maps[0].offset == pytest.approx(10, abs=0.04)
    assert not match_fingerprints(fingerprint(reference, 8000), fingerprint(audio(20, 99), 8000))


def test_pause_is_two_maps_not_a_smooth_warp():
    reference = audio(36)
    query = np.concatenate([reference[: 13 * 8000], reference[23 * 8000 :]])
    maps = refine_maps(
        match_fingerprints(fingerprint(reference, 8000), fingerprint(query, 8000)),
        reference,
        query,
        8000,
    )
    assert len(maps) == 2
    assert maps[0].offset == pytest.approx(0, abs=0.02)
    assert maps[1].offset == pytest.approx(10, abs=0.02)
    assert maps[0].end == maps[1].start == pytest.approx(13, abs=0.02)
    report = resolve({"continuous": reference, "paused": query})
    assert report["timing_complete"] is True
    assert len(report["spans"]["paused"]) == 2
    assert report["spans"]["paused"][1]["offset"] == pytest.approx(10, abs=0.02)


def test_repeated_tone_does_not_establish_a_clock():
    tone = np.sin(2 * np.pi * 440 * np.arange(8000 * 15) / 8000).astype(np.float32)
    assert not match_fingerprints(fingerprint(tone, 8000), fingerprint(tone * 0.8, 8000))


def test_identical_repeated_passages_are_rejected_as_ambiguous():
    passage = audio(8)
    assert not match_fingerprints(
        fingerprint(np.tile(passage, 2), 8000), fingerprint(passage * 0.8, 8000)
    )


def test_all_devices_off_keeps_unknown_gap_and_declared_order():
    waves = {"before": audio(8, 11), "after": audio(6, 22)}
    report = resolve(waves, layout_for(waves, same_track=True))
    assert report["timing_complete"] is False
    assert report["spans"]["before"][0]["clock_id"] == "meeting"
    assert report["spans"]["after"][0]["clock_id"] != "meeting"
    assert report["spans"]["after"][0]["offset"] == 0


def test_known_gap_is_applied_without_requiring_common_audio():
    waves = {"before": audio(8, 11), "after": audio(6, 22)}
    layout = layout_for(waves, {"after": {"kind": "sequential", "gap_before_ms": 15000}}, True)
    report = resolve(waves, layout)
    assert report["timing_complete"] is True
    assert report["spans"]["after"][0]["offset"] == 23


def test_manual_start_is_not_silently_replaced_by_audio():
    reference = audio(30)
    waves = {"reference": reference, "late": reference[10 * 8000 :] * 0.7}
    layout = layout_for(
        waves,
        {
            "reference": {"kind": "anchored", "start_ms": 0},
            "late": {"kind": "anchored", "start_ms": 5000},
        },
    )
    report = resolve(waves, layout)
    assert report["timing_complete"] is False
    assert any(
        value["reason"] == "declared_start_conflicts_with_audio" for value in report["conflicts"]
    )
    assert report["spans"]["late"][0]["offset"] == 5


def test_short_and_silent_parts_do_not_get_fabricated_matches():
    report = resolve({"silent": np.zeros(8000 * 8, np.float32), "short": audio(2)})
    assert report["timing_complete"] is False
    assert report["matched_pairs"] == 0


def test_indirect_recording_bridge_keeps_unique_edges_as_estimated_time():
    full = audio(48)
    waves = {
        "a": full[: 20 * 8000],
        "b": full[12 * 8000 : 36 * 8000] * 0.8,
        "c": full[30 * 8000 :] * 0.7,
    }
    layout = layout_for(waves, {"a": {"kind": "anchored", "start_ms": 0}})
    report = resolve(waves, layout)
    assert report["timing_complete"] is True
    c = report["spans"]["c"]
    assert c[0]["offset"] == pytest.approx(30, abs=0.04)
    assert any(span["origin"] == "extrapolated" for span in c)
    assert "a" in c[0]["via"] and "b" in c[0]["via"]


def test_small_clock_rate_difference_is_fitted_from_acoustic_anchors():
    full = audio(45)
    ratio = 1.0003
    positions = np.arange(round(len(full) / ratio)) * ratio
    shifted = np.interp(positions, np.arange(len(full)), full).astype(np.float32)
    maps = refine_maps(
        match_fingerprints(fingerprint(full, 8000), fingerprint(shifted, 8000)), full, shifted, 8000
    )
    assert len(maps) == 1
    assert maps[0].scale == pytest.approx(ratio, abs=0.00015)
    assert abs(maps[0].scale * maps[0].end + maps[0].offset - 45) < 0.05


def test_global_landmarks_find_offset_beyond_legacy_search_window():
    full = audio(180)
    query = full[144 * 8000 : 164 * 8000] * 0.7
    maps = match_fingerprints(fingerprint(full, 8000), fingerprint(query, 8000))
    assert len(maps) == 1 and maps[0].offset == pytest.approx(144, abs=0.04)


def test_two_recording_pauses_keep_three_separate_clock_maps():
    full = audio(50)
    query = np.concatenate([full[: 12 * 8000], full[18 * 8000 : 30 * 8000], full[38 * 8000 :]])
    maps = refine_maps(
        match_fingerprints(fingerprint(full, 8000), fingerprint(query, 8000)), full, query, 8000
    )
    assert len(maps) == 3
    assert [value.offset for value in maps] == pytest.approx([0, 6, 14], abs=0.02)
    assert maps[0].end == maps[1].start == pytest.approx(12, abs=0.02)
    assert maps[1].end == maps[2].start == pytest.approx(24, abs=0.02)
