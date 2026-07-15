"""Görüntü-öncelikli mod: konudan İngilizce footage arama sorgusu türetme."""
from types import SimpleNamespace

import pytest

import short_bot.reel_narration as RN
from short_bot.reel_models import FootageQueries


def _kanal(language="tr"):
    reel = SimpleNamespace(target_duration_s=(45, 60), persona="vahsi_mizah")
    return SimpleNamespace(reel=reel, language=language)


def test_konudan_n_ingilizce_sorgu(monkeypatch):
    yakalanan = {}

    def fake(prompt, schema, **k):
        yakalanan["prompt"] = prompt
        assert schema is FootageQueries
        return FootageQueries(queries=["chimpanzee", "chimpanzee fighting",
                                       "chimpanzee running"])

    monkeypatch.setattr(RN, "run_json", fake)
    qs = RN.footage_search_queries("şempanze kavgası", n=3, channel=_kanal())
    assert qs == ["chimpanzee", "chimpanzee fighting", "chimpanzee running"]
    # prompt konuyu ve n'i taşımalı, İngilizce sorgu istemeli
    assert "şempanze kavgası" in yakalanan["prompt"]
    assert "3" in yakalanan["prompt"]
    assert "ENGLISH" in yakalanan["prompt"]


def test_bos_sorgular_temizlenir_ve_hata(monkeypatch):
    monkeypatch.setattr(RN, "run_json",
                        lambda *a, **k: FootageQueries(queries=["  ", ""]))
    with pytest.raises(ValueError, match="sorgu üretilemedi"):
        RN.footage_search_queries("x", n=3, channel=_kanal())
