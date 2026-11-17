import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import db  # noqa: E402
import telegram  # noqa: E402
import worker  # noqa: E402

NOW = 1_800_000_000


class FakeSender:
    def __init__(self):
        self.sent = []

    def __call__(self, text, reply_to=None):
        self.sent.append((text, reply_to))
        return 100 + len(self.sent)


class TestTelegram(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        db.init(self.conn)
        orig = telegram.time.sleep
        self.addCleanup(setattr, telegram.time, "sleep", orig)
        telegram.time.sleep = lambda s: None
        config.SITE_URL = "https://ejemplo.github.io/noticias/"

    def story(self, cid, n_sources, relevance, headline="Titular", written=NOW - 600):
        self.conn.execute(
            """INSERT INTO clusters(id, created_at, updated_at, n_sources, n_articles, relevance, status,
                   first_published, last_published, headline, lead, ai_written_at)
               VALUES (?,?,?,?,?,?, 'active', ?,?,?,?,?)""",
            (cid, NOW, NOW, n_sources, n_sources, relevance, NOW - 3600, NOW - 300, headline, "Entradilla", written))
        for i in range(n_sources):
            self.conn.execute(
                """INSERT INTO articles(url, source, title, title_key, published_at, fetched_at, features, entities, cluster_id)
                   VALUES (?,?,?,?,?,?, '{}', '[]', ?)""",
                (f"https://x/{cid}/{i}", f"Medio {i}", "t", f"{cid}-{i}", NOW - 3000 + i, NOW, cid))
        self.conn.commit()

    def test_activacion_publica_las_3_principales(self):
        for cid in range(1, 6):
            self.story(cid, 5, relevance=cid)
        self.story(9, 2, relevance=99)  # pocos medios: nunca
        f = FakeSender()
        worker.publish_telegram(self.conn, NOW, fresh_db=False, sender=f)
        self.assertEqual(len(f.sent), 3)
        self.assertIn("ejemplo.github.io/noticias/#/noticia/5", f.sent[0][0])
        # siguiente ciclo: nada nuevo
        worker.publish_telegram(self.conn, NOW + 900, fresh_db=False, sender=f)
        self.assertEqual(len(f.sent), 3)
        # una noticia cruza el umbral -> se publica
        self.story(10, 4, relevance=1, headline="Nueva <b>gorda</b>")
        worker.publish_telegram(self.conn, NOW + 1800, fresh_db=False, sender=f)
        self.assertEqual(len(f.sent), 4)
        self.assertIn("Nueva &lt;b&gt;gorda&lt;/b&gt;", f.sent[-1][0])
        self.assertIn("📰 4 medios: Medio 0, Medio 1, Medio 2, Medio 3", f.sent[-1][0])

    def test_actualizacion_responde_al_mensaje_original(self):
        self.story(1, 5, relevance=5)
        f = FakeSender()
        worker.publish_telegram(self.conn, NOW, fresh_db=False, sender=f)
        msg_id = 101
        # novedad sin nota -> no se envía
        self.conn.execute("INSERT INTO story_updates(cluster_id, at, note, n_sources) VALUES (1, ?, NULL, 6)", (NOW + 600,))
        self.conn.execute("INSERT INTO story_updates(cluster_id, at, note, n_sources) VALUES (1, ?, ?, 7)",
                          (NOW + 1200, "Dimite el consejero."))
        self.conn.commit()
        worker.publish_telegram(self.conn, NOW + 2400, fresh_db=False, sender=f)
        self.assertEqual(len(f.sent), 2)
        text, reply = f.sent[-1]
        self.assertEqual(reply, msg_id)
        self.assertIn("Dimite el consejero.", text)
        # sin novedades nuevas no se repite
        worker.publish_telegram(self.conn, NOW + 6000, fresh_db=False, sender=f)
        self.assertEqual(len(f.sent), 2)

    def test_base_de_datos_nueva_no_inunda_el_canal(self):
        for cid in range(1, 6):
            self.story(cid, 5, relevance=cid)
        f = FakeSender()
        worker.publish_telegram(self.conn, NOW, fresh_db=True, sender=f)
        worker.publish_telegram(self.conn, NOW + 900, fresh_db=False, sender=f)
        self.assertEqual(f.sent, [])

    def test_limite_de_telegram_no_rompe_el_ciclo(self):
        self.story(1, 5, relevance=5)

        def limited(text, reply_to=None):
            raise telegram.RateLimited("retry_after 30")
        self.assertEqual(worker.publish_telegram(self.conn, NOW, fresh_db=False, sender=limited), 0)
        f = FakeSender()
        worker.publish_telegram(self.conn, NOW + 900, fresh_db=False, sender=f)
        self.assertEqual(len(f.sent), 1)  # se publica en el siguiente intento


if __name__ == "__main__":
    unittest.main(verbosity=2)
