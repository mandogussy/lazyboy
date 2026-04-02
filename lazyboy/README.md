# 📌 Pinter-Match AI

> Interior Furniture Matching & Logistics Analyzer  
> **Zero-API cost** · Playwright headless scraping · Streamlit dashboard

---

## What it does

Paste product URLs from **IKEA**, **오늘의집**, **AliExpress**, or **Temu** and get:

- **Total Cost of Ownership (TCO)** — Base price + Shipping + Assembly, all in one number
- **Masonry card grid** — Pinterest-style visual comparison
- **Quality risk signals** — Keyword analysis from reviews (AliExpress / Temu)
- **Convenience tier** — A (fast/no assembly) · B (DIY) · C (budget/risk)
- **Pinterest reverse image** — Paste a pin URL → Google Lens match → real product
- **Affiliate links** — Auto-appended tracking IDs per source

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browser
playwright install chromium

# 3. Launch dashboard
streamlit run dashboard.py
```

---

## File structure

```
furniture_analyzer/
├── scraper.py        # Playwright scrapers (IKEA, ohou, AliExpress, Temu, Pinterest)
├── dashboard.py      # Streamlit dashboard (Pinterest/magazine UI)
├── requirements.txt  # Python dependencies
└── .gitignore
```

---

## Configuration

Open the **Affiliate IDs** expander in the dashboard and paste your tracking IDs:

| Source | Parameter |
|---|---|
| IKEA | `affid` |
| 오늘의집 | `utm_source` + `utm_medium` + `utm_campaign` |
| AliExpress | `aff_fcid` |
| Temu | `refer_url` |

Or edit `AFFILIATE_CONFIG` directly in `scraper.py`.

---

## Requirements

- Python 3.9+
- `playwright >= 1.44`
- `streamlit >= 1.35`
- `plotly >= 5.20`
- `pandas >= 2.0`
