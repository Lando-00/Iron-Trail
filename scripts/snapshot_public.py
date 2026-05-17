"""Capture screenshots of each dashboard page for the public README.

Adapted from ``snapshot_pages.py``: writes into ``docs/screenshots/``,
targets port 8507, and is meant to run when the only CSV available is the
synthetic sample so no personal training data leaks into committed images.
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

PORT = 8507
BASE = f"http://localhost:{PORT}"

PAGES = [
    ("01_overview", f"{BASE}/"),
    ("02_strength", f"{BASE}/Strength"),
    ("03_volume", f"{BASE}/Volume"),
    ("04_adherence", f"{BASE}/Adherence"),
    ("05_achievements", f"{BASE}/Achievements"),
]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1400, "height": 2400})
        page = await ctx.new_page()
        errors = []
        for name, url in PAGES:
            print(f"-> {name} ({url})")
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                try:
                    await page.locator(
                        ".js-plotly-plot, [data-testid='stMetric'], .it-mini-metric"
                    ).first.wait_for(timeout=20000)
                except Exception:
                    pass
                await page.wait_for_timeout(8000)
                inner_h = await page.evaluate(
                    "document.querySelector('.block-container')?.scrollHeight"
                    " || document.documentElement.scrollHeight"
                )
                target_h = max(1200, int(inner_h) + 80)
                if target_h > 2400:
                    await page.set_viewport_size(
                        {"width": 1400, "height": min(target_h, 6000)}
                    )
                    await page.wait_for_timeout(2000)
                err_locator = page.locator("[data-testid='stException']")
                if await err_locator.count() > 0:
                    txt = await err_locator.first.inner_text()
                    errors.append(f"{name}: {txt[:600]}")
                    print(f"   ERR: {txt[:300]}")
                else:
                    print(f"   ok (inner_h={inner_h})")
                shot = OUT / f"{name}.png"
                await page.screenshot(path=str(shot), full_page=False)
                print(f"   wrote {shot}")
            except Exception as e:
                errors.append(f"{name}: {e}")
                print(f"   failed: {e}")
        await browser.close()
        if errors:
            print("\nERRORS:")
            for e in errors:
                print(f" - {e}")
            sys.exit(1)
        print("\nAll pages OK")


if __name__ == "__main__":
    asyncio.run(main())
