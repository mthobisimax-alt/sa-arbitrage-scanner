from collections import defaultdict
from datetime import datetime, timezone
import re


def normalize_text(value):
    if not value: return ""
    value=str(value).lower().strip(); value=re.sub(r"[^a-z0-9.+-]+"," ",value); return " ".join(value.split())


def event_key(q):
    event_id=normalize_text(q.get("event_id",""))
    if event_id: return event_id
    name=normalize_text(q.get("event_name",""))
    if " v " in name: parts=name.split(" v ",1)
    elif " vs " in name: parts=name.split(" vs ",1)
    else: parts=[]
    if len(parts)==2: return f"{parts[0].strip()}|{parts[1].strip()}"
    return name


def fresh(q,max_age):
    ts=q.get("timestamp")
    if not ts: return True
    try:
        t=datetime.fromisoformat(ts.replace("Z","+00:00")); return (datetime.now(timezone.utc)-t).total_seconds()<=max_age
    except Exception: return False


def _identity(q):
    return (
        event_key(q),
        str(q.get("market_id") or ""),
        normalize_text(q.get("market_type","")),
        normalize_text(q.get("period","")),
        normalize_text(q.get("line","")),
        int(q.get("market_length") or 0),
    )


def _complete_group(best,rows):
    if not best or not rows: return False
    identity=_identity(rows[0]); expected=identity[-1]
    if expected not in (2,3) or len(best)!=expected: return False
    if any(_identity(q)!=identity for q in rows): return False
    labels={normalize_text(q.get("selection")) for q in best.values()}
    if len(labels)!=expected or any(not x for x in labels): return False
    return True


def find_arbs(quotes,max_age=20,min_margin=0.10):
    groups=defaultdict(list)
    for q in quotes:
        try:
            odds=float(q["odds"])
            if odds<=1 or not fresh(q,max_age): continue
            if not q.get("market_id") or int(q.get("market_length") or 0) not in (2,3): continue
            groups[_identity(q)].append(q)
        except Exception: continue

    opportunities=[]
    for rows in groups.values():
        best={}
        for q in rows:
            selection=normalize_text(q.get("selection"))
            if not selection: continue
            odds=float(q["odds"])
            if selection not in best or odds>float(best[selection]["odds"]): best[selection]=q
        if not _complete_group(best,rows): continue
        if len({normalize_text(q.get("bookmaker")) for q in best.values()})<2: continue
        inverse_sum=sum(1/float(q["odds"]) for q in best.values())
        if inverse_sum>=1: continue
        margin=((1/inverse_sum)-1)*100
        if margin<min_margin or margin>100: continue
        first=next(iter(best.values()))
        legs=[{"selection":q["selection"],"bookmaker":q["bookmaker"],"bookmaker_url":q.get("bookmaker_url",""),"odds":float(q["odds"]),"timestamp":q.get("timestamp")} for q in best.values()]
        warning = margin >= 10
        opportunities.append({"event_name":first.get("event_name"),"sport":first.get("sport"),"league":first.get("league"),"market":first.get("market"),"market_id":first.get("market_id"),"market_type":first.get("market_type"),"period":first.get("period"),"line":first.get("line",""),"inverse_sum":round(inverse_sum,8),"margin":round(margin,4),"verify_warning":warning,"warning_reason":"Unusually high margin — verify every bookmaker price and settlement rule before betting." if warning else "","legs":legs})
    return sorted(opportunities,key=lambda x:x["margin"],reverse=True)
