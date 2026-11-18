"""JSON-lines worker. Run only with the isolated MLX Python environment."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import resource
import sys
import time
import traceback
from collections import OrderedDict
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--prefill-step-size", type=int, default=1024)
    parser.add_argument("--prefix-cache-entries", type=int, default=3)
    args = parser.parse_args()
    settings = yaml.safe_load(args.config.read_text())
    root = args.config.resolve().parent.parent
    cache = root / settings["cache_dir"]
    model = tokenizer = encoder = encoder_tokenizer = None
    prefixes = OrderedDict()
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
                    prefix_key = tuple(prefix)
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
