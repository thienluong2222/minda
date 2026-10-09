"""JSON-lines worker. Run only with the isolated MLX Python environment."""

from __future__ import annotations

import argparse
import contextlib
import json
import resource
import sys
import time
import traceback
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    settings = yaml.safe_load(args.config.read_text())
    root = args.config.resolve().parent.parent
    cache = root / settings["cache_dir"]
    model = tokenizer = encoder = encoder_tokenizer = None
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            start = time.perf_counter()
            op = request["op"]
            with contextlib.redirect_stdout(sys.stderr):
                if op in {"chat", "tokens"} and model is None:
                    from mlx_lm import load

                    path = cache / ("models--" + settings["model_id"].replace("/", "--"))
                    path = path / "snapshots" / settings["model_revision"]
                    model, tokenizer = load(str(path))
                if op == "tokens":
                    result = {"count": len(tokenizer.encode(request["text"]))}
                elif op == "chat":
                    import mlx.core as mx
                    from mlx_lm import stream_generate
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
                    parts = []
                    response = None
                    for response in stream_generate(
                        model,
                        tokenizer,
                        prompt=prompt,
                        max_tokens=request["max_tokens"],
                        sampler=make_sampler(temp=0),
                        prefill_step_size=512,
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
                    }
                    mx.clear_cache()
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
