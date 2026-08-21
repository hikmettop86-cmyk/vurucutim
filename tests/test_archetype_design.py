"""Arketip tasarım akışı: LLM → kapılar → kaydet (ya da kaydetme).

EN ÖNEMLİ DAVRANIŞ: üç turda kapılardan geçemeyen şablon KAYDEDİLMEZ.
Geçen her şablon diskte kalıcı dosya olur; "olsun bari" diye yazmak, 40
kalıbın yanına 41'inci bozuk kalıbı eklemek ve onu kimsenin temizlememesi
demektir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_archetype_gate import GECERLI


@pytest.fixture
def sablonlar(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    for ad in ("newscast", "flas"):
        (d / f"{ad}.html.j2").write_text(GECERLI, encoding="utf-8")
    return d


def _render_ok(yol, metinler):
    """Her uç metin için bir 'kare' üretir (dosya varlığı yeterli)."""
    out = []
    for i, _ in enumerate(metinler):
        p = Path(yol).parent / f"kare{i}.png"
        p.write_bytes(b"x")
        out.append(p)
    return out


def test_gecerli_sablon_kaydedilir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("siyah beyaz, eğik bant", ad="Beşiktaş Mono",
                templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda yol: {"sorun": False},
                render_fn=_render_ok)
    assert s.ok, s.sebep
    assert (sablonlar / f"{s.slug}.html.j2").exists()
    assert s.tur == 1


def test_yapi_kapisindan_gecemeyen_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Bozuk", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: "<!DOCTYPE html><html><body>yok</body></html>",
                vision_call=lambda yol: {"sorun": False},
                render_fn=_render_ok)
    assert not s.ok
    assert not (sablonlar / "bozuk.html.j2").exists()
    assert s.tur == 3, "üç tur denenmeliydi"


def test_vision_reddederse_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Tasan", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda yol: {"sorun": True, "aciklama": "manşet kesik"},
                render_fn=_render_ok)
    assert not s.ok
    assert "manşet kesik" in s.sebep
    assert not (sablonlar / "tasan.html.j2").exists()


def test_vision_YOKSA_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    """Fail-closed: denetlenmemiş arketip diske yazılmaz."""
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Denetimsiz", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI, vision_call=None,
                render_fn=_render_ok)
    assert not s.ok
    assert not (sablonlar / "denetimsiz.html.j2").exists()


def test_red_sebebi_BIR_SONRAKI_TURA_yazilir(sablonlar, monkeypatch, tmp_path):
    """Kapı 'geçmedi' demekle kalmamalı; sebep prompt'a girmeli ki tur boşa
    gitmesin."""
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    promptlar = []

    def _llm(p):
        promptlar.append(p)
        return "<!DOCTYPE html><html><body>yok</body></html>"

    tasarla("x", ad="A", templates_dir=sablonlar, settings=None, metin_llm=_llm,
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert len(promptlar) == 3
    assert "REDDEDİLDİ" in promptlar[1]
    assert "body-text" in promptlar[1], "eksik slot bir sonraki tura yazılmadı"


def test_ikinci_turda_duzelirse_kaydedilir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    n = {"i": 0}

    def _llm(p):
        n["i"] += 1
        return GECERLI if n["i"] == 2 else "<!DOCTYPE html><html></html>"

    s = tasarla("x", ad="Ikinci", templates_dir=sablonlar, settings=None,
                metin_llm=_llm, vision_call=lambda y: {"sorun": False},
                render_fn=_render_ok)
    assert s.ok and s.tur == 2


def test_markdown_citi_temizlenir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Citli", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: f"İşte şablon:\n```html\n{GECERLI}\n```\nUmarım olur.",
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert s.ok
    icerik = (sablonlar / f"{s.slug}.html.j2").read_text(encoding="utf-8")
    assert icerik.startswith("<!DOCTYPE html>")
    assert "Umarım olur" not in icerik


def test_YAPI_SPECTEN_gorunum_DILDEN_gelir(sablonlar, monkeypatch, tmp_path):
    """Bu test eskiden TERSİNİ sabitliyordu ("örnek şablonlar prompt'a girer").

    O tasarım kullanıcının şikâyetini üretiyordu: iki eski şablon tam metin
    veriliyor, model onlara demir atıyor, her çıktı aynı kalıba benziyordu.
    Üstelik o şablonlar gövdeyi kesen `line-clamp`'i içeriyor — kopyalanan şey
    hatanın kendisiydi.

    Yeni ayrım: YAPI TEMPLATE-SPEC'ten (bölüm 7 iskeleti), GÖRÜNÜM tasarım
    dilinden.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text(
        "SPEC-IMZASI bölüm 7 iskeleti", encoding="utf-8")
    from short_bot.archetype_design import tasarla
    p = {}
    tasarla("x", ad="A", templates_dir=sablonlar, settings=None,
            metin_llm=lambda pr: (p.setdefault("ilk", pr), GECERLI)[1],
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert "SPEC-IMZASI" in p["ilk"], "yapı sözleşmesi prompt'ta yok"
    assert "newscast.html.j2" not in p["ilk"]
    assert "flas.html.j2" not in p["ilk"]


def test_kaydedilen_arketip_ANINDA_GECERLI_olur(sablonlar, monkeypatch, tmp_path):
    """Kayıt, `dna.py`'nin OKUDUĞU dosyaya yazılmalı ve arketip yeniden
    başlatma beklemeden geçerli olmalı.

    Eski test CWD'ye göre yazılan dosyaya bakıyordu — yani hatanın kendisini
    sabitliyordu. Canlıda `dna.py` başka bir dosyayı, üstelik yalnız import
    anında okuduğu için kanal `unknown archetype` ile reddediliyordu.
    """
    import json
    import short_bot.dna as dna
    yol = tmp_path / "archetypes.json"
    yol.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(dna, "_REGISTRY_PATH", yol)
    for ad in ("ARCHETYPES", "ARCHETYPE_LABELS", "ARCHETYPE_DEFAULTS",
               "_DESIGNED_ARCHETYPES"):
        monkeypatch.setattr(dna, ad, type(getattr(dna, ad))(getattr(dna, ad)))
    monkeypatch.chdir(tmp_path)          # CWD kasten farklı

    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Yeni Kalıp", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert s.ok
    assert any(a["slug"] == s.slug
               for a in json.loads(yol.read_text(encoding="utf-8")))
    assert s.slug in dna.ARCHETYPES, "yeniden başlatmadan geçerli olmuyor"


# --- ADAY ŞABLON PAYLAŞILAN PARÇALARLA BİRLİKTE RENDER EDİLMELİ ------------
#
# CANLI ARIZA (2026-08-21, ilk gerçek koşu): aday şablon boş bir `tempfile`
# dizinine yazılıp oradan render ediliyordu. Jinja'nın arama yolu şablonun
# BULUNDUĞU dizin (`renderer.py`: FileSystemLoader(template_path.parent)) ve
# orada `_auto_fit.js.j2` yok → `{% include %}` HER denemede patlıyordu:
#
#     3 denemede kapılardan geçemedi. Son sebep: Render sırasında hata:
#     '_auto_fit.js.j2' not found in search path: '...\tmpb3ou2jv1'
#
# Yani Faz III hiçbir zaman çalışmamıştı. Testler sahte `render_fn` enjekte
# ettiği için görünmüyordu — sahte render dizine hiç bakmıyor.

def test_aday_sablon_PAYLASILAN_PARCALARLA_render_edilir(sablonlar, monkeypatch,
                                                         tmp_path):
    monkeypatch.chdir(tmp_path)
    (sablonlar / "_auto_fit.js.j2").write_text("// paylasilan", encoding="utf-8")
    gorulen: list[list[str]] = []

    def _render(yol, metinler):
        gorulen.append(sorted(p.name for p in Path(yol).parent.iterdir()))
        return _render_ok(yol, metinler)

    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Komsulu", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: GECERLI,
            vision_call=lambda yol: {"sorun": False}, render_fn=_render)
    assert gorulen, "render hiç çağrılmadı"
    assert "_auto_fit.js.j2" in gorulen[0], (
        "aday, paylaşılan parçaların yanında render edilmiyor — "
        f"dizinde yalnız {gorulen[0]}")


def test_render_dizini_TEMIZLENIR(sablonlar, monkeypatch, tmp_path):
    """Şablon dizinine geçici dosya bırakılmamalı: `templates/` kullanıcının
    deposu, 41'inci kalıp orada durmasın."""
    monkeypatch.chdir(tmp_path)
    (sablonlar / "_auto_fit.js.j2").write_text("// paylasilan", encoding="utf-8")
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Temiz", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda yol: {"sorun": False}, render_fn=_render_ok)
    kalanlar = sorted(p.name for p in sablonlar.iterdir())
    assert kalanlar == ["_auto_fit.js.j2", "flas.html.j2", "newscast.html.j2",
                        f"{s.slug}.html.j2"], kalanlar


# --- MODEL SÖZLEŞMENİN TAMAMINI GÖRMELİ -----------------------------------
#
# ÖLÇÜLDÜ (2026-08-21): prompt `TEMPLATE-SPEC.md`'yi ilk 6000 karaktere
# kırpıyordu. Ama metni kutuya SIĞDIRMA sözleşmesi çok sonra başlıyor:
#
#     body-text        8531. karakter
#     data-fit-min     8542
#     _auto_fit.js.j2  8836
#     data-fit-width   9321
#     "Zorunlu öğeler" 13345
#
# Yani model, taşmayı önleyen tek mekanizmayı HİÇ görmüyordu ve vision kapısı
# ilk gerçek koşuda üç turun üçünü de "manşet kutusuna sığmayıp kesilmiş"
# diye reddetti. Şans değil, kaçınılmazdı. Spec 14 KB — Opus için hiçbir şey.

def test_prompt_SPECIN_TAMAMINI_tasir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    imza = "SIGDIRMA-SOZLESMESI-BURADA"
    (tmp_path / "TEMPLATE-SPEC.md").write_text(
        "x" * 9000 + imza + "y" * 4000, encoding="utf-8")
    gorulen: list[str] = []

    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Spec", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda yol: {"sorun": False}, render_fn=_render_ok)
    assert gorulen, "model hiç çağrılmadı"
    assert imza in gorulen[0], (
        "spec kırpılıyor — sığdırma sözleşmesi modele hiç ulaşmıyor")


def test_prompt_SPEC_KIRPILMADAN_gider(sablonlar, monkeypatch, tmp_path):
    """Sözleşme kırpılmamalı: yapı ARTIK yalnız oradan öğreniliyor."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text(
        "bas" + "x" * 12000 + "SON-IMZA", encoding="utf-8")
    gorulen: list[str] = []
    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Ornek", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda yol: {"sorun": False}, render_fn=_render_ok)
    assert "bas" in gorulen[0] and "SON-IMZA" in gorulen[0]


# --- MODEL NEYE GÖRE YARGILANDIĞINI BİLMELİ --------------------------------
#
# ÖLÇÜLDÜ (2026-08-21): prompt kabul ölçütünü hiç söylemiyordu. Daha kötüsü,
# "ÇALIŞAN ÖRNEKLER — yapıyı bunlardan al" diye verilen üç şablonun ÜÇÜ DE
# vision kapısından geçmiyor (aynı uç metinlerle sınandı):
#
#   stadium  REDDEDİLDİ  manşet sağ kenarda kesilmiş, SON DAKİKA rozetiyle
#                        çakışıyor, gövdenin son satırı solarak kesiliyor
#   flas     REDDEDİLDİ  bant ve şerit gövde metninin üstüne binmiş
#   newscast REDDEDİLDİ  gövdenin son satırı alt kenarda yarıya kesilmiş
#
# Yani örneği birebir taklit etmek REDDEDİLMEK demekti ve model bunu
# bilmiyordu.

def test_prompt_KABUL_OLCUTUNU_ve_UZUNLUKLARI_soyler(sablonlar, monkeypatch,
                                                     tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    gorulen: list[str] = []
    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Olcut", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda yol: {"sorun": False}, render_fn=_render_ok)
    p = gorulen[0]
    for beklenen in ("25", "35", "40", "300"):
        assert beklenen in p, f"sığdırılacak uzunluk {beklenen} söylenmiyor"
    assert "data-fit-width" in p
    # NOT: `str.lower()` Türkçe değil ("TAŞIYOR" → "taşiyor"); büyük harfle ara.
    assert "TAŞIYOR" in p and "GEÇMİYOR" in p, (
        "örneklerin bu kapıdan geçmediği söylenmiyor — model onları taklit eder")


def test_slug_TURKCE_HARFLERI_dusurmez():
    """Şablon adı KALICI dosya adı. `re.sub("[^a-zA-Z0-9]+", "-", ...)` Türkçe
    harfleri komple siliyordu: canlıda "Bayern Münih" → `bayern-m-nih.html.j2`
    (ü düştü, yerine tire kaldı). `channel_chat._slugify` bunu doğru yapıyor —
    aynı eşleme tablosu burada da olmalı."""
    from short_bot.archetype_design import _slugify
    assert _slugify("Bayern Münih") == "bayern-munih"
    assert _slugify("Beşiktaş Gündem") == "besiktas-gundem"
    assert _slugify("Işık & Gölge") == "isik-golge"
    assert _slugify("") == "arketip"


# --- ESKİ ŞABLONLARDAN BAĞIMSIZLIK -----------------------------------------
#
# KULLANICI KURALI (2026-08-21): "yeni oluşturduklarımız sıfır, onlardan
# bağımsız olmalı" + "şablonlar birbirine benzemesin".
#
# Prompt iki ESKİ ŞABLONU tam metin veriyordu ("yapıyı bunlardan al"). Model
# onlara demir atıyor, üretilen her şablon aynı kalıba benziyordu. Üstelik o
# şablonlar gövdeyi kesen `line-clamp`'i içeriyordu — yani kopyalanan şey
# hatanın kendisiydi.

def test_prompt_ESKI_SABLONLARI_ARTIK_VERMEZ(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    gorulen: list[str] = []
    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Bagimsiz", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    p = gorulen[0]
    assert "newscast.html.j2" not in p and "flas.html.j2" not in p
    assert GECERLI[:200] not in p, "örnek şablon gövdesi hâlâ prompt'ta"


def test_prompt_TASARIM_DILINI_tasir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    (sablonlar / "design").mkdir()
    (sablonlar / "design" / "testdili.md").write_text(
        "---\nname: Test Dili\ndescription: kalin siyah beyaz\n---\n"
        "## Colors\nsiyah\n## Components\nbuton\n", encoding="utf-8")
    gorulen: list[str] = []
    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Dilli", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok,
            yon="testdili")
    p = gorulen[0]
    assert "Test Dili" in p and "kalin siyah beyaz" in p
    assert "## Components" not in p, "ayıklanmamış"
    assert "1080" in p, "tuval çapaları yok"


def test_yon_VERILMEZSE_de_calisir(sablonlar, monkeypatch, tmp_path):
    """Dil kütüphanesi yoksa üretim durmamalı."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Dilsiz", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert s.ok


# --- ÜÇ ADAY, KULLANICI SEÇER ----------------------------------------------
#
# KULLANICI KARARI (2026-08-21): "3 aday üret, ben seçeyim".
# Ücretsiz havuzda bir aday ~7 sn, yani üç aday ucuz. Her adaya FARKLI bir
# tasarım dili verilir → "şablonlar birbirine benzemesin".
#
# ADAYLAR DİSKE YAZILMAZ: seçilmeyen iki şablon `templates/`e düşerse orada
# kalır ve kimse temizlemez (aynı hata `archetypes.json`da yaşandı).

def test_kaydet_False_ise_DOSYA_YAZILMAZ(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Yazma", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok,
                kaydet=False, kanit_dir=tmp_path / "kanit")
    assert s.ok
    assert not (sablonlar / f"{s.slug}.html.j2").exists()
    assert s.html.startswith("<!DOCTYPE html>"), "html sonuçta taşınmıyor"
    assert s.kareler, "kareler sonuçta taşınmıyor"
    # Kareler TEMP dizinle birlikte silinmemeli — kullanıcı onlara bakacak.
    assert all(k.exists() for k in s.kareler)


def test_adaylar_HER_BIRINE_FARKLI_dil_verir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    d = sablonlar / "design"
    d.mkdir()
    for ad in ("bir", "iki", "uc", "dort"):
        (d / f"{ad}.md").write_text(
            f"---\nname: Dil {ad}\ndescription: {ad} dili\n---\n## Colors\nx\n",
            encoding="utf-8")
    gorulen: list[str] = []
    from short_bot.archetype_design import adaylar_uret
    a = adaylar_uret("x", ad="Kanal", templates_dir=sablonlar, settings=None,
                     metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
                     vision_call=lambda y: {"sorun": False},
                     render_fn=_render_ok, sayi=3, tohum="kanal")
    assert len(a) == 3
    assert len({x.yon for x in a}) == 3, "adaylar aynı dili kullanmış"
    diller = {g.split("Dil: ")[1].split("\n")[0] for g in gorulen if "Dil: " in g}
    assert len(diller) == 3, diller


def test_adaylar_DUSENI_de_dondurur(sablonlar, monkeypatch, tmp_path):
    """Bir aday kapıdan geçemezse ötekiler gösterilmeli; sessizce yutulmamalı."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    sayac = {"n": 0}

    def _llm(p):
        sayac["n"] += 1
        # tur=1 → aday başına TEK çağrı: 1. aday düşer, 2. aday geçer.
        return GECERLI if sayac["n"] > 1 else "<!DOCTYPE html><html></html>"

    from short_bot.archetype_design import adaylar_uret
    a = adaylar_uret("x", ad="K", templates_dir=sablonlar, settings=None,
                     metin_llm=_llm, vision_call=lambda y: {"sorun": False},
                     render_fn=_render_ok, sayi=2, tohum="t", tur=1)
    assert len(a) == 2
    assert not a[0].ok and a[0].sebep
    assert a[1].ok


def test_aday_kaydet_DOSYAYI_yazar_ve_KAYDA_ekler(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    import short_bot.dna as dna
    from short_bot.archetype_design import aday_kaydet, tasarla
    s = tasarla("x", ad="Seçilen", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok,
                kaydet=False)
    slug = aday_kaydet(s, ad="Seçilen", templates_dir=sablonlar)
    assert (sablonlar / f"{slug}.html.j2").exists()
    assert slug in dna.ARCHETYPES


def test_DUSEN_adayin_kareleri_de_saklanir(sablonlar, monkeypatch, tmp_path):
    """Kullanıcı NEDEN düştüğünü görmeli. Kare saklanmazsa elde yalnız vision'ın
    tek cümlesi kalıyor ve ne kullanıcı ne de biz bakabiliyoruz — canlıda üç
    aday düştü, hiçbirinin karesi yoktu (2026-08-21)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Dusen", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda y: {"sorun": True, "aciklama": "taştı"},
                render_fn=_render_ok, tur=1, kaydet=False,
                kanit_dir=tmp_path / "kanit")
    assert not s.ok
    assert s.kareler, "düşen adayın kareleri saklanmıyor"
    assert all(k.exists() for k in s.kareler)


# --- TASARLANAN ARKETİBİN GÖRSEL HAVUZU ------------------------------------
#
# ÖLÇÜLDÜ (2026-08-21): `register_designed_archetype` `pexels_queries: []`
# yazıyor. Kayıttaki 31 arketibin hepsinde dolu (galatasaray → "galatasaray
# stadium", eilmeldung → "berlin city street"), yalnız AI'ın ürettiği ikisi
# boş: `bursaspor-kart`, `amerika-gundemi`. Sonuç: o kanallar
# `pick_query_for_archetype`ın jenerik yedeğine ("abstract motion background")
# düşüyor — kanalın konusuyla ilgisi olmayan arka planlar.

def test_sorgular_INGILIZCE_ve_KONUYA_bagli():
    from short_bot.archetype_design import pexels_sorgulari
    cagri = {}

    def _llm(p):
        cagri["prompt"] = p
        return '["bursa stadium night", "green white fans", "turkish football crowd"]'

    q = pexels_sorgulari("Bursaspor Kart", keywords=["Bursaspor", "Timsah"],
                         persona="yeşil beyaz taraftar", metin_llm=_llm)
    assert q == ["bursa stadium night", "green white fans",
                 "turkish football crowd"]
    # NOT: prompt'ta büyük harfle geçiyor; `lower()` Türkçe değil.
    assert "Bursaspor" in cagri["prompt"] and "İNGİLİZCE" in cagri["prompt"]


def test_sorgular_LLM_PATLARSA_jenerik_dondurur():
    """Görsel havuzu yok diye şablon kaydı DURMAMALI."""
    from short_bot.archetype_design import pexels_sorgulari

    def _patla(p):
        raise RuntimeError("model yok")
    q = pexels_sorgulari("X", keywords=[], persona="", metin_llm=_patla)
    assert len(q) >= 3 and all(isinstance(x, str) for x in q)


def test_sorgular_BOZUK_CIKTIDA_jenerik():
    from short_bot.archetype_design import pexels_sorgulari
    q = pexels_sorgulari("X", keywords=[], persona="",
                         metin_llm=lambda p: "bu json degil")
    assert len(q) >= 3


def test_aday_kaydet_SORGULARI_kayda_yazar(sablonlar, monkeypatch, tmp_path):
    import json
    import short_bot.dna as dna
    monkeypatch.chdir(tmp_path)
    yol = tmp_path / "archetypes.json"
    yol.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(dna, "_REGISTRY_PATH", yol)
    for ad in ("ARCHETYPES", "ARCHETYPE_LABELS", "ARCHETYPE_DEFAULTS",
               "_DESIGNED_ARCHETYPES"):
        monkeypatch.setattr(dna, ad, type(getattr(dna, ad))(getattr(dna, ad)))
    from short_bot.archetype_design import aday_kaydet, tasarla
    s = tasarla("x", ad="Havuzlu", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok,
                kaydet=False)
    aday_kaydet(s, ad="Havuzlu", templates_dir=sablonlar,
                sorgular=["a shot", "b shot", "c shot"])
    kayit = json.loads(yol.read_text(encoding="utf-8"))
    assert kayit[0]["pexels_queries"] == ["a shot", "b shot", "c shot"]


def test_RED_SEBEBI_promptun_EN_SONUNDA(sablonlar, monkeypatch, tmp_path):
    """Sebep ortada kalınca model onu kaçırıyor: canlıda `stripe` adayı ÜÇ
    turda da aynı eksikle (`var(--text-main)`) düştü, oysa sebep her turda
    geri yazılıyordu. Model en son okuduğunu en iyi tutuyor."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    promptlar: list[str] = []
    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Sebep", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (promptlar.append(p),
                                 "<!DOCTYPE html><html></html>")[1],
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok,
            tur=2)
    assert len(promptlar) == 2
    son = promptlar[1]
    assert "REDDEDİLDİ" in son
    kuyruk = son[-900:]
    assert "REDDEDİLDİ" in kuyruk, "sebep prompt'un ortasında kalmış"


def test_prompt_TURKCE_ALT_UZANTI_kuralini_tasir(sablonlar, monkeypatch, tmp_path):
    """Ölçüldü: `line-height: 0.85` ile 'ŞOK' başlığının Ş çengeli alttaki
    satıra değdi ve vision 'üst üste binmiş' dedi. Satır kutusu harften küçük
    kalınca alt-uzantılı harfler komşu bloğa taşıyor."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    gorulen: list[str] = []
    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Uzanti", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    p = gorulen[0]
    assert "line-height" in p
    assert "Ş" in p and "Ğ" in p
