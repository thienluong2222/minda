from types import SimpleNamespace

import pytest

from meeting_pipeline.asr.cache import decoding_fingerprint
from meeting_pipeline.config import AsrConfig
from meeting_pipeline.minutes.graph_builder import extraction_rows
from meeting_pipeline.minutes.graph_contracts import Paragraph
from meeting_pipeline.minutes.graph_writer import verify_paragraphs


def graph_for(texts, kinds=None):
    from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
    from meeting_pipeline.minutes.graph_builder import build_graph, fallback_event
    from meeting_pipeline.minutes.graph_inputs import make_graph_units

    turns = [
        IndexedTurn(
            turn_id=str(i),
            speaker_label="An",
            speaker_id="An",
            text=text,
            start_sec=i,
            end_sec=i + 1,
            tokens=[],
            source_id="mic",
            clip_path=None,
            asr_status="transcribed",
            needs_review=False,
            confidence=None,
        )
        for i, text in enumerate(texts)
    ]
    units, _ = make_graph_units(turns)
    events = [
        fallback_event(u).model_copy(
            update={"kind": kinds[i] if kinds else "information", "extraction": "model"}
        )
        for i, u in enumerate(units)
    ]
    return build_graph(
        "m",
        units,
        events,
        {
            "primary": [0] * len(units),
            "membership": [[1.0]] * len(units),
            "titles": ["Tiến độ"],
            "cluster_count": 1,
        },
        [],
    )


def test_plan_merges_exact_repetition_but_never_distinct_tasks_or_dissent():
    from meeting_pipeline.minutes.graph_writer import plan_sections

    graph = graph_for(
        [
            "Tiến độ ổn.",
            "Tiến độ ổn.",
            "An gửi 20 hồ sơ.",
            "An gửi 200 hồ sơ.",
            "Tôi phản đối.",
            "Tôi phản đối.",
        ],
        ["information", "information", "task", "task", "objection", "objection"],
    )
    sections, ledger = plan_sections(graph)
    assert len(sections[0].claim_ids) == 5
    assert sum(r["disposition"] == "merged" for r in ledger) == 1
    assert len(graph.events) == 6
    _budget_sections, rows = plan_sections(graph, information_budget=1)
    assert all(r["disposition"] == "included" for r in rows if r.get("critical"))


def test_context_dependent_agreements_are_never_deduplicated_as_information():
    from meeting_pipeline.minutes.graph_writer import plan_sections

    graph = graph_for(["Tôi đồng ý.", "Tôi đồng ý."])
    sections, ledger = plan_sections(graph)
    assert len(sections[0].claim_ids) == 2
    assert all(row["disposition"] == "included" for row in ledger)


@pytest.mark.parametrize("valid_context", [True, False])
def test_compact_writer_validates_optional_context_citations(valid_context):
    from meeting_pipeline.minutes.graph_writer import plan_sections, write_sections

    graph = graph_for(["Nhóm có 3 thành viên.", "An gửi 20 hồ sơ."], ["information", "task"])
    sections, _ = plan_sections(graph)
    sections[0].claim_ids = [graph.events[1].event_id]

    class Session:
        settings = SimpleNamespace(
            input_token_budget=6144, output_token_budget=2048, compact_graph_output=True
        )

        def token_count(self, text):
            return len(text.split())

        def generate_json(self, system, payload):
            if "Kiểm tra từng đoạn" in system:
                return {"checks": [{"paragraph_index": 0, "verdict": "supported"}]}
            return {
                "text": "An gửi 20 hồ sơ.",
                "evidence_ids": [payload["sources"][0]["unit_id"] if valid_context else "foreign"],
            }

    written, _ = write_sections(Session(), graph, sections)
    paragraph = written[0].paragraphs[0]
    assert (paragraph.verification == "checked") == valid_context
    if valid_context:
        assert set(paragraph.evidence_ids) == {graph.units[1].unit_id}


def test_compact_writer_still_rejects_semantic_omission():
    from meeting_pipeline.minutes.graph_writer import plan_sections, write_sections

    graph = graph_for(["An gửi hồ sơ.", "Bình kiểm tra báo cáo."], ["task", "task"])
    sections, _ = plan_sections(graph)

    class Session:
        settings = SimpleNamespace(
            input_token_budget=6144, output_token_budget=2048, compact_graph_output=True
        )

        def token_count(self, text):
            return len(text.split())

        def generate_json(self, system, payload):
            if "Kiểm tra từng đoạn" in system:
                return {
                    "checks": [
                        {
                            "paragraph_index": 0,
                            "verdict": "unsupported",
                            "missing_claim_ids": ["c1"],
                        }
                    ]
                }
            return {"text": "An gửi hồ sơ."}

    written, _audit = write_sections(Session(), graph, sections)
    assert written[0].paragraphs
    assert all(p.verification == "source_fallback" for p in written[0].paragraphs)
    assert "Bình" in " ".join(p.text for p in written[0].paragraphs)


def test_mixed_json_batch_isolates_bad_output_and_keeps_order(tmp_path):
    from meeting_pipeline.minutes.model_runtime import (
        ModelRuntimeError,
        ModelSession,
        ModelSettings,
    )

    class Session(ModelSession):
        def request(self, op, **payload):
            assert op == "chat_batch"
            return {
                "results": [
                    {"text": '{"ok":1}', "finish_reason": "stop"},
                    {"text": "bad", "finish_reason": "stop"},
                ]
            }

    settings = ModelSettings(
        model_id="x",
        model_revision="x",
        embedding_id="x",
        embedding_revision="x",
        cache_dir=str(tmp_path),
        inference_batch_size=2,
        response_cache=False,
    )
    session = Session(tmp_path / "log", settings)
    results = session.generate_json_many("s", [{"id": 1}, {"id": 2}])
    assert results[0] == {"ok": 1}
    assert isinstance(results[1], (ModelRuntimeError, ValueError))


def test_auto_runtime_retries_failed_acceleration_on_same_cpu_checkpoint(monkeypatch, tmp_path):
    import numpy as np

    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter

    class BadPipe:
        device = "mps"

        def __call__(self, *args, **kwargs):
            return {
                "text": "a " * 100,
                "chunks": [{"text": "a", "timestamp": [0, 0.01]} for _ in range(100)],
            }

    def load(adapter):
        if adapter.config.runtime != "cpu":
            return BadPipe()
        return lambda *args, **kwargs: {
            "text": "xin chào",
            "chunks": [
                {"text": "xin", "timestamp": [0.1, 0.3]},
                {"text": "chào", "timestamp": [0.3, 0.5]},
            ],
        }

    monkeypatch.setattr(PhoWhisperAsrAdapter, "_load_pipeline", load)
    cfg = AsrConfig(model_id="same", model_revision="same", runtime="auto", max_decode_attempts=1)
    adapter = PhoWhisperAsrAdapter(cfg, tmp_path)
    result = adapter.transcribe(np.ones(16000, dtype=np.float32))
    assert result.status == "transcribed" and result.text == "xin chào"
    assert "asr_cpu_fallback" in result.warnings
    assert len(result.raw_candidates) == 2
    assert adapter._cpu_fallback.config.model_id == cfg.model_id


def test_mlx_does_not_repeat_an_identical_greedy_decode(tmp_path):
    import numpy as np

    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter

    class Pipe:
        device = "mlx"
        count = 0

        def __call__(self, *args, **kwargs):
            self.count += 1
            return {
                "text": "a " * 100,
                "chunks": [{"text": "a", "timestamp": [0, 0.01]} for _ in range(100)],
            }

    adapter = PhoWhisperAsrAdapter(
        AsrConfig(model_id="x", model_revision="x", runtime="mlx"), tmp_path
    )
    adapter._pipeline = Pipe()
    result = adapter.transcribe(np.ones(16000, dtype=np.float32))
    assert result.status == "unreliable" and adapter._pipeline.count == 1


def test_optional_budget_accounts_for_omissions_and_preserves_tasks():
    from meeting_pipeline.minutes.graph_writer import plan_sections

    graph = graph_for(
        ["Tiến độ ổn.", "Thiết bị hoạt động.", "An nhận việc."],
        ["information", "information", "task"],
    )
    sections, ledger = plan_sections(graph, information_budget=1)
    assert sum(row["disposition"] == "context_only" for row in ledger) == 1
    assert graph.events[-1].event_id in sections[0].claim_ids
    assert len(graph.units) == len(ledger) == 3


def test_batch_response_cache_avoids_inference_and_preserves_request_order(tmp_path):
    from meeting_pipeline.minutes.model_runtime import ModelSession, ModelSettings

    class Session(ModelSession):
        count = 0

        def request(self, op, **payload):
            assert op == "chat_batch"
            self.count += 1
            return {
                "results": [
                    {"text": r["user"], "finish_reason": "stop"} for r in payload["requests"]
                ]
            }

    settings = ModelSettings(
        model_id="x",
        model_revision="x",
        embedding_id="x",
        embedding_revision="x",
        cache_dir=str(tmp_path),
        inference_batch_size=2,
    )
    first = Session(tmp_path / "log", settings)
    assert first.generate_json_many("s", [{"id": 1}, {"id": 2}]) == [{"id": 1}, {"id": 2}]
    warm = Session(tmp_path / "log2", settings)
    assert warm.generate_json_many("s", [{"id": 2}, {"id": 1}]) == [{"id": 2}, {"id": 1}]
    assert warm.count == 0
    assert warm.generate_json_many("s", [{"id": 3}, {"id": 1}]) == [{"id": 3}, {"id": 1}]
    assert warm.count == 1


def test_failed_batch_retries_individually_instead_of_dropping_packets(tmp_path):
    from meeting_pipeline.minutes.model_runtime import (
        ModelRuntimeError,
        ModelSession,
        ModelSettings,
    )

    class Session(ModelSession):
        def request(self, op, **payload):
            if op == "chat_batch":
                raise ModelRuntimeError("batch unavailable")
            result = {"text": payload["user"], "finish_reason": "stop"}
            self.calls.append({"finish_reason": "stop"})
            return result

    settings = ModelSettings(
        model_id="x",
        model_revision="x",
        embedding_id="x",
        embedding_revision="x",
        cache_dir=str(tmp_path),
        inference_batch_size=2,
        response_cache=False,
    )
    session = Session(tmp_path / "log", settings)
    assert session.generate_json_many("s", [{"id": 1}, {"id": 2}]) == [{"id": 1}, {"id": 2}]


def test_obvious_numeric_failure_never_calls_semantic_model():
    class Session:
        def generate_json(self, *args):
            raise AssertionError("The deterministic rejection is already final")

    checks = verify_paragraphs(
        Session(),
        [Paragraph(text="An gửi 200 hồ sơ.", claim_ids=["c1"], evidence_ids=["u1"])],
        {
            "sources": [{"unit_id": "u1", "text": "An gửi 20 hồ sơ.", "speaker": "An"}],
            "claims": [],
            "relations": [],
        },
    )
    assert checks[0]["verdict"] == "deterministic_rejected"
    assert checks[0]["numeric_conflicts"]
    assert checks[0]["risks"]


def test_mixed_packet_verifies_only_valid_paragraph_with_original_index():
    class Session:
        def generate_json(self, system, payload):
            assert [p["paragraph_index"] for p in payload["paragraphs"]] == [1]
            return {"checks": [{"paragraph_index": 1, "verdict": "supported"}]}

    paragraphs = [
        Paragraph(text=t, claim_ids=["c1"], evidence_ids=["u1"])
        for t in ["An gửi 200 hồ sơ.", "An gửi 20 hồ sơ."]
    ]
    checks = verify_paragraphs(
        Session(),
        paragraphs,
        {
            "sources": [{"unit_id": "u1", "text": "An gửi 20 hồ sơ.", "speaker": "An"}],
            "claims": [],
            "relations": [],
        },
    )
    assert checks[0]["risks"] and not checks[1]["risks"]


@pytest.mark.parametrize("raw", [[["u0", "task", {"unit_id": "u1"}]], ["bad"], None])
def test_invalid_compact_extraction_fails_closed(raw):
    with pytest.raises(ValueError):
        extraction_rows(raw)


def test_compact_extraction_and_runtime_cache_namespace():
    assert extraction_rows([["u0", "task", {"owner": "An"}]])[0]["owner"] == "An"
    cpu = AsrConfig(model_id="x", model_revision="x", runtime="cpu")
    assert decoding_fingerprint(cpu) != decoding_fingerprint(
        cpu.model_copy(update={"runtime": "mps"})
    )
