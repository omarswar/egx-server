"""
EGX FastAPI Backend — uses Investing.com as primary source
Deploy to Railway: uvicorn egx_server:app --host 0.0.0.0 --port $PORT
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

# Your watchlist — Stooq uses these symbols for EGX
WATCHLIST = {
    'COMI.EG':  'Commercial International Bank',
    'EAST.EG':  'Eastern Company',
    'TMGH.EG':  'Talaat Moustafa Group',
    'SWDY.EG':  'ElSewedy Electric',
    'HRHO.EG':  'Emaar Misr',
    'EFIC.EG':  'EFG Hermes',
    'JUFO.EG':  'Juhayna Food Industries',
    'CSAG.EG':  'Canal Shipping Agencies',
    'SKPC.EG':  'Sidi Kerir Petrochemicals',
    'ABUK.EG':  'Abu Kir Fertilizers',
    'MFPC.EG':  'Misr Fertilizers',
    'ETEL.EG':  'Telecom Egypt',
}

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
    }

def clean_num(s) -> Optional[float]:
    try:
        return float(str(s).replace(',', '').replace('%', '').replace('+', '').replace('EGP', '').strip())
    except:
        return None

def scrape_stooq(symbol: str) -> Optional[dict]:
    """Fetch price from Stooq — reliable, no bot blocking"""
    try:
        url = f"https://stooq.com/q/l/?s={symbol.lower()}&f=sd2t2ohlcv&h&e=csv"
        r = requests.get(url, headers=get_headers(), timeout=10)
        r.raise_for_status()
        lines = r.text.strip().split('\n')
        if len(lines) < 2:
            return None
        parts = lines[1].split(',')
        # CSV format: Symbol,Date,Time,Open,High,Low,Close,Volume
        if len(parts) < 7:
            return None
        close = clean_num(parts[6])
        open_ = clean_num(parts[3])
        if close is None:
            return None
        change_pct = round(((close - open_) / open_) * 100, 2) if open_ and open_ != 0 else None
        return {
            "symbol": symbol.replace('.EG', ''),
            "name": WATCHLIST.get(symbol, symbol),
            "price": close,
            "open": open_,
            "high": clean_num(parts[4]),
            "low": clean_num(parts[5]),
            "change_pct": change_pct,
            "volume": clean_num(parts[7]) if len(parts) > 7 else None,
            "date": parts[1],
            "timestamp": datetime.now().isoformat(),
            "source": "stooq.com"
        }
    except Exception as e:
        logging.warning(f"Stooq failed for {symbol}: {e}")
        return None


def get_all_stocks() -> list:
    stocks = []
    for symbol in WATCHLIST:
        data = scrape_stooq(symbol)
        if data:
            stocks.append(data)
        else:
            # Still include with null price so we know it was attempted
            stocks.append({
                "symbol": symbol.replace('.EG', ''),
                "name": WATCHLIST[symbol],
                "price": None,
                "change_pct": None,
                "volume": None,
                "timestamp": datetime.now().isoformat(),
                "source": "unavailable"
            })
    return stocks


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.get("/prices")
def get_prices():
    stocks = get_all_stocks()
    valid   = [s for s in stocks if s.get("price")]
    gainers = [s for s in valid if s.get("change_pct") and s["change_pct"] > 0]
    losers  = [s for s in valid if s.get("change_pct") and s["change_pct"] < 0]
    return {
        "timestamp": datetime.now().isoformat(),
        "count": len(valid),
        "stocks": stocks,
        "summary": {
            "gainers": len(gainers),
            "losers": len(losers),
            "flat": len(valid) - len(gainers) - len(losers),
        }
    }
