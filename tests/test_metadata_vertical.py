"""metadata_writer dikeyi ve CJK'yi bilmeli.

BULGU (2026-08-22): personalara koyulan dikeye özgü GÜVENLİK kuralları
(yatırım tavsiyesi yasağı, masumiyet karinesi, özel hayat spekülasyonu yasağı)
yalnız ANLATIMI koruyordu. Başlık — en görünür metin, YouTube'un indekslediği
şey — korumasızdı: prompt'a giren tek persona `channel.reel.persona` (kürate
formatı), trend/yorum kanallarında hiç yok.

Somut risk: anlatımı "mutmaßlich" diyen bir adalet videosunun başlığı suçu
kesinleyebilir; para kanalı "şu bankaya yatır" diye başlık atabilir.
"""
from __future__ import annotations

import pytest

from short_bot.config import ChannelConfig, VoiceConfig


def _kanal(**kw):
    base = dict(
        slug="t", name="Test", keywords=["a"], language="tr", rss_locale="x",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, max_age_hours=24, template="flas",
        colors={"primary": "#f", "accent": "#0", "bg_gradient": ["#1", "#2"]},
        handle="@t", output_dir="o", enabled=False, content_source="trends",
    )
    base.update(kw)
    return ChannelConfig(**base)


SCRIPT = {"header_top": "ALTIN", "header_bottom": "7 BİN TL'Yİ AŞTI",
          "body_paragraph": "Gram altın rekor kırdı.", "category": "Ekonomi"}


def _prompt(**kw):
    from short_bot.youtube.metadata_writer import build_metadata_prompt
    return build_metadata_prompt(channel=_kanal(**kw), script=SCRIPT,
                                 rss_source="Test", rss_link="https://x.test/1")


# --- dikey güvenlik kuralları -------------------------------------------------

def test_para_dikeyinde_baslik_yatirim_tavsiyesi_veremez():
    p = _prompt(trends_vertical="para")
    # DİKKAT: Türkçe İ/I'da .lower() bozulur ("YATIRIM TAVSİYESİ" -> "yatirim
    # tavsi̇yesi̇"), bu yüzden metnin YAZILDIĞI biçimden bakılır.
    assert "DİKEY" in p
    assert "YATIRIM TAVSİYESİ YASAK" in p


def test_adalet_dikeyinde_baslik_sucu_kesinlestiremez():
    p = _prompt(trends_vertical="adalet")
    assert "MASUMİYET KARİNESİ BAŞLIKTA DA GEÇERLİ" in p
    assert "KESİNLEŞTİRME" in p
    assert "TAM ADLA anılmaz" in p


def test_magazin_dikeyinde_baslik_ozel_hayat_spekulasyonu_yapamaz():
    p = _prompt(trends_vertical="magazin")
    assert "ÖZEL HAYAT SPEKÜLASYONU YASAK" in p


def test_dikeysiz_kanalda_blok_hic_yok():
    """Dikeysiz kanalın prompt'u bit bit eskisi gibi kalmalı."""
    assert "DİKEY" not in _prompt()


# --- ölçülmüş başlık kalıbı ---------------------------------------------------

def test_baslik_kurali_varlik_artı_niyet():
    """ÖLÇÜLDÜ (Aslan Gündem, 28 gün, YouTube Analytics): bizi bulan ilk 25
    sorgunun HİÇBİRİ soru değildi, hepsi varlık+niyet kalıbıydı
    ('gs transfer', 'galatasaray transfer son dakika'). 'Anahtar kelime başta'
    kuralı bunu söylemiyordu."""
    p = _prompt(trends_vertical="para")
    assert "VARLIK + NİYET" in p
    assert "ÖZNEYİ yaz" in p


# --- CJK başlık bütçesi -------------------------------------------------------

def test_japonca_baslik_butcesi_cjk_ye_gore():
    """Japonca 60-100 karakter DEVASA bir metin — model dolgu yapar.
    '藤井風 タイ公演中止を発表 事務所が理由を説明' zaten 25 karakter."""
    p = _prompt(language="ja", trends_vertical="magazin")
    assert "60-100" not in p, "CJK kanalda latin karakter bütçesi kullanılmış"
    assert "20-40" in p


def test_turkce_baslik_butcesi_degismedi():
    p = _prompt(trends_vertical="para")
    assert "60-100" in p


# --- kanalın kendi yasakları ---------------------------------------------------

def test_dna_yasaklari_baslik_promptuna_gecer():
    """DNA'daki forbidden listesi kartı koruyordu ama başlığı korumuyordu."""
    from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone
    dna = DnaSpec(
        archetype="flas",
        palette=DnaPalette(primary="#d0021b", accent="#ffe600",
                           bg_gradient=["#3a3a3a", "#141414"],
                           body_bg=["#141414", "#0e0e0e"],
                           text_main="#ececec", text_muted="#9a9a9a"),
        fonts=DnaFonts(headline="Oswald", body="Barlow"),
        tone=DnaTone(voice="v", style="s",
                     forbidden=["BOMBA ve ŞOK gibi yıpranmış manşet klişeleri"],
                     sentence_max_words=14, paragraph_sentences=(3, 5),
                     body_max_chars=330),
        persona_summary="özet", search_query_template="{header_top}",
    )
    p = _prompt(dna=dna, trends_vertical="para")
    assert "yıpranmış manşet klişeleri" in p


# --- hashtag örneği sızıntısı --------------------------------------------------

def test_hashtag_ornegi_kanalin_kendi_kelimelerinden_gelir():
    """Kodun kendi notu: 'model ÖRNEĞİ kopyalar, kural metnini değil' — sabit
    haber örneği (#速報 #ニュース) magazin kanalına sızıyordu. Kanalın kendi
    anahtar kelimeleri varsa örnek ONLARDAN kurulmalı: hem dile hem dikeye
    doğru, tanım gereği."""
    p = _prompt(language="ja", trends_vertical="magazin",
                keywords=["芸能ニュース", "エンタメ", "解説"])
    assert "#芸能ニュース" in p
    assert "#速報" not in p, "sabit haber örneği magazin kanalına sızmış"


def test_anahtar_kelimesiz_kanalda_dil_varsayilani_kalir():
    """Kelimesi olmayan kanal eski davranışta kalmalı."""
    p = _prompt(language="ja", keywords=[])
    assert "#速報" in p


def test_kaynak_etiketi_kanalin_dilinde():
    """CANLI VAKA (2026-08-22, Japonca ilk metadata): açıklamada 'Kaynak:
    Yahoo!ニュース' çıktı — 'Kaynak' Türkçe. Model KURAL metnini değil ÖRNEĞİ
    kopyalar; örnek Türkçe sabitti. locale.UI_LABELS'ta karşılığı zaten var."""
    p = _prompt(language="ja", trends_vertical="magazin")
    assert "出典" in p, "Japonca kaynak etiketi prompt'ta yok"
    assert "Kaynak: {outlet}" not in p, "Türkçe kaynak örneği hâlâ sabit"


def test_almanca_kaynak_etiketi():
    p = _prompt(language="de")
    assert "Quelle" in p
