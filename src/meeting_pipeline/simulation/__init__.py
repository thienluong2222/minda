"""Multi-device meeting simulation package."""

from meeting_pipeline.simulation.device import (
    apply_clipping,
    apply_clock_drift,
    apply_dropout,
    apply_start_offset,
)
from meeting_pipeline.simulation.meeting_recipe import (
    generate_meeting_recipe,
    load_recipe,
    save_recipe,
)
from meeting_pipeline.simulation.noise import (
    generate_brown_noise,
    generate_hum_noise,
    generate_pink_noise,
    generate_vivos_babble_noise,
    generate_vivos_room_tone,
    generate_white_noise,
    scale_noise_to_snr,
)
from meeting_pipeline.simulation.render import render_meeting_audio
from meeting_pipeline.simulation.room import compute_direct_path_energy, compute_room_rirs

__all__ = [
    "apply_clipping",
    "apply_clock_drift",
    "apply_dropout",
    "apply_start_offset",
    "compute_direct_path_energy",
    "compute_room_rirs",
    "generate_brown_noise",
    "generate_hum_noise",
    "generate_meeting_recipe",
    "generate_pink_noise",
    "generate_vivos_babble_noise",
    "generate_vivos_room_tone",
    "generate_white_noise",
    "load_recipe",
    "render_meeting_audio",
    "save_recipe",
    "scale_noise_to_snr",
]
