"""Rekor/üstünlük iddiası KAYNAKTA olmalı.

CANLI VAKA (2026-08-22, Japonca kanalın ilk videosu): anlatım
「芸能事務所の倒産は過去最多を記録しています」 ("ajans iflasları REKOR seviyede")
dedi. Kaynakta yalnız 「経営破綻が相次ぐ中」 ("art arda iflaslar arasında") vardı —
"rekor" uydurmaydı. Sayı da Latin de olmadığı için desen kapısı göremiyordu.

Ama bu YAKALANABİLİR bir sınıf: rekor/ilk/en-çok iddiaları kapalı bir kelime
kümesi ve her zaman olgusaldır. Anlatımda geçip kaynakta geçmiyorsa uydurmadır.
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("dil,anlatim,kaynak,beklenen", [
    ("ja", "倒産は過去最多を記録しています。", "経営破綻が相次いでいます。", True),
    ("ja", "倒産は過去最多を記録しています。", "倒産は過去最多となりました。", False),
    ("tr", "Altın rekor kırdı.", "Altın yükselişini sürdürüyor.", True),
    ("tr", "Altın rekor kırdı.", "Altın rekor seviyeye ulaştı.", False),
    ("de", "Ein Rekord wurde erreicht.", "Die Zahl stieg weiter.", True),
    ("de", "Ein Rekord wurde erreicht.", "Ein Rekord wurde gemeldet.", False),
])
def test_rekor_iddiasi_kaynaksizsa_yakalanir(dil, anlatim, kaynak, beklenen):
    from short_bot.fact_gate import unverified_claims
    eksik = unverified_claims(anlatim, kaynak, language=dil)
    assert bool(eksik) is beklenen, f"{dil}: {eksik}"


def test_ilk_kez_iddiasi_da_yakalanir():
    from short_bot.fact_gate import unverified_claims
    assert unverified_claims("史上初の決定です。", "決定が下されました。", language="ja")
    assert unverified_claims("İlk kez böyle bir karar çıktı.",
                             "Karar açıklandı.", language="tr")


def test_siradan_metin_yanlis_pozitif_uretmez():
    from short_bot.fact_gate import unverified_claims
    assert unverified_claims("決定を受けました。", "決定を受けました。", language="ja") == []
    assert unverified_claims("Karar açıklandı.", "Karar açıklandı.", language="tr") == []
