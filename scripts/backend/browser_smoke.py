"""Read-only browser smoke. Credentials are read locally and excluded from reports."""

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


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


def check_motion(page, args):
    """Exercise motion without saving forms or changing application data."""
    checks = []
    page.emulate_media(reduced_motion="no-preference")
    page.goto(args.url + "/meetings/new")
    title = page.get_by_placeholder("Ví dụ: Họp triển khai kế hoạch tháng 10")
    title.fill("Kiểm tra chuyển động Minda")
    page.wait_for_timeout(300)
    title.focus()
    title.evaluate("node => node.setSelectionRange(5, 5)")
    page.evaluate("""() => {
        window.__motionRoute = document.querySelector('.route-motion');
        window.__motionInput = document.activeElement;
        window.__motionStarts = [];
        document.addEventListener('animationstart', event => {
            if (event.target.matches('.route-motion, .wizard-step-motion'))
                window.__motionStarts.push(event.animationName);
        });
    }""")
    page.wait_for_timeout(5500)
    expect(title).to_have_value("Kiểm tra chuyển động Minda")
    assert page.evaluate("""() =>
        window.__motionRoute === document.querySelector('.route-motion') &&
        window.__motionInput === document.activeElement &&
        document.activeElement.selectionStart === 5 && window.__motionStarts.length === 0
    """), "Polling replayed page motion or replaced the focused input"
    checks.append("polling preserves input, caret and page animation state")
    page.get_by_role("button", name="Tiếp tục", exact=True).click()
    heading = page.get_by_role("heading", name="Nguồn âm thanh", exact=True)
    expect(heading).to_be_focused()
    step = page.locator(".wizard-step-motion")
    expect(step).to_have_attribute("data-direction", "forward")
    assert step.evaluate("node => getComputedStyle(node).animationName") == "minda-step"
    assert (
        page.locator(".wizard-steps .confirmation-check path").first.evaluate(
            "node => getComputedStyle(node).animationName"
        )
        == "minda-check"
    )
    page.get_by_role("button", name="Quay lại", exact=True).click()
    expect(step).to_have_attribute("data-direction", "backward")
    expect(title).to_have_value("Kiểm tra chuyển động Minda")
    checks.append("wizard direction, keyboard focus and completion check")
    brand_el = page.locator(".minda-brand, .brand").first
    brand_el.hover()
    if page.locator(".brand-symbol path").count() > 0:
        path = page.locator(".brand-symbol path").first
        assert path.evaluate("node => getComputedStyle(node).animationIterationCount") == "1"
        page.wait_for_timeout(650)
        assert path.evaluate("node => node.getAnimations().length") == 0
    checks.append("brand wave runs once on hover")

    if args.meeting_id:
        route = args.url + "/meetings/" + args.meeting_id + "?tab=minutes"
        page.goto(route)
        preview_btn = page.get_by_role("button", name="Xem trước Word")
        if preview_btn.count() > 0:
            preview_btn.click()
        image = page.locator("img.document-page.is-ready")
        expect(image).to_be_visible()
        page.wait_for_timeout(250)
        assert image.evaluate("node => getComputedStyle(node).opacity") == "1"
        metadata = page.request.get(
            args.url + "/api/v1/meetings/" + args.meeting_id + "/minutes"
        ).json()["version"]
        pages = metadata["previews"]
        if len(pages) > 1:
            held = []
            pattern = "**/api/v1/artifacts/" + pages[1]["id"] + "*"
            page.route(pattern, lambda request: held.append(request))
            frame = page.locator(".document-page-frame")
            before = frame.bounding_box()
            page.get_by_role("button", name="Trang sau", exact=True).click()
            expect(frame).to_have_attribute("aria-busy", "true")
            expect(page.get_by_text("Đang tải trang 2…", exact=True)).to_be_visible()
            during = frame.bounding_box()
            assert abs(before["height"] - during["height"]) < 1
            page.wait_for_timeout(100)
            assert held, "Next-page image request was not intercepted"
            held[0].continue_()
            page.unroute(pattern)
            expect(image).to_be_visible()
            assert image.evaluate("node => getComputedStyle(node).animationName") == "minda-fade-in"
            failed_pattern = "**/api/v1/artifacts/" + pages[0]["id"] + "*"
            page.route(failed_pattern, lambda request: request.fulfill(status=404, body="test"))
            page.get_by_role("button", name="Trang trước", exact=True).click()
            expect(page.get_by_text("Không tải được trang xem trước.", exact=True)).to_be_visible()
            page.unroute(failed_pattern)
            page.get_by_role("button", name="Thử tải lại", exact=True).click()
            expect(image).to_be_visible()
            checks.append("preview reserves space, fades after load and retries image errors")
        trigger = page.get_by_role("button", name="Tạo lại biên bản", exact=True)
        trigger.click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        assert dialog.evaluate("node => getComputedStyle(node).animationName") == "minda-dialog-in"
        page.keyboard.press("Tab")
        assert dialog.evaluate("node => node.contains(document.activeElement)")
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        expect(trigger).to_be_focused()
        checks.append("Radix modal motion, focus trap and return focus")
        page.emulate_media(reduced_motion="reduce")
        trigger.click()
        expect(dialog).to_be_visible()
        assert dialog.evaluate("node => getComputedStyle(node).animationName") == "none"
        assert dialog.evaluate("node => getComputedStyle(node).opacity") == "1"
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        page.reload()
        preview_btn = page.get_by_role("button", name="Xem trước Word")
        if preview_btn.count() > 0:
            preview_btn.click()
        expect(image).to_be_visible()
        assert image.evaluate("node => getComputedStyle(node).animationName") == "none"
        assert image.evaluate("node => getComputedStyle(node).opacity") == "1"

    page.emulate_media(reduced_motion="reduce")
    page.goto(args.url + "/meetings/new")
    title = page.get_by_placeholder("Ví dụ: Họp triển khai kế hoạch tháng 10")
    title.fill("Kiểm tra giảm chuyển động")
    page.get_by_role("button", name="Tiếp tục", exact=True).click()
    assert (
        page.locator(".route-motion").evaluate("node => getComputedStyle(node).animationName")
        == "none"
    )
    assert (
        page.locator(".wizard-step-motion").evaluate("node => getComputedStyle(node).animationName")
        == "none"
    )
    assert (
        page.locator(".wizard-step-motion").evaluate("node => getComputedStyle(node).opacity")
        == "1"
    )
    checks.append("reduced motion leaves pages, wizard, modal and preview visible")
    page.emulate_media(reduced_motion="no-preference")
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--username")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--meeting-id")
    parser.add_argument("--template-id")
    parser.add_argument("--check-motion", action="store_true")
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
        "admin_lists": [],
        "motion_checks": [],
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
                    ("/meetings/" + args.meeting_id + "?tab=minutes", "Nội dung biên bản")
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
                        ("/admin/meetings", "Cuộc họp toàn hệ thống"),
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
                if route in {"/admin/users", "/admin/meetings"}:
                    response = context.request.get(args.url + "/api/v1" + route)
                    assert response.ok, "Cannot load the selected admin list"
                    payload = response.json()
                    records = payload if isinstance(payload, list) else payload["items"]
                    rows = page.locator("table tbody tr")
                    expect(rows).to_have_count(len(records))
                    for record in records:
                        value = (
                            "@" + record["username"] if route.endswith("users") else record["title"]
                        )
                        expect(
                            page.locator("table tbody").get_by_text(value, exact=False).first
                        ).to_be_visible()
                    report["admin_lists"].append({"route": route, "records": len(records)})
                if "?tab=minutes" in route or route.startswith("/templates/"):
                    if "?tab=minutes" in route:
                        preview_btn = page.get_by_role("button", name="Xem trước Word")
                        if preview_btn.count() > 0:
                            preview_btn.click()
                    report["document_previews"].append(
                        {"route": route, "pages": check_document_preview(page)}
                    )
                page.wait_for_timeout(600)
                filename = f"{index:02d}-desktop.png"
                page.screenshot(path=str(args.output / filename), full_page=True)
                report["pages"].append({"route": route, "screenshot": filename})
            if args.check_motion:
                report["motion_checks"] = check_motion(page, args)
            page.goto(args.url)
            page.get_by_role("heading", name="Cuộc họp gần đây").wait_for()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
            report["mobile_overflow"] = page.evaluate(
                "document.documentElement.scrollWidth>window.innerWidth"
            )
            page.get_by_role("button", name="Mở menu", exact=True).click()
            page.wait_for_timeout(250)
            page.screenshot(path=str(args.output / "mobile-menu.png"), full_page=True)
            if args.check_motion:
                page.locator(".mobile-overlay").click(position={"x": 380, "y": 420})
                page.goto(args.url + "/meetings/new")
                page.get_by_placeholder("Ví dụ: Họp triển khai kế hoạch tháng 10").fill(
                    "Kiểm tra mobile"
                )
                page.get_by_role("button", name="Tiếp tục", exact=True).click()
                expect(
                    page.get_by_role("heading", name="Nguồn âm thanh", exact=True)
                ).to_be_focused()
                page.wait_for_timeout(250)
                page.screenshot(path=str(args.output / "mobile-wizard.png"), full_page=True)
                assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
                if args.meeting_id:
                    page.goto(args.url + "/meetings/" + args.meeting_id + "?tab=minutes")
                    preview_btn = page.get_by_role("button", name="Xem trước Word")
                    if preview_btn.count() > 0:
                        preview_btn.click()
                    expect(page.locator("img.document-page.is-ready")).to_be_visible()
                    page.get_by_role("button", name="Tạo lại biên bản", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    expect(dialog).to_be_visible()
                    page.wait_for_timeout(250)
                    bounds = dialog.bounding_box()
                    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 390
                    page.screenshot(path=str(args.output / "mobile-dialog.png"), full_page=True)
                    page.keyboard.press("Escape")
                    expect(dialog).to_be_hidden()
                report["motion_checks"].append("mobile menu, wizard focus, DOCX and modal bounds")
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
