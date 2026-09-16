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
        if value > 10_000_000_000:
            value = value / 1000
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return str(value)


def _humanize(value):
    return str(value or "").replace("_", " ").replace("-", " ").strip().title()


def _outcome_label(outcome_id, outcome_data, player, home, away):
    raw = str(player.get("bookmakerOutcomeId") or "").strip()
    low = raw.lower()
    if low in ("home", "1"):
        return home
    if low in ("away", "2"):
        return away
    if low in ("draw", "x"):
        return "Draw"
    if low in ("yes", "no", "over", "under"):
        return low.title()
    if raw:
        return raw
    mapping = {"101": home, "102": "Draw", "103": away}
    return mapping.get(str(outcome_id), str(outcome_id))


def _market_line_and_name(market_id, market_data, outcome_data, player):
    bookmaker_market_id = str(market_data.get("bookmakerMarketId") or "")
    outcome_ref = str(player.get("bookmakerOutcomeId") or "")
    raw = " ".join([bookmaker_market_id, outcome_ref]).lower()
    line = ""
    import re
    nums = re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", outcome_ref)
    if nums:
        line = nums[0]
    name = market_data.get("marketName") or market_data.get("name") or outcome_data.get("marketName")
    if not name:
        if "both" in raw and "score" in raw:
            name = "Both Teams To Score"
        elif "over" in raw or "under" in raw:
            name = f"Over / Under{(' ' + line) if line else ''}"
        elif str(market_id) == "101":
            name = "Full Time Result"
        else:
            name = f"Football Market {market_id}"
    return line, str(name)


def adapt_oddspapi_fixture(data):
    """Normalize every active OddsPapi football market into generic engine quotes."""
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
        if not isinstance(book_data, dict) or book_data.get("suspended") is True:
            continue
        fixture_url = book_data.get("fixturePath") or ""
        for market_id, market_data in (book_data.get("markets") or {}).items():
            if not isinstance(market_data, dict) or market_data.get("marketActive") is False:
                continue
            for outcome_id, outcome_data in (market_data.get("outcomes") or {}).items():
                if not isinstance(outcome_data, dict):
                    continue
                for player_id, player in (outcome_data.get("players") or {}).items():
                    if not isinstance(player, dict) or player.get("active") is False:
                        continue
                    try:
                        price = float(player.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if price <= 1:
                        continue
                    selection = _outcome_label(outcome_id, outcome_data, player, home, away)
                    line, market_name = _market_line_and_name(market_id, market_data, outcome_data, player)
                    player_name = player.get("playerName")
                    if player_name:
                        selection = f"{player_name} — {selection}"
                    quotes.append({
                        "bookmaker": str(bookmaker),
                        "bookmaker_url": fixture_url,
                        "event_id": fixture_id,
                        "sport": str(sport).lower(),
                        "league": league,
                        "event_name": event_name,
                        "market": str(market_name),
                        "market_id": str(market_id),
                        "line": line,
                        "selection": selection,
                        "odds": price,
                        "timestamp": _iso_timestamp(player.get("bookmakerChangedAt") or player.get("changedAt") or fallback_ts),
                    })
    return quotes


async def fetch_oddspapi(cfg):
    api_key = _resolve_env(cfg.get("api_key", "env:ODDSPAPI_API_KEY"))
    if not api_key:
        raise RuntimeError("ODDSPAPI_API_KEY is not configured")

    base_url = cfg.get("base_url", "https://api.oddspapi.io/v4").rstrip("/")
    sport_id = int(cfg.get("sport_id", 10))
    max_fixtures = max(1, int(cfg.get("max_fixtures", 1)))
    hours_ahead = max(1, int(cfg.get("hours_ahead", 24)))
    timeout = float(cfg.get("timeout_seconds", 20))
    now = datetime.now(timezone.utc)
    until = now + timedelta(hours=hours_ahead)
    fixture_params = {"apiKey": api_key, "sportId": sport_id, "from": now.isoformat().replace("+00:00", "Z"), "to": until.isoformat().replace("+00:00", "Z"), "statusId": 0, "hasOdds": "true", "language": "en"}

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
            odds_response = await client.get(f"{base_url}/odds", params={"apiKey": api_key, "fixtureId": fixture["fixtureId"], "oddsFormat": "decimal", "language": "en", "verbosity": 3})
            odds_response.raise_for_status()
            quotes.extend(adapt_oddspapi_fixture(odds_response.json()))

    if not quotes:
        raise RuntimeError("OddsPapi returned no usable football market quotes")
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
