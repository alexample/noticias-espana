"""Redacción de la noticia con IA. Es la ÚNICA parte del sistema que usa IA.

Recibe los titulares/entradillas que han publicado los distintos medios sobre
una misma noticia (ya agrupados por el algoritmo) y redacta un texto neutral.
Si no hay ANTHROPIC_API_KEY, se usa el titular del artículo más representativo.
"""
import json
import time
import urllib.request
from datetime import datetime, timezone

import config

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = (
    "Eres redactor de una agencia de noticias española. Escribes en español de España, "
    "con tono neutral, preciso y sin adjetivos valorativos. Solo puedes usar los hechos que "
    "aparecen en los extractos de medios que se te dan: no inventes datos, cifras, citas ni "
    "contexto. Si los medios discrepan en algún dato, indícalo atribuyendo cada versión a su "
    "medio. No reproduzcas frases literales de los medios salvo citas breves entre comillas."
)

PROMPT = """Estos son los artículos que distintos medios han publicado sobre la misma noticia, ordenados del más antiguo al más reciente:

{sources}

Redacta la noticia. Devuelve SOLO un objeto JSON válido con estas claves:
- "titular": máximo 14 palabras, informativo, sin clickbait.
- "entradilla": 1-2 frases con lo esencial (qué, quién, cuándo, dónde).
- "cuerpo": 2-4 párrafos breves separados por "\\n\\n". Incluye la evolución de la noticia si los artículos más recientes aportan novedades, y atribuye los datos al medio que los publica cuando sea relevante.
"""


def _fmt_sources(articles):
    lines = []
    for a in articles:
        ts = datetime.fromtimestamp(a["published_at"], tz=timezone.utc).strftime("%d/%m %H:%M UTC")
        summary = (a["summary"] or "").strip()[:500]
        lines.append(f"[{a['source']} · {ts}]\nTitular: {a['title']}\nExtracto: {summary}")
    return "\n\n".join(lines)


def _pick_articles(articles, limit):
    """Un artículo por medio (el más reciente) para no sesgar, ordenados por fecha."""
    by_source = {}
    for a in sorted(articles, key=lambda x: x["published_at"]):
        by_source[a["source"]] = a
    picked = sorted(by_source.values(), key=lambda x: x["published_at"])
    if len(picked) > limit:
        picked = picked[:3] + picked[-(limit - 3):]  # origen + lo más reciente
    return picked


def call_claude(prompt, system, max_tokens=1200):
    body = json.dumps({
        "model": config.AI_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("La respuesta no contiene JSON")
    obj = json.loads(text[start:end + 1])
    for k in ("titular", "entradilla", "cuerpo"):
        if not isinstance(obj.get(k), str) or not obj[k].strip():
            raise ValueError(f"Falta la clave {k}")
    return obj


def write_story(articles):
    """articles: lista de dicts (source, title, summary, published_at).
    Devuelve dict(headline, lead, body)."""
    picked = _pick_articles(articles, config.AI_MAX_SOURCES_IN_PROMPT)
    prompt = PROMPT.format(sources=_fmt_sources(picked))
    last_err = None
    for attempt in range(2):
        try:
            obj = _parse_json(call_claude(prompt, SYSTEM))
            return {"headline": obj["titular"].strip(), "lead": obj["entradilla"].strip(),
                    "body": obj["cuerpo"].strip()}
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise last_err


def ai_enabled():
    return bool(config.ANTHROPIC_API_KEY)
