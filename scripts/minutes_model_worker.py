"""JSON-lines worker. Run only with the isolated MLX Python environment."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import resource
import sys
import time
import traceback
from collections import OrderedDict
from pathlib import Path

import yaml


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _attach_adapter(
    model,
    adapter_dir: Path,
    expected_weights_sha: str | None = None,
    expected_cfg_sha: str | None = None,
) -> list[tuple[object, float]]:
    import mlx.core as mx
    from mlx.utils import tree_flatten
    from mlx_lm.tuner.utils import linear_to_lora_layers, load_adapters

    cfg_path = adapter_dir / "adapter_config.json"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Thiếu adapter_config.json tại {adapter_dir}")
    if expected_cfg_sha and _sha256(cfg_path) != expected_cfg_sha:
        raise ValueError("Checksum adapter_config.json không khớp.")

    mlx_weights = adapter_dir / "adapters.safetensors"
    peft_weights = adapter_dir / "adapter_model.safetensors"
    if mlx_weights.is_file():
        if expected_weights_sha and _sha256(mlx_weights) != expected_weights_sha:
            raise ValueError("Checksum adapters.safetensors không khớp.")
        load_adapters(model, str(adapter_dir))
        layers = [
            (mod, float(mod.scale))
            for _, mod in model.named_modules()
            if hasattr(mod, "lora_a") and hasattr(mod, "scale")
        ]
        if not layers:
            raise ValueError("Không tìm thấy tầng LoRA sau khi nạp MLX adapter.")
        return layers

    if not peft_weights.is_file():
        raise FileNotFoundError(f"Thiếu trọng số LoRA tại {adapter_dir}")
    if expected_weights_sha and _sha256(peft_weights) != expected_weights_sha:
        raise ValueError("Checksum adapter_model.safetensors không khớp.")

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if cfg.get("peft_type") != "LORA" or cfg.get("use_dora"):
        raise ValueError("Chỉ hỗ trợ adapter PEFT loại LORA chuẩn.")
    target_modules = set(cfg.get("target_modules") or [])
    mlx_keys = sorted(
        path
        for path, _ in model.layers[0].named_modules()
        if path.split(".")[-1] in target_modules
    )
    if not mlx_keys:
        raise ValueError("Không ánh xạ được target_modules của PEFT sang mô hình MLX.")

    rank = int(cfg["r"])
    nominal_scale = float(cfg["lora_alpha"]) / float(rank)
    linear_to_lora_layers(
        model,
        len(model.layers),
        {"rank": rank, "scale": nominal_scale, "dropout": 0.0, "keys": mlx_keys},
    )
    peft_tensors = mx.load(str(peft_weights))
    model_params = dict(tree_flatten(model.parameters()))
    converted: list[tuple[str, object]] = []
    for key, tensor in peft_tensors.items():
        if key.endswith(".lora_A.weight"):
            target_key = key.removeprefix("base_model.model.").replace(".lora_A.weight", ".lora_a")
        elif key.endswith(".lora_B.weight"):
            target_key = key.removeprefix("base_model.model.").replace(".lora_B.weight", ".lora_b")
        else:
            continue
        transposed = tensor.T
        if target_key not in model_params or model_params[target_key].shape != transposed.shape:
            raise ValueError(f"Tensor adapter không khớp kiến trúc mô hình: {target_key}")
        converted.append((target_key, transposed))

    if len(converted) != len(peft_tensors):
        raise ValueError("Phát hiện tensor chưa được ánh xạ khi nạp PEFT adapter.")
    model.load_weights(converted, strict=False)
    mx.eval(model.parameters())
    layers = [
        (mod, nominal_scale)
        for _, mod in model.named_modules()
        if hasattr(mod, "lora_a") and hasattr(mod, "scale")
    ]
    if not layers:
        raise ValueError("Không gắn được tầng LoRA nào lên mô hình.")
    return layers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--prefill-step-size", type=int, default=1024)
    parser.add_argument("--prefix-cache-entries", type=int, default=3)
    parser.add_argument("--adapter-path", type=Path, default=None)
    parser.add_argument("--adapter-sha256", type=str, default=None)
    parser.add_argument("--adapter-config-sha256", type=str, default=None)
    args = parser.parse_args()
    settings = yaml.safe_load(args.config.read_text())
    root = args.config.resolve().parent.parent
    cache = root / settings["cache_dir"]
    model = tokenizer = encoder = encoder_tokenizer = None
    lora_layers: list[tuple[object, float]] = []
    adapter_active: bool | None = None
    prefixes = OrderedDict()

    def _set_adapter(want: bool) -> bool:
        nonlocal adapter_active
        effective = bool(want and lora_layers)
        if effective != adapter_active:
            for mod, nominal_scale in lora_layers:
                mod.scale = nominal_scale if effective else 0.0
            adapter_active = effective
        return effective

    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            start = time.perf_counter()
            op = request["op"]
            with contextlib.redirect_stdout(sys.stderr):
                if op in {"chat", "chat_batch", "tokens"} and model is None:
                    from mlx_lm import load

                    path = cache / ("models--" + settings["model_id"].replace("/", "--"))
                    path = path / "snapshots" / settings["model_revision"]
                    model, tokenizer = load(str(path))
                    raw_adapter = args.adapter_path or settings.get("adapter_path")
                    if raw_adapter:
                        adapter_dir = (
                            raw_adapter
                            if Path(raw_adapter).is_absolute()
                            else root / raw_adapter
                        )
                        lora_layers = _attach_adapter(
                            model,
                            Path(adapter_dir),
                            args.adapter_sha256 or settings.get("adapter_sha256"),
                            args.adapter_config_sha256 or settings.get("adapter_config_sha256"),
                        )
                if op == "tokens":
                    result = {"count": len(tokenizer.encode(request["text"]))}
                elif op == "chat":
                    import mlx.core as mx
                    from mlx_lm import stream_generate
                    from mlx_lm.models.cache import (
                        can_trim_prompt_cache,
                        make_prompt_cache,
                        trim_prompt_cache,
                    )
                    from mlx_lm.sample_utils import make_sampler

                    use_adapter = _set_adapter(bool(request.get("use_adapter", False)))
                    prompt = tokenizer.apply_chat_template(
                        [
                            {"role": "system", "content": request["system"]},
                            {"role": "user", "content": request["user"]},
                        ],
                        tokenize=False,
                        add_generation_prompt=True,
                    )
                    count = len(tokenizer.encode(prompt))
                    if count > settings["input_token_budget"]:
                        raise ValueError(
                            f"Prompt {count} tokens vượt giới hạn; cần chia nhỏ đầu vào."
                        )
                    mx.reset_peak_memory()
                    tokens = tokenizer.encode(prompt)
                    prefix = tokenizer.apply_chat_template(
                        [{"role": "system", "content": request["system"]}],
                        tokenize=True,
                        add_generation_prompt=False,
                    )
                    prefix_key = (use_adapter, tuple(prefix))
                    prefix_ok = tokens[: len(prefix)] == prefix
                    cache_hit = prefix_ok and prefix_key in prefixes
                    if cache_hit:
                        kv = copy.deepcopy(prefixes[prefix_key])
                        prefixes.move_to_end(prefix_key)
                        remaining = tokens[len(prefix) :]
                    else:
                        kv = make_prompt_cache(model)
                        remaining = tokens
                    parts = []
                    response = None
                    for response in stream_generate(
                        model,
                        tokenizer,
                        prompt=remaining,
                        prompt_cache=kv,
                        max_tokens=request["max_tokens"],
                        sampler=make_sampler(temp=0),
                        prefill_step_size=args.prefill_step_size,
                    ):
                        parts.append(response.text)
                    if response is None:
                        raise ValueError("Empty generation")
                    result = {
                        "text": "".join(parts),
                        "prompt_tokens": count,
                        "generation_tokens": response.generation_tokens,
                        "finish_reason": response.finish_reason,
                        "peak_mlx_gb": mx.get_peak_memory() / 1e9,
                        "prefix_cache_tokens": len(prefix) if cache_hit else 0,
                        "prompt_tps": response.prompt_tps,
                        "generation_tps": response.generation_tps,
                        "adapter_active": use_adapter,
                    }
                    if prefix_ok and args.prefix_cache_entries and can_trim_prompt_cache(kv):
                        trim_prompt_cache(kv, kv[0].offset - len(prefix))
                        prefixes[prefix_key] = kv
                        prefixes.move_to_end(prefix_key)
                        while len(prefixes) > args.prefix_cache_entries:
                            prefixes.popitem(last=False)
                    mx.clear_cache()
                elif op == "chat_batch":
                    import mlx.core as mx
                    from mlx_lm.generate import BatchGenerator

                    requests = request["requests"]
                    if not 1 <= len(requests) <= 4:
                        raise ValueError("Batch phải có từ 1 đến 4 requests.")
                    adapter_flags = {bool(r.get("use_adapter", False)) for r in requests}
                    if len(adapter_flags) > 1:
                        raise ValueError("Batch không thể trộn yêu cầu bật/tắt adapter.")
                    use_adapter = _set_adapter(next(iter(adapter_flags)))
                    prompts = [
                        tokenizer.apply_chat_template(
                            [
                                {"role": "system", "content": r["system"]},
                                {"role": "user", "content": r["user"]},
                            ],
                            tokenize=True,
                            add_generation_prompt=True,
                        )
                        for r in requests
                    ]
                    if any(len(p) > settings["input_token_budget"] for p in prompts):
                        raise ValueError("Batch vượt ngân sách prompt; cần chia nhỏ.")
                    generator = BatchGenerator(
                        model,
                        stop_tokens=tokenizer.eos_token_ids,
                        prefill_batch_size=len(requests),
                        completion_batch_size=len(requests),
                        prefill_step_size=args.prefill_step_size,
                    )
                    try:
                        ids = generator.insert(prompts, [r["max_tokens"] for r in requests])
                        tokens_by_id = {uid: [] for uid in ids}
                        reasons = {}
                        while batch := generator.next():
                            for response in batch:
                                if response.finish_reason != "stop":
                                    tokens_by_id[response.uid].append(response.token)
                                if response.finish_reason:
                                    reasons[response.uid] = response.finish_reason
                        elapsed = time.perf_counter() - start
                        result = {
                            "results": [
                                {
                                    "text": tokenizer.decode(tokens_by_id[uid]),
                                    "prompt_tokens": len(prompts[i]),
                                    "generation_tokens": len(tokens_by_id[uid]),
                                    "finish_reason": reasons.get(uid, "length"),
                                    "wall_sec": elapsed / len(ids),
                                    "batch_size": len(ids),
                                    "peak_mlx_gb": mx.get_peak_memory() / 1e9,
                                    "adapter_active": use_adapter,
                                }
                                for i, uid in enumerate(ids)
                            ]
                        }
                    finally:
                        generator.close()
                elif op == "embed":
                    import torch
                    from transformers import AutoModel, AutoTokenizer

                    if encoder is None:
                        path = cache / ("models--" + settings["embedding_id"].replace("/", "--"))
                        path = path / "snapshots" / settings["embedding_revision"]
                        encoder_tokenizer = AutoTokenizer.from_pretrained(
                            path, local_files_only=True
                        )
                        encoder = AutoModel.from_pretrained(path, local_files_only=True)
                        encoder.eval()
                        torch.set_num_threads(2)
                    texts = ["query: " + text for text in request["texts"]]
                    batch = encoder_tokenizer(
                        texts, padding=True, truncation=False, return_tensors="pt"
                    )
                    if batch["input_ids"].shape[1] > 512:
                        raise ValueError("Đơn vị ý nghĩa vượt 512 tokens của E5; không tự cắt bỏ.")
                    with torch.inference_mode():
                        hidden = encoder(**batch).last_hidden_state
                        mask = batch["attention_mask"].unsqueeze(-1)
                        vectors = (hidden * mask).sum(1) / mask.sum(1)
                        vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
                    result = {"vectors": vectors.tolist()}
                else:
                    raise ValueError(f"Unknown operation: {op}")
            result["wall_sec"] = round(time.perf_counter() - start, 4)
            result["peak_worker_rss_gb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
