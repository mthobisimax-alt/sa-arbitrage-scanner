import os
import asyncio
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
import httpx

SA_BOOKMAKER_HOSTS={"betway":{"betway.co.za","www.betway.co.za","cdn.betway.co.za","cdn2.betway.co.za","reg.betway.co.za"},"betway za":{"betway.co.za","www.betway.co.za","cdn.betway.co.za","cdn2.betway.co.za","reg.betway.co.za"},"sportingbet":{"sportingbet.co.za","www.sportingbet.co.za","sports.sportingbet.co.za"}}

def _resolve_env(value):
    if not isinstance(value,str): return value
    if not value.startswith("env:"): return value
    return os.getenv(value[4:].strip(),"")

def _iso_timestamp(value):
    if not value: return datetime.now(timezone.utc).isoformat()
    if isinstance(value,(int,float)):
        if value>10_000_000_000: value=value/1000
        return datetime.fromtimestamp(value,timezone.utc).isoformat()
    return str(value)

def _host(url):
    try: return (urlparse(str(url)).hostname or "").lower().strip(".")
    except Exception: return ""

def _sa_link_status(bookmaker,url):
    book=str(bookmaker or "").strip().lower(); host=_host(url)
    if book not in SA_BOOKMAKER_HOSTS: return "not_applicable",host
    if host in SA_BOOKMAKER_HOSTS[book]: return "verified_sa_domain",host
    if host: return "international_or_unverified",host
    return "no_direct_link",host

def _build_market_catalog(rows,sport_id=10):
    catalog={}
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict) or int(row.get("sportId") or -1)!=sport_id: continue
        mid=str(row.get("marketId")); outcomes={str(o.get("outcomeId")):str(o.get("outcomeName") or "") for o in (row.get("outcomes") or []) if isinstance(o,dict)}
        catalog[mid]={"name":str(row.get("marketName") or f"Football Market {mid}"),"length":int(row.get("marketLength") or len(outcomes)),"line":"" if row.get("handicap") is None else str(row.get("handicap")),"period":str(row.get("period") or ""),"type":str(row.get("marketType") or ""),"player_prop":bool(row.get("playerProp")),"outcomes":outcomes}
    return catalog

def _selection_name(meta,outcome_id,home,away):
    label=str(meta.get("outcomes",{}).get(str(outcome_id),"")).strip(); low=label.lower()
    if low in ("1","home"): return home
    if low in ("x","draw"): return "Draw"
    if low in ("2","away"): return away
    return label

def adapt_oddspapi_fixture(data,catalog,max_quotes=12000):
    if not isinstance(data,dict): return []
    fixture_id=str(data.get("fixtureId","")); home=data.get("participant1Name",""); away=data.get("participant2Name",""); event_name=f"{home} v {away}" if home and away else fixture_id; league=data.get("tournamentName",""); sport=data.get("sportName","Soccer"); fallback_ts=data.get("updatedAt"); quotes=[]
    for bookmaker,book_data in (data.get("bookmakerOdds") or {}).items():
        if not isinstance(book_data,dict) or book_data.get("suspended") is True: continue
        fixture_url=book_data.get("fixturePath") or ""; sa_status,link_host=_sa_link_status(bookmaker,fixture_url)
        for market_id,market_data in (book_data.get("markets") or {}).items():
            meta=catalog.get(str(market_id))
            if not meta or meta["player_prop"] or meta["length"] not in (2,3): continue
            if not isinstance(market_data,dict) or market_data.get("marketActive") is False: continue
            for outcome_id,outcome_data in (market_data.get("outcomes") or {}).items():
                selection=_selection_name(meta,outcome_id,home,away)
                if not selection or not isinstance(outcome_data,dict): continue
                players=outcome_data.get("players") or {}; player=players.get("0") or players.get(0)
                if not isinstance(player,dict) or player.get("active") is False: continue
                try: price=float(player.get("price"))
                except (TypeError,ValueError): continue
                if price<=1: continue
                quotes.append({"bookmaker":str(bookmaker),"bookmaker_url":fixture_url,"bookmaker_host":link_host,"sa_link_status":sa_status,"event_id":fixture_id,"sport":str(sport).lower(),"league":league,"event_name":event_name,"market":meta["name"],"market_id":str(market_id),"market_length":meta["length"],"market_type":meta["type"],"period":meta["period"],"line":meta["line"],"selection":selection,"odds":price,"timestamp":_iso_timestamp(player.get("bookmakerChangedAt") or player.get("changedAt") or fallback_ts)})
                if len(quotes)>=max_quotes: return quotes
    return quotes

def _preferred_present(quotes,preferred):
    wanted={str(x).strip().lower() for x in preferred}; return sorted({str(q.get("bookmaker","")).strip().lower() for q in quotes if str(q.get("bookmaker","")).strip().lower() in wanted})

def _oddspapi_cfg(config):
    for cfg in config.get("providers",[]):
        if cfg.get("enabled",False) and cfg.get("adapter","oddspapi_v4")=="oddspapi_v4": return cfg
    return None

async def fetch_oddspapi_account(config):
    """Read OddsPapi quota without ever exposing the API key in UI/errors."""
    cfg=_oddspapi_cfg(config)
    if not cfg: return {"available":False,"error":"OddsPapi provider is not enabled"}
    api_key=_resolve_env(cfg.get("api_key","env:ODDSPAPI_API_KEY"))
    if not api_key: return {"available":False,"error":"ODDSPAPI_API_KEY is not configured"}
    base_url=cfg.get("base_url","https://api.oddspapi.io/v4").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0),follow_redirects=True) as client:
            response=None
            for attempt in range(3):
                response=await client.get(f"{base_url}/account",params={"apiKey":api_key})
                if response.status_code!=429: break
                wait=1.2
                try:
                    body=response.json(); wait=max(wait,float((body.get("error") or {}).get("retryMs",0))/1000.0+0.15)
                except Exception: pass
                if attempt<2: await asyncio.sleep(min(wait,3.0))
            if response is None: return {"available":False,"error":"OddsPapi quota check unavailable","checked_at":datetime.now(timezone.utc).isoformat()}
            if response.status_code==429: return {"available":False,"error":"OddsPapi quota check temporarily rate-limited; retrying on the next scan","checked_at":datetime.now(timezone.utc).isoformat()}
            if response.status_code>=400: return {"available":False,"error":f"OddsPapi quota check returned HTTP {response.status_code}","checked_at":datetime.now(timezone.utc).isoformat()}
            data=response.json()
        subscriptions=data.get("subscriptions") or []
        active=next((s for s in subscriptions if isinstance(s,dict) and s.get("is_active") is True),None)
        if active is None and subscriptions: active=subscriptions[0] if isinstance(subscriptions[0],dict) else None
        if not active: return {"available":False,"error":"No OddsPapi subscription information returned"}
        limit=active.get("request_limit"); used=active.get("request_count")
        try: remaining=max(0,int(limit)-int(used)) if limit is not None and used is not None else None
        except (TypeError,ValueError): remaining=None
        return {"available":True,"request_limit":limit,"request_count":used,"requests_remaining":remaining,"last_request":active.get("last_request"),"valid_from":active.get("valid_from"),"valid_until":active.get("valid_until"),"checked_at":datetime.now(timezone.utc).isoformat()}
    except Exception:
        return {"available":False,"error":"OddsPapi quota check temporarily unavailable","checked_at":datetime.now(timezone.utc).isoformat()}

async def fetch_oddspapi(cfg):
    api_key=_resolve_env(cfg.get("api_key","env:ODDSPAPI_API_KEY"))
    if not api_key: raise RuntimeError("ODDSPAPI_API_KEY is not configured")
    base_url=cfg.get("base_url","https://api.oddspapi.io/v4").rstrip("/"); sport_id=int(cfg.get("sport_id",10)); max_fixtures=max(1,int(cfg.get("max_fixtures",1))); candidate_fixtures=max(max_fixtures,int(cfg.get("candidate_fixtures",max_fixtures*2))); concurrency=max(1,min(4,int(cfg.get("probe_concurrency",3)))); hours_ahead=max(1,int(cfg.get("hours_ahead",24))); timeout=min(20.0,max(5.0,float(cfg.get("timeout_seconds",12)))); max_quotes=max(500,int(cfg.get("max_quotes_per_fixture",12000))); preferred=cfg.get("preferred_bookmakers",[])
    now=datetime.now(timezone.utc); until=now+timedelta(hours=hours_ahead); fixture_params={"apiKey":api_key,"sportId":sport_id,"from":now.isoformat().replace("+00:00","Z"),"to":until.isoformat().replace("+00:00","Z"),"statusId":0,"hasOdds":"true","language":"en"}; limits=httpx.Limits(max_connections=concurrency+2,max_keepalive_connections=concurrency+1)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout),limits=limits,follow_redirects=True) as client:
        markets_response=await client.get(f"{base_url}/markets",params={"apiKey":api_key,"language":"en"}); markets_response.raise_for_status(); catalog=_build_market_catalog(markets_response.json(),sport_id)
        if not catalog: raise RuntimeError("OddsPapi football market catalog is empty")
        fixture_response=await client.get(f"{base_url}/fixtures",params=fixture_params); fixture_response.raise_for_status(); fixtures=fixture_response.json()
        if not isinstance(fixtures,list): raise RuntimeError("Unexpected OddsPapi fixtures response")
        fixtures=[f for f in fixtures if isinstance(f,dict) and f.get("fixtureId")]; fixtures.sort(key=lambda f:str(f.get("startTime",""))); candidates=fixtures[:candidate_fixtures]; sem=asyncio.Semaphore(concurrency)
        async def probe(fixture):
            fixture_id=fixture["fixtureId"]
            async with sem:
                try:
                    response=await client.get(f"{base_url}/odds",params={"apiKey":api_key,"fixtureId":fixture_id,"oddsFormat":"decimal","language":"en","verbosity":3}); response.raise_for_status(); fq=adapt_oddspapi_fixture(response.json(),catalog,max_quotes=max_quotes); present=_preferred_present(fq,preferred); return fixture,fq,present
                except Exception as exc:
                    print(f"SCANNER fixture={fixture_id} skipped {type(exc).__name__} HTTP={getattr(getattr(exc,'response',None),'status_code',None)}",flush=True); return fixture,[],[]
        results=await asyncio.gather(*(probe(f) for f in candidates))
    usable=[r for r in results if r[1]]; priority=[r for r in usable if r[2]]; ordinary=[r for r in usable if not r[2]]; selected=(priority+ordinary)[:max_fixtures]; quotes=[q for _,fq,_ in selected for q in fq]
    if not quotes: raise RuntimeError("OddsPapi returned no usable catalog-backed football market quotes")
    return quotes

async def fetch_provider(cfg):
    provider=cfg.get("name") or "Unknown provider"; adapter=cfg.get("adapter","oddspapi_v4")
    if adapter=="oddspapi_v4": return await fetch_oddspapi(cfg)
    raise RuntimeError(f"Unsupported feed adapter '{adapter}' for {provider}")

async def fetch_all_feeds(config):
    quotes,errors=[],[]; sources=config.get("providers",[])
    for cfg in sources:
        if not cfg.get("enabled",False): continue
        source_name=cfg.get("name") or "Unknown provider"
        try: quotes.extend(await fetch_provider(cfg))
        except Exception as exc:
            status=getattr(getattr(exc,"response",None),"status_code",None)
            message=f"{source_name}: {type(exc).__name__}"+(f" HTTP {status}" if status else "")
            print(f"SCANNER ERROR {message}",flush=True); errors.append(message)
    if not any(cfg.get("enabled",False) for cfg in sources): errors.append("No live odds provider is enabled")
    return quotes,errors