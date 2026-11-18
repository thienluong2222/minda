"""Compare the original local checkpoints with the saved Minda v2.1 Colab predictions."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import io
import json
import platform
import shutil
import sys
from collections import defaultdict
from importlib.metadata import version
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[3]
BUNDLE = WORKSPACE / "web_app/artifacts/minda-colab-v21"
PROJECT_DIR = BUNDLE / "LLMTraining"
OLD_REPORT = WORKSPACE / "reports/minutes_graph/20261117/llm_base_comparison/recheck_20261118"
COLAB_REPORT = PROJECT_DIR / "data/train/evaluation/AB"
LOCAL_MODELS = ("qwen35", "gemma4", "qwen3_mlx")
OLD_KEYS = {"qwen35": "qwen35", "gemma4": "gemma4", "qwen3_mlx": "qwen3"}
COLAB_MODELS = ("base", "A", "B")
LABELS = {
    "base": "Qwen3-4B-Instruct-2507 · NF4",
    "A": "Qwen3 + LoRA A · NF4",
    "B": "Qwen3 + LoRA B · NF4",
    "qwen35": "Qwen3.5-4B · MLX 4-bit",
    "gemma4": "Gemma 4 E2B-it · MLX 4-bit",
    "qwen3_mlx": "Qwen3-4B-Instruct-2507 · MLX 4-bit",
}
MIN_FREE_BYTES = 5 * 2**30

sys.path.insert(0, str(PROJECT_DIR))
from minda_colab.common import (
    check_hashes, check_project, check_train_dev, experiment, read_json, read_jsonl,
    sha, unpack_holdout, write_json, write_jsonl, write_text,
)

PUBLIC = ("case_id", "family_id", "meeting_mode", "domain", "turns")


def bind_file(path, expected):
    if path.is_file():
        if read_json(path) != expected:
            raise ValueError(f"Existing artifacts use a different protocol: {path}")
    else:
        write_json(path, expected)


def protocol():
    bundle_hash = check_project()
    data, split = check_train_dev(PROJECT_DIR, quiet=True)
    colab_file = COLAB_REPORT / "holdout_lock.json"
    colab_lock = read_json(colab_file)
    if (
        colab_lock["bundle_sha256"] != bundle_hash
        or colab_lock["split_manifest_sha256"] != sha(data / "split_manifest.json")
        or colab_lock["test_files"] != split["test_hashes"]
        or set(colab_lock["models"]) != set(COLAB_MODELS)
    ):
        raise ValueError("Colab A/B run uses a different release or holdout.")
    colab_digest = sha(colab_file)
    for name in COLAB_MODELS:
        binding = read_json(COLAB_REPORT / "test" / name / "prediction_input.json")
        if binding["holdout_lock_sha256"] != colab_digest or binding["model"] != name:
            raise ValueError(f"Downloaded predictions are from another run: {name}.")

    config = experiment()
    snapshots = {
        name: read_json(OLD_REPORT / f"{old_key}_weights.json")
        for name, old_key in OLD_KEYS.items()
    }
    record = {
        "bundle_sha256": bundle_hash,
        "split_manifest_sha256": colab_lock["split_manifest_sha256"],
        "test_files": split["test_hashes"],
        "prompt_hashes": split["prompts_sha256"],
        "colab_lock_sha256": colab_digest,
        "colab_models": colab_lock["models"],
        "colab_dtype": colab_lock["precision"],
        "mlx_snapshots": snapshots,
        "embedding": config["embedding"],
        "decoding": {
            "sampler": "greedy", "enable_thinking": False,
            "input_token_budget": config["evaluation"]["input_token_budget"],
            "output_token_budget": config["evaluation"]["output_token_budget"],
        },
    }
    bind_file(HERE / "protocol.json", record)
    return config, split, record


class MlxGenerate:
    def __init__(self, snapshot, settings):
        import mlx.core as mx
        from mlx_lm import load, stream_generate
        from mlx_lm.sample_utils import make_sampler

        self.mx = mx
        self.stream_generate = stream_generate
        self.sampler = make_sampler(temp=0)
        self.model, self.tokenizer = load(str(snapshot), trust_remote_code=False)
        self.settings = settings

    def __call__(self, system, payload):
        turns = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        template = self.tokenizer.apply_chat_template(
            turns, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        tokens = self.tokenizer.encode(template, add_special_tokens=False)
        n = len(tokens)
        if n > self.settings.input_token_budget:
            return {"text": "", "finish_reason": "input_length", "prompt_tokens": n,
                    "generation_tokens": 0, "wall_sec": 0.0}
        start = perf_counter()
        text = []
        for response in self.stream_generate(
            self.model, self.tokenizer, prompt=tokens,
            max_tokens=self.settings.output_token_budget, sampler=self.sampler, prefill_step_size=1024,
        ):
            text.append(response.text)
        return {
            "text": "".join(text), "finish_reason": response.finish_reason, "prompt_tokens": n,
            "generation_tokens": response.generation_tokens, "wall_sec": perf_counter() - start,
        }


def capture(path, tasks, key, execute):
    """Append in input order, recovering a partially written last line."""
    existing = []
    if path.is_file():
        lines = path.read_bytes().splitlines(keepends=True)
        complete = not lines or lines[-1].endswith(b"\n")
        existing = [json.loads(line) for line in (lines if complete else lines[:-1])]
        if [key(row) for row in existing] != [key(row) for row in tasks[:len(existing)]]:
            raise ValueError(f"Stored output keys do not match test input: {path}.")
        if not complete:
            write_jsonl(path, existing)
    with path.open("a", encoding="utf-8") as stream:
        for index, task in enumerate(tasks[len(existing):], start=len(existing) + 1):
            if shutil.disk_usage(path.parent).free < MIN_FREE_BYTES:
                raise RuntimeError("Stopped with outputs saved because free space is below 5 GiB.")
            row = execute(task)
            if key(row) != key(task):
                raise ValueError(f"Output identifier differs from input: {key(task)}")
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            if index == 1 or index % 5 == 0 or index == len(tasks):
                print(f"{path.parent.name}/{path.stem}: {index}/{len(tasks)}", flush=True)


def run_model(name, snapshot, split, record, config, test):
    from minda_colab.runtime import E5, GraphSession, ModelRuntimeError, PROMPTS, predict, settings_for

    identity = record["mlx_snapshots"][name]
    check_hashes(snapshot, identity["sha256"])
    if {key: hashlib.sha256(text.encode()).hexdigest() for key, text in PROMPTS.items()} != record["prompt_hashes"]:
        raise ValueError("Graph prompts no longer match the test contract.")
    inputs = read_jsonl(test / "inputs/transcripts.jsonl")
    oracle = read_jsonl(test / "inputs/relations_gold_events_inputs.jsonl")
    if (
        any(set(row) != set(PUBLIC) for row in inputs)
        or {row["family_id"] for row in inputs} != set(split["splits"]["test"])
        or len({row["case_id"] for row in inputs}) != len(inputs)
        or any(set(row) != {"case_id", "batch_index", "mode", "system", "user"}
               or row["system"] != PROMPTS["relations"] for row in oracle)
    ):
        raise ValueError("Holdout input fields do not match the locked interface.")

    location = HERE / name
    embedding = record["embedding"]
    embedding_path = (
        PROJECT_DIR.parents[2] / "data/model_cache/minutes/hub"
        / f"models--{embedding['id'].replace('/', '--')}" / "snapshots" / embedding["revision"]
    )
    packages = {package: version(package) for package in ("mlx", "mlx-lm", "transformers", "torch")}
    bind_file(location / "prediction_input.json", {
        "protocol_sha256": sha(HERE / "protocol.json"),
        "model": name, "snapshot": identity, "packages": packages,
        "generator_sha256": sha(Path(__file__)), "machine": platform.machine(),
    })

    tick = perf_counter()
    encoder = E5(config, local_path=embedding_path)
    prepared = {case["case_id"]: encoder.prepare(case) for case in inputs}
    del encoder
    gc.collect()
    settings = settings_for(config)
    generate = MlxGenerate(snapshot, settings)
    session = GraphSession(settings, generate.tokenizer, generate)

    print(f"Running {name}, {len(inputs)} transcripts, {len(oracle)} oracle batches.", flush=True)
    capture(
        location / "graphs.jsonl", inputs, lambda r: r["case_id"],
        lambda case: predict(case, prepared[case["case_id"]], session),
    )

    def link(batch):
        session.attempts.clear()
        try:
            parsed = session.generate_json(batch["system"], batch["user"])
        except ModelRuntimeError:
            parsed = None
        return {"case_id": batch["case_id"], "batch_index": batch["batch_index"],
                "parsed": parsed, "attempt": session.attempts[-1]}

    capture(location / "gold_event_links.jsonl", oracle, lambda r: (r["case_id"], r["batch_index"]), link)
    write_json(location / "generation_resources.json", {
        "hardware": "Apple M4 · Metal", "elapsed_this_execution_s": perf_counter() - tick,
        "peak_mlx_allocated_gib": generate.mx.get_peak_memory() / 2**30, "packages": packages,
    })


def bootstrap(models, draws, seed):
    import numpy as np
    from minda_colab.score import prf, ratio, total_counts

    families = sorted({row["family_id"] for row in models["base"]})
    indexes = np.random.default_rng(seed).integers(len(families), size=(draws, len(families)))
    samples, points = {}, {}
    for name, rows in models.items():
        groups = defaultdict(list)
        for row in rows:
            groups[row["family_id"]].append(row)
        if set(groups) != set(families):
            raise ValueError(f"Different holdout families for {name}.")
        edges = np.array([total_counts(r["relations"] for r in groups[f]) for f in families])
        states = np.array([
            [sum(r["state_exact"] is True for r in groups[f]),
             sum(r["state_exact"] is not None for r in groups[f])]
            for f in families
        ])
        tp, fp, fn = edges[indexes].sum(axis=1).T
        good, n = states[indexes].sum(axis=1).T
        denom = 2 * tp + fp + fn
        samples[name] = {
            "relation_f1": np.divide(2 * tp, denom, out=np.full(draws, np.nan), where=denom != 0),
            "state_exact": np.divide(good, n, out=np.full(draws, np.nan), where=n != 0),
        }
        correct, total = states.sum(axis=0).tolist()
        points[name] = {"relation_f1": prf(edges.sum(axis=0).tolist())["f1"],
                        "state_exact": ratio(correct, total)}
    comparisons = {}
    for before, after in combinations(models, 2):
        comparisons[f"{after}_minus_{before}"] = {}
        for metric in ("relation_f1", "state_exact"):
            diff = samples[after][metric] - samples[before][metric]
            diff = diff[np.isfinite(diff)]
            new, old = points[after][metric], points[before][metric]
            comparisons[f"{after}_minus_{before}"][metric] = {
                "delta": new - old if new is not None and old is not None else None,
                "ci_95": np.percentile(diff, [2.5, 97.5]).tolist() if diff.size else None,
                "valid_draws": len(diff),
            }
    return {"families": len(families), "draws": draws, "seed": seed, "comparisons": comparisons}


def compare(config, test, local_names):
    from minda_colab.score import save_scores, score_oracle, summarize

    references = read_jsonl(test / "references/cases.jsonl")
    transcripts = read_jsonl(test / "inputs/transcripts.jsonl")
    if [{key: case[key] for key in PUBLIC} for case in references] != transcripts:
        raise ValueError("Holdout transcripts and scoring references differ.")
    oracle_refs = read_jsonl(test / "references/relations_targets.jsonl")
    per_model, table = {}, []
    for name in (*COLAB_MODELS, *local_names):
        local = name in local_names
        folder = HERE / name if local else COLAB_REPORT / "test" / name
        if local and read_json(folder / "prediction_input.json")["protocol_sha256"] != sha(HERE / "protocol.json"):
            raise ValueError(f"{name} used a different holdout protocol.")
        graphs = read_jsonl(folder / "graphs.jsonl")
        oracle = read_jsonl(folder / "gold_event_links.jsonl")
        metrics, rows = summarize(references, graphs)
        metrics["oracle_linker"] = score_oracle(oracle, oracle_refs)
        per_model[name] = rows
        if local:
            save_scores(folder, metrics, rows)
        else:
            reported = read_json(folder / "metrics.json")
            for key in ("event", "relation_end_to_end", "state_exact", "oracle_linker"):
                if reported[key] != metrics[key]:
                    raise ValueError(f"Saved Colab scores diverge on {name}/{key}.")
        table.append({
            "model": name, "label": LABELS[name], "runtime": "MLX/Apple M4" if local else "NF4/NVIDIA L4",
            "cases": metrics["cases"], "families": metrics["families"],
            "event_f1": metrics["event"]["f1"],
            "relation_f1": metrics["relation_end_to_end"]["f1"],
            "relation_tp": metrics["relation_end_to_end"]["tp"],
            "relation_fp": metrics["relation_end_to_end"]["fp"],
            "relation_fn": metrics["relation_end_to_end"]["fn"],
            "relation_macro_f1": metrics["relation_macro_f1_gold_types"],
            "oracle_relation_f1": metrics["oracle_linker"]["relation_on_gold_events"]["f1"],
            "state_exact": metrics["state_exact"]["accuracy"],
            "state_exact_n": metrics["state_exact"]["correct"],
            "state_exact_support": metrics["state_exact"]["support"],
            "case_latency_median_s": metrics["case_wall_sec_median"],
        })
    table_stream = io.StringIO()
    writer = csv.DictWriter(table_stream, fieldnames=tuple(table[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(table)
    ev = config["evaluation"]
    write_json(HERE / "paired_bootstrap.json", bootstrap(per_model, ev["bootstrap_draws"], ev["bootstrap_seed"]))
    write_text(HERE / "comparison.csv", table_stream.getvalue())
    print(table_stream.getvalue(), end="", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("model", choices=LOCAL_MODELS)
    run.add_argument("snapshot", type=Path)
    score = commands.add_parser("compare")
    score.add_argument("models", nargs="*", choices=LOCAL_MODELS)
    args = parser.parse_args()
    config, split, record = protocol()
    with TemporaryDirectory(prefix="minda-v21-holdout-") as temp:
        test = unpack_holdout(BUNDLE / "Minda_graph_v21_test_holdout.zip", Path(temp), record["test_files"])
        if args.command == "run":
            run_model(args.model, args.snapshot, split, record, config, test)
        else:
            compare(config, test, args.models)


if __name__ == "__main__":
    main()
