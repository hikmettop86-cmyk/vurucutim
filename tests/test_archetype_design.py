"""Arketip tasarım akışı: LLM → kapılar → kaydet (ya da kaydetme).

EN ÖNEMLİ DAVRANIŞ: üç turda kapılardan geçemeyen şablon KAYDEDİLMEZ.
Geçen her şablon diskte kalıcı dosya olur; "olsun bari" diye yazmak, 40
kalıbın yanına 41'inci bozuk kalıbı eklemek ve onu kimsenin temizlememesi
demektir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_archetype_gate import GECERLI


@pytest.fixture
def sablonlar(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    for ad in ("newscast", "flas"):
        (d / f"{ad}.html.j2").write_text(GECERLI, encoding="utf-8")
    return d


def _render_ok(yol, metinler):
    """Her uç metin için bir 'kare' üretir (dosya varlığı yeterli)."""
    out = []
    for i, _ in enumerate(metinler):
        p = Path(yol).parent / f"kare{i}.png"
        p.write_bytes(b"x")
        out.append(p)
    return out


def test_gecerli_sablon_kaydedilir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("siyah beyaz, eğik bant", ad="Beşiktaş Mono",
                templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda yol: {"sorun": False},
                render_fn=_render_ok)
    assert s.ok, s.sebep
    assert (sablonlar / f"{s.slug}.html.j2").exists()
    assert s.tur == 1


def test_yapi_kapisindan_gecemeyen_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Bozuk", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: "<!DOCTYPE html><html><body>yok</body></html>",
                vision_call=lambda yol: {"sorun": False},
                render_fn=_render_ok)
    assert not s.ok
    assert not (sablonlar / "bozuk.html.j2").exists()
    assert s.tur == 3, "üç tur denenmeliydi"


def test_vision_reddederse_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Tasan", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda yol: {"sorun": True, "aciklama": "manşet kesik"},
                render_fn=_render_ok)
    assert not s.ok
    assert "manşet kesik" in s.sebep
    assert not (sablonlar / "tasan.html.j2").exists()


def test_vision_YOKSA_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    """Fail-closed: denetlenmemiş arketip diske yazılmaz."""
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Denetimsiz", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI, vision_call=None,
                render_fn=_render_ok)
    assert not s.ok
    assert not (sablonlar / "denetimsiz.html.j2").exists()


def test_red_sebebi_BIR_SONRAKI_TURA_yazilir(sablonlar, monkeypatch, tmp_path):
    """Kapı 'geçmedi' demekle kalmamalı; sebep prompt'a girmeli ki tur boşa
    gitmesin."""
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    promptlar = []

    def _llm(p):
        promptlar.append(p)
        return "<!DOCTYPE html><html><body>yok</body></html>"

    tasarla("x", ad="A", templates_dir=sablonlar, settings=None, metin_llm=_llm,
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert len(promptlar) == 3
    assert "REDDEDİLDİ" in promptlar[1]
    assert "body-text" in promptlar[1], "eksik slot bir sonraki tura yazılmadı"


def test_ikinci_turda_duzelirse_kaydedilir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    n = {"i": 0}

    def _llm(p):
        n["i"] += 1
        return GECERLI if n["i"] == 2 else "<!DOCTYPE html><html></html>"

    s = tasarla("x", ad="Ikinci", templates_dir=sablonlar, settings=None,
                metin_llm=_llm, vision_call=lambda y: {"sorun": False},
                render_fn=_render_ok)
    assert s.ok and s.tur == 2


def test_markdown_citi_temizlenir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Citli", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: f"İşte şablon:\n```html\n{GECERLI}\n```\nUmarım olur.",
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert s.ok
    icerik = (sablonlar / f"{s.slug}.html.j2").read_text(encoding="utf-8")
    assert icerik.startswith("<!DOCTYPE html>")
    assert "Umarım olur" not in icerik


def test_ornek_sablonlar_prompta_girer(sablonlar, monkeypatch, tmp_path):
    """Tek örnek verince LLM onu kopyalıyor; iki farklı örnek (sade + zengin)
    yapıyı öğretir, görünümü dayatmaz."""
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    p = {}
    tasarla("x", ad="A", templates_dir=sablonlar, settings=None,
            metin_llm=lambda pr: (p.setdefault("ilk", pr), GECERLI)[1],
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert "newscast.html.j2" in p["ilk"] and "flas.html.j2" in p["ilk"]


def test_kaydedilen_arketip_JSON_kaydina_girer(sablonlar, monkeypatch, tmp_path):
    """Panel açılırında görünmezse yeni arketip seçilemez."""
    import json
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "archetypes.json").write_text("[]", encoding="utf-8")
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Yeni Kalıp", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert s.ok
    kayit = json.loads((tmp_path / "config" / "archetypes.json").read_text(encoding="utf-8"))
    assert any(a["slug"] == s.slug for a in kayit)
