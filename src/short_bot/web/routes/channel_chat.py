"""Kanal sohbeti — format seçimi, kurma sohbeti, kanal sayfası.

OTURUM BELLEKTE: sohbet geçmişi ve taslak kanal `_OTURUMLAR` sözlüğünde durur.
Panel tek kullanıcılı bir masaüstü uygulaması ve desen zaten kullanılıyor
(`channel_agent._JOBS`, `curated._jobs`). Flask session'a koymak mümkün değil:
taslak bir ChannelConfig ve cookie'ye sığmaz.

KANAL SAYFASI AÇILIRKEN LLM ÇAĞRILMAZ. Teşhis `channel_diag` ile düz SQL'den
gelir; LLM yalnız kullanıcı bir şey yazınca devreye girer. Her sayfa açılışında
Claude CLI çalıştırmak hem yavaş (her çağrı yeni süreç) hem gereksiz masraf.
"""
from __future__ import annotations

import dataclasses
import logging
import re
import threading
import unicodedata
import uuid
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.archetype_design import (aday_kaydet, adaylar_uret,
                                        gercek_render, gercek_vision)
from short_bot.channel_chat import (Karar, SohbetCevabi, YasakAlan, fark,
                                    konus, taslak, uygula)
from short_bot.config import list_channels, load_channel, save_channel
from short_bot.dna import build_css_override, generate_dna
from short_bot.dna_smoke import smoke_render_dna
from short_bot.formats import FORMATS, channel_format

log = logging.getLogger(__name__)

bp = Blueprint("channel_chat", __name__)

_OTURUMLAR: dict[str, dict] = {}
_KILIT = threading.Lock()

# Arketip tasarımı DAKİKALAR sürüyor (LLM şablon yazar → 3 uç metinle render →
# vision kapısı, en fazla 3 tur). İstek içinde koşarsa tarayıcı zaman aşımına
# uğrar; `curated._jobs` deseniyle arka planda koşuyor.
_ISLER: dict[str, dict] = {}

# Kaç aday üretilsin. Ücretsiz havuzda bir aday ~7 sn (ölçüldü), yani üç
# aday ucuz; asıl kazanç ÇEŞİTLİLİK — tek adayda model hep aynı kalıba
# yaklaşıyordu ("şablonlar birbirine benzemesin").
ADAY_SAYISI = 3


def _is_yaz(jid: str, **alanlar) -> None:
    with _KILIT:
        _ISLER.setdefault(jid, {}).update(alanlar)


def _is_oku(jid: str) -> dict | None:
    with _KILIT:
        i = _ISLER.get(jid)
        return dict(i) if i else None

# unicodedata tek başına 'ı' ve 'ß' düşürüyor — elle eşliyoruz (channel_agent
# ile aynı tablo).
_SLUG_MAP = str.maketrans({"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g",
                           "Ğ": "G", "ç": "c", "Ç": "C", "ö": "o", "Ö": "O",
                           "ü": "u", "Ü": "U", "ä": "a", "Ä": "A", "ß": "ss"})


def _slugify(ad: str) -> str:
    s = (ad or "").translate(_SLUG_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "kanal"


def _channels_dir() -> Path:
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "channels"


def _benzersiz_slug(taban: str) -> str:
    d, slug, i = _channels_dir(), taban, 2
    while (d / f"{slug}.yaml").exists():
        slug, i = f"{taban}-{i}", i + 1
    return slug


def _secrets() -> dict:
    from short_bot.pexels import load_secrets
    sp = current_app.config.get("SHORTBOT_SECRETS_PATH")
    return load_secrets(Path(sp)) if sp else {}


def _llm():
    """Sohbet çağırıcısı — AYARLARDAKİ 'script' sağlayıcısı, patlarsa Sonnet.

    Eskiden yol koda sabitti (Claude CLI): kullanıcı ayarlardan ücretsiz Google
    havuzunu seçse bile sohbet yine CLI'ye gidiyordu. Ölçüldü (2026-08-21): bir
    sohbet turu CLI'da 52 sn, google_studio/gemini-3.5-flash-lite ile 6-7 sn.
    """
    from short_bot.config import resolve_ai_call
    from short_bot.llm_sonnet import sonnet_json
    ayar = current_app.config["SHORTBOT_SETTINGS"]
    gizli = _secrets()
    cagri = resolve_ai_call(ayar, gizli, "script")

    def _f(prompt, schema, **kw):
        return sonnet_json(prompt, schema,
                           claude_path=ayar.claude_cli_path,
                           backend=cagri.backend, model=cagri.model,
                           api_key=cagri.api_key,
                           openrouter_model=ayar.openrouter_models.get(
                               "script", "anthropic/claude-sonnet-5"),
                           openrouter_key=gizli.get("openrouter_api_key"))
    return _f


def _sohbet_motoru() -> str:
    """Sohbetin GERÇEKTEN kullandığı sağlayıcı/model — panelde yazılır.

    Başlıkta SABİT "Claude CLI · Sonnet 5" yazıyordu ve ayara hiç bakmıyordu;
    kullanıcı ayarlardan hepsini Gemini yaptıktan sonra "hangi AI çalışıyor"
    diye sormak zorunda kaldı (2026-08-21).
    """
    from short_bot.ai_providers import saglayici
    from short_bot.config import resolve_ai_call
    try:
        c = resolve_ai_call(current_app.config["SHORTBOT_SETTINGS"],
                            _secrets(), "script")
    except Exception:   # noqa: BLE001 — etiket üretim akışını düşürmesin
        return ""
    s = saglayici(c.backend)
    return f"{s.etiket if s else c.backend} · {c.model}"


def _oturum(oid: str) -> dict | None:
    with _KILIT:
        return _OTURUMLAR.get(oid)


# --- format seçimi ---------------------------------------------------------

@bp.get("/channels/new")
def format_sec():
    """Dört format kartı. Kanallar sayfasındaki üç ayrı düğmenin yerine geçer.

    Her kart o formatta ÇALIŞAN kanalların slug'larını gösterir: soyut bir
    format adı yerine tanıdık örnek, seçimi kolaylaştırır.
    """
    kanallar = list_channels(_channels_dir(), enabled_only=False)
    ornek: dict[str, list[str]] = {k: [] for k in FORMATS}
    for c in kanallar:
        f = channel_format(c)
        if f in ornek:
            ornek[f].append(c.slug)
    return render_template("channels/pick_format.html.j2",
                           formats=FORMATS, ornek=ornek)


# --- kurma sohbeti ---------------------------------------------------------

@bp.get("/channels/new/<fmt>")
def kurma_sohbeti(fmt):
    if fmt not in FORMATS:
        abort(404)
    dil = (request.args.get("dil") or "tr").strip()
    oid = uuid.uuid4().hex[:12]
    with _KILIT:
        _OTURUMLAR[oid] = {"fmt": fmt, "cfg": taslak(fmt, language=dil),
                           "gecmis": [], "kurulum": True}
    return render_template("channels/chat.html.j2", oid=oid, fmt=fmt,
                           spec=FORMATS[fmt], cfg=_OTURUMLAR[oid]["cfg"],
                           turlar=[], kurulum=True, bulgular=[],
                           diller=_diller(), motor=_sohbet_motoru())


def _diller():
    from short_bot.locale import LANGUAGE_NAMES, SUPPORTED_LANGUAGES
    return [(k, LANGUAGE_NAMES[k]) for k in SUPPORTED_LANGUAGES]


@bp.post("/channels/sohbet/<oid>")
def sohbet_turu(oid):
    """Tek sohbet turu. HTMX ile çağrılır, yalnız yeni turu döndürür."""
    o = _oturum(oid)
    if o is None:
        abort(404)
    girdi = (request.form.get("girdi") or "").strip()
    if not girdi:
        return "", 204

    kurulum = bool(o.get("kurulum"))
    try:
        cevap = konus(cfg=o["cfg"], gecmis=o["gecmis"], girdi=girdi,
                      llm=_llm(), fmt=o["fmt"], bulgular=o.get("bulgular", ()),
                      kurulum=kurulum)
    except Exception as e:   # noqa: BLE001 — kullanıcıya SEBEBİ söyle
        cevap = SohbetCevabi(
            mesaj=f"Modele ulaşamadım: {e}. Ayarları elle düzenleyebilirsin.")

    # Kararların uygulanabilirliği ŞİMDİ sınanır — ve GERÇEK YAZMA YOLUYLA.
    #
    # Eskiden `fark()` ile sınanıyordu; o yalnız alan ADININ beyaz listede
    # olduğuna bakıyor. Kart kanalında `voice.enabled` beyaz listede VAR ama
    # `voice` bloğu YOK: karar onay listesine giriyor, kullanıcı "uygula"ya
    # basınca `uygula` patlıyor ve BÜTÜN PARTİYİ reddediyor. Canlı koşuda
    # (2026-08-21) 15 kararın hiçbiri uygulanmadı, kanal "adı yok" diye
    # kurulamadı. `uygula([k], cfg)` yazma yolunun tamamını çalıştırır.
    gecerli, elenen = [], []
    for k in cevap.kararlar:
        try:
            uygula([k], o["cfg"], kurulum)
            gecerli.append(k)
        except Exception as e:   # noqa: BLE001 — tur çökmesin, karar elensin
            elenen.append(f"{k.alan}: {e}")
    cevap = cevap.model_copy(update={"kararlar": gecerli})

    with _KILIT:
        o["gecmis"] = list(o["gecmis"]) + [("kullanici", girdi),
                                           ("claude", cevap.mesaj)]
        o["bekleyen"] = gecerli
    return render_template("_partials/chat_turn.html.j2", oid=oid,
                           girdi=girdi, cevap=cevap, elenen=elenen,
                           farklar=fark(gecerli, o["cfg"], kurulum))


@bp.post("/channels/sohbet/<oid>/uygula")
def kararlari_uygula(oid):
    """Seçili kararları taslağa/kanala işler. Kurulumda henüz diske YAZMAZ."""
    o = _oturum(oid)
    if o is None:
        abort(404)
    secili = set(request.form.getlist("alan"))
    kararlar = [k for k in o.get("bekleyen", []) if not secili or k.alan in secili]
    if not kararlar:
        return redirect(_geri(o, oid))
    try:
        yeni = uygula(kararlar, o["cfg"], bool(o.get("kurulum")))
    except YasakAlan as e:
        flash(str(e), "error")
        return redirect(_geri(o, oid))

    with _KILIT:
        o["cfg"] = yeni
        o["bekleyen"] = []

    if not o.get("kurulum"):
        save_channel(_channels_dir() / f"{yeni.slug}.yaml", yeni)
        flash(f"{len(kararlar)} ayar güncellendi.", "success")
    return redirect(_geri(o, oid))


def _geri(o: dict, oid: str) -> str:
    if o.get("kurulum"):
        return url_for("channel_chat.kurma_sohbeti_devam", oid=oid)
    return url_for("channel_chat.kanal_sayfasi", slug=o["cfg"].slug)


@bp.get("/channels/sohbet/<oid>")
def kurma_sohbeti_devam(oid):
    o = _oturum(oid)
    if o is None:
        abort(404)
    return render_template("channels/chat.html.j2", oid=oid, fmt=o["fmt"],
                           spec=FORMATS[o["fmt"]], cfg=o["cfg"],
                           turlar=o["gecmis"], kurulum=o.get("kurulum", False),
                           bulgular=o.get("bulgular", []), diller=_diller(),
                           motor=_sohbet_motoru())


class _KimlikYok(RuntimeError):
    """Görsel kimlik üretilemedi ya da render kapısından geçmedi."""


def _gorsel_kimlik(cfg):
    """DNA üret → render kapısından geçir → CSS yaz → cfg'ye işle.

    KİMLİKSİZ KANAL KURULMAZ. Sohbetle kurulan ilk gerçek kanal
    (`besiktas-gundem`, 2026-08-21) taslağın SABİT varsayılanlarıyla
    kaydedildi: `template: flas` ve kırmızı/sarı palet — Beşiktaş siyah-beyaz.
    YAML'da `dna:` bloğu yoktu, `templates/css/<slug>.css` hiç yazılmamıştı.

    Eski sihirbaz (`channel_new.save`) tam bu üç adımı yapıyordu; sohbete
    bağlanmamıştı. Planda "YAML + CSS + konu bankası" işaretliydi ama yalnız
    YAML yazılıyordu.
    """
    from short_bot.config import resolve_ai_call
    ayar = current_app.config["SHORTBOT_SETTINGS"]
    templates_dir = Path(current_app.config["SHORTBOT_TEMPLATES_DIR"])
    cagri = resolve_ai_call(ayar, _secrets(), "dna")
    try:
        dna = generate_dna(name=cfg.name, keywords=list(cfg.keywords),
                           language=cfg.language,
                           topic_hint=", ".join(cfg.keywords[:6]),
                           claude_path=cagri.claude_path, model=cagri.model,
                           backend=cagri.backend, api_key=cagri.api_key)
    except Exception as e:   # noqa: BLE001 — sebebi kullanıcıya söylenir
        raise _KimlikYok(f"Görsel kimlik üretilemedi: {e}") from e

    # RENDER KAPISI: bozuk yerleşim diske yazılmasın (eski sihirbazın kapısı).
    ok, sebep = smoke_render_dna(dna, channel_template=dna.archetype,
                                 templates_dir=templates_dir, settings=ayar,
                                 language=cfg.language)
    if not ok:
        raise _KimlikYok(f"Görsel kimlik render kapısından geçmedi: {sebep}")

    css = templates_dir / "css" / f"{cfg.slug}.css"
    css.parent.mkdir(parents=True, exist_ok=True)
    css.write_text(build_css_override(dna), encoding="utf-8")

    return dataclasses.replace(
        cfg, dna=dna, template=dna.archetype,
        colors={"primary": dna.palette.primary,
                "accent": dna.palette.accent,
                "bg_gradient": list(dna.palette.bg_gradient)})


def _okunamayan_kanal(cfg, hedef: Path) -> str:
    """YAML'ı yerine yazmadan ÖNCE okunabilir mi diye sına; hatayı döndürür.

    `load_channel` kaydedicinin bilmediği kuralları uyguluyor (rss kaynağı
    keywords ister, trends bölge ister, dil desteklenmeli…). Sohbet bunları
    belirlemezse diske OKUNAMAYAN bir kanal yazılıyordu: dosya var, kanal
    sayfası patlıyor. Ölçüldü: yalnız `name` kararı veren bir tur tam bunu
    üretti.

    Sınama dosyası `*.yaml` DEĞİL — `list_channels` globuna takılmasın.
    """
    gecici = hedef.parent / f".{hedef.stem}.dogrula"
    try:
        save_channel(gecici, cfg)
        load_channel(gecici)
        return ""
    except Exception as e:   # noqa: BLE001 — sebebi kullanıcıya söylenir
        return str(e)
    finally:
        gecici.unlink(missing_ok=True)


@bp.post("/channels/sohbet/<oid>/kur")
def kanali_kur(oid):
    """Taslağı gerçek kanala çevirir: slug + görsel kimlik + YAML + CSS."""
    o = _oturum(oid)
    if o is None or not o.get("kurulum"):
        abort(404)
    cfg = o["cfg"]
    if not (cfg.name or "").strip():
        flash("Kanalın adı yok — sohbette bir isim belirle ya da kendin yaz.",
              "error")
        return redirect(url_for("channel_chat.kurma_sohbeti_devam", oid=oid))

    slug = _benzersiz_slug(_slugify(cfg.name))
    cfg = dataclasses.replace(cfg, slug=slug, output_dir=f"output/{slug}",
                              handle=(cfg.handle if cfg.handle.strip("@")
                                      else f"@{slug}"))
    hedef = _channels_dir() / f"{slug}.yaml"
    eksik = _okunamayan_kanal(cfg, hedef)
    if eksik:
        flash(f"Kanal eksik kaldı: {eksik} Sohbette tamamla, sonra tekrar kur.",
              "error")
        return redirect(url_for("channel_chat.kurma_sohbeti_devam", oid=oid))

    try:
        cfg = _gorsel_kimlik(cfg)
    except _KimlikYok as e:
        # OTURUM KORUNUR: sohbet kaybolmasın, kullanıcı tekrar denesin.
        flash(f"{e} Kanal kurulmadı — tekrar dene.", "error")
        return redirect(url_for("channel_chat.kurma_sohbeti_devam", oid=oid))

    save_channel(hedef, cfg)
    # SIFIRDAN TASARIM. `generate_dna` arketipi 40 hazır şablondan SEÇİP üstüne
    # `custom_css` yamıyor; kullanıcının şikâyeti tam buydu ("hala eski
    # arketipler üzerinden yamalıyor"). Kanal hemen kuruldu, kendi şablonu
    # arkadan geliyor.
    arketip_baslat(cfg)
    with _KILIT:
        _OTURUMLAR.pop(oid, None)
    # MESAJ DURUMU ANLATIR, VARSAYMAZ. Eskiden sabit "Cron KAPALI" yazıyordu;
    # canlıda model ilk turda `enabled: True` kararı verdi ve kullanıcı onu
    # onaylayabiliyordu — mesaj o an yalan oluyordu.
    flash(f"'{cfg.name}' kuruldu. " + (
        "Cron AÇIK — zamanlanmış üretim başlayacak."
        if cfg.enabled else
        "Cron KAPALI — birkaç video üretip sonucu gördükten sonra açman "
        "önerilir."), "success")
    return redirect(url_for("channel_chat.kanal_sayfasi", slug=slug))


# --- kanal sayfası ---------------------------------------------------------

@bp.get("/channels/<slug>")
def kanal_sayfasi(slug):
    """Kanalın kendi sayfası: teşhis + sohbet.

    Bu rota bugüne kadar YOKTU — `channel_agent` kanal kurunca buraya
    yönlendirmeye çalışıp 404 alıyordu (kodun kendi yorumu bunu belgeliyor).
    """
    path = _channels_dir() / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    cfg = load_channel(path)

    # LLM YOK — teşhis düz SQL.
    from short_bot.channel_diag import bulgular as _bulgular
    from short_bot.db import init_db
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    bulgular = _bulgular(eng, cfg)

    oid = uuid.uuid4().hex[:12]
    with _KILIT:
        _OTURUMLAR[oid] = {"fmt": channel_format(cfg), "cfg": cfg,
                           "gecmis": [], "kurulum": False,
                           "bulgular": bulgular}
    return render_template("channels/chat.html.j2", oid=oid,
                           fmt=channel_format(cfg),
                           spec=FORMATS[channel_format(cfg)], cfg=cfg,
                           turlar=[], kurulum=False, bulgular=bulgular,
                           diller=_diller(), arketip_isi=slug_isi(slug),
                           motor=_sohbet_motoru())


@bp.post("/channels/<slug>/bulgu/<kod>")
def bulguyu_duzelt(slug, kod):
    """Teşhis satırındaki 'düzelt' düğmesi — LLM'e sormadan uygular.

    Bulgunun düzeltmesi zaten ölçümden geliyor; araya LLM koymak hem yavaş
    hem de belirsizlik ekler.
    """
    path = _channels_dir() / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    cfg = load_channel(path)
    from short_bot.channel_diag import bulgular as _bulgular
    from short_bot.db import init_db
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    b = next((x for x in _bulgular(eng, cfg) if x.kod == kod), None)
    if b is None or not b.duzeltme:
        flash("Bu bulgunun otomatik düzeltmesi yok.", "error")
        return redirect(url_for("channel_chat.kanal_sayfasi", slug=slug))

    kararlar = [Karar(alan=a, deger=y, ozet=b.ozet, gerekce=b.gerekce)
                for a, _e, y in b.duzeltme]
    try:
        save_channel(path, uygula(kararlar, cfg))
    except YasakAlan as e:
        flash(str(e), "error")
        return redirect(url_for("channel_chat.kanal_sayfasi", slug=slug))
    flash(f"Düzeltildi: {b.ozet}", "success")
    return redirect(url_for("channel_chat.kanal_sayfasi", slug=slug))


# --- yeni arketip tasarımı -------------------------------------------------

def _tasarim_llm(settings, secrets):
    """Şablon YAZAN çağırıcı. Çıktı JSON değil HTML — `sonnet_json` olmaz.

    Rol `dna`: görsel kimlik işi zaten Opus'ta (config/settings.yaml
    `claude_models.dna`). Şablon yazmak DNA üretmekten daha zor bir iş.
    """
    from short_bot.claude_cli import _invoke_raw
    from short_bot.config import resolve_ai_call
    cagri = resolve_ai_call(settings, secrets, "dna")

    def _f(prompt: str) -> str:
        return _invoke_raw(prompt, backend=cagri.backend, model=cagri.model,
                           claude_path=cagri.claude_path, api_key=cagri.api_key,
                           timeout_s=600)
    return _f


def slug_isi(slug: str) -> dict | None:
    """Bu kanalın EN SON arketip tasarım işi. Kanal sayfası bunu gösterir."""
    with _KILIT:
        aday = [(jid, i) for jid, i in _ISLER.items() if i.get("slug") == slug]
    if not aday:
        return None
    jid, i = aday[-1]
    return dict(i, jid=jid)


def tasarim_niyeti(cfg) -> str:
    """Kanalın kimliğinden şablon tarifi üretir.

    Niyet boş kalırsa model jenerik bir haber kartı yazar — oysa kanalın
    paleti, personası ve adı zaten DNA'da duruyor. Bunları niyete koymak
    "sıfırdan tasarım"ı gerçekten o kanala ait yapan şey.
    """
    parca = [f"{cfg.name} kanalı için özgün bir haber kartı düzeni"]
    dna = getattr(cfg, "dna", None)
    if dna is not None:
        p = dna.palette
        parca.append(f"palet: ana {p.primary}, vurgu {p.accent}, "
                     f"zemin {' → '.join(p.bg_gradient)}")
        if getattr(dna, "persona_summary", ""):
            parca.append(f"kanalın kimliği: {dna.persona_summary}")
        f = dna.fonts
        if getattr(f, "headline", ""):
            parca.append(f"manşet fontu {f.headline}, gövde {f.body}")
    return "; ".join(parca)


def arketip_baslat(cfg) -> str:
    """Arka planda ÜÇ aday tasarımı başlatır, iş kimliğini döndürür.

    KANAL BEKLETİLMEZ: kurulum DNA ile hemen biter (ölçüldü ~70 sn), adaylar
    arkadan gelir. Hiçbiri kanala uygulanmaz — kullanıcı seçer.
    """
    jid = uuid.uuid4().hex[:12]
    niyet = tasarim_niyeti(cfg)
    _is_yaz(jid, durum="calisiyor", slug=cfg.slug, niyet=niyet, adaylar=[])
    threading.Thread(
        target=_arketip_isi, args=(jid,),
        kwargs=dict(niyet=niyet, ad=cfg.name or cfg.slug, slug=cfg.slug,
                    channels_dir=_channels_dir(),
                    templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
                    settings=current_app.config["SHORTBOT_SETTINGS"],
                    secrets=_secrets(), kanit_dir=_kanit_dir(jid)),
        daemon=True).start()
    return jid


def _arketip_isi(jid: str, *, niyet: str, ad: str, slug: str, channels_dir,
                 templates_dir, settings, secrets: dict, kanit_dir=None) -> None:
    """Arka plan işi: ÜÇ aday tasarla, kullanıcıya seçtir.

    `current_app` KULLANMAZ — thread'in uygulama bağlamı yok, gereken her şey
    parametreyle gelir (`curated._run_fetch_job` deseni).

    KANALA DOKUNULMAZ: adaylar diske yazılmaz, kanal seçim yapılana kadar
    olduğu gibi kalır. Kullanıcı kararı (2026-08-21): "3 aday üret, ben
    seçeyim" — her adaya farklı tasarım dili verilir ki şablonlar birbirine
    benzemesin.
    """
    _is_yaz(jid, durum="calisiyor", slug=slug, niyet=niyet, adaylar=[])
    try:
        # ÖNİZLEME = GERÇEK ÇIKTI: adaylar kanalın KENDİ paletiyle, kendi
        # handle'ı ve diliyle render edilir. Eskiden sabit kırmızı/sarı
        # jenerik paletle çiziliyordu; gösterilen kare üretilecek kare DEĞİLDİ.
        cfg = load_channel(Path(channels_dir) / f"{slug}.yaml")
        dna_css = build_css_override(cfg.dna) if cfg.dna is not None else ""
        sonuclar = adaylar_uret(
            niyet, ad=cfg.name or slug, templates_dir=Path(templates_dir),
            settings=settings, metin_llm=_tasarim_llm(settings, secrets),
            vision_call=gercek_vision(settings=settings, secrets=secrets),
            render_fn=gercek_render(
                settings=settings, language=cfg.language, dna_css=dna_css,
                colors=dict(cfg.colors), handle=cfg.handle,
                duration_s=cfg.duration_s),
            sayi=ADAY_SAYISI, tohum=slug, kanit_dir=kanit_dir,
            # DİLİ KONUYA GÖRE AI SEÇSİN: "bugün araba yaparım yarın yemek"
            # (kullanıcı kuralı 2026-08-21). Kanalın konusu buradan gidiyor.
            keywords=list(cfg.keywords),
            persona=(cfg.dna.persona_summary if cfg.dna is not None else ""))
    except Exception as e:   # noqa: BLE001 — iş çökmesin, sebebi göster
        log.warning(f"[arketip] {slug}: {e}")
        _is_yaz(jid, durum="hata", sebep=str(e))
        return

    adaylar = [{"i": i, "ok": s.ok, "yon": s.yon, "sebep": s.sebep,
                "tur": s.tur, "kare": len(s.kareler)}
               for i, s in enumerate(sonuclar)]
    with _KILIT:
        _ISLER.setdefault(jid, {})["_ham"] = sonuclar
    if not any(s.ok for s in sonuclar):
        _is_yaz(jid, durum="hata", adaylar=adaylar,
                sebep=("Üç adayın hiçbiri kapılardan geçemedi. "
                       "Kanal olduğu gibi duruyor."))
        return
    _is_yaz(jid, durum="secim", adaylar=adaylar)


def _kanit_dir(jid: str) -> Path:
    """Aday karelerinin durduğu dizin. Kullanıcı onlara bakacak, o yüzden
    temp DEĞİL — önbellek kökü altında iş kimliğine göre.

    MUTLAK YOL ŞART. `cache_dir` varsayılanı göreli ("data/cache") ve Flask'ın
    `send_file`ı göreli yolu CWD'ye değil APP ROOT'a (`src/short_bot/web`)
    göre çözüyor. Canlıda tam bu oldu: kareler diskte vardı, `Path.exists()`
    True diyordu, rota yine de 500 veriyordu —
    "cannot find 'src/short_bot/web/data/cache/arketip/...'".
    Testler `tmp_path` (mutlak) kullandığı için yakalamıyordu.
    """
    return (Path(current_app.config["SHORTBOT_CACHE_DIR"]).resolve()
            / "arketip" / jid)


@bp.get("/channels/arketip-kare/<jid>/<int:aday>/<int:kare>")
def arketip_kare(jid, aday, kare):
    """Bir adayın stres karesini gösterir.

    İNDEKSLE ERİŞİM, YOL DEĞİL: dosya adı kullanıcıdan gelseydi dizin dışına
    çıkma riski olurdu.
    """
    with _KILIT:
        ham = (_ISLER.get(jid) or {}).get("_ham") or []
    if aday >= len(ham):
        abort(404)
    kareler = ham[aday].kareler
    if kare >= len(kareler):
        abort(404)
    yol = Path(kareler[kare])
    if not yol.exists():
        abort(404)
    from flask import send_file
    return send_file(yol, mimetype="image/png")


@bp.post("/channels/arketip-sec/<jid>/<int:aday>")
def arketip_sec(jid, aday):
    """Kullanıcının seçtiği adayı diske yaz ve kanalı ona geçir."""
    i = _is_oku(jid)
    with _KILIT:
        ham = (_ISLER.get(jid) or {}).get("_ham") or []
    if i is None or aday >= len(ham):
        abort(404)
    sonuc = ham[aday]
    slug = i.get("slug", "")
    if not sonuc.ok:
        flash("Bu aday kapılardan geçemedi, seçilemez: " + sonuc.sebep[:200],
              "error")
        return redirect(url_for("channel_chat.kanal_sayfasi", slug=slug))

    yol = _channels_dir() / f"{slug}.yaml"
    if not yol.exists():
        abort(404)
    cfg = load_channel(yol)
    try:
        import short_bot.archetype_design as _ad
        # ARKETİBİN GÖRSEL HAVUZU: boş bırakılırsa kanal jenerik yedeğe düşer
        # ("abstract motion background") — konusuyla ilgisi olmayan arka
        # planlar. Kayıttaki 31 arketibin hepsinde dolu.
        sorgular = _ad.pexels_sorgulari(
            cfg.name or slug, keywords=list(cfg.keywords),
            persona=(cfg.dna.persona_summary if cfg.dna is not None else ""),
            metin_llm=_tasarim_llm(current_app.config["SHORTBOT_SETTINGS"],
                                   _secrets()))
        yeni_slug = _ad.aday_kaydet(
            sonuc, ad=cfg.name or slug,
            templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
            sorgular=sorgular)
    except Exception as e:   # noqa: BLE001
        flash(f"Şablon kaydedilemedi: {e}", "error")
        return redirect(url_for("channel_chat.kanal_sayfasi", slug=slug))

    yeni_dna = (cfg.dna.model_copy(update={"archetype": yeni_slug})
                if cfg.dna is not None else None)
    yeni_cfg = dataclasses.replace(cfg, template=yeni_slug, dna=yeni_dna)
    eksik = _okunamayan_kanal(yeni_cfg, yol)
    if eksik:
        flash(f"Şablon üretildi ({yeni_slug}) ama kanala bağlanamadı: {eksik}",
              "error")
        return redirect(url_for("channel_chat.kanal_sayfasi", slug=slug))
    save_channel(yol, yeni_cfg)
    _is_yaz(jid, durum="secildi", secilen=aday, sablon=yeni_slug)
    flash(f"'{yeni_slug}' şablonu kanala uygulandı.", "success")
    return redirect(url_for("channel_chat.kanal_sayfasi", slug=slug))


@bp.post("/channels/<slug>/arketip")
def arketip_tasarla(slug):
    """Claude'a bu kanal için YENİ bir şablon yazdır. Arka planda koşar."""
    yol = _channels_dir() / f"{slug}.yaml"
    if not yol.exists():
        abort(404)
    cfg = load_channel(yol)
    niyet = (request.form.get("niyet") or "").strip()
    if not niyet:
        niyet = (f"{cfg.name} kanalının kimliğine uyan özgün bir haber kartı "
                 f"düzeni")

    jid = uuid.uuid4().hex[:12]
    _is_yaz(jid, durum="calisiyor", slug=slug, niyet=niyet)
    threading.Thread(
        target=_arketip_isi, args=(jid,),
        kwargs=dict(niyet=niyet, ad=cfg.name or slug, slug=slug,
                    channels_dir=_channels_dir(),
                    templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
                    settings=current_app.config["SHORTBOT_SETTINGS"],
                    secrets=_secrets(), kanit_dir=_kanit_dir(jid)),
        daemon=True).start()
    return render_template("_partials/arketip_durum.html.j2",
                           jid=jid, is_=_is_oku(jid), slug=slug)


@bp.get("/channels/arketip-durum/<jid>")
def arketip_durum(jid):
    return render_template("_partials/arketip_durum.html.j2",
                           jid=jid, is_=_is_oku(jid), slug="")
