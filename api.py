"""
Lazyboy — Furniture Search API
FastAPI + Playwright keyword search across multiple Korean furniture platforms.

Deploy on Render (free tier):
  Build:  pip install -r requirements.txt && playwright install chromium --with-deps
  Start:  uvicorn api:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import quote, urlencode, urlparse, parse_qs, urlunparse

# ── Affiliate config (set via Render environment variables) ───────────────────
# Render dashboard → Environment → Add these keys
COUPANG_PARTNER_ID = os.getenv("COUPANG_PARTNER_ID", "")   # partners.coupang.com
ALIEXPRESS_AFF_ID  = os.getenv("ALIEXPRESS_AFF_ID",  "")   # portals.aliexpress.com


def affiliate_url(url: str, platform: str) -> str:
    """Append affiliate tracking parameters to a product/search URL."""
    if platform == "Coupang" and COUPANG_PARTNER_ID:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}affiliate=coupang&subid={COUPANG_PARTNER_ID}"
    if platform == "AliExpress" and ALIEXPRESS_AFF_ID:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}aff_fcid={ALIEXPRESS_AFF_ID}&aff_platform=portals-hotproduct"
    return url

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright, BrowserContext, Page

# ── Browser lifecycle (shared across requests) ────────────────────────────────

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
        ],
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    await context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    _state["context"] = context
    _state["sem"] = asyncio.Semaphore(3)  # max 3 parallel pages
    print("Browser ready.")
    yield
    await context.close()
    await browser.close()
    await pw.stop()


app = FastAPI(title="Lazyboy Search API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_price(s: str) -> int:
    n = re.sub(r"[^0-9]", "", str(s or ""))
    return int(n) if n else 0

def guess_size(name: str) -> int:
    m = re.search(r"(\d{3,4})\s*(?:mm|cm)?", name or "")
    if not m:
        return 0
    n = int(m.group(1))
    return n if n > 300 else n * 10

async def new_page(context: BrowserContext) -> Page:
    page = await context.new_page()
    await page.set_extra_http_headers({"Accept-Language": "ko-KR,ko;q=0.9"})
    return page

async def extract_next_data(page: Page) -> Optional[dict]:
    try:
        raw = await page.evaluate(
            "() => { const el = document.getElementById('__NEXT_DATA__'); return el ? el.textContent : null; }"
        )
        return json.loads(raw) if raw else None
    except Exception:
        return None

# ── Platform scrapers ─────────────────────────────────────────────────────────

async def search_ikea(query: str) -> list[dict]:
    async with _state["sem"]:
        page = await new_page(_state["context"])
        try:
            await page.goto(
                f"https://www.ikea.com/kr/ko/search/products/?q={quote(query)}",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            await page.wait_for_timeout(2000)

            nd = await extract_next_data(page)
            if not nd:
                return []

            products = (
                nd.get("props", {}).get("pageProps", {}).get("searchData", {}).get("productWindow")
                or nd.get("props", {}).get("pageProps", {}).get("products")
                or []
            )

            results = []
            for p in products[:6]:
                raw_price = (
                    (p.get("salesPrice") or {}).get("numeral")
                    or (p.get("price") or {}).get("numeral")
                    or "0"
                )
                name = (
                    p.get("mainImageAlt") or p.get("name") or p.get("productNameGlobal") or ""
                ).split(",")[0].strip()
                pip = p.get("pipUrl", "")
                url = f"https://www.ikea.com{pip}" if pip else f"https://www.ikea.com/kr/ko/search/products/?q={quote(query)}"
                price = parse_price(str(raw_price))
                if name and price > 0:
                    results.append({
                        "platform": "IKEA", "name": name, "price": price,
                        "shipping": 0, "shipping_label": "무료배송",
                        "delivery_type": "standard", "days": 2,
                        "size": guess_size(name), "popular": False,
                        "url": url, "live": True,
                    })
            return results
        except Exception as e:
            print(f"IKEA error: {e}")
            return []
        finally:
            await page.close()


async def search_coupang(query: str) -> list[dict]:
    async with _state["sem"]:
        page = await new_page(_state["context"])
        try:
            await page.goto(
                f"https://www.coupang.com/np/search?component=&q={quote(query)}&channel=user",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            await page.wait_for_timeout(2000)

            nd = await extract_next_data(page)
            items = (nd or {}).get("props", {}).get("pageProps", {}).get("searchResult", {}).get("productData", [])

            if items:
                results = []
                for p in items[:6]:
                    is_rocket = bool(p.get("isRocket"))
                    name = p.get("productName") or ""
                    price = parse_price(str(p.get("price") or p.get("salePrice") or 0))
                    purl = p.get("productUrl", "")
                    if name and price > 0:
                        results.append({
                            "platform": "Coupang", "name": name, "price": price,
                            "shipping": 0 if is_rocket else 3000,
                            "shipping_label": "무료배송 (로켓)" if is_rocket else "3,000원",
                            "delivery_type": "express" if is_rocket else "standard",
                            "days": 1 if is_rocket else 3,
                            "size": guess_size(name),
                            "popular": int(p.get("reviewCount") or 0) > 100,
                            "url": affiliate_url(f"https://www.coupang.com{purl}" if purl else f"https://www.coupang.com/np/search?q={quote(query)}", "Coupang"),
                            "live": True,
                        })
                return results

            # Fallback: parse DOM
            cards = await page.query_selector_all("li.search-product")
            results = []
            for card in cards[:6]:
                name_el  = await card.query_selector(".name")
                price_el = await card.query_selector(".price-value")
                rocket   = await card.query_selector(".rocket")
                name  = (await name_el.inner_text()).strip()  if name_el  else ""
                price = parse_price((await price_el.inner_text()).strip() if price_el else "0")
                is_rocket = rocket is not None
                if name and price > 0:
                    results.append({
                        "platform": "Coupang", "name": name, "price": price,
                        "shipping": 0 if is_rocket else 3000,
                        "shipping_label": "무료배송 (로켓)" if is_rocket else "3,000원",
                        "delivery_type": "express" if is_rocket else "standard",
                        "days": 1 if is_rocket else 3,
                        "size": guess_size(name), "popular": False,
                        "url": affiliate_url(f"https://www.coupang.com/np/search?q={quote(query)}", "Coupang"),
                        "live": True,
                    })
            return results
        except Exception as e:
            print(f"Coupang error: {e}")
            return []
        finally:
            await page.close()


async def search_ohou(query: str) -> list[dict]:
    async with _state["sem"]:
        page = await new_page(_state["context"])
        try:
            await page.goto(
                f"https://ohou.se/search?q={quote(query)}&type=product",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            await page.wait_for_timeout(2000)

            nd = await extract_next_data(page)
            products = (
                (nd or {}).get("props", {}).get("pageProps", {}).get("products")
                or (nd or {}).get("props", {}).get("pageProps", {}).get("searchResult", {}).get("products")
                or []
            )

            results = []
            for p in products[:6]:
                name  = p.get("name") or p.get("title") or ""
                price = parse_price(str(p.get("price") or p.get("salePrice") or 0))
                ship  = int(p.get("deliveryPrice") or 3000)
                purl  = p.get("url", "")
                if name and price > 0:
                    results.append({
                        "platform": "오늘의집", "name": name, "price": price,
                        "shipping": ship,
                        "shipping_label": "무료배송" if ship == 0 else f"{ship:,}원",
                        "delivery_type": "standard", "days": 3,
                        "size": guess_size(name),
                        "popular": int(p.get("reviewCount") or 0) > 50,
                        "url": f"https://ohou.se{purl}" if purl else f"https://ohou.se/search?q={quote(query)}",
                        "live": True,
                    })
            return results
        except Exception as e:
            print(f"오늘의집 error: {e}")
            return []
        finally:
            await page.close()


# ── Mock data for platforms we don't scrape ───────────────────────────────────

MOCK: dict[str, list[dict]] = {
    "마켓비": [
        {"name":"벨로 3단 사이드테이블",       "price":49000,  "shipping":3000,  "shipping_label":"3,000원",            "delivery_type":"standard",     "days":3, "size":400,  "popular":True  },
        {"name":"피노 원목 책상 1200",          "price":129000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":4, "size":1200, "popular":True  },
        {"name":"라움 패브릭 2인 소파",         "price":249000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":4, "size":1200, "popular":False },
        {"name":"누보 조립식 선반 5단",         "price":59000,  "shipping":3000,  "shipping_label":"3,000원",            "delivery_type":"standard",     "days":3, "size":600,  "popular":False },
    ],
    "29CM": [
        {"name":"프레임 월넛 사이드보드 1200",  "price":890000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":5, "size":1200, "popular":True  },
        {"name":"루이스 폴센 PH5 펜던트",       "price":520000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":4, "size":500,  "popular":True  },
        {"name":"무토 바이트 라운지체어",        "price":1290000,"shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":7, "size":700,  "popular":False },
        {"name":"헤이 ABC 카펫 200×140",        "price":390000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":5, "size":1400, "popular":False },
    ],
    "MUJI": [
        {"name":"스틸 유닛 선반 88cm",          "price":159000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":3, "size":880,  "popular":True  },
        {"name":"폴리프로필렌 서랍식 케이스",   "price":29900,  "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":3, "size":370,  "popular":True  },
        {"name":"비치 원목 낮은 테이블 120",    "price":189000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":4, "size":1200, "popular":False },
        {"name":"리넨 소파 2인용",              "price":499000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":5, "size":1300, "popular":False },
    ],
    "Desker": [
        {"name":"DSDR-150 모션데스크 150cm",    "price":649000, "shipping":0,     "shipping_label":"무료 전문 설치",      "delivery_type":"installation", "days":7, "size":1500, "popular":True  },
        {"name":"DCCR-100 링크 책상 100cm",     "price":289000, "shipping":0,     "shipping_label":"무료 전문 설치",      "delivery_type":"installation", "days":7, "size":1000, "popular":True  },
        {"name":"DSSR-120 단면책상 120cm",      "price":199000, "shipping":30000, "shipping_label":"30,000원 (설치포함)", "delivery_type":"installation", "days":5, "size":1200, "popular":False },
        {"name":"DCHR-01 데스크 체어",          "price":349000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":4, "size":600,  "popular":True  },
    ],
    "AliExpress": [
        {"name":"Nordic Shelf Unit 800mm",    "price":18500,  "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"slow",         "days":10, "size":800, "popular":False },
        {"name":"Minimalist Accent Chair",    "price":42000,  "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"slow",         "days":12, "size":600, "popular":False },
        {"name":"Storage Cabinet 600mm",      "price":67000,  "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"slow",         "days":10, "size":600, "popular":False },
        {"name":"Bamboo Side Table",          "price":12000,  "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"slow",         "days":14, "size":400, "popular":False },
    ],
    "Temu": [
        {"name":"접이식 수납 선반",             "price":8900,   "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"slow",         "days":7, "size":600, "popular":False },
        {"name":"플라스틱 스툴 3개 세트",       "price":6500,   "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"slow",         "days":7, "size":300, "popular":False },
        {"name":"벽걸이 선반 세트",             "price":14000,  "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"slow",         "days":9, "size":600, "popular":False },
        {"name":"서랍 수납장 900mm",            "price":22000,  "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"slow",         "days":8, "size":900, "popular":False },
    ],
    "Hanssem": [
        {"name":"에뚜알 4단 책장 900",          "price":285000, "shipping":30000, "shipping_label":"30,000원 (설치포함)", "delivery_type":"installation", "days":5, "size":900,  "popular":True  },
        {"name":"리베 패브릭 3인 소파",         "price":890000, "shipping":0,     "shipping_label":"무료 전문 설치",      "delivery_type":"installation", "days":7, "size":1200, "popular":True  },
        {"name":"모노 원목 다이닝테이블 1200",  "price":420000, "shipping":0,     "shipping_label":"무료 전문 설치",      "delivery_type":"installation", "days":7, "size":1200, "popular":False },
        {"name":"파로 다이닝 체어",             "price":195000, "shipping":0,     "shipping_label":"무료배송",            "delivery_type":"standard",     "days":5, "size":500,  "popular":False },
    ],
    "IKEA": [
        {"name":"BILLY 책장 80×202cm",         "price":129000, "shipping":0, "shipping_label":"무료배송", "delivery_type":"standard", "days":2, "size":800,  "popular":False },
        {"name":"KALLAX 선반 유닛 77×77cm",    "price":89000,  "shipping":0, "shipping_label":"무료배송", "delivery_type":"standard", "days":2, "size":770,  "popular":True  },
        {"name":"POANG 암체어",                 "price":179000, "shipping":0, "shipping_label":"무료배송", "delivery_type":"standard", "days":2, "size":600,  "popular":True  },
        {"name":"LACK 사이드테이블 55cm",       "price":35000,  "shipping":0, "shipping_label":"무료배송", "delivery_type":"standard", "days":2, "size":550,  "popular":False },
    ],
    "오늘의집": [
        {"name":"모던 패브릭 소파 2인용",       "price":389000, "shipping":3000, "shipping_label":"3,000원", "delivery_type":"standard", "days":3, "size":1200, "popular":True  },
        {"name":"원목 커피테이블 900mm",        "price":159000, "shipping":3000, "shipping_label":"3,000원", "delivery_type":"standard", "days":3, "size":900,  "popular":True  },
        {"name":"스칸디 패브릭 1인 암체어",     "price":219000, "shipping":3000, "shipping_label":"3,000원", "delivery_type":"standard", "days":4, "size":600,  "popular":False },
        {"name":"화이트 1200 책상",             "price":129000, "shipping":0,    "shipping_label":"무료배송","delivery_type":"standard", "days":3, "size":1200, "popular":True  },
    ],
    "Coupang": [
        {"name":"조립식 책장 5단 600mm",        "price":39900,  "shipping":0, "shipping_label":"무료배송 (로켓)", "delivery_type":"express", "days":1, "size":600,  "popular":True  },
        {"name":"접이식 다목적 테이블 900",     "price":29900,  "shipping":0, "shipping_label":"무료배송 (로켓)", "delivery_type":"express", "days":1, "size":900,  "popular":False },
        {"name":"1인 소파베드",                 "price":89000,  "shipping":0, "shipping_label":"무료배송 (로켓)", "delivery_type":"express", "days":1, "size":900,  "popular":True  },
        {"name":"북유럽 스타일 협탁",           "price":25000,  "shipping":3000, "shipping_label":"3,000원", "delivery_type":"standard", "days":2, "size":400,  "popular":False },
    ],
}


PLATFORM_SEARCH_URLS = {
    "IKEA":       "https://www.ikea.com/kr/ko/search/products/?q=",
    "오늘의집":   "https://ohou.se/search?q=",
    "Coupang":    "https://www.coupang.com/np/search?q=",
    "마켓비":     "https://www.marketb.kr/search?query=",
    "29CM":       "https://www.29cm.co.kr/search?q=",
    "MUJI":       "https://www.muji.com/kr/search?keyword=",
    "Desker":     "https://desker.co.kr/search?q=",
    "AliExpress": "https://www.aliexpress.com/wholesale?SearchText=",
    "Temu":       "https://www.temu.com/search_result.html?search_key=",
    "Hanssem":    "https://www.hanssem.com/search?q=",
}

def mock_for(platform: str, query: str = "") -> list[dict]:
    base = PLATFORM_SEARCH_URLS.get(platform, "https://www.google.com/search?q=")
    search_url = affiliate_url(base + quote(query or platform), platform)
    return [
        {**p, "platform": platform, "url": search_url, "live": False}
        for p in MOCK.get(platform, [])
    ]


# ── API endpoint ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/search")
async def search(q: str = ""):
    if not q.strip():
        return {"error": "q parameter required", "results": []}

    # Run live scrapers with 10s timeout each
    ikea_task    = asyncio.create_task(search_ikea(q))
    coupang_task = asyncio.create_task(search_coupang(q))
    ohou_task    = asyncio.create_task(search_ohou(q))

    try:
        ikea_res    = await asyncio.wait_for(ikea_task,    timeout=10)
    except Exception:
        ikea_res = []
    try:
        coupang_res = await asyncio.wait_for(coupang_task, timeout=10)
    except Exception:
        coupang_res = []
    try:
        ohou_res    = await asyncio.wait_for(ohou_task,    timeout=10)
    except Exception:
        ohou_res = []

    results = [
        *(ikea_res    or mock_for("IKEA",    q)),
        *(ohou_res    or mock_for("오늘의집", q)),
        *(coupang_res or mock_for("Coupang", q)),
        *mock_for("마켓비",    q),
        *mock_for("29CM",      q),
        *mock_for("MUJI",      q),
        *mock_for("Desker",    q),
        *mock_for("AliExpress",q),
        *mock_for("Temu",      q),
        *mock_for("Hanssem",   q),
    ]

    return {"results": results, "query": q}
