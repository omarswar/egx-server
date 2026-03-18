"""
EGX FastAPI Backend — uses yfinance (Yahoo Finance API)
EGX stocks on Yahoo Finance use .CA suffix e.g. COMI.CA
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Watchlist — Yahoo Finance uses .CA for EGX stocks
WATCHLIST = {
    'COMI.CA':  'Commercial International Bank',
    'EAST.CA':  'Eastern Company',
    'TMGH.CA':  'Talaat Moustafa Group',
    'SWDY.CA':  'ElSewedy Electric',
    'HRHO.CA':  'Emaar Misr',
    'EFIC.CA':  'EFG Hermes',
    'JUFO.CA':  'Juhayna Food Industries',
    'CSAG.CA':  'Canal Shipping Agencies',
    'SKPC.CA':  'Sidi Kerir Petrochemicals',
    'ABUK.CA':  'Abu Kir Fertilizers',
    'MFPC.CA':  'Misr Fertilizers',
    'ETEL.CA':  'Telecom Egypt',
}


def fetch_stock(ticker: str, name: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price      = round(info.last_price, 2) if info.last_price else None
        prev_close = round(info.previous_close, 2) if info.previous_close else None
        change_pct = round(((price - prev_close) / prev_close) * 100, 2) if price and prev_close else None
        volume     = info.last_volume if hasattr(info, 'last_volume') else None
        return {
            "symbol":     ticker.replace('.CA', ''),
            "name":       name,
            "price":      price,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "volume":     volume,
            "timestamp":  datetime.now().isoformat(),
            "source":     "yahoo_finance"
        }
    except Exception as e:
        logging.warning(f"yfinance failed for {ticker}: {e}")
        return {
            "symbol":     ticker.replace('.CA', ''),
            "name":       name,
            "price":      None,
            "change_pct": None,
            "volume":     None,
            "timestamp":  datetime.now().isoformat(),
            "source":     "unavailable"
        }


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.get("/prices")
def get_prices():
    stocks = [fetch_stock(ticker, name) for ticker, name in WATCHLIST.items()]
    valid   = [s for s in stocks if s.get("price")]
    gainers = [s for s in valid if s.get("change_pct") and s["change_pct"] > 0]
    losers  = [s for s in valid if s.get("change_pct") and s["change_pct"] < 0]
    return {
        "timestamp": datetime.now().isoformat(),
        "count":     len(valid),
        "stocks":    stocks,
        "summary":   {
            "gainers": len(gainers),
            "losers":  len(losers),
            "flat":    len(valid) - len(gainers) - len(losers),
        }
    }


@app.get("/price/{symbol}")
def get_single(symbol: str):
    """Check any EGX stock on demand e.g. /price/ORWE"""
    ticker = f"{symbol.upper()}.CA"
    name   = WATCHLIST.get(ticker, symbol.upper())
    return fetch_stock(ticker, name)
