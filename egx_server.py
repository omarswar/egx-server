"""
EGX MCP Server — works as a Claude connector
Exposes EGX price tools via MCP protocol over SSE
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import yfinance as yf
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional

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

# ─── MCP Tool definitions ───────────────────────────────────────────────────

MCP_TOOLS = [
    {
        "name": "get_egx_prices",
        "description": "Get live prices for all EGX watchlist stocks from Yahoo Finance. Returns price in EGP, change %, and volume.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_egx_stock",
        "description": "Get live price for a single EGX stock by symbol. Works for any stock on the Egyptian Exchange.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "EGX stock ticker symbol e.g. COMI, CSAG, EAST, TMGH"
                }
            },
            "required": ["symbol"]
        }
    }
]

# ─── Price fetching logic ────────────────────────────────────────────────────

def fetch_stock(ticker: str, name: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price      = round(float(info.last_price), 2) if info.last_price else None
        prev_close = round(float(info.previous_close), 2) if info.previous_close else None
        change_pct = round(((price - prev_close) / prev_close) * 100, 2) if price and prev_close else None
        volume     = int(info.last_volume) if hasattr(info, 'last_volume') and info.last_volume else None
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

def get_all_prices():
    stocks = [fetch_stock(t, n) for t, n in WATCHLIST.items()]
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

def get_single_price(symbol: str):
    ticker = f"{symbol.upper()}.CA"
    name   = WATCHLIST.get(ticker, symbol.upper())
    return fetch_stock(ticker, name)

# ─── Tool execution ──────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> str:
    if name == "get_egx_prices":
        data = get_all_prices()
        return json.dumps(data)
    elif name == "get_egx_stock":
        symbol = args.get("symbol", "")
        data = get_single_price(symbol)
        return json.dumps(data)
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})

# ─── MCP SSE endpoint (Claude connector protocol) ────────────────────────────

@app.get("/sse")
async def sse_endpoint(request: Request):
    async def event_stream():
        # Send endpoint event first (required by MCP spec)
        yield f"event: endpoint\ndata: /messages\n\n"
        # Keep alive
        while True:
            if await request.is_disconnected():
                break
            yield f": ping\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

@app.post("/messages")
async def messages_endpoint(request: Request):
    body = await request.json()
    method  = body.get("method", "")
    msg_id  = body.get("id", 1)

    # MCP initialize handshake
    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "egx-mcp-server",
                    "version": "1.0.0"
                }
            }
        })

    # List available tools
    elif method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": MCP_TOOLS}
        })

    # Execute a tool call
    elif method == "tools/call":
        tool_name = body.get("params", {}).get("name", "")
        tool_args = body.get("params", {}).get("arguments", {})
        result    = execute_tool(tool_name, tool_args)
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": result}],
                "isError": False
            }
        })

    # notifications/initialized — no response needed
    elif method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": {}})

    else:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        })

# ─── Regular REST endpoints (still work as before) ───────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.get("/prices")
def prices():
    return get_all_prices()

@app.get("/price/{symbol}")
def price(symbol: str):
    return get_single_price(symbol)
