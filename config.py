"""Configuración central. Todo se puede sobrescribir con variables de entorno."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env(name, default, cast=str):
    val = os.environ.get(name)
    return cast(val) if val not in (None, "") else default


# --- Rutas ---
DB_PATH = _env("NEWS_DB", os.path.join(BASE_DIR, "data", "noticias.db"))
FEEDS_FILE = _env("NEWS_FEEDS", os.path.join(BASE_DIR, "feeds.json"))
STATIC_DIR = os.path.join(BASE_DIR, "docs")             # la web (también es lo que publica GitHub Pages)
EXPORT_DIR = _env("NEWS_EXPORT_DIR", os.path.join(STATIC_DIR, "data"))  # JSON que lee la web
PRUNE_DAYS = _env("NEWS_PRUNE_DAYS", 7, int)

# --- Worker ---
POLL_SECONDS = _env("NEWS_POLL_SECONDS", 300, int)       # cada cuánto se leen los medios
FETCH_TIMEOUT = _env("NEWS_FETCH_TIMEOUT", 15, int)
FETCH_THREADS = _env("NEWS_FETCH_THREADS", 12, int)
MAX_ARTICLE_AGE_H = _env("NEWS_MAX_ARTICLE_AGE_H", 48, int)  # se ignoran artículos más antiguos
CLUSTER_ACTIVE_H = _env("NEWS_CLUSTER_ACTIVE_H", 72, int)    # una noticia sin novedades en este tiempo se cierra
USER_AGENT = "Mozilla/5.0 (compatible; DobleCheckNoticias/1.0)"

# --- Algoritmo de agrupación ---
# Puntuación mínima para añadir un artículo a una noticia existente (0-1).
JOIN_THRESHOLD = _env("NEWS_JOIN_THRESHOLD", 0.24, float)
# Similitud entre centroides a partir de la cual dos noticias se fusionan.
MERGE_THRESHOLD = _env("NEWS_MERGE_THRESHOLD", 0.50, float)

# --- Relevancia ---
RELEVANCE_HALF_LIFE_H = _env("NEWS_RELEVANCE_HALF_LIFE_H", 10, float)

# --- Redacción con IA (lo único que usa IA) ---
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY", "")
AI_MODEL = _env("NEWS_AI_MODEL", "claude-haiku-5-5")
AI_MIN_SOURCES = _env("NEWS_AI_MIN_SOURCES", 2, int)        # solo se redactan noticias con N medios o más
AI_MAX_PER_CYCLE = _env("NEWS_AI_MAX_PER_CYCLE", 8, int)
AI_MIN_INTERVAL_MIN = _env("NEWS_AI_MIN_INTERVAL_MIN", 10, int)  # no reescribir la misma noticia más a menudo
AI_MAX_SOURCES_IN_PROMPT = 15

# --- Cobertura internacional (prensa del país del que trata la noticia) ---
COUNTRIES_FILE = _env("NEWS_COUNTRIES", os.path.join(BASE_DIR, "countries.json"))
INTL_ENABLED = _env("NEWS_INTL", 1, int)
INTL_MIN_SOURCES = _env("NEWS_INTL_MIN_SOURCES", 3, int)    # solo noticias con cierta relevancia
INTL_MAX_PER_CYCLE = _env("NEWS_INTL_MAX_PER_CYCLE", 4, int)  # limita peticiones a Google Noticias
INTL_RECHECK_MIN = _env("NEWS_INTL_RECHECK_MIN", 60, int)     # cada cuánto se vuelve a buscar
INTL_MAX_PER_COUNTRY = 6

# --- Comentarios de YouTube ("Qué dicen los lectores") ---
YOUTUBE_API_KEY = _env("YOUTUBE_API_KEY", "")
YT_MIN_SOURCES = _env("YT_MIN_SOURCES", 4, int)           # solo noticias con cierta relevancia
YT_SEARCHES_PER_DAY = _env("YT_SEARCHES_PER_DAY", 90, int)  # la API permite 100 búsquedas al día
YT_SEARCHES_PER_CYCLE = _env("YT_SEARCHES_PER_CYCLE", 2, int)
YT_NEW_HOURS = _env("YT_NEW_HOURS", 12, int)                 # solo noticias nuevas (de menos de 12 h)
YT_FIRST_READ_MIN = _env("YT_FIRST_READ_MIN", 60, int)        # primera lectura: vídeo con 1 h publicado
YT_RECHECK_MIN = _env("YT_RECHECK_MIN", 180, int)             # después, releer cada 3 h…
YT_FOLLOW_HOURS = _env("YT_FOLLOW_HOURS", 24, int)            # …durante 24 h como máximo
YT_MIN_COMMENTS = _env("YT_MIN_COMMENTS", 15, int)            # mínimo para resumir
READERS_MAX_PER_CYCLE = _env("READERS_MAX_PER_CYCLE", 4, int)
READERS_EVERY_MIN = _env("READERS_EVERY_MIN", 360, int)       # el resumen se rehace como mucho cada 6 h
READERS_MIN_NEW = _env("READERS_MIN_NEW", 20, int)            # y solo si hay 20 comentarios nuevos o más

# --- Canal de Telegram ---
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")              # "@nombre_del_canal" o id numérico
TELEGRAM_MIN_SOURCES = _env("TELEGRAM_MIN_SOURCES", 4, int)  # medios mínimos para publicar una noticia
TELEGRAM_MAX_NEW_PER_CYCLE = _env("TELEGRAM_MAX_NEW_PER_CYCLE", 3, int)
TELEGRAM_MAX_UPDATES_PER_CYCLE = _env("TELEGRAM_MAX_UPDATES_PER_CYCLE", 4, int)
TELEGRAM_UPDATE_EVERY_MIN = _env("TELEGRAM_UPDATE_EVERY_MIN", 30, int)  # por noticia
# Cabecera con letras Unicode sin serifa: "Doble" normal y "Check" en negrita, como el logotipo de la web
# (Telegram no permite elegir fuente).
# Estos alfabetos no tienen tildes ni ñ: por eso solo se usan en la cabecera, no en titulares.
TELEGRAM_HEADER = _env("TELEGRAM_HEADER", "𝖣𝗈𝖻𝗅𝖾𝗖𝗵𝗲𝗰𝗸")  # se le añade ✓ (1 medio) o ✓✓ (confirmada)
SITE_URL = _env("NEWS_SITE_URL", "https://alexample.github.io/noticias-espana/")

# --- Web ---
HOST = _env("NEWS_HOST", "0.0.0.0")
PORT = _env("NEWS_PORT", 8000, int)
