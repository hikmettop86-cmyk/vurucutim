"""Anlatım, KARTIN anlattığı olayı anlatmalı.

CANLI VAKA (2026-08-22, short 1772): kaynak makale "görünür sutyen modası"
hakkındaydı ve YAN CÜMLEDE ilgili bir film devamından söz ediyordu. Kart ana
haberi doğru özetledi (シドニー・スウィーニー / ブラジャー見せるファッション大流行),
anlatım ise EK KAYNAĞA kayıp 40 saniyenin tamamını film devamına ayırdı
(ライオンズゲート / ザハウスメイド). Yani ekran bir şey, ses başka şey söylüyordu.

İki yapısal sebep:
  1. Prompt ek kaynakları "same story" diye tanıtıyor — Google Trends bir
     trende 3 makale verir ve bunlar farklı açılar/olaylar olabilir.
  2. KART anlatım promptuna HİÇ geçmiyordu: kart ve anlatım aynı makaleden
     BAĞIMSIZ yazılıyor, hiçbir şey ikisini birbirine bağlamıyordu.
"""
from __future__ import annotations

import types

from short_bot.config import ChannelConfig, VoiceConfig


def _kanal():
    return ChannelConfig(
        slug="t", name="T", keywords=[], language="ja", rss_locale="x",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, max_age_hours=24, template="flas",
        colors={"primary": "#d0021b", "accent": "#ffe600",
                "bg_gradient": ["#111111", "#222222"]},
        handle="@t", output_dir="o", enabled=False, content_source="trends",
        voice=VoiceConfig(enabled=True, provider="ai33", voice_id="v",
                          persona="p", target_duration_s=(30, 50)))


def _item():
    return types.SimpleNamespace(
        title="ブラジャー見せるファッションが大流行", description="",
        source="ハーパーズ バザー", link="https://x.test",
        trend_related=(), extra_links=(), trend_volume=20000,
        followup_of=None, trend_articles=())


KART = {"header_top": "シドニー・スウィーニー",
        "header_bottom": "ブラジャー見せるファッション大流行",
        "photo_overlay": "米スター女優28歳"}


def test_kart_prompta_capa_olarak_girer():
    from short_bot.narration_writer import build_yorum_prompt
    p = build_yorum_prompt(_item(), "gövde", _kanal(), extra_sources=[], card=KART)
    assert "シドニー・スウィーニー" in p
    assert "ブラジャー見せるファッション大流行" in p


def test_ek_kaynaklar_ayni_hikaye_diye_tanitilmaz():
    """Google Trends bir trende 3 makale verir; farklı olaylar olabilir."""
    from short_bot.narration_writer import build_yorum_prompt
    p = build_yorum_prompt(_item(), "gövde", _kanal(),
                           extra_sources=[("https://a.test/1", "başka bir olay")],
                           card=KART)
    assert "same story" not in p, "ek kaynaklar hâlâ aynı hikâye varsayılıyor"
    assert "MAIN STORY" in p or "ANA OLAY" in p


def test_kartsiz_cagri_hala_calisir():
    """Mevcut çağıranlar (kart geçmeyenler) kırılmamalı."""
    from short_bot.narration_writer import build_yorum_prompt
    p = build_yorum_prompt(_item(), "gövde", _kanal(), extra_sources=[])
    assert p


# --- uyum denetimi ------------------------------------------------------------

def test_kartin_oznesi_anlatimda_yoksa_uyumsuz():
    from short_bot.narration_writer import card_mismatch
    anlatim = "ライオンズゲートがザハウスメイドの続編製作を正式決定しました。"
    assert card_mismatch(anlatim, KART) is True


def test_kartin_oznesi_anlatimda_varsa_uyumlu():
    from short_bot.narration_writer import card_mismatch
    anlatim = "シドニー・スウィーニーさんも取り入れているこのファッションが広がっています。"
    assert card_mismatch(anlatim, KART) is False


def test_kart_yoksa_uyumsuzluk_iddia_edilmez():
    from short_bot.narration_writer import card_mismatch
    assert card_mismatch("herhangi bir metin", None) is False
    assert card_mismatch("herhangi bir metin", {}) is False


def test_cok_kisa_ozne_uyum_denetimine_girmez():
    """Tek karakterlik/çok kısa özne yanlış pozitif üretir."""
    from short_bot.narration_writer import card_mismatch
    assert card_mismatch("başka bir metin", {"header_top": "AB"}) is False
