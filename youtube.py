"""Comentarios de YouTube para la sección «Qué dicen los lectores».

Sin IA salvo el resumen final:
  1. Se vigilan los canales de YouTube de los medios españoles: cada 30 minutos se leen
     sus últimos vídeos (la búsqueda general de YouTube no encuentra bien estos vídeos).
  2. Cada vídeo se asigna a su noticia con el mismo algoritmo que agrupa los artículos
     (título y descripción del vídeo frente a las noticias activas).
  3. Solo noticias nuevas (menos de 24 h) de 2 medios o más. Los comentarios se leen cuando el
     vídeo lleva 1 h publicado y se releen cada 3 h durante 24 h. Se guarda solo el texto.
  4. Con al menos 8 comentarios, la IA resume en 2-3 frases neutrales lo que opinan los
     lectores (writer.summarize_readers); como mucho cada 6 h y con 20 comentarios nuevos.

Cupo gratuito de la API: 10.000 unidades al día (leer los vídeos de un canal o una página
de comentarios cuesta 1) y 100 búsquedas, que solo se usan una vez para localizar cada canal.
"""
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import config
import writer
from textproc import STOPWORDS, fold

log = logging.getLogger("youtube")

API = "https://www.googleapis.com/youtube/v3/"

# Canales que se vigilan (nombre tal como aparece en YouTube; se localizan una sola vez).
WATCH_CHANNELS = [
    "RTVE Noticias", "laSexta", "Antena 3 Noticias", "Informativos Telecinco", "EL PAÍS", "EL MUNDO",
    "ABC", "20minutos", "El Español", "La Vanguardia", "Europa Press", "Cadena SER", "COPE",
    "Onda Cero", "El Confidencial", "elDiario.es", "Newtral", "Agencia EFE", "La Razón", "OKDIARIO",
    "Público", "Telemadrid", "Canal Sur", "Libertad Digital", "El Periódico", "TRECE",
]

# Canales de YouTube de medios españoles (se compara con el nombre del canal, sin tildes).
MEDIA_CHANNELS = [
    "rtve", "24h", "lasexta", "antena 3", "el pais", "el mundo", "abc", "20minutos", "telecinco",
    "informativos telecinco", "cuatro", "el espanol", "la vanguardia", "europa press", "cadena ser",
    "cope", "onda cero", "el confidencial", "eldiario", "newtral", "efe", "la razon", "okdiario",
    "publico", "telemadrid", "canal sur", "a punt", "eitb", "la voz de galicia", "heraldo",
    "el periodico", "expansion", "libertad digital", "esradio", "trece", "euronews espanol",
]
_CHANNEL_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in MEDIA_CHANNELS) + r")\b")


class YouTubeError(Exception):
    def __init__(self, status, reason, message=""):
        super().__init__(f"HTTP {status} {reason} {message}".strip())
        self.status, self.reason = status, reason


def api_get(endpoint, params):
    params = {**params, "key": config.YOUTUBE_API_KEY}
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        reason, message = "", ""
        try:
            err = json.loads(e.read()).get("error", {})
            message = err.get("message", "")[:200]
            reason = (err.get("errors") or [{}])[0].get("reason", "")
        except Exception:
            pass
        raise YouTubeError(e.code, reason, message) from None


def is_media_channel(name):
    return bool(_CHANNEL_RE.search(fold(name or "")))


# ---------------------------------------------------------------- cupo diario de búsquedas

def _quota_day():
    """La cuota de YouTube se reinicia a medianoche de la hora del Pacífico."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:
        return (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d")


def searches_left(conn):
    row = conn.execute("SELECT v FROM kv WHERE k='yt_searches'").fetchone()
    day, used = (row[0].split(":") + ["0"])[:2] if row else ("", "0")
    return config.YT_SEARCHES_PER_DAY - (int(used) if day == _quota_day() else 0)


def _count_search(conn):
    left = searches_left(conn)
    used = config.YT_SEARCHES_PER_DAY - left + 1
    conn.execute("INSERT OR REPLACE INTO kv(k, v) VALUES ('yt_searches', ?)", (f"{_quota_day()}:{used}",))


# ---------------------------------------------------------------- canales y vídeos nuevos

def resolve_channels(conn, get=api_get, max_per_cycle=30):
    """Localiza el id de cada canal de WATCH_CHANNELS (una sola vez; se guarda en kv)."""
    done = 0
    for name in WATCH_CHANNELS:
        key = "ytch:" + name
        if conn.execute("SELECT 1 FROM kv WHERE k=?", (key,)).fetchone():
            continue
        if done >= max_per_cycle or searches_left(conn) <= 0:
            break
        _count_search(conn)
        data = get("search", {"part": "snippet", "type": "channel", "q": name, "regionCode": "ES", "maxResults": 5})
        want = set(re.findall(r"[a-z0-9]+", fold(name)))
        found = "-"
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            title = sn.get("channelTitle") or sn.get("title") or ""
            cid = (it.get("id") or {}).get("channelId") or sn.get("channelId")
            if cid and want <= set(re.findall(r"[a-z0-9]+", fold(title))):
                found = f"{cid}|{title}"
                break
        conn.execute("INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)", (key, found))
        log.info("YouTube: canal «%s» -> %s", name, found)
        done += 1
    conn.commit()
    return done


def watched_channels(conn):
    out = []
    for (v,) in conn.execute("SELECT v FROM kv WHERE k LIKE 'ytch:%' AND v != '-'"):
        cid, _, title = v.partition("|")
        out.append((cid, title))
    return out


def poll_uploads(conn, now, get=api_get):
    """Últimos vídeos de cada canal vigilado (1 unidad por canal), cada YT_POLL_MIN minutos."""
    row = conn.execute("SELECT v FROM kv WHERE k='yt_polled'").fetchone()
    if row and now - float(row[0]) < config.YT_POLL_MIN * 60:
        return []
    new = []
    for cid, title in watched_channels(conn):
        try:
            data = get("playlistItems", {"part": "snippet", "playlistId": "UU" + cid[2:], "maxResults": 20})
        except YouTubeError as e:
            log.warning("YouTube: no se pudieron leer los vídeos de %s (%s)", title, e)
            continue
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            vid = (sn.get("resourceId") or {}).get("videoId")
            pub = sn.get("publishedAt")
            ts = datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp() if pub else now
            if not vid or now - ts > 24 * 3600:
                continue
            cur = conn.execute(
                """INSERT OR IGNORE INTO yt_pool(video_id, channel, title, description, published_at, seen_at)
                   VALUES (?,?,?,?,?,?)""",
                (vid, title, sn.get("title") or "", (sn.get("description") or "")[:800], ts, now))
            if cur.rowcount:
                new.append(vid)
    conn.execute("INSERT OR REPLACE INTO kv(k, v) VALUES ('yt_polled', ?)", (str(now),))
    conn.execute("DELETE FROM yt_pool WHERE seen_at < ?", (now - 48 * 3600,))
    conn.commit()
    return new


def match_videos(conn, now):
    """Asigna los vídeos aún sin noticia a la noticia nueva y relevante que mejor encaja."""
    from clustering import vectorize
    from textproc import article_features
    from worker import load_state   # import tardío: worker importa este módulo
    # vídeos sin noticia de las últimas 12 h: se reintentan en cada pasada, porque a menudo
    # el vídeo sale antes de que la noticia tenga suficientes medios
    pool = conn.execute("SELECT * FROM yt_pool WHERE (cluster_id IS NULL OR cluster_id = -1) AND seen_at >= ?",
                        (now - 12 * 3600,)).fetchall()
    if not pool:
        return 0
    feats = [article_features(v["title"], v["description"]) for v in pool]
    corpus, matcher = load_state(conn, now, [f for f, _ in feats])
    eligible = {r[0]: r[1] for r in conn.execute(
        """SELECT id, first_published FROM clusters WHERE status='active'
           AND (n_sources >= ? OR breaking_at IS NOT NULL) AND first_published >= ?""",
        (config.YT_MIN_SOURCES, now - config.YT_NEW_HOURS * 3600))}
    matched = 0
    for v, (f, ents) in zip(pool, feats):
        cl, score = matcher.best_match(vectorize(f, corpus), ents, v["published_at"])
        conn.execute("UPDATE yt_pool SET cluster_id=-1 WHERE video_id=?", (v["video_id"],))  # revisado
        if cl is None or score < config.YT_MATCH_THRESHOLD or cl.id not in eligible:
            continue
        if v["published_at"] < (eligible[cl.id] or 0) - 6 * 3600:
            continue  # vídeo anterior a la noticia
        if conn.execute("SELECT COUNT(*) FROM yt_videos WHERE cluster_id=?", (cl.id,)).fetchone()[0] >= 3:
            continue
        conn.execute("UPDATE yt_pool SET cluster_id=? WHERE video_id=?", (cl.id, v["video_id"]))
        conn.execute(
            """INSERT OR IGNORE INTO yt_videos(video_id, cluster_id, channel, title, published_at, found_at)
               VALUES (?,?,?,?,?,?)""", (v["video_id"], cl.id, v["channel"], v["title"], v["published_at"], now))
        log.info("YouTube: vídeo «%s» (%s) -> noticia %s (%.2f)", v["title"][:70], v["channel"], cl.id, score)
        matched += 1
    conn.commit()
    log.info("YouTube: %d vídeos recientes sin noticia revisados, %d asignados", len(pool), matched)
    return matched


def fetch_comments(video_id, get=api_get):
    data = get("commentThreads", {
        "part": "snippet", "videoId": video_id, "order": "relevance",
        "maxResults": 50, "textFormat": "plainText",
    })
    out = []
    for it in data.get("items", []):
        sn = (it.get("snippet") or {}).get("topLevelComment", {}).get("snippet", {})
        text = (sn.get("textDisplay") or "").strip()
        if not text:
            continue
        pub = sn.get("publishedAt")
        out.append({"id": it.get("id"), "text": text[:600], "likes": int(sn.get("likeCount") or 0),
                    "published_at": datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp() if pub else None})
    return out


# ---------------------------------------------------------------- ciclo

def process(conn, now, get=api_get, countries=None):   # countries: ya no se usa (compatibilidad)
    """Busca vídeos de las noticias relevantes y relee sus comentarios. Devuelve estadísticas."""
    stats = {"searched": 0, "videos": 0, "comments": 0}   # searched = vídeos nuevos vistos en los canales
    if not config.YOUTUBE_API_KEY and get is api_get:
        return stats

    # 1) localizar canales (una vez), leer sus vídeos nuevos y asignarlos a noticias
    try:
        resolve_channels(conn, get)
        stats["searched"] = len(poll_uploads(conn, now, get))
        stats["videos"] = match_videos(conn, now)
    except YouTubeError as e:
        log.warning("YouTube: %s", e)
        if e.reason in ("quotaExceeded", "dailyLimitExceeded"):
            return stats

    # 2) leer comentarios: la primera vez cuando el vídeo lleva 1 h publicado y después
    #    cada 3 h, durante las primeras 24 h desde que se encontró
    vids = conn.execute(
        """SELECT v.video_id, v.cluster_id FROM yt_videos v JOIN clusters c ON c.id = v.cluster_id
           WHERE c.status='active' AND v.disabled=0 AND v.found_at >= ?
             AND COALESCE(v.published_at, v.found_at) <= ?
             AND (v.checked_at IS NULL OR v.checked_at < ?)
           ORDER BY c.relevance DESC LIMIT 12""",
        (now - config.YT_FOLLOW_HOURS * 3600, now - config.YT_FIRST_READ_MIN * 60,
         now - config.YT_RECHECK_MIN * 60)).fetchall()
    for v in vids:
        try:
            comments = fetch_comments(v["video_id"], get)
        except YouTubeError as e:
            if e.reason == "commentsDisabled" or e.status == 404:
                conn.execute("UPDATE yt_videos SET disabled=1, checked_at=? WHERE video_id=?", (now, v["video_id"]))
                continue
            log.warning("YouTube: comentarios fallidos (%s)", e)
            break
        for c in comments:
            conn.execute(
                """INSERT INTO yt_comments(comment_id, video_id, cluster_id, text, likes, published_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(comment_id) DO UPDATE SET likes=excluded.likes""",
                (c["id"], v["video_id"], v["cluster_id"], c["text"], c["likes"], c["published_at"]))
        n = conn.execute("SELECT COUNT(*) FROM yt_comments WHERE video_id=?", (v["video_id"],)).fetchone()[0]
        conn.execute("UPDATE yt_videos SET checked_at=?, comment_count=? WHERE video_id=?", (now, n, v["video_id"]))
        stats["comments"] += len(comments)
        log.info("YouTube: vídeo %s (noticia %s) · %d comentarios leídos, %d guardados", v["video_id"],
                 v["cluster_id"], len(comments), n)
        conn.commit()
    conn.commit()
    return stats


def summarize_pending(conn, now):
    """Pide a la IA el resumen «Qué dicen los lectores» donde hay comentarios nuevos suficientes."""
    if not writer.ai_enabled():
        return 0
    rows = conn.execute(
        """SELECT c.id, c.headline, c.readers_count, COUNT(y.comment_id) AS n
           FROM clusters c JOIN yt_comments y ON y.cluster_id = c.id
           WHERE c.status='active' AND c.headline IS NOT NULL
             AND (c.readers_at IS NULL OR c.readers_at < ?)
           GROUP BY c.id
           HAVING n >= ? AND (c.readers_count IS NULL OR n >= c.readers_count + ?)
           ORDER BY c.relevance DESC LIMIT ?""",
        (now - config.READERS_EVERY_MIN * 60, config.YT_MIN_COMMENTS, config.READERS_MIN_NEW,
         config.READERS_MAX_PER_CYCLE)).fetchall()
    done = 0
    for r in rows:
        comments = [x[0] for x in conn.execute(
            "SELECT text FROM yt_comments WHERE cluster_id=? ORDER BY likes DESC LIMIT 60", (r["id"],))]
        try:
            summary = writer.summarize_readers(r["headline"], comments)
        except Exception as e:
            log.warning("IA: resumen de lectores falló en noticia %s: %s", r["id"], e)
            continue
        conn.execute("UPDATE clusters SET readers_summary=?, readers_count=?, readers_at=? WHERE id=?",
                     (summary, r["n"], now, r["id"]))
        conn.commit()
        done += 1
        log.info("Lectores: noticia %s · %d comentarios · %s", r["id"], r["n"], summary)
    return done
