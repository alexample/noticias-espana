"""Cobertura internacional, sin IA.

Cuando una noticia trata de otro país (Estados Unidos, Alemania, Francia…):
  1. Se detecta el país contando en cuántos artículos españoles aparece
     (nombre, gentilicio, capital, dirigentes…; ver countries.json).
  2. Se eligen 2-3 nombres propios de la noticia que se escriben igual en
     cualquier idioma (Trump, Merz, Volkswagen…) y las siglas se traducen
     (OTAN -> NATO, UE -> EU…).
  3. Se buscan en la edición de Google Noticias de ese país y solo se aceptan
     titulares que contengan esos nombres.
"""
import json
import logging
import math
import re
import time
import urllib.parse
from collections import Counter

import config
import feeds
from textproc import ALIASES, ENTITY_STOP, apply_aliases, fold

log = logging.getLogger("intl")

GNEWS = "https://news.google.com/rss/search?q={q}+when:2d&{edition}"

# Siglas/alias españoles -> como se escriben en cada idioma.
TRANSLATE = {
    "otan": {"en": "NATO", "de": "NATO", "fr": "OTAN", "it": "NATO", "pt": "NATO", "es": "OTAN"},
    "ue": {"en": "EU", "de": "EU", "fr": "UE", "it": "UE", "pt": "UE", "es": "UE"},
    "onu": {"en": "UN", "de": "UNO", "fr": "ONU", "it": "ONU", "pt": "ONU", "es": "ONU"},
    "oms": {"en": "WHO", "de": "WHO", "fr": "OMS", "it": "OMS", "pt": "OMS", "es": "OMS"},
    "fmi": {"en": "IMF", "de": "IWF", "fr": "FMI", "it": "FMI", "pt": "FMI", "es": "FMI"},
    "bce": {"en": "ECB", "de": "EZB", "fr": "BCE", "it": "BCE", "pt": "BCE", "es": "BCE"},
    "fed": "Fed",
    "realmadrid": "Real Madrid",
    "barca": "Barcelona",
    "atletico": "Atletico Madrid",
    "casablanca": {"en": "White House", "de": "Weißes Haus", "fr": "Maison Blanche",
                   "it": "Casa Bianca", "pt": "Casa Branca", "es": "Casa Blanca"},
}

# Palabras españolas que, dentro de un nombre propio, no sirven para buscar en otro idioma.
SPANISH_COMMON = set("""
gobierno ministerio ministro ministra presidente presidenta congreso senado tribunal partido comision consejo
union nacional central banco ayuntamiento junta estado estados policia guardia ejercito fuerzas aerea armada
oficina agencia instituto universidad hospital camara parlamento justicia defensa exteriores interior hacienda
economia sanidad educacion trabajo vivienda transportes elecciones liga copa mundial selecciona seleccion
norte sur este oeste reino republica real casa blanca rey reina papa iglesia cumbre acuerdo plan ley
""".split())


def load_countries(path=None):
    with open(path or config.COUNTRIES_FILE, encoding="utf-8") as f:
        data = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    for c in data.values():
        words = [apply_aliases(fold(t)) for t in c.get("terms", []) + c.get("names", [])]
        c["_re"] = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)) + r")\b")
        c["_names"] = {apply_aliases(fold(n)) for n in c.get("names", [])}
    return data


def _spanish_country_words(countries):
    out = set()
    for c in countries.values():
        for t in c.get("terms", []):
            out.update(apply_aliases(fold(t)).split())
    return out


def detect_countries(texts, countries, max_countries=2):
    """texts: un texto por artículo. Devuelve códigos de país, del más mencionado al menos."""
    n = len(texts)
    if not n:
        return []
    folded = [apply_aliases(fold(t)) for t in texts]
    need = max(2, math.ceil(0.4 * n))
    hits = []
    for code, c in countries.items():
        k = sum(1 for t in folded if c["_re"].search(t))
        if k >= need:
            hits.append((k, code))
    hits.sort(reverse=True)
    return [code for _, code in hits[:max_countries]]


def search_terms(entity_lists, lang, countries, max_terms=3, texts=None):
    """Nombres propios de la noticia útiles para buscar en `lang`, de más a menos frecuentes.

    Si se pasan los textos, cada nombre se cuenta en todos los artículos donde aparece,
    aunque en alguno no se detectara como entidad (p. ej. "Trump anuncia…" al inicio
    del titular). Los dirigentes de countries.json se buscan siempre."""
    n = len(entity_lists)
    names_all = set().union(*(c["_names"] for c in countries.values()))
    if texts:
        folded = [apply_aliases(fold(t)) for t in texts]
        vocab = {e for ents in entity_lists for e in ents} | names_all
        counts = Counter()
        for e in vocab:
            rx = re.compile(r"\b" + re.escape(e) + r"\b")
            k = sum(1 for t in folded if rx.search(t))
            if k:
                counts[e] = k
    else:
        counts = Counter(e for ents in entity_lists for e in set(ents))
    min_count = max(2, math.ceil(0.3 * n)) if n >= 3 else 1
    country_words = _spanish_country_words(countries)
    names = names_all
    spanish_aliases = set(ALIASES.values()) - set(TRANSLATE)
    cands = []
    for e, k in counts.items():
        if k < min_count:
            continue
        if e in TRANSLATE:
            t = TRANSLATE[e]
            term = t if isinstance(t, str) else t.get(lang)
        elif e in spanish_aliases:
            continue
        else:
            words = e.split()
            if e not in names and any(w in SPANISH_COMMON or w in ENTITY_STOP or w in country_words for w in words):
                continue
            if len(e) < 3:
                continue
            term = e
        if term:
            cands.append((k, len(term.split()), term))
    cands.sort(key=lambda x: (-x[0], -x[1], x[2]))
    chosen = []
    for _, _, term in cands:
        tw = set(fold(term).split())
        if any(tw <= set(fold(c).split()) or set(fold(c).split()) <= tw for c in chosen):
            continue  # "sanchez" ya está dentro de "pedro sanchez" (o al revés)
        chosen.append(term)
        if len(chosen) == max_terms:
            break
    return chosen


def _query(terms):
    return " ".join(f'"{t}"' if " " in t else t for t in terms)


def _matches(title, terms, need):
    t = fold(title)
    return sum(1 for term in terms if re.search(r"\b" + re.escape(fold(term)) + r"\b", t)) >= need


def search_country(country, terms, fetch=feeds.fetch, limit=None):
    """Busca en la edición de Google Noticias del país. Devuelve [(source, title, url, published)]."""
    limit = limit or config.INTL_MAX_PER_COUNTRY
    attempts = [terms[:3]] + ([terms[:2]] if len(terms) > 2 else [])
    for q_terms in attempts:
        url = GNEWS.format(q=urllib.parse.quote(_query(q_terms)), edition=country["gnews"])
        status, body, _, _ = fetch(url)
        if not body:
            continue
        out, seen_sources = [], set()
        for it in feeds.parse(body):
            title, source = it["title"], ""
            if " - " in title:
                title, source = [x.strip() for x in title.rsplit(" - ", 1)]
            if not source or source in seen_sources:
                continue  # un artículo por medio
            if not _matches(title, q_terms, need=min(2, len(q_terms))):
                continue
            seen_sources.add(source)
            out.append((source, title, it["url"], it["published"] or time.time()))
            if len(out) >= limit:
                break
        if out:
            return out
        time.sleep(1)
    return []


def process(conn, now, fetch=feeds.fetch, countries=None):
    """Busca cobertura internacional para las noticias relevantes que lo necesiten."""
    if not config.INTL_ENABLED:
        return 0
    countries = countries or load_countries()
    rows = conn.execute(
        """SELECT id FROM clusters
           WHERE status='active' AND n_sources >= ? AND last_published >= ?
             AND (intl_checked_at IS NULL OR intl_checked_at < ?)
           ORDER BY relevance DESC LIMIT ?""",
        (config.INTL_MIN_SOURCES, now - 24 * 3600, now - config.INTL_RECHECK_MIN * 60,
         config.INTL_MAX_PER_CYCLE)).fetchall()
    added = 0
    for row in rows:
        cid = row["id"]
        arts = conn.execute("SELECT title, summary, entities FROM articles WHERE cluster_id=?", (cid,)).fetchall()
        texts = [f"{a['title']}. {a['summary'] or ''}" for a in arts]
        codes = detect_countries(texts, countries)
        ok = True
        for code in codes:
            c = countries[code]
            terms = search_terms([json.loads(a["entities"]) for a in arts], c["lang"], countries, texts=texts)
            if len(terms) < 2:
                continue  # con un solo nombre la búsqueda sería demasiado imprecisa
            try:
                results = search_country(c, terms, fetch)
            except Exception as e:
                log.warning("Google Noticias %s falló para noticia %s: %s", code, cid, e)
                ok = False
                continue
            for source, title, url, pub in results:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO intl_articles(cluster_id, country, source, title, url, published_at, fetched_at)
                       VALUES (?,?,?,?,?,?,?)""", (cid, code, source, title, url, pub, now))
                added += cur.rowcount
            log.info("Noticia %s · %s · %s -> %d artículos", cid, code, terms, len(results))
            time.sleep(1)
        # si Google falló, se reintenta en 15 min en vez de esperar la hora entera
        checked = now if ok else now - (config.INTL_RECHECK_MIN - 15) * 60
        conn.execute("UPDATE clusters SET intl_countries=?, intl_checked_at=? WHERE id=?",
                     (json.dumps(codes), checked, cid))
        conn.commit()
    return added
