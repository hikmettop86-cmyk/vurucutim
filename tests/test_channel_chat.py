"""Sohbet motoru: karar veren, soru sormayan; ve yazdığı alan SINIRLI.

ÜSLUP KURALI (spec C): "Tonu ne olsun? Sesi ne olsun?" diye soran bir sohbet,
94 alanlık formu 94 soruya çevirmekten başka bir şey değildir ve kullanıcıyı
ne diyeceğini bilmek zorunda bırakır. Claude kararı verir, gerekçesini yazar;
kullanıcı yalnız beğenmediği satıra dokunur.

GÜVENLİK: LLM'in yazabileceği alanlar BEYAZ LİSTE. `slug`, `output_dir`,
`language` gibi alanları değiştirmek kanalı bozar (dosya yolları, dil paketi,
DNA ve konu bankası tutarsız kalır).
"""
from __future__ import annotations

import pytest


def _cfg(**kw):
    from short_bot.config import ChannelConfig
    base = dict(slug="ch", name="C", keywords=["a"],
                rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 9 * * *",
                duration_s=6, min_score=6.0, max_candidates_per_run=10,
                template="newscast",
                colors={"primary": "#000", "accent": "#111",
                        "bg_gradient": ["#000", "#111"]},
                handle="@ch", output_dir="out", enabled=True, language="tr")
    base.update(kw)
    return ChannelConfig(**base)


# --- şema ------------------------------------------------------------------

def test_karar_semasi():
    from short_bot.channel_chat import Karar
    k = Karar(alan="trends_region", deger="AT", ozet="Bölge AT",
              gerekce="Avusturya gündemi istendi")
    assert k.dikkat is False and k.alternatif_etiket == ""


def test_sohbet_cevabi_bos_kararla_da_gecerli():
    """Kullanıcı soru sorduğunda (ör. 'klartext'ten farkı ne?') karar üretilmez."""
    from short_bot.channel_chat import SohbetCevabi
    c = SohbetCevabi(mesaj="Şöyle farklı…")
    assert c.kararlar == [] and c.oneriler == []


# --- prompt ----------------------------------------------------------------

def test_gecmis_prompta_gomulur():
    """CLI oturumu kullanılmıyor: `-p` tek atış ve OpenRouter düşme yolunda
    oturum diye bir şey yok. Geçmiş prompt'a gömülür."""
    from short_bot.channel_chat import prompt_kur
    p = prompt_kur(cfg=_cfg(), gecmis=[("kullanici", "günde 3 olsun"),
                                       ("claude", "Tamam, cron'u güncelledim")],
                   girdi="bir de sesi değiştir")
    assert "günde 3 olsun" in p
    assert "Tamam, cron'u güncelledim" in p
    assert "bir de sesi değiştir" in p


def test_prompt_uslup_kuralini_tasir():
    from short_bot.channel_chat import prompt_kur
    p = prompt_kur(cfg=_cfg(), gecmis=[], girdi="merhaba").lower()
    assert "soru sorma" in p or "soru sormadan" in p
    assert "gerekçe" in p


def test_prompt_kanalin_mevcut_ayarlarini_tasir():
    """Claude neyin ne olduğunu bilmeden 'değiştirdim' diyemez."""
    from short_bot.channel_chat import prompt_kur
    p = prompt_kur(cfg=_cfg(min_score=7.5), gecmis=[], girdi="x")
    assert "7.5" in p


def test_prompt_yazilabilir_alanlari_listeler():
    """LLM neyi yazabileceğini bilmezse yasak alana uzanır ve tur boşa gider."""
    from short_bot.channel_chat import YAZILABILIR, prompt_kur
    p = prompt_kur(cfg=_cfg(), gecmis=[], girdi="x")
    for alan in ("min_score", "schedule_cron", "youtube.auto_upload"):
        assert alan in p
    # Kanalı bozacak alanlar listede OLMAMALI — beyaz liste bunu garanti eder.
    for yasak in ("slug", "output_dir", "language", "rss_locale", "template"):
        assert yasak not in YAZILABILIR


# --- uygula ----------------------------------------------------------------

def test_duz_alan_yazilir():
    from short_bot.channel_chat import Karar, uygula
    yeni = uygula([Karar(alan="min_score", deger=7.5, ozet="", gerekce="")], _cfg())
    assert yeni.min_score == 7.5


def test_ic_ice_alan_yazilir():
    from short_bot.config import VoiceConfig
    from short_bot.channel_chat import Karar, uygula
    cfg = _cfg(voice=VoiceConfig(enabled=True, voice_id="v", speed=1.0))
    yeni = uygula([Karar(alan="voice.speed", deger=1.15, ozet="", gerekce="")], cfg)
    assert yeni.voice.speed == 1.15
    assert yeni.voice.voice_id == "v"      # kardeş alan korunur


def test_youtube_alani_yazilir():
    from short_bot.config import YoutubeChannelConfig
    from short_bot.channel_chat import Karar, uygula
    cfg = _cfg(youtube=YoutubeChannelConfig(auto_upload=False))
    yeni = uygula([Karar(alan="youtube.auto_upload", deger=True,
                         ozet="", gerekce="")], cfg)
    assert yeni.youtube.auto_upload is True


@pytest.mark.parametrize("alan", ["slug", "output_dir", "language", "rss_locale"])
def test_YASAK_alan_reddedilir(alan):
    """Bu alanları değiştirmek kanalı bozar: dosya yolları kayar, dil paketi
    ve DNA tutarsız kalır. LLM'in yazmasına izin verilmez."""
    from short_bot.channel_chat import Karar, YasakAlan, uygula
    with pytest.raises(YasakAlan):
        uygula([Karar(alan=alan, deger="x", ozet="", gerekce="")], _cfg())


def test_bilinmeyen_alan_reddedilir():
    from short_bot.channel_chat import Karar, YasakAlan, uygula
    with pytest.raises(YasakAlan):
        uygula([Karar(alan="uydurma_alan", deger=1, ozet="", gerekce="")], _cfg())


def test_uygula_ORIJINALI_DEGISTIRMEZ():
    """Fark gösterilip onaylanana kadar hiçbir şey yazılmamalı."""
    from short_bot.channel_chat import Karar, uygula
    cfg = _cfg(min_score=6.0)
    uygula([Karar(alan="min_score", deger=9.0, ozet="", gerekce="")], cfg)
    assert cfg.min_score == 6.0


def test_fark_listesi_uretilir():
    """Diff ekranı için: hangi alan neye dönüyor."""
    from short_bot.channel_chat import Karar, fark
    cfg = _cfg(min_score=6.0)
    f = fark([Karar(alan="min_score", deger=7.5, ozet="", gerekce="")], cfg)
    assert f == [("min_score", 6.0, 7.5)]


def test_fark_degismeyeni_LISTELEMEZ():
    from short_bot.channel_chat import Karar, fark
    cfg = _cfg(min_score=6.0)
    assert fark([Karar(alan="min_score", deger=6.0, ozet="", gerekce="")], cfg) == []


# --- konuş -----------------------------------------------------------------

def test_konus_llm_cagirir_ve_semayi_dogrular():
    from short_bot.channel_chat import SohbetCevabi, konus
    cagri = {}

    def _sahte_llm(prompt, schema, **kw):
        cagri["prompt"] = prompt
        cagri["schema"] = schema
        return schema(mesaj="Kurdum.", kararlar=[], oneriler=["günde 3 olsun"])

    c = konus(cfg=_cfg(), gecmis=[], girdi="kanal kur", llm=_sahte_llm)
    assert isinstance(c, SohbetCevabi)
    assert c.oneriler == ["günde 3 olsun"]
    assert cagri["schema"] is SohbetCevabi
    assert "kanal kur" in cagri["prompt"]


# --- taslak ----------------------------------------------------------------

def test_taslak_format_isaretlerini_tasir():
    """Ses/montaj bloğu KAPALI kurulur (voice_id henüz seçilmedi ve Pydantic
    enabled=True iken onu zorunlu kılıyor). Bu yüzden taslağın formatı
    channel_format'tan OKUNAMAZ — çağıran taşır ve prompt_kur(fmt=...) alır."""
    from short_bot.channel_chat import taslak
    assert taslak("voiced").voice is not None and taslak("voiced").voice.enabled is False
    assert taslak("yorum").content_source == "trends"
    assert taslak("yorum").voice.provider == "cartesia"
    assert taslak("curated").content_source == "curated"
    assert taslak("curated").reel is not None
    assert taslak("card").voice is None


def test_prompt_formati_disaridan_alir():
    from short_bot.channel_chat import prompt_kur, taslak
    p = prompt_kur(cfg=taslak("voiced"), gecmis=[], girdi="x", fmt="voiced")
    assert "Sesli" in p


def test_taslak_CRON_KAPALI_kurulur():
    """Ayarları oturmamış kanalı doğrudan üretime sokmak yanlış."""
    from short_bot.channel_chat import taslak
    assert taslak("card").enabled is False


def test_taslak_uzerinde_sohbet_kararlari_uygulanir():
    """Kurma ve düzenleme AYNI motoru kullanır — kurulum da bir cfg üstünde yürür."""
    from short_bot.channel_chat import Karar, taslak, uygula
    t = taslak("yorum")
    yeni = uygula([Karar(alan="trends_region", deger="AT", ozet="", gerekce=""),
                   Karar(alan="name", deger="Wien Klartext", ozet="", gerekce="")], t)
    assert yeni.trends_region == "AT"
    assert yeni.name == "Wien Klartext"


def test_taslak_dili_locale_ye_yansir():
    from short_bot.channel_chat import taslak
    assert "gl=DE" in taslak("card", language="de").rss_locale


# --- ÇIKTI ALANLARI MODELE SÖYLENİYOR MU -----------------------------------
#
# CANLI ARIZA (2026-08-21): sohbet gerçek modelle HİÇ çalışmadı. Prompt
# `SohbetCevabi`nin dört alanından yalnız birini (`oneriler`) adlandırıyordu;
# zorunlu olan `mesaj` hiç geçmiyordu. Model `mesaj`sız JSON üretti, iki deneme
# de aynı hatayla düştü, kullanıcı 111 saniye sonra hata gördü.
#
# Testler sahte LLM enjekte ettiği için boşluk görünmedi. Bu iki test ZİNCİRİ
# sınıyor: sohbet prompt'u + sonnet_json'ın şema bloğu birlikte modele ne
# söylüyor.

def test_modele_giden_prompt_TUM_cikti_alanlarini_adlandirir():
    from short_bot.channel_chat import SohbetCevabi, konus, taslak
    from short_bot.llm_sonnet import sonnet_json

    gorulen = []

    def _invoke(prompt, **kw):
        gorulen.append(prompt)
        return '{"mesaj": "tamam"}'

    def _llm(prompt, schema, **kw):
        return sonnet_json(prompt, schema, invoke=_invoke)

    konus(cfg=taslak("card"), gecmis=[], girdi="Beşiktaş kanalı",
          llm=_llm, fmt="card")
    p = gorulen[0]
    for alan in SohbetCevabi.model_fields:
        assert alan in p, f"'{alan}' modele hiç söylenmiyor — canlıda cevap reddedilir"


def test_uslup_MESAJIN_ne_olacagini_anlatir():
    """Alan adını bilmek yetmez: `mesaj` boş string de olabilir ve sohbet sessiz
    kalır. Üslup kuralı ne yazılacağını da söylemeli."""
    from short_bot.channel_chat import prompt_kur, taslak
    p = prompt_kur(cfg=taslak("card"), gecmis=[], girdi="x", fmt="card")
    assert "mesaj" in p
    assert "ASLA BOŞ BIRAKMA" in p


# --- KURULUMDA CRON AÇILMAZ ------------------------------------------------
#
# CANLI GÖZLEM (2026-08-21): ilk turda model `enabled: False → True` kararı
# verdi ("Kanal aktif edildi"). `taslak()` cron'u BİLEREK kapalı kuruyor —
# ayarları oturmamış bir kanalı doğrudan üretime sokmamak için — ve kurulum
# sonrası mesaj "Cron KAPALI" diye yazıyordu. İkisi aynı anda doğru olamaz.

def test_uslup_KURULUMDA_CRON_ACMAYI_yasaklar():
    from short_bot.channel_chat import prompt_kur, taslak
    p = prompt_kur(cfg=taslak("card"), gecmis=[], girdi="x", fmt="card")
    i = p.find("enabled")
    assert i > 0
    assert "kurulum" in p.lower()


# --- OLMAYAN BLOĞUN ALANI LİSTELENMEZ --------------------------------------
#
# CANLI ARIZA (2026-08-21, scratch panel): kart kanalı kurulurken model 15
# karar verdi — `voice.enabled`, `reel.cut_pacing`, `youtube.category_id`…
# Kart taslağında `voice`/`reel`/`youtube` blokları YOK; `uygula` ilk
# imkânsız kararda patlıyor ve BÜTÜN PARTİ düşüyor. Kullanıcı "İşaretlileri
# uygula"ya bastı, hiçbir şey uygulanmadı, "Kanalı kur" da "adı yok" dedi.

def test_prompt_OLMAYAN_BLOGUN_alanlarini_LISTELEMEZ():
    from short_bot.channel_chat import prompt_kur, taslak
    p = prompt_kur(cfg=taslak("card"), gecmis=[], girdi="x", fmt="card")
    assert "voice.enabled" not in p
    assert "reel.cut_pacing" not in p
    assert "dna.body_max_chars" not in p, "DNA kurulumda henüz üretilmedi"


def test_prompt_VAR_OLAN_blogun_alanlarini_listeler():
    from short_bot.channel_chat import prompt_kur, taslak
    p = prompt_kur(cfg=taslak("voiced"), gecmis=[], girdi="x", fmt="voiced")
    assert "voice.enabled" in p and "voice.persona" in p
    assert "reel.cut_pacing" not in p


def test_taslak_YOUTUBE_blogu_TASIR():
    """Kurulumda kategori/gizlilik belirlemek meşru (Beşiktaş → Spor 17) ve
    varsayılanları etkisiz (auto_upload False)."""
    from short_bot.channel_chat import prompt_kur, taslak
    for fmt in ("card", "voiced", "yorum", "curated"):
        cfg = taslak(fmt)
        assert cfg.youtube is not None, fmt
        assert cfg.youtube.auto_upload is False, fmt
    assert "youtube.category_id" in prompt_kur(
        cfg=taslak("card"), gecmis=[], girdi="x", fmt="card")
