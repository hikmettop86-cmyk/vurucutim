from short_bot.config import ReelConfig
from short_bot.reel_subscribe import (CTA_TEXTS, COMMENT_STYLES,
                                      SubscribeBits, build_subscribe_bits)


class _Ch:
    def __init__(self, **reel_kw):
        self.reel = ReelConfig(enabled=True, voice_id="v", **reel_kw)


def test_same_seed_same_bits():
    ch = _Ch(cta_enabled=True, comment_question=True, series_enabled=True, series_title="Tuhaf Gerçekler")
    assert build_subscribe_bits(ch, 5) == build_subscribe_bits(ch, 5)


def test_all_off_empty():
    ch = _Ch(cta_enabled=False, comment_question=False, series_enabled=False)
    b = build_subscribe_bits(ch, 3)
    assert b == SubscribeBits("", "", "")


def test_comment_from_pool_when_on():
    ch = _Ch(comment_question=True, cta_enabled=False, series_enabled=False)
    lines = {build_subscribe_bits(ch, s).comment_line for s in range(len(COMMENT_STYLES) * 2)}
    assert len(lines) >= 2
    assert build_subscribe_bits(ch, 0).comment_line in COMMENT_STYLES


def test_cta_from_pool_when_on():
    ch = _Ch(cta_enabled=True, comment_question=False, series_enabled=False)
    assert build_subscribe_bits(ch, 0).cta_text in CTA_TEXTS


def test_cta_custom_overrides_pool():
    ch = _Ch(cta_enabled=True, cta_text_custom="TAKİP ET →", comment_question=False, series_enabled=False)
    assert all(build_subscribe_bits(ch, s).cta_text == "TAKİP ET →" for s in range(4))


def test_series_directive_uses_title():
    ch = _Ch(series_enabled=True, series_title="Doğanın Sırları", cta_enabled=False, comment_question=False)
    d = build_subscribe_bits(ch, 1).series_directive
    assert "Doğanın Sırları" in d


def test_series_off_empty_directive():
    ch = _Ch(series_enabled=False, cta_enabled=False, comment_question=False)
    assert build_subscribe_bits(ch, 1).series_directive == ""
