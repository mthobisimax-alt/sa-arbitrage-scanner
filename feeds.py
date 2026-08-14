import os
import httpx
from datetime import datetime, timezone


ODDS_API_KEY = os.getenv("ODDS_API_KEY")

ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds/"


async def fetch_live_odds():
    """
    Fetch soccer odds from The Odds API and convert them
    into the format expected by engine.py.
    """

    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY is not configured")

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal",
    }

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        response = await client.get(ODDS_API_URL, params=params)
        response.raise_for_status()
        events = response.json()

    quotes = []

    for event in events:
        event_id = event.get("id")
        sport = event.get("sport_title", "Soccer")
        league = event.get("sport_title", "")
        home = event.get("home_team")
        away = event.get("away_team")

        event_name = f"{home} v {away}"

        bookmakers = event.get("bookmakers", [])

        for bookmaker in bookmakers:
            bookmaker_name = bookmaker.get("title", "Unknown")

            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                for outcome in market.get("outcomes", []):
                    selection = outcome.get("name")
                    odds = outcome.get("price")

                    if not selection or odds is None:
                        continue

                    quotes.append({
                        "bookmaker": bookmaker_name,
                        "event_id": event_id,
                        "sport": "soccer",
                        "league": league,
                        "event_name": event_name,
                        "market": "match_result",
                        "line": "",
                        "selection": selection,
                        "odds": float(odds),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

    return quotes
