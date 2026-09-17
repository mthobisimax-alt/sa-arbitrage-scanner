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
                quotes.append({"source":"OddsPapi","bookmaker":str(bookmaker),"bookmaker_url":fixture_url,"bookmaker_host":link_host,"sa_link_status":sa_status,"event_id":fixture_id,"sport":str(sport).lower(),"league":league,"event_name":event_name,"market":meta["name"],"market_id":str(market_id),"market_length":meta["length"],"market_type":meta["type"],"period":meta["period"],"line":meta["line"],"selection":selection,"odds":price,"timestamp":_iso_timestamp(player.get("bookmakerChangedAt") or player.get("changedAt") or fallback_ts)})
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

def _american_to_decimal(value):
    try: a=float(value)
    except (TypeError,ValueError): return None
    if a==0: return None
    return 1+(a/100.0 if a>0 else 100.0/abs(a))

def _sgo_team_name(event,side):
    team=((event.get("teams") or {}).get(side) or {})
    names=team.get("names") or {}
    return names.get("long") or names.get("medium") or names.get("short") or side.title()

def _sgo_selection(odd,home,away):
    side=str(odd.get("sideID") or "").lower()
    if side=="home": return home
    if side=="away": return away
    if side in ("draw","tie","x"): return "Draw"
    if side=="over": return "Over"
    if side=="under": return "Under"
    if side=="yes": return "Yes"
    if side=="no": return "No"
    return side.title() if side else ""

def adapt_sportsgameodds_events(payload,max_events=12):
    rows=(payload or {}).get("data") if isinstance(payload,dict) else None
    if not isinstance(rows,list): return []
    quotes=[]
    for event in rows[:max_events]:
        if not isinstance(event,dict): continue
        event_id=str(event.get("eventID") or "")
        if not event_id: continue
        home=_sgo_team_name(event,"home"); away=_sgo_team_name(event,"away")
        event_name=f"{home} v {away}"; league=str(event.get("leagueID") or ""); sport=str(event.get("sportID") or "SOCCER").lower()
        grouped={}
        for odd_id,odd in (event.get("odds") or {}).items():
            if not isinstance(odd,dict) or odd.get("ended") is True or odd.get("cancelled") is True: continue
            market_name=str(odd.get("marketName") or odd_id); period=str(odd.get("periodID") or "game"); bet_type=str(odd.get("betTypeID") or "")
            line=odd.get("bookOverUnder") if bet_type=="ou" else odd.get("bookSpread") if bet_type=="sp" else ""
            selection=_sgo_selection(odd,home,away)
            if not selection: continue
            key=(market_name,period,bet_type,"" if line is None else str(line))
            grouped.setdefault(key,[]).append((selection,odd))
        for (market_name,period,bet_type,line),items in grouped.items():
            selections={s for s,_ in items}
            if len(selections) not in (2,3): continue
            market_id=f"sgo:{market_name}|{period}|{bet_type}|{line}"
            for selection,odd in items:
                for bookmaker,book_data in (odd.get("byBookmaker") or {}).items():
                    if not isinstance(book_data,dict) or book_data.get("available") is False: continue
                    decimal=_american_to_decimal(book_data.get("odds"))
                    if not decimal or decimal<=1: continue
                    url=book_data.get("deeplink") or ""; sa_status,link_host=_sa_link_status(bookmaker,url)
                    quotes.append({"source":"SportsGameOdds","bookmaker":str(bookmaker),"bookmaker_url":url,"bookmaker_host":link_host,"sa_link_status":sa_status,"event_id":event_id,"sport":sport,"league":league,"event_name":event_name,"market":market_name,"market_id":market_id,"market_length":len(selections),"market_type":bet_type,"period":period,"line":line,"selection":selection,"odds":decimal,"timestamp":_iso_timestamp(book_data.get("lastUpdatedAt"))})
    return quotes

async def fetch_sportsgameodds(cfg):
    api_key=_resolve_env(cfg.get("api_key","env:SPORTSGAMEODDS_API_KEY"))
    if not api_key:
        if cfg.get("optional",False): return []
        raise RuntimeError("SPORTSGAMEODDS_API_KEY is not configured")
    base_url=cfg.get("base_url","https://api.sportsgameodds.com/v2").rstrip("/"); timeout=min(20.0,max(5.0,float(cfg.get("timeout_seconds",15)))); max_events=max(1,min(100,int(cfg.get("max_events",12))))
    params={"apiKey":api_key,"oddsAvailable":"true","limit":max_events}
    league_id=str(cfg.get("league_id") or "").strip()
    if league_id: params["leagueID"]=league_id
    else: params["sportID"]=cfg.get("sport_id","SOCCER")
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout),follow_redirects=True) as client:
        response=await client.get(f"{base_url}/events",params=params)
        if response.status_code>=400:
            detail=""
            try:
                body=response.json()
                if isinstance(body,dict): detail=str(body.get("message") or body.get("error") or body.get("detail") or "")
            except Exception:
                detail=response.text[:160]
            detail=" ".join(detail.split())[:180]
            raise RuntimeError(f"SportsGameOdds HTTP {response.status_code}"+(f": {detail}" if detail else ""))
        data=response.json()
    quotes=adapt_sportsgameodds_events(data,max_events=max_events)
    if not quotes: raise RuntimeError("SportsGameOdds returned no usable soccer quotes")
    return quotes

async def fetch_provider(cfg):
    provider=cfg.get("name") or "Unknown provider"; adapter=cfg.get("adapter","oddspapi_v4")
    if adapter=="oddspapi_v4": return await fetch_oddspapi(cfg)
    if adapter=="sportsgameodds_v2": return await fetch_sportsgameodds(cfg)
    raise RuntimeError(f"Unsupported feed adapter '{adapter}' for {provider}")

async def fetch_all_feeds(config):
    quotes,errors=[],[]
    sources=sorted([cfg for cfg in config.get("providers",[]) if cfg.get("enabled",False)],key=lambda x:int(x.get("priority",100)))
    strategy=str(config.get("provider_strategy","all")).lower(); min_quotes=max(1,int(config.get("min_quotes_to_stop",20)))
    if not sources:
        return [],["No live odds provider is enabled"]
    for cfg in sources:
        source_name=cfg.get("name") or "Unknown provider"
        if cfg.get("optional",False) and not _resolve_env(cfg.get("api_key","")):
            continue
        if strategy=="quota_aware_fallback" and cfg.get("adapter")=="oddspapi_v4":
            quota=await fetch_oddspapi_account(config)
            if quota.get("available") and int(quota.get("requests_remaining") or 0)<=0:
                print("SCANNER OddsPapi skipped because quota is exhausted; trying fallback provider",flush=True)
                continue
        try:
            provider_quotes=await fetch_provider(cfg)
            quotes.extend(provider_quotes)
            print(f"SCANNER source={source_name} quotes={len(provider_quotes)} strategy={strategy}",flush=True)
            if strategy=="quota_aware_fallback" and len(provider_quotes)>=min_quotes:
                break
        except Exception as exc:
            status=getattr(getattr(exc,"response",None),"status_code",None)
            detail=str(exc).strip()
            if detail.startswith("SportsGameOdds "):
                message=detail
            else:
                message=f"{source_name}: {type(exc).__name__}"+(f" HTTP {status}" if status else "")
            print(f"SCANNER ERROR {message}",flush=True); errors.append(message)
    if not quotes and not errors:
        errors.append("No configured provider currently returned usable odds")
    return quotes,errors
