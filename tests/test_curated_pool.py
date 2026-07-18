"""Kürate havuzu: dedup anahtarı + havuz CRUD (insert/list/mark/count) — ağsız."""
from short_bot.curated_pool import (POOL_MAX, clip_key, count_pending, list_pool,
                                    mark_pool, pool_counts, pool_keys, row_to_gem)
from short_bot.db import init_db, pooled_gems


def test_clip_key_consistency():
    # v.redd.it → id; query stripped → aynı klip aynı anahtar
    assert clip_key("https://v.redd.it/abc123/CMAF_720.mp4?x=1") == "vreddit:abc123"
    assert clip_key("https://v.redd.it/abc123/DASH.mp4") == "vreddit:abc123"
    # diğer domain → query'siz url
    assert clip_key("https://streamable.com/xyz?t=2") == "https://streamable.com/xyz"
    assert clip_key("") == ""


def _insert(eng, channel, clip, **kw):
    with eng.begin() as c:
        c.execute(pooled_gems.insert().values(
            channel=channel, clip_key=clip, video_url=kw.get("url", "https://v.redd.it/x/y.mp4"),
            title=kw.get("title", "t"), sub=kw.get("sub", "funny"), ups=kw.get("ups", 1000),
            score=kw.get("score", 8.0), tone="mizah", status=kw.get("status", "pending"),
            duration=kw.get("duration", 20)))


def test_pool_crud(tmp_path):
    eng = init_db(tmp_path / "pool.db")
    _insert(eng, "kaosdayi", "vreddit:a", score=9.0)
    _insert(eng, "kaosdayi", "vreddit:b", score=5.0)
    _insert(eng, "kaosdayi", "vreddit:c", status="produced")
    _insert(eng, "dayidiyorki", "vreddit:d")            # başka kanal

    # count_pending: kanal-bazlı, yalnız pending
    assert count_pending(eng, "kaosdayi") == 2
    assert count_pending(eng, "dayidiyorki") == 1

    # pool_keys: TÜM durumlar (üretilmiş dahil) — yeniden eklememek için
    assert pool_keys(eng, "kaosdayi") == {"vreddit:a", "vreddit:b", "vreddit:c"}

    # list_pool: pending, SKOR sıralı (a=9 önce, b=5 sonra)
    gems = list_pool(eng, "kaosdayi")
    assert [g["clip_key"] for g in gems] == ["vreddit:a", "vreddit:b"]

    # pool_counts: durum dağılımı
    counts = pool_counts(eng, "kaosdayi")
    assert counts.get("pending") == 2 and counts.get("produced") == 1

    # mark_pool: pending → skipped
    mark_pool(eng, gems[1]["id"], "skipped")
    assert count_pending(eng, "kaosdayi") == 1
    assert pool_counts(eng, "kaosdayi").get("skipped") == 1


def test_row_to_gem_shape():
    row = {"video_url": "https://v.redd.it/x/y.mp4", "title": "başlık",
           "permalink": "https://reddit.com/r/x/1", "sub": "funny", "ups": 500,
           "comments": 10, "duration": 25, "width": 1080, "height": 1920, "orient": "DİKEY",
           "thumb": "https://t/img.jpg"}
    gem = row_to_gem(row)
    # produce_curated'ın beklediği zorunlu alanlar
    assert gem["video_url"] == row["video_url"]
    assert gem["title"] == "başlık" and gem["permalink"] == row["permalink"]
    assert gem["duration"] == 25 and gem["orient"] == "DİKEY"


def test_pool_max_is_sane():
    assert 10 <= POOL_MAX <= 200
