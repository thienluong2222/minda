"""Read-only browser smoke. Credentials are read locally and excluded from reports."""

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def check_document_preview(page):
    """Require actual decoded images on every page, not just an error-free route."""
    page.locator("img.document-page").wait_for(state="visible")
    seen = set()
    while True:
        page.wait_for_function(
            """() => {
                const image = document.querySelector('img.document-page');
                return image && image.complete && image.naturalWidth > 0;
            }"""
        )
        source = page.locator("img.document-page").get_attribute("src")
        assert source and source not in seen, "Preview did not advance to a new page"
        seen.add(source)
        next_page = page.get_by_role("button", name="Trang sau", exact=True)
        if next_page.is_disabled():
            break
        next_page.click()
        page.wait_for_function(
            "source => document.querySelector('img.document-page')?.getAttribute('src') !== source",
            arg=source,
        )
    return len(seen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--username")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--meeting-id")
    parser.add_argument("--template-id")
    parser.add_argument("--output", type=Path, default=Path("data/evaluations/web_browser_smoke"))
    parser.add_argument(
        "--browser-path", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    args = parser.parse_args()
    credentials = (
        json.loads(args.credentials_file.read_text())
        if args.credentials_file
        else {"username": args.username, "password": os.environ.get("MEETING_QA_PASSWORD")}
    )
    if not credentials.get("username") or not credentials.get("password"):
        parser.error("Cần --username + MEETING_QA_PASSWORD hoặc --credentials-file JSON.")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "pages": [],
        "document_previews": [],
        "console_errors": [],
        "mobile_overflow": False,
        "ok": False,
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.browser_path, headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: report["console_errors"].append(str(error)))
        try:
            page.goto(args.url)
            page.get_by_label("Tên đăng nhập").fill(credentials["username"])
            page.get_by_label("Mật khẩu", exact=True).fill(credentials["password"])
            page.get_by_role("button", name="Đăng nhập", exact=True).click()
            page.get_by_role("heading", name="Cuộc họp gần đây").wait_for()
            user = context.request.get(args.url + "/api/v1/auth/me").json()
            routes = [
                ("/", "Cuộc họp gần đây"),
                ("/meetings", "Cuộc họp của bạn"),
                ("/templates", "Thư viện mẫu biên bản"),
                ("/voices", "Hồ sơ giọng nói"),
                ("/settings", "Thiết lập cá nhân"),
            ]
            if args.meeting_id:
                routes.append(
                    ("/meetings/" + args.meeting_id + "?tab=minutes", "Nội dung & dữ liệu")
                )
            if args.template_id:
                response = context.request.get(args.url + "/api/v1/templates/" + args.template_id)
                assert response.ok, "Cannot access the selected template"
                routes.append(("/templates/" + args.template_id, response.json()["name"]))
            if user["role"] == "admin":
                routes.extend(
                    [
                        ("/admin", "Tổng quan hệ thống"),
                        ("/admin/users", "Tài khoản hệ thống"),
                        ("/admin/jobs", "Tác vụ xử lý"),
                        ("/admin/models", "Mô hình & công cụ"),
                        ("/admin/backups", "Sao lưu & khôi phục"),
                        ("/admin/experiments", "Kiểm tra & đánh giá"),
                        ("/admin/audit", "Nhật ký hệ thống"),
                    ]
                )
            for index, (route, heading) in enumerate(routes):
                page.goto(args.url + route)
                page.get_by_role("heading", name=heading, exact=True).wait_for()
                if "?tab=minutes" in route or route.startswith("/templates/"):
                    report["document_previews"].append(
                        {"route": route, "pages": check_document_preview(page)}
                    )
                page.wait_for_timeout(600)
                filename = f"{index:02d}-desktop.png"
                page.screenshot(path=str(args.output / filename), full_page=True)
                report["pages"].append({"route": route, "screenshot": filename})
            page.goto(args.url)
            page.get_by_role("heading", name="Cuộc họp gần đây").wait_for()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
            report["mobile_overflow"] = page.evaluate(
                "document.documentElement.scrollWidth>window.innerWidth"
            )
            page.get_by_role("button", name="Mở menu", exact=True).click()
            page.screenshot(path=str(args.output / "mobile-menu.png"), full_page=True)
            assert not report["console_errors"], report["console_errors"]
            assert not report["mobile_overflow"], "Mobile has horizontal overflow"
            report["ok"] = True
        finally:
            browser.close()
            (args.output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
    print(json.dumps({"ok": report["ok"], "pages": len(report["pages"])}))


if __name__ == "__main__":
    main()
