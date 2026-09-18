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
    result={
        "provider":"Supabets Direct",
        "reachable":False,
        "operations":[],
        "operation_parameters":{},
        "operation_probes":[],
        "events":[],
        "quotes":[],
        "errors":[]
    }
    known={
        "getClientActiveEventsByGroup":["IDPalinsesto","IDGruppo","TipoVisualizzazioneQuote","IDLingua"],
        "getClientOddsBySubeEvent":["IDPalinsesto","IDSottoEvento","IDLingua","IDGmt"],
        "GetListOdds_OddLessThan":["strQuotaMax","strIDSport","typeOrder","tipoVisQuote"]
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout),follow_redirects=True) as client:
            landing=await client.get(base)
            landing.raise_for_status()
            result["reachable"]=True

            discovered=set()
            for name in known:
                if name.lower() in landing.text.lower():
                    discovered.add(name)

            try:
                wsdl=await client.get(base+"?WSDL")
                if wsdl.status_code<400 and wsdl.text.strip():
                    root=ET.fromstring(wsdl.text)
                    for el in root.iter():
                        if _local(el.tag)=="operation":
                            name=str(el.attrib.get("name") or "").strip()
                            if name:
                                discovered.add(name)
            except Exception as exc:
                result["errors"].append(f"WSDL inspection failed: {type(exc).__name__}")

            for name in known:
                help_page=await client.get(base,params={"op":name})
                if help_page.status_code<400 and name.lower() in help_page.text.lower():
                    discovered.add(name)

            result["operations"]=sorted(discovered)
            for name,params in known.items():
                if name in discovered:
                    result["operation_parameters"][name]=params

            test_params={
                "getClientActiveEventsByGroup":{
                    "IDPalinsesto":"0","IDGruppo":"0","TipoVisualizzazioneQuote":"0","IDLingua":"1"
                },
                "getClientOddsBySubeEvent":{
                    "IDPalinsesto":"0","IDSottoEvento":"0","IDLingua":"1","IDGmt":"2"
                },
                "GetListOdds_OddLessThan":{
                    "strQuotaMax":"2.00","strIDSport":"1","typeOrder":"0","tipoVisQuote":"0"
                }
            }
            for name,params in test_params.items():
                try:
                    r=await client.get(base+"/"+name,params=params)
                    preview=" ".join((r.text or "").replace("\r"," ").replace("\n"," ").split())[:180]
                    result["operation_probes"].append({
                        "operation":name,
                        "status":r.status_code,
                        "content_type":str(r.headers.get("content-type") or ""),
                        "final_url":str(r.url).split("?")[0],
                        "looks_like_xml":("<" in (r.text or "") and ("<?xml" in (r.text or "")[:100].lower() or "<string" in (r.text or "")[:200].lower())),
                        "preview":preview
                    })
                except Exception as exc:
                    result["operation_probes"].append({
                        "operation":name,
                        "error":type(exc).__name__
                    })

            group_id=str(cfg.get("group_id") or "").strip()
            if cfg.get("probe_active_events",False) and group_id:
                params={
                    "IDPalinsesto":str(cfg.get("schedule_id") or "0"),
                    "IDGruppo":group_id,
                    "TipoVisualizzazioneQuote":str(cfg.get("odds_view_type") or "0"),
                    "IDLingua":str(cfg.get("language_id") or "1")
                }
                r=await client.get(base+"/getClientActiveEventsByGroup",params=params)
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


async def probe_supabets_new_site():
    base="https://new.supabets.co.za/"
    result={
        "provider":"Supabets New Site",
        "reachable":False,
        "status":None,
        "content_type":"",
        "framework":"",
        "script_count":0,
        "scripts_scanned":0,
        "embedded_markers":[],
        "candidate_data_urls":[],
        "candidate_paths":[],
        "candidate_hosts":[],
        "sports_full_probe":{},
        "errors":[]
    }
    try:
        import re
        from urllib.parse import urljoin, urlparse
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={"User-Agent":"Mozilla/5.0"}
        ) as client:
            r=await client.get(base)
            result["status"]=r.status_code
            result["content_type"]=str(r.headers.get("content-type") or "")
            r.raise_for_status()
            result["reachable"]=True
            html=r.text or ""

            if "/_next/" in html:
                result["framework"]="Next.js"
            elif "__NUXT__" in html:
                result["framework"]="Nuxt"

            scripts=[]
            for m in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',html,re.I):
                src=urljoin(base,m)
                if src not in scripts:
                    scripts.append(src)
            result["script_count"]=len(scripts)

            markers=[]
            for key in ("__NEXT_DATA__","__NUXT__","apollo","graphql","sportsbook","odds","market","event","socket","websocket"):
                if key.lower() in html.lower():
                    markers.append(key)
            result["embedded_markers"]=markers

            absolute=set()
            paths=set()
            hosts=set()
            keywords=("api","graphql","odds","sportsbook","event","market","fixture","sport","bet","socket","feed")

            def collect(text):
                if not text:
                    return
                for match in re.findall(r'https?://[^"\'\\s<>]+',text,re.I):
                    clean=match.replace("\\/","/")
                    low=clean.lower()
                    if any(k in low for k in keywords):
                        absolute.add(clean[:500])
                        try:
                            host=urlparse(clean).hostname
                            if host:
                                hosts.add(host.lower())
                        except Exception:
                            pass
                for match in re.findall(r'["\'](/[^"\']{1,300})["\']',text):
                    clean=match.replace("\\/","/")
                    low=clean.lower()
                    if any(k in low for k in keywords):
                        paths.add(clean)
                for match in re.findall(r'["\']([^"\']{1,300})["\']',text):
                    low=match.lower()
                    if any(token in low for token in ("/api/","graphql","sportsbook","odds","markets","events","fixtures")):
                        clean=match.replace("\\/","/")
                        if clean.startswith("http"):
                            absolute.add(clean[:500])
                        elif clean.startswith("/"):
                            paths.add(clean)

            collect(html)

            scanned=0
            for src in scripts[:30]:
                try:
                    js=await client.get(src)
                    if js.status_code>=400:
                        continue
                    text=js.text or ""
                    if len(text)>3_000_000:
                        continue
                    collect(text)
                    scanned+=1
                except Exception:
                    continue
            result["scripts_scanned"]=scanned

            result["candidate_data_urls"]=sorted(absolute)[:60]
            result["candidate_paths"]=sorted(paths)[:80]
            result["candidate_hosts"]=sorted(hosts)[:30]

            sports_url=urljoin(base,"/api/b2c/EventsProgram/sports-full")
            try:
                sr=await client.get(sports_url)
                probe={
                    "url":sports_url,
                    "status":sr.status_code,
                    "content_type":str(sr.headers.get("content-type") or ""),
                    "final_url":str(sr.url)
                }
                body=(sr.text or "").strip()
                if "json" in probe["content_type"].lower() or (body.startswith("{") or body.startswith("[")):
                    try:
                        data=sr.json()
                        probe["json_type"]=type(data).__name__
                        if isinstance(data,dict):
                            probe["top_level_keys"]=list(data.keys())[:30]
                            for key in ("data","sports","events","result","items"):
                                value=data.get(key)
                                if isinstance(value,list):
                                    probe["item_count"]=len(value)
                                    probe["sample_keys"]=list(value[0].keys())[:30] if value and isinstance(value[0],dict) else []
                                    break
                        elif isinstance(data,list):
                            probe["item_count"]=len(data)
                            probe["sample_keys"]=list(data[0].keys())[:30] if data and isinstance(data[0],dict) else []
                    except Exception as exc:
                        probe["json_parse_error"]=type(exc).__name__
                else:
                    probe["preview"]=" ".join(body.replace("\r"," ").replace("\n"," ").split())[:220]
                result["sports_full_probe"]=probe
            except Exception as exc:
                result["sports_full_probe"]={"url":sports_url,"error":type(exc).__name__}
    except Exception as exc:
        result["errors"].append(f"New-site public page probe failed: {type(exc).__name__}")
    return result


async def probe_supabets_bundle_context():
    base="https://new.supabets.co.za/"
    result={
        "provider":"Supabets New Site",
        "reachable":False,
        "scripts_scanned":0,
        "sport_api_matches":[],
        "candidate_origins":[],
        "errors":[]
    }
    try:
        import re
        from urllib.parse import urljoin
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={"User-Agent":"Mozilla/5.0"}
        ) as client:
            r=await client.get(base)
            r.raise_for_status()
            result["reachable"]=True
            html=r.text or ""
            scripts=[]
            for m in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',html,re.I):
                src=urljoin(base,m)
                if src not in scripts:
                    scripts.append(src)

            tokens=("sportB2CApi","EventsProgram/sports-full","/api/b2c/")
            origins=set()
            found=[]
            for src in scripts[:40]:
                try:
                    js=await client.get(src)
                    if js.status_code>=400:
                        continue
                    text=js.text or ""
                    if len(text)>3_500_000:
                        continue
                    result["scripts_scanned"]+=1
                    lower=text.lower()
                    for token in tokens:
                        needle=token.lower()
                        pos=0
                        hits=0
                        while hits<12:
                            idx=lower.find(needle,pos)
                            if idx<0:
                                break
                            a=max(0,idx-900); b=min(len(text),idx+len(token)+1400)
                            snippet=" ".join(text[a:b].replace("\r"," ").replace("\n"," ").split())
                            found.append({
                                "token":token,
                                "script":src.rsplit("/",1)[-1],
                                "context":snippet[:2200]
                            })
                            for origin in re.findall(r'https?://[A-Za-z0-9._:-]+',snippet):
                                origins.add(origin)
                            pos=idx+len(token)
                            hits+=1
                except Exception:
                    continue

            result["sport_api_matches"]=found[:50]
            result["candidate_origins"]=sorted(origins)[:30]
    except Exception as exc:
        result["errors"].append(f"Bundle context probe failed: {type(exc).__name__}")
    return result


async def probe_supabets_public_sports_api():
    url="https://apib2c.supabets.co.za/api/b2c/EventsProgram/sports-full"
    result={
        "provider":"Supabets Public Sports API",
        "url":url,
        "status":None,
        "content_type":"",
        "json_type":"",
        "top_level_keys":[],
        "item_count":None,
        "sample_keys":[],
        "errors":[]
    }
    headers={
        "x-api-key":"H3DigitalAPIB2CWebsiteUser",
        "Accept":"application/json",
        "Content-Type":"application/json",
        "Origin":"https://new.supabets.co.za",
        "Referer":"https://new.supabets.co.za/",
        "User-Agent":"Mozilla/5.0"
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0),follow_redirects=True,headers=headers) as client:
            r=await client.get(url)
            result["status"]=r.status_code
            result["content_type"]=str(r.headers.get("content-type") or "")
            body=(r.text or "").strip()
            if r.status_code>=400:
                result["errors"].append(f"HTTP {r.status_code}")
                result["preview"]=" ".join(body.replace("\r"," ").replace("\n"," ").split())[:240]
                return result
            try:
                data=r.json()
                result["json_type"]=type(data).__name__
                if isinstance(data,dict):
                    result["top_level_keys"]=list(data.keys())[:40]
                    for key in ("data","sports","events","result","items","content"):
                        value=data.get(key)
                        if isinstance(value,list):
                            result["item_count"]=len(value)
                            if value and isinstance(value[0],dict):
                                result["sample_keys"]=list(value[0].keys())[:40]
                            break
                    if result["item_count"] is None:
                        for key,value in data.items():
                            if isinstance(value,list):
                                result["item_count"]=len(value)
                                if value and isinstance(value[0],dict):
                                    result["sample_keys"]=list(value[0].keys())[:40]
                                break
                elif isinstance(data,list):
                    result["item_count"]=len(data)
                    if data and isinstance(data[0],dict):
                        result["sample_keys"]=list(data[0].keys())[:40]
            except Exception as exc:
                result["errors"].append(f"JSON parse failed: {type(exc).__name__}")
                result["preview"]=" ".join(body.replace("\r"," ").replace("\n"," ").split())[:240]
    except Exception as exc:
        result["errors"].append(f"Public sports API probe failed: {type(exc).__name__}")
    return result


async def probe_supabets_soccer_program():
    base="https://apib2c.supabets.co.za"
    headers={
        "x-api-key":"H3DigitalAPIB2CWebsiteUser",
        "Accept":"application/json",
        "Content-Type":"application/json",
        "Origin":"https://new.supabets.co.za",
        "Referer":"https://new.supabets.co.za/",
        "User-Agent":"Mozilla/5.0"
    }
    result={
        "provider":"Supabets Public Sports API",
        "sports_status":None,
        "soccer_candidates":[],
        "selected_soccer":None,
        "program_probe":{},
        "errors":[]
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0),follow_redirects=True,headers=headers) as client:
            sports_url=base+"/api/b2c/EventsProgram/sports-full"
            sr=await client.get(sports_url)
            result["sports_status"]=sr.status_code
            sr.raise_for_status()
            payload=sr.json()
            sports=payload.get("data") if isinstance(payload,dict) else payload
            sports=sports if isinstance(sports,list) else []

            for item in sports:
                if not isinstance(item,dict):
                    continue
                name=str(item.get("name") or "")
                slug=str(item.get("slug") or "")
                if any(k in (name+" "+slug).lower() for k in ("soccer","football")):
                    result["soccer_candidates"].append({
                        "sportId":item.get("sportId"),
                        "sportTypeId":item.get("sportTypeId"),
                        "name":name,
                        "slug":slug,
                        "subEventsCount":item.get("subEventsCount")
                    })

            selected=None
            for item in result["soccer_candidates"]:
                text=(str(item.get("name") or "")+" "+str(item.get("slug") or "")).lower()
                if "soccer" in text:
                    selected=item
                    break
            if selected is None and result["soccer_candidates"]:
                selected=result["soccer_candidates"][0]
            result["selected_soccer"]=selected

            if selected and selected.get("sportId") is not None:
                sport_id=selected["sportId"]
                program_url=base+f"/api/b2c/EventsProgram/program?sportId={sport_id}"
                pr=await client.get(program_url)
                probe={
                    "url":program_url,
                    "status":pr.status_code,
                    "content_type":str(pr.headers.get("content-type") or "")
                }
                body=(pr.text or "").strip()
                if pr.status_code>=400:
                    probe["preview"]=" ".join(body.replace("\r"," ").replace("\n"," ").split())[:260]
                else:
                    try:
                        data=pr.json()
                        probe["json_type"]=type(data).__name__
                        if isinstance(data,dict):
                            probe["top_level_keys"]=list(data.keys())[:40]
                            values=[]
                            for key,val in data.items():
                                if isinstance(val,list):
                                    values.append((key,val))
                            if values:
                                key,val=values[0]
                                probe["list_key"]=key
                                probe["item_count"]=len(val)
                                if val and isinstance(val[0],dict):
                                    probe["sample_keys"]=list(val[0].keys())[:50]
                                    probe["sample_item"]={k:val[0].get(k) for k in probe["sample_keys"][:12]}
                        elif isinstance(data,list):
                            probe["item_count"]=len(data)
                            if data and isinstance(data[0],dict):
                                probe["sample_keys"]=list(data[0].keys())[:50]
                                probe["sample_item"]={k:data[0].get(k) for k in probe["sample_keys"][:12]}
                    except Exception as exc:
                        probe["json_parse_error"]=type(exc).__name__
                        probe["preview"]=" ".join(body.replace("\r"," ").replace("\n"," ").split())[:260]
                result["program_probe"]=probe
    except Exception as exc:
        result["errors"].append(f"Supabets soccer program probe failed: {type(exc).__name__}: {exc}")
    return result


async def probe_supabets_soccer_groups():
    base="https://apib2c.supabets.co.za"
    headers={
        "x-api-key":"H3DigitalAPIB2CWebsiteUser",
        "Accept":"application/json",
        "Content-Type":"application/json",
        "Origin":"https://new.supabets.co.za",
        "Referer":"https://new.supabets.co.za/",
        "User-Agent":"Mozilla/5.0"
    }
    result={
        "provider":"Supabets Public Sports API",
        "sportId":163,
        "status":None,
        "group_count":0,
        "group_sample_keys":[],
        "group_samples":[],
        "nested_list_keys":[],
        "errors":[]
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0),follow_redirects=True,headers=headers) as client:
            url=base+"/api/b2c/EventsProgram/program?sportId=163"
            r=await client.get(url)
            result["status"]=r.status_code
            r.raise_for_status()
            payload=r.json()
            data=payload.get("data") if isinstance(payload,dict) else payload
            if not isinstance(data,list) or not data or not isinstance(data[0],dict):
                result["errors"].append("Unexpected soccer program structure")
                return result
            sport=data[0]
            groups=sport.get("groups")
            if not isinstance(groups,list):
                result["errors"].append("Soccer program has no groups list")
                return result
            result["group_count"]=len(groups)
            if groups and isinstance(groups[0],dict):
                result["group_sample_keys"]=list(groups[0].keys())[:60]
            samples=[]
            nested=set()
            for g in groups[:8]:
                if not isinstance(g,dict):
                    continue
                sample={}
                for k,v in g.items():
                    if isinstance(v,(str,int,float,bool)) or v is None:
                        sample[k]=v
                    elif isinstance(v,list):
                        sample[k+"_count"]=len(v)
                        nested.add(k)
                        if v and isinstance(v[0],dict):
                            sample[k+"_sample_keys"]=list(v[0].keys())[:40]
                samples.append(sample)
            result["group_samples"]=samples
            result["nested_list_keys"]=sorted(nested)
    except Exception as exc:
        result["errors"].append(f"Supabets soccer group probe failed: {type(exc).__name__}: {exc}")
    return result


async def probe_supabets_event_api_paths():
    base="https://new.supabets.co.za/"
    result={
        "provider":"Supabets New Site",
        "reachable":False,
        "scripts_scanned":0,
        "event_api_paths":[],
        "event_contexts":[],
        "errors":[]
    }
    try:
        import re
        from urllib.parse import urljoin
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0),follow_redirects=True,headers={"User-Agent":"Mozilla/5.0"}) as client:
            r=await client.get(base)
            r.raise_for_status()
            result["reachable"]=True
            html=r.text or ""
            scripts=[]
            for m in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',html,re.I):
                src=urljoin(base,m)
                if src not in scripts:
                    scripts.append(src)

            paths=set()
            contexts=[]
            for src in scripts[:40]:
                try:
                    js=await client.get(src)
                    if js.status_code>=400:
                        continue
                    text=js.text or ""
                    if len(text)>3_500_000:
                        continue
                    result["scripts_scanned"]+=1

                    for m in re.findall(r'["\'](/api/b2c/EventsProgram/[^"\']{1,220})["\']',text):
                        paths.add(m.replace("\\/","/"))

                    lower=text.lower()
                    for token in ("subevent","eventid","eventsprogram/"):
                        pos=0
                        hits=0
                        while hits<10:
                            idx=lower.find(token,pos)
                            if idx<0:
                                break
                            a=max(0,idx-500); b=min(len(text),idx+1100)
                            snippet=" ".join(text[a:b].replace("\r"," ").replace("\n"," ").split())
                            if "/api/b2c/EventsProgram/" in snippet or "sportB2CApi" in snippet:
                                contexts.append({"token":token,"script":src.rsplit("/",1)[-1],"context":snippet[:1500]})
                            pos=idx+len(token)
                            hits+=1
                except Exception:
                    continue

            result["event_api_paths"]=sorted(paths)[:80]
            result["event_contexts"]=contexts[:40]
    except Exception as exc:
        result["errors"].append(f"Event API path probe failed: {type(exc).__name__}: {exc}")
    return result
