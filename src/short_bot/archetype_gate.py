"""Arketip kapıları — LLM'in yazdığı şablonu denetler.

"LLM şablon yazınca tutarlı çıkmıyor" doğru bir gözlem, ama suçlu sanılan
yerde değil. Şablonlar ölçüldü (2026-08-21):

    şablon        toplam   HTML gövdesi   CSS    CSS payı
    stadium         194         26        168      %87
    newscast        179         30        149      %83
    flas            254         51        203      %80
    eilmeldung      298         68        230      %77

HTML gövdesi zaten neredeyse sabit — `_auto_fit.js`'in bağlı olduğu slot
ağacı. Tutarsızlık %80'lik CSS kütlesinden geliyor ve bugün onu yakalayan tek
şey "kare düz renk mi" testi (piksel stddev > 5).

ÇÖZÜM LLM'İ KISITLAMAK DEĞİL, ÇIKTIYI DENETLEMEK: render deterministik
(Playwright chromium, aynı HTML → aynı kare), dolayısıyla üretilen şey
görülerek yargılanabilir. Desen projede kanıtlanmış — `footage_matcher`
(MAX_GATE_CHECKS=24) ve `image_picker._verify_with_claude` aynısını yapıyor.

ÜÇ AŞAMA:
    1. yapi_kapisi   düz kontrol, bedava — zorunlu slot ve değişkenler
    2. render        chromium, ÜÇ UÇ METİNLE
    3. vision_kapisi kareye bakar — sığıyor mu, okunuyor mu

FAIL-CLOSED: `footage_matcher` vision yoksa fail-open davranır (bir klip
elenmese de üretim durmamalı). Burada tersi doğru: vision yoksa şablon
KAYDEDİLMEZ — bozuk bir şablon diske yazılırsa kalıcı olur ve onu kimse
temizlemez.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from short_bot.models import Script

# KALİBRE EDİLDİ, EZBERE YAZILMADI. İlk sürüm TEMPLATE-SPEC'in örnek
# iskeletindeki her sınıfı zorunlu tutuyordu ve `comic` şablonunu reddediyordu —
# oysa comic çalışıyor, sadece `.panel-header`/`.panel` kullanıyor.
#
# Gerçek ölçüt `_auto_fit.js.j2`'nin bağlı olduğu seçiciler ve renderer'ın
# beklediği standart alt öğeler:
#     .body-text (ya da .body)  → JS gövdeyi buraya sığdırır
#     [data-fit-width]          → uzun manşeti buraya göre kısar
#     .progress, .handle        → TEMPLATE-SPEC 7 "standart alt öğeler"
#     .bg-img                   → görsel slotu; yoksa fotoğraf hiç görünmez
#     .top / .bot               → manşetin iki satırı
#
# `.stage`, `.header`, `.photo` İSTEĞE BAĞLI: yerleşim şablonun kendi kararı.
ZORUNLU_SINIFLAR: tuple[str, ...] = (
    "top", "bot", "bg-img", "body-text", "progress", "handle",
)

# Şablon bu değişkenleri yazmazsa render olur ama BOŞ kare verir — piksel
# testinden bile geçebilir (arka plan gradyanı stddev üretir).
ZORUNLU_DEGISKENLER: tuple[str, ...] = (
    "script.header_top", "script.header_bottom", "body_html",
    "handle", "dna_css", "duration_s",
)

# Şablonun MUTLAKA kullanması gereken DNA değişkenleri — kanalın paleti ve
# fontu bunlarla geliyor (`dna.build_css_override`).
ZORUNLU_DNA_DEGISKENLERI: tuple[str, ...] = (
    "--primary", "--accent", "--text-main", "--font-headline", "--font-body")

_AUTO_FIT = "_auto_fit.js.j2"
_VIEWPORT = ("1080px", "1920px")


def _govde_clampli(html: str) -> bool:
    """`.body-text` kuralında line-clamp var mı? (Yalnız GÖVDE — manşette
    clamp meşru olabilir.)"""
    import re as _re
    m = _re.search(r"\.body-text\s*\{([^}]*)\}", html)
    return bool(m and "line-clamp" in m.group(1))


def yapi_kapisi(html: str) -> tuple[bool, str]:
    """Bedava kontrol: sözleşme parçaları duruyor mu.

    Sebep metni LLM'e GERİ YAZILIR, o yüzden neyin eksik olduğunu tek tek
    saymalı — "geçersiz şablon" demek bir sonraki turu düzeltmez.
    """
    eksik: list[str] = []

    for sinif in ZORUNLU_SINIFLAR:
        if f'class="{sinif}"' not in html and f"class='{sinif}'" not in html \
                and f'class="{sinif} ' not in html and f' {sinif}"' not in html:
            eksik.append(f'class="{sinif}"')

    # Değişken ARAMASI BAĞLAMLI olmalı: düz `"handle" in html` araması
    # `class="handle"` ile eşleşir ve `{{ handle }}` yazmayan bir şablonu
    # geçirir — o şablon render olur ama kanal adı görünmez.
    import re as _re
    yazilanlar = set(_re.findall(r"\{\{\s*([a-zA-Z_][\w.]*)", html))
    for degisken in ZORUNLU_DEGISKENLER:
        if degisken not in yazilanlar:
            eksik.append("{{ " + degisken + " }}")

    if _AUTO_FIT not in html:
        eksik.append('{% include "_auto_fit.js.j2" %} (metin küçültme JS\'i)')

    # Gövde height-fit ZORUNLU (TEMPLATE-SPEC 8a): `data-fit-width` tek başına
    # yetmez, o yalnız uzun manşetin genişliğini kısar.
    if "data-fit-min" not in html or "data-fit-max" not in html:
        eksik.append('.body-text üzerinde data-fit-min ve data-fit-max '
                     "(gövde yüksekliğe sığdırılamıyor)")

    if not all(v in html for v in _VIEWPORT):
        eksik.append("1080px × 1920px viewport (html, body boyutu)")

    # GÖVDEDE line-clamp YASAK. Sabit satır sayısı `_auto_fit`i etkisiz kılar:
    # font küçülse de N. satırdan sonrası kesilir. ÖLÇÜLDÜ (2026-08-21):
    # `stadium` .body-text'inde `-webkit-line-clamp: 9` var; `data-fit-min`i
    # 38'den 24'e düşürmek KARE'yi hiç değiştirmedi, clamp+maske kaldırılınca
    # 267 karakterlik gövdenin TAMAMI taşmadan göründü. Yani clamp SIĞAN metni
    # kesiyordu — canlıda tasarım turlarının düşme sebebi buydu.
    # Depodaki 34 şablonun 26'sı zaten clamp kullanmıyor.
    # ŞABLON KANALIN PALETİNE CEVAP VERMELİ. `{{ dna_css }}` yazmak yetmiyor;
    # CSS o değişkenleri KULLANMALI. Ölçüldü (2026-08-21): AI'ın ürettiği
    # `amerika-gundemi` beş değişkenden dördünü, `bursaspor-kart` `--primary`yi
    # kullanmıyor → kanalın paleti ekrana yansımıyor, Spotify dilinde üretilen
    # aday Trabzonspor kanalında da Spotify yeşili kalıyor. 42 şablonun 33-38'i
    # bunları zaten kullanıyor.
    _kullanilan = set(_re.findall(r"var\((--[a-z0-9-]+)", html))
    _eksik_dna = [d for d in ZORUNLU_DNA_DEGISKENLERI if d not in _kullanilan]
    if _eksik_dna:
        eksik.append("DNA paletini kullan: " + ", ".join(
            f"var({d})" for d in _eksik_dna)
            + " (yoksa kanalın rengi/fontu ekrana yansımaz)")

    if _govde_clampli(html):
        eksik.append(".body-text üzerinde line-clamp YOK (sabit satır sayısı "
                     "auto-fit'i etkisiz kılar; metni data-fit-min/max ile "
                     "sığdır, kesme)")

    if eksik:
        return False, ("Şablon sözleşmeyi karşılamıyor. Eksikler: "
                       + "; ".join(eksik)
                       + ". TEMPLATE-SPEC bölüm 7'deki iskeleti temel al.")
    return True, ""


# --- uç metinler -----------------------------------------------------------
#
# Bugünkü `smoke_render_dna` TEK örnek metinle render ediyor (`_SMOKE_SCRIPT`)
# ve yalnız "kare düz renk mi" diye bakıyor. Kısa manşetle geçen şablon uzun
# manşette taşar; bu tuzağı kapatmanın maliyeti üç vision çağrısı ve havuz
# ücretsiz. Yeni arketip nadiren üretiliyor — burada cimrilik yanlış yerde
# tasarruf olurdu.

# METİNLER MODELİN SINIRLARINDA DURUR, ÜSTÜNDE DEĞİL.
#
# FATAL BULGU (2026-08-21, üç canlı koşu): eski fixture 44/56 karakterlik
# manşetler taşıyordu ama `Script` onları 25/35'te KIRPIYOR
# (models._TRIM_LIMITS). Yani kapıya giden metin daha en baştan kelime
# ortasından kesikti ('ÇOK UZUN BİR MANŞET ÜST S') ve vision her adayı
# "manşet kesilmiş" diye reddediyordu. Hiçbir şablon geçemezdi — üretimdeki
# `stadium` bile aynı kareyle sınandığında geçmedi.
#
# ÖLÇÜM (1159 üretim senaryosu, shorts.script_json):
#     header_top     p50 11  p90 17  p99 23  max 25
#     header_bottom  p50 24  p90 30  p99 34  max 35
#     photo_overlay  p50 19  p90 26  p99 34  max 40
#     body_paragraph p50 181 p90 226 p99 261 max 302  (model limiti 800 ama
#                                                      üretimde hiç görülmüyor)
# Uç metin bu maksimumlara yakın ve TAM KELİMEYLE biter.
UC_HAM: tuple[dict, ...] = (
    dict(header_top="KISA", header_bottom="Tek satır",
         photo_overlay="ÖZET", body_paragraph="Kısa bir gövde metni.",
         category="Test", mood="neutral"),
    dict(header_top="DEV TRANSFERDE SON PERDE",
         header_bottom="Yönetim kararı bu akşam açıklanacak",
         photo_overlay="ALLIANZ ARENA'DA TARİHİ GECE YAŞANDI",
         body_paragraph=(
             "Kulüp yönetimi dün akşam toplandı ve transfer dosyasını yeniden "
             "masaya yatırdı. Görüşmelerin ardından tarafların anlaşmaya çok "
             "yaklaştığı, imzaların hafta içinde atılabileceği öğrenildi. "
             "Teknik heyet oyuncuyu ilk on birde düşünüyor; sakatlık riski "
             "nedeniyle temkinli davranılacak."),
         category="Test", mood="breaking"),
    dict(header_top="ORTA UZUNLUK", header_bottom="Bir alt satır",
         photo_overlay="ORTA",
         body_paragraph=("Çok satırlı bir gövde. Cümle bir. Cümle iki. "
                         "Cümle üç. Cümle dört. Cümle beş. Cümle altı. "
                         "Cümle yedi."),
         category="Test", mood="neutral"),
)

UC_HAM: tuple[dict, ...] = (
    dict(header_top="KISA", header_bottom="Tek satır",
         photo_overlay="ÖZET", body_paragraph="Kısa bir gövde metni.",
         category="Test", mood="neutral"),
    dict(header_top="DEV TRANSFERDE SON PERDE",
         header_bottom="Yönetim kararı bu akşam açıklanacak",
         photo_overlay="ALLIANZ ARENA'DA TARİHİ GECE YAŞANDI",
         body_paragraph=(
             "Kulüp yönetimi dün akşam toplandı ve transfer dosyasını yeniden "
             "masaya yatırdı. Görüşmelerin ardından tarafların anlaşmaya çok "
             "yaklaştığı, imzaların hafta içinde atılabileceği öğrenildi. "
             "Teknik heyet oyuncuyu ilk on birde düşünüyor; sakatlık riski "
             "nedeniyle temkinli davranılacak."),
         category="Test", mood="breaking"),
    dict(header_top="ORTA UZUNLUK", header_bottom="Bir alt satır",
         photo_overlay="ORTA",
         body_paragraph=("Çok satırlı bir gövde. Cümle bir. Cümle iki. "
                         "Cümle üç. Cümle dört. Cümle beş. Cümle altı. "
                         "Cümle yedi."),
         category="Test", mood="neutral"),
    dict(header_top="ŞOK",
         header_bottom="Tek kelime",
         photo_overlay="TEK",
         body_paragraph="Çok kısa bir gövde metni.",
         category="Test", mood="breaking"),
    dict(header_top="世界のやさしさ",
         header_bottom="心が温まる小さな物語をお届け",
         photo_overlay="感動の瞬間がここにありました",
         body_paragraph=(
             "駅のホームで倒れた男性を、通りかかった高校生が助けました。"
             "周囲の人も次々に手を貸し、救急車が到着するまで声をかけ続けた"
             "そうです。彼らの名前は誰も知りません。"),
         category="やさしさ", mood="neutral", dil="ja"),
    dict(header_top="EILMELDUNG AUS BERLIN",
         header_bottom="Größte Änderung seit Jahren",
         photo_overlay="BUNDESTAG BESCHLIESST NEUE REGELUNG",
         body_paragraph=(
             "Die Abgeordneten haben am späten Abend über den Vorschlag "
             "abgestimmt. Kritiker bemängeln, dass die Übergangsfrist zu "
             "kurz sei; Befürworter verweisen auf die Dringlichkeit der "
             "Lage und die lange Vorbereitungszeit des Entwurfs."),
         category="Politik", mood="breaking", dil="de"),
    dict(header_top="EL CLÁSICO",
         header_bottom="La noche más larga del Bernabéu",
         photo_overlay="AFICIÓN EN PIE HASTA EL ÚLTIMO MINUTO",
         body_paragraph=(
             "El equipo salió decidido desde el primer minuto y encontró "
             "el gol tras una jugada ensayada. El técnico celebró con "
             "moderación; sabe que quedan muchas jornadas por delante."),
         category="Deportes", mood="upbeat", dil="es"),
)

def _kur(ham: dict) -> Script:
    """Uç metni KENDİ DİLİNİN bağlamında kur.

    `Script` alanları `strip_foreign_diacritics`ten geçiyor ve o HEDEF DİLE
    göre çalışıyor (Almancada 'ä' yabancı değil, alfabenin harfi). Bağlam
    kurulmazsa varsayılan "tr" olur ve Almanca/İspanyolca uç metinler daha
    fixture aşamasında bozulur: 'Größte' → 'Grosste', 'Clásico' → 'Clasico'.
    Kapı o zaman şablonu, üretimde ASLA görmeyeceği bir metinle sınar.
    """
    from short_bot.text_normalize import language
    h = dict(ham)
    dil = h.pop("dil", "tr")
    with language(dil):
        return Script(**h)


UC_METINLER: tuple[Script, ...] = tuple(_kur(h) for h in UC_HAM)


# --- vision kapısı ---------------------------------------------------------

VisionCall = Callable[[Path], dict]
"""Kareye bakıp `{"sorun": bool, "aciklama": str}` döndüren çağrı."""

VISION_SORUSU = """Bu, dikey bir YouTube Shorts karesinin render'ı (1080x1920).
Tasarımın DOĞRU çalışıp çalışmadığına bak — güzel olup olmadığına değil.

Şunlardan biri varsa sorun=true:
- Manşet ya da gövde metni kutusuna sığmamış, kesilmiş ya da taşmış
- Metin zeminden okunmuyor (kontrast yetersiz, fotoğraf yazıyı yutuyor)
- Öğeler üst üste binmiş
- Kare boş ya da tek renk

Sadece bunlara bak. Renk zevki, tipografi tercihi, kompozisyon SORUN DEĞİL.

JSON döndür: {"sorun": true/false, "aciklama": "tek cümle, ne bozuk"}"""


def vision_kapisi(kareler: Sequence[Path | str], *,
                  vision_call: VisionCall | None) -> tuple[bool, str]:
    """Render karelerine bakar. TEK karede sorun varsa şablon reddedilir.

    `vision_call=None` → FAIL-CLOSED. footage_matcher'dan bilinçli farkı:
    orada vision yoksa aday kabul edilir (üretim durmamalı), burada şablon
    reddedilir (bozuk şablon diske yazılırsa kalıcı olur).
    """
    if vision_call is None:
        return False, ("Vision kapısı çalıştırılamadı (görüntü modeli yok). "
                       "Şablon kaydedilmedi — denetlenmemiş bir arketip diske "
                       "yazılırsa onu kimse temizlemez.")

    for i, kare in enumerate(kareler, 1):
        p = Path(kare)
        if not p.exists():
            return False, f"{i}. kare üretilemedi: {p.name}"
        try:
            karar = vision_call(p) or {}
        except Exception as e:   # noqa: BLE001 — kapı, hatayı RED sayar
            return False, f"{i}. kare incelenemedi: {e}"
        if karar.get("sorun"):
            return False, (karar.get("aciklama")
                           or f"{i}. karede tanımsız bir sorun bulundu")
    return True, ""
