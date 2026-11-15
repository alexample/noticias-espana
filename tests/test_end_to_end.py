"""Flujo completo con feeds RSS locales (file://) y la IA simulada."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from email.utils import formatdate
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
import db  # noqa: E402
import server  # noqa: E402
import worker  # noqa: E402
import writer  # noqa: E402
from tests.fixtures_data import STORIES  # noqa: E402


def rss(items):
    body = "".join(
        f"<item><title>{escape(t)}</title><link>{escape(u)}?utm_source=rss</link>"
        f"<description><![CDATA[<p>{s}</p>]]></description><pubDate>{formatdate(ts)}</pubDate>"
        f'<media:content url="https://img.example/{abs(hash(u))}.jpg" medium="image"/></item>'
        for t, s, u, ts in items)
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" '
            'xmlns:media="http://search.yahoo.com/mrss/"><channel><title>x</title>'
            f"{body}&nbsp;</channel></rss>")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        config.DB_PATH = os.path.join(self.tmp, "t.db")
        self.calls = []
        config.ANTHROPIC_API_KEY = "test"

        def fake_claude(prompt, system, max_tokens=1200):
            self.calls.append(prompt)
            n = prompt.count("Titular:")
            return json.dumps({"titular": f"Noticia redactada con {n} medios",
                               "entradilla": "Entradilla.", "cuerpo": "Párrafo uno.\n\nPárrafo dos."})
        writer.call_claude = fake_claude

    def write_feeds(self, round_):
        """Ronda 1: primer artículo de cada historia. Ronda 2: todos."""
        now = time.time()
        per_source = {}
        for label, arts in STORIES.items():
            chosen = arts[:1] if round_ == 1 else arts
            for i, (src, t, s) in enumerate(chosen):
                url = f"https://{src.replace(' ', '').lower()}.example/{label}/{i}"
                per_source.setdefault(src, []).append((t, s, url, now - 3600 + i * 300))
        feeds = []
        for src, items in per_source.items():
            path = os.path.join(self.tmp, f"{abs(hash(src))}.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(rss(items))
            feeds.append({"name": src, "url": "file://" + path, "weight": 1.0})
        all_sources = {a[0] for arts in STORIES.values() for a in arts}
        for src in all_sources - set(per_source):  # medios sin artículos aún: feed vacío
            path = os.path.join(self.tmp, f"{abs(hash(src))}.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(rss([]))
            feeds.append({"name": src, "url": "file://" + path, "weight": 1.0})
        ff = os.path.join(self.tmp, "feeds.json")
        with open(ff, "w") as f:
            json.dump(feeds, f)
        return ff

    def test_flujo(self):
        conn = db.connect()
        db.init(conn)

        # ronda 1: una pieza por historia -> 10 noticias de 1 medio, sin IA
        db.sync_sources(conn, self.write_feeds(1))
        s1 = worker.run_cycle(conn)
        self.assertEqual(s1["new"], len(STORIES))
        self.assertEqual(s1["ai_written"], 0)

        # ronda 2: llegan el resto -> se añaden a las existentes, no se crean nuevas
        db.sync_sources(conn, self.write_feeds(2))
        s2 = worker.run_cycle(conn)
        self.assertEqual(s2["new"], 0, "los artículos nuevos debían añadirse a noticias existentes")
        multi = [k for k, v in STORIES.items() if len({a[0] for a in v}) >= 2]
        self.assertEqual(s2["ai_written"], len(multi))

        # ronda 3: nada nuevo -> nada cambia, la IA no se vuelve a llamar
        calls = len(self.calls)
        s3 = worker.run_cycle(conn)
        self.assertEqual((s3["new"], s3["joined"], s3["ai_written"]), (0, 0, 0))
        self.assertEqual(len(self.calls), calls)

        stories = server.list_stories(conn, min_sources=2)
        self.assertEqual(len(stories), len(multi))
        top = stories[0]
        self.assertTrue(top["ai_written"])
        self.assertEqual(top["n_sources"], 5)  # la DANA es la de más medios
        detail = server.get_story(conn, top["id"])
        self.assertEqual(len(detail["articles"]), 5)
        self.assertNotIn("utm_source", detail["articles"][0]["url"])

        # servidor HTTP real
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        api = json.loads(urllib.request.urlopen(f"{base}/api/stories?min_sources=1").read())
        self.assertEqual(len(api), len(STORIES))
        html = urllib.request.urlopen(f"{base}/noticia/{top['id']}").read().decode()
        self.assertIn("Al", html)
        st = json.loads(urllib.request.urlopen(f"{base}/api/status").read())
        self.assertTrue(all(s["last_status"] == "ok" for s in st["sources"]))
        httpd.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
