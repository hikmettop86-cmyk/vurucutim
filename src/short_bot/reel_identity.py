"""FEED KİMLİĞİ KİLİDİ — faceless kanalda FORMAT YÜZDÜR.

GERİLİM. İki doğru ilke birbirine çarpıyor:

  • VARYASYON (reel_variation): her video farklı layout/aksan/efekt alsın ki içerik
    "otomasyon ürünü" gibi görünmesin.
  • TANINMA (bu modül): izleyici feed'de kaydırırken kanalı BİR BAKIŞTA tanısın.
    Tanınmayan kanala abone olunmaz — abonelik, tanıdıklığın birikimidir.

Bugün varyasyon KAZANIYOR: ``accent_vary`` her videoda aksan rengini döndürüyor,
``layout="auto"`` yerleşimi döndürüyor. Yani aynı kanalın iki videosu feed'de
BİRBİRİNE BENZEMİYOR. Yüzü olmayan bir kanal için bu, kimliğin kendisini silmektir.

ÇÖZÜM — DOĞRU ŞEYİ KİLİTLE. İzleyici bir kanalı kesme efektinden tanımaz; FONTTAN,
RENKTEN, YERLEŞİMDEN, SESTEN, açılış sesinden ve bölüm numarasından tanır. O hâlde:

  KİLİTLİ (tanınma taşıyıcıları)      | DÖNMEYE DEVAM (parmak izi kırıcılar)
  ------------------------------------|--------------------------------------
  font                                 | cut_effect  (kesme efekti)
  aksan rengi                          | sfx_plan    (ses efektleri)
  layout (yerleşim)                    | marker_kit  (belirteçler)
  ses (voice_id)                       | music_mood  (müzik ruh hali)
  sting (açılış ses imzası)            | cut_pacing  (kesim temposu)
  bölüm rozeti                         | hook_angle  (açılış açısı)

Sağ sütun izleyicinin ADINI KOYAMADIĞI şeylerdir: onlar dönünce video "taze" durur.
Sol sütun izleyicinin TANIDIĞI şeylerdir: onlar dönünce kanal her seferinde YABANCI
olur. Varyasyon ve tanınma çelişmez — yanlış sütunu döndürürsen çelişir.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

# Kilit açıkken bu alanlar seed'e göre DÖNMEZ; kanalın sabit değerine oturur.
LOCKED_FIELDS = ("font", "accent", "layout", "voice_id", "sting", "badge")
# Kilit açıkken bile dönmeye devam eden alanlar (parmak izi kırıcılar).
VARYING_FIELDS = ("cut_effect", "sfx_plan", "marker_kit", "music_mood",
                  "cut_pacing", "hook_angle")


def _slug_idx(slug: str, n: int) -> int:
    """Kanal SLUG'una bağlı indeks — seed'e DEĞİL.

    Fark kritik: seed her videoda değişir, slug asla. Sting'in her bölümde AYNI
    olması gerekiyor; imza ancak tekrarlanınca imza olur.
    """
    h = hashlib.sha1(f"identity:{slug}".encode("utf-8")).hexdigest()
    return int(h, 16) % max(1, n)


def locked_accent(channel) -> str:
    """Kanalın SABİT aksan rengi: reel.highlight_color (parlaklık güvencesiyle)."""
    from short_bot.reel_colors import ensure_bright
    return ensure_bright(channel.reel.highlight_color)


def locked_layout(channel) -> str:
    """Kanalın SABİT yerleşimi. 'auto' iken slug'a göre BİR KEZ seçilir ve öyle kalır."""
    from short_bot.reel_variation import LAYOUTS
    l = channel.reel.layout
    if l in LAYOUTS:
        return l
    return LAYOUTS[_slug_idx(channel.slug, len(LAYOUTS))]


def lock_profile(profile, channel):
    """Varyasyon profilini kimlik kilidine oturt: aksan ve layout sabitlenir.

    Diğer alanlara DOKUNULMAZ — kesme efekti, SFX, marker, müzik, tempo dönmeye
    devam eder. Kilidin amacı çeşitliliği öldürmek değil, çeşitliliği izleyicinin
    tanımak için kullanmadığı alanlara TAŞIMAK.
    """
    return replace(profile, accent=locked_accent(channel),
                   layout=locked_layout(channel))


def pick_sting(sting_dir, channel_slug: str) -> Path | None:
    """Kanalın AÇILIŞ SES İMZASI — her bölümde aynı dosya.

    Sting bir "ses logosu"dur: 0.5-1sn'lik, kanala özgü, her videonun ilk karesinde
    çalan bir işaret. İzleyici onu bilinçli olarak fark etmez ama üçüncü videoda
    tanır — ve tanıdık şeye abone olunur. Seed'e göre seçilseydi her bölümde farklı
    olurdu, yani imza olmazdı.
    """
    d = Path(sting_dir)
    if not d.is_dir():
        return None
    files = sorted(p for p in d.glob("*.mp3") if p.is_file())
    if not files:
        return None
    return files[_slug_idx(channel_slug, len(files))]
