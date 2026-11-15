"""Algoritmo que decide si un artículo es una noticia nueva o pertenece a una existente.

Para cada artículo nuevo:
  1. Se convierte en un vector TF-IDF (rasgos de textproc + frecuencias del corpus reciente).
  2. Se compara con todas las noticias activas mediante tres señales:
       - coseno con el centroide de la noticia        (de qué trata la noticia en conjunto)
       - coseno máximo con cualquiera de sus artículos (enlaza con la versión más parecida)
       - solape de entidades (personas, organizaciones, lugares recurrentes)
  3. Si la mejor puntuación supera el umbral, se añade a esa noticia; si no, se crea una nueva.
Tras procesar el lote, se fusionan noticias que hayan acabado siendo la misma.
"""
import math
from collections import Counter


class Corpus:
    """Frecuencia documental de cada rasgo en la ventana reciente (para el IDF)."""

    def __init__(self):
        self.df = Counter()
        self.n = 0

    def add(self, features):
        self.n += 1
        self.df.update(features.keys())

    def idf(self, term):
        return math.log((self.n + 1) / (self.df.get(term, 0) + 1)) + 1.0


def vectorize(features, corpus):
    vec = {t: (1.0 + math.log(w)) * corpus.idf(t) if w >= 1 else w * corpus.idf(t)
           for t, w in features.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


class Cluster:
    def __init__(self, cid):
        self.id = cid
        self.sum = Counter()
        self.members = []          # (article_id, vector)
        self.entities = Counter()
        self.sources = set()
        self.first_time = None
        self.last_time = None
        self._centroid = None
        self.touched = False
        self.merged_into = None

    def add(self, art_id, vec, ents, source, ts):
        self.members.append((art_id, vec))
        self.sum.update(vec)
        self.entities.update(set(ents))
        self.sources.add(source)
        self.first_time = ts if self.first_time is None else min(self.first_time, ts)
        self.last_time = ts if self.last_time is None else max(self.last_time, ts)
        self._centroid = None

    @property
    def centroid(self):
        if self._centroid is None:
            norm = math.sqrt(sum(v * v for v in self.sum.values())) or 1.0
            self._centroid = {t: v / norm for t, v in self.sum.items()}
        return self._centroid

    def core_entities(self):
        """Entidades que aparecen en al menos ~25% de los artículos."""
        n = len(self.members)
        min_count = max(1, math.ceil(0.25 * n)) if n >= 4 else 1
        return {e for e, c in self.entities.items() if c >= min_count}

    def representative(self):
        """Artículo más cercano al centroide."""
        c = self.centroid
        return max(self.members, key=lambda m: cosine(m[1], c))[0]


class Matcher:
    def __init__(self, join_threshold=0.24, merge_threshold=0.50, active_hours=72):
        self.join_threshold = join_threshold
        self.merge_threshold = merge_threshold
        self.active_s = active_hours * 3600
        self.clusters = {}

    def score(self, vec, ents, ts, cluster):
        if cluster.merged_into is not None:
            return 0.0
        gap = ts - (cluster.last_time or ts)
        if gap > self.active_s:
            return 0.0
        c = cosine(vec, cluster.centroid)
        m = max(cosine(vec, mv) for _, mv in cluster.members[-40:])
        if c < 0.10 and m < 0.20:
            return 0.0  # sin vocabulario común: compartir un nombre propio no basta
        ents = set(ents)
        core = cluster.core_entities()
        if ents and core:
            shared = len(ents & core)
            e = shared / max(2, min(len(ents), len(core)))
            e = min(1.0, e)
        else:
            e = 0.0
        s = 0.45 * c + 0.35 * m + 0.20 * e
        if gap > 24 * 3600:
            s *= 0.85  # noticias viejas atraen menos
        return s

    def best_match(self, vec, ents, ts):
        best, best_s = None, 0.0
        for cl in self.clusters.values():
            s = self.score(vec, ents, ts, cl)
            if s > best_s:
                best, best_s = cl, s
        return best, best_s

    def assign(self, art_id, vec, ents, source, ts, new_cluster_id):
        """Devuelve (cluster, score, es_nueva)."""
        best, s = self.best_match(vec, ents, ts)
        if best is not None and s >= self.join_threshold:
            best.add(art_id, vec, ents, source, ts)
            best.touched = True
            return best, s, False
        cl = Cluster(new_cluster_id())
        cl.add(art_id, vec, ents, source, ts)
        cl.touched = True
        self.clusters[cl.id] = cl
        return cl, 1.0, True

    def merge_pass(self):
        """Fusiona noticias tocadas en este ciclo con otras muy parecidas.

        Devuelve lista de (origen, destino). El destino es la noticia más antigua
        con más artículos, para conservar su identidad (URL estable en la web)."""
        merges = []
        touched = [c for c in self.clusters.values() if c.touched and c.merged_into is None]
        for a in touched:
            if a.merged_into is not None:
                continue
            for b in list(self.clusters.values()):
                if b is a or b.merged_into is not None:
                    continue
                if abs((a.last_time or 0) - (b.last_time or 0)) > self.active_s:
                    continue
                sim = cosine(a.centroid, b.centroid)
                if sim < self.merge_threshold:
                    continue
                dst, src = (a, b) if (len(a.members), -a.id) >= (len(b.members), -b.id) else (b, a)
                for art_id, vec in src.members:
                    dst.members.append((art_id, vec))
                dst.sum.update(src.sum)
                dst.entities.update(src.entities)
                dst.sources |= src.sources
                dst.first_time = min(dst.first_time, src.first_time)
                dst.last_time = max(dst.last_time, src.last_time)
                dst._centroid = None
                dst.touched = True
                src.merged_into = dst.id
                merges.append((src.id, dst.id))
                if src is a:
                    break
        return merges
