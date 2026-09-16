from collections import defaultdict
from datetime import datetime, timezone
import re


def normalize_text(value):
    if not value: return ""
    value = str(value).lower().strip()
    value = re.sub(r"[^a-z0-9.]+", " ", value)
    return " ".join(value.split())


def event_key(q):
    name = normalize_text(q.get("event_name", ""))
    if " v " in name: parts = name.split(" v ", 1)
    elif " vs " in name: parts = name.split(" vs ", 1)
    else: parts = []
    if len(parts) == 2: return f"{parts[0].strip()}|{parts[1].strip()}"
    return normalize_text(q.get("event_id", ""))


def fresh(q, max_age):
    ts = q.get("timestamp")
    if not ts: return True
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() <= max_age
    except Exception: return False


def _simple_selection(value):
    s = normalize_text(value)
    if not s or len(s) > 80: return False
    # Provider/internal identifiers are not safe betting selections.
    if "|" in str(value) or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{20,}", str(value).lower()): return False
    return True


def _validated_group(best):
    """Only allow complete, recognisable 2-way/3-way football markets."""
    if len(best) not in (2, 3): return False
    labels = {normalize_text(q.get("selection")) for q in best.values()}
    if any(not _simple_selection(q.get("selection")) for q in best.values()): return False

    if len(best) == 2:
        # Safe generic two-way families. Unknown IDs/names are rejected.
        if labels == {"yes", "no"}: return True
        if labels == {"over", "under"}: return True
        # Some providers include the line in the selection text.
        if any(x.startswith("over ") for x in labels) and any(x.startswith("under ") for x in labels): return True
        return False

    # Three-way result: require Home/Draw/Away semantics. Team names may be used for home/away.
    rows = list(best.values())
    first = rows[0]
    event = str(first.get("event_name") or "")
    if " v " in event: home, away = [normalize_text(x) for x in event.split(" v ", 1)]
    elif " vs " in event: home, away = [normalize_text(x) for x in event.split(" vs ", 1)]
    else: return False
    return labels == {home, "draw", away}


def find_arbs(quotes, max_age=20, min_margin=0.10):
    groups = defaultdict(list)
    for q in quotes:
        try:
            odds = float(q["odds"])
            if odds <= 1 or not fresh(q, max_age): continue
            market_key = str(q.get("market_id") or normalize_text(q.get("market", "")))
            key = (event_key(q), market_key, normalize_text(q.get("line", "")))
            groups[key].append(q)
        except Exception: continue

    opportunities = []
    for rows in groups.values():
        best = {}
        for q in rows:
            selection = normalize_text(q.get("selection"))
            if not selection: continue
            odds = float(q["odds"])
            if selection not in best or odds > float(best[selection]["odds"]): best[selection] = q

        if not _validated_group(best): continue
        # A real cross-book arbitrage must use at least two bookmakers.
        if len({normalize_text(q.get("bookmaker")) for q in best.values()}) < 2: continue

        inverse_sum = sum(1 / float(q["odds"]) for q in best.values())
        if inverse_sum >= 1: continue
        margin = ((1 / inverse_sum) - 1) * 100
        if margin < min_margin: continue
        # Sanity guard: extreme margins almost always indicate incompatible/malformed outcomes.
        if margin > 100: continue

        first = next(iter(best.values()))
        legs = [{"selection": q["selection"], "bookmaker": q["bookmaker"], "bookmaker_url": q.get("bookmaker_url", ""), "odds": float(q["odds"])} for q in best.values()]
        opportunities.append({"event_name": first.get("event_name"), "sport": first.get("sport"), "league": first.get("league"), "market": first.get("market"), "market_id": first.get("market_id"), "line": first.get("line", ""), "inverse_sum": round(inverse_sum, 8), "margin": round(margin, 4), "legs": legs})
    return sorted(opportunities, key=lambda x: x["margin"], reverse=True)
