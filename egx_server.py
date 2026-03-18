"""
EGX MCP Server — EODHD for accurate prices on any EGX stock
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
import requests
import json
import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

EODHD_API_KEY = os.environ.get("EODHD_API_KEY", "69b4c98254dc11.70718475")
EODHD_BASE    = "https://eodhd.com/api"

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

MCP_TOOLS = [
    {
        "name": "get_egx_prices",
        "description": "Get accurate prices for all EGX watchlist stocks.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_egx_stock",
        "description": "Get accurate price for ANY EGX stock by ticker symbol. Works for any stock on the Egyptian Exchange, not just the watchlist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Any EGX ticker e.g. COMI, CSAG, ABUK, ORWE, AMOC"}
            },
            "required": ["symbol"]
        }
    }
]

# ─── Market hours ─────────────────────────────────────────────────────────────

def is_egx_open() -> bool:
    now     = datetime.now(ZoneInfo("Africa/Cairo"))
    weekday = now.weekday()
    h, m    = now.hour, now.minute
    is_trading_day  = weekday in (6, 0, 1, 2, 3)
    is_trading_hour = (h == 10 and m >= 0) or (10 < h < 14) or (h == 14 and m <= 30)
    return is_trading_day and is_trading_hour

# ─── Price logic ──────────────────────────────────────────────────────────────

def parse_val(val):
    try:
        v = float(val)
        return v if v > 0 else None
    except:
        return None

def fetch_stock(symbol: str, name: str = None) -> dict:
    sym  = symbol.upper().replace('.CA', '').replace('.EGX', '')
    name = name or WATCHLIST.get(sym, sym)
    try:
        # Try live real-time endpoint first
        r = requests.get(
            f"{EODHD_BASE}/real-time/{sym}.EGX",
            params={"api_token": EODHD_API_KEY, "fmt": "json"},
            timeout=15
        )
        r.raise_for_status()
        d = r.json()
        logging.info(f"EODHD real-time {sym}: {d}")

        live_price = parse_val(d.get("close"))
        prev_close = parse_val(d.get("previousClose"))
        change_pct = parse_val(d.get("change_p"))
        volume     = parse_val(d.get("volume"))
        market_open = is_egx_open()

        # Use live price if available, else fall back to previousClose
        price = live_price if live_price else prev_close

        if price:      price      = round(price, 2)
        if prev_close: prev_close = round(prev_close, 2)
        if change_pct: change_pct = round(change_pct, 2)
        if volume:     volume     = int(volume)

        # Only show change % when market is open and we have live data
        if not live_price or not market_open:
            change_pct = None

        status = "live" if market_open and live_price else "last_close" if price else "unavailable"

        return {
            "symbol":      sym,
            "name":        name,
            "price":       price,
            "prev_close":  prev_close,
            "change_pct":  change_pct,
            "volume":      volume,
            "market_open": market_open,
            "status":      status,
            "note":        "Live intraday price" if live_price else "Last session closing price — EODHD free tier",
            "timestamp":   datetime.now().isoformat(),
            "source":      "eodhd.com"
        }
    except Exception as e:
        logging.error(f"EODHD failed for {sym}: {e}")
        return {
            "symbol": sym, "name": name,
            "price": None, "change_pct": None, "volume": None,
            "market_open": False, "status": "unavailable",
            "timestamp": datetime.now().isoformat(), "source": "unavailable"
        }

def get_all_prices():
    stocks  = [fetch_stock(s, n) for s, n in WATCHLIST.items()]
    valid   = [s for s in stocks if s.get("price")]
    gainers = [s for s in valid if s.get("change_pct") and s["change_pct"] > 0]
    losers  = [s for s in valid if s.get("change_pct") and s["change_pct"] < 0]
    return {
        "timestamp":   datetime.now().isoformat(),
        "market_open": is_egx_open(),
        "count":       len(valid),
        "stocks":      stocks,
        "summary":     {"gainers": len(gainers), "losers": len(losers),
                        "flat":    len(valid) - len(gainers) - len(losers)}
    }

# ─── Tool execution ───────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> str:
    if name == "get_egx_prices":
        return json.dumps(get_all_prices())
    elif name == "get_egx_stock":
        sym = args.get("symbol", "")
        return json.dumps(fetch_stock(sym))
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
    return fetch_stock(symbol)
