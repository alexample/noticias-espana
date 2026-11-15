"""Procesado de texto en español: limpieza, tokens, stemming ligero y entidades.

No usa IA ni librerías externas. Convierte cada artículo en un conjunto de
"rasgos" ponderados que luego el algoritmo de agrupación compara.
"""
import html
import re
import unicodedata
from collections import Counter

STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun aunque bajo bien cada casi
como con contra cual cuales cuando cuanto de del desde donde dos e el ella ellas ello ellos en
entre era eran es esa esas ese eso esos esta estaba estado estan estar estas este esto estos fue
fueron ha habia han hasta hay la las le les lo los mas me mi mientras muy nada ni no nos nosotros
o os otra otras otro otros para pero poco por porque que quien quienes se sea segun ser si sido
sin sino sobre son su sus tal tambien tan tanto te tiene tienen todo todos tras tu un una unas
uno unos usted ya yo hoy ayer manana ahora sera seran puede pueden hace hacer hacen dice dicen
afirma asegura explica pide segun ultima ultimo ultimas ultimos hora horas directo minuto video
videos foto fotos imagenes ano anos dia dias semana mes nuevo nueva nuevos nuevas gran grandes
mejor peor primer primera tres cuatro cinco mil millones vez veces parte tiene tras durante
cuya cuyo donde mismo misma asi sus esta este estos estas aqui alli lunes martes miercoles jueves
viernes sabado domingo enero febrero marzo abril mayo junio julio agosto septiembre octubre
noviembre diciembre leer mas noticia noticias informacion espana espanol espanola
""".split())

# Palabras que aparecen en mayúscula en titulares sin ser entidades útiles.
ENTITY_STOP = STOPWORDS | {"gobierno", "ultima", "directo", "video", "opinion", "editorial", "exclusiva"}

_SUFFIXES = sorted("""
amientos imientos aciones iciones uciones amiento imiento mente acion icion ucion idades idad
ismos ismo istas ista ables ibles able ible adores adoras ador adora ados adas idos idas ado
ada ido ida ando iendo aron ieron aran eran ar er ir es os as s a o e
""".split(), key=len, reverse=True)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")

# Formas largas -> sigla, para que "Banco Central Europeo" y "BCE" coincidan.
ALIASES = {
    "banco central europeo": "bce", "alianza atlantica": "otan", "union europea": "ue",
    "agencia estatal de meteorologia": "aemet", "partido popular": "pp", "partido socialista": "psoe",
    "fondo monetario internacional": "fmi", "reserva federal": "fed", "banco de espana": "bde",
    "tribunal supremo": "supremo", "tribunal constitucional": "constitucional",
    "naciones unidas": "onu", "organizacion mundial de la salud": "oms", "guardia civil": "guardiacivil",
    "policia nacional": "policianacional", "comunidad de madrid": "cam", "generalitat valenciana": "generalitat",
    "comunitat valenciana": "cvalenciana", "comunidad valenciana": "cvalenciana",
    "consejo de ministros": "consejoministros", "seguridad social": "seguridadsocial",
    "presupuestos generales del estado": "presupuestos", "real madrid": "realmadrid",
    "fc barcelona": "barca", "atletico de madrid": "atletico", "estados unidos": "eeuu",
    "casa blanca": "casablanca", "reino unido": "uk", "valencia cf": "valenciacf",
}
_ALIAS_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(ALIASES, key=len, reverse=True)) + r")\b")


# Sinónimos frecuentes en titulares (sobre la raíz ya recortada): distintas
# redacciones del mismo hecho acaban en el mismo rasgo.
_SYNONYM_GROUPS = {
    "baj": "baja bajan bajada rebaja rebajan recorta recortan recorte reduce reducen reduccion",
    "alz": "sube suben subida eleva elevan aumenta aumentan aumento incrementa incremento dispara disparan alza",
    "ces": "destituye destituyen destitucion despide despiden despido cesa cesan cese dimite dimision",
    "muer": "muere mueren muerto muertos muerte fallece fallecen fallecido fallecidos",
    "deten": "detenido detenidos detenida detiene detienen detencion arresta arrestado arrestados",
    "tecnic": "entrenador entrenadores tecnico mister",
    "pact": "acuerdo acuerdan pacto pactan",
    "lluv": "lluvia lluvias precipitaciones",
    "gan": "gana ganan golea goleada vence arrolla",
    "fueg": "incendio incendios fuego",
    "elecc": "elecciones comicios",
}
SYNONYMS = {}  # se rellena tras definir stem()


def apply_aliases(folded):
    return _ALIAS_RE.sub(lambda m: ALIASES[m.group(1)], folded)
_CAP = r"[A-ZÁÉÍÓÚÑÜ][A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9\-]*"
_ENT_RE = re.compile(rf"{_CAP}(?:\s+(?:(?:de|del|la|las|los|el)\s+)?{_CAP})*")
_SENT_START_RE = re.compile(r"(^|[.!?:;¿¡\"«“'\(\[]\s*)$")


def strip_html(text):
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def fold(text):
    """minúsculas y sin tildes."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def stem(word):
    if len(word) <= 4 or word.isdigit():
        return word
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: -len(suf)]
    return word


for _canon, _words in _SYNONYM_GROUPS.items():
    for _w in _words.split():
        SYNONYMS[stem(_w)] = _canon


def tokens(text):
    out = []
    for tok in _TOKEN_RE.findall(apply_aliases(fold(text))):
        tok = tok.replace(",", "").replace(".", "")
        if tok in STOPWORDS:
            continue
        if tok.isdigit():
            # años y cifras sueltas aportan poco salvo cantidades concretas
            if len(tok) < 2:
                continue
        elif len(tok) < 3:
            continue
        st = stem(tok)
        out.append(SYNONYMS.get(st, st))
    return out


def entities(text):
    """Nombres propios y siglas: 'Pedro Sánchez', 'PSOE', 'Banco Central Europeo'."""
    found = set()
    for m in _ENT_RE.finditer(text):
        phrase = m.group(0)
        words = phrase.split()
        is_acronym = len(words) == 1 and phrase.isupper() and len(phrase) >= 2
        at_start = bool(_SENT_START_RE.search(text[: m.start()]))
        if at_start and len(words) == 1 and not is_acronym:
            continue  # primera palabra de frase: suele ser mayúscula gramatical
        if at_start and len(words) > 1 and apply_aliases(fold(phrase)) not in ALIASES.values():
            words = words[1:]  # "Lesión de Courtois" -> "Courtois"; "Real Madrid" se conserva
            while words and fold(words[0]) in ("de", "del", "la", "las", "los", "el"):
                words = words[1:]
        content = [fold(w) for w in words if fold(w) not in ENTITY_STOP and fold(w) not in ("de", "del", "y")]
        if not content:
            continue
        full = apply_aliases(fold(" ".join(words)))
        if full in ALIASES.values():
            found.add(full)  # la frase entera es una sigla conocida: no se trocea
            continue
        for w in content:
            if len(w) >= 2:
                found.add(w)
        if len(content) > 1:
            joined = " ".join(content)
            found.add(ALIASES.get(joined, joined))
            for alias in ALIASES.values():
                if re.search(rf"\b{alias}\b", full):
                    found.add(alias)
        elif content[0] in ALIASES.values():
            found.add(content[0])
    return found


def article_features(title, summary):
    """Devuelve (rasgos ponderados, entidades) de un artículo.

    - tokens del titular pesan más que los del resumen
    - entidades (nombres propios, siglas) pesan aún más
    - bigramas del titular capturan expresiones ("prima riesgo", "ley amnistia")
    """
    summary = (summary or "")[:700]
    feats = Counter()
    t_toks = tokens(title)
    for tok in t_toks:
        feats[tok] += 2.5
    for tok in tokens(summary):
        feats[tok] += 1.0
    for a, b in zip(t_toks, t_toks[1:]):
        feats[f"b:{a}_{b}"] += 1.5
    t_ents = entities(title)
    s_ents = entities(summary)
    for e in t_ents:
        feats[f"e:{e}"] += 2.0
    for e in s_ents:
        feats[f"e:{e}"] += 1.0
    return dict(feats), sorted(t_ents | s_ents)
