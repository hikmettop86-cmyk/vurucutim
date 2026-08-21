"""Dile ÖZGÜ anlatım kuralları prompt'a girmeli (üslup tercihi değil, DİL OLGUSU).

CANLI KANIT (2026-07-24): yerli okur kapısı, deneme videosunun anlatımını REDDETTİ —
hook sade biçimde ("その子はずっと一人だった"), beat'ler nazik biçimde ("走り出しました").
Japoncada tek bir kısa anlatımın içinde bu iki kayıt karışınca yerli kulağa BOZUK gelir.

Kapı bunu yakalıyor ama yakalamak PAHALI: her video fazladan bir Sonnet yeniden-yazım
turu (~50sn) yiyor ve iki denemede de tutmazsa iyi bir klip boşuna atlanıyor. Kuralı
yazarın ÖNÜNE koymak bedava.

Bu tablo bir OLGU tablosudur (ALPHABET_EXTRA gibi), dil paketine girmez: paketi Sonnet
üretiyor ve 'kayıt tutarlılığı' kuralını unutursa anlatım SESSİZCE bozulur.
"""
from pathlib import Path

from short_bot.config import load_channel
from short_bot.locale import NARRATION_STYLE_RULES, narration_style_rule


def test_japanese_has_a_register_rule():
    rule = narration_style_rule("ja")
    assert rule, "Japonca için kural yok"
    assert "です" in rule or "masu" in rule.lower()


def test_turkish_has_no_extra_rule():
    """Türkçe kanalların kanıtlanmış prompt'u uzamasın."""
    assert narration_style_rule("tr") == ""


def test_unknown_language_is_silent_not_an_error():
    assert narration_style_rule("xx") == ""


def test_every_declared_rule_is_non_empty():
    for lang, rule in NARRATION_STYLE_RULES.items():
        assert rule.strip(), lang


def _japon_kurate_kanali(tmp_path):
    """Testin KENDİ Japonca kürate kanalı.

    Eskiden `config/channels/yasashisa.yaml` okunuyordu ve kullanıcı o kanalı
    silince test kırıldı — oysa sınanan şey kanalın varlığı değil, JAPONCA bir
    kürate kanalında kuralın prompt'a girmesi. Depo yapılandırmasına bağlı test
    kırılgandır: kanal silmek bir hata değil, operatör kararı.
    """
    from short_bot.config import ChannelConfig, ReelConfig, save_channel
    p = tmp_path / "ja.yaml"
    save_channel(p, ChannelConfig(
        slug="ja", name="やさしさ", keywords=[], rss_locale="",
        schedule_cron="0 12 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="newscast",
        colors={"primary": "#000", "accent": "#111",
                "bg_gradient": ["#000", "#111"]},
        handle="@ja", output_dir="out", enabled=True, language="ja",
        content_source="curated",
        # CJK FONTU ŞART: doğrulayıcı Japonca kanalda Montserrat'ı reddediyor
        # (ekranda tofu çıkar). Fixture bunu doğru kurmalı ki test gerçek
        # bir kanalı taklit etsin.
        reel=ReelConfig(enabled=True, voice_id="v1", curated_tone="duygu",
                        font="Noto Sans JP")))
    return load_channel(p)


def test_curated_prompt_carries_the_rule_for_japanese(tmp_path):
    from short_bot.reel_narration import build_curated_prompt
    ch = _japon_kurate_kanali(tmp_path)
    p = build_curated_prompt("t", "a boy waits alone", channel=ch, tone="duygu")
    assert narration_style_rule("ja")[:40] in p


def test_curated_prompt_unchanged_for_turkish():
    from short_bot.reel_narration import build_curated_prompt
    ch = load_channel(Path("config/channels/dayidiyorki.yaml"))
    p = build_curated_prompt("t", "a cat jumps", channel=ch, tone="duygu")
    assert "です・ます" not in p


# Şartnamenin altı maddesi TEK TEK üretim reddinden çıkarıldı; biri silinirse o hata
# geri gelir ve KLİP MALİYETİNE mal olur. Testle bağla.

def test_spec_covers_every_observed_failure_mode():
    rule = narration_style_rule("ja")
    for anahtar, ipucu in [
        ("です・ます", "kayıt tutarlılığı"),
        ("TENSE", "zaman uyumu"),
        ("comma splice", "virgülle cümle bağlama"),
        ("コメントで教えてください", "CTA yorum çağrısı"),
        ("である", "yazınsal dil"),
        ("cover_title", "ekran uzunluğu"),
    ]:
        assert anahtar in rule, f"{ipucu} kuralı şartnameden düşmüş ({anahtar})"


def test_spec_does_not_teach_casual_cta():
    """Kendi kuralımız kendi kuralımızla çelişmesin: samimi CTA örneği vermek
    modele kayıt hatası YAPTIRDI (aday 71, 'いいね押してね')."""
    rule = narration_style_rule("ja")
    assert "押してね" not in rule.replace("押してね / 教えてね", "")


def test_cta_shape_is_mandated_as_question_then_invite():
    """CTA ÜÇ KEZ üretimde reddedildi (göndergesiz 'コメントで教えてください').
    Yargıç iki kez aynı şeyi söyledi: önce SORU, sonra çağrı. Kural artık sözcük
    tavsiyesi değil, YAPI zorunluluğu — biri silinirse aynı red geri gelir."""
    rule = narration_style_rule("ja")
    assert "か。" in rule, "soru cümlesi zorunluluğu düşmüş"
    assert "コメントで教えてください。" in rule
    assert "QUESTION" in rule
