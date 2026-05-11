"""
Kärcher Sharedien Asset Scraper
Scrapes product assets from https://karcher.sharedien.com/browser/assets
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Configuration ──────────────────────────────────────────────────────────
SHAREDIEN_BASE = "https://karcher.sharedien.com"
PRODUCT_BROWSER_URL = f"{SHAREDIEN_BASE}/browser/product_browser"
ASSETS_URL = f"{SHAREDIEN_BASE}/browser/assets"
LOGIN_URL = "https://auth.kaercher.com/account/login"

# Directories
OUTPUT_DIR = Path(__file__).parent / "sharedien_output"
IMAGES_DIR = OUTPUT_DIR / "images"
DATA_FILE = OUTPUT_DIR / "assets.json"

OUTPUT_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

# Playwright config
HEADLESS = False  # Set to True for headless mode
SLOW_MO = 500     # ms between actions
TIMEOUT = 30000   # 30 seconds default timeout

# ── Helper: download image ───────────────────────────────────────────────────
def download_image(url: str, filename: str, headers: dict = None) -> bool:
    """Download an image to the images directory."""
    try:
        if not url or url.startswith("data:"):
            return False
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = urljoin(SHAREDIEN_BASE, url)

        h = headers or {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=h, timeout=30)
        resp.raise_for_status()

        ext = Path(urlparse(url).path).suffix or ".jpg"
        if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".pdf"]:
            ext = ".jpg"

        out_path = IMAGES_DIR / f"{filename}{ext}"
        out_path.write_bytes(resp.content)
        print(f"  ✓ Image saved: {out_path.name}")
        return True
    except Exception as e:
        print(f"  ✗ Image failed ({url}): {e}")
        return False


# ── Helper: slugify filename ─────────────────────────────────────────────────
def slugify(text: str) -> str:
    """Convert text to a safe filename."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)[:80]


# ── Main scraping logic ──────────────────────────────────────────────────────
def scrape_sharedien_assets(username: str = None, password: str = None):
    assets = []
    seen_image_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_default_timeout(TIMEOUT)

        # ── Navigate directly to product browser ─────────────────────────────────
        print(f"Navigating to {PRODUCT_BROWSER_URL} ...")
        page.goto(PRODUCT_BROWSER_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)
        time.sleep(5)

        # ── Handle disclaimer page ───────────────────────────────────────────
        if "Disclaimer" in page.url or page.locator("h1:has-text('Conditions of Use'), h1:has-text('Disclaimer')").count() > 0:
            print("Detected disclaimer page. Auto-accepting...")
            try:
                # Try multiple selector strategies for the accept button
                accept_selectors = [
                    "button:has-text('Accept')",
                    "button:has-text('I agree')",
                    "button:has-text('I Agree')",
                    "input[type='submit'][value*='Accept']",
                    "a:has-text('Accept')",
                    "button:has-text('conditions')",
                    "button[type='submit']",
                    "input[type='submit']"
                ]

                for selector in accept_selectors:
                    btn = page.locator(selector).first
                    if btn.count():
                        print(f"  Found accept button with selector: {selector}")
                        btn.click()
                        page.wait_for_load_state("networkidle", timeout=30000)
                        print("  ✓ Disclaimer accepted")
                        time.sleep(3)
                        # Re-navigate to product browser
                        page.goto(PRODUCT_BROWSER_URL, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_load_state("networkidle", timeout=60000)
                        time.sleep(5)
                        break
                else:
                    print("  Could not find accept button. Please accept manually.")
                    input("Press ENTER after accepting the disclaimer...")
                    page.goto(PRODUCT_BROWSER_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=60000)
            except Exception as e:
                print(f"  Error accepting disclaimer: {e}")
                input("Press ENTER after accepting the disclaimer...")
                page.goto(PRODUCT_BROWSER_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_load_state("networkidle", timeout=60000)

        # Give SPA time to render
        print("Waiting for SPA to render...")
        time.sleep(10)

        # Scroll to trigger lazy loading
        print("Scrolling to load all lazy content...")
        for _ in range(15):
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            time.sleep(1)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(2)

        # Save page snapshot for inspection
        snapshot_path = OUTPUT_DIR / "sharedien_snapshot.html"
        snapshot_path.write_text(page.content(), encoding="utf-8")
        print(f"Page snapshot saved to: {snapshot_path}")

        # ── Discovery mode ─────────────────────────────────────────────────────
        print("\n--- Discovery: common selectors ---")
        selectors = [
            "img", "h1", "h2", "h3", "[class*='asset']", "[class*='item']",
            "[class*='card']", "[class*='tile']", "[class*='product']",
            "[class*='file']", "[class*='download']", "[class*='image']",
            "a[href*='download']", "a[href*='asset']", "article", "figure"
        ]
        for sel in selectors:
            count = page.locator(sel).count()
            print(f"  {sel:40s} → {count} elements")
        print("--- End discovery ---\n")

        # ── Extract assets ─────────────────────────────────────────────────────
        candidate_sets = [
            {
                "wrapper": "[class*='asset'], [class*='item']",
                "img": "img",
                "name": "h2, h3, h4, [class*='title'], [class*='name'], [class*='filename']",
                "link": "a"
            },
            {
                "wrapper": "[class*='card'], [class*='tile']",
                "img": "img",
                "name": "h2, h3, h4, [class*='title']",
                "link": "a"
            },
            {
                "wrapper": "article, figure",
                "img": "img",
                "name": "figcaption, h2, h3, [class*='title']",
                "link": "a"
            },
            {
                "wrapper": "div[class*='Asset'], div[class*='Item'], div[class*='Card']",
                "img": "img",
                "name": "h2, h3, h4, [class*='title']",
                "link": "a"
            },
        ]

        chosen = None
        for idx, cand in enumerate(candidate_sets, 1):
            count = page.locator(cand["wrapper"]).count()
            print(f"Candidate {idx} ({cand['wrapper']}): {count} items")
            if count > 0 and (chosen is None or count > page.locator(chosen["wrapper"]).count()):
                chosen = cand

        if chosen is None:
            print("No asset wrappers found. Saving snapshot and exiting.")
            browser.close()
            return []

        print(f"\nUsing selector: {chosen['wrapper']}\n")
        wrappers = page.locator(chosen["wrapper"])
        total = wrappers.count()

        for i in range(total):
            wrapper = wrappers.nth(i)
            try:
                # Image
                img_locator = wrapper.locator(chosen["img"]).first
                img_url = img_locator.get_attribute("src") if img_locator.count() else ""
                if not img_url:
                    img_url = img_locator.get_attribute("data-src") if img_locator.count() else ""

                # Name - try multiple approaches
                name_locator = wrapper.locator(chosen["name"]).first
                name = name_locator.inner_text().strip() if name_locator.count() else ""

                # Fallback: extract name from image URL or alt text
                if not name:
                    alt_text = img_locator.get_attribute("alt") if img_locator.count() else ""
                    if alt_text:
                        name = alt_text.strip()

                # Fallback 2: extract from image filename
                if not name and img_url:
                    filename = Path(urlparse(img_url).path).stem
                    name = filename.replace("-", " ").replace("_", " ").replace("default", "").replace("hero", "").strip().title()

                if not name:
                    name = f"asset_{i+1}"

                # Link
                link_url = ""
                if chosen["link"]:
                    link_locator = wrapper.locator(chosen["link"]).first
                    if link_locator.count():
                        href = link_locator.get_attribute("href")
                        link_url = urljoin(SHAREDIEN_BASE, href) if href else ""
                else:
                    href = wrapper.get_attribute("href")
                    link_url = urljoin(SHAREDIEN_BASE, href) if href else ""

                asset = {
                    "id": i + 1,
                    "name": name,
                    "image_url": img_url,
                    "download_url": link_url,
                    "image_file": ""
                }

                # Download image
                if img_url:
                    # Skip duplicates
                    if img_url in seen_image_urls:
                        print(f"[{i+1}/{total}] Skipped (duplicate): {name}")
                        continue
                    seen_image_urls.add(img_url)

                    safe_name = slugify(name) or f"asset_{i+1}"
                    success = download_image(img_url, safe_name)
                    if success:
                        ext = Path(urlparse(img_url).path).suffix or ".jpg"
                        asset["image_file"] = f"{safe_name}{ext}"
                        assets.append(asset)
                        print(f"[{i+1}/{total}] {name}")
                else:
                    print(f"[{i+1}/{total}] Skipped (no image): {name}")
            except Exception as e:
                print(f"[{i+1}/{total}] Error extracting asset: {e}")
                continue

        browser.close()

    return assets


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    USER = os.environ.get("SHAREDIEN_USER", "")
    PASS = os.environ.get("SHAREDIEN_PASS", "")

    if not USER or not PASS:
        print("No credentials provided via SHAREDIEN_USER / SHAREDIEN_PASS env vars.")
        print("The scraper will open a visible browser. Log in manually if required.\n")

    scraped = scrape_sharedien_assets(USER, PASS)

    DATA_FILE.write_text(json.dumps(scraped, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Scraped {len(scraped)} assets.")
    print(f"✓ Data saved to: {DATA_FILE}")
    print(f"✓ Images saved to: {IMAGES_DIR}")
