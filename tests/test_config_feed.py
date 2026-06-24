import pytest
from short_bot.config import load_channel, save_channel, ChannelConfig


def _write(tmp_path, body):
    p = tmp_path / "ch.yaml"
    p.write_text(body, encoding="utf-8")
    return p


_BASE = """slug: feedch
name: Feed Kanalı
schedule_cron: '0 */4 * * *'
duration_s: 6
min_score: 6
max_candidates_per_run: 10
template: newscast
colors: {primary: '#fff', accent: '#000', bg_gradient: ['#111','#222']}
handle: '@f'
output_dir: out
"""


def test_load_channel_feed_source(tmp_path):
    p = _write(tmp_path, _BASE + "content_source: feed\nauto_feed_ids: [1, 3]\n")
    cfg = load_channel(p)
    assert cfg.content_source == "feed"
    assert cfg.auto_feed_ids == [1, 3]


def test_feed_source_requires_feed_ids(tmp_path):
    p = _write(tmp_path, _BASE + "content_source: feed\n")
    with pytest.raises(ValueError, match="auto_feed_ids"):
        load_channel(p)


def test_save_channel_roundtrips_feed_ids(tmp_path):
    p = _write(tmp_path, _BASE + "content_source: feed\nauto_feed_ids: [2]\n")
    cfg = load_channel(p)
    save_channel(p, cfg)
    again = load_channel(p)
    assert again.content_source == "feed"
    assert again.auto_feed_ids == [2]


def test_rss_source_still_works(tmp_path):
    p = _write(tmp_path, _BASE + "keywords: [test]\n")
    cfg = load_channel(p)
    assert cfg.content_source == "rss"
    assert cfg.auto_feed_ids == []
