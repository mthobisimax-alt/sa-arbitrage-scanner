import json,asyncio,httpx
from datetime import datetime,timezone
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.templating import Jinja2Templates
from engine import find_arbs
from feeds import fetch_live_odds
with open("config.json") as f: CFG=json.load(f)
app=FastAPI(title="SA Arb Scanner Web")
templates=Jinja2Templates(directory=".")
latest={"quotes":[],"opportunities":[],"updated_at":None,"errors":[]}

def demo():
    n=datetime.now(timezone.utc).isoformat()
    return [
      {"bookmaker":"Hollywoodbets","event_id":"demo-web","sport":"soccer","league":"Demo League","event_name":"Alpha FC v Beta FC","market":"match_result","line":"","selection":"Alpha FC","odds":2.35,"timestamp":n},
      {"bookmaker":"Supabets","event_id":"demo-web","sport":"soccer","league":"Demo League","event_name":"Alpha FC v Beta FC","market":"match_result","line":"","selection":"Draw","odds":4.10,"timestamp":n},
      {"bookmaker":"Betway","event_id":"demo-web","sport":"soccer","league":"Demo League","event_name":"Alpha FC v Beta FC","market":"match_result","line":"","selection":"Beta FC","odds":4.00,"timestamp":n}
    ]

async def fetch(cfg):
    async with httpx.AsyncClient(timeout=8,follow_redirects=True) as c:
        r=await c.get(cfg["url"],headers=cfg.get("headers",{})); r.raise_for_status(); d=r.json()
    rows=d.get("odds",d) if isinstance(d,dict) else d
    if not isinstance(rows,list): raise ValueError("Feed must return an odds list")
    return [{**q,"bookmaker":q.get("bookmaker",cfg["bookmaker"])} for q in rows]

async def scan():
    q = []
    e = []

    try:
        q += await fetch_live_odds()
    except Exception as x:
        e.append(f"Odds API: {x}")

    if CFG.get("demo_mode"):
        q += demo()

    opportunities = find_arbs(
        q,
        CFG.get("max_quote_age_seconds", 20),
        CFG.get("min_margin_percent", 0.10)
    )

    return q, opportunities, e

@app.get("/",response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )

@app.get("/api/status")
def status(): return JSONResponse(latest)
@app.get("/api/bookmakers")
def bookmakers():
    return sorted(list(set(q.get("bookmaker") for q in latest["quotes"] if q.get("bookmaker"))))
@app.get("/api/health")
def health(): return {"ok":True,"service":"sa-arb-scanner-web"}

async def loop():
    global latest
    while True:
        try:
            q,o,e=await scan()
            latest={"quotes":q,"opportunities":o,"updated_at":datetime.now(timezone.utc).isoformat(),"errors":e}
        except Exception as x: latest["errors"]=[str(x)]
        await asyncio.sleep(CFG.get("poll_seconds",5))

@app.on_event("startup")
async def startup(): asyncio.create_task(loop())

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=8787)
