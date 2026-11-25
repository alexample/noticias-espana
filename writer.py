"""Redacción de la noticia con IA. Es la ÚNICA parte del sistema que usa IA.

Recibe los titulares/entradillas que han publicado los distintos medios sobre
una misma noticia (ya agrupados por el algoritmo) y redacta un texto neutral.
Si no hay ANTHROPIC_API_KEY, se usa el titular del artículo más representativo.
"""
import json
import time
import urllib.error
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

Redacta la noticia. Si algún medio solo aporta el titular, redacta igualmente con lo que dicen los titulares (el cuerpo puede ser más breve, de 1-2 párrafos). Devuelve SIEMPRE y SOLO un objeto JSON válido con estas claves:
- "etiqueta": el tema en 1-3 palabras, como lo rotularía una portada (p. ej. "DANA Valencia", "Presupuestos 2027", "Cumbre OTAN"). Sin verbos ni artículos.
- "titular": máximo 14 palabras, informativo, sin clickbait.
- "entradilla": 1-2 frases con lo esencial (qué, quién, cuándo, dónde).
- "cuerpo": 2-4 párrafos breves separados por "\\n\\n". Incluye la evolución de la noticia si los artículos más recientes aportan novedades, y atribuye los datos al medio que los publica cuando sea relevante.{novedad}
"""

NOVEDAD = """
- "novedad": una sola frase (máximo 25 palabras) con lo que ha cambiado respecto a la versión anterior: hechos, datos o reacciones nuevas. Si no hay nada sustancial, devuelve "".

Versión anterior publicada ({at}):
Titular: {headline}
Entradilla: {lead}"""


def _fmt_sources(articles):
    lines = []
    for a in articles:
        ts = datetime.fromtimestamp(a["published_at"], tz=timezone.utc).strftime("%d/%m %H:%M UTC")
        summary = (a["summary"] or "").strip()[:500] or "(no disponible: usa solo el titular)"
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


def _post(payload):
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(), method="POST", headers={
        "content-type": "application/json",
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from None


def call_claude(prompt, system, max_tokens=2000):
    payload = {
        "model": config.AI_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        # Redactar a partir de titulares no necesita razonamiento: sin "thinking" y con
        # esfuerzo bajo la respuesta es más rápida, más barata y no agota max_tokens pensando.
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "low"},
    }
    try:
        data = _post(payload)
    except RuntimeError as e:
        if not str(e).startswith("HTTP 400"):
            raise
        # modelo que no admite esas opciones: se reintenta con la petición básica
        payload.pop("thinking"); payload.pop("output_config")
        payload["max_tokens"] = 4000
        data = _post(payload)
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if not text.strip():
        kinds = [b.get("type") for b in data.get("content", [])]
        raise ValueError(f"Respuesta sin texto (stop_reason={data.get('stop_reason')}, bloques={kinds})")
    return text


def _parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"La respuesta no contiene JSON: {text[:200]!r}")
    obj = json.loads(text[start:end + 1], strict=False)  # tolera saltos de línea dentro de cadenas
    for k in ("titular", "entradilla", "cuerpo"):
        if not isinstance(obj.get(k), str) or not obj[k].strip():
            raise ValueError(f"Falta la clave {k}")
    return obj


def _fmt_foreign(foreign):
    if not foreign:
        return ""
    lines = [f"[{f['source']} · {f['country'].upper()}] {f['title']}" for f in foreign]
    return ("\n\nTitulares de la prensa del país implicado (en su idioma original; úsalos solo para contrastar "
            "y, si aportan algo, menciona cómo lo cuenta esa prensa):\n" + "\n".join(lines))


def write_story(articles, foreign=None, previous=None):
    """articles: lista de dicts (source, title, summary, published_at).
    previous: dict(headline, lead, at) de la versión anterior, si la hay; en la misma
    llamada se pide una frase con la novedad, sin gastar otra petición.
    Devuelve dict(headline, lead, body, tag, note)."""
    picked = _pick_articles(articles, config.AI_MAX_SOURCES_IN_PROMPT)
    novedad = ""
    if previous and previous.get("headline"):
        at = datetime.fromtimestamp(previous["at"] or 0, tz=timezone.utc).strftime("%d/%m %H:%M UTC")
        novedad = NOVEDAD.format(at=at, headline=previous["headline"], lead=previous.get("lead") or "")
    prompt = PROMPT.format(sources=_fmt_sources(picked) + _fmt_foreign(foreign), novedad=novedad)
    last_err = None
    for attempt in range(2):
        try:
            obj = _parse_json(call_claude(prompt, SYSTEM))
            tag = obj.get("etiqueta") if isinstance(obj.get("etiqueta"), str) else ""
            note = obj.get("novedad") if isinstance(obj.get("novedad"), str) else ""
            return {"headline": obj["titular"].strip(), "lead": obj["entradilla"].strip(),
                    "body": obj["cuerpo"].strip(), "tag": tag.strip().strip(".")[:40] or None,
                    "note": note.strip()[:300] or None}
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise last_err


def ai_enabled():
    return bool(config.ANTHROPIC_API_KEY)


READERS_SYSTEM = (
    "Resumes de forma neutral lo que opinan los lectores en los comentarios de una noticia. "
    "Describes las corrientes de opinión y su peso aproximado (la mayoría, una parte, algunos), "
    "nunca como hechos ni como la postura de DobleCheck. No citas comentarios literalmente, no nombras "
    "a nadie, no reproduces insultos ni expresiones de odio, e ignoras el spam y los comentarios "
    "que no hablan de la noticia. Escribes en español de España."
)

READERS_PROMPT = """Noticia: {headline}

Comentarios de lectores en vídeos de YouTube de {channels}. Van mezclados por turnos entre canales, los más valorados de cada uno primero; entre corchetes, el canal. Puede haber ruido:
{comments}

Resume en 2-3 frases (máximo 70 palabras) qué opinan los lectores. Si las opiniones están muy divididas, dilo. Si los comentarios de un canal se inclinan claramente hacia una postura distinta de los de otro, tenlo en cuenta y no la presentes como la opinión general (puedes decir, por ejemplo, que en un canal predomina una postura y en otro la contraria). Devuelve SOLO un JSON: {{"resumen": "..."}}"""


def summarize_readers(headline, comments):
    """Resumen de lo que opinan los lectores (comentarios de YouTube).
    comments: [(canal, texto)] o [texto]. Devuelve el texto del resumen."""
    pairs = [c if isinstance(c, tuple) else ("YouTube", c) for c in comments]
    channels = list(dict.fromkeys(ch for ch, _ in pairs))
    lines = "\n".join(f"- [{ch}] {t.strip()[:300]}" for ch, t in pairs if t.strip())
    names = ", ".join(channels[:-1]) + " y " + channels[-1] if len(channels) > 1 else (channels[0] if channels else "medios")
    text = call_claude(READERS_PROMPT.format(headline=headline, comments=lines, channels=names),
                       READERS_SYSTEM, max_tokens=400)
    start, end = text.find("{"), text.rfind("}")
    obj = json.loads(text[start:end + 1], strict=False)
    summary = (obj.get("resumen") or "").strip()
    if not summary:
        raise ValueError("Resumen vacío")
    return summary[:600]
