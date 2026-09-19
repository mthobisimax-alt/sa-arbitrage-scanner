import os
import json
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from engine import find_arbs, find_preferred_arbs, find_near_arbs, market_diagnostics
from feeds import fetch_all_feeds, fetch_oddspapi_account
from sgo_feed import fetch_sportsgameodds_fixed
from supabets_feed import probe_supabets, probe_supabets_new_site, probe_supabets_bundle_context, probe_supabets_public_sports_api, probe_supabets_soccer_program, probe_supabets_soccer_groups, probe_supabets_event_api_paths
# Supabets diagnostic probe v2
from supabets_event_probe import discover_supabets_sport_calls, fetch_supabets_soccer_event_samples, discover_supabets_event_detail_calls, discover_supabets_b2c_betting_paths

with open("config.json") as f: CFG=json.load(f)
app=FastAPI(title="SA Arb Scanner Web"); templates=Jinja2Templates(directory=".")
scan_lock=asyncio.Lock()
MIN_SCAN_INTERVAL_SECONDS=max(60,int(CFG.get("on_demand_min_scan_interval_seconds",7200)))

def preferred_bookmakers():
    names=[]
    for provider in CFG.get("providers",[]):
        for name in provider.get("preferred_bookmakers",[]):
            if name and name not in names: names.append(name)
    return names

def feed_names(): return [p.get("name","Unknown provider") for p in CFG.get("providers",[]) if p.get("enabled",False)]

def supabets_cfg():
    return next((p for p in CFG.get("providers",[]) if p.get("adapter")=="supabets_marketws"),None)


def fallback_available():
    for p in CFG.get("providers",[]):
        if not p.get("enabled",False) or int(p.get("priority",99))<=1: continue
        key_ref=str(p.get("api_key") or "")
        if key_ref.startswith("env:"):
            if os.getenv(key_ref[4:].strip(),"").strip(): return True
        elif key_ref.strip(): return True
    return False

def detected_preferred_bookmakers(quotes):
    live={str(q.get("bookmaker")).strip().lower():str(q.get("bookmaker")).strip() for q in quotes if q.get("bookmaker")}
    return [live[p.lower()] for p in preferred_bookmakers() if p.lower() in live]

def seconds_since_update():
    value=latest.get("updated_at")
    if not value: return None
    try: return max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(value.replace("Z","+00:00"))).total_seconds())
    except Exception: return None

latest={"quotes":[],"opportunities":[],"preferred_opportunities":[],"preferred_opportunity_count":0,"updated_at":None,"errors":[],"feed_names":feed_names(),"preferred_bookmakers":preferred_bookmakers(),"preferred_detected":[],"scan_state":"idle","quota":{"available":False},"scan_mode":"on_demand","min_scan_interval_seconds":MIN_SCAN_INTERVAL_SECONDS,"fallback_available":fallback_available(),"market_diagnostics":{"markets_checked":0,"complete_same_line_markets":0,"incomplete_markets":0,"arbs_found":0},"near_arbitrages":[]}

async def scan():
    quotes=[]; errors=[]
    if CFG.get("demo_mode"):
        now=datetime.now(timezone.utc).isoformat(); quotes=[
            {"bookmaker":"Hollywoodbets","event_id":"test-event-001","sport":"soccer","league":"Test League","event_name":"Alpha FC v Beta FC","market":"Full Time Result","market_id":"101","market_length":3,"market_type":"result","period":"full_time","line":"","selection":"Alpha FC","odds":2.35,"timestamp":now},
            {"bookmaker":"Supabets","event_id":"test-event-001","sport":"soccer","league":"Test League","event_name":"Alpha FC v Beta FC","market":"Full Time Result","market_id":"101","market_length":3,"market_type":"result","period":"full_time","line":"","selection":"Draw","odds":4.10,"timestamp":now},
            {"bookmaker":"Betway","event_id":"test-event-001","sport":"soccer","league":"Test League","event_name":"Alpha FC v Beta FC","market":"Full Time Result","market_id":"101","market_length":3,"market_type":"result","period":"full_time","line":"","selection":"Beta FC","odds":4.00,"timestamp":now}]
    else:
        feed_quotes,feed_errors=await fetch_all_feeds(CFG); quotes.extend(feed_quotes); errors.extend(feed_errors)
    age=CFG.get("max_quote_age_seconds",20); margin=CFG.get("min_margin_percent",0.10)
    opportunities=find_arbs(quotes,age,margin); preferred=find_preferred_arbs(quotes,preferred_bookmakers(),age,margin)
    return quotes,opportunities,preferred,errors

async def scan_fallback_only():
    quotes,errors=await fetch_sportsgameodds_fixed(CFG)
    age=CFG.get("max_quote_age_seconds",20); margin=CFG.get("min_margin_percent",0.10)
    opportunities=find_arbs(quotes,age,margin); preferred=find_preferred_arbs(quotes,preferred_bookmakers(),age,margin)
    return quotes,opportunities,preferred,errors

async def run_scan_if_allowed():
    global latest
    if scan_lock.locked(): return {"started":False,"reason":"scan_in_progress"}
    age=seconds_since_update()
    if age is not None and age<MIN_SCAN_INTERVAL_SECONDS and latest.get("scan_state") in ("ok","completed_with_errors"):
        return {"started":False,"reason":"cached","retry_after_seconds":int(MIN_SCAN_INTERVAL_SECONDS-age)}
    async with scan_lock:
        quota=await fetch_oddspapi_account(CFG); latest["quota"]=quota; latest["fallback_available"]=fallback_available()
        odds_exhausted=bool(quota.get("available") and int(quota.get("requests_remaining") or 0)<=0)
        if odds_exhausted and not latest["fallback_available"]:
            latest["scan_state"]="paused_quota"; latest["errors"]=["OddsPapi quota exhausted and no fallback provider is configured."]
            return {"started":False,"reason":"quota_exhausted"}
        latest["scan_state"]="fetching"; scan_timeout=max(10,min(45,int(CFG.get("scan_timeout_seconds",35)))); before=quota
        try:
            runner=scan_fallback_only() if odds_exhausted and latest["fallback_available"] else scan()
            quotes,opportunities,sa_opps,errors=await asyncio.wait_for(runner,timeout=scan_timeout); await asyncio.sleep(1.1); after=await fetch_oddspapi_account(CFG)
            if before.get("available") and after.get("available"):
                try: after["last_scan_requests"]=max(0,int(after.get("request_count",0))-int(before.get("request_count",0)))
                except (TypeError,ValueError): after["last_scan_requests"]=None
            diag=market_diagnostics(quotes,CFG.get("max_quote_age_seconds",20))
            diag["arbs_found"]=len(opportunities)
            near=find_near_arbs(quotes,CFG.get("max_quote_age_seconds",20),CFG.get("min_margin_percent",0.10),3)
            latest={"quotes":quotes,"opportunities":opportunities,"preferred_opportunities":sa_opps,"preferred_opportunity_count":len(sa_opps),"updated_at":datetime.now(timezone.utc).isoformat(),"errors":errors,"feed_names":feed_names(),"preferred_bookmakers":preferred_bookmakers(),"preferred_detected":detected_preferred_bookmakers(quotes),"scan_state":"ok" if not errors else "completed_with_errors","quota":after,"scan_mode":"on_demand","min_scan_interval_seconds":MIN_SCAN_INTERVAL_SECONDS,"fallback_available":fallback_available(),"market_diagnostics":diag,"near_arbitrages":near}
            return {"started":True,"reason":"completed"}
        except asyncio.TimeoutError:
            latest["scan_state"]="timeout"; latest["errors"]=[f"Scanner cycle timed out after {scan_timeout} seconds"]; return {"started":True,"reason":"timeout"}
        except Exception as exc:
            latest["scan_state"]="error"; latest["errors"]=[f"Scanner cycle failed: {type(exc).__name__}: {exc}"]; return {"started":True,"reason":"error"}

@app.get("/",response_class=HTMLResponse)
def home(request:Request):
    with open("index.html",encoding="utf-8") as f: html=f.read()
    html=html.replace("</head>",'<link rel="stylesheet" href="/compact-template.css?v=1"></head>')
    html=html.replace("</body>",'<script src="/status-fix.js?v=2"></script></body>')
    return HTMLResponse(html,headers={"Cache-Control":"no-store"})
@app.get("/hero-template.webp")
def hero_template(): return FileResponse("hero-template.webp",media_type="image/webp",headers={"Cache-Control":"public, max-age=3600"})
@app.get("/compact-template.css")
def compact_template(): return FileResponse("compact-template.css",media_type="text/css",headers={"Cache-Control":"no-store"})
@app.get("/status-fix.js")
def status_fix(): return FileResponse("status-fix.js",media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/api/status")
def status():
    latest["fallback_available"]=fallback_available()
    return JSONResponse(latest)
@app.post("/api/scan")
async def request_scan(): return JSONResponse(await run_scan_if_allowed())
@app.get("/api/quota")
async def quota(): return JSONResponse(await fetch_oddspapi_account(CFG))
@app.get("/api/sa-opportunities")
def sa_opportunities(): return {"preferred_bookmakers":latest["preferred_bookmakers"],"preferred_detected":latest["preferred_detected"],"count":latest["preferred_opportunity_count"],"opportunities":latest["preferred_opportunities"],"updated_at":latest["updated_at"]}
@app.get("/api/bookmakers")
def bookmakers():
    names=sorted({q.get("bookmaker") for q in latest["quotes"] if q.get("bookmaker")}); return {"live":names,"preferred_present":detected_preferred_bookmakers(latest["quotes"]),"preferred_configured":preferred_bookmakers()}
@app.get("/api/supabets-test")
async def supabets_test():
    cfg=supabets_cfg()
    if not cfg:
        return JSONResponse({"provider":"Supabets Direct","configured":False,"errors":["Supabets provider is not configured"]})
    result=await probe_supabets(cfg)
    result["configured"]=True
    result["enabled_for_scanner"]=bool(cfg.get("enabled",False))
    result["diagnostic_only"]=bool(cfg.get("diagnostic_only",True))
    result["event_count"]=len(result.get("events") or [])
    result["quote_count"]=len(result.get("quotes") or [])
    return JSONResponse(result)

@app.get("/api/supabets-newsite-test")
async def supabets_newsite_test():
    return JSONResponse(await probe_supabets_new_site())

@app.get("/api/supabets-sports-full-test")
async def supabets_sports_full_test():
    result=await probe_supabets_new_site()
    return JSONResponse({
        "provider":result.get("provider"),
        "reachable":result.get("reachable"),
        "framework":result.get("framework"),
        "sports_full_probe":result.get("sports_full_probe",{}),
        "errors":result.get("errors",[])
    })

@app.get("/api/supabets-bundle-context-test")
async def supabets_bundle_context_test():
    return JSONResponse(await probe_supabets_bundle_context())

@app.get("/api/supabets-public-sports-test")
async def supabets_public_sports_test():
    return JSONResponse(await probe_supabets_public_sports_api())

@app.get("/api/supabets-soccer-program-test")
async def supabets_soccer_program_test():
    return JSONResponse(await probe_supabets_soccer_program())

@app.get("/api/supabets-soccer-groups-test")
async def supabets_soccer_groups_test():
    return JSONResponse(await probe_supabets_soccer_groups())

@app.get("/api/supabets-event-api-paths-test")
async def supabets_event_api_paths_test():
    return JSONResponse(await probe_supabets_event_api_paths())

@app.get("/api/supabets-isolated-event-probe")
async def supabets_isolated_event_probe():
    return JSONResponse(await discover_supabets_sport_calls())

@app.get("/api/supabets-eventsprogram-paths-test")
async def supabets_eventsprogram_paths_test():
    result=await discover_supabets_sport_calls()
    return JSONResponse({
        "provider":result.get("provider"),
        "reachable":result.get("reachable"),
        "scripts_scanned":result.get("scripts_scanned"),
        "eventsprogram_paths":result.get("eventsprogram_paths",[]),
        "errors":result.get("errors",[])
    })

@app.get("/api/supabets-soccer-event-samples-test")
async def supabets_soccer_event_samples_test():
    return JSONResponse(await fetch_supabets_soccer_event_samples())

@app.get("/api/supabets-event-detail-calls-test")
async def supabets_event_detail_calls_test():
    return JSONResponse(await discover_supabets_event_detail_calls())

@app.get("/api/supabets-b2c-betting-paths-test")
async def supabets_b2c_betting_paths_test():
    return JSONResponse(await discover_supabets_b2c_betting_paths())

@app.get("/api/health")
def health(): return {"ok":True,"service":"sa-arb-scanner-web","scan_state":latest.get("scan_state"),"scan_mode":"on_demand","fallback_available":fallback_available()}

@app.on_event("startup")
async def startup():
    global latest
    latest["quota"]=await fetch_oddspapi_account(CFG); latest["fallback_available"]=fallback_available()
    odds_exhausted=bool(latest["quota"].get("available") and int(latest["quota"].get("requests_remaining") or 0)<=0)
    latest["scan_state"]="paused_quota" if odds_exhausted and not latest["fallback_available"] else "idle"

if __name__=="__main__":
    import uvicorn; uvicorn.run(app,host="0.0.0.0",port=8787)
