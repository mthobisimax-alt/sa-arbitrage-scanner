import json
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from engine import find_arbs
from feeds import fetch_all_feeds


with open("config.json") as f:
    CFG = json.load(f)


app = FastAPI(title="SA Arb Scanner Web")
templates = Jinja2Templates(directory=".")


def preferred_bookmakers():
    names = []
    for provider in CFG.get("providers", []):
        for name in provider.get("preferred_bookmakers", []):
            if name and name not in names:
                names.append(name)
    return names


def feed_names():
    return [
        provider.get("name", "Unknown provider")
        for provider in CFG.get("providers", [])
        if provider.get("enabled", False)
    ]


latest = {
    "quotes": [],
    "opportunities": [],
    "updated_at": None,
    "errors": [],
    "feed_names": feed_names(),
    "preferred_bookmakers": preferred_bookmakers(),
}


async def scan():
    quotes = []
    errors = []

    if CFG.get("demo_mode"):
        now = datetime.now(timezone.utc).isoformat()
        quotes = [
            {"bookmaker": "Hollywoodbets", "event_id": "test-event-001", "sport": "soccer", "league": "Test League", "event_name": "Alpha FC v Beta FC", "market": "match_result", "line": "", "selection": "Alpha FC", "odds": 2.35, "timestamp": now},
            {"bookmaker": "Supabets", "event_id": "test-event-001", "sport": "soccer", "league": "Test League", "event_name": "Alpha FC v Beta FC", "market": "match_result", "line": "", "selection": "Draw", "odds": 4.10, "timestamp": now},
            {"bookmaker": "Betway", "event_id": "test-event-001", "sport": "soccer", "league": "Test League", "event_name": "Alpha FC v Beta FC", "market": "match_result", "line": "", "selection": "Beta FC", "odds": 4.00, "timestamp": now},
        ]
    else:
        feed_quotes, feed_errors = await fetch_all_feeds(CFG)
        quotes.extend(feed_quotes)
        errors.extend(feed_errors)

    opportunities = find_arbs(
        quotes,
        CFG.get("max_quote_age_seconds", 20),
        CFG.get("min_margin_percent", 0.10),
    )
    return quotes, opportunities, errors


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/status")
def status():
    return JSONResponse(latest)


@app.get("/api/bookmakers")
def bookmakers():
    names = sorted({q.get("bookmaker") for q in latest["quotes"] if q.get("bookmaker")})
    preferred = {name.lower() for name in preferred_bookmakers()}
    return {
        "live": names,
        "preferred_present": [name for name in names if name.lower() in preferred],
        "preferred_configured": preferred_bookmakers(),
    }


@app.get("/api/health")
def health():
    return {"ok": True, "service": "sa-arb-scanner-web"}


@app.on_event("startup")
async def startup():
    asyncio.create_task(scanner_loop())


async def scanner_loop():
    global latest
    while True:
        try:
            quotes, opportunities, errors = await scan()
            latest = {
                "quotes": quotes,
                "opportunities": opportunities,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "errors": errors,
                "feed_names": feed_names(),
                "preferred_bookmakers": preferred_bookmakers(),
            }
        except Exception as exc:
            latest["errors"] = [str(exc)]

        await asyncio.sleep(CFG.get("poll_seconds", 5))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8787)
