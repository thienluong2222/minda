"""Serve the unchanged app with isolated data and already-cached models for UI review."""

import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
import torch
import uvicorn

from meeting_pipeline.config import load_config
from meeting_pipeline.web.app import create_app

root = Path("/Users/thien/Documents/School/Luận văn")
cfg = load_config(root / "configs/default.yaml")
cfg.paths.data_dir = Path("/private/tmp/meeting-demo-review/ui_data")
cfg.paths.model_cache_dir = root / "data/model_cache"
cfg.paths.database_path = cfg.paths.data_dir / "app.sqlite"
torch.set_num_threads(4)
uvicorn.run(create_app(cfg), host="127.0.0.1", port=8001)
