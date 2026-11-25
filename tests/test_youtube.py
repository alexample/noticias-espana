"""Comentarios de YouTube con la API simulada: canales vigilados -> vídeos -> noticia -> comentarios."""
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
ISO = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))  # noqa: E731
ARTS = [
    ("El País", "La Aemet activa la alerta roja por lluvias torrenciales en Valencia", "La DANA deja lluvias de 180 litros."),
    ("El Mundo", "Alerta roja en Valencia por la DANA: la Generalitat pide no salir", "Lluvias torrenciales."),
    ("RTVE", "La DANA obliga a suspender las clases en Valencia", "Aviso rojo de la Aemet por lluvias."),
    ("ABC", "Valencia, en alerta roja por la DANA y las lluvias torrenciales", "Hasta 180 litros."),
]
OTHER = [("El País", "El Gobierno aprueba el techo de gasto para 2027", "Hacienda eleva el límite de gasto."),
         ("El Mundo", "Montero presenta el techo de gasto", "El Consejo de Ministros aprueba el límite de gasto.")]


class FakeYouTube:
    def __init__(self, video_age=2 * 3600):
        self.calls = []
        self.video_age = video_age

    def __call__(self, endpoint, params):
        self.calls.append((endpoint, params))
        if endpoint == "search":          # localizar canales
            name = params["q"]
            return {"items": [{"id": {"channelId": "UC" + str(abs(hash(name)))[:10]},
                               "snippet": {"channelTitle": name, "title": name}}]}
        if endpoint == "playlistItems":
            if params["playlistId"] != "UU" + str(abs(hash("RTVE Noticias")))[:10]:
                return {"items": []}
            pub = ISO(NOW - self.video_age)
            return {"items": [
                {"snippet": {"resourceId": {"videoId": "dana1"}, "publishedAt": pub,
                             "title": "Alerta roja en Valencia por la DANA: lluvias torrenciales de hasta 180 litros",
                             "description": "La Aemet activa el aviso rojo en Valencia."}},
                {"snippet": {"resourceId": {"videoId": "otro"}, "publishedAt": pub,
                             "title": "Receta de croquetas de la abuela", "description": "Cocina fácil."}},
            ]}
        if endpoint == "commentThreads":
            return {"items": [{"id": f"c{i}", "snippet": {"topLevelComment": {"snippet": {
                "textDisplay": f"Comentario {i} sobre la gestión de la DANA", "likeCount": i,
                "publishedAt": ISO(NOW - 600)}}}} for i in range(20)]}
        raise AssertionError(endpoint)


class TestYouTube(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(os.path.join(tempfile.mkdtemp(), "y.db"))
        db.init(self.conn)
        config.YT_SEARCHES_PER_DAY = 90
        for cid, arts, n in ((1, ARTS, 4), (2, OTHER, 2)):
            self.conn.execute("""INSERT INTO clusters(id, created_at, updated_at, n_sources, n_articles, relevance, status,
                                 first_published, last_published, headline, tag, ai_written_at)
                                 VALUES (?,?,?,?,?,?,'active',?,?,?,?,?)""",
                              (cid, NOW, NOW, n, n, 10 - cid, NOW - 7200, NOW - 600, arts[0][1], "", NOW - 300))
            for i, (src, t, s) in enumerate(arts):
                f, e = article_features(t, s)
                self.conn.execute("""INSERT INTO articles(url, source, title, title_key, summary, published_at, fetched_at,
                                     features, entities, cluster_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                  (f"https://x/{cid}/{i}", src, t, f"k{cid}{i}", s, NOW - 3600, NOW,
                                   json.dumps(f), json.dumps(e), cid))
        self.conn.commit()

    def test_canales(self):
        self.assertTrue(youtube.is_media_channel("RTVE Noticias"))
        self.assertTrue(youtube.is_media_channel("EL PAÍS"))
        self.assertFalse(youtube.is_media_channel("Copenhagen Tours"))

    def test_vigila_canales_asigna_lee_y_resume(self):
        yt = FakeYouTube()
        stats = youtube.process(self.conn, NOW, get=yt)
        self.assertEqual([c[0] for c in yt.calls].count("search"), len(youtube.WATCH_CHANNELS))  # se localizan una vez
        self.assertEqual(stats["videos"], 1)                               # solo el de la DANA encaja
        self.assertEqual(self.conn.execute("SELECT cluster_id FROM yt_videos").fetchone()[0], 1)
        self.assertEqual(stats["comments"], 20)
        # 10 min después: ni se vuelven a mirar los canales ni se releen comentarios
        yt2 = FakeYouTube()
        youtube.process(self.conn, NOW + 600, get=yt2)
        self.assertEqual([c[0] for c in yt2.calls if c[0] != "search"], [])
        # a las 3 h se releen los comentarios
        yt3 = FakeYouTube()
        youtube.process(self.conn, NOW + 3 * 3600 + 60, get=yt3)
        self.assertIn("commentThreads", [c[0] for c in yt3.calls])

        config.ANTHROPIC_API_KEY = "test"
        seen = {}

        def fake(prompt, system, max_tokens=2000):
            seen["prompt"] = prompt
            return '{"resumen": "La mayoría critica la gestión de la emergencia; otros piden prudencia."}'
        orig = writer.call_claude
        writer.call_claude = fake
        self.addCleanup(setattr, writer, "call_claude", orig)
        self.assertEqual(youtube.summarize_pending(self.conn, NOW), 1)
        self.assertIn("Comentario 19", seen["prompt"].split("\n")[3])   # los más valorados primero
        self.assertEqual(youtube.summarize_pending(self.conn, NOW + 7 * 3600), 0)  # sin 20 nuevos, no
        out = os.path.join(tempfile.mkdtemp(), "data")
        export.export_static(self.conn, out)
        story = {s["id"]: s for s in json.load(open(os.path.join(out, "stories.json")))["stories"]}[1]
        self.assertEqual(story["readers"]["count"], 20)
        self.assertEqual(story["readers"]["videos"][0]["url"], "https://www.youtube.com/watch?v=dana1")

    def test_espera_una_hora_y_solo_noticias_nuevas(self):
        stats = youtube.process(self.conn, NOW, get=FakeYouTube(video_age=1200))
        self.assertEqual((stats["videos"], stats["comments"]), (1, 0))      # vídeo de hace 20 min
        self.conn.execute("DELETE FROM kv WHERE k='yt_polled'")
        stats = youtube.process(self.conn, NOW + 3600, get=FakeYouTube(video_age=1200))
        self.assertEqual(stats["comments"], 20)
        # noticia antigua: sus vídeos no se asignan
        self.conn.execute("DELETE FROM yt_videos")
        self.conn.execute("DELETE FROM yt_pool")
        self.conn.execute("DELETE FROM kv WHERE k='yt_polled'")
        self.conn.execute("UPDATE clusters SET first_published=?", (NOW - 30 * 3600,))
        stats = youtube.process(self.conn, NOW, get=FakeYouTube())
        self.assertEqual(stats["videos"], 0)

    def test_video_anterior_a_que_la_noticia_sea_relevante(self):
        # la noticia aún tiene 1 medio: el vídeo no se asigna…
        self.conn.execute("UPDATE clusters SET n_sources=1 WHERE id=1")
        stats = youtube.process(self.conn, NOW, get=FakeYouTube())
        self.assertEqual(stats["videos"], 0)
        # …pero cuando llega a 2 medios, el mismo vídeo se asigna sin volver a pedirlo a YouTube
        self.conn.execute("UPDATE clusters SET n_sources=2 WHERE id=1")
        yt = FakeYouTube()
        stats = youtube.process(self.conn, NOW + 600, get=yt)
        self.assertEqual(stats["videos"], 1)
        self.assertNotIn("playlistItems", [c[0] for c in yt.calls])

    def test_comentarios_desactivados(self):
        def disabled(endpoint, params):
            if endpoint == "commentThreads":
                raise youtube.YouTubeError(403, "commentsDisabled")
            return FakeYouTube()(endpoint, params)
        youtube.process(self.conn, NOW, get=disabled)
        self.assertEqual(self.conn.execute("SELECT disabled FROM yt_videos").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
