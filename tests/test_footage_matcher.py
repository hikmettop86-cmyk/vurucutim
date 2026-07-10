from pathlib import Path

from short_bot.footage_matcher import FootageDeps, match_beat_clip


class _Cand:
    def __init__(self, id, url, duration_s):
        self.id, self.url, self.duration_s = id, url, duration_s


def _deps(search_map, downloaded=b"mp4"):
    """FootageDeps + çağrı kaydı. verify her zaman True döner."""
    calls = {"search": [], "verify": [], "download": []}

    def search(q, key, **kw):
        calls["search"].append(q)
        return search_map.get(q, [])

    def verify(url, query, **kw):
        calls["verify"].append((url, query))
        return True

    def download(url, cache_dir, **kw):
        calls["download"].append(url)
        p = Path(cache_dir) / (url.split("/")[-1] or "c.mp4")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(downloaded)
        return p

    d = FootageDeps(search_videos=search, verify_footage=verify,
                    download_video=download)
    return d, calls


def test_match_returns_first_candidate(tmp_path):
    cands = [_Cand(1, "https://x/a.mp4", 10)]
    d, calls = _deps({"bee flower": cands})
    clip = match_beat_clip("bee flower", api_key="k", cache_dir=tmp_path,
                           verify=False, deps=d)
    assert clip is not None and clip.exists()
    assert calls["search"] == ["bee flower"]
    assert calls["verify"] == []            # verify=False -> vision yok


def test_match_uses_vision_when_enabled(tmp_path):
    cands = [_Cand(1, "https://x/a.mp4", 10)]
    d, calls = _deps({"bee flower": cands})
    match_beat_clip("bee flower", api_key="k", cache_dir=tmp_path,
                    verify=True, vision_call=object(), deps=d)
    assert len(calls["verify"]) == 1


def test_match_skips_rejected_by_vision(tmp_path):
    cands = [_Cand(1, "https://x/a.mp4", 10), _Cand(2, "https://x/b.mp4", 8)]
    calls = {"search": [], "verify": [], "download": []}

    def search(q, key, **kw):
        calls["search"].append(q); return cands

    def verify(url, query, **kw):
        calls["verify"].append(url); return url.endswith("b.mp4")   # sadece 2. uyar

    def download(url, cache_dir, **kw):
        calls["download"].append(url)
        p = Path(cache_dir) / "c.mp4"; p.write_bytes(b"mp4"); return p

    d = FootageDeps(search_videos=search, verify_footage=verify, download_video=download)
    match_beat_clip("bee flower", api_key="k", cache_dir=tmp_path,
                    verify=True, vision_call=object(), deps=d)
    assert calls["download"] == ["https://x/b.mp4"]   # reddedileni atladı


def test_match_returns_none_when_no_candidates(tmp_path):
    d, calls = _deps({})
    assert match_beat_clip("nothing", api_key="k", cache_dir=tmp_path,
                           verify=False, deps=d) is None
