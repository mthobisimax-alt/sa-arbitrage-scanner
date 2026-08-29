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


app = FastAPI(
    title="SA Arb Scanner Web"
)

templates = Jinja2Templates(
    directory="."
)


latest = {
    "quotes": [],
    "opportunities": [],
    "updated_at": None,
    "errors": []
}


async def scan():

    quotes = []
    errors = []

    # TEST MODE
    # This creates a known arbitrage opportunity so we can
    # verify that the feed -> engine -> API pipeline works.

    if CFG.get("demo_mode"):

        now = datetime.now(timezone.utc).isoformat()

        quotes = [

            {
                "bookmaker": "Hollywoodbets",
                "event_id": "test-event-001",
                "sport": "soccer",
                "league": "Test League",
                "event_name": "Alpha FC v Beta FC",
                "market": "match_result",
                "line": "",
                "selection": "Alpha FC",
                "odds": 2.35,
                "timestamp": now
            },

            {
                "bookmaker": "Supabets",
                "event_id": "test-event-001",
                "sport": "soccer",
                "league": "Test League",
                "event_name": "Alpha FC v Beta FC",
                "market": "match_result",
                "line": "",
                "selection": "Draw",
                "odds": 4.10,
                "timestamp": now
            },

            {
                "bookmaker": "Betway",
                "event_id": "test-event-001",
                "sport": "soccer",
                "league": "Test League",
                "event_name": "Alpha FC v Beta FC",
                "market": "match_result",
                "line": "",
                "selection": "Beta FC",
                "odds": 4.00,
                "timestamp": now
            }
        ]

    else:

        # LIVE FEED MODE
        feed_quotes, feed_errors = await fetch_all_feeds(CFG)

        quotes.extend(feed_quotes)
        errors.extend(feed_errors)

    opportunities = find_arbs(
        quotes,
        CFG.get("max_quote_age_seconds", 20),
        CFG.get("min_margin_percent", 0.10)
    )

    return quotes, opportunities, errors


@app.get(
    "/",
    response_class=HTMLResponse
)
def home(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


@app.get("/api/status")
def status():

    return JSONResponse(
        latest
    )


@app.get("/api/bookmakers")
def bookmakers():

    names = set()

    for q in latest["quotes"]:

        bookmaker = q.get("bookmaker")

        if bookmaker:
            names.add(bookmaker)

    return sorted(names)


@app.get("/api/health")
def health():

    return {
        "ok": True,
        "service": "sa-arb-scanner-web"
    }


@app.on_event("startup")
async def startup():

    asyncio.create_task(
        scanner_loop()
    )


async def scanner_loop():

    global latest

    while True:

        try:

            quotes, opportunities, errors = (
                await scan()
            )

            latest = {

                "quotes": quotes,

                "opportunities":
                    opportunities,

                "updated_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "errors":
                    errors
            }

        except Exception as exc:

            latest["errors"] = [
                str(exc)
            ]

        await asyncio.sleep(
            CFG.get(
                "poll_seconds",
                5
            )
        )


if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8787
    )
