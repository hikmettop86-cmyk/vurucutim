"""Kaynak ADI olgu kapısının referansında olmalı.

CANLI VAKA (2026-08-22, dördüncü Japonca koşu): haber 週刊女性PRIME'dan geldi,
persona kaynağı ADIYLA söylemeyi ZORUNLU kılıyor ("報じた媒体の名前"), anlatım
söyledi ve kapı 'PRIME' için "kaynakta yok" deyip ÜRETİMİ DURDURDU.

Sebep: referans yalnız gövde + ek kaynaklar + description idi. Yayın adı
haberin BAŞLIĞINDA ve item.source alanında duruyor, gövde metninde değil.

Yani persona bir şeyi zorunlu kılarken kapı onu uydurma sayıyordu — iki kural
birbiriyle çelişiyordu.
"""
from __future__ import annotations

import types


def _item(**kw):
    base = dict(title="三山凌輝の報道（週刊女性PRIME）", description="",
                source="週刊女性PRIME", link="https://x.test",
                trend_related=(), extra_links=(), trend_volume=1000,
                followup_of=None, trend_articles=())
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_kaynak_adi_referansa_girer():
    from short_bot.narration_writer import fact_reference
    ref = fact_reference(_item(), "gövde metni", [])
    assert "週刊女性PRIME" in ref
    assert "gövde metni" in ref


def test_baslik_da_referansa_girer():
    from short_bot.narration_writer import fact_reference
    ref = fact_reference(_item(title="藤井風 タイ公演中止"), "gövde", [])
    assert "藤井風" in ref


def test_ek_kaynaklar_korunur():
    from short_bot.narration_writer import fact_reference
    ref = fact_reference(_item(), "gövde", [("u", "ek kaynak metni")])
    assert "ek kaynak metni" in ref


def test_kaynak_adini_soyleyen_anlatim_reddedilmez():
    from short_bot.fact_gate import unverified_claims
    from short_bot.narration_writer import fact_reference
    it = _item()
    ref = fact_reference(it, "三山凌輝さんの報道について関係者が説明しました。", [])
    anlatim = "週刊女性PRIMEの報道によれば、関係者が説明しています。"
    assert unverified_claims(anlatim, ref, language="ja") == []


def test_gercek_uydurma_hala_yakalanir():
    from short_bot.fact_gate import unverified_claims
    from short_bot.narration_writer import fact_reference
    ref = fact_reference(_item(), "関係者が説明しました。", [])
    assert unverified_claims("NHKが五百億円と報じました。", ref, language="ja")
