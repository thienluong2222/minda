"""Exercise the real UI and API against a disposable, synthetic meeting database.

Start Vite, then run with PYTHONPATH=src. No worker or model inference is started.
"""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from meeting_backend.core.settings import Settings
from meeting_backend.main import create_app
from meeting_backend.modules.minutes.graph_store import persist_graph
from meeting_backend.modules.minutes.outline_store import persist_outline
from meeting_pipeline.minutes.graph_builder import build_graph
from meeting_pipeline.minutes.graph_contracts import Event, GraphUnit, SourceSpan
from meeting_pipeline.minutes.graph_writer import plan_sections


def seed(client):
    password = "isolated-graph-smoke-12345"
    client.post(
        "/api/v1/auth/setup",
        json={
            "username": "graphadmin",
            "password": password,
            "display_name": "Kiểm thử đồ thị",
        },
    ).raise_for_status()
    client.post(
        "/api/v1/auth/login",
        json={
            "username": "graphadmin",
            "password": password,
        },
    ).raise_for_status()
    client.headers["X-CSRF-Token"] = client.cookies.get("meeting_csrf")
    meeting = client.post(
        "/api/v1/meetings",
        json={
            "title": "Họp kế hoạch nghiên cứu · Dữ liệu kiểm thử",
            "location": "Phòng họp A",
        },
    ).json()
    mongo = client.app.state.mongo
    raw = mongo.db.meetings.find_one({"_id": meeting["id"]})
    titles = [
        "Tiến độ nghiên cứu",
        "Phương pháp thực nghiệm",
        "Phân công báo cáo",
        "Dữ liệu đánh giá",
        "Kế hoạch công bố",
        "Rà soát tài liệu",
        "Chất lượng biên bản",
        "Ngân sách thực hiện",
        "Mốc nghiệm thu",
        "Đào tạo nhóm",
        "Phản biện kết quả",
        "Thảo luận mở",
    ]
    units, events = [], []
    for i in range(1200):
        text = f"Minh đề nghị hoàn tất báo cáo số {i + 1} trước ngày 15/11 và giao Lan rà soát."
        units.append(
            GraphUnit(
                unit_id=f"u{i}",
                turn_id=f"t{i}",
                speaker="Nguyễn Minh",
                start_sec=i * 5,
                end_sec=i * 5 + 4,
                original=text,
                text=text,
                sources=[
                    SourceSpan(
                        turn_id=f"t{i}",
                        start_char=0,
                        end_char=len(text),
                        text=text,
                        start_sec=i * 5,
                        end_sec=i * 5 + 4,
                    )
                ],
            )
        )
        events.append(
            Event(
                event_id=f"e{i}",
                unit_ids=[f"u{i}"],
                kind="task" if i % 2 == 0 else "proposal",
                text=text,
                owner="Lan",
                deadline="15/11",
                verification="needs_review",
                extraction="source_fallback" if i % 7 == 0 else "model",
            )
        )
    graph = build_graph(
        raw["_id"],
        units,
        events,
        {
            "cluster_count": len(titles),
            "primary": [i % len(titles) for i in range(len(units))],
            "membership": [
                [float(k == i % len(titles)) for k in range(len(titles))] for i in range(len(units))
            ],
            "titles": titles,
        },
        [],
        metadata={"meeting_name": meeting["title"]},
    )
    persist_graph(mongo, raw, graph.model_dump())
    sections, ledger = plan_sections(graph)
    outline = persist_outline(
        mongo,
        raw,
        "graph-version",
        {
            "schema_version": "2.0",
            "sections": [section.model_dump() for section in sections],
            "ledger": ledger,
        },
    )
    common = {
        "meeting_id": meeting["id"],
        "owner_id": raw["owner_id"],
        "facts": [],
        "schema": {"fields": []},
        "topics": {},
        "options": {},
        "reason": "ui-test",
        "report": {},
        "corrections": [],
        "input_content_revision": 0,
    }
    mongo.db.minutes_versions.insert_many(
        [
            {
                **common,
                "_id": "graph-version",
                "graph_id": graph.graph_id,
                "outline": outline,
                "created_at": "2026-11-09T08:00:00+00:00",
            },
            {**common, "_id": "legacy-version", "created_at": "2026-11-08T08:00:00+00:00"},
        ]
    )
    mongo.db.meetings.update_one(
        {"_id": raw["_id"]},
        {
            "$set": {
                "active_minutes_id": "graph-version",
                "state": "minutes_ready",
            }
        },
    )
    return meeting["id"], graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5180")
    parser.add_argument(
        "--browser-path", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/meeting-graph-ui"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="meeting-graph-ui-") as data_dir:
        settings = Settings(
            mongo_database="meeting_app_graph_ui_" + uuid4().hex,
            data_dir=Path(data_dir),
            web_dist=Path(data_dir) / "no-web",
        )
        app = create_app(settings)
        checks, errors = [], []
        with TestClient(app) as client:
            try:
                meeting_id, graph = seed(client)
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=args.browser_path, headless=True)
                    page = browser.new_page(
                        viewport={"width": 1600, "height": 1100}, device_scale_factor=1
                    )
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def forward(route):
                        request = route.request
                        path = request.url.split("/api/v1", 1)[1]
                        response = client.request(
                            request.method,
                            "/api/v1" + path,
                            content=request.post_data,
                            headers={
                                "Content-Type": request.headers.get(
                                    "content-type", "application/json"
                                )
                            },
                        )
                        route.fulfill(
                            status=response.status_code,
                            body=response.content,
                            content_type=response.headers.get("content-type", "application/json"),
                        )

                    page.route("**/api/v1/**", forward)
                    url = args.url + f"/meetings/{meeting_id}?tab=graph"
                    page.goto(url)
                    expect(
                        page.get_by_role("heading", name="Đồ thị cuộc họp", exact=True)
                    ).to_be_visible()
                    canvas = page.get_by_role("img", name="Đồ thị gồm", exact=False)
                    expect(canvas).to_be_visible()
                    expect(page.locator(".meeting-graph-node-row")).to_have_count(12)
                    outline_panel = page.get_by_role("region", name="Dàn ý biên bản")
                    expect(outline_panel).to_be_visible()
                    expect(outline_panel.locator(".minutes-outline-section")).to_have_count(6)
                    outline_panel.locator(".minutes-outline-section summary").first.click()
                    expect(
                        outline_panel.get_by_role("button", name="Xem căn cứ").first
                    ).to_be_visible()
                    outline_panel.get_by_role("button", name="Xem căn cứ").first.click()
                    expect(page.locator(".meeting-graph-inspector")).to_contain_text("báo cáo số 1")
                    page.get_by_role("button", name="Tổng quan", exact=True).click()
                    outline_panel.locator(".minutes-outline-section summary").first.click()
                    checks.append("versioned outline expands and opens exact graph evidence")
                    page.screenshot(path=str(args.output / "overview.png"), full_page=True)
                    checks.append("overview renders a bounded real API view")

                    topic = page.locator(".meeting-graph-node-row").filter(
                        has_text="Tiến độ nghiên cứu"
                    )
                    topic.click()
                    page.get_by_role("button", name="Mở liên kết của nút").click()
                    expect(page).to_have_url(__import__("re").compile("graph_node=topic%3A0"))
                    expect(page.locator(".meeting-graph-stage-footer")).to_contain_text("9 nút")
                    page.locator(".meeting-graph-shell").screenshot(
                        path=str(args.output / "topic.png")
                    )
                    page.locator(".meeting-graph-stage-footer").get_by_role(
                        "button", name="Trang đồ thị sau"
                    ).click()
                    expect(
                        page.locator(".meeting-graph-stage-footer .meeting-graph-pager")
                    ).to_contain_text("2 / 13")
                    page.get_by_role("combobox", name="Bố cục đồ thị").select_option("breadthfirst")
                    page.get_by_role("button", name="Phóng to đồ thị").click()
                    page.get_by_role("button", name="Đưa đồ thị vừa khung").click()
                    page.get_by_role("combobox", name="Mức chi tiết đồ thị").select_option(
                        "technical"
                    )
                    expect(
                        page.locator(".meeting-graph-node-row")
                        .filter(has_text="Lời chép gốc")
                        .first
                    ).to_be_visible()
                    page.get_by_role("combobox", name="Mức chi tiết đồ thị").select_option(
                        "content"
                    )
                    checks.append(
                        "topic drill-down, pagination, alternate layout and viewport controls"
                    )

                    search = page.get_by_role("textbox", name="Tìm nội dung trong đồ thị")
                    search.fill("báo cáo số 1 trước")
                    page.get_by_role("combobox", name="Lọc loại nút").select_option("task")
                    expect(page.locator(".meeting-graph-node-row")).to_have_count(1)
                    page.locator(".meeting-graph-node-row").click()
                    expect(page.locator(".meeting-graph-inspector")).to_contain_text(
                        "Cần đối chiếu lại"
                    )
                    expect(page.locator(".meeting-graph-inspector")).to_contain_text(
                        "Nội dung giữ từ lời chép gốc"
                    )
                    expect(page.locator(".meeting-graph-properties")).to_contain_text("Lan")
                    expect(page.locator(".meeting-graph-evidence-card")).to_have_count(1)
                    page.locator(".meeting-graph-evidence-card").click()
                    expect(page.locator(".meeting-graph-source")).to_contain_text("báo cáo số 1")
                    page.screenshot(path=str(args.output / "evidence.png"), full_page=True)
                    checks.append(
                        "global search, kind filter, task warning and exact transcript evidence"
                    )

                    page.get_by_role("combobox", name="Phiên bản biên bản").select_option(
                        "legacy-version"
                    )
                    expect(
                        page.get_by_text("Phiên bản này chưa có đồ thị", exact=True)
                    ).to_be_visible()
                    page.get_by_role("combobox", name="Phiên bản biên bản").select_option(
                        "graph-version"
                    )
                    expect(canvas).to_be_visible()
                    checks.append("legacy version empty state and return to current version")

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "Mobile horizontal overflow"
                    )
                    checks.append("390px mobile layout without horizontal overflow")

                    page.set_viewport_size({"width": 1440, "height": 1000})
                    page.goto(args.url + "/admin/models")
                    switch = page.get_by_role("switch", name="Tạo biên bản bằng đồ thị cuộc họp")
                    expect(switch).to_be_checked()
                    switch.uncheck()
                    page.get_by_role("button", name="Lưu cấu hình · revision").click()
                    expect(
                        page.get_by_role("button", name="Lưu cấu hình · revision 2")
                    ).to_be_visible()
                    expect(switch).not_to_be_checked()
                    assert (
                        client.get("/api/v1/admin/preset").json()["minutes_graph_enabled"] is False
                    )
                    switch.check()
                    page.get_by_role("button", name="Lưu cấu hình · revision").click()
                    expect(
                        page.get_by_role("button", name="Lưu cấu hình · revision 3")
                    ).to_be_visible()
                    assert (
                        client.get("/api/v1/admin/preset").json()["minutes_graph_enabled"] is True
                    )
                    page.screenshot(path=str(args.output / "admin.png"), full_page=True)
                    checks.append("admin switches persist through the real settings API")
                    assert not errors, errors
                    browser.close()
                result = {
                    "checks": checks,
                    "browser_errors": errors,
                    "synthetic_graph_nodes": len(graph.nodes),
                    "synthetic_graph_edges": len(graph.edges),
                }
                (args.output / "result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2)
                )
                print(json.dumps(result, ensure_ascii=False))
            finally:
                app.state.mongo.client.drop_database(settings.mongo_database)


if __name__ == "__main__":
    main()
