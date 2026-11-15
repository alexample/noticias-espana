"""Servidor web: API JSON + página. Sin dependencias.

  GET /                      página
  GET /api/stories           ?min_sources=2&limit=40&q=texto&hours=48
  GET /api/stories/<id>      detalle con todas las fuentes
  GET /api/status            estado de los medios y del worker
"""
import json
import os
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import db

_STORY_RE = re.compile(r"^/api/stories/(\d+)$")


def _resolve(conn, cid):
    """Sigue fusiones: una URL antigua lleva a la noticia que la absorbió."""
    for _ in range(10):
        row = conn.execute("SELECT status, merged_into FROM clusters WHERE id=?", (cid,)).fetchone()
        if not row or row["status"] != "merged":
            return cid
        cid = row["merged_into"]
    return cid


def _story_dict(c, rep, sources):
    return {
        "id": c["id"],
        "headline": c["headline"] or (rep["title"] if rep else ""),
        "lead": c["lead"] or (rep["summary"][:300] if rep and rep["summary"] else ""),
        "ai_written": c["headline"] is not None,
        "ai_written_at": c["ai_written_at"],
        "ai_sources_count": c["ai_sources_count"],
        "image": c["image"],
        "n_sources": c["n_sources"],
        "n_articles": c["n_articles"],
        "relevance": c["relevance"],
        "first_published": c["first_published"],
        "last_published": c["last_published"],
        "updated_at": c["updated_at"],
        "status": c["status"],
        "sources": sources,
    }


def list_stories(conn, min_sources=2, limit=40, q="", hours=48):
    since = time.time() - hours * 3600
    params = [min_sources, since]
    where = "c.status IN ('active','closed') AND c.n_sources >= ? AND c.last_published >= ?"
    if q:
        where += """ AND (c.headline LIKE ? OR c.lead LIKE ? OR EXISTS (
                     SELECT 1 FROM articles x WHERE x.cluster_id=c.id AND x.title LIKE ?))"""
        like = f"%{q}%"
        params += [like, like, like]
    rows = conn.execute(
        f"SELECT c.* FROM clusters c WHERE {where} ORDER BY c.relevance DESC LIMIT ?", params + [limit]).fetchall()
    out = []
    for c in rows:
        rep = conn.execute("SELECT title, summary FROM articles WHERE id=?", (c["rep_article_id"],)).fetchone()
        srcs = [r[0] for r in conn.execute(
            "SELECT source FROM articles WHERE cluster_id=? GROUP BY source ORDER BY MIN(published_at)", (c["id"],))]
        out.append(_story_dict(c, rep, srcs))
    return out


def get_story(conn, cid):
    cid = _resolve(conn, cid)
    c = conn.execute("SELECT * FROM clusters WHERE id=?", (cid,)).fetchone()
    if not c:
        return None
    rep = conn.execute("SELECT title, summary FROM articles WHERE id=?", (c["rep_article_id"],)).fetchone()
    arts = conn.execute(
        """SELECT a.id, a.source, a.title, a.summary, a.url, a.image, a.published_at, a.fetched_at, a.match_score
           FROM articles a WHERE a.cluster_id=? ORDER BY a.published_at DESC""", (cid,)).fetchall()
    srcs = sorted({a["source"] for a in arts})
    d = _story_dict(c, rep, srcs)
    d["body"] = c["body"]
    ai_at = c["ai_written_at"] or 0
    d["articles"] = [{**dict(a), "summary": (a["summary"] or "")[:400],
                      "new_since_ai": bool(c["headline"]) and a["fetched_at"] > ai_at} for a in arts]
    return d


def status(conn):
    srcs = [dict(r) for r in conn.execute(
        "SELECT name, last_fetch, last_status, last_items, weight FROM sources WHERE enabled=1 ORDER BY name")]
    counts = conn.execute(
        """SELECT COUNT(*) total, SUM(status='active') active, SUM(status='active' AND n_sources>=2) multi
           FROM clusters""").fetchone()
    last = max((s["last_fetch"] or 0) for s in srcs) if srcs else None
    return {"sources": srcs, "last_cycle": last, "clusters": dict(counts),
            "articles": conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
            "ai_enabled": bool(config.ANTHROPIC_API_KEY)}


class Handler(BaseHTTPRequestHandler):
    server_version = "Noticias/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            return self._json({"error": "no encontrado"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        qs = urllib.parse.parse_qs(url.query)

        def arg(name, default, cast):
            try:
                return cast(qs.get(name, [default])[0])
            except (TypeError, ValueError):
                return default

        if url.path in ("/", "/index.html") or url.path.startswith("/noticia/"):
            return self._file(os.path.join(config.STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        conn = db.connect()
        try:
            if url.path == "/api/stories":
                return self._json(list_stories(
                    conn, min_sources=max(1, arg("min_sources", 2, int)), limit=min(200, arg("limit", 40, int)),
                    q=arg("q", "", str).strip()[:100], hours=min(168, arg("hours", 48, int))))
            m = _STORY_RE.match(url.path)
            if m:
                story = get_story(conn, int(m.group(1)))
                return self._json(story) if story else self._json({"error": "no encontrada"}, 404)
            if url.path == "/api/status":
                return self._json(status(conn))
            return self._json({"error": "no encontrado"}, 404)
        finally:
            conn.close()


def serve(host=None, port=None):
    conn = db.connect()
    db.init(conn)
    conn.close()
    httpd = ThreadingHTTPServer((host or config.HOST, port or config.PORT), Handler)
    print(f"Web en http://{host or config.HOST}:{port or config.PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
