"""
EGX MCP Server — with OAuth support for Claude.ai connector
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
import yfinance as yf
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

# ─── Price logic ─────────────────────────────────────────────────────────────

def fetch_stock(ticker: str, name: str) -> dict:
    try:
        t    = yf.Ticker(ticker)
        info = t.fast_info
        price      = round(float(info.last_price), 2) if info.last_price else None
        prev_close = round(float(info.previous_close), 2) if info.previous_close else None
        change_pct = round(((price - prev_close) / prev_close) * 100, 2) if price and prev_close else None
        volume     = int(info.last_volume) if hasattr(info, 'last_volume') and info.last_volume else None
        return {"symbol": ticker.replace('.CA',''), "name": name, "price": price,
                "prev_close": prev_close, "change_pct": change_pct, "volume": volume,
                "timestamp": datetime.now().isoformat(), "source": "yahoo_finance"}
    except Exception as e:
        logging.warning(f"yfinance failed for {ticker}: {e}")
        return {"symbol": ticker.replace('.CA',''), "name": name, "price": None,
                "change_pct": None, "volume": None,
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

def execute_tool(name: str, args: dict) -> str:
    if name == "get_egx_prices":
        return json.dumps(get_all_prices())
    elif name == "get_egx_stock":
        return json.dumps(get_single_price(args.get("symbol", "")))
    return json.dumps({"error": f"Unknown tool: {name}"})

MCP_TOOLS = [
    {
        "name": "get_egx_prices",
        "description": "Get live prices for all EGX watchlist stocks. Returns price in EGP, change %, and volume.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_egx_stock",
        "description": "Get live price for any single EGX stock by ticker symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "EGX ticker e.g. COMI, CSAG, EAST"}
            },
            "required": ["symbol"]
        }
    }
]

# ─── OAuth endpoints (required by Claude.ai connector) ───────────────────────

@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/oauth-authorization-server/{path:path}")
def oauth_metadata(request: Request, path: str = ""):
    base = str(request.base_url).rstrip("/").replace("http://", "https://")
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
def oauth_protected_resource(request: Request, path: str = ""):
    base = str(request.base_url).rstrip("/").replace("http://", "https://")
    return JSONResponse({
        "resource": base,
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"]
    })

@app.get("/oauth/authorize")
def oauth_authorize(request: Request):
    # Auto-approve — immediately redirect back with a code
    redirect_uri = request.query_params.get("redirect_uri", "")
    state        = request.query_params.get("state", "")
    code         = "egx-auth-code-2024"
    return RedirectResponse(url=f"{redirect_uri}?code={code}&state={state}")

@app.post("/oauth/token")
async def oauth_token(request: Request):
    # Accept any code and return a static token
    return JSONResponse({
        "access_token": "egx-static-token-2024",
        "token_type":   "bearer",
        "expires_in":   99999999,
        "scope":        "read"
    })

# ─── MCP SSE + messages ───────────────────────────────────────────────────────

@app.get("/sse")
@app.post("/sse")
async def sse_endpoint(request: Request):
    async def stream():
        yield "event: endpoint\ndata: /messages\n\n"
        while True:
            if await request.is_disconnected():
                break
            yield ": ping\n\n"
            await asyncio.sleep(15)
    return StreamingResponse(stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

@app.post("/messages")
async def messages_endpoint(request: Request):
    body   = await request.json()
    method = body.get("method", "")
    mid    = body.get("id", 1)

    if method == "initialize":
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "egx-mcp-server", "version": "1.0.0"}
        }})
    elif method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": {"tools": MCP_TOOLS}})
    elif method == "tools/call":
        name   = body.get("params", {}).get("name", "")
        args   = body.get("params", {}).get("arguments", {})
        result = execute_tool(name, args)
        return JSONResponse({"jsonrpc": "2.0", "id": mid,
            "result": {"content": [{"type": "text", "text": result}], "isError": False}})
    elif method in ("notifications/initialized", "ping"):
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": {}})
    else:
        return JSONResponse({"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"Method not found: {method}"}})

# ─── Regular REST endpoints ───────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.get("/prices")
def prices():
    return get_all_prices()

@app.get("/price/{symbol}")
def price(symbol: str):
    return get_single_price(symbol)
