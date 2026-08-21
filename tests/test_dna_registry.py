"""Tasarlanan arketiplerin kaydı — `config/archetypes.json`.

CANLI ARIZA (2026-08-21): arketip tasarımı ilk kez uçtan uca koşunca üç ayrı
kırık ortaya çıktı ve üçü de kanalı KULLANILAMAZ hâle getiriyordu:

1. `_kayit_ekle` `Path("config/archetypes.json")` yazıyor (CWD'ye göre), ama
   `dna.py` `<src>/../../config/archetypes.json` okuyor (dosyaya göre). CWD
   depo kökü değilse iki AYRI dosya.
2. Kayıt IMPORT ANINDA okunuyor → yeni arketip panel yeniden başlatılana kadar
   geçersiz. Kanalın YAML'ına yazılıyor ama `load_channel` reddediyor:
   "unknown archetype: 'bayern-m-nih'".
3. `_kayit_ekle` `"defaults": {}` yazıyor; `_designed_to_default` bunu açarken
   `KeyError: 'colors'` atıyor → sonraki açılışta `dna.py` IMPORT EDİLEMİYOR,
   yani PANEL AÇILMIYOR.
"""
from __future__ import annotations

import json

import pytest


def test_EKSIK_defaults_modulu_kirmaz():
    """Bozuk tek kayıt bütün paneli düşürmemeli."""
    from short_bot.dna import _designed_to_default
    d = _designed_to_default({"slug": "x", "label": "X", "defaults": {}})
    assert d["primary"].startswith("#") and d["accent"].startswith("#")


def test_YARIM_defaults_modulu_kirmaz():
    from short_bot.dna import _designed_to_default
    d = _designed_to_default({"slug": "x", "defaults": {"colors": {"primary": "#123456"}}})
    assert d["primary"] == "#123456"
    assert d["accent"].startswith("#")


def test_kayit_ANINDA_gecerli_olur(tmp_path, monkeypatch):
    """Yeniden başlatma beklemeden: kanal YAML'ı hemen yazılıyor."""
    import short_bot.dna as dna
    yol = tmp_path / "archetypes.json"
    yol.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(dna, "_REGISTRY_PATH", yol)
    monkeypatch.setattr(dna, "ARCHETYPES", list(dna.ARCHETYPES))
    monkeypatch.setattr(dna, "ARCHETYPE_LABELS", dict(dna.ARCHETYPE_LABELS))
    monkeypatch.setattr(dna, "ARCHETYPE_DEFAULTS", dict(dna.ARCHETYPE_DEFAULTS))
    monkeypatch.setattr(dna, "_DESIGNED_ARCHETYPES", list(dna._DESIGNED_ARCHETYPES))

    dna.register_designed_archetype("bayern-munih", "Bayern Münih")
    assert "bayern-munih" in dna.ARCHETYPES
    assert dna.ARCHETYPE_LABELS["bayern-munih"] == "Bayern Münih"
    assert "bayern-munih" in dna.ARCHETYPE_DEFAULTS
    kayit = json.loads(yol.read_text(encoding="utf-8"))
    assert [k["slug"] for k in kayit] == ["bayern-munih"]


def test_kayit_DNANIN_OKUDUGU_dosyaya_yazilir(tmp_path, monkeypatch):
    """CWD'ye göre yazıp dosyaya göre okumak iki ayrı dosya demekti."""
    import short_bot.dna as dna
    from short_bot.archetype_design import _kayit_ekle
    yol = tmp_path / "archetypes.json"
    yol.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(dna, "_REGISTRY_PATH", yol)
    for ad in ("ARCHETYPES", "ARCHETYPE_LABELS", "ARCHETYPE_DEFAULTS",
               "_DESIGNED_ARCHETYPES"):
        monkeypatch.setattr(dna, ad, type(getattr(dna, ad))(getattr(dna, ad)))
    monkeypatch.chdir(tmp_path / "..")     # CWD kasten farklı
    _kayit_ekle("yeni-kalip", "Yeni Kalıp")
    assert json.loads(yol.read_text(encoding="utf-8"))[0]["slug"] == "yeni-kalip"


def test_ayni_slug_IKI_KEZ_eklenmez(tmp_path, monkeypatch):
    import short_bot.dna as dna
    yol = tmp_path / "archetypes.json"
    yol.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(dna, "_REGISTRY_PATH", yol)
    for ad in ("ARCHETYPES", "ARCHETYPE_LABELS", "ARCHETYPE_DEFAULTS",
               "_DESIGNED_ARCHETYPES"):
        monkeypatch.setattr(dna, ad, type(getattr(dna, ad))(getattr(dna, ad)))
    dna.register_designed_archetype("tek", "Tek")
    dna.register_designed_archetype("tek", "Tek")
    assert len(json.loads(yol.read_text(encoding="utf-8"))) == 1
    assert dna.ARCHETYPES.count("tek") == 1


def test_DEPODAKI_kayit_dosyasi_okunabilir():
    """Gerçek `config/archetypes.json` hâlâ import edilebilir olmalı."""
    from pathlib import Path
    p = Path("config/archetypes.json")
    if not p.exists():
        pytest.skip("config takipsiz olabilir")
    from short_bot.dna import _designed_to_default
    for k in json.loads(p.read_text(encoding="utf-8")):
        _designed_to_default(k)          # patlarsa panel açılmaz
