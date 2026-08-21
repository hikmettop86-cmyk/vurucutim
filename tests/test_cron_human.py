"""`cron_human` panelin her yerinde zamanlamayı yazıya çeviriyor — çeviremediğinde
ham cron gösteriyor ve okunmuyor.

ÖLÇÜLDÜ (2026-08-21): depodaki 9 farklı cron ifadesinden 7'si çevrilemiyordu.
Desteklenmeyen iki desen, kanalların çoğunun kullandığı desenlerdi:

    0 7-22/3 * * *        aralık + adım   (7 kanal bu ailede)
    30 9,13,17,21 * * *   saat listesi
"""
from __future__ import annotations

import pytest

from short_bot.web.cron_describe import cron_human

# Depodaki gerçek ifadeler — hiçbiri ham dönmemeli.
GERCEK = [
    "0 */4 * * *", "0 1-23/2 * * *", "0 10 * * *", "0 2-22/4 * * *",
    "0 7-22/3 * * *", "0 8-23/3 * * *", "30 8-20/3 * * *",
    "30 9,13,17,21 * * *", "30 9-21/3 * * *", "0 9,15,20 * * *",
]


@pytest.mark.parametrize("ifade", GERCEK)
def test_depodaki_her_cron_cevriliyor(ifade):
    cikti = cron_human(ifade)
    assert cikti != ifade, f"ham döndü: {ifade}"
    assert cikti.strip()


def test_saat_listesi_saatleri_yazar():
    assert cron_human("0 9,15,20 * * *") == "Günde 3: 09:00, 15:00, 20:00"


def test_saat_listesi_dakikayi_tasir():
    assert cron_human("30 9,13,17,21 * * *") == "Günde 4: 09:30, 13:30, 17:30, 21:30"


def test_uzun_liste_kisaltilir():
    """Dar sütunda sekiz saat okunmaz; tam ifade zaten tooltip'te."""
    assert cron_human("0 6,8,10,12,14,16,18,20 * * *") == "Günde 8 kez"


def test_aralik_adim():
    assert cron_human("0 7-22/3 * * *") == "07–22 arası 3 saatte bir"


def test_aralik_adim_dakikali():
    assert cron_human("30 8-20/3 * * *") == "08–20 arası 3 saatte bir (:30)"


def test_tek_saat_degismedi():
    """Çalışan davranış bozulmasın."""
    assert cron_human("0 10 * * *") == "Her gun saat 10:00"


def test_her_n_saatte_bir_degismedi():
    assert cron_human("0 */4 * * *") == "Her 4 saatte bir, dakika 00"


def test_bos_ve_bozuk_guvenli():
    assert cron_human("") == ""
    assert cron_human("abc") == "abc"
    assert cron_human("0 9 * *") == "0 9 * *"      # 4 alan
