from urllib.parse import urljoin
import httpx

async def discover_supabets_sport_calls():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "sport_client_calls": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            page = await client.get(base)
            page.raise_for_status()
            result["reachable"] = True
            html = page.text or ""

            scripts = []
            pos = 0
            while True:
                start = html.lower().find("<script", pos)
                if start < 0:
                    break
                end = html.find(">", start)
                if end < 0:
                    break
                tag = html[start:end + 1]
                low = tag.lower()
                src_pos = low.find("src=")
                if src_pos >= 0:
                    value_start = src_pos + 4
                    while value_start < len(tag) and tag[value_start].isspace():
                        value_start += 1
                    if value_start < len(tag) and tag[value_start] in ('"', "'"):
                        quote = tag[value_start]
                        value_end = tag.find(quote, value_start + 1)
                        if value_end > value_start:
                            src = urljoin(base, tag[value_start + 1:value_end])
                            if src not in scripts:
                                scripts.append(src)
                pos = end + 1

            needles = (
                "sportB2CApi.get(",
                "sportB2CApi.post(",
                "sportB2CApi.put(",
                "sportB2CApi.delete(",
            )
            seen = set()
            calls = []

            for src in scripts[:40]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 3500000:
                        continue
                    result["scripts_scanned"] += 1

                    for needle in needles:
                        search_from = 0
                        while True:
                            idx = text.find(needle, search_from)
                            if idx < 0:
                                break
                            method = needle.split(".", 1)[1].split("(", 1)[0].upper()
                            arg_start = idx + len(needle)
                            while arg_start < len(text) and text[arg_start].isspace():
                                arg_start += 1

                            path = ""
                            if arg_start < len(text) and text[arg_start] in ('"', "'", "`"):
                                quote = text[arg_start]
                                value_end = text.find(quote, arg_start + 1)
                                if value_end > arg_start:
                                    path = text[arg_start + 1:value_end].replace("\\/", "/")

                            if path:
                                key = (method, path)
                                if key not in seen:
                                    seen.add(key)
                                    left = max(0, idx - 220)
                                    right = min(len(text), idx + 1000)
                                    context = " ".join(
                                        text[left:right]
                                        .replace("\r", " ")
                                        .replace("\n", " ")
                                        .split()
                                    )
                                    calls.append({
                                        "method": method,
                                        "path": path,
                                        "script": src.rsplit("/", 1)[-1],
                                        "context": context[:1100],
                                    })
                            search_from = idx + len(needle)
                except Exception:
                    continue

            result["sport_client_calls"] = calls[:120]
    except Exception as exc:
        result["errors"].append(
            f"Supabets sport call discovery failed: {type(exc).__name__}: {exc}"
        )
    return result
