"""Detección de "última hora", sin IA.

Una noticia es de última hora si:
  1. Etiqueta del medio: algún medio la titula como "Última hora" o "Urgente"
     (decisión editorial del propio medio). Se excluyen los directos recurrentes
     ("… en directo", "minuto a minuto"), que se publican a diario.
  2. Velocidad: 3 medios distintos la publican en menos de 45 minutos.

Las noticias de última hora se publican (web y Telegram) aunque solo las tenga un
medio, marcadas con un check ✓ "pendiente de confirmar"; cuando otros medios la
confirman pasan a doble check ✓✓.
"""
import re

from textproc import fold

LABEL_RE = re.compile(r"(^|[\[\(|:·-]\s*)(ultima hora|urgente)\b|\b(ultima hora|urgente)\s*[:|·\]\)-]")
LIVE_RE = re.compile(r"\b(directo|minuto a minuto|en vivo|live)\b")

LABEL_MAX_AGE_S = 90 * 60     # el titular etiquetado debe ser reciente
VELOCITY_SOURCES = 3
VELOCITY_WINDOW_S = 45 * 60
BREAKING_TTL_S = 6 * 3600     # cuánto tiempo se considera "última hora"


def is_labelled(title):
    t = fold(title)
    return bool(LABEL_RE.search(t)) and not LIVE_RE.search(t)


def strip_label(title):
    """Quita la etiqueta del medio para mostrar el titular limpio."""
    clean = re.sub(r"^\s*[\[\(]?\s*(última hora|ultima hora|urgente)\s*[\]\)]?\s*[:|·\-–—]?\s*", "",
                   title, flags=re.I).strip()
    if not clean:
        return title
    return clean[0].upper() + clean[1:] if clean != title else title


def velocity_ok(arts):
    """arts: [(source, published_at)] ordenados por fecha."""
    first = {}
    for src, ts in sorted(arts, key=lambda a: a[1]):
        first.setdefault(src, ts)
    times = sorted(first.values())
    return len(times) >= VELOCITY_SOURCES and times[VELOCITY_SOURCES - 1] - times[0] <= VELOCITY_WINDOW_S


def detect(conn, now):
    """Marca clusters.breaking_at en las noticias activas recientes que cumplen alguna regla."""
    rows = conn.execute(
        """SELECT id FROM clusters
           WHERE status='active' AND breaking_at IS NULL AND first_published >= ?""",
        (now - BREAKING_TTL_S,)).fetchall()
    marked = 0
    for r in rows:
        arts = conn.execute("SELECT source, title, published_at FROM articles WHERE cluster_id=?",
                            (r["id"],)).fetchall()
        labelled = any(is_labelled(a["title"]) and now - a["published_at"] <= LABEL_MAX_AGE_S for a in arts)
        fast = velocity_ok([(a["source"], a["published_at"]) for a in arts])
        if labelled or fast:
            conn.execute("UPDATE clusters SET breaking_at=? WHERE id=?", (now, r["id"]))
            marked += 1
    conn.commit()
    return marked
