"""
EGX MCP Server — prices scraped from Arab Finance
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
import requests
import json
import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

WATCHLIST = {
    'COMI': 'Commercial International Bank',
    'EAST': 'Eastern Company',
    'TMGH': 'Talaat Moustafa Group',
    'SWDY': 'ElSewedy Electric',
    'HRHO': 'Emaar Misr',
    'EFIC': 'EFG Hermes',
    'JUFO': 'Juhayna Food Industries',
    'CSAG': 'Canal Shipping Agencies',
    'SKPC': 'Sidi Kerir Petrochemicals',
    'ABUK': 'Abu Kir Fertilizers',
    'MFPC': 'Misr Fertilizers',
    'ETEL': 'Telecom Egypt',
}

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

MCP_TOOLS = [
    {
        "name": "get_egx_prices",
        "description": "Get live EGX stock prices for the full watchlist. Returns price in EGP, change %, volume, and market status.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_egx_stock",
        "description": "Get live price for any single EGX stock by ticker symbol e.g. COMI, CSAG, EAST.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "EGX stock ticker e.g. COMI, CSAG"}
            },
            "required": ["symbol"]
        }
    }
]

# ─── Market hours ─────────────────────────────────────────────────────────────

def is_egx_open() -> bool:
    """EGX trades Sun-Thu 10:00-14:30 Cairo time (UTC+2)"""
    now          = datetime.utcnow()
    cairo_hour   = (now.hour + 2) % 24
    cairo_minute = now.minute
    weekday      = now.weekday()  # 0=Mon 6=Sun
    is_trading_day  = weekday in (6, 0, 1, 2, 3)
    is_trading_hour = (cairo_hour == 10 and cairo_minute >= 0) or \
                      (10 < cairo_hour < 14) or \
                      (cairo_hour == 14 and cairo_minute <= 30)
    return is_trading_day and is_trading_hour

# ─── Price logic ──────────────────────────────────────────────────────────────

def fetch_stock(ticker: str, name: str) -> dict:
    try:
        t    = yf.Ticker(ticker)
        info = t.info
        price      = info.get("regularMarketPrice") or info.get("currentPrice")
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
        volume     = info.get("regularMarketVolume")
        price      = round(float(price), 2)      if price      else None
        prev_close = round(float(prev_close), 2) if prev_close else None
        volume     = int(volume)                 if volume      else None
        market_open = is_egx_open()
        change_pct = round(((price - prev_close) / prev_close) * 100, 2) if price and prev_close else None

        if market_open:
            status = "live"
        elif volume:
            status = "post_market"
        else:
            status = "market_closed"

        return {
            "symbol":      ticker.replace('.CA', ''),
            "name":        name,
            "price":       price,
            "prev_close":  prev_close,
            "change_pct":  change_pct,
            "volume":      volume,
            "market_open": market_open,
            "status":      status,
            "timestamp":   datetime.now().isoformat(),
            "source":      "yahoo_finance"
        }
    except Exception as e:
        logging.warning(f"yfinance failed for {ticker}: {e}")
        return {
            "symbol": ticker.replace('.CA', ''), "name": name,
            "price": None, "change_pct": None, "volume": None,
            "market_open": False, "status": "unavailable",
            "timestamp": datetime.now().isoformat(), "source": "unavailable"
        }

def get_all_prices():
    stocks  = [fetch_stock(t, n) for t, n in WATCHLIST.items()]
    valid   = [s for s in stocks if s.get("price")]
    gainers = [s for s in valid if s.get("change_pct") and s["change_pct"] > 0]
    losers  = [s for s in valid if s.get("change_pct") and s["change_pct"] < 0]
    return {
        "timestamp":   datetime.now().isoformat(),
        "market_open": is_egx_open(),
        "count":       len(valid),
        "stocks":      stocks,
        "summary":     {
            "gainers": len(gainers),
            "losers":  len(losers),
            "flat":    len(valid) - len(gainers) - len(losers)
        }
    }

def get_single_price(symbol: str):
    clean = symbol.upper().replace('.CA', '')
    ticker = f"{clean}.CA"
    return fetch_stock(ticker, WATCHLIST.get(ticker, clean))

# ─── Tool execution ───────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> str:
    if name == "get_egx_prices":
        return json.dumps(get_all_prices())
    elif name == "get_egx_stock":
        return json.dumps(get_single_price(args.get("symbol", "")))
    return json.dumps({"error": f"Unknown tool: {name}"})

def make_response(mid, result):
    return json.dumps({"jsonrpc": "2.0", "id": mid, "result": result})

def handle_message(body: dict) -> str:
    method = body.get("method", "")
    mid    = body.get("id", 1)
    if method == "initialize":
        return make_response(mid, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "egx-mcp-server", "version": "1.0.0"}
        })
    elif method == "tools/list":
        return make_response(mid, {"tools": MCP_TOOLS})
    elif method == "tools/call":
        name   = body.get("params", {}).get("name", "")
        args   = body.get("params", {}).get("arguments", {})
        result = execute_tool(name, args)
        return make_response(mid, {
            "content": [{"type": "text", "text": result}],
            "isError": False
        })
    elif method in ("notifications/initialized", "ping"):
        return make_response(mid, {})
    else:
        return json.dumps({"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"Method not found: {method}"}})

# ─── OAuth ────────────────────────────────────────────────────────────────────

def get_base(request: Request):
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"https://{host}"

@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/oauth-authorization-server/{path:path}")
def oauth_server(request: Request, path: str = ""):
    base = get_base(request)
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"]
    })

@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/{path:path}")
def oauth_resource(request: Request, path: str = ""):
    base = get_base(request)
    return JSONResponse({
        "resource": base,
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"]
    })

@app.get("/oauth/authorize")
def oauth_authorize(request: Request):
    redirect_uri = request.query_params.get("redirect_uri", "")
    state        = request.query_params.get("state", "")
    return RedirectResponse(url=f"{redirect_uri}?code=egx-code-2024&state={state}")

@app.post("/oauth/token")
async def oauth_token():
    return JSONResponse({
        "access_token": "egx-token-2024",
        "token_type":   "bearer",
        "expires_in":   99999999,
        "scope":        "read"
    })

# ─── MCP SSE ─────────────────────────────────────────────────────────────────

@app.get("/sse")
@app.post("/sse")
async def sse(request: Request):
    base = get_base(request)
    if request.method == "POST":
        try:
            body   = await request.json()
            result = handle_message(body)
            async def post_stream():
                yield f"data: {result}\n\n"
            return StreamingResponse(post_stream(), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def get_stream():
        yield f"event: endpoint\ndata: {base}/messages\n\n"
        while True:
            if await request.is_disconnected():
                break
            yield ": ping\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(get_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

@app.post("/messages")
async def messages(request: Request):
    body   = await request.json()
    result = handle_message(body)
    return JSONResponse(json.loads(result))

# ─── REST endpoints ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat(), "market_open": is_egx_open()}

@app.get("/prices")
def prices():
    return get_all_prices()

@app.get("/price/{symbol}")
def price(symbol: str):
    return get_single_price(symbol)
