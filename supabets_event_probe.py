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
