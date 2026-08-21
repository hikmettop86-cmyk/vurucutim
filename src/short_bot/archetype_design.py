"""Claude'un yeni arketip TASARLAMASI — kapılı.

Bugün Claude palet, font, punto, banner/vurgu/çip stili ve 8000 karaktere kadar
`custom_css` üretiyor ama arketipi 40 hazır `.j2`'den SEÇİYOR. Bu modül onu
yeni şablon YAZABİLİR hâle getirir; tutarsızlık korkusunun cevabı LLM'i
kısıtlamak değil, çıktıyı DENETLEMEK (bkz. archetype_gate).

DÖNGÜ:
    1. Claude şablonu yazar (serbest HTML + CSS)
    2. yapı kapısı — bedava; geçmezse SEBEP LLM'e geri yazılır
    3. render — chromium, YEDİ UÇ METİNLE (kısa/uzun manşet, uzun gövde,
       Japonca, Almanca, İspanyolca)
    4. vision kapısı — yedi kareye bakar
    5. geçerse kaydedilir; en fazla `TUR` deneme, sonra kaydetmeden pes edilir

KAYDETMEDEN PES ETMEK ŞART: geçen her şablon diskte KALICI dosya olur.
Üç turda düzelmeyen bir şablonu "olsun bari" diye yazmak, 40 kalıbın yanına
41'inci bozuk kalıbı eklemek ve onu kimsenin temizlememesi demektir.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from short_bot.archetype_gate import UC_METINLER, vision_kapisi, yapi_kapisi

log = logging.getLogger(__name__)

TUR = 3


@dataclass(frozen=True)
class TasarimSonucu:
    """Bir tasarım denemesinin sonucu.

    `html` ve `kareler` ADAY akışı için taşınır: üç aday üretilip kullanıcıya
    gösterilirken hiçbiri diske YAZILMAZ — seçilmeyen iki şablon
    `templates/`e düşerse orada kalır ve kimse temizlemez (aynı hata
    `archetypes.json`da yaşandı, on tane şablonsuz kayıt birikmişti).
    """
    ok: bool
    slug: str = ""
    sebep: str = ""
    tur: int = 0
    html: str = ""
    kareler: tuple = ()
    yon: str = ""


# Vision kapısının ÖLÇTÜĞÜ ŞEY. Model neye göre yargılanacağını bilmeden
# yazıyordu — ve daha kötüsü, "çalışan örnekler" diye verilen üç şablonun ÜÇÜ
# DE bu kapıdan geçmiyor (ölçüldü 2026-08-21, aynı uç metinlerle):
#
#   stadium  manşet sağ kenarda kesilmiş + SON DAKİKA rozetiyle çakışıyor,
#            gövdenin son satırı solarak kesiliyor
#   flas     bant ve şerit gövde metninin üstüne binmiş
#   newscast gövdenin son satırı alt kenarda yarıya kesilmiş
#
# Yani örneği birebir taklit etmek REDDEDİLMEK demekti. Uzunluklar üretimden
# ölçüldü (1159 senaryo, shorts.script_json).
KABUL_OLCUTU = """KABUL ÖLÇÜTÜ — şablonun YEDİ uç metinle render edilip karesine
bakılacak. Şunlardan biri varsa REDDEDİLİR:
  - manşet ya da gövde metni kutusuna sığmamış, kesilmiş ya da taşmış
  - metin zeminden okunmuyor (kontrast yetersiz)
  - öğeler üst üste binmiş
  - kare boş ya da tek renk

SIĞDIRMAN GEREKEN EN UZUN METİNLER (üretimden ölçüldü, 1159 senaryo):
  script.header_top      25 karakter
  script.header_bottom   35 karakter
  script.photo_overlay   40 karakter
  body_html             ~300 karakter

DİKKAT — üretimdeki eski şablonların ÇOĞU bu uzunluklarda TAŞIYOR ve bu
kapıdan GEÇMİYOR (ölçüldü: manşet sağ kenarda kesiliyor, gövdenin son satırı
solarak kırpılıyor). Bu yüzden sana örnek olarak VERİLMİYORLAR — onları
taklit etmek reddedilmek demek. Sığdırmayı kendin kur: manşette
`data-fit-width` + `data-fit-min/max`, gövdede `data-fit-min/max` +
`data-fit-pad`, kutuların genişliğini ve YÜKSEKLİĞİNİ sabitle, hiçbir katmanı
üst üste bindirme.

GÖVDE KUTUSU — EN SIK DÜŞME SEBEBİ BURASI (ölçüldü):
  1. `.body-text`in KAPSAYICISI (`.body`) YÜKSEKLİĞİ SINIRLI olmalı. `_auto_fit`
     fontu `container.clientHeight`e göre küçültüyor; kapsayıcı içerikle
     birlikte büyürse ölçüm anlamsız kalır, küçültme HİÇ çalışmaz ve yazı
     1920 px'in dışına taşar. Çalışan iki desen:
        .body { flex: 1; min-height: 0; overflow: hidden; }   (dikey flex sahne)
        .body { position: absolute; top: Xpx; bottom: Ypx; overflow: hidden; }
  2. `.body-text` üzerinde `-webkit-line-clamp` KULLANMA. Sabit satır sayısı
     auto-fit'i etkisiz kılar: font küçülse bile N. satırdan sonrası kesilir.
     ÖLÇÜLDÜ: `stadium` gövdesinde `line-clamp: 9` var; `data-fit-min`i 38'den
     24'e düşürmek kareyi HİÇ değiştirmedi, clamp kaldırılınca 267 karakterin
     TAMAMI taşmadan göründü. Yani clamp SIĞAN metni kesiyordu.
  3. `data-fit-min` 24-28 arası olsun: 300 karakterlik gövdenin küçülecek yeri
     kalsın.

SATIR ARALIĞI — TÜRKÇE ALT UZANTI: `line-height` 1'in altına inerse satır
kutusu harften küçük kalır ve ALT UZANTILI harfler (Ş, Ç, Ğ, ş, ç, ğ) komşu
bloğa taşar. ÖLÇÜLDÜ: `line-height: 0.85` ile üst üste iki manşet satırında
'ŞOK' başlığının Ş çengeli alttaki satıra değdi, vision "üst üste binmiş" diye
reddetti. Dar aralık istiyorsan satırlar arasına AÇIK boşluk koy (margin ya da
padding) — yalnız line-height'e güvenme.

TÜRKÇE GLİFLER: manşet fontu Ç Ğ İ Ö Ş Ü harflerini göstermeli. Ölçüldü: bir
adayın manşeti 'MANŞET' yerine 'MANSET' render oldu ('Anton'); aynı metin
'Oswald' ile doğru çıktı. Yedek zincirine Türkçe destekleyen font koy."""


def _prompt(niyet_blogu: str, spec_metni: str, onceki_hata: str = "") -> str:
    """Tasarım istemi.

    ESKİ ŞABLONLAR ARTIK VERİLMİYOR. Önceden `newscast` ve `flas` tam metin
    örnek olarak gidiyordu ("yapıyı bunlardan al"); model onlara demir atıyor
    ve üretilen her şablon aynı kalıba benziyordu — kullanıcının şikâyeti
    buydu. Üstelik o iki şablon gövdeyi kesen `line-clamp`'i içeriyor, yani
    kopyalanan şey hatanın kendisiydi.

    Yapı artık TEMPLATE-SPEC'in kendisinden (bölüm 7 iskeleti) geliyor,
    görünüm ise `niyet_blogu` içindeki TASARIM DİLİNDEN.
    """
    p = [
        "Bir YouTube Shorts kanalı için YENİ bir görsel şablon (Jinja2 + HTML + CSS) yaz.",
        "",
        niyet_blogu,
        "",
        KABUL_OLCUTU,
        "",
        "ZORUNLU SÖZLEŞME (uymayan şablon reddedilir):",
        spec_metni,
        "",
    ]

    # SON HATIRLATMA. Tasarım dili 12-30 KB; kapıdan düşme sebeplerinin
    # neredeyse tamamı SIĞDIRMA ve PALET. Model en son okuduğunu en iyi tutuyor,
    # o yüzden bu üç kural en sonda tekrar ediliyor.
    p += ["", "SON KONTROL — bunlar olmadan şablon REDDEDİLİR:",
          "  1. `.body-text`in kapsayıcısı yükseklikçe SINIRLI olsun "
          "(flex:1 + min-height:0 + overflow:hidden ya da absolute top/bottom).",
          "  2. `.body-text`te line-clamp YOK; `data-fit-min` 24-28.",
          "  3. CSS kanalın DNA'sını KULLANSIN: var(--primary), var(--accent), "
          "var(--text-main), var(--font-headline), var(--font-body). "
          "Sabit renk/font yazarsan kanalın kimliği ekrana yansımaz.",
          "",
          "Yalnız şablonun kendisini döndür: <!DOCTYPE html> ile başla, "
          "</html> ile bitir. Açıklama yazma."]
    # RED SEBEBİ EN SONA. Ortada kalınca model kaçırıyor: canlıda `stripe`
    # adayı ÜÇ turda da aynı eksikle (`var(--text-main)`) düştü, oysa sebep
    # her turda geri yazılıyordu.
    if onceki_hata:
        p += ["", "=" * 60,
              "ÖNCEKİ DENEMEN REDDEDİLDİ. Sebep:", onceki_hata,
              "Bunu düzelt ve şablonun TAMAMINI yeniden yaz.",
              "=" * 60]
    return "\n".join(p)


def _sablonu_ayikla(ham: str) -> str:
    """LLM markdown çiti ya da açıklama eklemiş olabilir."""
    m = re.search(r"<!DOCTYPE html>.*?</html>", ham, re.S | re.I)
    return m.group(0) if m else ham.strip()


# `unicodedata` tek başına 'ı' ve 'ş'yi düşürüyor — `channel_chat._SLUG_MAP`
# ile AYNI tablo. Şablon adı KALICI dosya adı: canlıda "Bayern Münih"
# `bayern-m-nih.html.j2` oldu (ü silindi, yerine tire kaldı).
_SLUG_MAP = str.maketrans({"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g",
                           "Ğ": "G", "ç": "c", "Ç": "C", "ö": "o", "Ö": "O",
                           "ü": "u", "Ü": "U", "ä": "a", "Ä": "A", "ß": "ss"})


def _slugify(ad: str) -> str:
    import unicodedata
    s = (ad or "").translate(_SLUG_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "arketip"


def _kareleri_sakla(kareler, kanit_dir, slug: str) -> tuple:
    """Render karelerini kalıcı bir dizine kopyala ve yeni yolları döndür."""
    import shutil
    d = Path(kanit_dir) / slug
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for i, k in enumerate(kareler):
        hedef = d / f"kare{i}.png"
        try:
            shutil.copy(k, hedef)
            out.append(hedef)
        except OSError as e:   # noqa: PERF203 — kopyalanamayan kare atlanır
            log.warning(f"[arketip] kare saklanamadı ({e})")
    return tuple(out)


def tasarla(niyet: str, *, ad: str, templates_dir: Path, settings,
            metin_llm: Callable[[str], str],
            vision_call=None,
            render_fn: Callable[..., Sequence[Path]] | None = None,
            tur: int = TUR, yon: str = "",
            kaydet: bool = True, kanit_dir=None) -> TasarimSonucu:
    """Yeni bir arketip şablonu üretir ve kapılardan geçirir.

    `metin_llm`: prompt alır, ham metin döndürür (şema YOK — çıktı HTML).
    `render_fn`: (html_yolu, script) -> üretilen PNG'ler. Enjekte edilebilir
                 olması testin Playwright'a bağımlı olmamasını sağlar.
    """
    templates_dir = Path(templates_dir)
    # SPEC KIRPILMAZ. Eskiden ilk 6000 karakter gidiyordu; oysa metni kutuya
    # SIĞDIRMA sözleşmesi çok sonra başlıyor (ölçüldü: `body-text` 8531,
    # `data-fit-min` 8542, `_auto_fit.js.j2` 8836, `data-fit-width` 9321,
    # "Zorunlu öğeler" 13345). Model taşmayı önleyen tek mekanizmayı HİÇ
    # görmüyordu ve ilk gerçek koşuda üç turun üçü de vision kapısında
    # "manşet kutusuna sığmayıp kesilmiş" diye düştü — şans değil, kaçınılmaz.
    #
    # Spec 14 KB, iki örnek 17 KB. Toplam ~31 KB ≈ 8K token: bu iş kanal başına
    # bir kez koşuyor, burada cimrilik yanlış yerde tasarruf.
    spec_yolu = Path("TEMPLATE-SPEC.md")
    spec_metni = (spec_yolu.read_text(encoding="utf-8")
                  if spec_yolu.exists() else
                  "TEMPLATE-SPEC bulunamadı; örneklerdeki yapıyı birebir izle.")
    # GÖRÜNÜM tasarım dilinden gelir, eski şablonlardan değil.
    from short_bot.design_directions import prompt_blogu
    niyet_blogu = prompt_blogu(templates_dir / "design", yon, niyet)

    slug = _slugify(ad)
    hata = ""
    # Düşen turların son karesi/HTML'i — sebebe bakılabilsin diye taşınır.
    son_kareler: tuple = ()
    son_html = ""
    for deneme in range(1, tur + 1):
        try:
            html = _sablonu_ayikla(metin_llm(_prompt(niyet_blogu, spec_metni, hata)))
        except Exception as e:   # noqa: BLE001 — modele ulaşılamadı
            return TasarimSonucu(False, sebep=f"Modele ulaşılamadı: {e}", tur=deneme, yon=yon)

        ok, hata = yapi_kapisi(html)
        if not ok:
            log.info(f"[arketip] tur {deneme}: yapı kapısı reddetti — {hata[:120]}")
            continue

        # Render + vision yalnız yapı kapısını geçenler için: chromium açmak
        # pahalı, eksik slotlu şablon için harcanmasın.
        if render_fn is None:
            return TasarimSonucu(False, sebep="Render çağrısı verilmedi.", tur=deneme, yon=yon)
        # ADAY, PAYLAŞILAN PARÇALARIN YANINDA RENDER EDİLİR. `renderer.py`
        # Jinja arama yolunu şablonun BULUNDUĞU dizin yapıyor
        # (FileSystemLoader(template_path.parent)); boş bir temp dizininde
        # `{% include "_auto_fit.js.j2" %}` çözülemiyor.
        #
        # İLK GERÇEK KOŞUDA (2026-08-21) tam bu oldu: üç tur da
        # "'_auto_fit.js.j2' not found in search path" ile düştü — yani bu
        # akış hiç çalışmamıştı. Testler sahte `render_fn` enjekte ettiği
        # için görünmüyordu.
        #
        # Kopya temp dizine alınır, `templates_dir`e geçici dosya YAZILMAZ:
        # orası kullanıcının deposu.
        with tempfile.TemporaryDirectory() as tmp:
            for paylasilan in templates_dir.glob("_*.j2"):
                (Path(tmp) / paylasilan.name).write_text(
                    paylasilan.read_text(encoding="utf-8"), encoding="utf-8")
            yol = Path(tmp) / f"{slug}.html.j2"
            yol.write_text(html, encoding="utf-8")
            try:
                kareler = list(render_fn(yol, UC_METINLER))
            except Exception as e:   # noqa: BLE001
                hata = f"Render sırasında hata: {e}"
                log.info(f"[arketip] tur {deneme}: {hata[:120]}")
                continue
            # KARELER TEMP DİZİNLE BİRLİKTE SİLİNİR. Kullanıcı ne ürettiğini
            # GÖRMELİ (kullanıcı kuralı 2026-08-21) → kalıcı yere kopyala.
            #
            # DÜŞEN ADAYINKİLER DE SAKLANIR: canlıda üç aday düştü ve hiçbirinin
            # karesi yoktu; elde yalnız vision'ın tek cümlesi kalınca ne
            # kullanıcı ne de biz sebebe bakabildik.
            kalici = _kareleri_sakla(kareler, kanit_dir, slug) if kanit_dir else ()
            ok, hata = vision_kapisi(kareler, vision_call=vision_call)
            if not ok:
                log.info(f"[arketip] tur {deneme}: vision reddetti — {hata[:120]}")
                son_kareler, son_html = kalici, html
                continue

        if kaydet:
            hedef = templates_dir / f"{slug}.html.j2"
            hedef.write_text(html, encoding="utf-8")
            _kayit_ekle(slug, ad)
        return TasarimSonucu(True, slug=slug, tur=deneme, html=html,
                             kareler=tuple(kalici), yon=yon)

    # KAYDETMEDEN PES: 41'inci bozuk kalıbı diske yazmaktansa hiç yazmamak.
    return TasarimSonucu(False, sebep=(f"{tur} denemede kapılardan geçemedi. "
                                       f"Son sebep: {hata}"), tur=tur, yon=yon,
                         html=son_html, kareler=son_kareler)


# Görsel havuzu üretilemezse düşülecek jenerik sorgular. `pexels.
# pick_query_for_archetype` boş havuzda zaten "abstract motion background"a
# düşüyor; bu üçlü ondan kötü değil ve kayıtta GÖRÜNÜR/düzenlenebilir olur.
JENERIK_SORGULAR: tuple[str, ...] = (
    "abstract motion background", "dark gradient loop", "soft light bokeh")


def pexels_sorgulari(ad: str, *, keywords, persona: str, metin_llm) -> list[str]:
    """Arketibin arka plan havuzu — İngilizce görsel arama sorguları.

    EV KURALI (kayıttaki 31 arketipten ölçüldü): sorgular arketibin KONUSUNA
    bağlı ve İngilizce — `galatasaray` → "galatasaray stadium",
    `eilmeldung` → "berlin city street". AI'ın ürettiği arketipler bunu boş
    bırakıyordu ve kanal jenerik yedeğe düşüyordu (`bursaspor-kart`,
    `amerika-gundemi`, 2026-08-21).

    HATA ÜRETİMİ DURDURMAZ: havuz üretilemezse jenerik üçlü döner.
    """
    istem = "\n".join([
        "Bir video arka planı için Pexels/Pixabay arama sorguları yaz.",
        f"Kanal: {ad}",
        f"Anahtar kelimeler: {', '.join(list(keywords)[:8]) or '-'}",
        f"Kimlik: {persona[:200] or '-'}",
        "",
        "3-5 sorgu üret. SORGULAR İNGİLİZCE olmalı (stok video siteleri "
        "Türkçe aramada neredeyse boş döner) ve GÖRSEL bir sahne tarif "
        "etmeli — soyut sıfat değil.",
        'Örnek: ["stadium lights night", "crowd cheering blur"]',
        "Yalnız JSON dizisi döndür."])
    try:
        ham = metin_llm(istem)
        veri = json.loads(_extract_dizi(ham))
        temiz = [str(x).strip() for x in veri if str(x).strip()]
        if len(temiz) >= 3:
            return temiz[:6]
    except Exception as e:   # noqa: BLE001 — havuz ikincil, üretim durmasın
        log.warning(f"[arketip] görsel havuzu üretilemedi ({e}) → jenerik")
    return list(JENERIK_SORGULAR)


def _extract_dizi(ham: str) -> str:
    m = re.search(r"\[.*\]", ham, re.S)
    return m.group(0) if m else ham.strip()


def adaylar_uret(niyet: str, *, ad: str, templates_dir: Path, settings,
                 metin_llm, vision_call=None, render_fn=None,
                 sayi: int = 3, tohum: str = "", tur: int = TUR,
                 kanit_dir=None) -> list[TasarimSonucu]:
    """`sayi` kadar aday üret — her birine FARKLI bir tasarım dili vererek.

    Kullanıcı kararı (2026-08-21): "3 aday üret, ben seçeyim". Ücretsiz
    havuzda bir aday ~7 sn olduğu için üç aday ucuz; asıl kazanç ÇEŞİTLİLİK:
    tek adayda model hep aynı kalıba yaklaşıyordu.

    DÜŞEN ADAY DA DÖNER: sessizce yutulursa kullanıcı neden iki aday
    gördüğünü anlamaz. Hiçbiri diske YAZILMAZ — seçilen `aday_kaydet` ile
    yazılır.
    """
    from short_bot.design_directions import sec
    diller = sec(templates_dir / "design", sayi, tohum=tohum or ad)
    # Dil kütüphanesi eksikse yine `sayi` kadar aday üret (dilsiz).
    while len(diller) < sayi:
        diller.append("")
    out: list[TasarimSonucu] = []
    for i, dil in enumerate(diller[:sayi]):
        out.append(tasarla(
            niyet, ad=f"{ad} {i + 1}", templates_dir=templates_dir,
            settings=settings, metin_llm=metin_llm, vision_call=vision_call,
            render_fn=render_fn, tur=tur, yon=dil, kaydet=False,
            kanit_dir=kanit_dir))
    return out


def aday_kaydet(sonuc: TasarimSonucu, *, ad: str, templates_dir: Path,
                sorgular=()) -> str:
    """Seçilen adayı diske yaz ve arketip kaydına ekle. Slug döner."""
    if not (sonuc.ok and sonuc.html):
        raise ValueError("kapılardan geçmemiş aday kaydedilemez")
    slug = _slugify(ad)
    (Path(templates_dir) / f"{slug}.html.j2").write_text(
        sonuc.html, encoding="utf-8")
    _kayit_ekle(slug, ad, sorgular=sorgular)
    return slug


def gercek_render(*, settings, language: str = "tr", dna_css: str = "",
                  colors: dict | None = None, handle: str = "@onizleme",
                  duration_s: int = 6):
    """Üretimdeki `render_fn`: her uç metin için bir kare çizer.

    ÖNİZLEME = GERÇEK ÇIKTI. Eskiden burası SABİT kırmızı/sarı palet ve BOŞ
    `dna_css` ile çiziyordu; yani kapılar şablonu kanalın paletiyle DEĞİL
    jenerik bir paletle yargılıyor, kanal sonra kendi DNA'sıyla bambaşka render
    ediyordu. Kullanıcının gördüğü kare ile yayınlanan kare aynı olmalı
    (kullanıcı kuralı 2026-08-21).

    fps=1 ile tek kare yeter — ilerleme çubuğu animasyonunun ilk karesi bize
    yerleşimi zaten gösteriyor. `dna_smoke` ile aynı desen; oradan farkı uç
    metinlerin TAMAMIYLA çağrılması.
    """
    from short_bot.locale import ui_labels_for
    from short_bot.models import RenderJob
    from short_bot import renderer

    palet = dict(colors or {"primary": "#d0021b", "accent": "#ffe600",
                            "bg_gradient": ["#3a3a3a", "#141414"]})

    def _f(sablon_yolu: Path, metinler: Sequence) -> list[Path]:
        etiketler = ui_labels_for(language)
        kareler: list[Path] = []
        kok = Path(sablon_yolu).parent
        for i, script in enumerate(metinler):
            job = RenderJob(
                script=script, bg_image_path=None,
                music_path=Path("dummy.mp3"),   # render_frames okumaz
                channel_colors=palet, handle=handle,
                duration_s=duration_s, language=language)
            hedef = kok / f"kare{i}"
            renderer.render_frames(
                job, Path(sablon_yolu), hedef, fps=1,
                browser=getattr(settings, "playwright_browser", "chromium"),
                ui_labels=etiketler, dna_css=dna_css)
            pngs = sorted(hedef.glob("*.png"))
            if pngs:
                kareler.append(pngs[len(pngs) // 2])
        return kareler
    return _f


def gercek_vision(*, settings, secrets):
    """Üretimdeki `vision_call`. Modele ulaşılamazsa None döner → FAIL-CLOSED.

    `footage_matcher._judge_image_file` deseni: yerel PNG `image_path` ile
    gönderilir, prompt'a @yol konmaz.
    """
    from short_bot.archetype_gate import VISION_SORUSU
    from short_bot.config import resolve_ai_call

    try:
        cagri = resolve_ai_call(settings, secrets, "vision")
    except Exception:   # noqa: BLE001 — vision yapılandırılmamış
        return None

    def _f(yol: Path) -> dict:
        from short_bot.claude_cli import _extract_json, _invoke_raw
        ham = _invoke_raw(VISION_SORUSU, backend=cagri.backend,
                          model=cagri.model, claude_path=cagri.claude_path,
                          api_key=cagri.api_key, timeout_s=90, image_path=Path(yol))
        return json.loads(_extract_json(ham))
    return _f


def _kayit_ekle(slug: str, ad: str, sorgular=()) -> None:
    """`config/archetypes.json`'a giriş ekler — VE arketipi anında geçerli kılar.

    Eskiden burası dosyayı CWD'ye göre kendisi yazıyordu; `dna.py` ise onu
    dosyaya göre okuyor ve YALNIZ IMPORT ANINDA. Sonuç (canlıda ölçüldü):
    şablon üretildi, kanal ona geçirildi, sonra `load_channel`
    "unknown archetype" diyerek kanalı REDDETTİ. Kayıt tek bir yerden
    yönetilsin diye iş `dna.register_designed_archetype`e devredildi.
    """
    from short_bot.dna import register_designed_archetype
    try:
        register_designed_archetype(slug, ad, pexels_queries=list(sorgular))
    except Exception as e:   # noqa: BLE001 — şablon VAR, kayıt ikincil
        log.warning(f"[arketip] arketip kaydı eklenemedi ({slug}): {e}")
