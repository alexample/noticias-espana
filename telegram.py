"""Publica en un canal de Telegram las noticias importantes y sus actualizaciones.

No usa IA propia: reutiliza el titular, la entradilla y la frase de "novedad"
que la IA ya escribe al redactar cada noticia.

  - Noticia nueva: cuando alcanza TELEGRAM_MIN_SOURCES medios y ya está redactada.
  - Actualización: cuando la IA detecta una novedad en una noticia ya publicada; se
    envía como respuesta al mensaje original, así el canal agrupa cada historia.
"""
import html
import json
import logging
import time
import urllib.error
import urllib.request

import breaking
import config

log = logging.getLogger("telegram")


class RateLimited(Exception):
    pass


def send(text, reply_to=None, preview_url=None):
    """Envía un mensaje al canal. Devuelve el message_id."""
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if preview_url:  # miniatura grande con el titular y la foto (página n/<id>.html)
        payload["link_preview_options"] = {"url": preview_url, "prefer_large_media": True}
    else:
        payload["link_preview_options"] = {"is_disabled": True}
    if reply_to:
        payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        data=json.dumps(payload).encode(), method="POST", headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode(errors="replace")
        if e.code == 429:
            raise RateLimited(body) from None
        raise RuntimeError(f"Telegram HTTP {e.code}: {body}") from None
    return data["result"]["message_id"]


def enabled():
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _e(s):
    return html.escape(s or "", quote=False)


def page_url(cid):
    return f"{config.SITE_URL}n/{cid}.html"


def _link(cid):
    return f'<a href="{page_url(cid)}">Leer en DobleCheck →</a>'


def _media_line(sources):
    n = len(sources)
    names = ", ".join(sources[:4]) + (f" y {n - 4} más" if n > 4 else "")
    if n == 1:
        return f"Fuente: {_e(names)}"
    return f"✅ Confirmada por {n} medios: {_e(names)}"


def _header(label, n_sources):
    ticks = "✓✓" if n_sources >= 2 else "✓"
    return f"{_e(config.TELEGRAM_HEADER)} {ticks}  ·  <i>{label}</i>"


def format_new(story, sources, flags, is_breaking=False):
    """Noticia ya redactada por la IA (confirmada por varios medios)."""
    lines = [_header("Última hora" if is_breaking else "Noticia confirmada", len(sources)), "",
             f"{'🔴' if is_breaking else '🗞'} <b>{_e(story['headline'])}</b>", ""]
    if story["lead"]:
        lines += [_e(story["lead"]), ""]
    lines.append(_media_line(sources))
    if flags:
        lines.append("🌍 También en la prensa de " + " ".join(flags))
    lines += ["", _link(story["id"])]
    return "\n".join(lines)


def format_breaking(story, rep, sources):
    """Última hora todavía sin redactar: titular original citando al medio, sin IA."""
    title = breaking.strip_label(rep["title"])
    lines = [_header("Última hora", len(sources)), "", f"🔴 <b>{_e(title)}</b>", "",
             f"Según {_e(rep['source'])}."]
    if len(sources) == 1:
        lines.append("☑️ Pendiente de confirmar por otros medios")
    else:
        lines.append(_media_line(sources))
    lines += ["", _link(story["id"])]
    return "\n".join(lines)


def format_confirmed(story, sources):
    """Respuesta cuando una última hora publicada con un medio queda confirmada y redactada."""
    lines = [_header("Confirmada", len(sources)), "", f"✅ <b>{_e(story['headline'])}</b>", ""]
    if story["lead"]:
        lines += [_e(story["lead"]), ""]
    lines += [_media_line(sources), "", _link(story["id"])]
    return "\n".join(lines)


def format_update(story, note, n_sources):
    return "\n".join([_header("Actualización", n_sources), "",
                      f"🔄 <b>{_e(note)}</b>", "", f"✅ Ya la confirman {n_sources} medios", "", _link(story["id"])])


def _sources(conn, cid):
    return [r[0] for r in conn.execute(
        "SELECT source FROM articles WHERE cluster_id=? GROUP BY source ORDER BY MIN(published_at)", (cid,))]


def _flags(conn, cid, countries):
    codes = [r[0] for r in conn.execute("SELECT DISTINCT country FROM intl_articles WHERE cluster_id=?", (cid,))]
    return [countries.get(c, {}).get("flag", c.upper()) for c in codes]


def mark_existing(conn, now, keep=0):
    """Marca como vistas, sin publicarlas, las noticias que ya cumplen el criterio,
    salvo las `keep` más relevantes.

    Se usa al activar el canal (keep=3: arranca con las 3 noticias principales) y
    cuando la base de datos es nueva por haberse perdido la caché (keep=0), para no
    inundar el canal con todo lo acumulado."""
    conn.execute(
        """INSERT OR IGNORE INTO telegram_posts(cluster_id, message_id, posted_at, last_update_at)
           SELECT id, NULL, ?, ? FROM clusters WHERE status='active' AND (n_sources >= ? OR breaking_at IS NOT NULL)
             AND id NOT IN (SELECT id FROM clusters WHERE status='active' AND n_sources >= ?
                            AND headline IS NOT NULL ORDER BY relevance DESC LIMIT ?)""",
        (now, now, config.TELEGRAM_MIN_SOURCES, config.TELEGRAM_MIN_SOURCES, keep))
    conn.commit()


def process(conn, now, sender=None, countries=None, written_before=None):
    """Publica noticias nuevas y actualizaciones. Devuelve (nuevas, actualizaciones)."""
    if not enabled() and sender is None:
        return 0, 0
    sender = sender or send
    if countries is None:
        try:
            import intl
            countries = intl.load_countries()
        except Exception:
            countries = {}
    new = updates = 0
    try:
        # 1) noticias que acaban de cruzar el umbral, o de última hora (aunque tengan un solo medio)
        rows = conn.execute(
            """SELECT c.*, a.title AS rep_title, a.source AS rep_source
               FROM clusters c LEFT JOIN telegram_posts t ON t.cluster_id = c.id
                    LEFT JOIN articles a ON a.id = c.rep_article_id
               WHERE t.cluster_id IS NULL AND c.status='active' AND c.last_published >= ?
                 AND ((c.n_sources >= ? AND c.headline IS NOT NULL
                       AND (? IS NULL OR c.ai_written_at < ?))       -- su página ya está en la web
                      OR (c.breaking_at IS NOT NULL AND c.breaking_at >= ?
                          AND (? IS NULL OR c.breaking_at < ?)))
               ORDER BY (c.breaking_at IS NOT NULL) DESC, c.relevance DESC LIMIT ?""",
            (now - 6 * 3600, config.TELEGRAM_MIN_SOURCES, written_before, written_before,
             now - breaking.BREAKING_TTL_S, written_before, written_before,
             config.TELEGRAM_MAX_NEW_PER_CYCLE)).fetchall()
        for c in rows:
            srcs = _sources(conn, c["id"])
            is_breaking = c["breaking_at"] is not None
            if c["headline"]:
                text = format_new(c, srcs, _flags(conn, c["id"], countries), is_breaking)
            elif c["rep_title"]:
                text = format_breaking(c, {"title": c["rep_title"], "source": c["rep_source"]}, srcs)
            else:
                continue
            msg_id = sender(text, preview_url=page_url(c["id"]))
            # last_update_at = ai_written_at: las novedades anteriores ya están en el mensaje
            conn.execute(
                "INSERT INTO telegram_posts(cluster_id, message_id, posted_at, last_update_at, posted_ai) VALUES (?,?,?,?,?)",
                (c["id"], msg_id, now, c["ai_written_at"] or now, 1 if c["headline"] else 0))
            conn.commit()
            new += 1
            log.info("Telegram: publicada noticia %s%s", c["id"], " (última hora)" if is_breaking else "")
            time.sleep(1)

        # 1b) últimas horas publicadas con el titular original que ya están confirmadas y redactadas
        for r in conn.execute(
                """SELECT c.*, t.message_id FROM telegram_posts t JOIN clusters c ON c.id = t.cluster_id
                   WHERE t.posted_ai = 0 AND t.message_id IS NOT NULL AND c.status='active'
                     AND c.headline IS NOT NULL AND c.n_sources >= 2
                   ORDER BY c.relevance DESC LIMIT ?""", (config.TELEGRAM_MAX_UPDATES_PER_CYCLE,)).fetchall():
            sender(format_confirmed(r, _sources(conn, r["id"])), reply_to=r["message_id"])
            conn.execute("UPDATE telegram_posts SET posted_ai=1, last_update_at=? WHERE cluster_id=?", (now, r["id"]))
            conn.commit()
            updates += 1
            log.info("Telegram: confirmada noticia %s", r["id"])
            time.sleep(1)

        # 2) novedades de noticias ya publicadas, como respuesta al mensaje original
        rows = conn.execute(
            """SELECT t.cluster_id, t.message_id, t.last_update_at, c.n_sources, c.id, c.headline
               FROM telegram_posts t JOIN clusters c ON c.id = t.cluster_id
               WHERE t.message_id IS NOT NULL AND c.status='active' AND t.last_update_at < ?
               ORDER BY c.relevance DESC""",
            (now - config.TELEGRAM_UPDATE_EVERY_MIN * 60,)).fetchall()
        for r in rows:
            if updates >= config.TELEGRAM_MAX_UPDATES_PER_CYCLE:
                break
            u = conn.execute(
                """SELECT note, at FROM story_updates WHERE cluster_id=? AND at > ? AND note IS NOT NULL AND note != ''
                   ORDER BY at DESC LIMIT 1""", (r["cluster_id"], r["last_update_at"])).fetchone()
            if not u:
                continue
            sender(format_update(r, u["note"], r["n_sources"]), reply_to=r["message_id"])
            conn.execute("UPDATE telegram_posts SET last_update_at=? WHERE cluster_id=?", (now, r["cluster_id"]))
            conn.commit()
            updates += 1
            log.info("Telegram: actualización de noticia %s", r["cluster_id"])
            time.sleep(1)
    except RateLimited as e:
        log.warning("Telegram pide esperar; se sigue en el próximo ciclo: %s", e)
    return new, updates
