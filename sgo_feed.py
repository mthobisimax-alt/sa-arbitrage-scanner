import os
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx

SA_BOOKMAKER_HOSTS={
    "betway":{"betway.co.za","www.betway.co.za","cdn.betway.co.za","cdn2.betway.co.za","reg.betway.co.za"},
    "betway za":{"betway.co.za","www.betway.co.za","cdn.betway.co.za","cdn2.betway.co.za","reg.betway.co.za"},
    "sportingbet":{"sportingbet.co.za","www.sportingbet.co.za","sports.sportingbet.co.za"},
}

def _host(url):
    try: return (urlparse(str(url)).hostname or "").lower().strip(".")
    except Exception: return ""

def _sa_link_status(bookmaker,url):
    book=str(bookmaker or "").strip().lower(); host=_host(url)
    if book not in SA_BOOKMAKER_HOSTS: return "not_applicable",host
    if host in SA_BOOKMAKER_HOSTS[book]: return "verified_sa_domain",host
    if host: return "international_or_unverified",host
    return "no_direct_link",host

def _iso(value):
    if not value: return datetime.now(timezone.utc).isoformat()
    return str(value)

def _american_to_decimal(value):
    try: a=float(value)
    except (TypeError,ValueError): return None
    if a==0: return None
    return 1+(a/100.0 if a>0 else 100.0/abs(a))

def _team(event,side):
    team=((event.get("teams") or {}).get(side) or {})
    names=team.get("names") or {}
    return names.get("long") or names.get("medium") or names.get("short") or side.title()

def _selection(odd,home,away):
    side=str(odd.get("sideID") or "").lower()
    return {"home":home,"away":away,"draw":"Draw","tie":"Draw","x":"Draw","over":"Over","under":"Under","yes":"Yes","no":"No"}.get(side,side.title() if side else "")

def _canon_num(value,absolute=False):
    if value in (None,""): return ""
    try:
        x=float(value)
        if absolute: x=abs(x)
        if x==0: x=0.0
        return (f"{x:.6f}").rstrip("0").rstrip(".")
    except (TypeError,ValueError): return str(value).strip()

def _market_entity(odd,bet_type):
    stat=str(odd.get("statID") or "").strip()
    entity=str(odd.get("statEntityID") or "all").strip()
    # Match-level moneyline/spread sides use home/away entities but belong to one market.
    if stat=="points" and bet_type in ("ml","sp") and entity.lower() in ("home","away","all"):
        return "match"
    return entity

def adapt_events(payload,max_events=12):
    rows=(payload or {}).get("data") if isinstance(payload,dict) else None
    if not isinstance(rows,list): return []
    candidates=[]
    for event in rows[:max_events]:
        if not isinstance(event,dict): continue
        event_id=str(event.get("eventID") or "")
        if not event_id: continue
        home=_team(event,"home"); away=_team(event,"away")
        event_name=f"{home} v {away}"; league=str(event.get("leagueID") or ""); sport=str(event.get("sportID") or "SOCCER").lower()
        for odd_id,odd in (event.get("odds") or {}).items():
            if not isinstance(odd,dict) or odd.get("ended") is True or odd.get("cancelled") is True: continue
            bet_type=str(odd.get("betTypeID") or "").lower(); period=str(odd.get("periodID") or "game")
            stat=str(odd.get("statID") or "").strip(); entity=_market_entity(odd,bet_type)
            selection=_selection(odd,home,away)
            if not selection or bet_type not in ("ml","sp","ou","yn"): continue
            market_name=str(odd.get("marketName") or odd_id)
            for bookmaker,book_data in (odd.get("byBookmaker") or {}).items():
                if not isinstance(book_data,dict) or book_data.get("available") is False: continue
                decimal=_american_to_decimal(book_data.get("odds"))
                if not decimal or decimal<=1: continue
                if bet_type=="ou":
                    line=_canon_num(book_data.get("overUnder",odd.get("bookOverUnder")))
                elif bet_type=="sp":
                    line=_canon_num(book_data.get("spread",odd.get("bookSpread")),absolute=True)
                else:
                    line=""
                # Never combine totals/spreads from different bookmaker-specific lines.
                if bet_type in ("ou","sp") and not line: continue
                identity=f"sgo:{stat}|{entity}|{period}|{bet_type}|{line}"
                url=book_data.get("deeplink") or ""; sa_status,link_host=_sa_link_status(bookmaker,url)
                candidates.append({
                    "source":"SportsGameOdds","bookmaker":str(bookmaker),"bookmaker_url":url,"bookmaker_host":link_host,"sa_link_status":sa_status,
                    "event_id":event_id,"sport":sport,"league":league,"event_name":event_name,"market":market_name,"market_id":identity,
                    "market_type":bet_type,"period":period,"line":line,"selection":selection,"odds":decimal,"timestamp":_iso(book_data.get("lastUpdatedAt"))
                })
    # Determine complete market length only after bookmaker-specific line normalization.
    selections_by_key={}
    for q in candidates:
        key=(q["event_id"],q["market_id"])
        selections_by_key.setdefault(key,set()).add(str(q["selection"]).lower())
    quotes=[]
    for q in candidates:
        n=len(selections_by_key.get((q["event_id"],q["market_id"]),set()))
        if n not in (2,3): continue
        q["market_length"]=n
        quotes.append(q)
    return quotes

async def fetch_sportsgameodds_fixed(config):
    cfg=next((p for p in config.get("providers",[]) if p.get("enabled") and p.get("adapter")=="sportsgameodds_v2"),None)
    if not cfg: return [],["SportsGameOdds provider is not enabled"]
    key_ref=str(cfg.get("api_key") or "env:SPORTSGAMEODDS_API_KEY")
    api_key=os.getenv(key_ref[4:].strip(),"") if key_ref.startswith("env:") else key_ref
    if not api_key: return [],["SportsGameOdds API key is not configured"]
    base=str(cfg.get("base_url") or "https://api.sportsgameodds.com/v2").rstrip("/")
    max_events=max(1,min(100,int(cfg.get("max_events",12))))
    params={"apiKey":api_key,"oddsAvailable":"true","limit":max_events}
    league_id=str(cfg.get("league_id") or "").strip()
    if league_id: params["leagueID"]=league_id
    else: params["sportID"]=cfg.get("sport_id","SOCCER")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(float(cfg.get("timeout_seconds",15))),follow_redirects=True) as client:
            response=await client.get(f"{base}/events",params=params)
            if response.status_code>=400:
                detail=""
                try:
                    body=response.json(); detail=str(body.get("message") or body.get("error") or body.get("detail") or "") if isinstance(body,dict) else ""
                except Exception: detail=response.text[:160]
                detail=" ".join(detail.split())[:180]
                return [],[f"SportsGameOdds HTTP {response.status_code}"+(f": {detail}" if detail else "")]
            data=response.json()
        quotes=adapt_events(data,max_events=max_events)
        if not quotes: return [],["SportsGameOdds returned events but no complete same-line soccer markets"]
        return quotes,[]
    except Exception as exc:
        return [],[f"SportsGameOdds fallback failed: {type(exc).__name__}"]
