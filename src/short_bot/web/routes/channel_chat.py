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
import re
import threading
import unicodedata
import uuid
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.channel_chat import (Karar, SohbetCevabi, YasakAlan, fark,
                                    konus, taslak, uygula)
from short_bot.config import list_channels, load_channel, save_channel
from short_bot.formats import FORMATS, channel_format

bp = Blueprint("channel_chat", __name__)

_OTURUMLAR: dict[str, dict] = {}
_KILIT = threading.Lock()

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
    """Sohbet çağırıcısı — Claude CLI, patlarsa OpenRouter'daki AYNI model."""
    from short_bot.llm_sonnet import sonnet_json
    ayar = current_app.config["SHORTBOT_SETTINGS"]
    gizli = _secrets()

    def _f(prompt, schema, **kw):
        return sonnet_json(prompt, schema,
                           claude_path=ayar.claude_cli_path,
                           openrouter_model=ayar.openrouter_models.get(
                               "script", "anthropic/claude-sonnet-5"),
                           openrouter_key=gizli.get("openrouter_api_key"))
    return _f


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
                           diller=_diller())


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

    try:
        cevap = konus(cfg=o["cfg"], gecmis=o["gecmis"], girdi=girdi,
                      llm=_llm(), fmt=o["fmt"], bulgular=o.get("bulgular", ()))
    except Exception as e:   # noqa: BLE001 — kullanıcıya SEBEBİ söyle
        cevap = SohbetCevabi(
            mesaj=f"Modele ulaşamadım: {e}. Ayarları elle düzenleyebilirsin.")

    # Kararların uygulanabilirliği ŞİMDİ sınanır: yasak alan varsa kullanıcıya
    # onay düğmesi gösterip sonra patlamak yerine burada eleriz.
    gecerli, elenen = [], []
    for k in cevap.kararlar:
        try:
            fark([k], o["cfg"])
            gecerli.append(k)
        except YasakAlan as e:
            elenen.append(f"{k.alan}: {e}")
    cevap = cevap.model_copy(update={"kararlar": gecerli})

    with _KILIT:
        o["gecmis"] = list(o["gecmis"]) + [("kullanici", girdi),
                                           ("claude", cevap.mesaj)]
        o["bekleyen"] = gecerli
    return render_template("_partials/chat_turn.html.j2", oid=oid,
                           girdi=girdi, cevap=cevap, elenen=elenen,
                           farklar=fark(gecerli, o["cfg"]))


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
        yeni = uygula(kararlar, o["cfg"])
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
                           bulgular=o.get("bulgular", []), diller=_diller())


@bp.post("/channels/sohbet/<oid>/kur")
def kanali_kur(oid):
    """Taslağı gerçek kanala çevirir: slug türetilir, YAML yazılır."""
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
    save_channel(_channels_dir() / f"{slug}.yaml", cfg)
    with _KILIT:
        _OTURUMLAR.pop(oid, None)
    flash(f"'{cfg.name}' kuruldu. Cron KAPALI — birkaç video üretip sonucu "
          f"gördükten sonra açman önerilir.", "success")
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
                           diller=_diller())


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
