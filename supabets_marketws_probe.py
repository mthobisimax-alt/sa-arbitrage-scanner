import xml.etree.ElementTree as ET
import httpx

BASE="https://mobile.supabets.co.za/Controls/MarketWS.asmx"

def _local(tag):
    return tag.split("}",1)[-1] if "}" in tag else tag

def _summarize_xml(text):
    out={"root":"","counts":{},"sample_tags":[]}
    try:
        root=ET.fromstring(text)
        out["root"]=_local(root.tag)
        counts={}
        tags=[]
        for el in root.iter():
            name=_local(el.tag)
            counts[name]=counts.get(name,0)+1
            if name not in tags:
                tags.append(name)
        out["counts"]={k:counts[k] for k in list(counts)[:30]}
        out["sample_tags"]=tags[:40]
    except Exception as exc:
        out["parse_error"]=type(exc).__name__
        out["preview"]=" ".join((text or "").replace("\r"," ").replace("\n"," ").split())[:260]
    return out

async def probe_supabets_marketws():
    result={"provider":"Supabets MarketWS","base":BASE,"probes":[],"errors":[]}
    tests=[
        {
            "name":"GetListOdds_OddLessThan",
            "url":BASE+"/GetListOdds_OddLessThan",
            "params":{"strQuotaMax":"1000","strIDSport":"","typeOrder":"0","tipoVisQuote":"0"},
        },
        {
            "name":"GetListOdds_OddLessThan sport 1",
            "url":BASE+"/GetListOdds_OddLessThan",
            "params":{"strQuotaMax":"1000","strIDSport":"1","typeOrder":"0","tipoVisQuote":"0"},
        },
        {
            "name":"GetListOdds_OddLessThan sport 163",
            "url":BASE+"/GetListOdds_OddLessThan",
            "params":{"strQuotaMax":"1000","strIDSport":"163","typeOrder":"0","tipoVisQuote":"0"},
        },
    ]
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            headers={"User-Agent":"Mozilla/5.0","Accept":"text/xml,application/xml;q=0.9,*/*;q=0.8"},
        ) as client:
            for test in tests:
                item={"name":test["name"],"status":None,"final_url":None,"location":None,"content_type":"","xml":{}}
                try:
                    r=await client.get(test["url"],params=test["params"])
                    item["status"]=r.status_code
                    item["final_url"]=str(r.url)
                    item["location"]=r.headers.get("location")
                    item["content_type"]=str(r.headers.get("content-type") or "")
                    item["xml"]=_summarize_xml(r.text or "")
                except Exception as exc:
                    item["error"]=f"{type(exc).__name__}: {exc}"
                result["probes"].append(item)
    except Exception as exc:
        result["errors"].append(f"MarketWS probe failed: {type(exc).__name__}: {exc}")
    return result
