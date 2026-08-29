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

    feed_quotes, feed_errors = await fetch_all_feeds(CFG)

    quotes.extend(feed_quotes)
    errors.extend(feed_errors)

    opportunities = find_arbs(
        quotes,
        CFG.get(
            "max_quote_age_seconds",
            20
        ),
        CFG.get(
            "min_margin_percent",
            0.10
        )
    )

    return (
        quotes,
        opportunities,
        errors
    )


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
