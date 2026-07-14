"""Planlı ark: seriyi KEŞFETMEK yerine TASARLAMAK.

Zincirin iki zayıflığı vardı:
  • SAPMA BİRİKİMLİ — her bölüm bir öncekinin kapısından doğduğu için küçük sapmalar
    üst üste biniyor.
  • VAAT TEK ADIM — "sıradakinde şunu anlatacağım" diyebiliyoruz ama "bu 3 bölümlük
    bir seri" diyemiyoruz. Oysa izleyici bir VİDEOYA değil bir SERİYE abone olur.

Planlı arkta bir sonraki bölümün konusu PLANDA YAZILI → LLM cliffhanger'ı UYDURMAZ,
SÖYLER. Konu sapması yapısal olarak imkânsız.
"""
import pytest

from short_bot.reel_arc import (MAX_ARC, MIN_ARC, ArcEpisode, ArcPlan,
                                _fallback_title, plan_arc, suggest_series_title,
                                validate_plan)
from short_bot.reel_series import EpisodePlan, series_directive

# Metinler artık DİL PAKETİNDE (tr.json = eski sabitlerin birebir kopyası;
# bkz. test_lang_pack_tr_golden.py). Beklentiler DEĞİŞMEDİ.
from short_bot.lang_pack import load_pack
TR = load_pack("tr")



def _plan(n=3, title="Kedilerin Gizli Biyolojisi"):
    return ArcPlan(title=title, episodes=[
        ArcEpisode(topic=f"Bolum {i} konusu: somut ve uretilebilir bir konu",
                   promise=f"Bolum {i} icin verilen soz") for i in range(1, n + 1)])


# --- PLAN DOĞRULAMA --------------------------------------------------------

def test_ilk_bolumun_vaadi_BOSALTILIR():
    """İlk bölümün 'promise'i anlamsız: ondan önce bir bölüm yok."""
    p = validate_plan(_plan(3), n=3)
    assert p.episodes[0].promise == ""
    assert p.episodes[1].promise, "sonraki bölümlerin vaadi durmalı"


def test_fazla_bolum_ORTADAN_atilir():
    """Sondan kırpmak SON bölümü (en vurucu olanı) atardı; baştan kırpmak kancayı."""
    p = _plan(5)
    ilk, son = p.episodes[0].topic, p.episodes[-1].topic
    k = validate_plan(p, n=3)
    assert len(k.episodes) == 3
    assert k.episodes[0].topic == ilk, "kanca (ilk bölüm) atılmamalı"
    assert k.episodes[-1].topic == son, "tepe (son bölüm) atılmamalı"


def test_eksik_bolum_oldugu_gibi_kabul():
    """Kısa ama tutarlı bir ark, uydurulmuş bir bölümden iyidir."""
    k = validate_plan(_plan(2), n=4)
    assert len(k.episodes) == 2


def test_ark_sinirlari_makul():
    assert MIN_ARC >= 2 and MAX_ARC <= 6


def test_llm_hatasi_None_doner():
    class _Patlar:
        claude_path = "x"; model = "m"; backend = "b"; api_key = None

    class _Ch:
        name = "K"
        generator = None

    import short_bot.reel_arc as m

    def _patla(*a, **kw):
        raise RuntimeError("LLM yok")

    orig = m.run_json
    m.run_json = _patla
    try:
        assert plan_arc("konu", channel=_Ch(), n=3, llm_call=_Patlar()) is None
    finally:
        m.run_json = orig


def test_plan_arc_LLM_i_cagirir_ve_dogrular(monkeypatch):
    import short_bot.reel_arc as m

    class _Ch:
        name = "Bilim"
        generator = None

    class _LC:
        claude_path = "x"; model = "m"; backend = "b"; api_key = None

    monkeypatch.setattr(m, "run_json", lambda *a, **kw: _plan(5))
    p = plan_arc("kediler", channel=_Ch(), n=3, llm_call=_LC())
    assert p is not None
    assert len(p.episodes) == 3, "validate_plan n'e oturtmalı"
    assert p.episodes[0].promise == ""


# --- YÖNERGE: PLANLI vs ZİNCİR ---------------------------------------------

def test_PLANLI_arkta_kapi_UYDURULMAZ_dayatilir():
    """Modülün varlık sebebi: konu planda yazılı, LLM onu yalnız SÖYLÜYOR."""
    p = EpisodePlan(episode_no=2, arc_pos=2, next_topic="Kedi kulagindaki 32 kas",
                    arc_title="Kedilerin Gizli Biyolojisi", arc_total=3)
    d = series_directive(p, "Bilim Tarihi", pack=TR)
    assert "Kedi kulagindaki 32 kas" in d
    assert "PLANDA YAZILI, UYDURMA" in d
    assert "aynen yaz" in d


def test_PLANLI_arkin_ILK_bolumu_SERIYI_ILAN_eder():
    """İzleyici bir VİDEOYA değil bir SERİYE abone olur — 'N bölümlük seri' demek,
    tek adımlık bir vaatten çok daha güçlü bir abone sebebidir."""
    p = EpisodePlan(episode_no=1, arc_pos=1, next_topic="Sonraki konu",
                    arc_title="Kedilerin Gizli Biyolojisi", arc_total=3)
    d = series_directive(p, "Bilim Tarihi", pack=TR)
    assert "SERİYİ İLAN ET" in d
    assert "3 BÖLÜMLÜK" in d
    assert "Kedilerin Gizli Biyolojisi" in d


def test_arkin_SON_bolumu_odenmemis_vaat_BIRAKMAZ():
    """Plan bitti → kapı yok. Ama seri bitmiyor: sıradaki bölüm yeni bir konuyla gelir."""
    p = EpisodePlan(episode_no=3, arc_pos=3, next_topic="",
                    arc_title="Kedilerin Gizli Biyolojisi", arc_total=3)
    assert p.is_arc_finale
    d = series_directive(p, "Bilim Tarihi", pack=TR)
    assert "SON BÖLÜMÜ" in d
    assert "BOŞ bırak" in d
    assert "4. bölümün" in d, "seri devam etmeli (numara ilerler)"


def test_ZINCIR_modunda_eski_yonerge_aynen_surer():
    p = EpisodePlan(episode_no=5, arc_pos=2, continue_from="Onceki kapi")
    assert not p.is_planned
    d = series_directive(p, "Bilim Tarihi", pack=TR)
    assert "open_loop" in d
    assert "PLANDA YAZILI" not in d
    assert "SERİYİ İLAN ET" not in d


# --- BAŞLIK ÖNERİSİ --------------------------------------------------------

def test_LLM_yoksa_kanal_adina_dusulur():
    class _Ch:
        name = "Bilim Tarihinin Sok Anlari"
        dna = None
    assert suggest_series_title(_Ch(), None) == "Bilim Tarihinin Sok"


def test_fallback_baslik_bos_kanalda_cokmez():
    class _Ch:
        name = ""
    assert _fallback_title(_Ch()) == ""


def test_baslik_LLM_den_gelir(monkeypatch):
    import short_bot.reel_arc as m

    class _Dna:
        persona_summary = "Bilim tarihinin sok anlari"

    class _Ch:
        name = "Bilim"
        dna = _Dna()
        generator = None

    class _LC:
        claude_path = "x"; model = "m"; backend = "b"; api_key = None

    class _R:
        title = "Bilinmeyen Bilim"

    monkeypatch.setattr(m, "run_json", lambda *a, **kw: _R())
    assert suggest_series_title(_Ch(), _LC()) == "Bilinmeyen Bilim"


def test_baslik_LLM_hatasinda_kanal_adina_duser(monkeypatch):
    import short_bot.reel_arc as m

    class _Dna:
        persona_summary = "x"

    class _Ch:
        name = "Bilim Tarihi Kanali"
        dna = _Dna()
        generator = None

    class _LC:
        claude_path = "x"; model = "m"; backend = "b"; api_key = None

    def _patla(*a, **kw):
        raise RuntimeError("yok")

    monkeypatch.setattr(m, "run_json", _patla)
    assert suggest_series_title(_Ch(), _LC()) == "Bilim Tarihi Kanali"
