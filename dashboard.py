"""
Pinter-Match AI — Interior Sourcing Platform
Pinterest/Magazine aesthetic · Zero-API cost · Playwright headless
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import csv
import io
from pathlib import Path
from typing import Optional

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import scraper as sc

try:
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit Cloud bootstrap
# Playwright browser binaries are NOT pre-installed on Streamlit Cloud.
# This runs `playwright install chromium` exactly once per container lifetime
# via @st.cache_resource (result is cached — never runs twice in the same pod).
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _bootstrap_playwright() -> bool:
    """Install Chromium binary if missing. Cached — runs once per container."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Non-fatal: scraper will show a user-friendly error when called
        st.warning(
            f"Playwright browser install warning: {result.stderr[:200]}",
            icon="⚠️",
        )
        return False
    return True

# ─────────────────────────────────────────────────────────────────────────────
# Page config  (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Pinter-Match AI",
    page_icon="📌",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────────────────────
# Design tokens
# ─────────────────────────────────────────────────────────────────────────────
TIER_META = {
    "A": {"label": "Direct / Fast",   "color": "#00B894", "bg": "#E8FAF5", "icon": "⚡"},
    "B": {"label": "DIY / Assembly",  "color": "#FDCB6E", "bg": "#FFF9EC", "icon": "🔧"},
    "C": {"label": "Budget / Risk",   "color": "#FF7675", "bg": "#FFF0F0", "icon": "⚠️"},
}

SOURCE_META = {
    "ikea":        {"color": "#0058A3", "text": "#FFDA1A", "icon": "🇸🇪", "label": "IKEA"},
    "ohou":        {"color": "#00B894", "text": "#fff",    "icon": "🏠", "label": "오늘의집"},
    "aliexpress":  {"color": "#E84142", "text": "#fff",    "icon": "🌏", "label": "AliExpress"},
    "temu":        {"color": "#F47500", "text": "#fff",    "icon": "📦", "label": "Temu"},
}

GRADIENT_BG = {
    "ikea":       "linear-gradient(140deg, #003087 0%, #0058A3 60%, #1976D2 100%)",
    "ohou":       "linear-gradient(140deg, #00796B 0%, #00B894 60%, #55EFC4 100%)",
    "aliexpress": "linear-gradient(140deg, #B71C1C 0%, #E84142 60%, #FF8A80 100%)",
    "temu":       "linear-gradient(140deg, #E65100 0%, #F47500 60%, #FFCC02 100%)",
}

SOURCE_DOMAINS = {
    "ikea.com": "ikea",
    "ohou.se": "ohou",
    "aliexpress.com": "aliexpress",
    "temu.com": "temu",
    "pinterest.com": "pinterest",
    "pin.it": "pinterest",
}

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────────────────────────────────────
def inject_css():
    st.markdown("""
    <style>
    /* ── Google Fonts ── */
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');

    /* ── Reset & base ── */
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
        background-color: #F8F9FA;
    }
    .main .block-container { padding: 0 2rem 3rem; max-width: 1400px; }

    /* ── Hide Streamlit chrome ── */
    #MainMenu, footer, header { visibility: hidden; }
    [data-testid="stSidebar"] { display: none; }
    button[kind="header"] { display: none; }

    /* ════════════════════════════════════════
       NAVBAR
    ════════════════════════════════════════ */
    .pm-navbar {
        background: #fff;
        border-bottom: 1px solid #EBEBEB;
        padding: 0 2rem;
        height: 64px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        position: sticky;
        top: 0;
        z-index: 100;
        margin: 0 -2rem 2rem;
        box-shadow: 0 1px 8px rgba(0,0,0,0.04);
    }
    .pm-logo {
        font-family: 'Playfair Display', serif;
        font-size: 1.45rem;
        font-weight: 700;
        color: #1A1A2E;
        letter-spacing: -0.02em;
    }
    .pm-logo span { color: #E60023; }
    .pm-tagline {
        font-size: 0.78rem;
        color: #9CA3AF;
        font-weight: 400;
        letter-spacing: 0.04em;
    }
    .pm-badge {
        background: #FFF0F0;
        color: #E60023;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        padding: 0.2rem 0.6rem;
        border-radius: 9999px;
        border: 1px solid #FFD0D0;
    }

    /* ════════════════════════════════════════
       SEARCH / INPUT SECTION
    ════════════════════════════════════════ */
    .search-section {
        background: #fff;
        border-radius: 20px;
        padding: 2rem 2.5rem;
        margin-bottom: 1.5rem;
        border: 1px solid #EBEBEB;
        box-shadow: 0 2px 16px rgba(0,0,0,0.04);
    }
    .search-title {
        font-size: 1rem;
        font-weight: 600;
        color: #1A1A2E;
        margin-bottom: 0.3rem;
    }
    .search-hint {
        font-size: 0.78rem;
        color: #9CA3AF;
        margin-bottom: 1rem;
    }

    /* ════════════════════════════════════════
       KPI STRIP
    ════════════════════════════════════════ */
    .kpi-strip {
        display: flex;
        gap: 1rem;
        margin-bottom: 1.75rem;
        flex-wrap: wrap;
    }
    .kpi-pill {
        background: #fff;
        border: 1px solid #EBEBEB;
        border-radius: 14px;
        padding: 0.9rem 1.4rem;
        flex: 1;
        min-width: 160px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.03);
    }
    .kpi-pill .kl { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.09em; color: #9CA3AF; font-weight: 600; margin-bottom: 0.3rem; }
    .kpi-pill .kv { font-size: 1.35rem; font-weight: 700; color: #1A1A2E; line-height: 1.1; }
    .kpi-pill .ks { font-size: 0.72rem; color: #9CA3AF; margin-top: 0.2rem; }
    .kpi-pill.accent-green { border-color: #D1FAE5; }
    .kpi-pill.accent-green .kv { color: #059669; }
    .kpi-pill.accent-blue  { border-color: #DBEAFE; }
    .kpi-pill.accent-blue  .kv { color: #2563EB; }
    .kpi-pill.accent-amber { border-color: #FEF3C7; }
    .kpi-pill.accent-amber .kv { color: #D97706; }
    .kpi-pill.accent-red   { border-color: #FFE4E6; }
    .kpi-pill.accent-red   .kv { color: #E11D48; }

    /* ════════════════════════════════════════
       MASONRY COLUMN LAYOUT
       Actual columns provided by st.columns(3);
       these rules ensure cards stack flush with
       no extra padding and equal column width.
    ════════════════════════════════════════ */
    .masonry-col { display: flex; flex-direction: column; gap: 0; }
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        padding: 0 0.5rem !important;
    }

    /* ════════════════════════════════════════
       SECTION HEADER
    ════════════════════════════════════════ */
    .section-hdr {
        display: flex;
        align-items: baseline;
        gap: 0.6rem;
        margin-bottom: 1.25rem;
    }
    .section-hdr h2 {
        font-family: 'Playfair Display', serif;
        font-size: 1.4rem;
        font-weight: 700;
        color: #1A1A2E;
        margin: 0;
    }
    .section-hdr .count {
        font-size: 0.75rem;
        color: #9CA3AF;
        background: #F3F4F6;
        padding: 0.15rem 0.5rem;
        border-radius: 9999px;
    }

    /* ════════════════════════════════════════
       PRODUCT CARD
    ════════════════════════════════════════ */
    .pm-card {
        background: #fff;
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid #F0F0F0;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 1.25rem;
        transition: box-shadow 0.2s ease, transform 0.2s ease;
        position: relative;
    }
    .pm-card:hover {
        box-shadow: 0 12px 32px rgba(0,0,0,0.12);
        transform: translateY(-2px);
    }
    .pm-card.winner-card {
        border: 2px solid #059669;
        box-shadow: 0 4px 20px rgba(5,150,105,0.15);
    }

    /* Image / gradient hero */
    .card-hero {
        width: 100%;
        height: 160px;
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
        overflow: hidden;
    }
    .card-hero img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    .card-hero .hero-placeholder {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 2.5rem;
    }

    /* Winner crown */
    .winner-crown {
        position: absolute;
        top: 10px;
        left: 10px;
        background: #059669;
        color: #fff;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
    }

    /* Source badge — top-right of hero */
    .hero-source-badge {
        position: absolute;
        top: 10px;
        right: 10px;
        font-size: 0.62rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.25rem 0.65rem;
        border-radius: 9999px;
    }

    /* Card body */
    .card-body {
        padding: 1.1rem 1.2rem 0.9rem;
    }
    .card-body .product-name {
        font-weight: 600;
        font-size: 0.95rem;
        color: #1A1A2E;
        margin: 0 0 0.4rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.35;
    }
    .card-body .dim-chip {
        display: inline-block;
        font-size: 0.7rem;
        color: #6B7280;
        background: #F3F4F6;
        border-radius: 6px;
        padding: 0.18rem 0.55rem;
        margin-bottom: 0.75rem;
        font-family: 'Courier New', monospace;
    }
    .card-body .tco-price {
        font-size: 1.55rem;
        font-weight: 700;
        color: #1A1A2E;
        letter-spacing: -0.03em;
        line-height: 1;
        margin-bottom: 0.2rem;
    }
    .card-body .tco-label {
        font-size: 0.68rem;
        color: #9CA3AF;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        margin-bottom: 0.75rem;
    }

    /* Price breakdown — visible on hover via CSS */
    .breakdown-wrap {
        overflow: hidden;
        max-height: 0;
        transition: max-height 0.3s ease;
    }
    .pm-card:hover .breakdown-wrap {
        max-height: 120px;
    }
    .breakdown-rows {
        border-top: 1px solid #F3F4F6;
        padding-top: 0.6rem;
        margin-bottom: 0.6rem;
    }
    .breakdown-row {
        display: flex;
        justify-content: space-between;
        font-size: 0.75rem;
        color: #6B7280;
        padding: 0.18rem 0;
    }
    .breakdown-row.total-row {
        color: #1A1A2E;
        font-weight: 600;
        border-top: 1px solid #EBEBEB;
        padding-top: 0.35rem;
        margin-top: 0.2rem;
    }

    /* Card footer */
    .card-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.65rem 1.2rem 1rem;
        border-top: 1px solid #F9F9F9;
        gap: 0.5rem;
    }
    .tier-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        font-size: 0.68rem;
        font-weight: 600;
        padding: 0.25rem 0.65rem;
        border-radius: 9999px;
        white-space: nowrap;
    }

    /* ── Risk banner ── */
    .risk-strip {
        font-size: 0.72rem;
        padding: 0.4rem 1.2rem;
        font-weight: 500;
    }
    .risk-high   { background: #FFF0F0; color: #E11D48; }
    .risk-medium { background: #FFFBEB; color: #D97706; }
    .risk-low    { background: #ECFDF5; color: #059669; }

    /* Design tags */
    .tag-row { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.5rem 1.2rem 0; }
    .tag-pill {
        font-size: 0.64rem;
        background: #F3F4F6;
        color: #6B7280;
        border-radius: 9999px;
        padding: 0.15rem 0.5rem;
    }

    /* ── Buy button ── */
    .buy-btn {
        display: inline-block;
        background: #1A1A2E;
        color: #fff !important;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        padding: 0.45rem 1.1rem;
        border-radius: 9999px;
        text-decoration: none !important;
        white-space: nowrap;
        transition: background 0.15s ease, transform 0.15s ease;
    }
    .buy-btn:hover {
        background: #E60023;
        transform: scale(1.03);
    }

    /* ════════════════════════════════════════
       PINTEREST PANEL
    ════════════════════════════════════════ */
    .pinterest-panel {
        background: #fff;
        border-radius: 16px;
        border: 1px solid #FFD0D0;
        overflow: hidden;
        margin-top: 1.5rem;
    }
    .pinterest-header {
        background: linear-gradient(135deg, #E60023 0%, #AD081B 100%);
        padding: 1rem 1.5rem;
        color: #fff;
    }
    .pinterest-header h3 { font-size: 1rem; font-weight: 700; margin: 0; }
    .pinterest-header p  { font-size: 0.78rem; margin: 0.2rem 0 0; opacity: 0.85; }
    .pinterest-body { padding: 1.25rem 1.5rem; }

    /* ════════════════════════════════════════
       EMPTY STATE
    ════════════════════════════════════════ */
    .empty-state {
        text-align: center;
        padding: 5rem 2rem 4rem;
        background: #fff;
        border-radius: 20px;
        border: 1px dashed #DDDEE0;
        margin-top: 1rem;
    }
    .empty-state .icon { font-size: 3.5rem; margin-bottom: 1rem; }
    .empty-state h3 { font-family: 'Playfair Display', serif; font-size: 1.4rem; color: #1A1A2E; margin-bottom: 0.5rem; }
    .empty-state p { color: #9CA3AF; font-size: 0.88rem; max-width: 360px; margin: 0 auto 1.5rem; }

    /* Source chips in empty state */
    .source-chips { display: flex; justify-content: center; gap: 0.5rem; flex-wrap: wrap; margin-top: 1rem; }
    .source-chip {
        font-size: 0.72rem; font-weight: 600;
        padding: 0.3rem 0.9rem; border-radius: 9999px;
        border: 1px solid #EBEBEB; color: #6B7280;
    }

    /* ════════════════════════════════════════
       SORT / FILTER BAR
    ════════════════════════════════════════ */
    .filter-bar {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin-bottom: 1rem;
        flex-wrap: wrap;
    }
    .filter-label { font-size: 0.75rem; color: #9CA3AF; font-weight: 500; }

    /* ════════════════════════════════════════
       EXPORT ROW
    ════════════════════════════════════════ */
    .export-row { display: flex; gap: 0.75rem; margin-top: 1.5rem; }

    /* ════════════════════════════════════════
       STREAMLIT WIDGET OVERRIDES
    ════════════════════════════════════════ */
    /* Text area */
    .stTextArea textarea {
        border-radius: 12px !important;
        border: 1.5px solid #EBEBEB !important;
        font-size: 0.84rem !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        padding: 0.75rem 1rem !important;
        background: #FAFAFA !important;
        resize: vertical;
    }
    .stTextArea textarea:focus {
        border-color: #1A1A2E !important;
        background: #fff !important;
        box-shadow: 0 0 0 3px rgba(26,26,46,0.06) !important;
    }
    /* Primary button */
    .stButton > button[kind="primary"] {
        background: #1A1A2E !important;
        color: #fff !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
        font-size: 0.88rem !important;
        padding: 0.65rem 2rem !important;
        border: none !important;
        transition: background 0.15s !important;
        letter-spacing: 0.02em;
    }
    .stButton > button[kind="primary"]:hover {
        background: #E60023 !important;
    }
    /* Secondary button */
    .stButton > button:not([kind="primary"]) {
        border-radius: 10px !important;
        font-size: 0.82rem !important;
        border: 1.5px solid #EBEBEB !important;
        color: #6B7280 !important;
        background: #fff !important;
    }
    /* Link button */
    .stLinkButton a {
        border-radius: 10px !important;
        font-size: 0.82rem !important;
        font-weight: 500 !important;
    }
    /* Selectbox */
    .stSelectbox > div > div {
        border-radius: 10px !important;
        border: 1.5px solid #EBEBEB !important;
        font-size: 0.82rem !important;
    }
    /* Progress bar */
    .stProgress > div > div { border-radius: 9999px !important; }
    .stProgress > div > div > div { background: #1A1A2E !important; border-radius: 9999px !important; }
    /* Expander */
    .streamlit-expanderHeader {
        font-size: 0.82rem !important;
        font-weight: 500 !important;
        color: #6B7280 !important;
    }
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.25rem;
        background: transparent;
        border-bottom: 2px solid #F0F0F0;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        font-size: 0.83rem;
        font-weight: 500;
        padding: 0.5rem 1.2rem;
        color: #9CA3AF;
    }
    .stTabs [aria-selected="true"] {
        color: #1A1A2E !important;
        font-weight: 600 !important;
    }
    /* Columns gap */
    [data-testid="column"] { padding: 0 0.4rem !important; }
    </style>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Async bridge: isolated event loop in a worker thread
# ─────────────────────────────────────────────────────────────────────────────
def _run_in_thread(coro, timeout: int = 180):
    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_worker).result(timeout=timeout)


# ─────────────────────────────────────────────────────────────────────────────
# URL utilities
# ─────────────────────────────────────────────────────────────────────────────
def detect_source(url: str) -> str:
    for domain, src in SOURCE_DOMAINS.items():
        if domain in url.lower():
            return src
    return "unknown"


def classify_urls(raw_lines: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Returns (source_groups, pinterest_urls)."""
    groups: dict[str, list[str]] = {}
    pinterest: list[str] = []
    for line in raw_lines:
        u = line.strip()
        if not u or not u.startswith("http"):
            continue
        src = detect_source(u)
        if src == "pinterest":
            pinterest.append(u)
        elif src != "unknown":
            groups.setdefault(src, []).append(u)
    return groups, pinterest


# ─────────────────────────────────────────────────────────────────────────────
# Scraping orchestrator with per-URL progress
# ─────────────────────────────────────────────────────────────────────────────
def scrape_with_progress(
    url_groups: dict[str, list[str]],
) -> tuple[list[sc.Product], list[str]]:
    products: list[sc.Product] = []
    errors: list[str] = []

    all_urls = [
        (src, url) for src, urls in url_groups.items() for url in urls
    ]
    if not all_urls:
        return [], []

    bar  = st.progress(0.0)
    stat = st.empty()

    for i, (src, url) in enumerate(all_urls):
        short = url[:52] + "…" if len(url) > 52 else url
        bar.progress(i / len(all_urls), text=f"Fetching {src.upper()} ({i+1}/{len(all_urls)})")
        stat.markdown(
            f"<p style='font-size:0.78rem;color:#9CA3AF;margin:0'>⏳ {short}</p>",
            unsafe_allow_html=True,
        )
        try:
            result = _run_in_thread(sc.analyze({src: url}))
            products.extend(result)
        except Exception as exc:
            errors.append(f"{src} · {short} → {exc}")

    bar.progress(1.0, text="Analysis complete")
    stat.empty()
    return products, errors


def run_pinterest_lookup(url: str) -> dict:
    async def _go():
        from playwright.async_api import async_playwright  # type: ignore
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(locale="ko-KR")
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            result = await sc.pinterest_to_product(url, ctx)
            await browser.close()
        return result
    return _run_in_thread(_go())


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────
def fmt(value: Optional[float], na: str = "—") -> str:
    return f"₩{value:,.0f}" if value is not None else na


def risk_level(p: sc.Product) -> tuple[str, str]:
    kws = p.review_keywords
    neg = {"fragile", "cheap", "poor", "broken", "bad"}
    pos = {"sturdy", "quality", "worth", "만족", "튼튼", "가성비"}
    neg_hits = [k for k in kws if k in neg]
    pos_hits = [k for k in kws if k in pos]
    if neg_hits:
        return "high",   f"🚨 Negative signals: {', '.join(neg_hits)}"
    if len(pos_hits) >= 2:
        return "low",    f"✅ Positive signals: {', '.join(pos_hits)}"
    if kws:
        return "medium", f"⚠️ Mixed signals — verify before ordering"
    return "medium",     "⚠️ Insufficient review data — exercise caution"


# ─────────────────────────────────────────────────────────────────────────────
# Navbar
# ─────────────────────────────────────────────────────────────────────────────
def render_navbar():
    st.markdown("""
    <div class="pm-navbar">
        <div style="display:flex;align-items:center;gap:0.75rem">
            <div class="pm-logo">📌 Pinter<span>-Match</span> AI</div>
            <span class="pm-badge">BETA</span>
        </div>
        <div class="pm-tagline">Interior Sourcing · TCO Analysis · Zero-API Cost</div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# URL input section
# ─────────────────────────────────────────────────────────────────────────────
def render_input_section() -> tuple[list[str], bool]:
    st.markdown("""
    <div class="search-section">
        <div class="search-title">🔍 Paste Product URLs</div>
        <div class="search-hint">One URL per line · Supports IKEA · 오늘의집 · AliExpress · Temu · Pinterest pins</div>
    </div>
    """, unsafe_allow_html=True)

    col_input, col_config = st.columns([3, 1], gap="medium")

    with col_input:
        raw = st.text_area(
            "urls",
            placeholder=(
                "https://www.ikea.com/kr/ko/p/kallax-...\n"
                "https://ohou.se/productions/view/...\n"
                "https://www.aliexpress.com/item/...\n"
                "https://www.pinterest.com/pin/..."
            ),
            height=130,
            label_visibility="collapsed",
        )

    with col_config:
        st.markdown("<p style='font-size:0.75rem;font-weight:600;color:#6B7280;margin-bottom:0.5rem'>AFFILIATE IDs</p>", unsafe_allow_html=True)
        with st.expander("Configure →", expanded=False):
            sc.AFFILIATE_CONFIG["ikea"]["id"]        = st.text_input("IKEA",        sc.AFFILIATE_CONFIG["ikea"]["id"],        key="aff_ikea")
            sc.AFFILIATE_CONFIG["ohou"]["id"]        = st.text_input("오늘의집",     sc.AFFILIATE_CONFIG["ohou"]["id"],        key="aff_ohou")
            sc.AFFILIATE_CONFIG["aliexpress"]["id"]  = st.text_input("AliExpress",  sc.AFFILIATE_CONFIG["aliexpress"]["id"],  key="aff_ali")
            sc.AFFILIATE_CONFIG["temu"]["id"]        = st.text_input("Temu",        sc.AFFILIATE_CONFIG["temu"]["id"],        key="aff_temu")

    _, col_btn, _ = st.columns([2, 1, 2])
    with col_btn:
        clicked = st.button("Analyze →", type="primary", use_container_width=True)

    raw_lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    return raw_lines, clicked


# ─────────────────────────────────────────────────────────────────────────────
# KPI strip
# ─────────────────────────────────────────────────────────────────────────────
def render_kpi_strip(products: list[sc.Product]):
    priced = [p for p in products if p.price_krw]
    if not priced:
        return

    cheapest = min(priced, key=lambda p: p.tco)
    fastest  = next((p for p in priced if p.source in ("ohou", "coupang")), cheapest)
    hidden   = sum((p.shipping_fee or 0) + (p.assembly_fee or 0) for p in priced)
    sources  = len({p.source for p in priced})

    def pill(label, value, sub, cls=""):
        return f"""
        <div class="kpi-pill {cls}">
            <div class="kl">{label}</div>
            <div class="kv">{value}</div>
            <div class="ks">{sub}</div>
        </div>"""

    html = '<div class="kpi-strip">'
    html += pill("💰 Lowest TCO",       fmt(cheapest.tco),   (cheapest.name or cheapest.source.upper())[:28], "accent-green")
    html += pill("⚡ Fastest Delivery", fastest.source.upper(), (fastest.name or "—")[:28],                   "accent-blue")
    html += pill("📦 Items Analyzed",   str(len(priced)),    f"across {sources} source{'s' if sources > 1 else ''}",     "accent-amber")
    html += pill("🔍 Hidden Costs",     fmt(hidden),         "shipping + assembly total",                      "accent-red")
    html += "</div>"

    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Individual product card (pure HTML — includes buy button as <a>)
# ─────────────────────────────────────────────────────────────────────────────
def _card_html(p: sc.Product, rank: int, is_winner: bool) -> str:
    aff_url  = sc.generate_affiliate_url(p)
    p.affiliate_url = aff_url

    src_meta  = SOURCE_META.get(p.source, {"color": "#6B7280", "text": "#fff", "icon": "📦", "label": p.source.upper()})
    tier_ltr  = p.convenience_tier[0]
    tier_meta = TIER_META.get(tier_ltr, {"label": "Unknown", "color": "#6B7280", "bg": "#F3F4F6", "icon": ""})
    gradient  = GRADIENT_BG.get(p.source, "linear-gradient(140deg,#6B7280,#9CA3AF)")

    winner_crown = '<div class="winner-crown">🏆 Best Value</div>' if is_winner else ""

    # Hero: use scraped image if available, otherwise gradient placeholder
    if p.image_url:
        hero_content = f'<img src="{p.image_url}" alt="{p.name}" loading="lazy">'
    else:
        hero_content = f'<div class="hero-placeholder" style="background:{gradient}">{src_meta["icon"]}</div>'

    # Dimension chip
    dim_chip = ""
    dim_str  = str(p.dimensions)
    if dim_str and dim_str != "N/A":
        dim_chip = f'<span class="dim-chip">{dim_str}</span><br>'

    # Design tags (max 4)
    tags_html = ""
    if p.design_tags:
        tags = "".join(f'<span class="tag-pill">{t}</span>' for t in p.design_tags[:4])
        tags_html = f'<div class="tag-row">{tags}</div>'

    # Price breakdown rows
    breakdown = f"""
    <div class="breakdown-wrap">
      <div class="breakdown-rows">
        <div class="breakdown-row"><span>Base price</span><span>{fmt(p.price_krw, '—')}</span></div>
        <div class="breakdown-row"><span>Shipping</span><span>{fmt(p.shipping_fee, 'Free')}</span></div>
        <div class="breakdown-row"><span>Assembly</span><span>{fmt(p.assembly_fee, 'None')}</span></div>
        <div class="breakdown-row total-row"><span>Total TCO</span><span>{fmt(p.tco)}</span></div>
      </div>
    </div>"""

    # Risk strip (overseas only)
    risk_strip = ""
    if p.source in ("aliexpress", "temu"):
        lvl, msg = risk_level(p)
        risk_strip = f'<div class="risk-strip risk-{lvl}">{msg}</div>'

    # Tier badge
    tier_badge = (
        f'<span class="tier-badge" '
        f'style="background:{tier_meta["bg"]};color:{tier_meta["color"]}">'
        f'{tier_meta["icon"]} Tier {tier_ltr} · {tier_meta["label"]}'
        f'</span>'
    )

    # Source badge
    src_badge = (
        f'<span class="hero-source-badge" '
        f'style="background:{src_meta["color"]};color:{src_meta["text"]}">'
        f'{src_meta["label"]}</span>'
    )

    winner_cls = "winner-card" if is_winner else ""

    return f"""
<div class="pm-card {winner_cls}">
  <div class="card-hero">
    {hero_content}
    {winner_crown}
    {src_badge}
  </div>
  {tags_html}
  <div class="card-body">
    <p class="product-name">{p.name or "Unknown Product"}</p>
    {dim_chip}
    <div class="tco-price">{fmt(p.tco)}</div>
    <div class="tco-label">Total Cost of Ownership</div>
    {breakdown}
  </div>
  {risk_strip}
  <div class="card-footer">
    {tier_badge}
    <a class="buy-btn" href="{aff_url}" target="_blank" rel="noopener">Buy Now →</a>
  </div>
</div>"""


# ─────────────────────────────────────────────────────────────────────────────
# Masonry grid (3-column round-robin, CSS-styled cards)
# ─────────────────────────────────────────────────────────────────────────────
def render_masonry_grid(products: list[sc.Product], sort_key: str = "tco"):
    sort_fns = {
        "tco":   lambda p: p.tco,
        "price": lambda p: p.price_krw or 0,
        "name":  lambda p: p.name.lower(),
    }
    sorted_prods = sorted(
        [p for p in products if p.price_krw],
        key=sort_fns.get(sort_key, sort_fns["tco"]),
    )

    n = len(sorted_prods)
    st.markdown(
        f'<div class="section-hdr"><h2>Results</h2><span class="count">{n} item{"s" if n != 1 else ""}</span></div>',
        unsafe_allow_html=True,
    )

    # Sort / filter controls
    _, col_sort, col_filter, _ = st.columns([2, 1, 1, 2])
    with col_sort:
        new_sort = st.selectbox(
            "Sort by",
            ["tco", "price", "name"],
            format_func={"tco": "Total TCO", "price": "Base Price", "name": "Name"}.get,
            index=["tco", "price", "name"].index(sort_key),
            key="sort_select",
            label_visibility="collapsed",
        )
        if new_sort != sort_key:
            st.session_state["sort_key"] = new_sort
            st.rerun()
    with col_filter:
        sources = sorted({p.source for p in products if p.price_krw})
        source_filter = st.selectbox(
            "Filter",
            ["All"] + sources,
            key="source_filter",
            label_visibility="collapsed",
        )

    if source_filter != "All":
        sorted_prods = [p for p in sorted_prods if p.source == source_filter]

    if not sorted_prods:
        st.info("No products match the selected filter.")
        return

    # 3-column masonry
    c1, c2, c3 = st.columns(3, gap="medium")
    cols = [c1, c2, c3]
    for i, prod in enumerate(sorted_prods):
        with cols[i % 3]:
            st.markdown(_card_html(prod, i + 1, is_winner=(i == 0)), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TCO breakdown chart (tab view)
# ─────────────────────────────────────────────────────────────────────────────
def render_tco_chart(products: list[sc.Product]):
    priced = sorted([p for p in products if p.price_krw], key=lambda p: p.tco)
    if not priced:
        return

    names = [
        ((p.name or p.source.upper())[:22] + "…" if len(p.name or "") > 22 else (p.name or p.source.upper()))
        for p in priced
    ]

    if _PLOTLY:
        fig = go.Figure(data=[
            go.Bar(name="Base Price",  x=names, y=[p.price_krw or 0 for p in priced],    marker_color="#1A1A2E"),
            go.Bar(name="Shipping",    x=names, y=[p.shipping_fee or 0 for p in priced], marker_color="#00B894"),
            go.Bar(name="Assembly",    x=names, y=[p.assembly_fee or 0 for p in priced], marker_color="#FDCB6E"),
        ])
        fig.update_layout(
            barmode="stack",
            plot_bgcolor="#fff",
            paper_bgcolor="#fff",
            font=dict(family="Plus Jakarta Sans", color="#6B7280", size=11),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                        font=dict(size=11)),
            margin=dict(l=0, r=0, t=30, b=0),
            xaxis=dict(gridcolor="#F3F4F6", linecolor="#F3F4F6"),
            yaxis=dict(gridcolor="#F3F4F6", tickprefix="₩", tickformat=",", linecolor="#F3F4F6"),
            height=340,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        import pandas as pd
        df = pd.DataFrame(
            {"Base": [p.price_krw or 0 for p in priced],
             "Shipping": [p.shipping_fee or 0 for p in priced],
             "Assembly": [p.assembly_fee or 0 for p in priced]},
            index=names,
        )
        st.bar_chart(df)

    # Tier legend
    st.markdown("<br>", unsafe_allow_html=True)
    ta, tb, tc = st.columns(3)
    for col, (ltr, meta) in zip([ta, tb, tc], TIER_META.items()):
        col.markdown(
            f"""<div style="background:{meta['bg']};border-radius:12px;padding:0.9rem 1rem;
                border-left:3px solid {meta['color']}">
                <p style="font-size:0.72rem;font-weight:700;color:{meta['color']};margin:0 0 0.2rem;text-transform:uppercase;letter-spacing:0.07em">
                    {meta['icon']} Tier {ltr}</p>
                <p style="font-size:0.8rem;color:#6B7280;margin:0">{meta['label']}</p>
            </div>""",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pinterest reverse-image panel
# ─────────────────────────────────────────────────────────────────────────────
def render_pinterest_panel(pinterest_urls: list[str]):
    for pin_url in pinterest_urls:
        with st.spinner(f"Extracting image from {pin_url[:50]}…"):
            result = run_pinterest_lookup(pin_url)

        st.markdown("""
        <div class="pinterest-panel">
            <div class="pinterest-header">
                <h3>📌 Pinterest Reverse-Image Match</h3>
                <p>Image extracted · Use Google Lens to find matching products</p>
            </div>
        </div>""", unsafe_allow_html=True)

        if "error" in result:
            st.error(f"Extraction failed: {result['error']}")
            continue

        col_img, col_actions = st.columns([1, 2], gap="large")
        with col_img:
            if result.get("image_url"):
                st.image(result["image_url"], use_container_width=True)

        with col_actions:
            st.markdown("<p style='font-weight:600;font-size:0.9rem;margin-bottom:0.75rem'>Find this product:</p>", unsafe_allow_html=True)
            st.link_button("🔍 Open in Google Lens",   result["google_lens_url"],   use_container_width=True)
            st.link_button("🖼️ Google Images Search",  result["google_images_url"], use_container_width=True)
            st.markdown("""
            <div style="background:#FFF9EC;border-radius:10px;padding:0.75rem 1rem;
                        border-left:3px solid #FDCB6E;margin-top:0.75rem;font-size:0.78rem;color:#92400E">
                <b>Next step:</b> Copy a product URL from Google Lens results,
                paste it in the URL box above, and click Analyze.
            </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Export buttons
# ─────────────────────────────────────────────────────────────────────────────
def render_export(products: list[sc.Product]):
    st.markdown("---")
    col_j, col_c, _ = st.columns([1, 1, 4])

    with col_j:
        data = json.dumps([p.to_dict() for p in products], ensure_ascii=False, indent=2).encode()
        st.download_button("⬇️ Export JSON", data=data, file_name="pintermatch_report.json", mime="application/json", use_container_width=True)

    with col_c:
        buf = io.StringIO()
        fields = ["name", "source", "price_krw", "shipping_fee", "assembly_fee", "tco",
                  "convenience_tier", "affiliate_url", "url"]
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in products:
            row = {**p.to_dict(), "tco": p.tco, "convenience_tier": p.convenience_tier}
            writer.writerow({k: row.get(k, "") for k in fields})
        st.download_button("⬇️ Export CSV", data=buf.getvalue().encode(), file_name="pintermatch_report.csv", mime="text/csv", use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Empty state
# ─────────────────────────────────────────────────────────────────────────────
def render_empty_state():
    st.markdown("""
    <div class="empty-state">
        <div class="icon">📌</div>
        <h3>Find Your Perfect Furniture Match</h3>
        <p>Paste product URLs from IKEA, 오늘의집, AliExpress, or Temu above.
           We'll calculate the true Total Cost of Ownership and find the best deal.</p>
        <div class="source-chips">
            <span class="source-chip" style="border-color:#0058A3;color:#0058A3">🇸🇪 IKEA</span>
            <span class="source-chip" style="border-color:#00B894;color:#00B894">🏠 오늘의집</span>
            <span class="source-chip" style="border-color:#E84142;color:#E84142">🌏 AliExpress</span>
            <span class="source-chip" style="border-color:#F47500;color:#F47500">📦 Temu</span>
            <span class="source-chip" style="border-color:#E60023;color:#E60023">📌 Pinterest</span>
        </div>
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    inject_css()
    render_navbar()

    # ── Streamlit Cloud: install Playwright browser (cached, runs once) ───────
    _bootstrap_playwright()

    # Session state
    if "products"   not in st.session_state: st.session_state.products   = []
    if "errors"     not in st.session_state: st.session_state.errors     = []
    if "analyzed"   not in st.session_state: st.session_state.analyzed   = False
    if "sort_key"   not in st.session_state: st.session_state.sort_key   = "tco"
    if "pinterest"  not in st.session_state: st.session_state.pinterest  = []

    raw_lines, clicked = render_input_section()

    # Playwright check
    if clicked and not sc._PLAYWRIGHT_AVAILABLE:
        st.error("**Playwright is not installed.** Run: `pip install playwright && playwright install chromium`")
        return

    # Trigger analysis
    if clicked:
        if not raw_lines:
            st.warning("Paste at least one URL above.", icon="⚠️")
        else:
            url_groups, pinterest_urls = classify_urls(raw_lines)
            unknown = [l for l in raw_lines if detect_source(l) == "unknown" and l.startswith("http")]
            if unknown:
                st.warning(f"Skipped unrecognised URLs: {', '.join(u[:40] for u in unknown[:3])}", icon="⚠️")

            with st.spinner("Launching headless browser…"):
                products, errors = scrape_with_progress(url_groups)

            st.session_state.products  = products
            st.session_state.errors    = errors
            st.session_state.analyzed  = True
            st.session_state.pinterest = pinterest_urls

    # Errors
    if st.session_state.errors:
        with st.expander(f"⚠️ {len(st.session_state.errors)} error(s) during scraping", expanded=False):
            for e in st.session_state.errors:
                st.code(e)

    products = st.session_state.products
    priced   = [p for p in products if p.price_krw]

    if st.session_state.analyzed and not priced:
        st.info("No priced products were returned. The site may have blocked the scraper or the page structure changed.", icon="ℹ️")

    if priced:
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        render_kpi_strip(priced)

        tab_grid, tab_chart = st.tabs(["📦 Product Cards", "💹 TCO Breakdown"])

        with tab_grid:
            render_masonry_grid(priced, sort_key=st.session_state.sort_key)
            render_export(priced)

        with tab_chart:
            render_tco_chart(priced)

    # Pinterest reverse-image results
    if st.session_state.analyzed and st.session_state.pinterest and sc._PLAYWRIGHT_AVAILABLE:
        render_pinterest_panel(st.session_state.pinterest)

    # Empty state
    if not st.session_state.analyzed:
        render_empty_state()


if __name__ == "__main__":
    main()
