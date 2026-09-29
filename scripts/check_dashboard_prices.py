"""Browser acceptance against an isolated API/DB; never point at production."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18875")
    parser.add_argument("--output", type=Path, default=Path("output/dashboard-prices-verify"))
    args = parser.parse_args()
    if args.base_url != "http://127.0.0.1:18875":
        parser.error("Use the isolated local test service on port 18875.")
    args.output.mkdir(parents=True, exist_ok=True)
    endpoint = args.base_url + "/api/v1/fluxcast/config/prices"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.base_url + "/dashboard/")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#station-rows tr")).to_have_count(7)
        page.locator("#station-prices").click()
        expect(page.locator("#station-heading th")).to_have_count(3)
        assert "天然气" not in page.locator("#station-heading").inner_text()
        history = page.locator("#station-rows").inner_text()
        page.locator("#edit-prices").click()
        expect(page.locator("#price-inputs input")).to_have_count(14)
        expect(page.locator("#price-save")).to_be_enabled()
        first = page.locator("#price-inputs input").first
        first.fill("0")
        page.locator("#price-save").click()
        assert not first.evaluate("e => e.checkValidity()")
        original = page.request.get(endpoint).json()
        first.fill(str(original["stations"][0]["gen_cost_yuan_per_kwh"] + 0.01))
        page.locator("#price-save").click()
        expect(page.locator("#price-message")).to_contain_text("保存成功")
        saved = page.request.get(endpoint).json()
        assert saved["version"] == original["version"] + 1
        assert len(saved["stations"]) == 7
        assert all(len(s) == 3 and "gas_price_yuan_per_m3" not in s for s in saved["stations"])
        assert page.locator("#station-rows").inner_text() == history
        page.screenshot(path=str(args.output / "price-editor-desktop.png"), full_page=True)
        page.locator("#price-close").click()
        page.locator("#edit-prices").click()
        expect(page.locator("#price-save")).to_be_enabled()
        assert float(first.input_value()) == saved["stations"][0]["gen_cost_yuan_per_kwh"]
        # Another user saves after this editor loaded its version.
        saved["stations"][0]["buy_price_yuan_per_kwh"] += 0.01
        response = page.request.put(
            endpoint,
            data={"expected_version": saved["version"], "stations": saved["stations"]},
        )
        assert response.status == 200
        first.fill("0.77")
        page.locator("#price-save").click()
        expect(page.locator("#price-message")).to_contain_text("本次未保存")
        expect(page.locator("#price-save")).to_be_disabled()
        assert first.input_value() == "0.77"
        page.locator("#price-reload").click()
        expect(page.locator("#price-save")).to_be_enabled()
        assert float(first.input_value()) == response.json()["stations"][0]["gen_cost_yuan_per_kwh"]

        def unavailable(route):
            route.fulfill(status=503, json={"detail": "测试存储不可用"})

        page.route(endpoint, unavailable)
        page.locator("#price-save").click()
        expect(page.locator("#price-message")).to_contain_text("未收到保存成功确认")
        expect(page.locator("#price-save")).to_be_disabled()
        page.locator("#price-reload").click()
        expect(page.locator("#price-message")).to_contain_text("读取失败")
        expect(page.locator("#price-save")).to_be_disabled()
        page.unroute(endpoint, unavailable)
        page.locator("#price-reload").click()
        expect(page.locator("#price-save")).to_be_enabled()
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(args.output / "price-editor-mobile.png"), full_page=True)
        bounds = page.locator("#price-dialog").bounding_box()
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 390
        page.keyboard.press("Escape")
        expect(page.locator("#price-dialog")).not_to_be_visible()
        # Standalone offline files must never imply that server prices can be saved.
        page.goto((Path("dashboard/index.html").resolve()).as_uri())
        page.wait_for_load_state("networkidle")
        page.locator("#edit-prices").click()
        expect(page.locator("#price-message")).to_contain_text("离线文件不能修改")
        expect(page.locator("#price-save")).to_be_disabled()
        assert not errors, errors
        browser.close()
    report = {
        "passed": True,
        "checks": [
            "no gas column",
            "14 inputs",
            "invalid value rejected",
            "real GET/PUT and reopen",
            "historical display unchanged",
            "real concurrent edit conflict",
            "save/read failure handling",
            "mobile dialog and Escape",
            "offline save disabled",
            "no JavaScript exceptions",
        ],
    }
    (args.output / "browser-verification.json").write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
