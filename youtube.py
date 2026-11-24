"""Comentarios de YouTube para la sección «Qué dicen los lectores».

Sin IA salvo el resumen final:
  1. Para las noticias relevantes se busca el vídeo en YouTube (API oficial de Google)
     y solo se aceptan vídeos de canales de medios españoles cuyo título encaje con la
     noticia.
  Solo noticias nuevas (menos de 12 h). Los comentarios se leen cuando el vídeo lleva 1 h
  publicado y se releen cada 3 h durante 24 h; el resumen se rehace como mucho cada 6 h
  y solo si han llegado 20 comentarios nuevos o más.
  2. Se leen sus comentarios más valorados. Se guarda solo el texto y los «me gusta»:
     ni autores ni perfiles.
  3. Cuando hay suficientes comentarios, la IA escribe 2-3 frases neutrales con las
     opiniones principales (writer.summarize_readers).

Cupo gratuito de la API: 100 búsquedas al día y 10.000 unidades para lo demás (leer
comentarios cuesta 1 unidad por página de 50).
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
import intl
import writer
from textproc import STOPWORDS, fold

log = logging.getLogger("youtube")

API = "https://www.googleapis.com/youtube/v3/"

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


# ---------------------------------------------------------------- búsqueda del vídeo

def query_terms(conn, cid, countries):
    """Palabras para buscar la noticia: la etiqueta de la IA o sus nombres propios."""
    c = conn.execute("SELECT tag FROM clusters WHERE id=?", (cid,)).fetchone()
    arts = conn.execute("SELECT title, summary, entities FROM articles WHERE cluster_id=?", (cid,)).fetchall()
    if c and c["tag"]:
        words = [w for w in re.findall(r"[a-z0-9]+", fold(c["tag"])) if w not in STOPWORDS and len(w) > 2]
        if words:
            return c["tag"], words
    texts = [f"{a['title']}. {a['summary'] or ''}" for a in arts]
    terms = intl.search_terms([json.loads(a["entities"]) for a in arts], "es", countries, texts=texts)
    return " ".join(terms[:3]), [fold(t) for t in terms[:3]]


def find_videos(query, keywords, since, get=api_get, limit=2):
    data = get("search", {
        "part": "snippet", "type": "video", "q": query, "regionCode": "ES",
        "relevanceLanguage": "es", "order": "relevance", "maxResults": 15,
        "publishedAfter": datetime.fromtimestamp(since, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    need = min(2, len(keywords))
    out = []
    for it in data.get("items", []):
        sn = it.get("snippet", {})
        vid = (it.get("id") or {}).get("videoId")
        if not vid or not is_media_channel(sn.get("channelTitle")):
            continue
        text = fold(f"{sn.get('title', '')} {sn.get('description', '')}")
        if sum(1 for k in keywords if re.search(r"\b" + re.escape(k) + r"\b", text)) < need:
            continue
        pub = sn.get("publishedAt")
        out.append({"video_id": vid, "channel": sn.get("channelTitle"), "title": sn.get("title"),
                    "published_at": datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp() if pub else None})
        if len(out) >= limit:
            break
    return out


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

def process(conn, now, get=api_get, countries=None):
    """Busca vídeos de las noticias relevantes y relee sus comentarios. Devuelve estadísticas."""
    stats = {"searched": 0, "videos": 0, "comments": 0}
    if not config.YOUTUBE_API_KEY and get is api_get:
        return stats
    countries = countries if countries is not None else intl.load_countries()

    # 1) buscar el vídeo de las noticias nuevas que aún no lo tienen (un reintento a las 6 h)
    budget = min(config.YT_SEARCHES_PER_CYCLE, searches_left(conn))
    rows = conn.execute(
        """SELECT c.id, c.first_published FROM clusters c
           WHERE c.status='active' AND (c.n_sources >= ? OR c.breaking_at IS NOT NULL)
             AND c.first_published >= ?          -- solo noticias nuevas
             AND (c.yt_checked_at IS NULL
                  OR (c.yt_checked_at < ? AND NOT EXISTS (SELECT 1 FROM yt_videos v WHERE v.cluster_id = c.id)))
           ORDER BY c.relevance DESC LIMIT ?""",
        (config.YT_MIN_SOURCES, now - config.YT_NEW_HOURS * 3600, now - 6 * 3600, max(0, budget))).fetchall()
    for r in rows:
        query, keywords = query_terms(conn, r["id"], countries)
        if not keywords:
            conn.execute("UPDATE clusters SET yt_checked_at=? WHERE id=?", (now, r["id"]))
            continue
        try:
            _count_search(conn)
            videos = find_videos(query, keywords, (r["first_published"] or now) - 12 * 3600, get)
        except YouTubeError as e:
            log.warning("YouTube: búsqueda fallida (%s)", e)
            if e.reason in ("quotaExceeded", "dailyLimitExceeded"):
                conn.execute("INSERT OR REPLACE INTO kv(k, v) VALUES ('yt_searches', ?)",
                             (f"{_quota_day()}:{config.YT_SEARCHES_PER_DAY}",))
            break
        stats["searched"] += 1
        for v in videos:
            conn.execute(
                """INSERT OR IGNORE INTO yt_videos(video_id, cluster_id, channel, title, published_at, found_at)
                   VALUES (?,?,?,?,?,?)""", (v["video_id"], r["id"], v["channel"], v["title"], v["published_at"], now))
            stats["videos"] += 1
        conn.execute("UPDATE clusters SET yt_checked_at=? WHERE id=?", (now, r["id"]))
        log.info("YouTube: noticia %s · «%s» -> %d vídeos", r["id"], query, len(videos))
        conn.commit()

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
