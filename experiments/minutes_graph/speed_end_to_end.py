"""One-source real audio -> transcript -> graph -> DOCX/ZIP smoke, outside live storage."""

import gc
import json
import time
import zipfile
from pathlib import Path


def main():
    import soundfile as sf
    import torch

    from meeting_pipeline.config import load_config
    from meeting_pipeline.minutes import graph_pipeline
    from meeting_pipeline.minutes.model_runtime import ModelSession, load_model_settings
    from meeting_pipeline.minutes.service import MinutesService
    from meeting_pipeline.minutes.text_engine import MinutesOptions
    from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

    torch.set_num_threads(2)
    root = Path(__file__).resolve().parents[2]
    output = root / "reports/pipeline_speed/20261109/end_to_end"
    cfg = load_config(root / "web_app/configs/default.yaml")
    cfg.paths.data_dir = output
    cfg.paths.database_path = output / "test.sqlite"
    cfg.paths.model_cache_dir = root / "data/model_cache"
    cfg.asr.cache_enabled = False
    started = time.perf_counter()
    pipeline = MultiSourceFusionPipeline(cfg)
    print("START audio", flush=True)
    run = pipeline.run(
        "speed_one_source",
        [root / "data/generated/fpt_tts_pilot_20261003/meeting_audio/clean_reference.wav"],
        fusion_method="F5_RULE_WEIGHTED_CORRECTED",
    )
    audio_sec = time.perf_counter() - started
    del pipeline
    gc.collect()

    class UncachedSession(ModelSession):
        def __init__(self, log_path, settings=None):
            super().__init__(
                log_path,
                (settings or load_model_settings()).model_copy(update={"response_cache": False}),
            )

    graph_pipeline.ModelSession = UncachedSession
    print(f"START minutes audio_sec={audio_sec:.2f}", flush=True)
    minutes_start = time.perf_counter()
    result = MinutesService().process_template_for_run(
        root / "reports/minutes_graph/20261108/end_to_end_final/minimal_template.docx",
        run,
        meeting_metadata={
            "meeting_name": "Họp triển khai kho tài liệu Sao Khuê",
            "meeting_date": "2026-10-03",
            "location": "B201",
        },
        options=MinutesOptions(
            use_model=True,
            graph_enabled=True,
            mode="general",
            correct_transcript=True,
            format_standard="minimal",
        ),
        reuse_schema=True,
    )
    with zipfile.ZipFile(result["zip_export"]) as archive:
        assert archive.testzip() is None
    summary = {
        "audio_wall_sec": audio_sec,
        "minutes_wall_sec": time.perf_counter() - minutes_start,
        "total_wall_sec": time.perf_counter() - started,
        "input_audio_sec": sf.info(
            root / "data/generated/fpt_tts_pilot_20261003/meeting_audio/clean_reference.wav"
        ).duration,
        "sources": 1,
        "cached_asr_responses": False,
        "cached_llm_responses": False,
        "run": str(run),
        "docx": result["completed_docx"],
        "zip": result["zip_export"],
        "zip_integrity_passed": True,
        "semantic_accuracy_verified": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
