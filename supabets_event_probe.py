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

            api_occurrences = []
            api_seen = set()
            for src in scripts[:40]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 3500000:
                        continue

                    search_from = 0
                    needle = "/api/b2c/"
                    while True:
                        idx = text.find(needle, search_from)
                        if idx < 0:
                            break

                        left = max(0, idx - 260)
                        right = min(len(text), idx + 900)
                        context = " ".join(
                            text[left:right]
                            .replace("\r", " ")
                            .replace("\n", " ")
                            .split()
                        )

                        path_end = idx
                        stop_chars = set(['"', "'", " ", ")", ",", ";", "}"])
                        while path_end < len(text) and path_end - idx < 320:
                            if path_end > idx and text[path_end] in stop_chars:
                                break
                            path_end += 1
                        path = text[idx:path_end].replace("\\/", "/")

                        key = (src.rsplit("/", 1)[-1], path)
                        if key not in api_seen:
                            api_seen.add(key)
                            api_occurrences.append({
                                "path": path,
                                "script": src.rsplit("/", 1)[-1],
                                "context": context[:1100],
                            })

                        search_from = idx + len(needle)

                except Exception:
                    continue

            result["api_path_occurrences"] = api_occurrences[:120]

            eventsprogram_paths = []
            eventsprogram_seen = set()
            for src in scripts[:40]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 3500000:
                        continue

                    needle = "/api/b2c/EventsProgram/"
                    search_from = 0
                    while True:
                        idx = text.find(needle, search_from)
                        if idx < 0:
                            break

                        end = idx
                        while end < len(text) and end - idx < 400:
                            ch = text[end]
                            if end > idx and ch in ('"', "'", "`"):
                                break
                            end += 1

                        path = text[idx:end].replace("\\/", "/")
                        if path and path not in eventsprogram_seen:
                            eventsprogram_seen.add(path)
                            left = max(0, idx - 180)
                            right = min(len(text), idx + 800)
                            context = " ".join(
                                text[left:right]
                                .replace("\r", " ")
                                .replace("\n", " ")
                                .split()
                            )
                            eventsprogram_paths.append({
                                "path": path,
                                "script": src.rsplit("/", 1)[-1],
                                "context": context[:900],
                            })

                        search_from = idx + len(needle)
                except Exception:
                    continue

            result["eventsprogram_paths"] = eventsprogram_paths[:80]
    except Exception as exc:
        result["errors"].append(
            f"Supabets sport call discovery failed: {type(exc).__name__}: {exc}"
        )
    return result


async def fetch_supabets_soccer_event_samples():
    url = "https://apib2c.supabets.co.za/api/b2c/EventsProgram/program?sportId=163"
    headers = {
        "x-api-key": "H3DigitalAPIB2CWebsiteUser",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://new.supabets.co.za",
        "Referer": "https://new.supabets.co.za/",
        "User-Agent": "Mozilla/5.0",
    }
    result = {
        "provider": "Supabets Public Sports API",
        "status": None,
        "event_samples": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)
            result["status"] = response.status_code
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(data, list) or not data or not isinstance(data[0], dict):
                result["errors"].append("Unexpected soccer program structure")
                return result

            groups = data[0].get("groups") or []
            samples = []
            for group in groups:
                if not isinstance(group, dict):
                    continue
                group_name = group.get("name")
                events = group.get("events") or []
                if not isinstance(events, list):
                    continue
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    samples.append({
                        "group": group_name,
                        "eventId": event.get("eventId"),
                        "name": event.get("name"),
                        "slug": event.get("slug"),
                        "subEventsCount": event.get("subEventsCount"),
                    })
                    if len(samples) >= 20:
                        break
                if len(samples) >= 20:
                    break
            result["event_samples"] = samples
    except Exception as exc:
        result["errors"].append(
            f"Supabets soccer event sample failed: {type(exc).__name__}: {exc}"
        )
    return result


async def discover_supabets_event_detail_calls():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "event_detail_contexts": [],
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

            tokens = ("eventId=", "subEvent", "subevent", "EventsProgram/")
            contexts = []
            seen = set()

            for src in scripts[:40]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 3500000:
                        continue
                    result["scripts_scanned"] += 1
                    lower = text.lower()

                    for token in tokens:
                        needle = token.lower()
                        search_from = 0
                        hits = 0
                        while hits < 20:
                            idx = lower.find(needle, search_from)
                            if idx < 0:
                                break
                            left = max(0, idx - 700)
                            right = min(len(text), idx + 1500)
                            context = " ".join(
                                text[left:right]
                                .replace("\r", " ")
                                .replace("\n", " ")
                                .split()
                            )

                            if "/api/b2c/" in context or "sportB2CApi" in context:
                                key = (src.rsplit("/", 1)[-1], token, context[:260])
                                if key not in seen:
                                    seen.add(key)
                                    contexts.append({
                                        "token": token,
                                        "script": src.rsplit("/", 1)[-1],
                                        "context": context[:2000],
                                    })

                            search_from = idx + len(needle)
                            hits += 1
                except Exception:
                    continue

            result["event_detail_contexts"] = contexts[:60]
    except Exception as exc:
        result["errors"].append(
            f"Supabets event-detail discovery failed: {type(exc).__name__}: {exc}"
        )

    return result


async def discover_supabets_b2c_betting_paths():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "betting_paths": [],
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

            keywords = (
                "event", "subevent", "market", "odd", "fixture",
                "coupon", "bet", "program", "sport"
            )
            found = []
            seen = set()

            for src in scripts[:40]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 3500000:
                        continue
                    result["scripts_scanned"] += 1

                    needle = "/api/b2c/"
                    search_from = 0
                    while True:
                        idx = text.find(needle, search_from)
                        if idx < 0:
                            break

                        end = idx
                        while end < len(text) and end - idx < 500:
                            ch = text[end]
                            if end > idx and ch in ('"', "'", "`", " ", "\n", "\r"):
                                break
                            end += 1

                        path = text[idx:end].replace("\\/", "/")
                        low_path = path.lower()

                        if any(k in low_path for k in keywords):
                            key = (src.rsplit("/", 1)[-1], path)
                            if key not in seen:
                                seen.add(key)
                                left = max(0, idx - 300)
                                right = min(len(text), idx + 1200)
                                context = " ".join(
                                    text[left:right]
                                    .replace("\r", " ")
                                    .replace("\n", " ")
                                    .split()
                                )
                                found.append({
                                    "path": path,
                                    "script": src.rsplit("/", 1)[-1],
                                    "context": context[:1400],
                                })

                        search_from = idx + len(needle)
                except Exception:
                    continue

            result["betting_paths"] = found[:120]
    except Exception as exc:
        result["errors"].append(
            f"Supabets B2C betting path discovery failed: {type(exc).__name__}: {exc}"
        )
    return result


async def discover_supabets_public_routes():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "route_candidates": [],
        "script_route_candidates": [],
        "scripts_scanned": 0,
        "errors": [],
    }

    def is_route_candidate(value):
        if not value:
            return False
        low = value.lower()
        if low.startswith(("mailto:", "tel:", "javascript:", "#")):
            return False
        if any(x in low for x in (
            "/assets/", "/_next/", ".webp", ".png", ".jpg", ".jpeg",
            ".svg", ".gif", ".css", ".js", ".ico", ".woff", ".woff2"
        )):
            return False
        if value.startswith("http") and not value.startswith(base):
            return False
        return any(k in low for k in (
            "soccer", "football", "sport", "event",
            "premier-league", "champions-league", "laliga"
        ))

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

            routes = []
            seen = set()
            pos = 0
            while True:
                href_pos = html.lower().find("href=", pos)
                if href_pos < 0:
                    break
                value_start = href_pos + 5
                while value_start < len(html) and html[value_start].isspace():
                    value_start += 1
                if value_start < len(html) and html[value_start] in ('"', "'"):
                    quote = html[value_start]
                    value_end = html.find(quote, value_start + 1)
                    if value_end > value_start:
                        href = html[value_start + 1:value_end]
                        if is_route_candidate(href):
                            full = urljoin(base, href)
                            if full not in seen:
                                seen.add(full)
                                routes.append(full)
                    pos = value_end + 1 if value_end > value_start else value_start + 1
                else:
                    pos = value_start + 1
            result["route_candidates"] = routes[:80]

            scripts = []
            pos = 0
            while True:
                start_tag = html.lower().find("<script", pos)
                if start_tag < 0:
                    break
                end_tag = html.find(">", start_tag)
                if end_tag < 0:
                    break
                tag = html[start_tag:end_tag + 1]
                low_tag = tag.lower()
                src_pos = low_tag.find("src=")
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
                pos = end_tag + 1

            script_routes = []
            script_seen = set()
            tokens = (
                "/sports/", "/sport/", "/soccer/", "/football/",
                "/event/", "/events/", "premier-league",
                "champions-league", "laliga"
            )

            for src in scripts[:40]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 3500000:
                        continue
                    result["scripts_scanned"] += 1

                    lower = text.lower()
                    for token in tokens:
                        search_from = 0
                        hits = 0
                        while hits < 25:
                            idx = lower.find(token, search_from)
                            if idx < 0:
                                break

                            left_quote = -1
                            quote_char = ""
                            j = idx - 1
                            while j >= max(0, idx - 220):
                                if text[j] in ('"', "'", "`"):
                                    left_quote = j
                                    quote_char = text[j]
                                    break
                                j -= 1

                            if left_quote >= 0:
                                right_quote = text.find(quote_char, idx)
                                if right_quote > idx and right_quote - left_quote <= 420:
                                    value = text[left_quote + 1:right_quote].replace("\\/", "/")
                                    if is_route_candidate(value):
                                        full = urljoin(base, value)
                                        if full not in script_seen:
                                            script_seen.add(full)
                                            script_routes.append(full)

                            search_from = idx + len(token)
                            hits += 1
                except Exception:
                    continue

            result["script_route_candidates"] = script_routes[:100]
    except Exception as exc:
        result["errors"].append(
            f"Supabets public route discovery failed: {type(exc).__name__}: {exc}"
        )
    return result


async def discover_supabets_sports_page_calls():
    targets = [
        "https://new.supabets.co.za/sports",
        "https://new.supabets.co.za/?view=all&section=Popular%20Sports",
    ]
    result = {
        "provider": "Supabets New Site",
        "pages": [],
        "errors": [],
    }

    async def inspect_page(client, page_url):
        page_result = {
            "url": page_url,
            "status": None,
            "final_url": None,
            "script_count": 0,
            "scripts_scanned": 0,
            "api_paths": [],
            "route_paths": [],
        }
        response = await client.get(page_url)
        page_result["status"] = response.status_code
        page_result["final_url"] = str(response.url)
        response.raise_for_status()
        html = response.text or ""

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
                        src = urljoin(str(response.url), tag[value_start + 1:value_end])
                        if src not in scripts:
                            scripts.append(src)
            pos = end + 1
        page_result["script_count"] = len(scripts)

        api_found = []
        api_seen = set()
        route_found = []
        route_seen = set()

        for src in scripts[:50]:
            try:
                js = await client.get(src)
                if js.status_code >= 400:
                    continue
                text = js.text or ""
                if len(text) > 4000000:
                    continue
                page_result["scripts_scanned"] += 1

                needle = "/api/b2c/"
                search_from = 0
                while True:
                    idx = text.find(needle, search_from)
                    if idx < 0:
                        break
                    end_idx = idx
                    while end_idx < len(text) and end_idx - idx < 500:
                        ch = text[end_idx]
                        if end_idx > idx and ch in ('"', "'", "`", " ", "\n", "\r"):
                            break
                        end_idx += 1
                    path = text[idx:end_idx].replace("\\/", "/")
                    low_path = path.lower()
                    if any(k in low_path for k in (
                        "event", "subevent", "market", "odd", "fixture",
                        "coupon", "program", "sport", "competition"
                    )):
                        if path not in api_seen:
                            api_seen.add(path)
                            left = max(0, idx - 250)
                            right = min(len(text), idx + 1000)
                            context = " ".join(
                                text[left:right].replace("\r"," ").replace("\n"," ").split()
                            )
                            api_found.append({
                                "path": path,
                                "script": src.rsplit("/",1)[-1],
                                "context": context[:1200],
                            })
                    search_from = idx + len(needle)

                lower = text.lower()
                for token in ("/sports", "/sport/", "/event/", "/events/", "/soccer/"):
                    search_from = 0
                    hits = 0
                    while hits < 20:
                        idx = lower.find(token, search_from)
                        if idx < 0:
                            break
                        left = max(0, idx - 220)
                        right = min(len(text), idx + 500)
                        snippet = " ".join(
                            text[left:right].replace("\r"," ").replace("\n"," ").split()
                        )
                        if snippet not in route_seen:
                            route_seen.add(snippet)
                            route_found.append({
                                "token": token,
                                "script": src.rsplit("/",1)[-1],
                                "context": snippet[:700],
                            })
                        search_from = idx + len(token)
                        hits += 1
            except Exception:
                continue

        page_result["api_paths"] = api_found[:100]
        page_result["route_paths"] = route_found[:60]
        return page_result

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            for target in targets:
                try:
                    result["pages"].append(await inspect_page(client, target))
                except Exception as exc:
                    result["pages"].append({
                        "url": target,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
    except Exception as exc:
        result["errors"].append(
            f"Supabets sports-page discovery failed: {type(exc).__name__}: {exc}"
        )

    return result


async def probe_supabets_event_endpoint_candidates():
    base = "https://apib2c.supabets.co.za"
    event_id = 990625
    headers = {
        "x-api-key": "H3DigitalAPIB2CWebsiteUser",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://new.supabets.co.za",
        "Referer": "https://new.supabets.co.za/",
        "User-Agent": "Mozilla/5.0",
    }
    candidates = [
        f"/api/b2c/EventsProgram/event?eventId={event_id}",
        f"/api/b2c/EventsProgram/events?eventId={event_id}",
        f"/api/b2c/EventsProgram/subevents?eventId={event_id}",
        f"/api/b2c/EventsProgram/sub-events?eventId={event_id}",
        f"/api/b2c/EventsProgram/program?eventId={event_id}",
        f"/api/b2c/EventsProgram/event/{event_id}",
        f"/api/b2c/EventsProgram/events/{event_id}",
        f"/api/b2c/EventsProgram/subevents/{event_id}",
    ]
    result = {
        "provider": "Supabets Public Sports API",
        "eventId": event_id,
        "probes": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0),
            follow_redirects=True,
            headers=headers,
        ) as client:
            for path in candidates:
                item = {"path": path, "status": None, "content_type": "", "json_type": "", "top_level_keys": [], "preview": ""}
                try:
                    response = await client.get(base + path)
                    item["status"] = response.status_code
                    item["content_type"] = str(response.headers.get("content-type") or "")
                    body = (response.text or "").strip()
                    if "application/json" in item["content_type"].lower():
                        try:
                            data = response.json()
                            item["json_type"] = type(data).__name__
                            if isinstance(data, dict):
                                item["top_level_keys"] = list(data.keys())[:30]
                                item["preview"] = str({k:data.get(k) for k in item["top_level_keys"][:4]})[:420]
                            elif isinstance(data, list):
                                item["preview"] = f"list[{len(data)}]"
                        except Exception:
                            item["preview"] = body[:220]
                    else:
                        item["preview"] = " ".join(body.replace("\r"," ").replace("\n"," ").split())[:220]
                except Exception as exc:
                    item["error"] = f"{type(exc).__name__}: {exc}"
                result["probes"].append(item)
    except Exception as exc:
        result["errors"].append(
            f"Supabets event endpoint probe failed: {type(exc).__name__}: {exc}"
        )
    return result


async def inspect_supabets_competition_object():
    url = "https://apib2c.supabets.co.za/api/b2c/EventsProgram/program?sportId=163"
    headers = {
        "x-api-key": "H3DigitalAPIB2CWebsiteUser",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://new.supabets.co.za",
        "Referer": "https://new.supabets.co.za/",
        "User-Agent": "Mozilla/5.0",
    }
    target_event_id = 990625
    result = {
        "provider": "Supabets Public Sports API",
        "target_eventId": target_event_id,
        "status": None,
        "competition": None,
        "field_summary": {},
        "nested_samples": {},
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)
            result["status"] = response.status_code
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(data, list) or not data or not isinstance(data[0], dict):
                result["errors"].append("Unexpected soccer program structure")
                return result

            groups = data[0].get("groups") or []
            target = None
            target_group = None
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for event in group.get("events") or []:
                    if isinstance(event, dict) and event.get("eventId") == target_event_id:
                        target = event
                        target_group = group.get("name")
                        break
                if target:
                    break

            if not target:
                result["errors"].append("Target eventId not found in soccer program")
                return result

            compact = {"group": target_group}
            summary = {}
            nested = {}

            for key, value in target.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    compact[key] = value
                    summary[key] = type(value).__name__
                elif isinstance(value, list):
                    summary[key] = f"list[{len(value)}]"
                    if value:
                        sample = value[0]
                        if isinstance(sample, dict):
                            nested[key] = {
                                "sample_keys": list(sample.keys())[:60],
                                "sample_item": {
                                    k: sample.get(k)
                                    for k in list(sample.keys())[:20]
                                    if isinstance(sample.get(k), (str, int, float, bool)) or sample.get(k) is None
                                },
                            }
                        else:
                            nested[key] = {"sample": sample}
                elif isinstance(value, dict):
                    summary[key] = f"dict[{len(value)}]"
                    nested[key] = {
                        "keys": list(value.keys())[:60],
                        "sample": {
                            k: value.get(k)
                            for k in list(value.keys())[:20]
                            if isinstance(value.get(k), (str, int, float, bool)) or value.get(k) is None
                        },
                    }
                else:
                    summary[key] = type(value).__name__

            result["competition"] = compact
            result["field_summary"] = summary
            result["nested_samples"] = nested
    except Exception as exc:
        result["errors"].append(
            f"Supabets competition inspection failed: {type(exc).__name__}: {exc}"
        )
    return result


async def discover_supabets_subevent_loader():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "matches": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
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

            tokens = (
                "subEventsCount",
                "subeventsCount",
                "subEvent",
                "subevent",
                "eventId",
                "selectedEvent",
                "activeEvent",
            )
            matches = []
            seen = set()

            for src in scripts[:50]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 4500000:
                        continue
                    result["scripts_scanned"] += 1
                    lower = text.lower()

                    for token in tokens:
                        needle = token.lower()
                        search_from = 0
                        hits = 0
                        while hits < 20:
                            idx = lower.find(needle, search_from)
                            if idx < 0:
                                break

                            left = max(0, idx - 1800)
                            right = min(len(text), idx + 3200)
                            context = " ".join(
                                text[left:right]
                                .replace("\r", " ")
                                .replace("\n", " ")
                                .split()
                            )

                            if any(k in context for k in (
                                "sportB2CApi",
                                "/api/b2c/",
                                "fetch(",
                                "axios",
                                ".get(",
                                ".post(",
                                "WebSocket",
                                "wss://",
                            )):
                                key = (src.rsplit("/",1)[-1], token, context[:300])
                                if key not in seen:
                                    seen.add(key)
                                    matches.append({
                                        "token": token,
                                        "script": src.rsplit("/",1)[-1],
                                        "context": context[:3600],
                                    })

                            search_from = idx + len(needle)
                            hits += 1
                except Exception:
                    continue

            result["matches"] = matches[:80]
    except Exception as exc:
        result["errors"].append(
            f"Supabets sub-event loader discovery failed: {type(exc).__name__}: {exc}"
        )
    return result


async def discover_supabets_odds_loader_tokens():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "matches": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
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

            tokens = (
                "getClientActiveEventsByGroup",
                "getClientOddsBySubeEvent",
                "getClientOddsBySubEvent",
                "GetListOdds_OddLessThan",
                "MarketWS",
                "IDGruppo",
                "IDSottoEvento",
                "IDPalinsesto",
                "palinsesto",
                "odds",
                "market",
            )
            matches = []
            seen = set()

            for src in scripts[:50]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 4500000:
                        continue
                    result["scripts_scanned"] += 1
                    lower = text.lower()

                    for token in tokens:
                        needle = token.lower()
                        search_from = 0
                        hits = 0
                        while hits < 12:
                            idx = lower.find(needle, search_from)
                            if idx < 0:
                                break
                            left = max(0, idx - 1200)
                            right = min(len(text), idx + 2200)
                            context = " ".join(
                                text[left:right].replace("\r"," ").replace("\n"," ").split()
                            )
                            key = (src.rsplit("/",1)[-1], token, context[:240])
                            if key not in seen:
                                seen.add(key)
                                matches.append({
                                    "token": token,
                                    "script": src.rsplit("/",1)[-1],
                                    "context": context[:2800],
                                })
                            search_from = idx + len(needle)
                            hits += 1
                except Exception:
                    continue

            result["matches"] = matches[:100]
    except Exception as exc:
        result["errors"].append(
            f"Supabets odds-loader discovery failed: {type(exc).__name__}: {exc}"
        )
    return result


async def discover_supabets_sport_api_calls_escaped():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "calls": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
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

            calls = []
            seen = set()
            needle = "sportB2CApi."

            for src in scripts[:50]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 4500000:
                        continue
                    result["scripts_scanned"] += 1

                    search_from = 0
                    while True:
                        idx = text.find(needle, search_from)
                        if idx < 0:
                            break

                        method_start = idx + len(needle)
                        method_end = method_start
                        while method_end < len(text) and (text[method_end].isalpha() or text[method_end] == "_"):
                            method_end += 1
                        method = text[method_start:method_end]

                        paren = text.find("(", method_end, min(len(text), method_end + 40))
                        path = ""
                        if paren >= 0:
                            p = paren + 1
                            while p < len(text) and (text[p].isspace() or text[p] == "\\"):
                                p += 1
                            if p < len(text) and text[p] in ('"', "'", "`"):
                                quote = text[p]
                                q = p + 1
                                chars = []
                                while q < len(text) and q - p < 500:
                                    ch = text[q]
                                    if ch == "\\" and q + 1 < len(text):
                                        nxt = text[q + 1]
                                        if nxt in ('"', "'", "`", "/", "\\"):
                                            chars.append(nxt)
                                            q += 2
                                            continue
                                    if ch == quote:
                                        break
                                    chars.append(ch)
                                    q += 1
                                path = "".join(chars)

                        left = max(0, idx - 180)
                        right = min(len(text), idx + 1100)
                        context = " ".join(
                            text[left:right].replace("\r"," ").replace("\n"," ").split()
                        )

                        key = (method, path, src.rsplit("/",1)[-1])
                        if key not in seen:
                            seen.add(key)
                            calls.append({
                                "method": method,
                                "path": path,
                                "script": src.rsplit("/",1)[-1],
                                "context": context[:1300],
                            })

                        search_from = idx + len(needle)
                except Exception:
                    continue

            result["calls"] = calls[:120]
    except Exception as exc:
        result["errors"].append(
            f"Supabets escaped sport API discovery failed: {type(exc).__name__}: {exc}"
        )
    return result


async def inspect_supabets_sport_client_raw():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "matches": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
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
                "sportB2CApi",
                "EventsProgram/program?",
                "EventsProgram/sports-full",
                "apib2c.supabets.co.za",
            )
            seen = set()
            matches = []

            for src in scripts[:50]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 5000000:
                        continue
                    result["scripts_scanned"] += 1

                    for needle in needles:
                        search_from = 0
                        hits = 0
                        while hits < 12:
                            idx = text.find(needle, search_from)
                            if idx < 0:
                                break
                            left = max(0, idx - 700)
                            right = min(len(text), idx + 1800)
                            raw = text[left:right]
                            compact = " ".join(
                                raw.replace("\r", " ").replace("\n", " ").split()
                            )
                            key = (src.rsplit("/",1)[-1], needle, idx)
                            if key not in seen:
                                seen.add(key)
                                matches.append({
                                    "needle": needle,
                                    "script": src.rsplit("/",1)[-1],
                                    "index": idx,
                                    "context": compact[:2200],
                                })
                            search_from = idx + len(needle)
                            hits += 1
                except Exception:
                    continue

            result["matches"] = matches[:80]
    except Exception as exc:
        result["errors"].append(
            f"Supabets raw sport-client inspection failed: {type(exc).__name__}: {exc}"
        )
    return result


async def inspect_supabets_sport_client_module():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "modules": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
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

            found = []
            seen = set()
            needle = "sportB2CApi"

            for src in scripts[:50]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 5000000:
                        continue
                    result["scripts_scanned"] += 1

                    search_from = 0
                    hits = 0
                    while hits < 20:
                        idx = text.find(needle, search_from)
                        if idx < 0:
                            break

                        left = max(0, idx - 1200)
                        right = min(len(text), idx + 7000)
                        block = text[left:right]

                        api_paths = []
                        p = 0
                        while True:
                            api_idx = block.find("/api/b2c/", p)
                            if api_idx < 0:
                                break
                            api_end = api_idx
                            while api_end < len(block) and api_end - api_idx < 500:
                                ch = block[api_end]
                                if api_end > api_idx and ch in ('"', "'", "`", " ", "\n", "\r", "\\"):
                                    # allow escaped slash but stop at escaped quote
                                    if ch == "\\" and api_end + 1 < len(block) and block[api_end + 1] == "/":
                                        api_end += 2
                                        continue
                                    break
                                api_end += 1
                            path = block[api_idx:api_end].replace("\\/", "/")
                            if path and path not in api_paths:
                                api_paths.append(path)
                            p = api_idx + 8

                        compact = " ".join(
                            block.replace("\r", " ").replace("\n", " ").split()
                        )
                        key = (src.rsplit("/",1)[-1], idx)
                        if key not in seen:
                            seen.add(key)
                            found.append({
                                "script": src.rsplit("/",1)[-1],
                                "index": idx,
                                "api_paths_nearby": api_paths[:40],
                                "context": compact[:6500],
                            })

                        search_from = idx + len(needle)
                        hits += 1
                except Exception:
                    continue

            result["modules"] = found[:30]
    except Exception as exc:
        result["errors"].append(
            f"Supabets sport-client module inspection failed: {type(exc).__name__}: {exc}"
        )
    return result


async def inspect_supabets_eventsprogram_module():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "matches": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
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
                "EventsProgram/program?",
                "EventsProgram/sports-full",
            )
            matches = []
            seen = set()

            for src in scripts[:50]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 5000000:
                        continue
                    result["scripts_scanned"] += 1

                    for needle in needles:
                        search_from = 0
                        hits = 0
                        while hits < 8:
                            idx = text.find(needle, search_from)
                            if idx < 0:
                                break

                            left = max(0, idx - 2500)
                            right = min(len(text), idx + 12000)
                            block = text[left:right]
                            compact = " ".join(
                                block.replace("\r", " ").replace("\n", " ").split()
                            )

                            nearby_paths = []
                            p = 0
                            while True:
                                api_idx = block.find("/api/b2c/", p)
                                if api_idx < 0:
                                    break
                                api_end = api_idx
                                while api_end < len(block) and api_end - api_idx < 700:
                                    ch = block[api_end]
                                    if api_end > api_idx and ch in ('"', "'", "`", " ", "\n", "\r"):
                                        break
                                    api_end += 1
                                path = block[api_idx:api_end].replace("\\/", "/")
                                if path and path not in nearby_paths:
                                    nearby_paths.append(path)
                                p = api_idx + 8

                            key = (src.rsplit("/",1)[-1], needle, idx)
                            if key not in seen:
                                seen.add(key)
                                matches.append({
                                    "needle": needle,
                                    "script": src.rsplit("/",1)[-1],
                                    "index": idx,
                                    "api_paths_nearby": nearby_paths[:60],
                                    "context": compact[:10000],
                                })

                            search_from = idx + len(needle)
                            hits += 1
                except Exception:
                    continue

            result["matches"] = matches[:20]
    except Exception as exc:
        result["errors"].append(
            f"Supabets EventsProgram module inspection failed: {type(exc).__name__}: {exc}"
        )
    return result


async def inspect_supabets_api_clients():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "clients": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
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
                "baseURL",
                "apib2c.supabets.co.za",
                "supaskins-backend.azurewebsites.net",
                "api.sbpay.co.za",
                "axios.create",
                ".create({baseURL",
            )
            found = []
            seen = set()

            for src in scripts[:50]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 5000000:
                        continue
                    result["scripts_scanned"] += 1
                    lower = text.lower()

                    for needle in needles:
                        needle_lower = needle.lower()
                        search_from = 0
                        hits = 0
                        while hits < 16:
                            idx = lower.find(needle_lower, search_from)
                            if idx < 0:
                                break
                            left = max(0, idx - 1800)
                            right = min(len(text), idx + 3600)
                            block = text[left:right]
                            compact = " ".join(
                                block.replace("\r"," ").replace("\n"," ").split()
                            )
                            key = (src.rsplit("/",1)[-1], needle, idx)
                            if key not in seen:
                                seen.add(key)
                                found.append({
                                    "needle": needle,
                                    "script": src.rsplit("/",1)[-1],
                                    "index": idx,
                                    "context": compact[:4800],
                                })
                            search_from = idx + len(needle_lower)
                            hits += 1
                except Exception:
                    continue

            result["clients"] = found[:80]
    except Exception as exc:
        result["errors"].append(
            f"Supabets API-client inspection failed: {type(exc).__name__}: {exc}"
        )
    return result


async def inspect_supabets_fixtures_route_context():
    base = "https://new.supabets.co.za/"
    result = {
        "provider": "Supabets New Site",
        "reachable": False,
        "scripts_scanned": 0,
        "matches": [],
        "errors": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
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
                '"/fixtures"',
                "'/fixtures'",
                "/fixtures",
                "fixtures",
            )
            found = []
            seen = set()

            for src in scripts[:50]:
                try:
                    response = await client.get(src)
                    if response.status_code >= 400:
                        continue
                    text = response.text or ""
                    if len(text) > 5000000:
                        continue
                    result["scripts_scanned"] += 1
                    lower = text.lower()

                    for needle in needles:
                        needle_lower = needle.lower()
                        search_from = 0
                        hits = 0
                        while hits < 20:
                            idx = lower.find(needle_lower, search_from)
                            if idx < 0:
                                break

                            left = max(0, idx - 2600)
                            right = min(len(text), idx + 8000)
                            block = text[left:right]
                            compact = " ".join(
                                block.replace("\r"," ").replace("\n"," ").split()
                            )

                            api_paths = []
                            p = 0
                            while True:
                                api_idx = block.find("/api/", p)
                                if api_idx < 0:
                                    break
                                api_end = api_idx
                                while api_end < len(block) and api_end - api_idx < 700:
                                    ch = block[api_end]
                                    if api_end > api_idx and ch in ('"', "'", "`", " ", "\n", "\r"):
                                        break
                                    api_end += 1
                                path = block[api_idx:api_end].replace("\\/", "/")
                                if path and path not in api_paths:
                                    api_paths.append(path)
                                p = api_idx + 5

                            urls = []
                            for host in (
                                "https://apib2c.supabets.co.za",
                                "https://supaskins-backend.azurewebsites.net/api/v1",
                                "https://api.sbpay.co.za",
                            ):
                                if host in block and host not in urls:
                                    urls.append(host)

                            key = (src.rsplit("/",1)[-1], needle, idx)
                            if key not in seen:
                                seen.add(key)
                                found.append({
                                    "needle": needle,
                                    "script": src.rsplit("/",1)[-1],
                                    "index": idx,
                                    "backend_urls_nearby": urls,
                                    "api_paths_nearby": api_paths[:60],
                                    "context": compact[:7000],
                                })

                            search_from = idx + len(needle_lower)
                            hits += 1
                except Exception:
                    continue

            result["matches"] = found[:40]
    except Exception as exc:
        result["errors"].append(
            f"Supabets fixtures route inspection failed: {type(exc).__name__}: {exc}"
        )
    return result
