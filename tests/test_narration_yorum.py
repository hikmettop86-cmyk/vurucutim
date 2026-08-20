"""Gündem Yorum anlatımı: tarafsız-ama-görüşlü yorumcu promptu ve üretim makinesi."""
from __future__ import annotations

import pytest

from short_bot.models import NewsItem
from short_bot.narration import Narration


def _channel(persona=None, language="tr"):
    from short_bot.config import ChannelConfig, VoiceConfig
    from short_bot.narration_writer import YORUM_PERSONA_TR
    return ChannelConfig(
        slug="gundem-yorum", name="Gündem Yorum", keywords=[], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0, max_candidates_per_run=5,
        template="flas", colors={"primary": "#d0021b", "accent": "#ffe600",
                                 "bg_gradient": ["#3a3a3a", "#141414"]},
        handle="@gundem", output_dir="out", enabled=True, language=language,
        content_source="trends",
        voice=VoiceConfig(enabled=True, provider="cartesia", voice_id="v", speed=1.05,
                          persona=persona or YORUM_PERSONA_TR, target_duration_s=(35, 50)),
    )


def _item():
    return NewsItem(guid="https://milliyet/1", title="Marmara 8 saatte 36 kez sallandı",
                    link="https://milliyet/1", source="Milliyet", pub_date=None, thumb_url=None,
                    description="Google Trends · 100.000 arama · +%1.000 · istanbul deprem, adalar fayı",
                    trend_volume=100000, extra_links=("https://ntv/2", "https://onedio/3"))


EXTRA = [("https://ntv/2", "NTV: Kandilli Rasathanesi gece boyu 51 sarsıntı kaydetti."),
         ("https://onedio/3", "Onedio: Uzmanlar Adalar fayının izlendiğini söyledi.")]


def test_yorum_prompt_carries_persona_sources_and_rules():
    from short_bot.narration_writer import build_yorum_prompt
    p = build_yorum_prompt(_item(), "Milliyet gövdesi: 3.1 büyüklüğünde deprem oldu.",
                           _channel(), extra_sources=EXTRA)
    # persona + kaynaklar
    assert "kimsenin adamı olmayan" in p
    assert "PRIMARY SOURCE (Milliyet)" in p
    assert "ADDITIONAL SOURCES" in p and "ntv" in p.lower() and "Onedio" in p
    # kurallar: görüş + denge var, kaynak sayma SINIRLI (bibliyografya değil)
    for needle in ("At most TWO such attributions", "HAVE A VIEW", "BE FAIR",
                   "party's or a leader's side", "Invent nothing"):
        assert needle.lower() in p.lower(), needle
    # çıktı şeması mevcut Narration ile aynı
    assert '"hook"' in p and '"beats"' in p and '"loop_close"' in p and '"mood"' in p


def test_yorum_prompt_forbids_speaking_the_search_signal():
    """Kullanıcı bildirimi (2026-08-20): 'Google Trends'te yirmi bin kişi aradı' cümlesi
    videoyu otomasyon gibi gösteriyor. Arama verisi konuyu SEÇER, konuşulmaz."""
    from short_bot.narration_writer import BANNED_PHRASES, build_yorum_prompt
    p = build_yorum_prompt(_item(), "gövde", _channel(), extra_sources=EXTRA)
    assert "NEVER MENTION how many people searched" in p
    for phrase in ("Google Trends", "kişi aradı", "Peki sizce", "Bence risk var ama",
                   "Öte yandan", "abone ol"):
        assert phrase in BANNED_PHRASES
        assert phrase in p                      # yalnız YASAK listesinde geçer
    # eski zorunlu kural artık YOK
    assert "WHY IT IS TRENDING" not in p
    assert "100.000 arama" not in p


def test_yorum_prompt_injects_the_video_shape():
    from short_bot.narration_writer import build_yorum_prompt
    from short_bot.yorum_variation import pick_variation
    v = pick_variation(seed_text="x")
    p = build_yorum_prompt(_item(), "gövde", _channel(), extra_sources=[], variation=v)
    assert "SHAPE OF THIS VIDEO" in p
    assert v.opening in p and v.angle in p and v.closing in p
    # varyasyonsuz çağrıda sabit iskelet dayatılmaz
    assert "SHAPE OF THIS VIDEO" not in build_yorum_prompt(_item(), "gövde", _channel(),
                                                           extra_sources=[])


def test_yorum_prompt_word_budget_from_voice_target():
    from short_bot.narration_writer import build_yorum_prompt, word_budget
    ch = _channel()
    lo, hi = word_budget(ch.voice.target_duration_s, "tr")
    p = build_yorum_prompt(_item(), "gövde", ch, extra_sources=[])
    assert f"between {lo} and {hi}" in p


def test_yorum_prompt_without_extra_sources_relaxes_two_source_rule():
    from short_bot.narration_writer import build_yorum_prompt
    p = build_yorum_prompt(_item(), "gövde", _channel(), extra_sources=[])
    assert "ADDITIONAL SOURCES" not in p
    assert "name the source" in p.lower()


def test_write_yorum_narration_checks_facts_against_all_sources(monkeypatch):
    from short_bot import narration_writer as nw
    prompts = []

    def _run_json(prompt, model_cls, **kw):
        prompts.append(prompt)
        return Narration(
            hook="Adalar yine mi sallandı?",
            beats=[{"text": "Milliyet'e göre 8 saatte 36 sarsıntı oldu.", "on_screen": "36 SARSINTI"},
                   {"text": "NTV, Kandilli'nin gece 51 sarsıntı saydığını yazdı.", "on_screen": "KANDİLLİ: 51"},
                   {"text": "Bence panik değil, hazırlık zamanı.", "on_screen": "HAZIRLIK ZAMANI"}],
            loop_close="Siz ne düşünüyorsunuz, yüz bin kişi bunu aradı.", mood="neutral")
    monkeypatch.setattr(nw, "run_json", _run_json)
    monkeypatch.setattr(nw, "word_budget", lambda *a, **k: (5, 200))
    seen = {}

    def _claims(text, reference, **kw):
        seen["reference"] = reference
        return []
    monkeypatch.setattr(nw, "unverified_claims", _claims)
    from short_bot.yorum_variation import pick_variation
    n = nw.write_yorum_narration(_item(), "Milliyet gövdesi 36 sarsıntı.", channel=_channel(),
                                 extra_sources=EXTRA, variation=pick_variation(seed_text="s"))
    assert n.hook.startswith("Adalar")
    # referans metin = ana gövde + ek kaynaklar + Trends bağlamı
    assert "Milliyet gövdesi" in seen["reference"]
    assert "51 sarsıntı" in seen["reference"]
    assert "100.000 arama" in seen["reference"]   # olgu kapısı arama verisini TANIR
    assert "SHAPE OF THIS VIDEO" in prompts[0]    # ama prompt onu konuşturmaz
    assert len(prompts) == 1


def test_default_persona_is_neutral_but_opinionated():
    from short_bot.narration_writer import YORUM_PERSONA_TR
    for needle in ("Taraf tutmaz", "görüşsüz de değil", "herkesin aklındaki soru", "adil ama net",
                   "Vatandaşın tarafında", "alay olmaz", "saygılı"):
        assert needle in YORUM_PERSONA_TR, needle
