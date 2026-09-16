from collections import defaultdict
from datetime import datetime, timezone
import re


def normalize_text(value):
    if not value:
        return ""
    value = str(value).lower().strip()
    value = re.sub(r"[^a-z0-9.]+", " ", value)
    return " ".join(value.split())


def event_key(q):
    name = normalize_text(q.get("event_name", ""))
    if " v " in name:
        parts = name.split(" v ", 1)
    elif " vs " in name:
        parts = name.split(" vs ", 1)
    else:
        parts = []
    if len(parts) == 2:
        return f"{parts[0].strip()}|{parts[1].strip()}"
    return normalize_text(q.get("event_id", ""))


def fresh(q, max_age):
    ts = q.get("timestamp")
    if not ts:
        return True
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() <= max_age
    except Exception:
        return False


def find_arbs(quotes, max_age=20, min_margin=0.10):
    groups = defaultdict(list)
    for q in quotes:
        try:
            odds = float(q["odds"])
            if odds <= 1 or not fresh(q, max_age):
                continue
            market_key = str(q.get("market_id") or normalize_text(q.get("market", "")))
            key = (event_key(q), market_key, normalize_text(q.get("line", "")))
            groups[key].append(q)
        except Exception:
            continue

    opportunities = []
    for rows in groups.values():
        best = {}
        for q in rows:
            selection = normalize_text(q.get("selection"))
            if not selection:
                continue
            odds = float(q["odds"])
            if selection not in best or odds > float(best[selection]["odds"]):
                best[selection] = q

        # Genuine mutually-exclusive football arb groups are normally 2-way or 3-way.
        if len(best) not in (2, 3):
            continue
        inverse_sum = sum(1 / float(q["odds"]) for q in best.values())
        if inverse_sum >= 1:
            continue
        margin = ((1 / inverse_sum) - 1) * 100
        if margin < min_margin:
            continue

        first = next(iter(best.values()))
        legs = [{
            "selection": q["selection"],
            "bookmaker": q["bookmaker"],
            "bookmaker_url": q.get("bookmaker_url", ""),
            "odds": float(q["odds"]),
        } for q in best.values()]
        opportunities.append({
            "event_name": first.get("event_name"),
            "sport": first.get("sport"),
            "league": first.get("league"),
            "market": first.get("market"),
            "market_id": first.get("market_id"),
            "line": first.get("line", ""),
            "inverse_sum": round(inverse_sum, 8),
            "margin": round(margin, 4),
            "legs": legs,
        })
    return sorted(opportunities, key=lambda x: x["margin"], reverse=True)
