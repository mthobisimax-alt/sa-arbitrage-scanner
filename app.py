import json
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from engine import find_arbs
from feeds import fetch_all_feeds

with open("config.json") as f: CFG = json.load(f)
app = FastAPI(title="SA Arb Scanner Web")
templates = Jinja2Templates(directory=".")


def preferred_bookmakers():
    names=[]
    for provider in CFG.get("providers", []):
        for name in provider.get("preferred_bookmakers", []):
            if name and name not in names: names.append(name)
    return names


def feed_names():
    return [p.get("name","Unknown provider") for p in CFG.get("providers",[]) if p.get("enabled",False)]


def detected_preferred_bookmakers(quotes):
    live={str(q.get("bookmaker")).strip().lower():str(q.get("bookmaker")).strip() for q in quotes if q.get("bookmaker")}
    return [live[p.lower()] for p in preferred_bookmakers() if p.lower() in live]


def preferred_opportunities(opportunities):
    targets={name.lower() for name in preferred_bookmakers()}
    return [o for o in opportunities if any(str(l.get("bookmaker","")).strip().lower() in targets for l in o.get("legs",[]))]


latest={"quotes":[],"opportunities":[],"preferred_opportunities":[],"preferred_opportunity_count":0,"updated_at":None,"errors":[],"feed_names":feed_names(),"preferred_bookmakers":preferred_bookmakers(),"preferred_detected":[],"scan_state":"starting"}


async def scan():
    quotes=[]; errors=[]
    if CFG.get("demo_mode"):
        now=datetime.now(timezone.utc).isoformat()
        quotes=[
            {"bookmaker":"Hollywoodbets","event_id":"test-event-001","sport":"soccer","league":"Test League","event_name":"Alpha FC v Beta FC","market":"Full Time Result","market_id":"101","line":"","selection":"Alpha FC","odds":2.35,"timestamp":now},
            {"bookmaker":"Supabets","event_id":"test-event-001","sport":"soccer","league":"Test League","event_name":"Alpha FC v Beta FC","market":"Full Time Result","market_id":"101","line":"","selection":"Draw","odds":4.10,"timestamp":now},
            {"bookmaker":"Betway","event_id":"test-event-001","sport":"soccer","league":"Test League","event_name":"Alpha FC v Beta FC","market":"Full Time Result","market_id":"101","line":"","selection":"Beta FC","odds":4.00,"timestamp":now},
        ]
    else:
        feed_quotes,feed_errors=await fetch_all_feeds(CFG); quotes.extend(feed_quotes); errors.extend(feed_errors)
    opportunities=find_arbs(quotes,CFG.get("max_quote_age_seconds",20),CFG.get("min_margin_percent",0.10))
    return quotes,opportunities,errors


@app.get("/",response_class=HTMLResponse)
def home(request:Request): return templates.TemplateResponse(request=request,name="index.html")
@app.get("/api/status")
def status(): return JSONResponse(latest)
@app.get("/api/sa-opportunities")
def sa_opportunities(): return {"preferred_bookmakers":latest["preferred_bookmakers"],"preferred_detected":latest["preferred_detected"],"count":latest["preferred_opportunity_count"],"opportunities":latest["preferred_opportunities"],"updated_at":latest["updated_at"]}
@app.get("/api/bookmakers")
def bookmakers():
    names=sorted({q.get("bookmaker") for q in latest["quotes"] if q.get("bookmaker")})
    return {"live":names,"preferred_present":detected_preferred_bookmakers(latest["quotes"]),"preferred_configured":preferred_bookmakers()}
@app.get("/api/health")
def health(): return {"ok":True,"service":"sa-arb-scanner-web","scan_state":latest.get("scan_state")}


@app.on_event("startup")
async def startup(): asyncio.create_task(scanner_loop())


async def scanner_loop():
    global latest
    scan_timeout=max(10,min(45,int(CFG.get("scan_timeout_seconds",35))))
    while True:
        started=datetime.now(timezone.utc).isoformat()
        latest["scan_state"]="fetching"
        print(f"SCANNER cycle starting at {started} timeout={scan_timeout}s",flush=True)
        try:
            quotes,opportunities,errors=await asyncio.wait_for(scan(),timeout=scan_timeout)
            sa_opps=preferred_opportunities(opportunities)
            latest={"quotes":quotes,"opportunities":opportunities,"preferred_opportunities":sa_opps,"preferred_opportunity_count":len(sa_opps),"updated_at":datetime.now(timezone.utc).isoformat(),"errors":errors,"feed_names":feed_names(),"preferred_bookmakers":preferred_bookmakers(),"preferred_detected":detected_preferred_bookmakers(quotes),"scan_state":"ok" if not errors else "completed_with_errors"}
            print(f"SCANNER cycle completed quotes={len(quotes)} arbs={len(opportunities)} errors={len(errors)}",flush=True)
        except asyncio.TimeoutError:
            message=f"Scanner cycle timed out after {scan_timeout} seconds"
            latest["errors"]=[message]; latest["updated_at"]=datetime.now(timezone.utc).isoformat(); latest["scan_state"]="timeout"
            print(f"SCANNER ERROR {message}",flush=True)
        except Exception as exc:
            message=f"Scanner cycle failed: {type(exc).__name__}: {exc}"
            latest["errors"]=[message]; latest["updated_at"]=datetime.now(timezone.utc).isoformat(); latest["scan_state"]="error"
            print(f"SCANNER ERROR {message}",flush=True)
        await asyncio.sleep(CFG.get("poll_seconds",5))


if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=8787)
