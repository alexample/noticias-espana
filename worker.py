"""Worker: lee los medios, agrupa artículos en noticias y pide la redacción a la IA.

Uso:
  python worker.py              # bucle infinito (cada NEWS_POLL_SECONDS)
  python worker.py --once       # un solo ciclo
  python worker.py --check-feeds  # comprueba qué feeds responden
"""
import argparse
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import config
import breaking
import db
import export
import feeds
import intl
import telegram
import writer
from clustering import Cluster, Corpus, Matcher, vectorize
from textproc import article_features, fold

log = logging.getLogger("worker")


def title_key(title):
    return re.sub(r"[^a-z0-9]+", " ", fold(title)).strip()[:200]


# ---------------------------------------------------------------- ingest

def fetch_all(conn, fetcher):
    sources = [dict(r) for r in conn.execute("SELECT * FROM sources WHERE enabled=1")]
    with ThreadPoolExecutor(max_workers=config.FETCH_THREADS) as ex:
        results = list(ex.map(fetcher, sources))
    now = time.time()
    for res in results:
        conn.execute(
            "UPDATE sources SET etag=?, last_modified=?, last_fetch=?, last_status=?, last_items=? WHERE name=?",
            (res["etag"], res["last_modified"], now, res["status"], len(res["items"]), res["name"]),
        )
        if res["status"].startswith("error"):
            log.warning("%s: %s", res["name"], res["status"])
    conn.commit()
    return results


def new_items(conn, results, now):
    cutoff = now - config.MAX_ARTICLE_AGE_H * 3600
    seen_urls, seen_keys, out = set(), set(), []
    for res in results:
        for it in res["items"]:
            pub = min(it["published"] or now, now)  # fechas futuras = ahora
            if pub < cutoff:
                continue
            key = (res["name"], title_key(it["title"]))
            if it["url"] in seen_urls or key in seen_keys:
                continue
            seen_urls.add(it["url"])
            seen_keys.add(key)
            out.append({**it, "source": res["name"], "published": pub, "title_key": key[1]})
    if not out:
        return []
    # descartar los que ya están en la base de datos
    known_urls, known_keys = set(), set()
    for chunk in range(0, len(out), 500):
        part = out[chunk:chunk + 500]
        q = ",".join("?" * len(part))
        known_urls |= {r[0] for r in conn.execute(f"SELECT url FROM articles WHERE url IN ({q})",
                                                  [p["url"] for p in part])}
        known_keys |= {(r[0], r[1]) for r in conn.execute(
            f"SELECT source, title_key FROM articles WHERE title_key IN ({q})", [p["title_key"] for p in part])}
    fresh = [p for p in out if p["url"] not in known_urls and (p["source"], p["title_key"]) not in known_keys]
    return sorted(fresh, key=lambda p: p["published"])


# ---------------------------------------------------------------- clustering

def load_state(conn, now, new_feats):
    """Reconstruye el corpus (IDF) y las noticias activas con sus vectores."""
    window = now - config.CLUSTER_ACTIVE_H * 3600
    corpus = Corpus()
    rows = conn.execute(
        """SELECT a.id, a.source, a.features, a.entities, a.published_at, a.cluster_id
           FROM articles a JOIN clusters c ON c.id = a.cluster_id
           WHERE c.status='active' AND a.published_at >= ?""", (window,)).fetchall()
    parsed = []
    for r in rows:
        f = json.loads(r["features"])
        corpus.add(f)
        parsed.append((r, f))
    for f in new_feats:
        corpus.add(f)
    matcher = Matcher(config.JOIN_THRESHOLD, config.MERGE_THRESHOLD, config.CLUSTER_ACTIVE_H)
    for r, f in parsed:
        cl = matcher.clusters.get(r["cluster_id"])
        if cl is None:
            cl = matcher.clusters[r["cluster_id"]] = Cluster(r["cluster_id"])
        cl.add(r["id"], vectorize(f, corpus), json.loads(r["entities"]), r["source"], r["published_at"])
    return corpus, matcher


def cluster_items(conn, items, now):
    feats = [article_features(it["title"], it["summary"]) for it in items]
    corpus, matcher = load_state(conn, now, [f for f, _ in feats])

    def new_cluster_id():
        cur = conn.execute("INSERT INTO clusters(created_at, updated_at) VALUES (?,?)", (now, now))
        return cur.lastrowid

    stats = {"new": 0, "joined": 0}
    for it, (f, ents) in zip(items, feats):
        cur = conn.execute(
            """INSERT INTO articles(url, source, title, title_key, summary, image, published_at,
                                    fetched_at, features, entities)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (it["url"], it["source"], it["title"], it["title_key"], it["summary"], it["image"],
             it["published"], now, json.dumps(f, ensure_ascii=False), json.dumps(ents, ensure_ascii=False)))
        art_id = cur.lastrowid
        cl, score, is_new = matcher.assign(art_id, vectorize(f, corpus), ents, it["source"],
                                           it["published"], new_cluster_id)
        conn.execute("UPDATE articles SET cluster_id=?, match_score=? WHERE id=?", (cl.id, round(score, 4), art_id))
        conn.execute("UPDATE clusters SET updated_at=? WHERE id=?", (now, cl.id))
        stats["new" if is_new else "joined"] += 1
        log.debug("%s %.2f [%s] %s", "NUEVA " if is_new else "AÑADE ", score, it["source"], it["title"])

    merges = matcher.merge_pass()
    for src, dst in merges:
        conn.execute("UPDATE articles SET cluster_id=? WHERE cluster_id=?", (dst, src))
        conn.execute("UPDATE OR IGNORE intl_articles SET cluster_id=? WHERE cluster_id=?", (dst, src))
        conn.execute("DELETE FROM intl_articles WHERE cluster_id=?", (src,))
        conn.execute("UPDATE story_updates SET cluster_id=? WHERE cluster_id=?", (dst, src))
        conn.execute("UPDATE OR IGNORE telegram_posts SET cluster_id=? WHERE cluster_id=?", (dst, src))
        conn.execute("DELETE FROM telegram_posts WHERE cluster_id=?", (src,))
        conn.execute("UPDATE clusters SET status='merged', merged_into=? WHERE id=?", (dst, src))
        conn.execute("UPDATE clusters SET updated_at=? WHERE id=?", (now, dst))
    stats["merged"] = len(merges)

    for cl in matcher.clusters.values():
        if cl.touched and cl.merged_into is None:
            conn.execute("UPDATE clusters SET rep_article_id=? WHERE id=?", (cl.representative(), cl.id))
    conn.commit()
    return stats


# ---------------------------------------------------------------- stats y relevancia

def refresh_clusters(conn, now):
    conn.execute("UPDATE clusters SET status='closed' WHERE status='active' AND last_published < ?",
                 (now - config.CLUSTER_ACTIVE_H * 3600,))
    weights = {r["name"]: r["weight"] for r in conn.execute("SELECT name, weight FROM sources")}
    recent = now - 6 * 3600
    rows = conn.execute(
        """SELECT cluster_id, source, published_at, image, id FROM articles
           WHERE cluster_id IN (SELECT id FROM clusters WHERE status='active')""").fetchall()
    data = {}
    for r in rows:
        d = data.setdefault(r["cluster_id"], {"n": 0, "src": set(), "recent_src": set(), "first": r["published_at"],
                                              "last": r["published_at"], "img": {}})
        d["n"] += 1
        d["src"].add(r["source"])
        if r["published_at"] >= recent:
            d["recent_src"].add(r["source"])
        d["first"] = min(d["first"], r["published_at"])
        d["last"] = max(d["last"], r["published_at"])
        if r["image"]:
            d["img"][r["id"]] = r["image"]
    for cid, d in data.items():
        rep = conn.execute("SELECT rep_article_id FROM clusters WHERE id=?", (cid,)).fetchone()[0]
        image = d["img"].get(rep) or next(iter(d["img"].values()), None)
        age_h = max(0.0, (now - d["last"]) / 3600)
        w = sum(weights.get(s, 1.0) for s in d["src"])
        rel = (w + 0.3 * len(d["recent_src"])) * 0.5 ** (age_h / config.RELEVANCE_HALF_LIFE_H)
        conn.execute(
            """UPDATE clusters SET n_articles=?, n_sources=?, first_published=?, last_published=?,
                   relevance=?, image=? WHERE id=?""",
            (d["n"], len(d["src"]), d["first"], d["last"], round(rel, 4), image, cid))
    conn.commit()


# ---------------------------------------------------------------- redacción IA

def write_pending(conn, now):
    if not writer.ai_enabled():
        return 0
    pending = conn.execute(
        """SELECT id, n_sources, headline, lead, ai_written_at FROM clusters
           WHERE status='active' AND n_sources >= ?
             AND (ai_sources_count IS NULL OR n_sources > ai_sources_count)
             AND (ai_written_at IS NULL OR ai_written_at < ?)
           ORDER BY (breaking_at IS NOT NULL AND ai_written_at IS NULL) DESC,  -- última hora sin redactar primero
                    relevance DESC LIMIT ?""",
        (config.AI_MIN_SOURCES, now - config.AI_MIN_INTERVAL_MIN * 60, config.AI_MAX_PER_CYCLE)).fetchall()
    done = 0
    for row in pending:
        arts = [dict(a) for a in conn.execute(
            "SELECT source, title, summary, published_at FROM articles WHERE cluster_id=?", (row["id"],))]
        try:
            foreign = [dict(a) for a in conn.execute(
                "SELECT country, source, title, published_at FROM intl_articles WHERE cluster_id=? "
                "ORDER BY published_at DESC LIMIT 8", (row["id"],))]
            previous = {"headline": row["headline"], "lead": row["lead"], "at": row["ai_written_at"]}
            story = writer.write_story(arts, foreign, previous if row["headline"] else None)
            written_at = time.time()
            conn.execute(
                "INSERT INTO story_updates(cluster_id, at, headline, lead, note, n_sources) VALUES (?,?,?,?,?,?)",
                (row["id"], written_at, story["headline"], story["lead"], story.get("note"), row["n_sources"]))
            conn.execute(
                """UPDATE clusters SET headline=?, lead=?, body=?, ai_written_at=?, ai_sources_count=?,
                       ai_error=NULL, tag=COALESCE(?, tag) WHERE id=?""",
                (story["headline"], story["lead"], story["body"], written_at, row["n_sources"],
                 story.get("tag"), row["id"]))
            done += 1
            log.info("Redactada noticia %s (%d medios)%s", row["id"], row["n_sources"],
                     f" · novedad: {story['note']}" if story.get("note") else "")
        except Exception as e:
            log.warning("IA falló en noticia %s: %s", row["id"], e)
            conn.execute("UPDATE clusters SET ai_error=? WHERE id=?", (str(e)[:300], row["id"]))
        conn.commit()
    return done


# ---------------------------------------------------------------- telegram

def publish_telegram(conn, now, fresh_db=False, sender=None, written_before=None):
    """written_before: solo noticias redactadas antes de ese momento (cuya página para
    compartir ya está en la web). En GitHub Actions no hace falta: Telegram se publica en
    un paso aparte, justo después de desplegar la web (python worker.py --telegram)."""
    if fresh_db:
        telegram.mark_existing(conn, now, keep=0)   # caché perdida: no repetir lo ya publicado
        return 0
    if not (telegram.enabled() or sender):
        return 0
    if conn.execute("SELECT COUNT(*) FROM telegram_posts").fetchone()[0] == 0:
        telegram.mark_existing(conn, now, keep=3)   # canal recién activado: empieza con las 3 principales
    try:
        new, upd = telegram.process(conn, now, sender=sender, written_before=written_before)
    except Exception:
        log.exception("Telegram falló")
        return 0
    return new + upd


# ---------------------------------------------------------------- ciclo

def run_cycle(conn, fetcher=feeds.fetch_source, now=None, telegram_inline=True):
    t0 = time.time()
    now = now or time.time()
    fresh_db = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
    results = fetch_all(conn, fetcher)
    items = new_items(conn, results, now)
    stats = cluster_items(conn, items, now) if items else {"new": 0, "joined": 0, "merged": 0}
    refresh_clusters(conn, now)
    stats["breaking"] = breaking.detect(conn, now)
    try:
        stats["intl"] = intl.process(conn, now)
    except Exception:
        log.exception("Cobertura internacional falló")
        stats["intl"] = 0
    stats["ai_written"] = write_pending(conn, now)
    export.prune(conn, config.PRUNE_DAYS)
    stats["exported"] = export.export_static(conn)
    if telegram_inline:
        stats["telegram"] = publish_telegram(conn, now, fresh_db, written_before=now)
    else:  # se publicará en otro paso tras desplegar la web; aquí solo se protege una BD nueva
        stats["telegram"] = publish_telegram(conn, now, fresh_db) if fresh_db else 0
    stats["feeds_ok"] = sum(1 for r in results if not r["status"].startswith("error"))
    stats["feeds"] = len(results)
    stats["seconds"] = round(time.time() - t0, 1)
    log.info("Ciclo: %d artículos nuevos -> %d noticias nuevas, %d añadidos a existentes, %d fusiones, "
             "%d redactadas, %d de última hora, %d artículos internacionales, %d mensajes a Telegram · feeds %d/%d · %.1fs", len(items), stats["new"],
             stats["joined"], stats["merged"], stats["ai_written"], stats["breaking"], stats["intl"], stats["telegram"], stats["feeds_ok"], stats["feeds"], stats["seconds"])
    return stats


def check_feeds(conn):
    for src in conn.execute("SELECT * FROM sources WHERE enabled=1"):
        res = feeds.fetch_source({**dict(src), "etag": None, "last_modified": None})
        print(f"{res['name']:<20} {res['status'][:70]:<70} {len(res['items'])} artículos")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--check-feeds", action="store_true")
    ap.add_argument("--no-telegram", action="store_true", help="no publicar en Telegram en este ciclo")
    ap.add_argument("--telegram", action="store_true", help="solo publicar en Telegram (tras desplegar la web)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = db.connect()
    db.init(conn)
    db.sync_sources(conn)
    if args.check_feeds:
        return check_feeds(conn)
    if args.telegram:
        n = publish_telegram(conn, time.time())
        log.info("Telegram: %d mensajes", n)
        return
    if not writer.ai_enabled():
        log.warning("ANTHROPIC_API_KEY no definida: las noticias se mostrarán con el titular original.")
    while True:
        try:
            run_cycle(conn, telegram_inline=not args.no_telegram)
        except Exception:
            log.exception("Error en el ciclo")
        if args.once:
            break
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
