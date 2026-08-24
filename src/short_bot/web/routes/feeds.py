"""RSS Havuzu — feed ekleme/silme + manuel haber seçimi → video üretimi."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache

import feedparser
import requests
from pathlib import Path
from flask import (Blueprint, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.db import (
    init_db, add_feed, list_feeds, get_feed, delete_feed, set_feed_meta,
)
from short_bot.fetcher import fetch_feed_url
from short_bot.extractor import extract_og_image_url
from short_bot.web.runs import launch_pipeline
from short_bot.config import load_channel, list_channels
from short_bot.models import NewsItem
from short_bot.feed_translate import temizle as _feed_translate_temizle

bp = Blueprint("feeds", __name__)

_IMG_SRC_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.IGNORECASE)


def _first_img_in_html(html):
    """RSS description HTML'inden ilk <img src> değerini çıkar (yoksa None).
    Çoğu feed media:thumbnail vermez ama description gövdesinde görsel taşır;
    bu sayede haber önizlemesinde mümkün olduğunca gerçek görsel gösterilir."""
    if not html:
        return None
    m = _IMG_SRC_RE.search(html)
    return m.group(1) if m else None


@lru_cache(maxsize=512)
def _og_image_cached(link):
    """Makale sayfasından og:image çek (sonuç — None dahil — cache'lenir, böylece
    aynı feed tekrar açıldığında ve başarısız fetch'lerde yeniden indirme olmaz)."""
    if not link:
        return None
    try:
        return extract_og_image_url(link, timeout=8)
    except Exception:
        return None


def _resolve_item_image(n):
    """Haber önizleme görseli: feed thumbnail → açıklama görseli → makale og:image.
    İlk ikisi HTTP gerektirmez; og:image makale sayfasını indirir (paralel çağrılır)."""
    return (n.thumb_url or _first_img_in_html(n.description)
            or _og_image_cached(n.link))


@lru_cache(maxsize=2048)
def _google_gercek_url(link):
    """Google News yönlendirmesinin ardındaki YAYINCI adresi (yoksa None).

    NEDEN AYRI: Google News RSS'i görsel TAŞIMAZ — ölçüldü, ham XML'de tek bir
    <img> ya da media: etiketi yok, `link` de yayıncıya değil Google'ın ara
    sayfasına gidiyor. Bu yüzden og:image doğrudan denendiğinde her seferinde
    None dönüyordu ve üç Google kaynağının tamamı panelde görselsizdi.

    Çözüm Playwright ister (Google 2024'ten beri JS ile imzalı token üretiyor)
    ve ÖLÇÜLDÜ: 5-7 sn/haber. Yani bu YALNIZ arka plan tazelemesinde çağrılır;
    panel isteğinde 110 haber 12 dakika sürerdi. Sonuç cache'lenir.
    """
    if not link:
        return None
    try:
        from short_bot.google_news_resolver import resolve as _resolve
        return _resolve(link, timeout_s=12)
    except Exception:
        return None


def _resolve_item_image_derin(n):
    """Görsel çözümü + Google yönlendirmesini açma. Yalnız arka planda kullanılır."""
    hazir = n.thumb_url or _first_img_in_html(n.description)
    if hazir:
        return hazir
    from short_bot.google_news_resolver import is_google_news_url
    hedef = n.link
    if hedef and is_google_news_url(hedef):
        hedef = _google_gercek_url(hedef) or hedef
    return _og_image_cached(hedef)


# Cache biçimi değişirse artır: eski kayıtlar sessizce yok sayılıp yeniden çekilir.
# v2: Türkçe başlık/özet (`title_tr`, `desc_tr`) ve temizlenmiş özet (`desc_clean`)
# cache'e girdi — yoksa her açılışta yeniden LLM çağrısı yapılırdı.
_CACHE_VERSION = 2


def _dump_items(rows):
    """[{item, image}] → cache JSON'ı. RSS yolunda dolan alanlar + çözülmüş
    görsel taşınır; 'yapıldı' işareti taşınmaz (üretim durumu değişebilir,
    her gösterimde DB'den yeniden hesaplanır)."""
    payload = [{
        "guid": r["item"].guid,
        "title": r["item"].title,
        "link": r["item"].link,
        "source": r["item"].source,
        "pub_date": (r["item"].pub_date.isoformat()
                     if r["item"].pub_date else None),
        "thumb_url": r["item"].thumb_url,
        "description": r["item"].description,
        "image": r["image"],
        "desc_clean": r.get("desc_clean", ""),
        "title_tr": r.get("title_tr", ""),
        "desc_tr": r.get("desc_tr", ""),
    } for r in rows]
    return json.dumps({"v": _CACHE_VERSION, "items": payload},
                      ensure_ascii=False)


def _load_items(raw):
    """Cache JSON'ı → [{item, image}]. Boş/bozuk/eski sürümde None döner;
    çağıran bunu 'cache yok' sayıp taze çekime düşer."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if data.get("v") != _CACHE_VERSION:
            return None
        rows = []
        for d in data.get("items", []):
            pub = d.get("pub_date")
            rows.append({
                "item": NewsItem(
                    guid=d.get("guid", ""),
                    title=d.get("title", ""),
                    link=d.get("link", ""),
                    source=d.get("source"),
                    pub_date=datetime.fromisoformat(pub) if pub else None,
                    thumb_url=d.get("thumb_url"),
                    description=d.get("description"),
                ),
                "image": d.get("image"),
                "desc_clean": d.get("desc_clean", ""),
                "title_tr": d.get("title_tr", ""),
                "desc_tr": d.get("desc_tr", ""),
            })
        return rows
    except Exception:
        return None


def _age_label(dt):
    """'3 dk önce' gibi kısa yaş etiketi. DB'den naive dönen tarihler UTC
    sayılır (yazarken UTC yazılıyor)."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 90:
        return "az önce"
    if secs < 3600:
        return f"{int(secs // 60)} dk önce"
    if secs < 86400:
        return f"{int(secs // 3600)} sa önce"
    return f"{int(secs // 86400)} gün önce"


def _secrets():
    from short_bot.pexels import load_secrets
    sp = current_app.config.get("SHORTBOT_SECRETS_PATH")
    return load_secrets(Path(sp)) if sp else {}


def _turkcelestir_rows(rows):
    """Yabancı dilli listeyi panelde Türkçe göstermek için satırları zenginleştir.

    Satır sözlüğüne yazar (NewsItem'a DEĞİL): `desc_clean` her hâlde dolar,
    `title_tr`/`desc_tr` yalnız kaynak yabancıysa. NewsItem'a alan eklemek, o
    nesneyi kuran/taşıyan her yolu (pipeline, üretim formu, cache) da
    değiştirmek demekti — oysa çeviri yalnız BU sayfanın gösterimi için var.

    Fail-open: çeviri patlarsa satırlar orijinal diliyle görünür.
    """
    from short_bot.feed_translate import temizle, turkcelestir
    for r in rows:
        r["desc_clean"] = temizle(r["item"].description)
        r.setdefault("title_tr", "")
        r.setdefault("desc_tr", "")
    settings = current_app.config["SHORTBOT_SETTINGS"]
    if not getattr(settings, "feed_translate", True):
        return
    try:
        from short_bot.config import resolve_ai_call
        call = resolve_ai_call(settings, _secrets(), "default")
        ceviri = turkcelestir(
            [(r["item"].title, r["desc_clean"]) for r in rows],
            backend=call.backend, model=call.model, api_key=call.api_key,
            claude_path=call.claude_path)
    except Exception as e:  # noqa: BLE001 — pencere, kapı değil
        current_app.logger.info(f"feed çevirisi atlandı: {e}")
        return
    for i, r in enumerate(rows):
        if i in ceviri:
            r["title_tr"], r["desc_tr"] = ceviri[i]


# Arka plan tazelemesinde Google yönlendirmesi açılacak EN FAZLA haber sayısı ve
# en fazla yaş. Ölçüldü: çözüm 5-7 sn/haber, 3 iş parçacığıyla 40 haber ≈ 80-90 sn
# — sekiz kaynak bir saatlik turun içinde rahat kalır.
DERIN_LIMIT = 40
DERIN_YAS_SAAT = 48

# Yaş penceresi seçenekleri (saat). 0 = sınır yok.
YAS_SECENEKLERI = ((24, "24 saat"), (48, "2 gün"), (168, "1 hafta"), (0, "hepsi"))
# Varsayılan 48 saat: 24 saat fazla dardı — ÖLÇÜLDÜ (kayıtlı 8 kaynak), FOTOMAÇ
# beslemelerinin 24 saat içinde TEK haberi yoktu ve o kaynaklar bomboş görünürdü.
VARSAYILAN_YAS = 48


def _yas_penceresi():
    """?yas=<saat> — geçersiz/eksik değerde varsayılan pencere."""
    ham = (request.args.get("yas") or "").strip()
    try:
        saat = int(ham)
    except (TypeError, ValueError):
        return VARSAYILAN_YAS
    return saat if any(saat == s for s, _ in YAS_SECENEKLERI) else VARSAYILAN_YAS


def _yasa_gore(rows, saat):
    """Pencereye göre süz + EN YENİ ÜSTTE sırala. Döner: (satırlar, elenen_sayısı).

    TARİHSİZ haber ELENMEZ, sona konur: bazı kaynaklar pub_date vermiyor ve
    onları "eski" sayıp gizlemek kaynağı tümüyle boşaltırdı.
    """
    simdi = datetime.now(timezone.utc)

    def _yas(r):
        d = r["item"].pub_date
        if d is None:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (simdi - d).total_seconds() / 3600.0

    yasli = [(r, _yas(r)) for r in rows]
    if saat > 0:
        kalan = [(r, y) for r, y in yasli if y is None or y <= saat]
    else:
        kalan = yasli
    elenen = len(yasli) - len(kalan)
    kalan.sort(key=lambda ry: (1, 0.0) if ry[1] is None else (0, ry[1]))
    return [r for r, _ in kalan], elenen


def tazele(eng, feed, *, derin=False):
    """Kaynağı yeniden çek → görselleri çöz → Türkçeleştir → cache'e yaz.

    Panel isteği ve saatlik arka plan işi AYNI yoldan geçsin diye burada:
    ikisinin ayrı kopyaları olsaydı biri düzeltilip öteki unutulurdu.

    ``derin``: Google News yönlendirmelerini Playwright ile açar. ÖLÇÜLDÜ 5-7
    sn/haber — panel isteğinde ASLA açılmaz (110 haberlik bir kaynak 12 dakika
    sürerdi), yalnız arka plan tazelemesi kullanır.

    Ağ hatasında istisna atar; ELDEKİ cache'i ezmemek çağıranın işidir.
    """
    news = fetch_feed_url(feed.url)
    if not news:
        # fetch_feed_url ağ hatasında İSTİSNA ATMAZ, [] döner. Bunu sessizce
        # kabul etmek eldeki cache'i boş listeyle ezerdi: tek geçici hata
        # çalışan listeyi siler.
        raise RuntimeError("Kaynak yanıt vermedi ya da boş döndü.")

    if derin:
        # DERİN ÇÖZÜM SINIRLI. Haber başına 5-7 sn: 110 haberlik bir Google
        # kaynağını tümüyle çözmek ~11 dakika, üç Google kaynağı bir saatlik
        # turu aşardı. Yalnız EN TAZE haberler derin çözülür — zaten videoya
        # dönüşme ihtimali olanlar onlar; gerisi ucuz yoldan geçer.
        simdi = datetime.now(timezone.utc)

        def _yas_saat(n):
            d = n.pub_date
            if d is None:
                return 1e9
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return (simdi - d).total_seconds() / 3600.0

        adaylar = sorted(news, key=_yas_saat)
        derin_kume = {id(n) for n in adaylar[:DERIN_LIMIT]
                      if _yas_saat(n) <= DERIN_YAS_SAAT}
        cozucu = (lambda n: _resolve_item_image_derin(n) if id(n) in derin_kume
                  else _resolve_item_image(n))
    else:
        cozucu = _resolve_item_image

    # Görselleri paralel çöz: og:image makale sayfasını indirir, tek tek yapmak
    # haber sayısı kadar seri HTTP demek olurdu. Derin modda her iş bir tarayıcı
    # sekmesi açtığı için eşzamanlılık düşük tutulur.
    with ThreadPoolExecutor(max_workers=3 if derin else 10) as ex:
        images = list(ex.map(cozucu, news))

    # ÖNCEDEN ÇÖZÜLMÜŞ GÖRSELİ KORU. Google kaynaklarının görselleri yalnız
    # arka planın derin turunda bulunabiliyor; panelden 'Yenile'ye basmak (hızlı
    # yol) onları bulamaz ve eski cache'i ezerek SİLERDİ — saatlik turun emeği
    # tek tıkla kaybolurdu. Aynı koruma geçici og:image hatalarında da işe yarar.
    eski = {}
    for r in (_load_items(getattr(feed, "cached_items_json", None)) or []):
        if r.get("image"):
            eski[r["item"].guid or r["item"].link] = r["image"]
    images = [img or eski.get(n.guid or n.link)
              for n, img in zip(news, images)]

    rows = [{"item": n, "image": img} for n, img in zip(news, images)]
    # Çeviri görsel çözümünden SONRA: `_first_img_in_html` ham description'daki
    # <img> etiketine bakıyor, temizlik onu siler.
    _turkcelestir_rows(rows)
    set_feed_meta(eng, feed.id, last_fetched_at=datetime.now(timezone.utc),
                  last_error="", cached_items_json=_dump_items(rows))
    return rows


def _eng():
    return init_db(current_app.config["SHORTBOT_DB_PATH"])


def _feed_sagligi(feed):
    """Kaynak listesinde gösterilecek sağlık özeti — HTTP çağrısı YAPMAZ.

    NEDEN VAR: bir feed'in ölü olduğu hiçbir yerde görünmüyordu. Ölçüldü
    (2026-08-24, kayıtlı 8 kaynak): Mynet 21 Temmuz'dan beri hiç çekilmemişti ve
    cache'i boştu — panelde diğerleriyle bire bir aynı görünüyordu. İki FOTOMAÇ
    kaynağı da (galatasaray + fenerbahce) aynı başlığı taşıdığı için ayırt
    edilemiyordu ve ikisinde de 24 saat içinde TEK haber yoktu; operatör
    tıklayana kadar bunu göremiyordu.

    Sayım cache'ten okunur: liste sayfası 8 kaynak için 8 HTTP isteği atamaz.
    """
    # SÜRÜMDEN BAĞIMSIZ OKUMA. `_load_items` eski sürümlü cache'i "yok" sayar
    # (alan şeması değiştiği için doğru davranış), ama SAĞLIK için o kadar sertlik
    # yanlış alarm üretiyordu: cache sürümü artırıldığı an, dolu ve çalışan
    # kaynaklar listede "⚠ hiç haber yok" diye göründü. Sayım ve tarih her
    # sürümde aynı yerde duruyor.
    ham = getattr(feed, "cached_items_json", None)
    try:
        kayitlar = (json.loads(ham) or {}).get("items", []) if ham else []
    except (ValueError, TypeError):
        kayitlar = []
    if not kayitlar:
        return {"sayi": 0, "taze": 0, "yas": None, "durum": "bos"}
    simdi = datetime.now(timezone.utc)
    yaslar = []
    for k in kayitlar:
        p = k.get("pub_date")
        if not p:
            continue
        try:
            d = datetime.fromisoformat(p)
        except (ValueError, TypeError):
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        yaslar.append((simdi - d).total_seconds() / 3600.0)
    rows = kayitlar
    taze = sum(1 for y in yaslar if y < 24)
    en_yeni = min(yaslar) if yaslar else None
    if not rows:
        durum = "bos"
    elif en_yeni is None:
        durum = "iyi"          # tarihsiz feed — tazelik ölçülemez, suçlamayalım
    elif taze == 0:
        durum = "bayat"        # 24 saat içinde tek haber yok: video çıkmaz
    else:
        durum = "iyi"
    return {"sayi": len(rows), "taze": taze, "yas": en_yeni, "durum": durum}


@bp.route("/feeds")
def list_view():
    feeds = list_feeds(_eng())
    saglik = {f.id: _feed_sagligi(f) for f in feeds}
    return render_template("feeds.html.j2", feeds=feeds, saglik=saglik,
                           yas_etiketi=_age_label)


@bp.route("/feeds/<int:feed_id>/rename", methods=["POST"])
def rename(feed_id):
    """Kaynağa okunur bir ad ver. Feed başlıkları çakışabiliyor (iki ayrı
    FOTOMAÇ beslemesi listede aynı satır gibi görünüyordu)."""
    from flask import abort
    eng = _eng()
    if get_feed(eng, feed_id) is None:
        abort(404)
    ad = (request.form.get("title") or "").strip()
    if not ad:
        flash("Ad boş olamaz.", "error")
    else:
        set_feed_meta(eng, feed_id, title=ad[:120])
        flash(f"Kaynak adı güncellendi: {ad[:60]}", "success")
    return redirect(url_for("feeds.list_view"))


@bp.route("/feeds/<int:feed_id>/toggle", methods=["POST"])
def toggle(feed_id):
    """Kaynağı geçici olarak kapat/aç. `enabled` sütunu vardı ama hiçbir yerden
    değiştirilemiyordu; bozuk bir kaynağı silmeden susturmanın yolu yoktu."""
    from flask import abort
    eng = _eng()
    feed = get_feed(eng, feed_id)
    if feed is None:
        abort(404)
    yeni = 0 if feed.enabled else 1
    set_feed_meta(eng, feed_id, enabled=yeni)
    flash(f"{feed.title or feed.url} {'açıldı' if yeni else 'kapatıldı'}.", "success")
    return redirect(url_for("feeds.list_view"))


@bp.route("/feeds/add", methods=["POST"])
def add():
    url = (request.form.get("url") or "").strip()
    if not url:
        flash("Feed URL'si boş olamaz.", "error")
        return redirect(url_for("feeds.list_view"))
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "short-bot/0.1"})
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception as e:
        flash(f"Feed alınamadı: {e}", "error")
        return redirect(url_for("feeds.list_view"))
    if not parsed.entries:
        flash("Bu adres geçerli bir RSS/Atom feed'i değil (haber bulunamadı).",
              "error")
        return redirect(url_for("feeds.list_view"))
    title = (parsed.feed.get("title") if parsed.feed else None) or url
    try:
        add_feed(_eng(), url=url, title=title)
        flash(f"Feed eklendi: {title}", "success")
    except Exception:
        flash("Bu feed zaten ekli.", "error")
    return redirect(url_for("feeds.list_view"))


@bp.route("/feeds/<int:feed_id>/delete", methods=["POST"])
def delete(feed_id):
    delete_feed(_eng(), feed_id)
    flash("Feed silindi.", "success")
    return redirect(url_for("feeds.list_view"))


@bp.route("/feeds/<int:feed_id>/items")
def items(feed_id):
    """Feed'in haberleri. Varsayılan: son çekilen liste cache'ten gelir (anında).
    ?refresh=1 → RSS yeniden indirilir, görseller yeniden çözülür, cache tazelenir."""
    from flask import abort
    from short_bot.db import is_processed, similar_title_exists
    eng = _eng()
    feed = get_feed(eng, feed_id)
    if feed is None:
        abort(404)

    refresh = request.args.get("refresh") == "1"
    cache_raw = getattr(feed, "cached_items_json", None)
    rows = None if refresh else _load_items(cache_raw)
    from_cache = rows is not None
    fetched_at = feed.last_fetched_at
    fetch_error = ""

    if rows is None:
        try:
            rows = tazele(eng, feed)
            fetched_at = datetime.now(timezone.utc)
        except Exception as e:
            # Çekim patlarsa ELDEKİ cache'i koru: kullanıcı boş ekranla kalmasın,
            # sadece hatayı görsün.
            set_feed_meta(eng, feed_id, last_error=str(e))
            fallback = _load_items(cache_raw)
            rows = fallback or []
            from_cache = fallback is not None
            fetch_error = str(e)

    channels = list_channels(current_app.config["SHORTBOT_CONFIG_DIR"] / "channels")
    saat = _yas_penceresi()
    rows, elenen = _yasa_gore(rows, saat)
    enriched = _zenginlestir(eng, rows, channels)
    return render_template("_feed_items.html.j2", feed=feed,
                           items=enriched, channels=channels,
                           from_cache=from_cache, fetch_error=fetch_error,
                           translated=any(e["title_tr"] for e in enriched),
                           yas_saat=saat, elenen=elenen, yas_secenekleri=YAS_SECENEKLERI,
                           fetched_label=_age_label(fetched_at))


def _ozet_bilgi_veriyor_mu(ozet, baslik):
    """Özet başlığın tekrarı mı? (Öyleyse gösterilmez.)

    Google News RSS'inde `summary` alanı haberin özeti DEĞİL: başlığın kendisi
    artı yayıncı adı ("… en az 25 milyon euro isteniyor Habertürk"). Bunu ikinci
    bir satır olarak basmak kartın yarısını aynı cümleyi iki kez okumaya
    harcıyordu.
    """
    o = (ozet or "").strip()
    b = (baslik or "").strip()
    if not o:
        return False
    if not b:
        return True
    ok, bk = o.lower(), b.lower()
    # Başlıkla başlayıp yalnız kaynak adı kadar uzayan metin bilgi taşımıyor.
    return not (ok.startswith(bk) and len(ok) - len(bk) < 40)


def _zenginlestir(eng, rows, channels, feed_title=""):
    """Cache satırlarını şablonun beklediği biçime getir ('yapıldı' işareti dahil).

    'yapıldı' cache'e YAZILMAZ, her gösterimde DB'den hesaplanır: üretim durumu
    liste çekildikten sonra değişiyor.
    """
    from short_bot.db import processed_index, benzer_baslik_var_mi
    # İNDEKS BİR KEZ. Kanal kanal sorgulamak 110 haberlik bir kaynağı 13 saniye
    # açıyordu (bkz. db.processed_index). "Hangi kanalda yapıldı" bilgisi bu
    # listede zaten gösterilmiyor — yalnız "yapıldı mı" sorusu var, o yüzden
    # indeks kanal ayrımı olmadan tek parça tutulur.
    idx = processed_index(eng)
    cikti = []
    for r in rows:
        n = r["item"]
        done = (n.guid in idx["guid"]) or benzer_baslik_var_mi(idx, n.title, 0.85)
        temiz = r.get("desc_clean") or _feed_translate_temizle(n.description)
        cikti.append({
            "item": n, "done": done, "image": r["image"],
            # v1 cache'inden gelen satırlarda bu alanlar yok; .get ile boş
            # kalırlar ve şablon orijinali gösterir.
            "desc_clean": temiz if _ozet_bilgi_veriyor_mu(temiz, n.title) else "",
            "title_tr": r.get("title_tr", ""),
            "desc_tr": (r.get("desc_tr", "")
                        if _ozet_bilgi_veriyor_mu(r.get("desc_tr", ""),
                                                  r.get("title_tr") or n.title) else ""),
            # Birleşik görünümde satır hangi kaynaktan geldiğini kendi taşır.
            "feed_title": r.get("_feed_title") or feed_title,
        })
    return cikti


@bp.route("/feeds/tumu/items")
def all_items():
    """TÜM açık kaynakların haberleri, tarihe göre tek listede.

    NEDEN VAR: haber aramak kaynak kaynak tıklamak demekti. Ölçüldü (kayıtlı 8
    kaynak): 464 benzersiz başlığın yalnız 14'ü birden fazla kaynakta geçiyor —
    yani kaynaklar birbirini tekrar etmiyor, tek tek gezmek gerçekten de her
    seferinde yeni haberler demekti.

    Yalnız CACHE okunur, HTTP YOK: 8 kaynağı canlı çekmek sayfayı dakikalara
    çıkarırdı. Tazeleme tek tek kaynağın 'Yenile' düğmesine bağlı kalır.
    """
    eng = _eng()
    channels = list_channels(current_app.config["SHORTBOT_CONFIG_DIR"] / "channels")
    saat = _yas_penceresi()
    ham, kaynak_sayisi, elenen = [], 0, 0
    for f in list_feeds(eng, enabled_only=True):
        rows = _load_items(getattr(f, "cached_items_json", None))
        if not rows:
            continue
        kaynak_sayisi += 1
        # Süzme ZENGİNLEŞTİRMEDEN ÖNCE: 'yapıldı' hesabı satır başına iş, elenecek
        # haberler için harcanması boşuna.
        rows, e = _yasa_gore(rows, saat)
        elenen += e
        for r in rows:
            r["_feed_title"] = f.title or f.url
        ham.extend(rows)

    # GUID tekilleştirme: aynı haber iki kaynakta varsa iki kez listelenmesin.
    gorulen, benzersiz = set(), []
    for r in ham:
        g = r["item"].guid or r["item"].link
        if g in gorulen:
            continue
        gorulen.add(g)
        benzersiz.append(r)
    benzersiz, _ = _yasa_gore(benzersiz, 0)     # kaynaklar arası birleşik sıra

    # TEK çağrı: `_zenginlestir` her seferinde işlenmiş-haber indeksini kuruyor,
    # satır başına çağırmak onu haber sayısı kadar tekrarlardı.
    items = _zenginlestir(eng, benzersiz, channels)

    return render_template("_feed_items.html.j2", feed=None,
                           items=items, channels=channels,
                           from_cache=True, fetch_error="",
                           translated=any(e["title_tr"] for e in items),
                           birlesik=True, kaynak_sayisi=kaynak_sayisi,
                           yas_saat=saat, elenen=elenen, yas_secenekleri=YAS_SECENEKLERI,
                           fetched_label="")


@bp.route("/feeds/items/produce", methods=["POST"])
def produce():
    from flask import abort
    slug = (request.form.get("channel_slug") or "").strip()
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channel_path = cfg_dir / "channels" / f"{slug}.yaml"
    if not slug or not channel_path.exists():
        abort(404)
    channel = load_channel(channel_path)

    pub_date = None
    raw_pub = (request.form.get("pub_date") or "").strip()
    if raw_pub:
        from datetime import datetime
        try:
            pub_date = datetime.fromisoformat(raw_pub)
        except ValueError:
            pub_date = None

    item = NewsItem(
        guid=request.form.get("guid", ""),
        title=request.form.get("title", ""),
        link=request.form.get("link", ""),
        source=(request.form.get("source") or None),
        pub_date=pub_date,
        thumb_url=(request.form.get("thumb_url") or None),
        description=(request.form.get("description") or None),
    )

    launch_pipeline(
        channel=channel,
        settings=current_app.config["SHORTBOT_SETTINGS"],
        db_path=current_app.config["SHORTBOT_DB_PATH"],
        music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
        templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
        cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
        lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
        logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
        trigger="manual_feed",
        preselected_item=item,
    )
    flash(f"Video üretimi başladı: {item.title[:60]} → {channel.name}. "
          f"İlerlemeyi Loglar sayfasından takip et.", "success")
    return redirect(url_for("feeds.list_view"))
