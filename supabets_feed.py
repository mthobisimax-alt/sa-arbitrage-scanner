import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import httpx


def _local(tag):
    return str(tag or "").split("}",1)[-1].lower()


def _text(node, *names):
    wanted={n.lower() for n in names}
    for el in node.iter():
        if _local(el.tag) in wanted and el.text:
            value=el.text.strip()
            if value:
                return value
    return ""


def _float(value):
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _now():
    return datetime.now(timezone.utc).isoformat()


def parse_active_events(xml_text):
    root=ET.fromstring(xml_text)
    events=[]
    seen=set()
    for node in root.iter():
        event_id=_text(node,"eventid","event_id","subeventid","sub_event_id","subevent")
        event_name=_text(node,"eventname","event_name","subeventname","sub_event_name","name")
        sport=_text(node,"sport","sportname","sport_name")
        if not event_id or not event_name:
            continue
        key=(event_id,event_name)
        if key in seen:
            continue
        seen.add(key)
        events.append({"event_id":event_id,"event_name":event_name,"sport":sport})
    return events


def parse_event_odds(xml_text, bookmaker="Supabets"):
    root=ET.fromstring(xml_text)
    quotes=[]
    event_name=_text(root,"eventname","event_name","subeventname","sub_event_name","name")
    event_id=_text(root,"eventid","event_id","subeventid","sub_event_id","subevent")
    sport=_text(root,"sport","sportname","sport_name") or "soccer"
    league=_text(root,"league","leaguename","league_name","tournament","tournamentname")
    for node in root.iter():
        price=_float(_text(node,"odd","odds","price","decimalodd","decimal_odds"))
        if not price or price<=1:
            continue
        selection=_text(node,"selection","selectionname","selection_name","runner","runnername","outcome","outcomename")
        market=_text(node,"market","marketname","market_name","marketclass","marketclassname","bettype","bettypename")
        if not selection or not market:
            continue
        line=_text(node,"handicap","line","points","total")
        period=_text(node,"period","periodname","period_name") or "full_time"
        market_id=_text(node,"marketid","market_id","marketclassid","market_class_id")
        if not market_id:
            market_id=f"supabets:{market}|{period}|{line}"
        quotes.append({
            "source":"Supabets Direct",
            "bookmaker":bookmaker,
            "bookmaker_url":"",
            "bookmaker_host":"mobile.supabets.co.za",
            "sa_link_status":"verified_sa_domain",
            "event_id":event_id or event_name,
            "sport":sport.lower(),
            "league":league,
            "event_name":event_name or event_id,
            "market":market,
            "market_id":market_id,
            "market_length":0,
            "market_type":market,
            "period":period,
            "line":line,
            "selection":selection,
            "odds":price,
            "timestamp":_now()
        })
    return quotes


async def probe_supabets(cfg):
    base=str(cfg.get("base_url") or "https://mobile.supabets.co.za/Controls/MarketWS.asmx").rstrip("/")
    timeout=max(5.0,min(20.0,float(cfg.get("timeout_seconds",12))))
    result={"provider":"Supabets Direct","reachable":False,"operations":[],"events":[],"quotes":[],"errors":[]}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout),follow_redirects=True) as client:
            landing=await client.get(base)
            landing.raise_for_status()
            result["reachable"]=True
            text=landing.text
            for name in ("getClientActiveEventsByGroup","getClientOddsBySubeEvent","GetListOdds_OddLessThan"):
                if name.lower() in text.lower():
                    result["operations"].append(name)

            group_id=str(cfg.get("group_id") or "").strip()
            if cfg.get("probe_active_events",False) and group_id:
                r=await client.get(base+"/getClientActiveEventsByGroup",params={"groupID":group_id})
                if r.status_code<400:
                    try:
                        result["events"]=parse_active_events(r.text)
                    except Exception as exc:
                        result["errors"].append(f"Active-events XML parse failed: {type(exc).__name__}")
                else:
                    result["errors"].append(f"Active-events request returned HTTP {r.status_code}")
    except Exception as exc:
        result["errors"].append(f"Supabets service probe failed: {type(exc).__name__}")
    return result
