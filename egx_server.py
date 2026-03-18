"""
EGX MCP Server — prices + charts + portfolio + alerts + technicals + macro
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
import yfinance as yf
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional
import numpy as np

logging.basicConfig(level=logging.INFO)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

WATCHLIST = {
    'COMI.CA': 'Commercial International Bank',
    'EAST.CA': 'Eastern Company',
    'TMGH.CA': 'Talaat Moustafa Group',
    'SWDY.CA': 'ElSewedy Electric',
    'HRHO.CA': 'Emaar Misr',
    'EFIC.CA': 'EFG Hermes',
    'JUFO.CA': 'Juhayna Food Industries',
    'CSAG.CA': 'Canal Shipping Agencies',
    'SKPC.CA': 'Sidi Kerir Petrochemicals',
    'ABUK.CA': 'Abu Kir Fertilizers',
    'MFPC.CA': 'Misr Fertilizers',
    'ETEL.CA': 'Telecom Egypt',
}

# ─── In-memory storage (persists while server is running) ────────────────────
PORTFOLIO = {}   # { "COMI": {"qty": 100, "avg_buy": 65.0} }
ALERTS    = {}   # { "CSAG": {"above": 30.0, "below": 25.0} }

# ─── Price logic ──────────────────────────────────────────────────────────────

def is_egx_open() -> bool:
    """EGX trades Sun-Thu 10:00-14:30 Cairo time (UTC+2)"""
    now = datetime.utcnow()
    cairo_hour   = (now.hour + 2) % 24
    cairo_minute = now.minute
    weekday      = now.weekday()  # 0=Mon, 6=Sun
    is_trading_day = weekday in (6, 0, 1, 2, 3)  # Sun-Thu
    is_trading_hour = (cairo_hour == 10 and cairo_minute >= 0) or \
                      (10 < cairo_hour < 14) or \
                      (cairo_hour == 14 and cairo_minute <= 30)
    return is_trading_day and is_trading_hour

def fetch_stock(ticker: str, name: str) -> dict:
    try:
        t    = yf.Ticker(ticker)
        info = t.fast_info
        price      = round(float(info.last_price), 2)     if info.last_price     else None
        prev_close = round(float(info.previous_close), 2) if info.previous_close else None
        volume     = int(info.last_volume) if hasattr(info, 'last_volume') and info.last_volume else None
        market_open = is_egx_open()

        # Only calculate change_pct when market is open and volume confirms trading
        if price and prev_close and market_open and volume:
            change_pct = round(((price - prev_close) / prev_close) * 100, 2)
            status = "live"
        elif price and prev_close and not market_open:
            change_pct = None
            status = "market_closed — price is last session close, change % not reliable"
        else:
            change_pct = None
            status = "unavailable"

        return {
            "symbol": ticker.replace('.CA', ''), "name": name,
            "price": price, "prev_close": prev_close,
            "change_pct": change_pct, "volume": volume,
            "market_open": market_open, "status": status,
            "timestamp": datetime.now().isoformat(), "source": "yahoo_finance"
        }
    except Exception as e:
        logging.warning(f"yfinance failed for {ticker}: {e}")
        return {"symbol": ticker.replace('.CA', ''), "name": name,
                "price": None, "change_pct": None, "volume": None,
                "market_open": False, "status": "unavailable",
                "timestamp": datetime.now().isoformat(), "source": "unavailable"}

def get_all_prices():
    stocks  = [fetch_stock(t, n) for t, n in WATCHLIST.items()]
    valid   = [s for s in stocks if s.get("price")]
    gainers = [s for s in valid if s.get("change_pct") and s["change_pct"] > 0]
    losers  = [s for s in valid if s.get("change_pct") and s["change_pct"] < 0]
    return {"timestamp": datetime.now().isoformat(), "count": len(valid), "stocks": stocks,
            "summary": {"gainers": len(gainers), "losers": len(losers),
                        "flat": len(valid) - len(gainers) - len(losers)}}

def get_single_price(symbol: str):
    ticker = f"{symbol.upper()}.CA"
    return fetch_stock(ticker, WATCHLIST.get(ticker, symbol.upper()))

# ─── Chart + Technicals ───────────────────────────────────────────────────────

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_g  = np.mean(gains[:period])
    avg_l  = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period-1) + gains[i]) / period
        avg_l = (avg_l * (period-1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - (100 / (1 + rs)), 2)

def calc_ma(closes, period):
    if len(closes) < period:
        return None
    return round(float(np.mean(closes[-period:])), 2)

def get_chart_data(symbol: str, period: str = "3mo") -> dict:
    try:
        ticker = f"{symbol.upper()}.CA"
        t      = yf.Ticker(ticker)
        hist   = t.history(period=period)
        if hist.empty:
            return {"error": f"No chart data for {symbol}"}
        candles = []
        for date, row in hist.iterrows():
            candles.append({
                "date":   date.strftime("%Y-%m-%d"),
                "open":   round(float(row["Open"]),  2),
                "high":   round(float(row["High"]),  2),
                "low":    round(float(row["Low"]),   2),
                "close":  round(float(row["Close"]), 2),
                "volume": int(row["Volume"])
            })
        closes     = np.array([c["close"] for c in candles])
        rsi        = calc_rsi(closes)
        ma20       = calc_ma(closes, 20)
        ma50       = calc_ma(closes, 50)
        latest     = candles[-1]
        first      = candles[0]
        period_chg = round(((latest["close"] - first["close"]) / first["close"]) * 100, 2)

        # Simple signal
        signal = "neutral"
        if rsi and ma20 and ma50:
            if rsi < 35 and latest["close"] > ma20:
                signal = "buy — oversold, price above MA20"
            elif rsi > 65 and latest["close"] < ma20:
                signal = "sell — overbought, price below MA20"
            elif latest["close"] > ma20 > ma50:
                signal = "bullish — price above MA20 > MA50"
            elif latest["close"] < ma20 < ma50:
                signal = "bearish — price below MA20 < MA50"

        return {
            "symbol": symbol.upper(), "name": WATCHLIST.get(ticker, symbol.upper()),
            "period": period, "candles": candles, "total_candles": len(candles),
            "period_change_pct": period_chg,
            "technicals": {"rsi": rsi, "ma20": ma20, "ma50": ma50, "signal": signal},
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

# ─── Portfolio ────────────────────────────────────────────────────────────────

def get_portfolio():
    if not PORTFOLIO:
        return {"message": "Portfolio is empty. Add stocks with add_to_portfolio.", "holdings": [], "total_value": 0}
    holdings = []
    total_value = 0
    total_cost  = 0
    for sym, h in PORTFOLIO.items():
        stock = get_single_price(sym)
        price = stock.get("price")
        qty   = h["qty"]
        avg   = h["avg_buy"]
        value = round(price * qty, 2) if price else None
        cost  = round(avg * qty, 2)
        pnl   = round(value - cost, 2) if value else None
        pnl_pct = round(((price - avg) / avg) * 100, 2) if price else None
        if value:
            total_value += value
        total_cost += cost
        holdings.append({
            "symbol": sym, "name": stock.get("name", sym),
            "qty": qty, "avg_buy": avg, "current_price": price,
            "value": value, "cost": cost, "pnl": pnl, "pnl_pct": pnl_pct,
            "change_pct_today": stock.get("change_pct")
        })
    total_pnl     = round(total_value - total_cost, 2)
    total_pnl_pct = round((total_pnl / total_cost) * 100, 2) if total_cost else 0
    return {
        "holdings": holdings,
        "total_value": round(total_value, 2),
        "total_cost":  round(total_cost, 2),
        "total_pnl":   total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "timestamp": datetime.now().isoformat()
    }

# ─── Alerts ───────────────────────────────────────────────────────────────────

def check_alerts():
    triggered = []
    for sym, thresholds in ALERTS.items():
        stock = get_single_price(sym)
        price = stock.get("price")
        if not price:
            continue
        if "above" in thresholds and price >= thresholds["above"]:
            triggered.append({"symbol": sym, "type": "above",
                "threshold": thresholds["above"], "current_price": price,
                "message": f"{sym} is at EGP {price} — above your alert of EGP {thresholds['above']}"})
        if "below" in thresholds and price <= thresholds["below"]:
            triggered.append({"symbol": sym, "type": "below",
                "threshold": thresholds["below"], "current_price": price,
                "message": f"{sym} is at EGP {price} — below your alert of EGP {thresholds['below']}"})
    return {"alerts_set": ALERTS, "triggered": triggered,
            "triggered_count": len(triggered), "timestamp": datetime.now().isoformat()}

# ─── Macro ────────────────────────────────────────────────────────────────────

def get_macro():
    tickers = {"USD_EGP": "EGP=X", "Oil_Brent": "BZ=F", "Gold": "GC=F", "EGX30": "^EGX30"}
    result  = {}
    for name, ticker in tickers.items():
        try:
            t    = yf.Ticker(ticker)
            info = t.fast_info
            price = round(float(info.last_price), 2) if info.last_price else None
            prev  = round(float(info.previous_close), 2) if info.previous_close else None
            chg   = round(((price-prev)/prev)*100, 2) if price and prev else None
            result[name] = {"price": price, "change_pct": chg}
        except:
            result[name] = {"price": None, "change_pct": None}
    result["timestamp"] = datetime.now().isoformat()
    return result

# ─── MCP Tools list ───────────────────────────────────────────────────────────

MCP_TOOLS = [
    {
        "name": "get_egx_prices",
        "description": "Get live prices for all EGX watchlist stocks. Returns price EGP, change %, volume.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_egx_stock",
        "description": "Get live price for any single EGX stock by ticker.",
        "inputSchema": {"type": "object",
            "properties": {"symbol": {"type": "string", "description": "EGX ticker e.g. COMI, CSAG"}},
            "required": ["symbol"]}
    },
    {
        "name": "get_egx_chart",
        "description": "Get historical OHLCV candles + RSI + MA20 + MA50 + trading signal for any EGX stock.",
        "inputSchema": {"type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "EGX ticker"},
                "period": {"type": "string", "description": "1mo 3mo 6mo 1y 2y — default 3mo"}
            }, "required": ["symbol"]}
    },
    {
        "name": "get_portfolio",
        "description": "Get current portfolio with live P&L, total value, and today's change for each holding.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "add_to_portfolio",
        "description": "Add or update a stock in the portfolio with quantity and average buy price.",
        "inputSchema": {"type": "object",
            "properties": {
                "symbol":    {"type": "string"},
                "qty":       {"type": "number", "description": "Number of shares"},
                "avg_buy":   {"type": "number", "description": "Average buy price in EGP"}
            }, "required": ["symbol", "qty", "avg_buy"]}
    },
    {
        "name": "remove_from_portfolio",
        "description": "Remove a stock from the portfolio.",
        "inputSchema": {"type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"]}
    },
    {
        "name": "set_alert",
        "description": "Set a price alert for a stock. Triggers when price goes above or below threshold.",
        "inputSchema": {"type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "above":  {"type": "number", "description": "Alert when price rises above this EGP value"},
                "below":  {"type": "number", "description": "Alert when price drops below this EGP value"}
            }, "required": ["symbol"]}
    },
    {
        "name": "check_alerts",
        "description": "Check all price alerts and return which ones have been triggered.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_macro",
        "description": "Get key macro indicators: USD/EGP rate
