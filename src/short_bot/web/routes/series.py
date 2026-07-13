"""Seri paneli: ark GÖRÜNÜR ve ONAYLANABİLİR olsun.

Otomasyon kendini AÇIKLAMALI. Seri mimarisi kurulduğunda bölümler yalnız veritabanında
ve logda vardı: kullanıcı hangi bölümde olduğunu, arkın nerede olduğunu, SIRADAKİ
bölümün neyi anlatacağını ya da zincirin kopup kopmadığını hiçbir yerden göremiyordu.
Görünmeyen bir otomasyon, güvenilemeyen bir otomasyondur.

İki soru bu sayfanın merkezinde:
  1. BİR SONRAKİ KOŞU NE ÜRETECEK?  (üretim başladıktan sonra öğrenmek geç kalmaktır)
  2. ARK NEREYE GİDİYOR?             (planlı modda: tüm plan, onaydan önce)
"""
from __future__ import annotations

import logging
import threading

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.config import load_channel
from short_bot.db import (active_arc, approve_arc, arc_history, create_arc,
                          discard_arc, draft_arc, episode_history, init_db,
                          last_episode)
from short_bot.reel_series import (clean_open_loop, episode_badge, plan_episode,
                                   trade_cta)

bp = Blueprint("series", __name__)
_LOG = logging.getLogger(__name__)


def _load_cfg(slug: str):
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    return load_channel(path)


def _llm_call():
    """Panelin ayarlarından bir LLM çağrısı taşıyıcısı. Kurulamıyorsa None."""
    import yaml

    from short_bot.config import resolve_ai_call
    try:
        sp = current_app.config["SHORTBOT_SECRETS_PATH"]
        secrets = yaml.safe_load(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    except Exception:
        secrets = {}
    try:
        return resolve_ai_call(current_app.config["SHORTBOT_SETTINGS"],
                               secrets or {}, "default")
    except Exception:
        return None


@bp.get("/channels/<slug>/series")
def page(slug):
    cfg = _load_cfg(slug)
    reel = getattr(cfg, "reel", None)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])

    gecmis = episode_history(eng, slug, limit=30)
    son = last_episode(eng, slug)
    arc_max = getattr(reel, "series_arc_length", 3) if reel else 3
    baslik = (getattr(reel, "series_title", "") or "") if reel else ""
    mod = getattr(reel, "arc_mode", "planned") if reel else "planned"

    aktif = active_arc(eng, slug) if mod == "planned" else None
    taslak = draft_arc(eng, slug) if mod == "planned" else None

    # SIRADAKİ BÖLÜM: bir sonraki koşunun ne üreteceği. Sayfanın asıl cevabı bu.
    plan = plan_episode(son, arc_max=arc_max)
    if aktif and aktif["remaining"] > 0:
        i = int(aktif["produced"])
        konu = aktif["plan"][i]["topic"]
        kaynak = "plan"
        arc_pos, arc_total = i + 1, aktif["total"]
    elif plan.continue_from and mod == "chain":
        konu, kaynak = clean_open_loop(plan.continue_from), "zincir"
        arc_pos, arc_total = plan.arc_pos, arc_max
    else:
        konu, kaynak = "", "banka"
        arc_pos, arc_total = 1, arc_max

    sonraki = {
        "episode_no": plan.episode_no,
        "badge": episode_badge(baslik, plan.episode_no),
        "cta": trade_cta(plan.next_no),
        "topic": konu, "source": kaynak,
        "arc_pos": arc_pos, "arc_total": arc_total,
    }
    return render_template(
        "series.html.j2", slug=slug, channel=cfg,
        enabled=bool(reel and reel.series_enabled),
        mode=mod, episodes=gecmis, next=sonraki,
        series_title=baslik, active_arc=aktif, draft=taslak,
        past_arcs=[a for a in arc_history(eng, slug)
                   if not aktif or a["id"] != aktif["id"]],
        arc_len=arc_max)


# --- ARK PLANLAMA ----------------------------------------------------------

@bp.post("/channels/<slug>/series/plan-arc")
def plan_arc_route(slug):
    """Bankadan bir konu al, N bölümlük arka böl → TASLAK (onaya düşer).

    Taslak ÜRETİME GİRMEZ. Kullanıcı görmeden hiçbir ark üretilmeye başlamaz —
    seçim ona ait (bkz. reel_arc modül başlığı).
    """
    from short_bot.db import active_bank_topics, mark_bank_topic_used
    cfg = _load_cfg(slug)
    reel = getattr(cfg, "reel", None)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])

    if draft_arc(eng, slug):
        flash("Zaten onay bekleyen bir taslak var — önce onu onayla ya da sil.", "info")
        return redirect(url_for("series.page", slug=slug))

    # Tohum konu: kullanıcı verdiyse o, yoksa bankanın en yeni aktif kaydı.
    tohum = (request.form.get("seed_topic") or "").strip()
    bank_id = None
    if not tohum:
        aktifler = active_bank_topics(eng, slug, limit=1)
        if not aktifler:
            flash("Konu bankası boş — önce 'Konu' sayfasından yenile ya da bir tohum "
                  "konu yaz.", "error")
            return redirect(url_for("series.page", slug=slug))
        tohum, bank_id = aktifler[0]["topic"], aktifler[0]["id"]

    llm = _llm_call()
    if llm is None:
        flash("LLM ayarlanmamış — ark planlanamıyor.", "error")
        return redirect(url_for("series.page", slug=slug))

    n = getattr(reel, "series_arc_length", 3) if reel else 3
    db_path = current_app.config["SHORTBOT_DB_PATH"]

    def _job():
        from short_bot.reel_arc import plan_arc
        try:
            e2 = init_db(db_path)
            p = plan_arc(tohum, channel=cfg, n=n, llm_call=llm)
            if p is None:
                _LOG.warning(f"[seri] {slug}: ark planlanamadı")
                return
            create_arc(e2, slug, title=p.title, seed_topic=tohum,
                       plan=[{"topic": e.topic, "promise": e.promise}
                             for e in p.episodes])
            # Tohum konu ARKA GİTTİ → bankadan düş (mükerrer üretimi engelleyen şey bu).
            if bank_id is not None:
                mark_bank_topic_used(e2, bank_id)
            _LOG.info(f"[seri] {slug}: taslak ark '{p.title}' ({len(p.episodes)} bölüm)")
        except Exception as e:   # noqa: BLE001 — thread paneli düşürmesin
            _LOG.warning(f"[seri] {slug} ark planlama hatası: {e}")

    threading.Thread(target=_job, daemon=True).start()
    flash(f"'{tohum[:60]}' konusundan {n} bölümlük ark planlanıyor (birkaç saniye) — "
          f"sayfayı yenile.", "info")
    return redirect(url_for("series.page", slug=slug))


@bp.post("/channels/<slug>/series/arcs/<int:arc_id>/approve")
def approve(slug, arc_id):
    _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    approve_arc(eng, arc_id)
    flash("Ark onaylandı — sıradaki koşu planın 1. bölümünü üretecek.", "success")
    return redirect(url_for("series.page", slug=slug))


@bp.post("/channels/<slug>/series/arcs/<int:arc_id>/discard")
def discard(slug, arc_id):
    _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    discard_arc(eng, arc_id)
    flash("Ark silindi.", "info")
    return redirect(url_for("series.page", slug=slug))


# --- SERİ BAŞLIĞI ----------------------------------------------------------

@bp.post("/channels/<slug>/series/suggest-title")
def suggest_title(slug):
    """Kanal DNA'sından seri başlığı öner ve YAML'a yaz (kullanıcı değiştirebilir)."""
    import dataclasses

    from short_bot.config import save_channel
    from short_bot.reel_arc import suggest_series_title
    cfg = _load_cfg(slug)
    baslik = suggest_series_title(cfg, _llm_call())
    if not baslik:
        flash("Başlık önerilemedi — Ayarlar'dan elle yazabilirsin.", "error")
        return redirect(url_for("series.page", slug=slug))
    reel = dataclasses.replace(cfg.reel, series_title=baslik) \
        if dataclasses.is_dataclass(cfg.reel) else cfg.reel.model_copy(
            update={"series_title": baslik})
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    save_channel(path, dataclasses.replace(cfg, reel=reel))
    flash(f"Seri başlığı: '{baslik}' — beğenmezsen Ayarlar'dan değiştir.", "success")
    return redirect(url_for("series.page", slug=slug))


# --- ZİNCİR ----------------------------------------------------------------

@bp.post("/channels/<slug>/series/break-arc")
def break_arc(slug):
    """Zinciri ELLE KES: sıradaki bölüm bankadan taze konu alsın.

    Zincir konudan sapabiliyor (her bölüm bir öncekinin kapısından doğduğu için sapma
    birikimli). Kullanıcının "bu ark saçmaladı, kes" diyebileceği bir düğme olmadan
    tek çare YAML düzenlemek olurdu.

    NASIL: son bölümün kapısını BOŞALTIRIZ — plan_episode kapı yoksa zaten yeni ark
    açar. Bölüm numarası korunur (feed kimliği delinmemeli).
    """
    _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    son = last_episode(eng, slug)
    if son is None:
        flash("Henüz bölüm yok — kesilecek bir zincir de yok.", "info")
        return redirect(url_for("series.page", slug=slug))
    if not son["open_loop"]:
        flash("Zincir zaten kapalı: sıradaki bölüm bankadan konu alacak.", "info")
        return redirect(url_for("series.page", slug=slug))
    _clear_open_loop(eng, slug, son["episode_no"])
    flash(f"Zincir kesildi. Bölüm #{son['episode_no'] + 1} konu bankasından "
          f"taze bir konuyla başlayacak.", "success")
    return redirect(url_for("series.page", slug=slug))


def _clear_open_loop(eng, channel: str, episode_no: int) -> None:
    from short_bot.db import series_episodes
    with eng.begin() as conn:
        conn.execute(series_episodes.update()
                     .where(series_episodes.c.channel == channel)
                     .where(series_episodes.c.episode_no == int(episode_no))
                     .values(open_loop=""))
