import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import writer  # noqa: E402
from export import build_timeline  # noqa: E402

T0 = 1_800_000_000
ARTS = [  # (minuto, medio, titular)
    (0, "El País", "La Aemet activa la alerta roja en Valencia"),
    (10, "El Mundo", "Alerta roja en Valencia por lluvias"),
    (95, "RTVE", "Suspendidas las clases en la Ribera"),
    (100, "ABC", "Colegios cerrados en Valencia"),
    (240, "El País", "Primeras inundaciones en Algemesí"),       # mismo medio, información nueva
]


def arts():
    return [{"published_at": T0 + m * 60, "source": s, "title": t} for m, s, t in ARTS]


class TestTimeline(unittest.TestCase):
    def test_eventos_sin_ia(self):
        ev = build_timeline(arts())
        kinds = [(e["kind"], e.get("first"), e.get("sources"), e.get("follow")) for e in reversed(ev)]
        self.assertEqual(kinds, [
            ("media", True, ["El País", "El Mundo"], []),
            ("media", False, ["RTVE", "ABC"], []),
            ("media", False, [], ["El País"]),
        ])
        self.assertEqual(ev[-1]["title"], "La Aemet activa la alerta roja en Valencia")
        self.assertEqual(ev[0]["title"], "Primeras inundaciones en Algemesí")

    def test_actualizaciones_ia_e_internacional(self):
        updates = [
            {"at": T0 + 20 * 60, "headline": "v1", "lead": "", "note": None, "n_sources": 2},
            {"at": T0 + 110 * 60, "headline": "v2", "lead": "", "note": "Se suspenden las clases en la Ribera.", "n_sources": 4},
            {"at": T0 + 250 * 60, "headline": "v3", "lead": "", "note": None, "n_sources": 4},  # sin novedad: no sale
        ]
        foreign = [{"country": "us", "fetched_at": T0 + 130 * 60}, {"country": "us", "fetched_at": T0 + 140 * 60}]
        ev = build_timeline(arts(), updates, foreign, {"us": {"name": "Estados Unidos", "flag": "🇺🇸"}})
        ai = [e for e in ev if e["kind"] == "ai"]
        self.assertEqual([e["first"] for e in ai], [False, True])
        self.assertEqual(ai[0]["note"], "Se suspenden las clases en la Ribera.")
        intl = [e for e in ev if e["kind"] == "intl"]
        self.assertEqual((intl[0]["count"], intl[0]["at"]), (2, T0 + 130 * 60))
        self.assertEqual([e["at"] for e in ev], sorted([e["at"] for e in ev], reverse=True))

    def test_prompt_pide_novedad_solo_si_hay_version_anterior(self):
        prompts = []
        self.addCleanup(setattr, writer, "call_claude", writer.call_claude)
        writer.call_claude = lambda p, s, max_tokens=2000: (prompts.append(p) or
            '{"titular":"T","entradilla":"E","cuerpo":"C","novedad":"Nuevo dato."}')
        a = [{"source": "El País", "title": "x", "summary": "y", "published_at": T0}]
        first = writer.write_story(a)
        self.assertNotIn('"novedad"', prompts[0])
        second = writer.write_story(a, previous={"headline": "Antes", "lead": "L", "at": T0})
        self.assertIn("Versión anterior", prompts[1])
        self.assertIn("Antes", prompts[1])
        self.assertEqual(second["note"], "Nuevo dato.")
        self.assertEqual(first["headline"], "T")


if __name__ == "__main__":
    unittest.main(verbosity=2)
