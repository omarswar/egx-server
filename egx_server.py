"""
EGX FastAPI Backend
Run with: uvicorn egx_server:app --reload --port 8000
Install:  pip install fastapi uvicorn requests beautifulsoup4 pandas
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import random
import logging
from datetime import datetime
from typing import Optional

logging.basicConfig(level=logging.INFO)
app = FastAPI()

# Allow the Claude artifact (any origin) to call this
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
]

KNOWN_STOCKS = {
    'COMI': 'Commercial International Bank',
    'EAST': 'Eastern Company',
    'HRHO': 'Emaar Misr',
    'TMGH': 'Talaat Moustafa Group',
    'SWDY': 'ElSewedy Electric',
    'EFIC': 'EFG Hermes',
    'JUFO': 'Juhayna Food Industries',
    'ORHD': 'Orascom Development',
}

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
    }

def clean_price(s: str) -> Optional[float]:
    try:
        return float(s.replace(',', '').replace('EGP', '').strip())
    except Exception:
        return None

def clean_change(s: str) -> Optional[float]:
    try:
        return float(s.replace('%', '').replace('+', '').strip())
    except Exception:
        return None

def scrape_egx() -> list[dict]:
    """
    Scrape live prices from the official EGX website.
    EGX loads data via an AJAX endpoint — we hit that directly.
    Falls back to HTML table parsing if AJAX fails.
    """
    stocks = []
    timestamp = datetime.now().isoformat()

    # --- Attempt 1: EGX AJAX/API endpoint (faster, more reliable) ---
    try:
        ajax_url = "https://www.egx.com.eg/en/Webservices/Stock/getStockData.aspx"
        resp = requests.get(ajax_url, headers=get_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()  # EGX returns JSON from this endpoint
        for item in data:
            sym = item.get("StockSymbol", "").strip()
            stocks.append({
                "symbol": sym,
                "name": item.get("StockNameEn", KNOWN_STOCKS.get(sym, sym)).strip(),
                "price": clean_price(str(item.get("LastPrice", ""))),
                "change": clean_change(str(item.get("Change", ""))),
                "change_pct": clean_change(str(item.get("ChangePercentage", ""))),
                "volume": item.get("TotalVolume", None),
                "timestamp": timestamp,
                "source": "egx.com.eg (ajax)"
            })
        if stocks:
            logging.info(f"AJAX: got {len(stocks)} stocks")
            return stocks
    except Exception as e:
        logging.warning(f"AJAX endpoint failed: {e}, falling back to HTML scrape")

    # --- Attempt 2: HTML table scrape ---
    try:
        url = "https://www.egx.com.eg/en/stock-price.aspx"
        resp = requests.get(url, headers=get_headers(), timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        # Try the known GridView table ID
        table = soup.find("table", {"id": "ctl00_Content_StockGrid_GridView1"})
        if not table:
            # Broader fallback — grab first large table on page
            tables = soup.find_all("table")
            table = max(tables, key=lambda t: len(t.find_all("tr")), default=None)

        if not table:
            logging.error("No table found on EGX HTML page")
            return []

        rows = table.find_all("tr")[1:]  # skip header
        for row in rows:
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) < 3:
                continue
            sym = cols[1] if len(cols) > 1 else cols[0]
            stocks.append({
                "symbol": sym.strip(),
                "name": cols[2].strip() if len(cols) > 2 else KNOWN_STOCKS.get(sym, sym),
                "price": clean_price(cols[3]) if len(cols) > 3 else None,
                "change": clean_change(cols[4]) if len(cols) > 4 else None,
                "change_pct": clean_change(cols[5]) if len(cols) > 5 else None,
                "volume": cols[6].strip() if len(cols) > 6 else None,
                "timestamp": timestamp,
                "source": "egx.com.eg (html)"
            })

        logging.info(f"HTML scrape: got {len(stocks)} stocks")
        return stocks

    except Exception as e:
        logging.error(f"HTML scrape also failed: {e}")
        return []


@app.get("/prices")
def get_prices():
    stocks = scrape_egx()
    gainers = [s for s in stocks if s.get("change_pct") and s["change_pct"] > 0]
    losers  = [s for s in stocks if s.get("change_pct") and s["change_pct"] < 0]
    return {
        "timestamp": datetime.now().isoformat(),
        "count": len(stocks),
        "stocks": stocks,
        "summary": {
            "gainers": len(gainers),
            "losers": len(losers),
            "flat": len(stocks) - len(gainers) - len(losers),
        }
    }

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
