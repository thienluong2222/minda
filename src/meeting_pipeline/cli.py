"""Command-line interface shared with application services used by the web app."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from meeting_pipeline.adapters.model_registry import (
    configured_models,
    model_download_size,
    prepare_model,
)
from meeting_pipeline.application.doctor import run_checks
from meeting_pipeline.config import load_config, load_dataset_config
from meeting_pipeline.datasets.fetch import fetch_manifest
from meeting_pipeline.datasets.manifests import DatasetManifest
from meeting_pipeline.domain.errors import PipelineError
from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

app = typer.Typer(no_args_is_help=True)
models_app = typer.Typer(no_args_is_help=True)
data_app = typer.Typer(no_args_is_help=True)
simulate_app = typer.Typer(no_args_is_help=True)
evaluate_app = typer.Typer(no_args_is_help=True)
app.add_typer(models_app, name="models")
app.add_typer(data_app, name="data")
app.add_typer(simulate_app, name="simulate")
app.add_typer(evaluate_app, name="evaluate")
load_dotenv(".env", override=False)

ConfigOption = Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)]


@app.command()
def doctor(config: ConfigOption = Path("configs/default.yaml")) -> None:
    """Check the local environment without downloading models or datasets."""
    results = run_checks(load_config(config))
    for result in results:
        typer.echo(f"{'OK' if result.ok else 'FAIL'}\t{result.name}\t{result.detail}")
    if any(not result.ok for result in results):
        raise typer.Exit(1)


@models_app.command("prepare")
def models_prepare(config: ConfigOption = Path("configs/default.yaml")) -> None:
    """Prepare explicitly configured model snapshots in the local cache."""
    settings = load_config(config)
    raw = settings.model_dump(mode="python")
    specs = configured_models(raw)
    typer.echo("Models will be downloaded to the configured local cache.")
    unavailable = False
    for spec in specs:
        size = model_download_size(spec)
        size_text = "unknown" if size is None else f"{size} bytes"
        typer.echo(f"Preparing {spec.role}: {spec.model_id}@{spec.revision} ({size_text})")
        try:
            path = prepare_model(spec, settings.paths.model_cache_dir)
        except PipelineError as exc:
            typer.echo(f"{exc.code}: {exc}", err=True)
            unavailable = True
            continue
        typer.echo(f"Prepared at {path}")
    if unavailable:
        raise typer.Exit(2)


@data_app.command("plan")
def data_plan(
    config: ConfigOption = Path("configs/evaluation.yaml"),
    manifest: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    """Print byte budgets and unknown transfer sizes without fetching audio."""
    payload = load_dataset_config(config)
    typer.echo(f"Total network budget: {payload.total_download_budget_bytes} bytes")
    typer.echo(f"VIVOS: {payload.vivos_download_budget_bytes} bytes")
    typer.echo(f"LibriWASN: {payload.libriwasn_download_budget_bytes} bytes")
    typer.echo(f"VoxVietnam: {payload.voxvietnam_download_budget_bytes} bytes")
    if manifest is not None:
        plan = DatasetManifest.model_validate(json.loads(manifest.read_text(encoding="utf-8")))
        typer.echo(f"Known planned bytes: {plan.planned_known_bytes}")
        typer.echo(f"Unknown-size objects: {plan.unknown_size_count}")


@data_app.command("fetch")
def data_fetch(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, dir_okay=False)],
    config: ConfigOption = Path("configs/default.yaml"),
) -> None:
    """Fetch exactly one reviewed manifest under its configured source budget."""
    settings = load_config(config)
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    try:
        report = fetch_manifest(manifest, settings.paths.data_dir / "external", token)
    except PipelineError as exc:
        typer.echo(f"{exc.code}: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@data_app.command("prepare-vivos")
def data_prepare_vivos(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)] = Path(
        "configs/data/vivos.yaml"
    ),
) -> None:
    """Build VIVOS manifest, speaker-disjoint splits, and enrollment catalog."""
    import yaml

    from meeting_pipeline.data.splitting import build_and_save_vivos_data
    from meeting_pipeline.domain.contracts import VivosDataConfig

    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    cfg = VivosDataConfig.model_validate(data)
    typer.echo(f"Building VIVOS manifest from {cfg.vivos_root}...")
    build_and_save_vivos_data(cfg)
    typer.echo("Successfully generated manifest, splits, and enrollment catalog.")


@data_app.command("audit")
def data_audit(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, dir_okay=False)] = Path(
        "data/manifests/vivos.jsonl"
    ),
    reports_dir: Annotated[Path, typer.Option("--reports-dir")] = Path("reports"),
) -> None:
    """Audit VIVOS manifest for leakage, duplicates, missing files, and integrity."""
    from meeting_pipeline.data.leakage import audit_vivos_manifest

    typer.echo(f"Auditing manifest at {manifest}...")
    result = audit_vivos_manifest(manifest, reports_dir=reports_dir)
    if not result["passed"]:
        typer.echo(f"AUDIT FAILED with {result['violations_count']} violations!", err=True)
        for v in result["violations"]:
            typer.echo(f"  - {v}", err=True)
        raise typer.Exit(1)
    typer.echo(
        f"AUDIT PASSED! Clean records: {result['total_records']}. Reports written to {reports_dir}/"
    )


@simulate_app.command("generate")
def simulate_generate(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)] = Path(
        "configs/experiment/smoke.yaml"
    ),
) -> None:
    """Generate canonical meeting recipes and render multi-device audio."""
    import json

    import yaml

    from meeting_pipeline.data.manifest import load_manifest_jsonl
    from meeting_pipeline.domain.contracts import (
        ExperimentConfig,
        SimulationProfileConfig,
        VivosDataConfig,
    )
    from meeting_pipeline.simulation.meeting_recipe import (
        generate_meeting_recipe,
        save_recipe,
    )
    from meeting_pipeline.simulation.render import render_meeting_audio

    exp_data = yaml.safe_load(config.read_text(encoding="utf-8"))
    exp_cfg = ExperimentConfig.model_validate(exp_data)

    data_cfg_data = yaml.safe_load(Path(exp_cfg.data_config).read_text(encoding="utf-8"))
    data_cfg = VivosDataConfig.model_validate(data_cfg_data)

    manifest_records = load_manifest_jsonl(data_cfg.manifest_output_path)
    catalog_path = Path(data_cfg.catalog_output_path)
    if not catalog_path.exists():
        typer.echo(
            f"Catalog not found at {catalog_path}; please run 'data prepare-vivos' first",
            err=True,
        )
        raise typer.Exit(1)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    profile_path = Path(exp_cfg.simulation_profile or "configs/simulation/smoke.yaml")
    profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile_cfg = SimulationProfileConfig.model_validate(profile_data)

    meetings_per_split = exp_cfg.meetings_per_split or {
        "development": 1,
        "validation": 1,
        "test": 1,
    }

    recipes_dir = Path(exp_cfg.output_dirs.get("recipes", "data/recipes/smoke"))
    audio_dir = Path(exp_cfg.output_dirs.get("generated_audio", "data/generated/smoke"))

    total_rendered = 0
    for split_name, count in meetings_per_split.items():
        for idx in range(count):
            meeting_id = f"meeting_{split_name}_{idx + 1:03d}"
            seed = exp_cfg.seed + total_rendered * 101
            typer.echo(f"Generating recipe for {meeting_id} (split={split_name}, seed={seed})...")
            recipe = generate_meeting_recipe(
                meeting_id=meeting_id,
                split=split_name,
                seed=seed,
                profile=profile_cfg,
                manifest_records=manifest_records,
                enrollment_catalog=catalog,
                manifest_path=data_cfg.manifest_output_path,
                config_path=str(config),
            )
            recipe_file = recipes_dir / f"{meeting_id}.json"
            save_recipe(recipe, recipe_file)

            meeting_audio_dir = audio_dir / meeting_id
            typer.echo(
                f"Rendering audio to {meeting_audio_dir} "
                f"({len(recipe.devices)} devices, {len(recipe.turns)} turns, "
                f"{recipe.canonical_duration_sec:.1f}s)..."
            )
            files = render_meeting_audio(
                recipe=recipe,
                manifest_records=manifest_records,
                output_dir=meeting_audio_dir,
            )
            typer.echo(f"  Rendered {len(files)} tracks for {meeting_id}")
            total_rendered += 1

    typer.echo(f"Successfully rendered {total_rendered} meetings.")


@evaluate_app.command("run")
def evaluate_run(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)] = Path(
        "configs/experiment/smoke.yaml"
    ),
) -> None:
    """Run end-to-end evaluation pipeline (Dev train -> Val calibrate -> Test evaluate)."""
    from meeting_pipeline.evaluation.experiment_runner import run_experiment_pipeline

    typer.echo(f"Starting experiment runner with config: {config}")
    report = run_experiment_pipeline(config)
    exp_name = report.get("experiment_name")
    typer.echo(f"Experiment '{exp_name}' completed. Summary saved to reports/metrics/summary.json")


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8010,
) -> None:
    """Run the Minda FastAPI web server; ML jobs run in the separate meeting_backend worker."""
    import uvicorn

    uvicorn.run("meeting_backend.main:create_app", factory=True, host=host, port=port)


@app.command("run-files")
def run_files(
    sources: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False)],
    meeting_name: Annotated[str, typer.Option("--meeting-name")] = "prototype-meeting",
    fusion_method: Annotated[str, typer.Option("--fusion-method")] = "F5_RULE_WEIGHTED",
    config: ConfigOption = Path("configs/default.yaml"),
) -> None:
    """Run the multi-source transcript-fusion backend on local meeting recordings."""
    run_dir = MultiSourceFusionPipeline(load_config(config)).run(
        meeting_name,
        sources,
        fusion_method=fusion_method,
    )
    typer.echo(str(run_dir))


@app.command()
def worker() -> None:
    """Run the single-job ML worker."""
    typer.echo("Worker foundation is not yet migrated; run M1 migrations first.", err=True)
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
