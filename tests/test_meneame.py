"""Comentarios de Menéame con RSS simulados (mismo formato que los reales)."""
import json
import os
import sys
import tempfile
import time
import unittest
from email.utils import formatdate

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import db  # noqa: E402
import export  # noqa: E402
import meneame  # noqa: E402
from textproc import article_features  # noqa: E402

NOW = time.time()
NS = 'xmlns:meneame="http://meneame.net/faq-es.php"'


def story(link_id, title, url, comments):
    return (f"<item><meneame:link_id>{link_id}</meneame:link_id><meneame:comments>{comments}</meneame:comments>"
            f"<comments>https://www.meneame.net/story/s{link_id}</comments><meneame:url>{url}</meneame:url>"
            f"<title>{title}</title><link>https://www.meneame.net/story/s{link_id}</link>"
            f"<pubDate>{formatdate(NOW - 1800)}</pubDate>"
            f'<description><![CDATA[<p>Resumen <a href="{url}">enlace</a></p>]]></description></item>')


def comment(cid, link_id, text, votes, user="pepe"):
    return (f"<item><meneame:comment_id>{cid}</meneame:comment_id><meneame:link_id>{link_id}</meneame:link_id>"
            f"<meneame:user>{user}</meneame:user><meneame:votes>{votes}</meneame:votes><meneame:karma>20</meneame:karma>"
            f"<title>#{cid} Algo</title><pubDate>{formatdate(NOW - 600)}</pubDate>"
            f"<description><![CDATA[<p>{text}</p><p>&#187;&nbsp;autor: <strong>{user}</strong></p>]]></description></item>")


def rss(items):
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" {NS}><channel>{"".join(items)}</channel></rss>'.encode()


class FakeMeneame:
    def __init__(self):
        self.urls = []

    def __call__(self, url, *a, **k):
        self.urls.append(url)
        if url.endswith("/rss"):
            return 200, rss([
                story(1001, "La Generalitat pide no salir de casa por la DANA en Valencia",
                      "https://www.eldiario.es/valencia/dana-alerta.html?utm_source=meneame", 40),   # por enlace
                story(1002, "Receta de croquetas", "https://cocina.example/croquetas", 3),             # sin noticia
            ]), None, None
        if "status=queued" in url:
            return 200, rss([story(1003, "Alerta roja por lluvias torrenciales en Valencia, la DANA obliga a cerrar colegios",
                                   "https://blog.example/dana", 12)]), None, None                      # por título
        if "comments_rss?id=1001" in url:
            return 200, rss([comment(i, 1001, f"Opinión {i} sobre la DANA #3 https://x.es/y", i) for i in range(10)]), None, None
        if "comments_rss?id=1003" in url:
            return 200, rss([comment(50 + i, 1003, f"Otra opinión {i}", 1, user="ana") for i in range(4)]), None, None
        raise AssertionError(url)


class TestMeneame(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(os.path.join(tempfile.mkdtemp(), "m.db"))
        db.init(self.conn)
        self.conn.execute("""INSERT INTO clusters(id, created_at, updated_at, n_sources, n_articles, relevance, status,
                             first_published, last_published, headline, tag, ai_written_at)
                             VALUES (1,?,?,3,3,9,'active',?,?, 'Alerta roja en Valencia por la DANA', '', ?)""",
                          (NOW, NOW, NOW - 7200, NOW - 600, NOW - 300))
        arts = [("elDiario.es", "Alerta roja en Valencia por la DANA: lluvias torrenciales",
                 "https://www.eldiario.es/valencia/dana-alerta.html"),
                ("El País", "La DANA obliga a cerrar colegios en Valencia por las lluvias torrenciales", "https://elpais.example/1"),
                ("RTVE", "Alerta roja por la DANA en Valencia", "https://rtve.example/1")]
        for i, (src, t, url) in enumerate(arts):
            f, e = article_features(t, "")
            self.conn.execute("""INSERT INTO articles(url, source, title, title_key, summary, published_at, fetched_at,
                                 features, entities, cluster_id) VALUES (?,?,?,?,'',?,?,?,?,1)""",
                              (url, src, t, f"k{i}", NOW - 3600, NOW, json.dumps(f), json.dumps(e)))
        self.conn.commit()

    def test_limpia_comentarios(self):
        self.assertEqual(meneame.clean_comment("<p>Muy bien #2 dicho https://a.es/b</p><p>&#187;&nbsp;autor: <strong>pepe</strong></p>"),
                         "Muy bien dicho")

    def test_asigna_por_enlace_y_por_titulo_y_lee_comentarios(self):
        fake = FakeMeneame()
        stats = meneame.process(self.conn, NOW, fetch=fake)
        self.assertEqual(stats["new"], 3)
        self.assertEqual(stats["matched"], 2)
        rows = dict(self.conn.execute("SELECT link_id, cluster_id FROM mnm_links").fetchall())
        self.assertEqual(rows, {1001: 1, 1002: -1, 1003: 1})
        self.assertEqual(stats["comments"], 14)
        texts = [r[0] for r in self.conn.execute("SELECT text FROM yt_comments ORDER BY likes DESC")]
        self.assertEqual(texts[0], "Opinión 9 sobre la DANA")
        self.assertFalse(any("pepe" in t or "ana" in t or "http" in t for t in texts))   # sin autores ni enlaces
        # no se relee antes de 90 min
        fake2 = FakeMeneame()
        meneame.process(self.conn, NOW + 600, fetch=fake2)
        self.assertFalse(any("comments_rss" in u for u in fake2.urls))
        # el resumen y la web indican Menéame
        self.conn.execute("UPDATE clusters SET readers_summary='Resumen', readers_count=14, readers_at=? WHERE id=1", (NOW,))
        self.conn.commit()
        out = os.path.join(tempfile.mkdtemp(), "data")
        export.export_static(self.conn, out)
        r = json.load(open(os.path.join(out, "stories.json")))["stories"][0]["readers"]
        self.assertEqual(r["platforms"], ["Menéame"])
        self.assertTrue(r["videos"][0]["url"].startswith("https://www.meneame.net/story/s100"))

    def test_menéame_caído_no_rompe(self):
        def down(url, *a, **k):
            return 403, None, None, None
        self.assertEqual(meneame.process(self.conn, NOW, fetch=down), {"new": 0, "matched": 0, "comments": 0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
