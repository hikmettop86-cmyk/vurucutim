"""Seri paneli: ark GÖRÜNÜR olsun.

Otomasyon kendini AÇIKLAMALI. Seri mimarisi kurulduğunda bölümler yalnız veritabanında
ve logda vardı: kullanıcı hangi bölümde olduğunu, arkın nerede olduğunu, SIRADAKİ
bölümün neyi anlatacağını ya da zincirin kopup kopmadığını hiçbir yerden göremiyordu.
Görünmeyen bir otomasyon, güvenilemeyen bir otomasyondur.

Bu sayfanın merkezinde tek bir soru var: **BİR SONRAKİ KOŞU NE ÜRETECEK?** Cevabı
önceden göstermek, kullanıcıya müdahale şansı verir (zincir saçmaladıysa kes, konuyu
elle seç). Üretim başladıktan sonra öğrenmek geç kalmaktır.
"""
from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, redirect, render_template, url_for

from short_bot.config import load_channel
from short_bot.db import episode_history, init_db, last_episode, record_episode
from short_bot.reel_series import (clean_open_loop, episode_badge, plan_episode,
                                   trade_cta)

bp = Blueprint("series", __name__)


def _load_cfg(slug: str):
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    return load_channel(path)


@bp.get("/channels/<slug>/series")
def page(slug):
    cfg = _load_cfg(slug)
    reel = getattr(cfg, "reel", None)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])

    gecmis = episode_history(eng, slug, limit=30)
    son = last_episode(eng, slug)
    arc_max = getattr(reel, "series_arc_length", 3) if reel else 3
    baslik = (getattr(reel, "series_title", "") or "") if reel else ""

    # SIRADAKİ BÖLÜM: bir sonraki koşunun ne üreteceği. Sayfanın asıl cevabı bu.
    plan = plan_episode(son, arc_max=arc_max)
    sonraki = {
        "episode_no": plan.episode_no,
        "arc_pos": plan.arc_pos,
        "badge": episode_badge(baslik, plan.episode_no),
        "cta": trade_cta(plan.next_no),
        # Zincirden geliyorsa konu ŞİMDİDEN belli — meta dili ayıklanmış hâliyle
        # göster, çünkü üretime giden tam olarak budur.
        "topic": clean_open_loop(plan.continue_from) if plan.continue_from else "",
        "from_chain": bool(plan.continue_from),
        "arc_max": arc_max,
    }
    return render_template("series.html.j2", slug=slug, channel=cfg,
                           enabled=bool(reel and reel.series_enabled),
                           episodes=gecmis, next=sonraki, arc_max=arc_max,
                           series_title=baslik)


@bp.post("/channels/<slug>/series/break-arc")
def break_arc(slug):
    """Zinciri ELLE KES: sıradaki bölüm bankadan taze konu alsın.

    Zincir konudan sapabiliyor (her bölüm bir öncekinin kapısından doğduğu için
    sapma birikimli). Kullanıcının "bu ark saçmaladı, kes" diyebileceği bir düğme
    olmadan tek çare YAML düzenlemek olurdu.

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
    # Aynı bölümü kapısı BOŞ olarak yeniden yaz (episode_no korunur).
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
