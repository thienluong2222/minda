"""Bounded, offline inference in an isolated process; released after each job."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import select
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
MODEL_LOCK = threading.Lock()
RUNTIME_SIGNATURE = "mlx-lm-0.29.1-temp0-v2-lone-closing-quote"
LEGACY_RUNTIME_SIGNATURE = "mlx-lm-0.29.1-temp0-v1"


class ModelSettings(BaseModel):
    runtime_python: str = ".venv-llm/bin/python"
    cache_dir: str = "data/model_cache/minutes/hub"
    model_id: str
    model_revision: str
    embedding_id: str
    embedding_revision: str
    input_token_budget: int = Field(6144, ge=512)
    output_token_budget: int = Field(2048, ge=128)
    request_timeout_sec: float = Field(240, gt=0)
    max_clusters: int = Field(6, ge=2, le=12)
    minimum_silhouette: float = Field(0.08, ge=0, le=1)
    fuzziness: float = Field(2.0, gt=1)
    compact_graph_output: bool = True
    extraction_batch_size: int = Field(6, ge=1, le=24)
    writer_batch_size: int = Field(8, ge=1, le=24)
    information_budget_per_topic: int = Field(0, ge=0)
    prefill_step_size: int = Field(1024, ge=128, le=4096)
    prefix_cache_entries: int = Field(3, ge=0, le=8)
    response_cache: bool = True
    correction_policy: Literal["all", "flagged"] = "all"
    inference_batch_size: int = Field(1, ge=1, le=4)

    def snapshot(self, embedding: bool = False) -> Path:
        name = self.embedding_id if embedding else self.model_id
        revision = self.embedding_revision if embedding else self.model_revision
        return ROOT / self.cache_dir / f"models--{name.replace('/', '--')}" / "snapshots" / revision


def load_model_settings() -> ModelSettings:
    return ModelSettings.model_validate(yaml.safe_load((ROOT / "configs/minutes.yaml").read_text()))


def model_status() -> dict[str, Any]:
    settings = load_model_settings()
    return {
        "runtime_available": (ROOT / settings.runtime_python).is_file(),
        "model_cached": any(settings.snapshot().glob("*.safetensors")),
        "embedding_cached": any(settings.snapshot(True).glob("*.safetensors")),
        "model_id": settings.model_id,
        "model_revision": settings.model_revision,
        "embedding_id": settings.embedding_id,
        "busy": MODEL_LOCK.locked(),
    }


class ModelRuntimeError(RuntimeError):
    """Missing runtime, invalid/truncated model output, or inference failure."""


class ModelSession:
    def __init__(self, log_path: Path, settings: ModelSettings | None = None) -> None:
        self.settings = settings or load_model_settings()
        self.log_path = log_path
        self.calls: list[dict[str, Any]] = []
        self.process: subprocess.Popen[str] | None = None
        self._log: Any = None
        self._file_lock: Any = None

    def __enter__(self) -> ModelSession:
        if not MODEL_LOCK.acquire(blocking=False):
            raise ModelRuntimeError("LLM đang xử lý một biên bản khác. Hãy thử lại sau.")
        try:
            lock_path = ROOT / self.settings.cache_dir / "inference.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_lock = lock_path.open("a")
            try:
                fcntl.flock(self._file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ModelRuntimeError("LLM đang được một tiến trình khác sử dụng.") from exc
            if not (ROOT / self.settings.runtime_python).is_file():
                raise ModelRuntimeError("Chưa cài runtime. Xem docs/LLM_FCM_MINUTES.md.")
            for embedding in (False, True):
                if not any(self.settings.snapshot(embedding).glob("*.safetensors")):
                    raise ModelRuntimeError(
                        "Chưa có đủ model trong cache. Chạy prepare_minutes_models.py."
                    )
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = self.log_path.open("a", encoding="utf-8")
            env = dict(
                os.environ,
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
                TOKENIZERS_PARALLELISM="false",
            )
            self.process = subprocess.Popen(
                [
                    str(ROOT / self.settings.runtime_python),
                    str(ROOT / "scripts/minutes_model_worker.py"),
                    "--config",
                    str(ROOT / "configs/minutes.yaml"),
                    "--prefill-step-size",
                    str(self.settings.prefill_step_size),
                    "--prefix-cache-entries",
                    str(self.settings.prefix_cache_entries),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._log,
                text=True,
                bufsize=1,
                cwd=ROOT,
                env=env,
            )
            self._receive()
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _receive(self) -> dict[str, Any]:
        assert self.process is not None and self.process.stdout is not None
        ready, _, _ = select.select(
            [self.process.stdout], [], [], self.settings.request_timeout_sec
        )
        if not ready:
            raise ModelRuntimeError("LLM vượt thời gian xử lý; xem model_runtime.log.")
        line = self.process.stdout.readline()
        if not line:
            raise ModelRuntimeError("Runtime LLM đã dừng; xem model_runtime.log.")
        result: dict[str, Any] = json.loads(line)
        if "error" in result:
            raise ModelRuntimeError(str(result["error"]))
        return result

    def request(self, op: str, **payload: Any) -> dict[str, Any]:
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(json.dumps({"op": op, **payload}, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        result = self._receive()
        if op == "chat":
            self.calls.append({k: v for k, v in result.items() if k != "text"})
        return result

    def token_count(self, text: str) -> int:
        return int(self.request("tokens", text=text)["count"])

    def generate_json(self, system: str, payload: Any, *, _result=None) -> dict[str, Any]:
        signature_data = {
            "settings": self.settings.model_dump(),
            "system": system,
            "payload": payload,
            "runtime": RUNTIME_SIGNATURE,
        }
        signature = json.dumps(
            signature_data,
            ensure_ascii=False,
            sort_keys=True,
        )
        key = hashlib.sha256(signature.encode()).hexdigest()
        cache = ROOT / self.settings.cache_dir / "responses" / f"{key}.json"
        # Old successful values remain compatible: this parser only adds one
        # syntax repair. Newly repaired responses never overwrite the old namespace.
        legacy_signature = json.dumps(
            {**signature_data, "runtime": LEGACY_RUNTIME_SIGNATURE},
            ensure_ascii=False,
            sort_keys=True,
        )
        legacy_key = hashlib.sha256(legacy_signature.encode()).hexdigest()
        legacy_cache = cache.with_name(legacy_key + ".json")
        for candidate in (cache, legacy_cache) if self.settings.response_cache else ():
            if candidate.is_file():
                saved = json.loads(candidate.read_text())
                self.calls.append(
                    {
                        **saved["metrics"],
                        "cache_hit": True,
                        "wall_sec": 0.0,
                        "legacy_compatible_cache": candidate == legacy_cache,
                    }
                )
                value: dict[str, Any] = saved["value"]
                return value
        result = (
            _result
            if _result is not None
            else self.request(
                "chat",
                system=system,
                user=json.dumps(payload, ensure_ascii=False),
                max_tokens=self.settings.output_token_budget,
            )
        )
        if _result is not None:
            self.calls.append({k: v for k, v in result.items() if k != "text"})
        if result.get("finish_reason") != "stop":
            raise ModelRuntimeError(
                "LLM hết ngân sách token; đầu ra bị từ chối thay vì cắt nội dung."
            )
        raw = str(result["text"]).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Repair only syntax with no content after a complete object.
            value, end = json.JSONDecoder().raw_decode(raw)
            suffix = raw[end:].strip()
            if suffix not in {"}", "}}", '"'}:
                raise ModelRuntimeError("JSON không hợp lệ; không bỏ nội dung phía sau.") from exc
            self.calls[-1]["format_repair"] = (
                "redundant_closing_quote" if suffix == '"' else "redundant_closing_brace"
            )
        if not isinstance(value, dict):
            raise ModelRuntimeError("LLM phải trả một JSON object.")
        cache.parent.mkdir(parents=True, exist_ok=True)
        metrics = {k: v for k, v in self.calls[-1].items() if k != "text"}
        metrics["cache_hit"] = False
        self.calls[-1]["cache_hit"] = False
        if self.settings.response_cache:
            temp = cache.with_suffix(".tmp")
            temp.write_text(json.dumps({"value": value, "metrics": metrics}, ensure_ascii=False))
            temp.replace(cache)
        return value

    def generate_json_many(self, system: str, payloads: list[Any]) -> list[Any]:
        """Bounded independent inference; malformed output fails only its own packet."""
        size = self.settings.inference_batch_size
        # Warm response caches already eliminate inference. Avoid decoding them again.
        if size == 1:
            results = []
            for payload in payloads:
                try:
                    results.append(self.generate_json(system, payload))
                except (ModelRuntimeError, ValueError, TypeError, KeyError) as exc:
                    results.append(exc)
            return results
        results = []
        for start in range(0, len(payloads), size):
            batch = payloads[start : start + size]
            cached = []
            fresh = []
            for i, payload in enumerate(batch):
                exists = False
                if self.settings.response_cache:
                    for signature in (RUNTIME_SIGNATURE, LEGACY_RUNTIME_SIGNATURE):
                        key = hashlib.sha256(
                            json.dumps(
                                {
                                    "settings": self.settings.model_dump(),
                                    "system": system,
                                    "payload": payload,
                                    "runtime": signature,
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            ).encode()
                        ).hexdigest()
                        exists |= (
                            ROOT / self.settings.cache_dir / "responses" / f"{key}.json"
                        ).is_file()
                (cached if exists else fresh).append(i)
            slots = [None] * len(batch)
            for i in cached:
                try:
                    slots[i] = self.generate_json(system, batch[i])
                except (ModelRuntimeError, ValueError, TypeError, KeyError) as exc:
                    slots[i] = exc
            if not fresh:
                results.extend(slots)
                continue
            try:
                response = self.request(
                    "chat_batch",
                    requests=[
                        {
                            "system": system,
                            "user": json.dumps(p, ensure_ascii=False),
                            "max_tokens": self.settings.output_token_budget,
                        }
                        for p in [batch[i] for i in fresh]
                    ],
                )
                raw = response["results"]
                if not isinstance(raw, list) or len(raw) != len(fresh):
                    raise ModelRuntimeError("Batch runtime trả thiếu kết quả.")
            except (ModelRuntimeError, ValueError, TypeError, KeyError):
                for i in fresh:
                    try:
                        slots[i] = self.generate_json(system, batch[i])
                    except (ModelRuntimeError, ValueError, TypeError, KeyError) as exc:
                        slots[i] = exc
                results.extend(slots)
                continue
            for i, item in zip(fresh, raw, strict=True):
                try:
                    slots[i] = self.generate_json(system, batch[i], _result=item)
                except (ModelRuntimeError, ValueError, TypeError, KeyError) as exc:
                    slots[i] = exc
            results.extend(slots)
        return results

    def embed(self, texts: list[str]) -> list[list[float]]:
        key = hashlib.sha256(
            json.dumps(
                {
                    "texts": texts,
                    "id": self.settings.embedding_id,
                    "revision": self.settings.embedding_revision,
                    "pooling": "masked_mean_l2_query",
                },
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        cache = ROOT / self.settings.cache_dir / "embeddings" / f"{key}.json"
        if cache.is_file():
            vectors: list[list[float]] = json.loads(cache.read_text())
            return vectors
        result: list[list[float]] = self.request("embed", texts=texts)["vectors"]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result))
        return result

    def __exit__(self, *_: Any) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe is not None:
                    pipe.close()
        if self._log is not None:
            self._log.close()
        if self._file_lock is not None:
            self._file_lock.close()
        MODEL_LOCK.release()


def timed_call(session: ModelSession, system: str, payload: Any) -> tuple[dict[str, Any], float]:
    start = time.perf_counter()
    return session.generate_json(system, payload), time.perf_counter() - start
