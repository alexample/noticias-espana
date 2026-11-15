"""Prueba direcciones RSS candidatas: python tools/probar_feeds.py tools/candidatos.json

Para cada medio prueba sus URLs con el User-Agent del worker y con uno de navegador,
y muestra estado, número de artículos y fecha del más reciente."""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
import feeds  # noqa: E402

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


def probe(url, ua):
    config.USER_AGENT = ua
    try:
        status, body, _, _ = feeds.fetch(url, timeout=20)
        items = feeds.parse(body)
        newest = max((i["published"] or 0 for i in items), default=0)
        age = f"{(time.time() - newest) / 3600:.1f}h" if newest else "sin fecha"
        return f"OK {status} · {len(items)} artículos · último hace {age}"
    except Exception as e:
        return f"FALLA {type(e).__name__}: {str(e)[:90]}"


def main(path):
    default_ua = config.USER_AGENT
    with open(path, encoding="utf-8") as f:
        cands = json.load(f)
    for name, urls in cands.items():
        print(f"\n=== {name}")
        for url in urls:
            for label, ua in (("bot", default_ua), ("nav", BROWSER_UA)):
                print(f"  [{label}] {url}\n        {probe(url, ua)}")


if __name__ == "__main__":
    main(sys.argv[1])
