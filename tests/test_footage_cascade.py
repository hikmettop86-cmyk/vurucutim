from pathlib import Path
from short_bot.footage_sources import FootageCandidate
from short_bot.footage_matcher import match_beat_clip, FootageDeps


class _Src:
    def __init__(self, name, cands, avail=True):
        self.name = name; self._c = cands; self._a = avail
    def available(self): return self._a
    def search(self, q, *, max_results, orientation): return self._c
    def download(self, cand, cache_dir): return Path(cache_dir) / (self.name + ".mp4")


def test_cascade_falls_to_next_when_empty(tmp_path):
    a = _Src("a", [])                                   # boş
    b = _Src("b", [FootageCandidate(url="u", duration_s=9, source="b")])
    deps = FootageDeps(sources=[a, b], verify_footage=None)
    clip = match_beat_clip("kedi", api_key="", cache_dir=tmp_path, verify=False, deps=deps)
    assert clip is not None and clip.name == "b.mp4"


def test_cascade_first_wins(tmp_path):
    a = _Src("a", [FootageCandidate(url="u", duration_s=9, source="a")])
    b = _Src("b", [FootageCandidate(url="u2", duration_s=9, source="b")])
    deps = FootageDeps(sources=[a, b], verify_footage=None)
    clip = match_beat_clip("kedi", api_key="", cache_dir=tmp_path, verify=False, deps=deps)
    assert clip.name == "a.mp4"


def test_cascade_skips_unavailable(tmp_path):
    a = _Src("a", [FootageCandidate(url="u", duration_s=9)], avail=False)
    b = _Src("b", [FootageCandidate(url="u2", duration_s=9)])
    deps = FootageDeps(sources=[a, b], verify_footage=None)
    assert match_beat_clip("k", api_key="", cache_dir=tmp_path, verify=False, deps=deps).name == "b.mp4"
