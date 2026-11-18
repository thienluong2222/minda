"""Read-only visual QA of an authorised local meeting using its owner's scoped API.

All non-GET browser requests are blocked. No session credentials are exported.
"""

import argparse
from pathlib import Path

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from meeting_backend.api.dependencies import current_user
from meeting_backend.core.settings import Settings
from meeting_backend.infrastructure.mongodb.client import Mongo
from meeting_backend.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meeting-id", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:5180")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    mongo = Mongo(settings)
    try:
        meeting = mongo.db.meetings.find_one({"_id": args.meeting_id})
        if not meeting:
            raise SystemExit("Meeting not found")
        user = mongo.db.users.find_one({"_id": meeting["owner_id"], "active": True})
        if not user:
            raise SystemExit("Meeting owner not active")
    finally:
        mongo.client.close()
    app = create_app(settings)
    app.dependency_overrides[current_user] = lambda: user
    errors = []
    with TestClient(app) as client, sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            headless=True,
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        page.on("pageerror", lambda error: errors.append(str(error)))

        def forward(route):
            if route.request.method != "GET":
                route.fulfill(
                    status=403, json={"error": {"code": "QA_READ_ONLY", "message": "Read-only QA"}}
                )
                return
            path = route.request.url.split("/api/v1", 1)[1]
            response = client.get("/api/v1" + path)
            route.fulfill(
                status=response.status_code,
                body=response.content,
                content_type=response.headers.get("content-type", "application/json"),
            )

        page.route("**/api/v1/**", forward)
        page.goto(args.url + f"/meetings/{args.meeting_id}?tab=graph")
        expect(page.get_by_role("img", name="Đồ thị gồm", exact=False)).to_be_visible()
        outline = page.get_by_role("region", name="Dàn ý biên bản")
        expect(outline.locator(".minutes-outline-section").first).to_be_visible()
        page.screenshot(path=str(args.output / "overview.png"), full_page=True)
        outline.locator(".minutes-outline-section summary").first.click()
        outline.screenshot(path=str(args.output / "outline.png"))
        row = page.locator(".meeting-graph-node-row").first
        row.click()
        page.get_by_role("button", name="Mở liên kết của nút").click()
        expect(page.locator(".meeting-graph-stage-footer")).not_to_contain_text("0 nút")
        page.locator(".meeting-graph-shell").screenshot(path=str(args.output / "graph.png"))
        assert not errors, errors
        browser.close()
    print("Read-only graph, outline and viewport capture passed.")


if __name__ == "__main__":
    main()
