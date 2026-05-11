"""
Kärcher DCA Product Scraper
Extracts product images and data from https://dca.kaercher.com/group-overview/20035385
Uses Playwright to render the React SPA.
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

# Config
BASE_URL = "https://dca.kaercher.com"
GROUP_URL = f"{BASE_URL}/group-overview/20035385"
LOGIN_URL = "https://marketingportal.karcher.com/home"

# Directories
OUTPUT_DIR = Path(__file__).parent / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
DATA_FILE = OUTPUT_DIR / "products.json"

OUTPUT_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

# Playwright config
HEADLESS = False  # Set to True for headless mode
SLOW_MO = 500     # ms between actions (helps with lazy-loading)
TIMEOUT = 30000   # 30 seconds default timeout

# Image download
def download_image(url: str, filename: str, headers: dict = None) -> bool:
    """Download an image to the images directory."""
    try:
        if not url or url.startswith("data:"):
            return False
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = urljoin(BASE_URL, url)

        h = headers or {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=h, timeout=30)
        resp.raise_for_status()

        ext = Path(urlparse(url).path).suffix or ".jpg"
        if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"]:
            ext = ".jpg"

        out_path = IMAGES_DIR / f"{filename}{ext}"
        out_path.write_bytes(resp.content)
        print(f"  ✓ Image saved: {out_path.name}")
        return True
    except Exception as e:
        print(f"  ✗ Image failed ({url}): {e}")
        return False



def slugify(text: str) -> str:
    """Convert text to a safe filename."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)[:80]



def discover_selectors(page):
    """Print common product-related element counts to help identify selectors."""
    print("\n--- Discovery: common selectors ---")
    selectors = [
        "img", "h1", "h2", "h3", "[class*='product']", "[class*='item']",
        "[class*='card']", "[class*='tile']", "a[href*='product']",
        "a[href*='detail']", "[data-testid*='product']", "article", "figure"
    ]
    for sel in selectors:
        count = page.locator(sel).count()
        print(f"  {sel:40s} → {count} elements")
    print("--- End discovery ---\n")


# Main scraping logic
def scrape_group_overview(username: str = None, password: str = None):
    products = []
    seen_image_urls = set()  # Duplicatie vermijden

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=HEADLESS, slow_mo=SLOW_MO)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_default_timeout(TIMEOUT)

        # Login
        # Login is only needed for marketingportal.karcher.com (high-res images)
        # The dca.kaercher.com site with products can be accessed directly
        if username and password:
            print("Login is for marketingportal.karcher.com (optional for high-res images).")
            print("Proceeding directly to dca.kaercher.com for product listing...\n")
            # Uncomment below if you need to login to marketingportal first
            # print("Logging in to marketingportal.karcher.com...")
            # page.goto(LOGIN_URL)
            # try:
            #     page.locator("input[name='username'], input[type='email'], #username, input[id*='user']").first.fill(username)
            #     page.locator("input[name='password'], input[type='password'], #password").first.fill(password)
            #     page.locator("button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Sign in')").first.click()
            #     page.wait_for_load_state("networkidle")
            #     print("Login flow completed.\n")
            # except PlaywrightTimeout:
            #     print("Could not auto-detect login form. Please log in manually in the opened browser.")
            #     input("Press ENTER after you have logged in...")

        # ── Navigate to product group ────────────────────────────────────────
        print(f"Navigating to {GROUP_URL} ...")
        page.goto(GROUP_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        # Check if we're on the welcome/country selection page
        if page.locator("h1.welcome, h1:has-text('Welcome'), .welcome-container").count() > 0:
            print("Detected welcome/country selection page. Selecting Netherlands and English...")

            # Select country (Netherlands)
            try:
                country_dropdown = page.locator("button:has-text('International'), button.dropdown-toggle").first
                if country_dropdown.count():
                    country_dropdown.click()
                    time.sleep(1)
                    # Look for Netherlands option
                    netherlands_option = page.locator("a, button, div").filter(has_text="Netherlands").first
                    if netherlands_option.count():
                        netherlands_option.click()
                        print("  ✓ Selected Netherlands")
            except Exception as e:
                print(f"  Could not select country: {e}")

            # Select language (English)
            try:
                language_dropdown = page.locator("button.dropdown-toggle").nth(1) if page.locator("button.dropdown-toggle").count() > 1 else page.locator("button:has-text('English'), button.dropdown-toggle").first
                if language_dropdown.count():
                    language_dropdown.click()
                    time.sleep(1)
                    english_option = page.locator("a, button, div").filter(has_text="English").first
                    if english_option.count():
                        english_option.click()
                        print("  ✓ Selected English")
            except Exception as e:
                print(f"  Could not select language: {e}")

            # Click START button
            try:
                start_button = page.locator("button:has-text('START'), button.start, button.theme-btn").first
                if start_button.count():
                    start_button.click()
                    print("  ✓ Clicked START")
                    page.wait_for_load_state("networkidle")
                    time.sleep(3)
            except Exception as e:
                print(f"  Could not click START: {e}")

            # Now navigate to the actual group overview
            print(f"Re-navigating to {GROUP_URL} after selection...")
            page.goto(GROUP_URL, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")

        # Give React extra time to hydrate / fetch data
        print("Waiting for SPA to render...")
        time.sleep(10)

        # Scroll to trigger lazy loading
        print("Scrolling to load all lazy content...")
        for _ in range(10):
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            time.sleep(1)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(2)

        # Discovery mode (comment out once selectors are known)
        discover_selectors(page)

        # Save page snapshot for inspection
        snapshot_path = OUTPUT_DIR / "page_snapshot.html"
        snapshot_path.write_text(page.content(), encoding="utf-8")
        print(f"Page snapshot saved to: {snapshot_path}")

        # ── Extract products ─────────────────────────────────────────────────
        # Try several common selector strategies.  Playwright locators auto-wait,
        # so we test a few heuristic locators and pick the one that returns hits.
        candidate_sets = [
            # Kärcher DCA often uses class names containing "product" or "card"
            {
                "wrapper": "[class*='product']",
                "img": "img",
                "name": "h2, h3, [class*='title'], [class*='name']",
                "link": "a"
            },
            {
                "wrapper": "article, [class*='card'], [class*='item']",
                "img": "img",
                "name": "h2, h3, [class*='title']",
                "link": "a"
            },
            {
                "wrapper": "a[href*='product'], a[href*='detail']",
                "img": "img",
                "name": "h2, h3, span, div",
                "link": ""
            },
            {
                "wrapper": "[class*='tile'], [class*='grid'], [class*='list']",
                "img": "img",
                "name": "h2, h3, h4, span, div",
                "link": "a"
            },
            {
                "wrapper": "div[class*='Product'], div[class*='Item'], div[class*='Card']",
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
            print("No product wrappers found with heuristics. Saving page snapshot for inspection.")
            snapshot_path = OUTPUT_DIR / "page_snapshot.html"
            snapshot_path.write_text(page.content(), encoding="utf-8")
            print(f"Snapshot saved to {snapshot_path}")
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
                    # Clean up filename (remove underscores, hyphens, convert to title case)
                    name = filename.replace("-", " ").replace("_", " ").replace("default", "").replace("hero", "").strip().title()

                if not name:
                    name = f"product_{i+1}"

                # Link
                link_url = ""
                if chosen["link"]:
                    link_locator = wrapper.locator(chosen["link"]).first
                    if link_locator.count():
                        href = link_locator.get_attribute("href")
                        link_url = urljoin(BASE_URL, href) if href else ""
                else:
                    href = wrapper.get_attribute("href")
                    link_url = urljoin(BASE_URL, href) if href else ""

                product = {
                    "id": i + 1,
                    "name": name,
                    "image_url": img_url,
                    "product_url": link_url,
                    "image_file": ""
                }

                # Download image
                if img_url:
                    # Skip duplicates
                    if img_url in seen_image_urls:
                        print(f"[{i+1}/{total}] Skipped (duplicate): {name}")
                        continue
                    seen_image_urls.add(img_url)

                    safe_name = slugify(name) or f"product_{i+1}"
                    success = download_image(img_url, safe_name)
                    if success:
                        ext = Path(urlparse(img_url).path).suffix or ".jpg"
                        product["image_file"] = f"{safe_name}{ext}"
                        products.append(product)
                        print(f"[{i+1}/{total}] {name}")
                else:
                    # Skip items without images (likely navigation elements)
                    print(f"[{i+1}/{total}] Skipped (no image): {name}")
            except Exception as e:
                print(f"[{i+1}/{total}] Error extracting product: {e}")
                continue

        # Handle page
        # Look for a "next" or "load more" button and recurse
        next_btn_selectors = [
            "button:has-text('Next')", "a:has-text('Next')",
            "button:has-text('Load more')", "a:has-text('Load more')",
            "[class*='pagination'] a:last-child", "[aria-label*='next']"
        ]
        for sel in next_btn_selectors:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                print("\nPagination detected — clicking 'Next / Load more'...")
                btn.click()
                page.wait_for_load_state("networkidle")
                time.sleep(3)
                # Recursively scrape new items (simple approach)
                more = scrape_remaining(page, chosen, len(products))
                products.extend(more)
                break

        browser.close()

    return products


def scrape_remaining(page, chosen, start_index):
    """Scrape additional products after pagination (helper)."""
    more = []
    wrappers = page.locator(chosen["wrapper"])
    total = wrappers.count()
    for i in range(start_index, total):
        wrapper = wrappers.nth(i)
        try:
            img_locator = wrapper.locator(chosen["img"]).first
            img_url = img_locator.get_attribute("src") if img_locator.count() else ""
            if not img_url:
                img_url = img_locator.get_attribute("data-src") if img_locator.count() else ""

            name_locator = wrapper.locator(chosen["name"]).first
            name = name_locator.inner_text().strip() if name_locator.count() else f"product_{i+1}"

            link_url = ""
            if chosen["link"]:
                link_locator = wrapper.locator(chosen["link"]).first
                if link_locator.count():
                    href = link_locator.get_attribute("href")
                    link_url = urljoin(BASE_URL, href) if href else ""
            else:
                href = wrapper.get_attribute("href")
                link_url = urljoin(BASE_URL, href) if href else ""

            product = {
                "id": i + 1,
                "name": name,
                "image_url": img_url,
                "product_url": link_url,
                "image_file": ""
            }

            if img_url:
                safe_name = slugify(name) or f"product_{i+1}"
                success = download_image(img_url, safe_name)
                if success:
                    ext = Path(urlparse(img_url).path).suffix or ".jpg"
                    product["image_file"] = f"{safe_name}{ext}"

            more.append(product)
            print(f"[{i+1}/{total}] {name}")
        except Exception as e:
            print(f"[{i+1}/{total}] Error: {e}")
    return more


# Entry
if __name__ == "__main__":
    # Credentials can be passed as env vars or left empty for manual login
    USER = os.environ.get("KARCHER_USER", "")
    PASS = os.environ.get("KARCHER_PASS", "")

    if not USER or not PASS:
        print("No credentials provided via KARCHER_USER / KARCHER_PASS env vars.")
        print("The scraper will open a visible browser. Log in manually if required, then press ENTER.\n")

    scraped = scrape_group_overview(USER, PASS)

    # Save JSON manifest
    DATA_FILE.write_text(json.dumps(scraped, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Scraped {len(scraped)} products.")
    print(f"✓ Data saved to: {DATA_FILE}")
    print(f"✓ Images saved to: {IMAGES_DIR}")
