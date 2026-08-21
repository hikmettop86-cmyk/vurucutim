"""Kapı prompt'u kanalın dikeyini bilmeli."""
from __future__ import annotations

from short_bot.config import ChannelConfig


def _kanal(**kw):
    base = dict(
        slug="t", name="Test", keywords=[], language="tr",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, max_age_hours=24, template="flas",
        colors={"primary": "#fff", "accent": "#000", "bg_gradient": ["#1", "#2"]},
        handle="@t", output_dir="o", content_source="trends",
        rss_locale="hl=tr&gl=TR&ceid=TR:tr", enabled=False,
    )
    base.update(kw)
    return ChannelConfig(**base)


def _items():
    from short_bot.models import NewsItem
    return [NewsItem(guid="g1", title="Altın rekor kırdı", link="l", source=None,
                     pub_date=None, thumb_url=None, description=None,
                     trend_volume=100000, trend_categories=(3,))]


def test_dikeysiz_prompt_degismez():
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal())
    assert "BU KANALIN DİKEYİ" not in p


def test_para_dikeyinde_fiyat_hareketi_olay_sayilir():
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal(trends_vertical="para"))
    assert "BU KANALIN DİKEYİ" in p
    assert "Para" in p
    # Varsayılan kapı altın kuru sorgusunu eliyor; para dikeyinde HAREKETİN
    # NEDENİ olay sayılmalı.
    assert "neden" in p.lower()


def test_adalet_dikeyi_prompta_yazilir():
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal(trends_vertical="adalet"))
    assert "BU KANALIN DİKEYİ" in p
    assert "Adalet" in p


def test_ingilizce_kanalda_dikey_blogu_ingilizce():
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(),
                             channel=_kanal(language="en", trends_vertical="para"))
    assert "THIS CHANNEL'S VERTICAL" in p


def test_rss_kanalinda_dikey_blogu_eklenmez():
    """Dikey yalnız trends kaynağında anlamlı — RSS kanalının prompt'u bozulmasın."""
    from short_bot.scorer import build_scoring_prompt
    from short_bot.models import NewsItem
    items = [NewsItem(guid="g", title="t", link="l", source=None, pub_date=None,
                      thumb_url=None, description=None)]
    p = build_scoring_prompt(items, channel=_kanal(content_source="rss",
                                                   trends_vertical="para"))
    assert "BU KANALIN DİKEYİ" not in p


def test_blok_baslik_listesine_yapismaz():
    """Blok şablonda '{vertical_block}Başlıklar:' olarak gömülü; ayırmazsak
    not satırı listeye yapışır ve model iki talimatı tek cümle sanır."""
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal(trends_vertical="para"))
    assert "\n\nBaşlıklar:" in p
    assert "ver.Başlıklar" not in p


def test_json_talimati_prompt_un_sonunda_kalir():
    """Son talimat çıktı biçimi olmalı; dikey bloğu ondan SONRA gelmemeli."""
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal(trends_vertical="para"))
    assert p.index("BU KANALIN DİKEYİ") < p.index("SADECE şu JSON")
