"""Dört düzenleme rotası tek `/channels/<slug>/edit` rotasına iner.

Bugüne kadar `FORMAT_EDIT_SUFFIX` dört ayrı yol üretiyordu: edit, edit-yorum,
edit-curated, edit-reel. Aynı işi yapan dört yol, dört ayrı POST okuyucusu ve
dört ayrı eksik YouTube bloğu demekti.

Eski yollar 301 ile yeni rotaya döner — kullanıcının kayıtlı sekmeleri ve
tarayıcı geçmişi kırılmasın.
"""
from __future__ import annotations

import pytest

from short_bot.config import load_channel
from short_bot.web import create_app

_SETTINGS = (
    "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
    "web: {host: 127.0.0.1, port: 5005}\n"
    "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
)
_ORTAK = ("keywords: [a]\nlanguage: tr\nschedule_cron: '0 9 * * *'\n"
          "duration_s: 6\nmin_score: 6.0\nmax_candidates_per_run: 10\n"
          "template: newscast\n"
          "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
          "output_dir: out\nenabled: true\n")

KANALLAR = {
    "kart": "slug: kart\nname: Kart\nhandle: '@kart'\n" + _ORTAK,
    "sesli": ("slug: sesli\nname: Sesli\nhandle: '@sesli'\n" + _ORTAK
              + "voice: {enabled: true, voice_id: v1}\n"),
    "yorumk": ("slug: yorumk\nname: Yorum\nhandle: '@yorumk'\n" + _ORTAK
               + "content_source: trends\nvoice: {enabled: true, voice_id: v1}\n"),
    "kurate": ("slug: kurate\nname: Kürate\nhandle: '@kurate'\n" + _ORTAK
               + "content_source: curated\n"
               + "reel: {enabled: true, voice_id: v1, highlight_color: '#38bdf8'}\n"),
}


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    for slug, icerik in KANALLAR.items():
        (cfg_dir / "channels" / f"{slug}.yaml").write_text(icerik, encoding="utf-8")
    return create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates", music_root=tmp_path / "music",
        cache_dir=tmp_path / "cache", lock_dir=tmp_path / "locks",
        logs_dir=tmp_path / "logs", output_root=tmp_path / "out", scheduler=False)


@pytest.mark.parametrize("slug", list(KANALLAR))
def test_tek_edit_rotasi_200_doner(app, slug):
    r = app.test_client().get(f"/channels/{slug}/edit")
    assert r.status_code == 200, f"{slug}: {r.status_code}"


@pytest.mark.parametrize("slug,fmt_izi", [
    ("kart", "Kart"), ("sesli", "Sesli"), ("yorumk", "Gündem Yorum"), ("kurate", "Kürate"),
])
def test_dogru_formatin_sayfasi_cizilir(app, slug, fmt_izi):
    """Tek rota ama içerik formata göre — yanlış şablon çizilirse yakala."""
    html = app.test_client().get(f"/channels/{slug}/edit").get_data(as_text=True)
    assert fmt_izi.lower() in html.lower(), f"{slug} sayfasında '{fmt_izi}' izi yok"


@pytest.mark.parametrize("slug,eski", [
    ("yorumk", "/channels/yorumk/edit-yorum"),
    ("kurate", "/channels/kurate/edit-curated"),
])
def test_eski_yollar_301_ile_yonlenir(app, slug, eski):
    r = app.test_client().get(eski)
    assert r.status_code == 301, f"{eski}: {r.status_code}"
    assert r.headers["Location"].endswith(f"/channels/{slug}/edit")


@pytest.mark.parametrize("slug", list(KANALLAR))
def test_tek_rotadan_POST_kaydeder(app, slug):
    """POST da tek rotadan — formata göre doğru kaydediciye delege edilmeli."""
    app.test_client().post(f"/channels/{slug}/edit",
                           data={"name": "Yeni Ad"}, follow_redirects=True)
    cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml")
    assert cfg.name == "Yeni Ad", f"{slug}: ad kaydedilmedi"


def test_edit_path_kalkti():
    """Tek rota varken slug'dan sonraki parçayı hesaplayan tabloya gerek yok."""
    import short_bot.formats as f
    assert not hasattr(f, "FORMAT_EDIT_SUFFIX")
    assert not hasattr(f, "edit_path")
