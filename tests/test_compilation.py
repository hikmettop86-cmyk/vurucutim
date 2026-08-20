"""Günün derlemesi: gün seçimi (TZ), 190 sn eşiği, concat akışı, DB satırı, metadata."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from short_bot import compilation as comp
from short_bot.db import init_db, record_short, shorts


def _channel():
    from short_bot.config import ChannelConfig
    return ChannelConfig(slug="gundem-yorum", name="Gündem Yorum", keywords=[], rss_locale="",
                         schedule_cron="0 * * * *", duration_s=6, min_score=6.0, max_candidates_per_run=5,
                         template="flas", colors={"primary": "#d0021b", "accent": "#ffe600",
                                                  "bg_gradient": ["#3a3a3a", "#141414"]},
                         handle="@gundem", output_dir="out", enabled=True, language="tr",
                         content_source="trends")


def _insert(eng, tmp_path, title, created_local: datetime, *, exists=True, guid=None, channel="gundem-yorum"):
    p = tmp_path / f"{title}.mp4"
    if exists:
        p.write_bytes(b"x")
    created_utc = created_local.astimezone(timezone.utc).replace(tzinfo=None)
    sid = record_short(eng, channel=channel, rss_item_guid=guid or f"https://x/{title}", title=title,
                       file_path=str(p), duration_s=6, script_json="{}", render_ms=0)
    with eng.begin() as conn:
        conn.execute(shorts.update().where(shorts.c.id == sid).values(created_at=created_utc))
    return sid


IST = ZoneInfo("Europe/Istanbul")


def test_pick_day_clips_respects_local_day_and_skips_missing_and_compilations(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    day = date(2026, 8, 20)
    _insert(eng, tmp_path, "a", datetime(2026, 8, 20, 0, 30, tzinfo=IST))    # gün başı (UTC önceki gün!)
    _insert(eng, tmp_path, "b", datetime(2026, 8, 20, 23, 40, tzinfo=IST))   # gün sonu
    _insert(eng, tmp_path, "c", datetime(2026, 8, 21, 0, 10, tzinfo=IST))    # ertesi gün
    _insert(eng, tmp_path, "d", datetime(2026, 8, 20, 12, 0, tzinfo=IST), exists=False)
    _insert(eng, tmp_path, "e", datetime(2026, 8, 20, 13, 0, tzinfo=IST), guid="compilation:gundem-yorum:2026-08-20")
    _insert(eng, tmp_path, "f", datetime(2026, 8, 20, 14, 0, tzinfo=IST), channel="baska")
    clips = comp.pick_day_clips(eng, "gundem-yorum", day, probe=lambda p: 40.0)
    assert [c.title for c in clips] == ["a", "b"]
    assert all(c.duration_s == 40.0 for c in clips)


def test_total_seconds_and_chapters():
    clips = [comp.Clip(1, "Bir", Path("a"), 40.0, datetime.now()),
             comp.Clip(2, "İki", Path("b"), 35.5, datetime.now())]
    assert comp.total_seconds(clips) == pytest.approx(4 + 40 + 0.4 + 35.5 + 3)
    assert comp.chapters(clips) == [(0, "Giriş"), (4, "Bir"), (44, "İki")]
    assert comp.total_seconds([]) == 0.0


def test_metadata_has_no_shorts_tag_and_has_chapters():
    clips = [comp.Clip(1, "Adalar yine sallandı", Path("a"), 40.0, datetime.now()),
             comp.Clip(2, "Asgari ücrete ara zam", Path("b"), 38.0, datetime.now())]
    m = comp.build_compilation_metadata(date(2026, 8, 20), clips, channel_name="Gündem Yorum", handle="@gundem")
    assert m["title"] == "Türkiye bugün ne aradı? — 20 Ağustos 2026 | 2 gündem"
    assert "00:00 Giriş" in m["description"] and "00:04 Adalar yine sallandı" in m["description"]
    assert "00:44 Asgari ücrete ara zam" in m["description"]
    assert "#shorts" not in m["description"].lower() and "shorts" not in " ".join(m["tags"]).lower()


def _fake_pipeline(tmp_path):
    cmds = []

    def _run(cmd, **kw):
        cmds.append(cmd)
        out = Path(cmd[-1])
        if out.suffix in (".mp4",):
            out.write_bytes(b"v")

    def _png(template_path, ctx, out_png, **kw):
        ctx_seen.append((template_path.name, ctx))
        Path(out_png).write_bytes(b"p")
        return out_png
    ctx_seen = []
    return _run, _png, cmds, ctx_seen


def test_produce_skips_when_below_threshold(tmp_path, caplog):
    eng = init_db(tmp_path / "x.sqlite")
    _insert(eng, tmp_path, "a", datetime(2026, 8, 20, 10, 0, tzinfo=IST))
    _run, _png, cmds, _ = _fake_pipeline(tmp_path)
    sid = comp.produce_daily_compilation(_channel(), eng=eng, day=date(2026, 8, 20), templates_dir=Path("templates"),
                                         output_root=tmp_path / "out", probe=lambda p: 40.0, run=_run, render_png=_png)
    assert sid is None and cmds == []


def test_produce_builds_concat_and_records_row(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    for i, h in enumerate(["Bir", "İki", "Üç", "Dört", "Beş"]):
        _insert(eng, tmp_path, h, datetime(2026, 8, 20, 9 + i, 0, tzinfo=IST))
    _run, _png, cmds, ctx_seen = _fake_pipeline(tmp_path)
    sid = comp.produce_daily_compilation(_channel(), eng=eng, day=date(2026, 8, 20), templates_dir=Path("templates"),
                                         output_root=tmp_path / "out", probe=lambda p: 40.0, run=_run, render_png=_png)
    assert sid is not None
    # intro/outro bağlamı
    assert ctx_seen[0][0] == "compilation_intro.html.j2" and ctx_seen[0][1]["headlines"] == ["Bir", "İki", "Üç", "Dört", "Beş"]
    assert ctx_seen[1][0] == "compilation_outro.html.j2"
    # son komut concat; liste dosyası: intro, 5 klip, 4 boşluk, outro
    concat = cmds[-1]
    assert "concat" in concat
    lst = Path(concat[concat.index("-i") + 1]).read_text(encoding="utf-8").splitlines()
    assert len(lst) == 1 + 5 + 4 + 1
    assert lst[0].endswith("p_intro.mp4'") and lst[-1].endswith("p_outro.mp4'")
    assert lst[2].endswith("p_gap.mp4'")
    out = tmp_path / "out" / "gundem-yorum" / "derleme" / "2026-08-20.mp4"
    assert Path(concat[-1]) == out
    # normalize komutları 1080x1920 30fps
    norm = [c for c in cmds if "-vf" in c and "scale=1080:1920:force_original_aspect_ratio" in c[c.index("-vf") + 1]]
    assert len(norm) == 5
    with eng.connect() as conn:
        row = conn.execute(select(shorts).where(shorts.c.id == sid)).fetchone()
    assert row.rss_item_guid == "compilation:gundem-yorum:2026-08-20"
    assert row.title.startswith("Türkiye bugün ne aradı? — 20 Ağustos 2026")
    assert row.duration_s == round(4 + 5 * 40 + 4 * 0.4 + 3)
    import json
    sj = json.loads(row.script_json)
    assert sj["kind"] == "compilation" and sj["compilation_meta"]["title"] == row.title
    assert len(sj["clip_ids"]) == 5


def test_produce_again_same_day_soft_deletes_previous(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    for i, h in enumerate(["Bir", "İki", "Üç", "Dört", "Beş"]):
        _insert(eng, tmp_path, h, datetime(2026, 8, 20, 9 + i, 0, tzinfo=IST))
    _run, _png, *_ = _fake_pipeline(tmp_path)
    kw = dict(eng=eng, day=date(2026, 8, 20), templates_dir=Path("templates"), output_root=tmp_path / "out",
              probe=lambda p: 40.0, run=_run, render_png=_png)
    first = comp.produce_daily_compilation(_channel(), **kw)
    second = comp.produce_daily_compilation(_channel(), **kw)
    with eng.connect() as conn:
        rows = conn.execute(select(shorts.c.id, shorts.c.deleted_at)
                            .where(shorts.c.rss_item_guid == "compilation:gundem-yorum:2026-08-20")).fetchall()
    st = {r.id: r.deleted_at for r in rows}
    assert st[first] is not None and st[second] is None


def test_force_allows_short_compilation(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _insert(eng, tmp_path, "a", datetime(2026, 8, 20, 10, 0, tzinfo=IST))
    _run, _png, *_ = _fake_pipeline(tmp_path)
    sid = comp.produce_daily_compilation(_channel(), eng=eng, day=date(2026, 8, 20), templates_dir=Path("templates"),
                                         output_root=tmp_path / "out", probe=lambda p: 40.0, run=_run,
                                         render_png=_png, force=True)
    assert sid is not None
