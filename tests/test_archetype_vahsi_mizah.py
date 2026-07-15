"""vahsi-mizah görsel arketip girişi (config/archetypes.json)."""
import json


def _arketipler():
    return json.load(open("config/archetypes.json", encoding="utf-8"))


def test_vahsi_mizah_arketibi_var():
    slugs = [a["slug"] for a in _arketipler()]
    assert "vahsi-mizah" in slugs


def test_vahsi_mizah_defaults_gecerli():
    a = next(x for x in _arketipler() if x["slug"] == "vahsi-mizah")
    assert a["defaults"]["colors"]["primary"].startswith("#")
    assert len(a["pexels_queries"]) >= 2
