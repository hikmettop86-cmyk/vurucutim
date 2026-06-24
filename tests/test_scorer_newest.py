from datetime import datetime, timezone, timedelta

from short_bot.models import NewsItem, ScoredItem
from short_bot.scorer import select_newest_above


def _scored(guid, score, hours_ago):
    pub = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    item = NewsItem(guid=guid, title=guid, link="x", source=None,
                    pub_date=pub, thumb_url=None, description=None)
    return ScoredItem(item=item, score=score, reasoning="")


def test_picks_newest_above_threshold():
    scored = [
        _scored("old_high", 9.0, hours_ago=10),
        _scored("new_ok", 7.0, hours_ago=1),
        _scored("low", 3.0, hours_ago=0),
    ]
    out = select_newest_above(scored, min_score=6.0)
    assert len(out) == 1
    assert out[0].item.guid == "new_ok"   # eşik üstü + en yeni


def test_empty_when_none_above_threshold():
    scored = [_scored("a", 4.0, 1), _scored("b", 5.0, 2)]
    assert select_newest_above(scored, min_score=6.0) == []


def test_none_pubdate_sorts_oldest():
    item = NewsItem(guid="nopub", title="x", link="x", source=None,
                    pub_date=None, thumb_url=None, description=None)
    scored = [ScoredItem(item=item, score=8.0, reasoning=""),
              _scored("dated", 8.0, hours_ago=5)]
    out = select_newest_above(scored, min_score=6.0)
    assert out[0].item.guid == "dated"   # pub_date olan, None'dan yeni sayılır
