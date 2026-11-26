"""Comentarios de Menéame para «Qué dicen los lectores». Sin IA ni clave.

  1. Cada pasada se leen los RSS de portada y de pendientes de Menéame.
  2. Cada envío enlaza al artículo original del medio: si ese enlace es uno de nuestros
     artículos, el envío pertenece a esa noticia (coincidencia exacta). Si no, se prueba
     con el título, con el mismo algoritmo que agrupa los artículos.
  3. Los comentarios se leen de su RSS (texto y votos; el autor se descarta) con el mismo
     ritmo que los de YouTube y se guardan junto a ellos, así el resumen los mezcla.
"""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import config
import feeds
from textproc import strip_html

log = logging.getLogger("meneame")

FEEDS = ["https://www.meneame.net/rss", "https://www.meneame.net/rss?status=queued"]
COMMENTS = "https://www.meneame.net/comments_rss?id={id}"
MATCH_TITLE_THRESHOLD = 0.30   # sin enlace coincidente, el título debe parecerse bastante


def _fetch_text(url, fetch):
    status, body, _, _ = fetch(url)
    if not body:
        raise RuntimeError(f"Menéame respondió {status}")
    return body


def _items(raw):
    root = ET.fromstring(feeds._clean_xml(raw))
    for it in root.iter():
        if feeds._local(it.tag) != "item":
            continue
        d = {}
        for c in it:
            name, text = feeds._local(c.tag), (c.text or "").strip()
            if name == "comments":   # hay dos: <comments> (enlace) y <meneame:comments> (número)
                if text.isdigit():
                    d["comments"] = text
                continue
            d[name] = text
        d["_desc_raw"] = "".join(next((c.itertext() for c in it if feeds._local(c.tag) == "description"), []))
        yield d


def _source_url(d):
    """Enlace al artículo original de un envío."""
    url = d.get("url", "")
    if url and "meneame.net" not in url:
        return url
    m = re.search(r'href="(https?://(?![^"]*meneame\.net)[^"]+)"', d.get("_desc_raw", ""))
    return m.group(1) if m else ""


def clean_comment(desc_html):
    """Texto del comentario sin la firma del autor, enlaces ni referencias a otros comentarios."""
    html = re.split(r"&#187;|»", desc_html)[0]          # «» autor: X» va al final
    text = strip_html(html)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"#\d+\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def poll(conn, now, fetch=feeds.fetch):
    """Lee portada y pendientes y guarda los envíos recientes. Devuelve cuántos son nuevos."""
    new = 0
    for url in FEEDS:
        try:
            raw = _fetch_text(url, fetch)
        except Exception as e:
            log.warning("Menéame: no se pudo leer %s (%s)", url, e)
            continue
        for d in _items(raw):
            try:
                link_id = int(d.get("link_id") or 0)
            except ValueError:
                continue
            pub = feeds.parse_date(d.get("pubdate")) or now
            if not link_id or now - pub > 24 * 3600:
                continue
            comments = int(d.get("comments") or 0)
            known = conn.execute("SELECT 1 FROM mnm_links WHERE link_id=?", (link_id,)).fetchone()
            src = _source_url(d)
            conn.execute(
                """INSERT INTO mnm_links(link_id, title, url, story_url, comments, published_at, seen_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(link_id) DO UPDATE SET comments=excluded.comments""",
                (link_id, strip_html(d.get("title", "")), feeds.normalize_url(src) if src else "",
                 d.get("link", ""), comments, pub, now))
            new += 0 if known else 1
    conn.execute("DELETE FROM mnm_links WHERE seen_at < ? AND (cluster_id IS NULL OR cluster_id < 0)",
                 (now - 48 * 3600,))
    conn.commit()
    return new


def match(conn, now):
    """Asigna los envíos sin noticia: primero por enlace exacto, si no por título."""
    pending = conn.execute(
        "SELECT * FROM mnm_links WHERE (cluster_id IS NULL OR cluster_id = -1) AND seen_at >= ?",
        (now - 12 * 3600,)).fetchall()
    if not pending:
        return 0
    eligible = {r[0]: r[1] for r in conn.execute(
        """SELECT id, first_published FROM clusters WHERE status='active'
           AND (n_sources >= ? OR breaking_at IS NOT NULL) AND first_published >= ?""",
        (config.YT_MIN_SOURCES, now - config.YT_NEW_HOURS * 3600))}
    by_url = {}
    for url, cid in conn.execute(
            "SELECT url, cluster_id FROM articles WHERE published_at >= ? AND cluster_id IS NOT NULL",
            (now - 72 * 3600,)):
        by_url[url] = cid

    matcher = corpus = None
    matched = 0
    for p in pending:
        cid, how, score = by_url.get(p["url"]), "enlace", 1.0
        if cid is None and p["title"]:
            if matcher is None:   # solo se monta si hace falta
                from clustering import vectorize
                from textproc import article_features
                from worker import load_state
                corpus, matcher = load_state(conn, now, [])
            f, ents = article_features(p["title"], "")
            vec = vectorize(f, corpus)
            best, score = None, 0.0
            for ecid in eligible:
                cl = matcher.clusters.get(ecid)
                if cl is not None:
                    sc = matcher.score(vec, ents, p["published_at"], cl)
                    if sc > score:
                        best, score = cl, sc
            if best is not None and score >= MATCH_TITLE_THRESHOLD:
                cid, how = best.id, "título"
        if cid is None or cid not in eligible:
            conn.execute("UPDATE mnm_links SET cluster_id=-1 WHERE link_id=?", (p["link_id"],))
            continue
        conn.execute("UPDATE mnm_links SET cluster_id=? WHERE link_id=?", (cid, p["link_id"]))
        conn.execute(
            """INSERT OR IGNORE INTO yt_videos(video_id, cluster_id, channel, title, published_at, found_at, platform, url)
               VALUES (?,?,?,?,?,?, 'meneame', ?)""",
            (f"mnm:{p['link_id']}", cid, "Menéame", p["title"], p["published_at"], now, p["story_url"]))
        log.info("Menéame: «%s» -> noticia %s (%s, %.2f)", (p["title"] or "")[:70], cid, how, score)
        matched += 1
    conn.commit()
    return matched


def fetch_comments(link_id, fetch=feeds.fetch):
    raw = _fetch_text(COMMENTS.format(id=link_id), fetch)
    out = []
    for d in _items(raw):
        text = clean_comment(d.get("_desc_raw", ""))
        if len(text) < 3 or not d.get("comment_id"):
            continue
        try:
            votes = int(d.get("votes") or 0) + max(0, int(d.get("karma") or 0)) // 10
        except ValueError:
            votes = 0
        out.append({"id": "mnm:" + d["comment_id"], "text": text[:600], "likes": votes,
                    "published_at": feeds.parse_date(d.get("pubdate"))})
    return out


def read_comments(conn, now, fetch=feeds.fetch):
    """Lee los comentarios de los envíos asignados, al mismo ritmo que los de YouTube."""
    rows = conn.execute(
        """SELECT v.video_id, v.cluster_id FROM yt_videos v JOIN clusters c ON c.id = v.cluster_id
           WHERE v.platform='meneame' AND c.status='active' AND v.disabled=0 AND v.found_at >= ?
             AND (v.checked_at IS NULL OR v.checked_at < ?)
           ORDER BY c.relevance DESC LIMIT 15""",
        (now - config.YT_FOLLOW_HOURS * 3600, now - config.YT_RECHECK_MIN * 60)).fetchall()
    total = 0
    for v in rows:
        link_id = v["video_id"].split(":", 1)[1]
        try:
            comments = fetch_comments(link_id, fetch)
        except Exception as e:
            log.warning("Menéame: comentarios de %s fallidos (%s)", link_id, e)
            break
        for c in comments:
            conn.execute(
                """INSERT INTO yt_comments(comment_id, video_id, cluster_id, text, likes, published_at)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(comment_id) DO UPDATE SET likes=excluded.likes""",
                (c["id"], v["video_id"], v["cluster_id"], c["text"], c["likes"], c["published_at"]))
        n = conn.execute("SELECT COUNT(*) FROM yt_comments WHERE video_id=?", (v["video_id"],)).fetchone()[0]
        conn.execute("UPDATE yt_videos SET checked_at=?, comment_count=? WHERE video_id=?", (now, n, v["video_id"]))
        log.info("Menéame: envío %s (noticia %s) · %d comentarios", link_id, v["cluster_id"], n)
        total += len(comments)
    conn.commit()
    return total


def process(conn, now, fetch=feeds.fetch):
    if not config.MENEAME_ENABLED:
        return {}
    stats = {"new": poll(conn, now, fetch)}
    stats["matched"] = match(conn, now)
    stats["comments"] = read_comments(conn, now, fetch)
    return stats
