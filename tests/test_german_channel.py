"""Almanca gündem kanalı: arketip, şablonlar, dil kuralları.

Bu dosya çok dilli kurulumun SESSİZ tuzaklarını kilitler. Hepsi canlı üretimde
görüldü (2026-08-20, Deutschland Kompakt / Klartext ilk koşuları):

  1. Olgu kapısı Almancada her sıradan adı "uydurma" sayıyordu — Almanca TÜM
     adları büyük harfle yazar.
  2. Panel önizlemesi dil bağlamı açmadığı için 'späte' → 'spate' oluyordu.
  3. Uzun bileşik adlar iki satıra çıkınca alt kuşak gövdenin üstüne biniyordu.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from short_bot.config import load_channel
from short_bot.models import Highlight, RenderJob, Script
from short_bot.renderer import build_html
from short_bot.text_normalize import language as lang_context


# --- arketip -------------------------------------------------------------------

def test_eilmeldung_arketibi_kayitli():
    from short_bot.dna import ARCHETYPES, ARCHETYPE_DEFAULTS
    from short_bot.pexels import ARCHETYPE_BG_QUERIES
    assert "eilmeldung" in ARCHETYPES
    d = ARCHETYPE_DEFAULTS["eilmeldung"]
    # Mavi+kırmızı: Türk 'flas' arketibinin kırmızı+sarısı Alman haber kodu değil.
    assert d["primary"] == "#0b3b73" and d["accent"] == "#e2001a"
    # Fira: Almanca bileşik adlar için condensed grotesk şart.
    assert d["font_headline"] == "Fira Sans Condensed"
    assert ARCHETYPE_BG_QUERIES["eilmeldung"]


def test_her_iki_sablon_da_var():
    """Seslendirmeli biçim <template>-narrator kademesini kullanır; ikizi yoksa
    genel şablona düşer ve kanal kimliğini kaybeder."""
    assert Path("templates/eilmeldung.html.j2").exists()
    assert Path("templates/eilmeldung-narrator.html.j2").exists()


# --- kanal ayarları -------------------------------------------------------------

def test_kart_kanali_almanya_icin_ayarli():
    c = load_channel(Path("config/channels/deutschland-kompakt.yaml"))
    assert c.language == "de" and c.trends_region == "DE"
    assert c.content_source == "trends" and c.template == "eilmeldung"
    # Kart AKIŞ içindir → saf olay; soru niyetli konu Klartext'e kalır.
    assert c.trends_intent == "breaking"
    # Sunucu Europe/Istanbul; Alman günü 07-22 olsun diye cron 1 saat ileri.
    assert c.schedule_cron.startswith("0 8-23/")


def test_yorum_kanali_kart_kanaliyla_es_ama_ayri_niyette():
    k = load_channel(Path("config/channels/deutschland-klartext.yaml"))
    assert k.language == "de" and k.trends_intent == "question"
    assert k.voice.enabled and k.voice.provider in ("cartesia", "ai33")
    # Aynı YouTube kanalı: kimlik/kota/istatistik tek yerde. Bu ayar panelden
    # kaydedince SESSİZCE siliniyordu (bkz. test_web_yorum_edit).
    assert k.youtube.credentials_from == "deutschland-kompakt"


def test_yorum_personasi_almanca_ve_pressekodex_tasiyor():
    k = load_channel(Path("config/channels/deutschland-klartext.yaml"))
    p = k.voice.persona
    # Persona ALMANCA yazılmış olmalı — Türkçe personanın çevirisi değil.
    assert "parteilos" in p and "Du kommentierst" in p
    for needle in ("Bürgerinnen", "Pressekodex", "mutmaßlich", "Der Reihe nach"):
        assert needle in p, needle
    assert "sokak bilgesi" not in p


# --- dil kuralları ---------------------------------------------------------------

def test_yasak_kaliplar_dile_ozgu():
    """Almanca kanala Türkçe yasak koymak boşa kürek; Almancanın kendi klişesi
    'Es bleibt abzuwarten'dır."""
    from short_bot.narration_writer import banned_phrases
    de = banned_phrases("de")
    assert "Es bleibt abzuwarten" in de and "Google Trends" in de
    assert "Peki sizce" not in de
    assert "Peki sizce" in banned_phrases("tr")
    assert banned_phrases("es") == ()          # listesi yoksa yasak da yok


def test_varsayilan_persona_bilinmeyen_dilde_turkce_dondurmez():
    """Çok dilli tuzakların en sinsisi: bilinmeyen dilde Türkçe metin dönüp
    Almanca sese Türkçe okutmak."""
    from short_bot.narration_writer import default_yorum_persona
    assert default_yorum_persona("de").startswith("Du kommentierst")
    assert default_yorum_persona("tr").startswith("Sen Türkiye")
    assert default_yorum_persona("es") == ""


def test_olgu_kapisi_almanca_siradan_adlari_uydurma_saymaz():
    """CANLI VAKA: kapı ['Überläufer','Reihe','Konkurrenz','Streit','Wechsel',
    'Kontoauszug'] deyip boşuna bir yeniden yazım turu harcadı."""
    from short_bot.fact_gate import unverified_claims
    anlatim = ("Der Streit in der CDU geht weiter. Ein Wechsel ist nicht geplant. "
               "Die Konkurrenz beobachtet den Kontoauszug genau. "
               "Viele sehen ihn als Überläufer. Der Tornado beschädigte 60 Häuser.")
    kaynak = ("Die CDU prüft ein Verfahren. Ein Tornado zog über die Region. "
              "60 Häuser wurden beschädigt.")
    assert unverified_claims(anlatim, kaynak, language="de") == []


def test_olgu_kapisi_almancada_gercek_uydurmayi_YAKALAR():
    """Gevşetme kapıyı körleştirmemeli."""
    from short_bot.fact_gate import unverified_claims
    kaynak = "Die CDU prüft ein Verfahren gegen den Bürgermeister."
    assert "Scholz" in unverified_claims(
        "Auch Olaf Scholz äußerte sich zu dem Verfahren.", kaynak, language="de")


def test_turkce_olgu_kapisi_degismedi():
    from short_bot.fact_gate import unverified_claims
    kaynak = "Galatasaray, Batrakov ile anlaştı."
    assert unverified_claims("Galatasaray Batrakov ile anlaştı.", kaynak) == []
    # NOT: cümle BAŞINDAKİ ad, metinde başka yerde de geçmedikçe aday sayılmaz
    # (mevcut kural — halk dili personasının "Yav bak şimdi" açılışları yüzünden).
    assert "Mourinho" in unverified_claims(
        "Galatasaray Batrakov ile anlaştı. Ayrıca Mourinho da geliyor.", kaynak)


def test_panel_ornegi_aksanlari_korur():
    """Önizleme dil bağlamı açmıyordu: 'späte' → 'spate', 'año' → 'ano'."""
    from short_bot.web.routes.preview import _load_sample_script
    assert "späte" in _load_sample_script("de").body_paragraph
    assert "decisión" in _load_sample_script("es").body_paragraph
    assert "décision" in _load_sample_script("fr").body_paragraph


# --- şablon --------------------------------------------------------------------

def _job(cfg, header_top="STENDAL", header_bottom="CDU-BÜRGERMEISTER SPENDET"):
    with lang_context("de"):
        script = Script(
            header_top=header_top, header_bottom=header_bottom,
            photo_overlay="BEHÖRDE: ZWÖLF CHARGEN BETROFFEN",
            body_paragraph=("Die Lebensmittelüberwachungsbehörde hat einen bundesweiten "
                            "Rückruf veranlasst. Betroffen sind zwölf Chargen."),
            highlights=[Highlight(text="zwölf Chargen", color="red")],
            category="Rückruf", mood="breaking")
    return RenderJob(script=script, channel_colors=cfg.colors, handle=cfg.handle,
                     duration_s=6, language="de", bg_image_path=None, music_path=None,
                     rss_source="Tagesschau",
                     ticker_items=("Unwetter in Rheinland-Pfalz", "Zverev scheitert"))


def _html(template: str) -> str:
    from short_bot.dna import build_css_override
    from short_bot.locale import ui_labels_for
    cfg = load_channel(Path("config/channels/deutschland-kompakt.yaml"))
    return build_html(_job(cfg), Path(f"templates/{template}"),
                      ui_labels=ui_labels_for("de"),
                      dna_css=build_css_override(cfg.dna),
                      now=datetime(2026, 8, 20, 14, 32))


@pytest.mark.parametrize("tpl", ["eilmeldung.html.j2", "eilmeldung-narrator.html.j2"])
def test_sablon_alman_haber_grameri(tpl):
    html = _html(tpl)
    assert 'lang="de"' in html                       # tireleme sözlüğü buna bağlı
    assert "EILMELDUNG" in html                      # locale.UI_LABELS['de']
    assert "Stand: 20.08.2026, 14:32 Uhr" in html    # Alman tarih damgası
    assert "Quelle: Tagesschau" in html
    assert "hyphens: auto" in html                   # bileşik adlar için ŞART
    assert "'+++'" in html                           # dpa/teletext ayracı
    assert "Weiter" in html                          # ticker etiketi Almanca
    assert "ä" in html or "ö" in html or "ü" in html  # aksanlar sağ


@pytest.mark.parametrize("tpl", ["eilmeldung.html.j2", "eilmeldung-narrator.html.j2"])
def test_sablon_uzun_mansette_govdeyi_asagi_kaydirir(tpl):
    """Manşet iki satıra çıkınca alt kuşak gövdeye biniyordu — ölçüp taşıyoruz."""
    html = _html(tpl)
    assert "getBoundingClientRect" in html
    assert "body.style.top" in html


def test_renderer_baglama_now_gecirir():
    """Şablonun kendi biçiminde damgalayabilmesi için."""
    html = _html("eilmeldung.html.j2")
    assert "20.08.2026" in html


def test_metadata_hashtag_ornegi_dile_ozgu():
    """Örnek Türkçe sabit kalınca Almanca kanalın etiketlerine '#sondakika'
    sızıyordu: model KURAL metnini değil ÖRNEĞİ kopyalar."""
    from short_bot.youtube.metadata_writer import build_metadata_prompt

    class _De:
        name = "Deutschland Kompakt"; handle = "@deutschlandkompakt"; language = "de"
        keywords = ["Nachrichten"]; reel = None; slug = "deutschland-kompakt"

    p = build_metadata_prompt(channel=_De(), script={"body_paragraph": "x"},
                              rss_source="Spiegel", rss_link="https://spiegel.de/1")
    assert "#eilmeldung" in p and "#nachrichten" in p
    assert "#sondakika" not in p

    class _Tr(_De):
        language = "tr"; handle = "@gundem"

    assert "#sondakika" in build_metadata_prompt(
        channel=_Tr(), script={"body_paragraph": "x"}, rss_source=None, rss_link=None)


# --- kardeş kanal kısıtı ---------------------------------------------------------

def test_kardes_kanal_ayni_olayi_ikinci_kez_anlatmaz(tmp_path):
    """ÖLÇÜLDÜ: Alman trendlerinde soru sorgusu oranı %0 (Türkçede %8), yani
    trends_intent tercihi Almancada neredeyse hiç bağlamıyor ve iki format aynı
    olaya düşüyordu — TEK YouTube kanalında aynı haberin iki videosu."""
    import json
    import logging
    from datetime import datetime, timedelta
    from short_bot.db import init_db, record_short
    from short_bot.models import NewsItem
    from short_bot.pipeline import _drop_sibling_coverage

    eng = init_db(tmp_path / "t.sqlite")
    record_short(eng, channel="deutschland-kompakt", rss_item_guid="https://a/1",
                 title="STENDAL", file_path="f.mp4", duration_s=6,
                 script_json=json.dumps({}), render_ms=1)
    items = [NewsItem(guid="https://a/1", title="CDU spendet an AfD", link="l",
                      source="s", pub_date=None, thumb_url=None, description="d"),
             NewsItem(guid="https://b/2", title="Unwetter in Hessen", link="l",
                      source="s", pub_date=None, thumb_url=None, description="d")]
    klartext = load_channel(Path("config/channels/deutschland-klartext.yaml"))
    kalan = _drop_sibling_coverage(items, channel=klartext, eng=eng,
                                   log=logging.getLogger("t"))
    assert [i.guid for i in kalan] == ["https://b/2"]

    # Kimliği ödünç ALMAYAN kanal etkilenmez: ayrı kanallar aynı olayı işleyebilir.
    kart = load_channel(Path("config/channels/deutschland-kompakt.yaml"))
    assert len(_drop_sibling_coverage(items, channel=kart, eng=eng,
                                      log=logging.getLogger("t"))) == 2


def test_kardes_kisiti_kanali_susturmaz(tmp_path):
    """Havuzun TAMAMI kardeş tarafından işlenmişse boş dönmek yerine eski
    davranışa düşülür — kanalın hiç üretmemesi daha kötü."""
    import json
    import logging
    from short_bot.db import init_db, record_short
    from short_bot.models import NewsItem
    from short_bot.pipeline import _drop_sibling_coverage

    eng = init_db(tmp_path / "t.sqlite")
    record_short(eng, channel="deutschland-kompakt", rss_item_guid="https://a/1",
                 title="T", file_path="f.mp4", duration_s=6,
                 script_json=json.dumps({}), render_ms=1)
    items = [NewsItem(guid="https://a/1", title="X", link="l", source="s",
                      pub_date=None, thumb_url=None, description="d")]
    klartext = load_channel(Path("config/channels/deutschland-klartext.yaml"))
    assert len(_drop_sibling_coverage(items, channel=klartext, eng=eng,
                                      log=logging.getLogger("t"))) == 1


def test_kardes_kisiti_24_saatlik_pencereyle_sinirli(tmp_path):
    """Saat dilimi tuzağı: shorts.created_at NAİF UTC saklanıyor. Farkındalıklı
    bir datetime ile karşılaştırmak pencereyi sessizce kaydırır — dünkü haber
    sonsuza dek engellenir ya da hiç engellenmez."""
    import json
    import logging
    from datetime import timedelta
    from sqlalchemy import update
    from short_bot.db import init_db, record_short, shorts, _utcnow
    from short_bot.models import NewsItem
    from short_bot.pipeline import _drop_sibling_coverage

    eng = init_db(tmp_path / "t.sqlite")
    sid = record_short(eng, channel="deutschland-kompakt", rss_item_guid="https://eski/1",
                       title="ESKİ", file_path="f.mp4", duration_s=6,
                       script_json=json.dumps({}), render_ms=1)
    eski = (_utcnow() - timedelta(hours=25)).replace(tzinfo=None)
    with eng.begin() as c:
        c.execute(update(shorts).where(shorts.c.id == sid).values(created_at=eski))

    items = [NewsItem(guid="https://eski/1", title="25 saat önceki olay", link="l",
                      source="s", pub_date=None, thumb_url=None, description="d"),
             NewsItem(guid="https://yeni/2", title="Yeni olay", link="l",
                      source="s", pub_date=None, thumb_url=None, description="d")]
    klartext = load_channel(Path("config/channels/deutschland-klartext.yaml"))
    kalan = _drop_sibling_coverage(items, channel=klartext, eng=eng,
                                   log=logging.getLogger("t"))
    # 25 saat önce anlatılan olay artık serbest (takip/gelişme meşru).
    assert {i.guid for i in kalan} == {"https://eski/1", "https://yeni/2"}


@pytest.mark.parametrize("cumle", [
    "Ein Todesfall, zwei Schwerverletzte.",
    "Der Todesfall in Waldorf wirft Fragen auf.",
    "Nach dem tragischen Todesfall ermittelt die Polizei.",
    "Ein plötzlicher Todesfall trifft die Gemeinde.",
    "Die Menschen stehen unter Schock, vor Ort helfen Rettungskräfte.",
    "Nach Angaben der Feuerwehr gab es einen Todesfall.",
])
def test_olgu_kapisi_almanca_deyim_ve_sifatli_adlari_gecirir(cumle):
    """KULLANICI BİLDİRİMİ (2026-08-20, 19:35): 'Todesfall' iki turda da
    düzelmedi ve VİDEO ÜRETİLMEDİ. Belirteç kuralı yetmiyordu — Almancada sıfat
    araya giriyor ('ein plötzlicher Todesfall') ve deyimler belirteçsiz kuruluyor
    ('unter Schock', 'vor Ort', 'nach Angaben')."""
    from short_bot.fact_gate import unverified_claims
    kaynak = "Bei einem Unwetter starb eine Frau. Die Polizei ermittelt."
    assert unverified_claims(cumle, kaynak, language="de") == []


@pytest.mark.parametrize("cumle,beklenen", [
    ("Auch Olaf Scholz äußerte sich zu dem Verfahren.", "Scholz"),
    ("Der Bericht stammt vom ZDF Magazin Royale.", "ZDF"),
])
def test_olgu_kapisi_almancada_uydurma_adlari_hala_yakalar(cumle, beklenen):
    """Gevşetme kapıyı körleştirmemeli: kişi/kurum adları ya iki sözcüklü ya
    kısaltmadır, ikisi de aday kalır."""
    from short_bot.fact_gate import unverified_claims
    kaynak = "Die Polizei ermittelt nach einem Unwetter."
    assert beklenen in unverified_claims(cumle, kaynak, language="de")


def test_olgu_kapisi_almanca_BILINEN_BOSLUK_tek_sozcuklu_ad():
    """BİLİNEN VE KABUL EDİLEN BOŞLUK — gizlenmesin diye testle yazılı.

    Almancada tek başına duran büyük harfli sözcük özel ad KANITI DEĞİLDİR
    ('unter Schock' ile 'in Karlsruhe' aynı yapıda). Kapı bu yüzden tek
    sözcüklü adı yakalamıyor. Takas bilinçli: iki günde iki kez video
    kaybetmektense ('Todesfall'), nadir bir tek-sözcüklü yer adı kaçsın.
    Uydurmanın asıl biçimleri — iki sözcüklü kişi/kurum adları, kısaltmalar ve
    SAYILAR — yakalanmaya devam ediyor."""
    from short_bot.fact_gate import unverified_claims
    kaynak = "Die Polizei ermittelt nach einem Unwetter."
    assert unverified_claims("Die Sache landete in Karlsruhe.", kaynak,
                             language="de") == []
    # Sayı kaçmaz — dilden bağımsız denetim:
    assert "42" in unverified_claims("Es gab 42 Verletzte.", kaynak, language="de")
