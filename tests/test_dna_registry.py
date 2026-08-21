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


# --- KAYIT YOLU YAPILANDIRILABİLİR OLMALI ----------------------------------
#
# `_REGISTRY_PATH` KAYNAK DOSYAYA göre çözülüyordu
# (`<src>/../../config/archetypes.json`) ve `register_designed_archetype` oraya
# YAZIYORDU. İki somut zarar (ikisi de 2026-08-21'de yaşandı):
#
#   1. Depo dışında koşan her şey (scratch panel, ölçüm betiği) kullanıcının
#      DEPOSUNU kirletiyor. `bayern-bedava` kaydı böyle sızdı ve `test_pexels`
#      "3 sorgudan az" diye düştü.
#   2. Paketlenmiş Electron kurulumunda kaynak ağacı kullanıcının config
#      dizini DEĞİL — tasarlanan arketip yanlış yere yazılır (ya da salt-okunur
#      dizine yazılamaz).

def test_kayit_yolu_DEGISTIRILEBILIR(tmp_path, monkeypatch):
    import short_bot.dna as dna
    for ad in ("ARCHETYPES", "ARCHETYPE_LABELS", "ARCHETYPE_DEFAULTS",
               "_DESIGNED_ARCHETYPES"):
        monkeypatch.setattr(dna, ad, type(getattr(dna, ad))(getattr(dna, ad)))
    hedef = tmp_path / "cfg" / "archetypes.json"
    dna.set_registry_path(hedef)
    try:
        dna.register_designed_archetype("yolluk", "Yolluk")
        assert hedef.exists(), "verilen yola yazmadı"
        assert json.loads(hedef.read_text(encoding="utf-8"))[0]["slug"] == "yolluk"
    finally:
        dna.set_registry_path(None)


def test_None_ile_VARSAYILANA_doner(tmp_path):
    """NOT: `conftest._arketip_kaydi_yalitimi` her testte yolu tmp'ye çekiyor;
    burada sınanan şey MODÜL VARSAYILANINA dönüş."""
    import short_bot.dna as dna
    dna.set_registry_path(tmp_path / "x.json")
    dna.set_registry_path(None)
    assert dna._REGISTRY_PATH == dna._VARSAYILAN_REGISTRY_PATH


def test_create_app_KAYIT_YOLUNU_config_dizinine_kurar(tmp_path):
    """Panel açılırken kaydı KENDİ config dizinine bağlamalı."""
    import short_bot.dna as dna
    from short_bot.web import create_app
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    try:
        create_app(config_dir=cfg, db_path=tmp_path / "d.sqlite", scheduler=False)
        assert dna._REGISTRY_PATH == cfg / "archetypes.json"
    finally:
        dna.set_registry_path(None)
