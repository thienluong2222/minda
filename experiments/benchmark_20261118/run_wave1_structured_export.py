"""Wave 1-3: Structured fields (ND30/2020), parser/schema mapper, and graph export guard benchmark."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT, ROOT, log, read_json, rss_mb, setup_root_src, write_csv, write_json


def make_turns(texts: list[tuple[str, str]], prefix: str = "t") -> list:
    from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn

    return [
        IndexedTurn(
            turn_id=f"{prefix}_{i:04d}",
            speaker_label=spk,
            speaker_id=f"spk_{i % 3}",
            start_sec=float(i * 5),
            end_sec=float(i * 5 + 4),
            text=txt,
            tokens=txt.lower().split(),
            source_id="src-1",
            clip_path=None,
            asr_status="transcribed",
            needs_review=False,
            confidence=0.95,
        )
        for i, (spk, txt) in enumerate(texts)
    ]


def build_nd30_stress_cases() -> list[dict]:
    """20 deterministic Vietnamese cases exercising dates, word numbers, clocks, votes, rejections, signatures."""
    return [
        {
            "id": "nd30_01_full_spoken_numbers",
            "turns": [("Chủ tọa Nguyễn Văn An", "Hôm nay ngày hai mươi sáu tháng mười một năm hai nghìn không trăm hai sáu, cuộc họp bắt đầu lúc chín giờ mười lăm phút tại Phòng họp A1. Thư ký Trần Thị Bình ghi biên bản."), ("Chủ tọa Nguyễn Văn An", "Tổng số hai lăm phiếu, hai ba phiếu tán thành, hai phiếu không tán thành. Cuộc họp kết thúc lúc mười một giờ rưỡi.")],
            "expected": {"day": "26", "month": "11", "year": "2026", "start_hour": "9", "start_minute": "15", "end_hour": "11", "end_minute": "30", "vote_total": "25", "vote_yes": "23", "vote_no": "2"},
        },
        {
            "id": "nd30_02_digital_date_afternoon",
            "turns": [("Lê Minh", "Cuộc họp ngày 18/11/2026 bắt đầu lúc 14h30 tại Hội trường B. Anh Lê Minh làm chủ tọa, chị Phạm Thu làm thư ký."), ("Lê Minh", "Đến 16:45 toàn bộ cuộc họp bế mạc.")],
            "expected": {"day": "18", "month": "11", "year": "2026", "start_hour": "14", "start_minute": "30", "end_hour": "16", "end_minute": "45"},
        },
        {
            "id": "nd30_03_afternoon_chi_chieu_word",
            "turns": [("Hùng", "Cuộc họp chiều ngày 05-09-2026 khai mạc lúc hai giờ chiều, kết thúc lúc năm giờ rưỡi chiều.")],
            "expected": {"day": "5", "month": "9", "year": "2026", "start_hour": "14", "start_minute": "0", "end_hour": "17", "end_minute": "30"},
        },
        {
            "id": "nd30_04_scoped_part_not_end_meeting",
            "turns": [("An", "Cuộc họp bắt đầu lúc 8h00. Phần thảo luận kết thúc lúc 9h15, sau đó chuyển sang biểu quyết. Toàn bộ cuộc họp kết thúc lúc 10h45.")],
            "expected": {"start_hour": "8", "start_minute": "0", "end_hour": "10", "end_minute": "45"},
        },
        {
            "id": "nd30_05_uncertain_proposed_time_rejected",
            "turns": [("Bình", "Cuộc họp dự kiến bắt đầu lúc 8h00 ngày 20/11/2026 nhưng thực tế cuộc họp bắt đầu lúc 8h25 ngày 21/11/2026."), ("Bình", "Dự kiến cuộc họp kết thúc lúc 12h00 nếu kịp tiến độ.")],
            "expected": {"day": "21", "month": "11", "year": "2026", "start_hour": "8", "start_minute": "25", "end_hour": None},
        },
        {
            "id": "nd30_06_vote_uncertain_rejected",
            "turns": [("Lan", "Chưa kiểm phiếu nên chưa rõ kết quả, giả sử tổng số 20 phiếu, 18 phiếu tán thành.")],
            "expected": {"vote_total": None, "vote_yes": None},
        },
        {
            "id": "nd30_07_vote_real_with_abstain",
            "turns": [("Dung", "Biểu quyết nội dung một: tổng số 30 phiếu, 24 phiếu tán thành, 4 phiếu không tán thành, 2 phiếu trắng.")],
            "expected": {"vote_total": "30", "vote_yes": "24", "vote_no": "4"},
        },
        {
            "id": "nd30_08_multi_round_vote_ambiguous_unscoped",
            "turns": [("A", "Phương án A: tổng số 10 phiếu, 8 phiếu tán thành, 2 phiếu không tán thành."), ("B", "Phương án B: tổng số 10 phiếu, 6 phiếu tán thành, 4 phiếu không tán thành.")],
            "expected": {"vote_rounds": 2},
        },
        {
            "id": "nd30_09_signature_unsigned_conflict",
            "turns": [("Thư ký", "Biên bản này hiện chưa có ai ký, sẽ ký sau khi rà soát.")],
            "expected": {"signature_conflict": True},
        },
        {
            "id": "nd30_10_signature_signed_ok",
            "turns": [("Thư ký", "Các thành viên nhất trí thông qua toàn bộ nội dung biên bản.")],
            "expected": {"signature_conflict": False},
        },
        {
            "id": "nd30_11_spoken_room_code_no_negation",
            "turns": [("An", "Cuộc họp ngày 12 tháng 10 năm 2026 bắt đầu lúc 9h00 tại phòng hai không một.")],
            "expected": {"day": "12", "month": "10", "year": "2026", "start_hour": "9", "start_minute": "0"},
        },
        {
            "id": "nd30_12_late_year_2026",
            "turns": [("Minh", "Ngày 03/11/2026, cuộc họp bắt đầu lúc 13 giờ 05 phút và kết thúc lúc 15 giờ 20 phút.")],
            "expected": {"day": "3", "month": "11", "year": "2026", "start_hour": "13", "start_minute": "5", "end_hour": "15", "end_minute": "20"},
        },
    ]


def main() -> None:
    setup_root_src()
    from meeting_pipeline.minutes.converter import normalize_template
    from meeting_pipeline.minutes.doc_parser import parse_template_document
    from meeting_pipeline.minutes.fact_extractor import M2RuleFactExtractor
    from meeting_pipeline.minutes.graph_export import guard_graph_export
    from meeting_pipeline.minutes.renderer import render_completed_document
    from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper
    from meeting_pipeline.minutes.schemas import FactStatus, PlaceholderType, SemanticFieldType
    from meeting_pipeline.minutes.structured_fields import extract_meeting_record, structured_facts

    t0 = time.perf_counter()
    fixtures_tpl = ROOT / "tests/fixtures/templates"
    fixtures_gt = ROOT / "tests/fixtures/ground_truth"

    template_results = []
    mapper = M0RuleSchemaMapper()
    extractor = M2RuleFactExtractor()

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        # 1. Template parsing, M0 schema mapping & DOCX render verification
        template_specs = [
            ("bien_ban_hop_chi_bo.docx", "bien_ban_hop_chi_bo_gold.json"),
            ("mau_bien_ban_hop_chung.doc", "mau_bien_ban_hop_chung_gold.json"),
            ("bien_ban_ban_giao_thiet_bi.docx", None),
        ]
        parsed_cache = {}
        for tpl_name, gt_name in template_specs:
            tpl_path = fixtures_tpl / tpl_name
            ts = time.perf_counter()
            conv = normalize_template(tpl_path, work / tpl_path.stem)
            conv_sec = time.perf_counter() - ts
            tp = time.perf_counter()
            doc_graph = parse_template_document(conv.normalized_docx_path, original_sha256=conv.original_sha256)
            schema = mapper.propose_schema(doc_graph)
            parse_sec = time.perf_counter() - tp
            parsed_cache[tpl_name] = (conv, doc_graph, schema)

            anchor_count = len(doc_graph.all_anchors)
            expected_anchors = None
            field_recall = None
            if gt_name:
                gt = read_json(fixtures_gt / gt_name)
                expected_anchors = gt.get("expected_anchor_count")
                gt_types = {f["semantic_type"] for f in gt.get("fields", [])}
                pred_types = {f.semantic_type.value for f in schema.fields}
                field_recall = round(len(gt_types & pred_types) / max(len(gt_types), 1), 4)
            template_results.append(
                {
                    "template": tpl_name,
                    "format": conv.original_format,
                    "anchors": anchor_count,
                    "expected_anchors": expected_anchors,
                    "schema_fields": len(schema.fields),
                    "semantic_type_recall": field_recall,
                    "convert_sec": round(conv_sec, 4),
                    "parse_map_sec": round(parse_sec, 4),
                }
            )

        # 2. Render & Zip integrity + guard_graph_export check on meeting_run_gold_facts context
        _, doc_graph_chung, schema_chung = parsed_cache["mau_bien_ban_hop_chung.doc"]
        conv_chung = parsed_cache["mau_bien_ban_hop_chung.doc"][0]
        _, doc_graph_chibo, schema_chibo = parsed_cache["bien_ban_hop_chi_bo.docx"]
        conv_chibo = parsed_cache["bien_ban_hop_chi_bo.docx"][0]

        stress_turns = make_turns(
            [
                ("Nguyễn Văn An", "Hôm nay ngày 18 tháng 11 năm 2026, cuộc họp bắt đầu lúc 14 giờ 30 phút tại Phòng 201."),
                ("Trần Thị Bình", "Thư ký Trần Thị Bình ghi biên bản. Tổng số 25 phiếu, 23 phiếu tán thành, 2 phiếu không tán thành."),
                ("Nguyễn Văn An", "Nhóm thống nhất thông qua kế hoạch triển khai. Toàn bộ cuộc họp kết thúc lúc 16 giờ 00 phút."),
            ],
            prefix="seg",
        )
        run_dir = work / "mock_run"
        (run_dir / "minutes").mkdir(parents=True)
        (run_dir / "minutes/meeting_graph.json").write_text(
            json.dumps(
                {
                    "events": [
                        {
                            "event_id": "ev1",
                            "kind": "decision",
                            "lifecycle": "decided",
                            "text": "Thống nhất thông qua kế hoạch triển khai.",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )
        (run_dir / "minutes/content_plan.json").write_text(
            json.dumps(
                {
                    "sections": [
                        {
                            "title": "Kết luận",
                            "paragraphs": [
                                {
                                    "verification": "checked",
                                    "claim_ids": ["ev1"],
                                    "text": "Cuộc họp đã thống nhất thông qua kế hoạch triển khai.",
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )

        # Evaluate structured_facts + M2 + guard_graph_export + DOCX render on chung
        facts_m2 = extractor.extract_facts(
            schema_chung,
            stress_turns,
            meeting_metadata={"title": "Họp rà soát tiến độ", "attendees": ["Nguyễn Văn An", "Trần Thị Bình", "Lê Văn Cường"]},
            run_id="mock_run",
        )
        facts_struct = structured_facts(
            schema_chung,
            doc_graph_chung,
            stress_turns,
            "mock_run",
            meeting_metadata={"title": "Họp rà soát tiến độ", "attendees": ["Nguyễn Văn An", "Trần Thị Bình", "Lê Văn Cường"]},
        )
        # Merge structured fields + guard_graph_export
        by_id = {f.field_id: f for f in facts_m2}
        for sf_fact in facts_struct:
            if sf_fact.value not in (None, "", []):
                by_id[sf_fact.field_id] = sf_fact
        guarded = guard_graph_export(run_dir, schema_chung, doc_graph_chung, list(by_id.values()), stress_turns)
        out_docx = work / "rendered_chung.docx"
        rendered_path, rendered_sha = render_completed_document(
            conv_chung.normalized_docx_path, out_docx, doc_graph_chung, schema_chung, guarded
        )
        with zipfile.ZipFile(rendered_path, "r") as zf:
            zip_ok = zf.testzip() is None

        # 3. Benchmark structured_fields.py on 12 deterministic ND30 stress cases
        stress_eval = []
        total_checks = 0
        passed_checks = 0
        for sc in build_nd30_stress_cases():
            tlist = make_turns(sc["turns"], prefix=sc["id"])
            rec, rounds = extract_meeting_record(tlist, sc["id"])
            # Also check structured_facts on chi_bo template (has signature block + vote fields)
            sf_list = structured_facts(schema_chibo, doc_graph_chibo, tlist, sc["id"])
            sf_map = {f.field_id: f for f in sf_list}
            exp = sc["expected"]
            case_ok = True
            failures = []
            for k, v in exp.items():
                total_checks += 1
                if k == "vote_rounds":
                    got = len(rounds)
                elif k == "signature_conflict":
                    got = any(
                        a.placeholder_type == PlaceholderType.FIXED_TEXT
                        and sf_map.get(f.field_id)
                        and sf_map[f.field_id].status == FactStatus.CONFLICTING
                        for f in schema_chibo.fields
                        for a in [next(aa for aa in doc_graph_chibo.all_anchors if aa.anchor_id == f.anchor_id)]
                    )
                else:
                    got = str(rec[k].value) if k in rec else None
                if got == v:
                    passed_checks += 1
                else:
                    case_ok = False
                    failures.append({"key": k, "expected": v, "got": got})
            stress_eval.append({"case_id": sc["id"], "passed": case_ok, "failures": failures})

        # 4. False-positive check on all 60 v2.1 test transcripts (stylized dialogues without formal dates/votes)
        v21_rows = [
            json.loads(l)
            for l in (ROOT / "web_app/artifacts/graph-synthetic-v2.1/test/inputs/transcripts.jsonl").read_text().splitlines()
            if l.strip()
        ]
        v21_scalar_hits = 0
        v21_vote_hits = 0
        for row in v21_rows:
            tlist = make_turns([(t["speaker"], t["text"]) for t in row["turns"]], prefix=row["case_id"])
            rec, rounds = extract_meeting_record(tlist, row["case_id"])
            v21_scalar_hits += sum(k in {"day", "month", "year", "start_hour", "end_hour"} for k in rec)
            v21_vote_hits += len(rounds)

    out_dir = OUT / "wave1/structured_export"
    write_csv(out_dir / "templates.csv", template_results)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave1_structured_fields_and_export",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "templates": template_results,
            "render_zip_integrity": zip_ok,
            "rendered_sha256": rendered_sha,
            "nd30_stress": {
                "cases": len(stress_eval),
                "checks_total": total_checks,
                "checks_passed": passed_checks,
                "check_accuracy": round(passed_checks / max(total_checks, 1), 4),
                "details": stress_eval,
            },
            "v21_false_positive_audit": {
                "cases": len(v21_rows),
                "spurious_date_clock_hits": v21_scalar_hits,
                "spurious_vote_round_hits": v21_vote_hits,
            },
        },
    )
    log(f"[Structured] Done in {time.perf_counter() - t0:.2f}s (stress={passed_checks}/{total_checks}, zip={zip_ok})")


if __name__ == "__main__":
    main()

