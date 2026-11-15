import os
import random
import sys
import unittest
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clustering import Corpus, Matcher, vectorize  # noqa: E402
from textproc import article_features, entities  # noqa: E402
from tests.fixtures_data import STORIES  # noqa: E402


def run(items, seed=0, threshold=0.24):
    feats = [article_features(t, s) for _, _, t, s in items]
    corpus = Corpus()
    for f, _ in feats:
        corpus.add(f)
    m = Matcher(join_threshold=threshold, merge_threshold=0.50)
    counter = iter(range(1, 10_000))
    assign = {}
    for i, ((label, src, _, _), (f, ents)) in enumerate(zip(items, feats)):
        cl, score, _ = m.assign(i, vectorize(f, corpus), ents, src, 1_000_000 + i * 60, lambda: next(counter))
        assign[i] = cl.id
    merges = dict(m.merge_pass())

    def final(cid):
        while cid in merges:
            cid = merges[cid]
        return cid

    groups = defaultdict(set)
    for i, cid in assign.items():
        groups[final(cid)].add(items[i][0])
    by_label = defaultdict(set)
    for i, cid in assign.items():
        by_label[items[i][0]].add(final(cid))
    return groups, by_label


def all_items():
    return [(label, src, t, s) for label, arts in STORIES.items() for src, t, s in arts]


class TestClustering(unittest.TestCase):
    def check(self, items):
        groups, by_label = run(items)
        impure = {cid: labels for cid, labels in groups.items() if len(labels) > 1}
        split = {label: cids for label, cids in by_label.items() if len(cids) > 1}
        self.assertFalse(impure, f"Noticias mezcladas: {impure}")
        self.assertFalse(split, f"Noticias partidas: {split}")

    def test_orden_original(self):
        self.check(all_items())

    def test_orden_aleatorio(self):
        for seed in range(20):
            items = all_items()
            random.Random(seed).shuffle(items)
            with self.subTest(seed=seed):
                self.check(items)

    def test_entidades(self):
        ents = entities("Sánchez viaja a Bruselas para la cumbre de la OTAN con Pedro Sánchez")
        self.assertIn("otan", ents)
        self.assertIn("bruselas", ents)
        self.assertIn("pedro sanchez", ents)


if __name__ == "__main__":
    unittest.main(verbosity=2)
