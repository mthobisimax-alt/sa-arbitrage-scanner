import os
from datetime import datetime, timedelta, timezone

import httpx


def _resolve_env(value):
    if not isinstance(value, str):
        return value
    if not value.startswith("env:"):
        return value
    return os.getenv(value[4:].strip(), "")


def _iso_timestamp(value):
    if not value:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        # OddsPapi v5 uses milliseconds for changedAt; keep this tolerant.
        if value > 10_000_000_000:
            value = value / 1000
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return str(value)


def _selection_name(outcome_id, home, away):
    mapping = {
        "101": home,
        "102": "Draw",
        "103": away,
    }
    return mapping.get(str(outcome_id))


def adapt_oddspapi_fixture(data):
    """Normalize OddsPapi v4 Full Time Result (market 101) into engine.py quotes."""
    if not isinstance(data, dict):
        return []

    fixture_id = str(data.get("fixtureId", ""))
    home = data.get("participant1Name", "")
    away = data.get("participant2Name", "")
    event_name = f"{home} v {away}" if home and away else fixture_id
    league = data.get("tournamentName", "")
    sport = data.get("sportName", "Soccer")
    fallback_ts = data.get("updatedAt")

    quotes = []
    for bookmaker, book_data in (data.get("bookmakerOdds") or {}).items():
        if not isinstance(book_data, dict):
            continue
        if book_data.get("suspended") is True:
            continue

        markets = book_data.get("markets") or {}
        market = markets.get("101") or markets.get(101)
        if not isinstance(market, dict) or market.get("marketActive") is False:
            continue

        for outcome_id, outcome_data in (market.get("outcomes") or {}).items():
            selection = _selection_name(outcome_id, home, away)
            if not selection or not isinstance(outcome_data, dict):
                continue

            players = outcome_data.get("players") or {}
            player = players.get("0") or players.get(0)
            if not isinstance(player, dict) or player.get("active") is False:
                continue

            try:
                price = float(player.get("price"))
            except (TypeError, ValueError):
                continue
            if price <= 1:
                continue

            quotes.append({
                "bookmaker": str(bookmaker),
                "event_id": fixture_id,
                "sport": str(sport).lower(),
                "league": league,
                "event_name": event_name,
                "market": "match_result",
                "line": "",
                "selection": selection,
                "odds": price,
                "timestamp": _iso_timestamp(
                    player.get("bookmakerChangedAt")
                    or player.get("changedAt")
                    or fallback_ts
                ),
            })

    return quotes


async def fetch_oddspapi(cfg):
    """
    Fetch a deliberately small OddsPapi sample for integration testing.

    One scan uses one fixtures request plus one odds request per selected fixture.
    max_fixtures defaults to 1 to protect small/free request allowances.
    """
    api_key = _resolve_env(cfg.get("api_key", "env:ODDSPAPI_API_KEY"))
    if not api_key:
        raise RuntimeError("ODDSPAPI_API_KEY is not configured")

    base_url = cfg.get("base_url", "https://api.oddspapi.io/v4").rstrip("/")
    sport_id = int(cfg.get("sport_id", 10))  # Soccer in OddsPapi v4.
    max_fixtures = max(1, int(cfg.get("max_fixtures", 1)))
    hours_ahead = max(1, int(cfg.get("hours_ahead", 24)))
    timeout = float(cfg.get("timeout_seconds", 20))

    now = datetime.now(timezone.utc)
    until = now + timedelta(hours=hours_ahead)
    fixture_params = {
        "apiKey": api_key,
        "sportId": sport_id,
        "from": now.isoformat().replace("+00:00", "Z"),
        "to": until.isoformat().replace("+00:00", "Z"),
        "statusId": 0,
        "hasOdds": "true",
        "language": "en",
    }

    quotes = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        fixture_response = await client.get(f"{base_url}/fixtures", params=fixture_params)
        fixture_response.raise_for_status()
        fixtures = fixture_response.json()
        if not isinstance(fixtures, list):
            raise RuntimeError("Unexpected OddsPapi fixtures response")

        fixtures = [f for f in fixtures if isinstance(f, dict) and f.get("fixtureId")]
        fixtures.sort(key=lambda f: str(f.get("startTime", "")))

        for fixture in fixtures[:max_fixtures]:
            odds_response = await client.get(
                f"{base_url}/odds",
                params={
                    "apiKey": api_key,
                    "fixtureId": fixture["fixtureId"],
                    "oddsFormat": "decimal",
                    "language": "en",
                    "verbosity": 3,
                },
            )
            odds_response.raise_for_status()
            quotes.extend(adapt_oddspapi_fixture(odds_response.json()))

    if not quotes:
        raise RuntimeError("OddsPapi returned no usable Full Time Result quotes")
    return quotes


async def fetch_provider(cfg):
    provider = cfg.get("name") or "Unknown provider"
    adapter = cfg.get("adapter", "oddspapi_v4")

    if adapter == "oddspapi_v4":
        return await fetch_oddspapi(cfg)

    raise RuntimeError(f"Unsupported feed adapter '{adapter}' for {provider}")


async def fetch_all_feeds(config):
    quotes = []
    errors = []
    sources = config.get("providers", [])

    for cfg in sources:
        if not cfg.get("enabled", False):
            continue
        source_name = cfg.get("name") or "Unknown provider"
        try:
            quotes.extend(await fetch_provider(cfg))
        except Exception as exc:
            errors.append(f"{source_name}: {type(exc).__name__}: {exc}")

    if not any(cfg.get("enabled", False) for cfg in sources):
        errors.append("No live odds provider is enabled")

    return quotes, errors
