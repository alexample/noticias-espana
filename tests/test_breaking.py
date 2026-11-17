import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import breaking  # noqa: E402
import db  # noqa: E402
import telegram  # noqa: E402
import worker  # noqa: E402
from tests.test_telegram import FakeSender  # noqa: E402


class TestBreaking(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(os.path.join(tempfile.mkdtemp(), "b.db"))
        db.init(self.conn)
        self.now = time.time()
        orig = telegram.time.sleep
        self.addCleanup(setattr, telegram.time, "sleep", orig)
        telegram.time.sleep = lambda s: None

    def cluster(self, cid, arts, headline=None):
        """arts: [(medio, titular, minutos_atrás)]"""
        pubs = [self.now - m * 60 for _, _, m in arts]
        self.conn.execute(
            """INSERT INTO clusters(id, created_at, updated_at, n_sources, n_articles, relevance, status,
                   first_published, last_published, headline, lead, ai_written_at)
               VALUES (?,?,?,?,?,?, 'active', ?,?,?,?,?)""",
            (cid, self.now, self.now, len({a[0] for a in arts}), len(arts), 1.0, min(pubs), max(pubs),
             headline, "Entradilla" if headline else None, self.now - 60 if headline else None))
        for i, (src, title, m) in enumerate(arts):
            cur = self.conn.execute(
                """INSERT INTO articles(url, source, title, title_key, published_at, fetched_at, features, entities, cluster_id)
                   VALUES (?,?,?,?,?,?, '{}', '[]', ?)""",
                (f"https://x/{cid}/{i}", src, title, f"{cid}-{i}", self.now - m * 60, self.now, cid))
            self.conn.execute("UPDATE clusters SET rep_article_id=COALESCE(rep_article_id, ?) WHERE id=?", (cur.lastrowid, cid))
        self.conn.commit()

    def flag(self, cid):
        return self.conn.execute("SELECT breaking_at FROM clusters WHERE id=?", (cid,)).fetchone()[0] is not None

    def test_reglas(self):
        self.cluster(1, [("El País", "Última hora: dimite la ministra de Sanidad", 10)])
        self.cluster(2, [("RTVE", "Última hora de la guerra en Ucrania, en directo", 10)])
        self.cluster(3, [("ABC", "Terremoto en Granada", 40), ("El Mundo", "Fuerte terremoto en Granada", 30),
                         ("RTVE", "Sacudida sísmica en Granada", 20)])
        self.cluster(4, [("ABC", "Presupuestos", 300), ("El Mundo", "Presupuestos 2027", 200),
                         ("RTVE", "Las cuentas", 100)])
        self.cluster(5, [("ABC", "Urgente: muere el actor X", 300)])  # etiqueta, pero ya no es reciente
        self.assertEqual(breaking.detect(self.conn, self.now), 2)
        self.assertEqual([self.flag(i) for i in range(1, 6)], [True, False, True, False, False])

    def test_telegram_publica_con_un_medio_y_confirma_despues(self):
        self.cluster(1, [("El País", "ÚLTIMA HORA | Dimite la ministra de Sanidad", 5)])
        self.cluster(2, [("ABC", "Una noticia normal de un solo medio", 5)])
        breaking.detect(self.conn, self.now)
        f = FakeSender()
        self.conn.execute("INSERT INTO telegram_posts VALUES (99, 1, 0, 0, 1)")  # canal ya activo
        self.conn.commit()
        worker.publish_telegram(self.conn, self.now, sender=f)
        self.assertEqual(len(f.sent), 1)
        text = f.sent[0][0]
        self.assertIn("✓  ·  <i>Última hora</i>", text)
        self.assertIn("<b>Dimite la ministra de Sanidad</b>", text)
        self.assertIn("Según El País.", text)
        self.assertIn("Pendiente de confirmar", text)
        # llega otro medio y la IA la redacta -> respuesta de confirmación con ✓✓
        self.conn.execute("""INSERT INTO articles(url, source, title, title_key, published_at, fetched_at, features, entities, cluster_id)
                             VALUES ('https://x/1/9','RTVE','Dimite la ministra','1-9',?,?,'{}','[]',1)""", (self.now, self.now))
        self.conn.execute("UPDATE clusters SET n_sources=2, headline='La ministra de Sanidad dimite', lead='L', ai_written_at=? WHERE id=1",
                          (self.now + 100,))
        self.conn.commit()
        worker.publish_telegram(self.conn, self.now + 200, sender=f)
        self.assertEqual(len(f.sent), 2)
        text, reply = f.sent[1]
        self.assertEqual(reply, 101)
        self.assertIn("✓✓  ·  <i>Confirmada</i>", text)
        self.assertIn("Confirmada por 2 medios: El País, RTVE", text)
        worker.publish_telegram(self.conn, self.now + 300, sender=f)
        self.assertEqual(len(f.sent), 2)  # no se repite

    def test_bd_nueva_no_publica_ultimas_horas_antiguas(self):
        self.cluster(1, [("El País", "Última hora: dimite la ministra", 5)])
        breaking.detect(self.conn, self.now)
        f = FakeSender()
        worker.publish_telegram(self.conn, self.now, fresh_db=True, sender=f)
        worker.publish_telegram(self.conn, self.now + 900, sender=f)
        self.assertEqual(f.sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
