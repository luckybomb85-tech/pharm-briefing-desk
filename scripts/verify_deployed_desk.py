"""Verify a deployed GitHub Pages briefing desk using public HTTP endpoints.

This runs AFTER Pages deployment, rather than mistaking an uploaded artifact for a
publicly served page. Limited retries allow GitHub Pages CDN propagation.
"""
import argparse
import json
import time
import urllib.error
import urllib.request


def fetch_text(url, timeout=15):
    request = urllib.request.Request(url, headers={
        "User-Agent": "pharm-briefing-desk-deployment-check/1.0",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP_{response.status}: {url}")
        return response.read().decode("utf-8")


def verify(base_url, day, minimum=4, fetcher=fetch_text):
    base = base_url.rstrip("/") + "/"
    html = fetcher(base + "index.html")
    if "./domestic/" not in html or "loadDomesticDiscovery(date)" not in html:
        raise ValueError("PUBLIC_DESK_DOMESTIC_LOADER_NOT_FOUND")
    data = json.loads(fetcher(base + "domestic/" + day + ".json"))
    if data.get("date") != day:
        raise ValueError("PUBLIC_DESK_WRONG_DATE")
    items = data.get("items")
    if not isinstance(items, list) or len(items) < minimum:
        raise ValueError(f"PUBLIC_DESK_TOO_FEW_DOMESTIC_ITEMS: {len(items) if isinstance(items,list) else 'invalid'}")
    links = [x.get("source", "") for x in items if isinstance(x, dict)]
    if len(links) != len(items) or not all(x.startswith("https://") for x in links):
        raise ValueError("PUBLIC_DESK_INVALID_SOURCE_LINK")
    if len(set(links)) != len(links):
        raise ValueError("PUBLIC_DESK_DUPLICATE_SOURCE_LINK")
    if not all(x.get("title") for x in items):
        raise ValueError("PUBLIC_DESK_MISSING_TITLE")
    return len(items)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--minimum", type=int, default=4)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--delay", type=int, default=12)
    args = parser.parse_args()
    if args.attempts < 1 or args.minimum < 1:
        parser.error("attempts and minimum must be positive")
    for attempt in range(1, args.attempts + 1):
        try:
            count = verify(args.base_url, args.date, args.minimum)
            print(f"PUBLIC_DESK_OK: {args.date}, domestic={count}, url={args.base_url}", flush=True)
            return
        except (ValueError, RuntimeError, json.JSONDecodeError, OSError, UnicodeError) as exc:
            print(f"PUBLIC_DESK_RETRY {attempt}/{args.attempts}: {exc}", flush=True)
            if attempt == args.attempts:
                raise SystemExit("PUBLIC_DESK_NOT_VERIFIED") from exc
            time.sleep(args.delay)


if __name__ == "__main__":
    main()
