"""Yayın kokpiti — `/youtube`.

Sayfa dilim değil KARAR üzerine kurulu. Nedeni panelin kendi ölçümü
(2026-08-18, n=157, permütasyon testi): görüntülemeyi yordayan tek değişken
günlük üretim adedi. Kategori (p=0,69), yükleme saati (p=0,15), başlık uzunluğu
(p=0,45) ve seçim puanı (p=0,37) gürültü. Bu yüzden burada "en iyi yayın saati"
gibi bir grafik YOK; olan şey 48 saatlik karar penceresi, kanal medyanına oran
ve hacim kaldıracı.

Ölçüm inceliklerinin tamamı `short_bot.youtube.analytics_query` içinde ve orada
gerekçelendirilmiş durumda; burası yalnız onu şablona taşıyor.
"""
from pathlib import Path

from flask import Blueprint, current_app, render_template

from short_bot.config import list_channels
from short_bot.db import init_db, count_uploads_for_channel, last_upload_at_for_channel
from short_bot.youtube import auth as _yt_auth
from short_bot.youtube.avatar import has_avatar
from short_bot.youtube.analytics_query import (
    MIN_ORNEK, OLCUM_TABANI, OLGUNLUK_GUN, YORUNGE_UFKU, KanalOzeti,
    arama_terimleri, dagilim_bantlari, erken_olcek, hacim_serisi,
    kanal_ozetleri, kanal_serisi, saptanabilir_fark, trafik_karmasi,
    video_olcumleri, yorunge_medyani,
)

bp = Blueprint("youtube_overview", __name__)

#: Kanal başına şablona taşınan video sayısı — en çok izlenenler ve en yeniler.
#: Tamamını göndermek 998 satır demek; defterin işi tekil video incelemek,
#: toplamlar zaten sunucuda hesaplanıyor.
VIDEO_BASI_LIMIT = 120


def _kimlik_slug(ayarlar: dict, slug: str) -> str:
    """Kanalın kimlik dosyasının bulunduğu slug.

    Bazı kanallar kimliğini başka bir kanaldan ödünç alıyor
    (`youtube.credentials_from`). Yapılandırması silinmiş ama yüklemesi olan
    kanallarda ödünç bilgisi de yok; o zaman kendi slug'ı denenir.
    """
    cfg = ayarlar.get(slug)
    return _yt_auth.creds_slug(cfg) if cfg is not None else slug


def _kanal_adlari(yt_root: Path, kimlikler: dict[str, str]) -> dict[str, dict]:
    """Kanal slug'ı → YouTube'daki gerçek ad/el/açıklama.

    Üç bot kanalı tek bir YouTube kanalına bağlı olabiliyor ("Bi Dakka Dayı"
    ×3); ad tek başına ayırt etmediği için slug da taşınıyor ve arayüz
    çakışanlara kısa bir ek yazıyor.
    """
    cikti: dict[str, dict] = {}
    for slug, kimlik in kimlikler.items():
        bilgi = _yt_auth.load_channel_info(yt_root, kimlik) or {}
        snippet = bilgi.get("snippet", {}) or {}
        istatistik = bilgi.get("statistics", {}) or {}
        if snippet.get("title"):
            cikti[slug] = {
                "ad": snippet["title"].strip(),
                "el": (snippet.get("customUrl") or "").lstrip("@"),
                "aciklama": (snippet.get("description") or "")[:180],
                "yt_video": int(istatistik.get("videoCount") or 0),
            }
    # Aynı adı taşıyanlara ayırt edici ek.
    sayac: dict[str, int] = {}
    for v in cikti.values():
        sayac[v["ad"]] = sayac.get(v["ad"], 0) + 1
    for slug, v in cikti.items():
        v["ad2"] = slug if sayac[v["ad"]] > 1 else ""
    return cikti


def _bos_ozet(eng, slug: str) -> KanalOzeti:
    """Ölçümü olmayan ama bağlı bir kanalın özeti.

    Kanal anlık görüntüsü (abone/izlenme) videolardan bağımsız çekildiği için
    o varsa gösterilir; video ölçüleri sıfır kalır.
    """
    from sqlalchemy import text as _t
    with eng.connect() as conn:
        k = conn.execute(_t(
            "SELECT snapshot_date, subscribers, total_views FROM youtube_channel_stats"
            " WHERE channel = :c ORDER BY snapshot_date DESC LIMIT 1"), {"c": slug}).first()
    return KanalOzeti(
        slug=slug, video_sayisi=0, toplam_izlenme=0, medyan_izlenme=0,
        p90_izlenme=0, toplam_begeni=0,
        # Ölçümü olmayan kanalda oran da yok: `abone_1k` iki snapshot arasındaki
        # FARK'tan hesaplanır, tek satırla hesaplanamaz.
        abone_1k=None,
        aboneler=int(k.subscribers) if k else None,
        kanal_izlenmesi=int(k.total_views) if k else None,
        son_snapshot=k.snapshot_date if k else None,
    )


def _video_sozlugu(v, olcek) -> dict:
    from short_bot.youtube.analytics_query import erken_oran
    return {
        "vid": v.video_id,
        "sid": v.short_id,
        "title": v.title,
        "ch": v.channel,
        "dur": v.duration_s,
        "up": v.uploaded_at.strftime("%Y-%m-%dT%H:%M"),
        "views": v.views,
        "likes": v.likes,
        "com": v.comments,
        "sg": v.subscribers_gained,
        "avp": round(v.avg_view_percentage, 1),
        "avd": round(v.avg_view_duration_s, 1),
        "spark": v.yorunge,
        "d1": v.ilk_okuma,
        "pencere": round(v.ilk_pencere_saat, 1) if v.ilk_pencere_saat else None,
        "erken": (lambda o: round(o, 3) if o is not None else None)(
            erken_oran(v, olcek)),
        "olgun": v.olgun,
    }


@bp.route("/youtube")
def index():
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    yt_root = Path(current_app.config["SHORTBOT_YT_CREDS_DIR"])

    olcumler = video_olcumleri(eng)
    ozetler = kanal_ozetleri(eng, olcumler)

    ayarlar = {c.slug: c for c in list_channels(cfg_dir / "channels", enabled_only=False)}

    # LİSTE İKİ KÜMENİN BİRLEŞİMİ.
    #  · ölçümü olanlar — yapılandırması silinmiş olsa bile kalır, geçmiş
    #    ölçüm kaybolmasın;
    #  · YouTube'a bağlı olanlar — henüz tek video yüklenmemiş olsa bile
    #    görünür. Yalnız ölçümden türetmek, yeni bağlanan bir kanalı sayfadan
    #    tamamen siliyordu ve kullanıcı bağlantının tuttuğunu göremiyordu.
    ozet_haritasi = {o.slug: o for o in ozetler}
    bagli = [s for s, c in ayarlar.items()
             if _yt_auth.has_credentials(yt_root, _yt_auth.creds_slug(c))]
    sluglar = list(dict.fromkeys([o.slug for o in ozetler] + sorted(bagli)))
    adlar = _kanal_adlari(yt_root, {s: _kimlik_slug(ayarlar, s) for s in sluglar})

    kanallar, videolar, yorungeler = [], [], {}
    seriler, hacimler, dagilimlar = {}, {}, {}

    for slug in sluglar:
        o = ozet_haritasi.get(slug) or _bos_ozet(eng, slug)
        kanal_olcumleri = [v for v in olcumler if v.channel == o.slug]
        olcek = erken_olcek(kanal_olcumleri)

        y = yorunge_medyani(kanal_olcumleri)
        if y:
            yorungeler[o.slug] = {str(g): [m, n] for g, (m, n) in y.items()}
        seriler[o.slug] = kanal_serisi(eng, channel=o.slug)
        hacimler[o.slug] = hacim_serisi(kanal_olcumleri)
        dagilimlar[o.slug] = dagilim_bantlari(kanal_olcumleri)

        cfg = ayarlar.get(slug)
        kanallar.append({
            "slug": o.slug,
            "n": o.video_sayisi,
            "views": o.toplam_izlenme,
            "medyan": o.medyan_izlenme,
            "p90": o.p90_izlenme,
            "likes": o.toplam_begeni,
            "abone_1k": o.abone_1k,
            "subs": o.aboneler,
            "kanal_views": o.kanal_izlenmesi,
            "snapshot": o.son_snapshot,
            "ad": (adlar.get(o.slug) or {}).get("ad") or (cfg.name if cfg else o.slug),
            "ad2": (adlar.get(o.slug) or {}).get("ad2", ""),
            "el": (adlar.get(o.slug) or {}).get("el", ""),
            "aciklama": (adlar.get(o.slug) or {}).get("aciklama", ""),
            "yt_video": (adlar.get(o.slug) or {}).get("yt_video", 0),
            "avatar": has_avatar(yt_root, o.slug),
            # Yapılandırması silinmiş ama yüklemesi olan kanallar da listelenir;
            # onlarda ayarlar bağlantısı GÖSTERİLMEZ, 404 verirdi.
            "yapilandirildi": cfg is not None,
            "bot_yuklemesi": count_uploads_for_channel(eng, o.slug),
            "son_yukleme": (lambda d: d.strftime("%Y-%m-%dT%H:%M") if d else None)(
                last_upload_at_for_channel(eng, o.slug)),
            "mdd": round(saptanabilir_fark(o.video_sayisi), 1),
            # Erken ölçeğin dayanağı: kaç ölçüm, kaç komşu, düzeltme etkin mi.
            # `erken_yerel` yanlışsa komşuluk havuzun tamamı demektir ve
            # pencere düzeltmesi FİİLEN çalışmıyordur — arayüz bunu söyler.
            "erken_ornek": olcek.ornek,
            "erken_k": olcek.k if olcek else 0,
            "erken_yerel": olcek.yerel_mi,
        })

        # En çok izlenenler + en yeniler: defterin iki işi de bunlar.
        en_iyi = sorted(kanal_olcumleri, key=lambda v: -v.views)[:VIDEO_BASI_LIMIT]
        en_yeni = kanal_olcumleri[:VIDEO_BASI_LIMIT]      # zaten yeniden eskiye
        secilen = {v.video_id: v for v in en_iyi + en_yeni}
        videolar.extend(_video_sozlugu(v, olcek) for v in secilen.values())

    veri = {
        "kanallar": kanallar,
        "videolar": videolar,
        "yorunge": yorungeler,
        "seri": seriler,
        "hacim": hacimler,
        "dagilim": dagilimlar,
        "trafik": trafik_karmasi(eng),
        "arama": arama_terimleri(eng),
        "sabitler": {
            "min_ornek": MIN_ORNEK,
            "olcum_tabani": OLCUM_TABANI,
            "olgunluk_gun": OLGUNLUK_GUN,
            "yorunge_ufku": YORUNGE_UFKU,
        },
    }
    return render_template("youtube/index.html.j2", veri=veri, kanallar=kanallar)
