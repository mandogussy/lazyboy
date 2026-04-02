"""
Interior Furniture Matching & Logistics Analyzer
Zero-cost strategy: Playwright headless scraping, no paid APIs.
"""

from __future__ import annotations

import asyncio
import re
import json
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    async_playwright = Page = BrowserContext = None  # type: ignore


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Dimensions:
    width_cm: Optional[float] = None
    depth_cm: Optional[float] = None
    height_cm: Optional[float] = None
    raw: str = ""

    def __str__(self) -> str:
        if self.width_cm and self.depth_cm and self.height_cm:
            return f"W{self.width_cm} × D{self.depth_cm} × H{self.height_cm} cm"
        return self.raw or "N/A"


@dataclass
class Product:
    source: str                          # "ikea" | "ohou" | "aliexpress" | "temu"
    url: str
    name: str = ""
    price_krw: Optional[float] = None   # KRW; convert if foreign
    shipping_fee: Optional[float] = None
    assembly_fee: Optional[float] = None
    dimensions: Dimensions = field(default_factory=Dimensions)
    design_tags: list[str] = field(default_factory=list)
    review_keywords: list[str] = field(default_factory=list)
    affiliate_url: str = ""
    image_url: str = ""          # product thumbnail (best available resolution)

    # --- TCO helpers --------------------------------------------------------

    @property
    def tco(self) -> float:
        base = self.price_krw or 0.0
        ship = self.shipping_fee or 0.0
        asm  = self.assembly_fee or 0.0
        return base + ship + asm

    @property
    def convenience_tier(self) -> str:
        if self.source in ("ohou", "coupang"):
            return "A – Direct/Fast (no assembly, fast shipping)"
        if self.source == "ikea":
            return "B – Transit/DIY (assembly required)"
        return "C – Budget/Long-haul (quality risk; check reviews)"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tco"] = self.tco
        d["convenience_tier"] = self.convenience_tier
        return d


# ---------------------------------------------------------------------------
# Regex dimension parser
# ---------------------------------------------------------------------------

# Handles patterns like:
#   "W120 x D45 x H75 cm"   "120 × 45 × 75"   "가로120 세로45 높이75"
#   "너비 120cm / 깊이 45cm / 높이 75cm"
#   "1200 x 450 x 750 mm"   (auto-converts mm → cm)

_SEP   = r"[\s×x\*xX\u00d7]+"          # separators: space / × / x / * / X
_NUM   = r"(\d+(?:\.\d+)?)"             # capture group for a number
_UNIT  = r"\s*(?:cm|mm)?"              # optional unit suffix per value
_LABEL = r"(?:[WwGg가-힣]*\s*)"         # optional label prefix (W / 가로 / etc.)

# --- Pattern A: three numbers in sequence with optional labels/units
_DIM_SEQ = re.compile(
    rf"{_LABEL}{_NUM}{_UNIT}\s*{_SEP}\s*"
    rf"{_LABEL}{_NUM}{_UNIT}\s*{_SEP}\s*"
    rf"{_LABEL}{_NUM}{_UNIT}",
    re.IGNORECASE,
)

# --- Pattern B: Korean labelled (가로|너비|폭 … 세로|깊이 … 높이|키)
_DIM_KO = re.compile(
    r"(?:가로|너비|폭)[^\d]*?(\d+(?:\.\d+)?)\s*(?:cm|mm)?"
    r"[^\d]*?(?:세로|깊이|depth)[^\d]*?(\d+(?:\.\d+)?)\s*(?:cm|mm)?"
    r"[^\d]*?(?:높이|height)[^\d]*?(\d+(?:\.\d+)?)\s*(?:cm|mm)?",
    re.IGNORECASE,
)

# --- Pattern C: explicit W/D/H labels (IKEA style)
_DIM_WDH = re.compile(
    r"[Ww(?:width)(?:너비)]+[^\d]*?(\d+(?:\.\d+)?)\s*(?:cm|mm)?"
    r"[^\d]*?[Dd(?:depth)(?:깊이)]+[^\d]*?(\d+(?:\.\d+)?)\s*(?:cm|mm)?"
    r"[^\d]*?[Hh(?:height)(?:높이)]+[^\d]*?(\d+(?:\.\d+)?)\s*(?:cm|mm)?",
    re.IGNORECASE,
)

# price pattern: handles "₩123,456" "123,456원" "KRW 123456"
_PRICE_KO = re.compile(r"[₩￦]?\s*(\d{1,3}(?:,\d{3})+|\d+)\s*원?")


def _to_cm(value: float, raw_text: str) -> float:
    """Auto-detect mm and convert."""
    if "mm" in raw_text.lower():
        return round(value / 10, 1)
    return value


def parse_dimensions(text: str) -> Dimensions:
    """Extract W/D/H from arbitrary Korean/English product text."""
    for pattern in (_DIM_WDH, _DIM_KO, _DIM_SEQ):
        m = pattern.search(text)
        if m:
            w, d, h = (float(v) for v in m.groups()[:3])
            w = _to_cm(w, text)
            d = _to_cm(d, text)
            h = _to_cm(h, text)
            return Dimensions(width_cm=w, depth_cm=d, height_cm=h, raw=m.group(0))
    return Dimensions(raw="")


def parse_price(text: str) -> Optional[float]:
    m = _PRICE_KO.search(text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}


async def make_page(context: BrowserContext) -> Page:
    page = await context.new_page()
    await page.set_extra_http_headers(HEADERS)
    return page


async def safe_text(page: Page, selector: str, default: str = "") -> str:
    try:
        el = await page.query_selector(selector)
        return (await el.inner_text()).strip() if el else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# IKEA scraper
# ---------------------------------------------------------------------------

async def scrape_ikea(url: str, context: BrowserContext) -> Product:
    product = Product(source="ikea", url=url)
    page = await make_page(context)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)

        # --- Name
        product.name = await safe_text(
            page,
            "h1[class*='pip-header-section__title'], "
            "span[class*='pip-header-section__title--big']",
        )

        # --- Hero image (prefer zoom/large variant)
        for img_sel in [
            "img[class*='pip-image']",
            "div[class*='pip-media-grid'] img",
            "img[class*='product-image']",
        ]:
            el = await page.query_selector(img_sel)
            if el:
                src = await el.get_attribute("src") or ""
                srcset = await el.get_attribute("srcset") or ""
                if srcset:
                    parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
                    src = parts[-1] if parts else src
                if src:
                    product.image_url = src
                    break

        # --- Price (handle "From" pricing too)
        price_raw = await safe_text(
            page,
            "span[class*='pip-price__integer'], "
            "span[class*='pip-temp-price__integer']",
        )
        if price_raw:
            # IKEA KR prices are in KRW integers
            product.price_krw = float(re.sub(r"[^\d.]", "", price_raw))

        # --- Product details section – grab all text
        details_text = await safe_text(
            page,
            "div[class*='pip-product-details__container'], "
            "div[id*='product-details']",
        )
        if not details_text:
            # fallback: dump full page text for regex scanning
            details_text = await page.inner_text("body")

        product.dimensions = parse_dimensions(details_text)

        # --- Shipping fee (look for delivery/배송비 mentions)
        ship_match = re.search(
            r"(?:배송비|shipping)[^\d]*?([₩￦]?\d[\d,]*\s*원?)",
            details_text,
            re.IGNORECASE,
        )
        if ship_match:
            product.shipping_fee = parse_price(ship_match.group(1))

        # --- Assembly (IKEA items usually list assembly separately)
        asm_match = re.search(
            r"(?:조립|assembly)[^\d]*?([₩￦]?\d[\d,]*\s*원?)",
            details_text,
            re.IGNORECASE,
        )
        if asm_match:
            product.assembly_fee = parse_price(asm_match.group(1))

    finally:
        await page.close()

    return product


# ---------------------------------------------------------------------------
# Today's House (ohou.se) scraper
# ---------------------------------------------------------------------------

async def scrape_ohou(url: str, context: BrowserContext) -> Product:
    product = Product(source="ohou", url=url)
    page = await make_page(context)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)

        # --- Name
        product.name = await safe_text(
            page,
            "h1[class*='productTitle'], "
            "h2[class*='name'], "
            "div[class*='product-name']",
        )

        # --- Hero image
        for img_sel in [
            "img[class*='productImage']",
            "div[class*='thumbnail'] img",
            "img[class*='main-image']",
            "div[class*='gallery'] img",
        ]:
            el = await page.query_selector(img_sel)
            if el:
                src = await el.get_attribute("src") or ""
                srcset = await el.get_attribute("srcset") or ""
                if srcset:
                    parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
                    src = parts[-1] if parts else src
                if src:
                    product.image_url = src
                    break

        # --- Price
        price_raw = await safe_text(
            page,
            "span[class*='salePrice'], "
            "strong[class*='price'], "
            "p[class*='price']",
        )
        product.price_krw = parse_price(price_raw)

        # --- Spec table (오늘의집 상품 스펙)
        spec_rows = await page.query_selector_all(
            "table[class*='spec'] tr, "
            "dl[class*='spec'] dt, "
            "div[class*='productInfo'] li"
        )
        spec_text_parts: list[str] = []
        for row in spec_rows:
            spec_text_parts.append(await row.inner_text())
        spec_text = "\n".join(spec_text_parts)

        if not spec_text:
            spec_text = await safe_text(page, "div[class*='detail'], div[class*='spec']")

        product.dimensions = parse_dimensions(spec_text or await page.inner_text("body"))

        # --- Design tags
        tag_els = await page.query_selector_all(
            "a[class*='tag'], span[class*='tag'], button[class*='tag']"
        )
        for el in tag_els:
            tag = (await el.inner_text()).strip()
            if tag and tag not in product.design_tags:
                product.design_tags.append(tag)

        # --- Shipping fee
        ship_raw = await safe_text(
            page,
            "span[class*='delivery'], "
            "p[class*='ship'], "
            "div[class*='shippingFee']",
        )
        product.shipping_fee = parse_price(ship_raw) if ship_raw else 0.0  # often free

    finally:
        await page.close()

    return product


# ---------------------------------------------------------------------------
# AliExpress / Temu scraper (reviews + quality signals)
# ---------------------------------------------------------------------------

_QUALITY_KEYWORDS = [
    "실물", "품질", "만족", "배송", "색상", "사이즈", "튼튼", "가성비",
    "quality", "size", "color", "sturdy", "worth", "cheap", "fragile",
]

async def scrape_aliexpress(url: str, context: BrowserContext) -> Product:
    source = "temu" if "temu.com" in url else "aliexpress"
    product = Product(source=source, url=url)
    page = await make_page(context)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40_000)
        await page.wait_for_timeout(3000)

        product.name = await safe_text(
            page,
            "h1[class*='product-title'], "
            "h1[data-pl='product-title'], "
            "span[class*='Title']",
        )

        # --- Hero image
        for img_sel in [
            "img[class*='product-image']",
            "img[class*='magnifier-image']",
            "div[class*='slider'] img",
            "img[class*='ProductImage']",
        ]:
            el = await page.query_selector(img_sel)
            if el:
                src = await el.get_attribute("src") or ""
                srcset = await el.get_attribute("srcset") or ""
                if srcset:
                    parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
                    src = parts[-1] if parts else src
                if src and src.startswith("http"):
                    product.image_url = src
                    break

        price_raw = await safe_text(
            page,
            "span[class*='price'], "
            "div[class*='uniform-banner-box-price']",
        )
        if price_raw:
            # Prices in USD/CNY – leave raw, flag for manual conversion
            nums = re.findall(r"\d+(?:\.\d+)?", price_raw)
            if nums:
                product.price_krw = float(nums[0])  # placeholder; multiply by FX rate

        # Product spec
        spec_text = await safe_text(
            page,
            "div[class*='specification'], "
            "div[id*='specification']",
        )
        product.dimensions = parse_dimensions(spec_text)

        # Top reviews (Korean, 4-5 star)
        review_els = await page.query_selector_all(
            "div[class*='review-content'], "
            "span[class*='review-text'], "
            "p[class*='reviewText']"
        )
        all_review_text = " ".join(
            [(await el.inner_text()).strip() for el in review_els[:20]]
        )

        product.review_keywords = [
            kw for kw in _QUALITY_KEYWORDS if kw in all_review_text.lower()
        ]

    finally:
        await page.close()

    return product


# ---------------------------------------------------------------------------
# Pinterest → reverse image → real product mapper
# ---------------------------------------------------------------------------

async def pinterest_to_product(
    pinterest_url: str, context: BrowserContext
) -> dict:
    """
    1. Load Pinterest pin and grab the main image URL.
    2. Build a Google Images reverse-search URL (no API).
    3. Scrape the first few results for product matches.
    Returns a dict with image_url + candidate search URLs.
    """
    page = await make_page(context)
    image_url = ""

    try:
        await page.goto(pinterest_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)

        # Pinterest renders images in <img> tags with srcset
        img_el = await page.query_selector(
            "div[data-test-id='pin-closeup-image'] img, "
            "img[class*='hCL']"
        )
        if img_el:
            image_url = await img_el.get_attribute("src") or ""
            # Prefer the highest-res URL from srcset
            srcset = await img_el.get_attribute("srcset") or ""
            if srcset:
                parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
                if parts:
                    image_url = parts[-1]  # last = highest resolution
    finally:
        await page.close()

    if not image_url:
        return {"error": "Could not extract image from Pinterest URL", "image_url": ""}

    # Google reverse image search URL (no API key needed)
    encoded = urllib.parse.quote(image_url, safe="")
    google_lens_url = f"https://lens.google.com/uploadbyurl?url={encoded}"
    google_images_url = (
        f"https://www.google.com/searchbyimage?image_url={encoded}&safe=off"
    )

    # Ohou.se text search fallback using extracted pin title
    return {
        "image_url": image_url,
        "google_lens_url": google_lens_url,
        "google_images_url": google_images_url,
        "note": (
            "Open google_lens_url in browser for visual matches. "
            "Feed matching product pages back to scrape_ikea / scrape_ohou."
        ),
    }


# ---------------------------------------------------------------------------
# Affiliate link generator
# ---------------------------------------------------------------------------

AFFILIATE_CONFIG: dict[str, dict] = {
    "ikea": {
        "param": "affid",
        "id": "YOUR_IKEA_AFFILIATE_ID",
    },
    "ohou": {
        "param": "utm_source",
        "id": "YOUR_OHOU_AFFILIATE_ID",
        "extra": {"utm_medium": "affiliate", "utm_campaign": "furniture"},
    },
    "aliexpress": {
        "param": "aff_fcid",
        "id": "YOUR_ALI_AFFILIATE_ID",
    },
    "temu": {
        "param": "refer_url",
        "id": "YOUR_TEMU_AFFILIATE_ID",
    },
}


def generate_affiliate_url(product: Product) -> str:
    cfg = AFFILIATE_CONFIG.get(product.source)
    if not cfg:
        return product.url

    parsed = urllib.parse.urlparse(product.url)
    qs = dict(urllib.parse.parse_qsl(parsed.query))
    qs[cfg["param"]] = cfg["id"]
    if "extra" in cfg:
        qs.update(cfg["extra"])

    new_query = urllib.parse.urlencode(qs)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


# ---------------------------------------------------------------------------
# TCO report formatter
# ---------------------------------------------------------------------------

def print_tco_report(products: list[Product]) -> None:
    print("\n" + "=" * 70)
    print("  FURNITURE MATCHING & LOGISTICS ANALYZER — TCO REPORT")
    print("=" * 70)

    sorted_products = sorted(
        [p for p in products if p.price_krw],
        key=lambda p: p.tco,
    )

    for i, p in enumerate(sorted_products, 1):
        aff = generate_affiliate_url(p)
        p.affiliate_url = aff
        print(f"\n[{i}] {p.name or 'Unknown Product'}")
        print(f"    Source    : {p.source.upper()}")
        print(f"    Dimensions: {p.dimensions}")
        print(f"    Base Price: ₩{p.price_krw:,.0f}")
        print(f"    Shipping  : ₩{p.shipping_fee or 0:,.0f}")
        print(f"    Assembly  : ₩{p.assembly_fee or 0:,.0f}")
        print(f"    ── TCO ──: ₩{p.tco:,.0f}")
        print(f"    Tier      : {p.convenience_tier}")
        if p.design_tags:
            print(f"    Tags      : {', '.join(p.design_tags[:8])}")
        if p.review_keywords:
            print(f"    Review KWs: {', '.join(p.review_keywords)}")
        print(f"    Affiliate : {aff}")

    print("\n" + "=" * 70)
    if sorted_products:
        winner = sorted_products[0]
        print(f"  LOWEST TCO: {winner.name or winner.source.upper()} — ₩{winner.tco:,.0f}")
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def analyze(urls: dict[str, str]) -> list[Product]:
    """
    urls: {"ikea": "https://...", "ohou": "https://...", "aliexpress": "https://..."}
    """
    products: list[Product] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )

        # Stealth: hide webdriver property
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        tasks = []
        if "ikea" in urls:
            tasks.append(scrape_ikea(urls["ikea"], context))
        if "ohou" in urls:
            tasks.append(scrape_ohou(urls["ohou"], context))
        if "aliexpress" in urls or "temu" in urls:
            key = "aliexpress" if "aliexpress" in urls else "temu"
            tasks.append(scrape_aliexpress(urls[key], context))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                print(f"[WARN] Scrape error: {r}")
            else:
                products.append(r)

        await browser.close()

    return products


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # --- Demo mode with sample URLs (replace with real ones) ---------------
    sample_urls: dict[str, str] = {}

    if len(sys.argv) > 1:
        # Accept JSON file path: python scraper.py urls.json
        with open(sys.argv[1]) as f:
            sample_urls = json.load(f)
    else:
        # Hardcode for quick testing (replace these URLs)
        sample_urls = {
            # "ikea": "https://www.ikea.com/kr/ko/p/...",
            # "ohou": "https://ohou.se/productions/...",
            # "aliexpress": "https://www.aliexpress.com/item/...",
        }

    if not sample_urls:
        # --- Self-test: dimension parser only (no network needed) ----------
        print("No URLs provided. Running dimension parser self-test...\n")
        test_cases = [
            ("IKEA EN",   "Width: 120 cm Depth: 45 cm Height: 75 cm"),
            ("IKEA W×D×H","W120 × D45 × H75 cm"),
            ("Korean 1",  "가로 120cm / 세로 45cm / 높이 75cm"),
            ("Korean 2",  "너비 1200mm × 깊이 450mm × 높이 750mm"),
            ("Sequence",  "120 x 45 x 75"),
            ("Mixed",     "상품 크기: 폭 60 깊이 40 높이 120 (cm)"),
            ("No dim",    "이 제품은 인기 있는 소파입니다."),
        ]
        for label, text in test_cases:
            dim = parse_dimensions(text)
            print(f"  [{label:12s}]  '{text}'")
            print(f"               → {dim}\n")
        print("To scrape real URLs, create urls.json:")
        print('  {"ikea": "https://...", "ohou": "https://..."}')
        print("Then run: python scraper.py urls.json\n")
        sys.exit(0)

    if not _PLAYWRIGHT_AVAILABLE:
        print("Playwright not installed. Run:\n  pip install playwright && playwright install chromium")
        sys.exit(1)

    products = asyncio.run(analyze(sample_urls))

    if products:
        print_tco_report(products)
        # Save JSON
        out_path = "furniture_report.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([p.to_dict() for p in products], f, ensure_ascii=False, indent=2)
        print(f"Full report saved → {out_path}")
    else:
        print("No products scraped.")
