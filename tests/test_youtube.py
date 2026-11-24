"""Comentarios de YouTube con la API simulada."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import db  # noqa: E402
import export  # noqa: E402
import writer  # noqa: E402
import youtube  # noqa: E402
from textproc import article_features  # noqa: E402

NOW = time.time()
ARTS = [
    ("El País", "La Aemet activa la alerta roja por lluvias en Valencia", "La DANA deja lluvias torrenciales."),
    ("El Mundo", "Alerta roja en Valencia por la DANA", "La Generalitat pide no salir."),
    ("RTVE", "La DANA obliga a suspender las clases en Valencia", "Aviso rojo de la Aemet."),
    ("ABC", "Valencia, en alerta roja por la DANA", "Lluvias de hasta 180 litros."),
]


class FakeYouTube:
    def __init__(self):
        self.calls = []

    def __call__(self, endpoint, params):
        self.calls.append((endpoint, params))
        if endpoint == "search":
            return {"items": [
                {"id": {"videoId": "v1"}, "snippet": {"channelTitle": "RTVE Noticias", "publishedAt": "2026-11-24T10:00:00Z",
                 "title": "DANA en Valencia: alerta roja", "description": ""}},
                {"id": {"videoId": "v2"}, "snippet": {"channelTitle": "Un youtuber cualquiera", "publishedAt": "2026-11-24T10:00:00Z",
                 "title": "DANA Valencia EN DIRECTO", "description": ""}},           # no es un medio
                {"id": {"videoId": "v3"}, "snippet": {"channelTitle": "laSexta", "publishedAt": "2026-11-24T10:00:00Z",
                 "title": "El tiempo del fin de semana", "description": ""}},       # no habla de la noticia
            ]}
        if endpoint == "commentThreads":
            return {"items": [{"id": f"c{i}", "snippet": {"topLevelComment": {"snippet": {
                "textDisplay": f"Comentario {i} sobre la gestión de la DANA", "likeCount": i, "publishedAt": "2026-11-24T11:00:00Z"}}}}
                for i in range(20)]}
        raise AssertionError(endpoint)


class TestYouTube(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(os.path.join(tempfile.mkdtemp(), "y.db"))
        db.init(self.conn)
        self.conn.execute("""INSERT INTO clusters(id, created_at, updated_at, n_sources, n_articles, relevance, status,
                             first_published, last_published, headline, tag, ai_written_at)
                             VALUES (1,?,?,4,4,9,'active',?,?, 'Alerta roja en Valencia por la DANA', 'DANA Valencia', ?)""",
                          (NOW, NOW, NOW - 7200, NOW - 600, NOW - 300))
        for i, (src, t, s) in enumerate(ARTS):
            f, e = article_features(t, s)
            self.conn.execute("""INSERT INTO articles(url, source, title, title_key, summary, published_at, fetched_at,
                                 features, entities, cluster_id) VALUES (?,?,?,?,?,?,?,?,?,1)""",
                              (f"https://x/{i}", src, t, f"k{i}", s, NOW - 3600, NOW, json.dumps(f), json.dumps(e)))
        self.conn.commit()
        config.YT_SEARCHES_PER_DAY = 90

    def test_canales(self):
        self.assertTrue(youtube.is_media_channel("RTVE Noticias"))
        self.assertTrue(youtube.is_media_channel("EL PAÍS"))
        self.assertTrue(youtube.is_media_channel("laSexta"))
        self.assertFalse(youtube.is_media_channel("Copenhagen Tours"))
        self.assertFalse(youtube.is_media_channel("Un youtuber cualquiera"))

    def test_busca_lee_y_resume(self):
        yt = FakeYouTube()
        stats = youtube.process(self.conn, NOW, get=yt, countries={})
        self.assertEqual(stats, {"searched": 1, "videos": 1, "comments": 20})
        self.assertEqual(yt.calls[0][1]["q"], "DANA Valencia")
        self.assertEqual(youtube.searches_left(self.conn), 89)
        # no se repite la búsqueda ni se releen comentarios antes de tiempo
        yt2 = FakeYouTube()
        youtube.process(self.conn, NOW + 60, get=yt2, countries={})
        self.assertEqual(yt2.calls, [])
        # resumen de lectores con IA simulada
        config.ANTHROPIC_API_KEY = "test"
        seen = {}

        def fake(prompt, system, max_tokens=2000):
            seen["prompt"] = prompt
            return '{"resumen": "La mayoría critica la gestión de la emergencia; otros piden prudencia."}'
        orig = writer.call_claude
        writer.call_claude = fake
        self.addCleanup(setattr, writer, "call_claude", orig)
        self.assertEqual(youtube.summarize_pending(self.conn, NOW), 1)
        self.assertIn("Comentario 19", seen["prompt"].split("\n")[3])  # los más valorados primero
        self.assertEqual(youtube.summarize_pending(self.conn, NOW + 60), 0)  # sin comentarios nuevos
        out = os.path.join(tempfile.mkdtemp(), "data")
        export.export_static(self.conn, out)
        story = json.load(open(os.path.join(out, "stories.json")))["stories"][0]
        self.assertEqual(story["readers"]["count"], 20)
        self.assertIn("La mayoría", story["readers"]["summary"])
        self.assertEqual(story["readers"]["videos"][0]["url"], "https://www.youtube.com/watch?v=v1")

    def test_comentarios_desactivados_y_cupo(self):
        def disabled(endpoint, params):
            if endpoint == "search":
                return FakeYouTube()(endpoint, params)
            raise youtube.YouTubeError(403, "commentsDisabled")
        youtube.process(self.conn, NOW, get=disabled, countries={})
        self.assertEqual(self.conn.execute("SELECT disabled FROM yt_videos").fetchone()[0], 1)
        # cupo agotado: no se busca nada más hoy
        self.conn.execute("UPDATE clusters SET yt_checked_at=NULL")
        self.conn.execute("DELETE FROM yt_videos")
        config.YT_SEARCHES_PER_DAY = 1
        yt = FakeYouTube()
        youtube.process(self.conn, NOW + 3600, get=yt, countries={})
        self.assertEqual([c for c in yt.calls if c[0] == "search"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
