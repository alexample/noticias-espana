"""Cobertura internacional con Google Noticias simulado."""
import json
import os
import sys
import tempfile
import time
import unittest
from email.utils import formatdate
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import db  # noqa: E402
import export  # noqa: E402
import intl  # noqa: E402
from textproc import article_features  # noqa: E402

TRUMP = [
    ("El País", "Trump anuncia aranceles del 25% a los coches de la Unión Europea",
     "La Casa Blanca confirma que los aranceles entrarán en vigor en marzo."),
    ("El Mundo", "La UE responde a Trump: aranceles a productos de Estados Unidos",
     "Von der Leyen promete una respuesta firme a los aranceles de Washington."),
    ("ABC", "Trump impone aranceles a los coches europeos y amenaza a la UE",
     "El presidente de Estados Unidos acusa a Bruselas de prácticas desleales."),
]
LOCAL = [
    ("El País", "Sánchez presenta los Presupuestos de 2027", "El Consejo de Ministros aprueba las cuentas."),
    ("El Mundo", "Los Presupuestos de 2027 llegan al Congreso", "Hacienda eleva la partida de vivienda."),
    ("ABC", "Presupuestos 2027: más gasto en vivienda", "Sánchez confía en sus socios."),
]


def gnews_rss(titles):
    items = "".join(f"<item><title>{escape(t)}</title><link>https://news.google.com/rss/articles/{i}</link>"
                    f"<pubDate>{formatdate(time.time() - 600)}</pubDate></item>" for i, t in enumerate(titles))
    return f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>'.encode()


class TestIntl(unittest.TestCase):
    def setUp(self):
        config.INTL_ENABLED = 1  # otros tests lo desactivan
        self.countries = intl.load_countries()
        self.urls = []

    def fake_fetch(self, url, *a, **k):
        self.urls.append(url)
        return 200, gnews_rss([
            "Trump slaps 25% tariffs on EU cars - The New York Times",
            "EU vows to retaliate against Trump tariffs - Reuters",
            "Trump tariffs: what it means for car prices - The New York Times",  # mismo medio: se ignora
            "Trump plays golf in Florida - Fox News",                            # no menciona la UE: se ignora
        ]), None, None

    def test_detecta_pais_y_terminos(self):
        texts = [f"{t}. {s}" for _, t, s in TRUMP]
        self.assertEqual(intl.detect_countries(texts, self.countries), ["us"])
        self.assertEqual(intl.detect_countries([f"{t}. {s}" for _, t, s in LOCAL], self.countries), [])
        ents = [article_features(t, s)[1] for _, t, s in TRUMP]
        self.assertEqual(sorted(intl.search_terms(ents, "en", self.countries, texts=texts)), ["EU", "trump"])
        self.assertEqual(sorted(intl.search_terms(ents, "de", self.countries, texts=texts)), ["EU", "trump"])

    def test_busqueda_filtra_resultados(self):
        res = intl.search_country(self.countries["us"], ["trump", "EU"], fetch=self.fake_fetch)
        self.assertEqual([r[0] for r in res], ["The New York Times", "Reuters"])
        self.assertIn("gl=US", self.urls[0])
        self.assertIn("trump", self.urls[0])

    def test_proceso_completo(self):
        tmp = tempfile.mkdtemp()
        conn = db.connect(os.path.join(tmp, "i.db"))
        db.init(conn)
        now = time.time()
        for i, group in enumerate([TRUMP, LOCAL], start=1):
            conn.execute("""INSERT INTO clusters(id, created_at, updated_at, n_sources, n_articles, relevance,
                            first_published, last_published, status) VALUES (?,?,?,?,?,?,?,?, 'active')""",
                         (i, now, now, 3, 3, 10 - i, now - 3600, now - 600))
            for j, (src, t, s) in enumerate(group):
                f, e = article_features(t, s)
                conn.execute("""INSERT INTO articles(url, source, title, title_key, summary, published_at, fetched_at,
                                features, entities, cluster_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                             (f"https://x/{i}/{j}", src, t, f"{i}-{j}", s, now - 3600, now,
                              json.dumps(f), json.dumps(e), i))
        conn.commit()
        added = intl.process(conn, now, fetch=self.fake_fetch, countries=self.countries)
        self.assertEqual(added, 2)
        self.assertEqual(len(self.urls), 1, "la noticia nacional no debe buscar en prensa extranjera")
        # no se repite la búsqueda hasta que pase INTL_RECHECK_MIN
        self.assertEqual(intl.process(conn, now + 60, fetch=self.fake_fetch, countries=self.countries), 0)
        self.assertEqual(len(self.urls), 1)
        out = os.path.join(tmp, "data")
        export.export_static(conn, out)
        stories = {s["id"]: s for s in json.load(open(os.path.join(out, "stories.json")))["stories"]}
        self.assertEqual(stories[1]["intl"][0]["flag"], "🇺🇸")
        self.assertEqual(len(stories[1]["intl"][0]["articles"]), 2)
        self.assertEqual(stories[2]["intl"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
