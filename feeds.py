import os
from datetime import datetime, timezone

import httpx


STANDARD_FIELDS = (
    "bookmaker",
    "event_id",
    "sport",
    "league",
    "event_name",
    "market",
    "line",
    "selection",
    "odds",
    "timestamp",
)


def _resolve_env(value):
    """Resolve values written as env:VARIABLE_NAME without exposing secrets in GitHub."""
    if not isinstance(value, str):
        return value

    if not value.startswith("env:"):
        return value

    env_name = value[4:].strip()
    if not env_name:
        return ""

    return os.getenv(env_name, "")


def _resolved_headers(headers):
    return {
        str(key): str(_resolve_env(value))
        for key, value in (headers or {}).items()
        if _resolve_env(value) not in (None, "")
    }


def _extract_rows(data, rows_key=None):
    """Return a list of quote/event rows from a provider response."""
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    if rows_key:
        current = data
        for part in str(rows_key).split("."):
            if not isinstance(current, dict):
                return []
            current = current.get(part)
        return current if isinstance(current, list) else []

    for key in ("odds", "events", "data", "results"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows

    return []


def _standard_quote(row, default_bookmaker="Unknown"):
    """Convert an already-flat provider row to the quote format used by engine.py."""
    now = datetime.now(timezone.utc).isoformat()

    bookmaker = row.get("bookmaker") or default_bookmaker
    event_id = row.get("event_id") or row.get("id")
    home = row.get("home_team") or row.get("home")
    away = row.get("away_team") or row.get("away")
    event_name = row.get("event_name")

    if not event_name and home and away:
        event_name = f"{home} v {away}"

    selection = row.get("selection")
    odds = row.get("odds")

    if not bookmaker or not selection or odds is None:
        return None

    try:
        odds = float(odds)
    except (TypeError, ValueError):
        return None

    if odds <= 1:
        return None

    return {
        "bookmaker": str(bookmaker),
        "event_id": str(event_id) if event_id is not None else "",
        "sport": row.get("sport", "soccer"),
        "league": row.get("league", ""),
        "event_name": event_name or "",
        "market": row.get("market", "match_result"),
        "line": row.get("line", ""),
        "selection": selection,
        "odds": odds,
        "timestamp": row.get("timestamp", now),
    }


def adapt_flat_json(data, cfg):
    """Adapter for flat JSON rows. A single response may contain multiple bookmakers."""
    rows = _extract_rows(data, cfg.get("rows_key"))
    default_bookmaker = cfg.get("bookmaker", "Unknown")
    allowed = {
        str(name).lower()
        for name in cfg.get("bookmakers", [])
        if name
    }

    quotes = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        quote = _standard_quote(row, default_bookmaker)
        if not quote:
            continue

        if allowed and quote["bookmaker"].lower() not in allowed:
            continue

        quotes.append(quote)

    return quotes


ADAPTERS = {
    "flat_json": adapt_flat_json,
    "json": adapt_flat_json,
}


async def fetch_provider(cfg):
    """Fetch one configured provider once, then normalize its response through an adapter."""
    provider = cfg.get("name") or cfg.get("bookmaker") or "Unknown provider"
    url = _resolve_env(cfg.get("url", ""))

    if not url:
        raise RuntimeError(f"No feed URL configured for {provider}")

    adapter_name = cfg.get("adapter", cfg.get("type", "flat_json"))
    adapter = ADAPTERS.get(adapter_name)
    if not adapter:
        raise RuntimeError(f"Unsupported feed adapter '{adapter_name}' for {provider}")

    headers = _resolved_headers(cfg.get("headers", {}))
    params = {
        str(key): _resolve_env(value)
        for key, value in cfg.get("params", {}).items()
        if _resolve_env(value) not in (None, "")
    }

    timeout = float(cfg.get("timeout_seconds", 15))

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

    quotes = adapter(data, cfg)
    if not quotes:
        raise RuntimeError(f"{provider} returned no usable quotes")

    return quotes


async def fetch_json_feed(cfg):
    """Backward-compatible wrapper for the original per-bookmaker JSON configuration."""
    legacy_cfg = dict(cfg)
    legacy_cfg.setdefault("adapter", "flat_json")
    return await fetch_provider(legacy_cfg)


async def fetch_all_feeds(config):
    """
    Fetch all enabled sources.

    Preferred configuration uses `providers`, allowing one API response to carry
    Hollywoodbets, Betway ZA and Supabets together. The original `feeds` format
    remains supported until a live provider is selected.
    """
    quotes = []
    errors = []

    providers = config.get("providers")
    sources = providers if isinstance(providers, list) else config.get("feeds", [])

    for cfg in sources:
        if not cfg.get("enabled", False):
            continue

        source_name = cfg.get("name") or cfg.get("bookmaker") or "Unknown provider"

        try:
            source_quotes = await fetch_provider(cfg)
            quotes.extend(source_quotes)
        except Exception as exc:
            errors.append(f"{source_name}: {type(exc).__name__}: {exc}")

    if not any(cfg.get("enabled", False) for cfg in sources):
        errors.append("No live odds provider is enabled")

    return quotes, errors
