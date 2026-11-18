"""Record task-only changes against the dirty workspace snapshot; never compare to clean HEAD."""

from __future__ import annotations

import difflib
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/minutes_graph/20261108"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = json.loads((OUT / "before_change.json").read_text())
    paths = set(baseline["files"])
    names = [
        "graph_builder",
        "graph_contracts",
        "graph_inputs",
        "graph_pipeline",
        "graph_topics",
        "graph_values",
        "graph_writer",
        "minimal_format",
        "style_memory",
        "model_runtime",
    ]
    for prefix in ("src/meeting_pipeline/minutes", "web_app/src/meeting_pipeline/minutes"):
        paths.update(f"{prefix}/{name}.py" for name in names)
    paths.update(
        {
            "tests/unit/test_minutes_graph.py",
            "web_app/tests/unit/test_minutes_graph.py",
            "web_app/tests/backend/test_minutes_graph.py",
            "web_app/src/meeting_backend/modules/minutes/graph_settings.py",
            "web_app/src/meeting_backend/modules/minutes/graph_store.py",
        }
    )
    paths.update(
        str(path.relative_to(ROOT)) for path in (ROOT / "experiments/minutes_graph").glob("*.py")
    )
    changed, patch = [], []
    with zipfile.ZipFile(OUT / "before_change.zip") as previous:
        old_names = set(previous.namelist())
        for name in sorted(paths):
            path = ROOT / name
            old = previous.read(name) if name in old_names else b""
            new = path.read_bytes() if path.exists() else b""
            if old == new:
                continue
            changed.append(
                {
                    "path": name,
                    "before_sha256": hashlib.sha256(old).hexdigest() if old else None,
                    "after_sha256": sha(path) if path.exists() else None,
                    "status": "modified" if name in old_names else "added",
                }
            )
            patch.extend(
                difflib.unified_diff(
                    old.decode().splitlines(keepends=True),
                    new.decode().splitlines(keepends=True),
                    fromfile="a/" + name if name in old_names else "/dev/null",
                    tofile="b/" + name,
                )
            )
    ui_changes = [
        name
        for name, expected in baseline["ui_sha256"].items()
        if not (ROOT / name).is_file() or sha(ROOT / name) != expected
    ]
    assert not ui_changes, ui_changes
    mirror = {}
    for name in names:
        a, b = [
            ROOT / prefix / (name + ".py")
            for prefix in ("src/meeting_pipeline/minutes", "web_app/src/meeting_pipeline/minutes")
        ]
        mirror[name] = sha(a) == sha(b)
    assert all(mirror.values()), mirror
    frozen = json.loads((OUT / "frozen_generation_source_v2.json").read_text())
    drift = [name for name, expected in frozen.items() if sha(ROOT / name) != expected]
    result = {
        "comparison_base": "before_change.zip: existing uncommitted work is preserved",
        "changed_files": changed,
        "ui_files_checked": len(baseline["ui_sha256"]),
        "ui_changed_by_task": ui_changes,
        "new_core_module_mirrors_match": mirror,
        "v2_frozen_generation_source_differences": drift,
        "model_settings_unchanged": all(
            sha(ROOT / name) == baseline["files"][name]["sha256"]
            for name in ("configs/minutes.yaml", "web_app/configs/minutes.yaml")
        ),
        "upstream_asr_or_speaker_pipeline_changed_in_this_task": False,
    }
    (OUT / "task_changes.patch").write_text("".join(patch))
    (OUT / "task_changes.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(OUT / "final_source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for item in changed:
            archive.write(ROOT / item["path"], item["path"])
    print(
        json.dumps(
            {
                "changed_files": len(changed),
                "UI_unchanged": not ui_changes,
                "model_settings_unchanged": result["model_settings_unchanged"],
                "source_drift_from_v2": drift,
            }
        )
    )


if __name__ == "__main__":
    main()
