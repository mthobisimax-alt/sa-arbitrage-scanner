import httpx
from datetime import datetime, timezone


async def fetch_json_feed(cfg):
    """
    Fetch one bookmaker's JSON feed and convert it into
    the standard quote format used by engine.py.
    """

    url = cfg.get("url", "").strip()

    if not url:
        raise RuntimeError(
            f'No feed URL configured for {cfg.get("bookmaker", "Unknown")}'
        )

    headers = cfg.get("headers", {})

    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=True
    ) as client:

        response = await client.get(
            url,
            headers=headers
        )

        response.raise_for_status()
        data = response.json()

    if isinstance(data, dict):
        rows = data.get("odds", data.get("events", []))
    else:
        rows = data

    if not isinstance(rows, list):
        raise ValueError(
            f'{cfg.get("bookmaker", "Unknown")} feed must return a JSON list'
        )

    now = datetime.now(timezone.utc).isoformat()

    quotes = []

    for row in rows:

        bookmaker = cfg.get("bookmaker", "Unknown")

        event_id = row.get("event_id") or row.get("id")

        home = row.get("home_team") or row.get("home")
        away = row.get("away_team") or row.get("away")

        event_name = row.get("event_name")

        if not event_name and home and away:
            event_name = f"{home} v {away}"

        market = row.get("market", "match_result")

        line = row.get("line", "")

        selection = row.get("selection")

        odds = row.get("odds")

        if not selection or odds is None:
            continue

        try:
            odds = float(odds)
        except (TypeError, ValueError):
            continue

        if odds <= 1:
            continue

        quotes.append({
            "bookmaker": bookmaker,
            "event_id": str(event_id) if event_id is not None else "",
            "sport": row.get("sport", "soccer"),
            "league": row.get("league", ""),
            "event_name": event_name or "",
            "market": market,
            "line": line,
            "selection": selection,
            "odds": odds,
            "timestamp": row.get("timestamp", now)
        })

    return quotes


async def fetch_all_feeds(config):
    """
    Fetch every enabled bookmaker feed.
    """

    quotes = []
    errors = []

    feeds = config.get("feeds", [])

    for cfg in feeds:

        if not cfg.get("enabled", False):
            continue

        bookmaker = cfg.get("bookmaker", "Unknown")

        try:

            feed_quotes = await fetch_json_feed(cfg)

            quotes.extend(feed_quotes)

        except Exception as exc:

            errors.append(
                f"{bookmaker}: {exc}"
            )

    return quotes, errors
