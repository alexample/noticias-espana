"""Arranca web + worker en un solo proceso: python run.py"""
import logging
import threading
import time

import config
import db
import server
import worker


def worker_loop():
    conn = db.connect()
    db.init(conn)
    db.sync_sources(conn)
    while True:
        try:
            worker.run_cycle(conn)
        except Exception:
            logging.getLogger("worker").exception("Error en el ciclo")
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = db.connect()
    db.init(conn)
    conn.close()
    threading.Thread(target=worker_loop, daemon=True).start()
    server.serve()
