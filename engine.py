from collections import defaultdict
from datetime import datetime, timezone
import re

def normalize_text(value):
    if not value: return ""
    value=str(value).lower().strip(); value=re.sub(r"[^a-z0-9.+-]+"," ",value); return " ".join(value.split())
def event_key(q):
    event_id=normalize_text(q.get("event_id",""))
    if event_id: return event_id
    name=normalize_text(q.get("event_name","")); parts=name.split(" v ",1) if " v " in name else name.split(" vs ",1) if " vs " in name else []
    return f"{parts[0].strip()}|{parts[1].strip()}" if len(parts)==2 else name
def fresh(q,max_age):
    ts=q.get("timestamp")
    if not ts: return True
    try: return (datetime.now(timezone.utc)-datetime.fromisoformat(ts.replace("Z","+00:00"))).total_seconds()<=max_age
    except Exception: return False
def _identity(q): return (event_key(q),str(q.get("market_id") or ""),normalize_text(q.get("market_type","")),normalize_text(q.get("period","")),normalize_text(q.get("line","")),int(q.get("market_length") or 0))
def _groups(quotes,max_age):
    groups=defaultdict(list)
    for q in quotes:
        try:
            if float(q["odds"])<=1 or not fresh(q,max_age) or not q.get("market_id") or int(q.get("market_length") or 0) not in (2,3): continue
            groups[_identity(q)].append(q)
        except Exception: continue
    return groups
def _complete_group(best,rows):
    if not best or not rows: return False
    identity=_identity(rows[0]); expected=identity[-1]
    if expected not in (2,3) or len(best)!=expected or any(_identity(q)!=identity for q in rows): return False
    labels={normalize_text(q.get("selection")) for q in best.values()}; return len(labels)==expected and all(labels)
def _opportunity(best,min_margin,preferred_anchor=None):
    if len({normalize_text(q.get("bookmaker")) for q in best.values()})<2: return None
    inverse_sum=sum(1/float(q["odds"]) for q in best.values())
    if inverse_sum>=1: return None
    margin=((1/inverse_sum)-1)*100
    if margin<min_margin or margin>100: return None
    first=next(iter(best.values())); warning=margin>=10
    legs=[{"selection":q["selection"],"bookmaker":q["bookmaker"],"bookmaker_url":q.get("bookmaker_url",""),"bookmaker_host":q.get("bookmaker_host",""),"sa_link_status":q.get("sa_link_status","not_applicable"),"odds":float(q["odds"]),"timestamp":q.get("timestamp")} for q in best.values()]
    return {"event_name":first.get("event_name"),"sport":first.get("sport"),"league":first.get("league"),"market":first.get("market"),"market_id":first.get("market_id"),"market_type":first.get("market_type"),"period":first.get("period"),"line":first.get("line",""),"inverse_sum":round(inverse_sum,8),"margin":round(margin,4),"verify_warning":warning,"warning_reason":"Unusually high margin — verify every bookmaker price and settlement rule before betting." if warning else "","preferred_anchor":preferred_anchor or "","legs":legs}
def market_diagnostics(quotes,max_age=20):
    groups=_groups(quotes,max_age)
    complete=0
    incomplete=0
    for rows in groups.values():
        best={}
        for q in rows:
            try:
                selection=normalize_text(q.get("selection")); odds=float(q["odds"])
            except Exception:
                continue
            if selection and (selection not in best or odds>float(best[selection]["odds"])):
                best[selection]=q
        if _complete_group(best,rows): complete+=1
        else: incomplete+=1
    return {
        "markets_checked": len(groups),
        "complete_same_line_markets": complete,
        "incomplete_markets": incomplete
    }

def find_arbs(quotes,max_age=20,min_margin=0.10):
    opportunities=[]
    for rows in _groups(quotes,max_age).values():
        best={}
        for q in rows:
            selection=normalize_text(q.get("selection")); odds=float(q["odds"])
            if selection and (selection not in best or odds>float(best[selection]["odds"])): best[selection]=q
        if _complete_group(best,rows):
            opp=_opportunity(best,min_margin)
            if opp: opportunities.append(opp)
    return sorted(opportunities,key=lambda x:x["margin"],reverse=True)
def find_preferred_arbs(quotes,preferred_bookmakers,max_age=20,min_margin=0.10):
    wanted={normalize_text(x) for x in preferred_bookmakers if x}; opportunities=[]; seen=set()
    for rows in _groups(quotes,max_age).values():
        expected=int(rows[0].get("market_length") or 0); selections={normalize_text(q.get("selection")) for q in rows if q.get("selection")}
        if expected not in (2,3) or len(selections)!=expected: continue
        global_best={}
        for q in rows:
            sel=normalize_text(q.get("selection")); odds=float(q["odds"])
            if sel and (sel not in global_best or odds>float(global_best[sel]["odds"])): global_best[sel]=q
        if not _complete_group(global_best,rows): continue
        for anchor in rows:
            book=normalize_text(anchor.get("bookmaker")); anchor_sel=normalize_text(anchor.get("selection"))
            if book not in wanted or not anchor_sel: continue
            candidate=dict(global_best); candidate[anchor_sel]=anchor
            if len(candidate)!=expected: continue
            opp=_opportunity(candidate,min_margin,preferred_anchor=anchor.get("bookmaker"))
            if not opp: continue
            signature=(_identity(anchor),tuple(sorted((normalize_text(l["selection"]),normalize_text(l["bookmaker"]),float(l["odds"])) for l in opp["legs"])))
            if signature not in seen: seen.add(signature); opportunities.append(opp)
    return sorted(opportunities,key=lambda x:x["margin"],reverse=True)
