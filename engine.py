from collections import defaultdict
from datetime import datetime, timezone

def fresh(q, max_age):
    ts=q.get("timestamp")
    if not ts: return True
    try:
        t=datetime.fromisoformat(ts.replace("Z","+00:00"))
        return (datetime.now(timezone.utc)-t).total_seconds() <= max_age
    except: return False

def find_arbs(quotes,max_age=20,min_margin=0.10):
    groups=defaultdict(list)
    for q in quotes:
        try:
            if float(q["odds"])<=1 or not fresh(q,max_age): continue
            groups[(q.get("event_id"),q.get("market"),q.get("line"))].append(q)
        except: pass
    out=[]
    for rows in groups.values():
        best={}
        for q in rows:
            s=q.get("selection")
            if s and (s not in best or float(q["odds"])>float(best[s]["odds"])): best[s]=q
        if len(best) not in (2,3): continue
        inv=sum(1/float(q["odds"]) for q in best.values())
        if inv<1:
            margin=(1/inv-1)*100
            if margin>=min_margin:
                b=next(iter(best.values()))
                out.append({"event_name":b.get("event_name"),"sport":b.get("sport"),
                "league":b.get("league"),"market":b.get("market"),
                "inverse_sum":round(inv,8),"margin":round(margin,4),
                "legs":[{"selection":q["selection"],"bookmaker":q["bookmaker"],"odds":float(q["odds"])} for q in best.values()]})
    return sorted(out,key=lambda x:x["margin"],reverse=True)
