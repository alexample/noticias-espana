"""Exporta las noticias a JSON estático para servir la web sin servidor (GitHub Pages).

  docs/data/stories.json  noticias de las últimas horas con sus artículos
  docs/data/status.json   estado de los medios
"""
import json
import os
import time

import config
import intl


def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def export_static(conn, out_dir=None, hours=48, limit=400):
    out_dir = out_dir or config.EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    now = time.time()
    clusters = conn.execute(
        """SELECT * FROM clusters WHERE status IN ('active','closed') AND last_published >= ?
           ORDER BY relevance DESC LIMIT ?""", (now - hours * 3600, limit)).fetchall()
    ids = [c["id"] for c in clusters]
    arts = {}
    if ids:
        q = ",".join("?" * len(ids))
        for a in conn.execute(
                f"""SELECT id, cluster_id, source, title, summary, url, image, published_at, fetched_at
                    FROM articles WHERE cluster_id IN ({q}) ORDER BY published_at DESC""", ids):
            arts.setdefault(a["cluster_id"], []).append(a)
    foreign = {}
    if ids:
        for f in conn.execute(
                f"""SELECT cluster_id, country, source, title, url, published_at FROM intl_articles
                    WHERE cluster_id IN ({q}) ORDER BY published_at DESC""", ids):
            foreign.setdefault(f["cluster_id"], {}).setdefault(f["country"], []).append(f)
    try:
        countries = intl.load_countries()
    except (OSError, ValueError):
        countries = {}
    stories = []
    for c in clusters:
        items = arts.get(c["id"], [])
        rep = next((a for a in items if a["id"] == c["rep_article_id"]), items[0] if items else None)
        ai_at = c["ai_written_at"] or 0
        sources = []
        for a in sorted(items, key=lambda a: a["published_at"]):
            if a["source"] not in sources:
                sources.append(a["source"])
        recent = [a for a in items if a["fetched_at"] >= now - 2 * 3600]
        stories.append({
            "id": c["id"],
            "tag": c["tag"],
            "recent_articles": len(recent),               # artículos llegados en las últimas 2 h
            "recent_sources": len({a["source"] for a in recent}),
            "headline": c["headline"] or (rep["title"] if rep else ""),
            "lead": c["lead"] or ((rep["summary"] or "")[:300] if rep else ""),
            "body": c["body"] or "",
            "ai_written": c["headline"] is not None,
            "ai_written_at": c["ai_written_at"],
            "ai_sources_count": c["ai_sources_count"],
            "image": c["image"],
            "n_sources": c["n_sources"],
            "n_articles": c["n_articles"],
            "relevance": c["relevance"],
            "first_published": c["first_published"],
            "last_published": c["last_published"],
            "sources": sources,
            "intl": [{
                "country": code, "name": countries.get(code, {}).get("name", code.upper()),
                "flag": countries.get(code, {}).get("flag", ""),
                "articles": [{"source": f["source"], "title": f["title"], "url": f["url"],
                              "published_at": f["published_at"]} for f in fs[:8]],
            } for code, fs in foreign.get(c["id"], {}).items()],
            "articles": [{
                "source": a["source"], "title": a["title"], "url": a["url"],
                "summary": (a["summary"] or "")[:240], "published_at": a["published_at"],
                "new_since_ai": bool(c["headline"]) and a["fetched_at"] > ai_at,
            } for a in items[:40]],
        })
    # ids antiguos que se fusionaron en otra noticia, para que los enlaces viejos sigan funcionando
    merged = {str(r["id"]): r["merged_into"] for r in conn.execute(
        "SELECT id, merged_into FROM clusters WHERE status='merged' AND updated_at >= ?", (now - hours * 3600,))}
    _write(os.path.join(out_dir, "stories.json"), {"generated_at": now, "stories": stories, "merged": merged})

    srcs = [dict(r) for r in conn.execute(
        "SELECT name, last_fetch, last_status, last_items FROM sources WHERE enabled=1 ORDER BY name")]
    _write(os.path.join(out_dir, "status.json"), {
        "generated_at": now, "sources": srcs, "ai_enabled": bool(config.ANTHROPIC_API_KEY),
        "multi": sum(1 for s in stories if s["n_sources"] >= 2)})
    return len(stories)


def prune(conn, days=7):
    """Borra datos antiguos para que la base de datos no crezca sin límite."""
    cutoff = time.time() - days * 86400
    conn.execute("DELETE FROM articles WHERE published_at < ? AND cluster_id IN "
                 "(SELECT id FROM clusters WHERE status != 'active')", (cutoff,))
    conn.execute("DELETE FROM intl_articles WHERE cluster_id NOT IN (SELECT id FROM clusters WHERE status='active') "
                 "AND fetched_at < ?", (cutoff,))
    conn.execute("""DELETE FROM clusters WHERE status != 'active' AND updated_at < ?
                    AND id NOT IN (SELECT DISTINCT cluster_id FROM articles WHERE cluster_id IS NOT NULL)""",
                 (cutoff,))
    conn.commit()
