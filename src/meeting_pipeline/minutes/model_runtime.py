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
PROMPT_TASK_BY_SHA256 = {
    "1e4c584030c035c1bcf8ccb722ebf20306beb51833d7ca101a3e4615638e02e3": "extract",
    "5d3691add012435969b8154909f4d3a6d6f635de969af66f2d72230d911d2ff3": "relations",
}
_ADAPTER_SETTING_FIELDS = (
    "adapter_path",
    "adapter_sha256",
    "adapter_config_sha256",
    "adapter_scopes",
)


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class ModelSettings(BaseModel):
    runtime_python: str = ".venv-llm/bin/python"
    cache_dir: str = "data/model_cache/minutes/hub"
    model_id: str
    model_revision: str
    adapter_path: str | None = None
    adapter_sha256: str | None = None
    adapter_config_sha256: str | None = None
    adapter_scopes: list[str] = Field(default_factory=lambda: ["extract", "relations"])
    embedding_id: str
    embedding_revision: str
    input_token_budget: int = Field(6144, ge=512)
    output_token_budget: int = Field(2048, ge=128)
    request_timeout_sec: float = Field(240, gt=0)
    max_clusters: int = Field(6, ge=2, le=12)
    minimum_silhouette: float = Field(0.22, ge=0, le=1)
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

    def adapter_dir(self) -> Path | None:
        if not self.adapter_path:
            return None
        candidate = Path(self.adapter_path)
        return candidate if candidate.is_absolute() else ROOT / candidate


def task_for_prompt(system: str) -> str:
    return PROMPT_TASK_BY_SHA256.get(hashlib.sha256(system.encode()).hexdigest(), "default")


def adapter_active_for(settings: ModelSettings, system: str) -> bool:
    if not settings.adapter_path:
        return False
    scopes = set(settings.adapter_scopes)
    return "all" in scopes or "*" in scopes or task_for_prompt(system) in scopes


def verify_adapter_dir(adapter_dir: Path, settings: ModelSettings) -> Path:
    """Validate local PEFT or MLX LoRA adapter files and optional pinned SHA-256 digests."""
    cfg_path = adapter_dir / "adapter_config.json"
    weights_path = (
        adapter_dir / "adapter_model.safetensors"
        if (adapter_dir / "adapter_model.safetensors").is_file()
        else adapter_dir / "adapters.safetensors"
    )
    if not cfg_path.is_file() or not weights_path.is_file():
        raise ModelRuntimeError(f"Thiếu tệp trọng số/cấu hình adapter LoRA tại {adapter_dir}.")
    if settings.adapter_config_sha256 and _file_sha256(cfg_path) != settings.adapter_config_sha256:
        raise ModelRuntimeError("Checksum adapter_config.json không khớp cấu hình đã ghim.")
    if settings.adapter_sha256 and _file_sha256(weights_path) != settings.adapter_sha256:
        raise ModelRuntimeError("Checksum trọng số adapter LoRA không khớp cấu hình đã ghim.")
    return weights_path


def load_model_settings() -> ModelSettings:
    return ModelSettings.model_validate(yaml.safe_load((ROOT / "configs/minutes.yaml").read_text()))


def model_status() -> dict[str, Any]:
    settings = load_model_settings()
    adapter_dir = settings.adapter_dir()
    adapter_ok = True
    if adapter_dir is not None:
        try:
            verify_adapter_dir(adapter_dir, settings)
        except ModelRuntimeError:
            adapter_ok = False
    return {
        "runtime_available": (ROOT / settings.runtime_python).is_file(),
        "model_cached": any(settings.snapshot().glob("*.safetensors")),
        "embedding_cached": any(settings.snapshot(True).glob("*.safetensors")),
        "model_id": settings.model_id,
        "model_revision": settings.model_revision,
        "adapter_configured": adapter_dir is not None,
        "adapter_cached": adapter_ok if adapter_dir is not None else False,
        "adapter_path": settings.adapter_path,
        "adapter_sha256": settings.adapter_sha256,
        "adapter_scopes": list(settings.adapter_scopes),
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
            adapter_dir = self.settings.adapter_dir()
            if adapter_dir is not None:
                verify_adapter_dir(adapter_dir, self.settings)
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = self.log_path.open("a", encoding="utf-8")
            env = dict(
                os.environ,
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
                TOKENIZERS_PARALLELISM="false",
            )
            cmd = [
                str(ROOT / self.settings.runtime_python),
                str(ROOT / "scripts/minutes_model_worker.py"),
                "--config",
                str(ROOT / "configs/minutes.yaml"),
                "--prefill-step-size",
                str(self.settings.prefill_step_size),
                "--prefix-cache-entries",
                str(self.settings.prefix_cache_entries),
            ]
            if adapter_dir is not None:
                cmd.extend(["--adapter-path", str(adapter_dir)])
                if self.settings.adapter_sha256:
                    cmd.extend(["--adapter-sha256", self.settings.adapter_sha256])
                if self.settings.adapter_config_sha256:
                    cmd.extend(["--adapter-config-sha256", self.settings.adapter_config_sha256])
            self.process = subprocess.Popen(
                cmd,
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

    def _cache_keys(self, system: str, payload: Any, use_adapter: bool) -> tuple[Path, Path | None]:
        settings_data = self.settings.model_dump()
        for field in _ADAPTER_SETTING_FIELDS:
            if not use_adapter or field == "adapter_path":
                # Omit local path differences when hashing; pin weights via SHA-256 instead.
                settings_data.pop(field, None)
        signature_data: dict[str, Any] = {
            "settings": settings_data,
            "system": system,
            "payload": payload,
            "runtime": RUNTIME_SIGNATURE,
        }
        if use_adapter:
            signature_data["adapter_active"] = True
            signature_data["adapter_id"] = self.settings.adapter_path
        responses_dir = ROOT / self.settings.cache_dir / "responses"
        key = hashlib.sha256(
            json.dumps(signature_data, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        cache = responses_dir / f"{key}.json"
        if use_adapter:
            return cache, None
        legacy_key = hashlib.sha256(
            json.dumps(
                {**signature_data, "runtime": LEGACY_RUNTIME_SIGNATURE},
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return cache, cache.with_name(legacy_key + ".json")

    def generate_json(self, system: str, payload: Any, *, _result=None) -> dict[str, Any]:
        use_adapter = adapter_active_for(self.settings, system)
        task_name = task_for_prompt(system)
        cache, legacy_cache = self._cache_keys(system, payload, use_adapter)
        candidates = (cache, legacy_cache) if legacy_cache is not None else (cache,)
        for candidate in candidates if self.settings.response_cache else ():
            if candidate.is_file():
                saved = json.loads(candidate.read_text())
                self.calls.append(
                    {
                        **saved["metrics"],
                        "task": saved["metrics"].get("task", task_name),
                        "adapter_active": saved["metrics"].get("adapter_active", use_adapter),
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
                use_adapter=use_adapter,
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
        self.calls[-1]["task"] = task_name
        self.calls[-1]["adapter_active"] = bool(result.get("adapter_active", use_adapter))
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
        use_adapter = adapter_active_for(self.settings, system)
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
                    cache, legacy = self._cache_keys(system, payload, use_adapter)
                    exists = cache.is_file() or (legacy is not None and legacy.is_file())
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
                            "use_adapter": use_adapter,
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
