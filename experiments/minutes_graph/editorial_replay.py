"""Re-evaluate a frozen transcript without ASR or overwriting any saved meeting."""

import argparse
import json
from pathlib import Path

from meeting_pipeline.minutes.graph_contracts import GraphUnit, StyleProfile
from meeting_pipeline.minutes.graph_inputs import resplit_units
from meeting_pipeline.minutes.graph_pipeline import generate_graph_minutes
from meeting_pipeline.minutes.model_runtime import ModelSession, load_model_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.source.read_text())
    settings = load_model_settings().model_copy(update={"extraction_batch_size": 6})
    args.output.mkdir(parents=True, exist_ok=True)
    with ModelSession(args.output / "runtime.log", settings) as session:
        result = generate_graph_minutes(
            session,
            resplit_units([GraphUnit.model_validate(row) for row in snapshot["units"]]),
            meeting_id="editorial_replay",
            output=args.output,
            metadata=snapshot.get("metadata"),
            agenda=snapshot.get("agenda"),
            mode=snapshot.get("mode", "general"),
            style=StyleProfile.model_validate(snapshot["style"]) if snapshot.get("style") else None,
        )
    print(json.dumps({"report": result["report"], "text": result["text"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
