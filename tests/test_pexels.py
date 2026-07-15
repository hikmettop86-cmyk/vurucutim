import os
from pathlib import Path

import pytest

from short_bot.pexels import _pick_best_mp4, load_secrets, resolve_pexels_api_key


def _f(link, w, h):
    return {"file_type": "video/mp4", "link": link, "width": w, "height": h}


def test_pick_best_mp4_1080_yerine_4k_secmez():
    # Final video 1080x1920; 4K indirmek 4x veri israfı (footage darboğazı buydu).
    files = [_f("uhd", 2160, 3840), _f("fhd", 1080, 1920),
             _f("hd", 720, 1280), _f("sd", 360, 640)]
    assert _pick_best_mp4(files) == "fhd"


def test_pick_best_mp4_yatay_1080_secer():
    assert _pick_best_mp4([_f("l4k", 3840, 2160), _f("l1080", 1920, 1080)]) == "l1080"


def test_pick_best_mp4_hicbiri_1080_degilse_en_iyisi():
    assert _pick_best_mp4([_f("hd", 720, 1280), _f("sd", 360, 640)]) == "hd"


def test_pick_best_mp4_bos_liste_none():
    assert _pick_best_mp4([]) is None


def test_load_secrets_returns_empty_dict_when_file_missing(tmp_path):
    assert load_secrets(tmp_path / "missing.yaml") == {}


def test_load_secrets_parses_yaml(tmp_path):
    p = tmp_path / "secrets.yaml"
    p.write_text("pexels_api_key: abc123\n", encoding="utf-8")
    assert load_secrets(p) == {"pexels_api_key": "abc123"}


def test_resolve_returns_env_var_when_set(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "from-env")
    assert resolve_pexels_api_key({"pexels_api_key": "from-file"}) == "from-env"


def test_resolve_falls_back_to_secrets_dict(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert resolve_pexels_api_key({"pexels_api_key": "from-file"}) == "from-file"


def test_resolve_returns_empty_string_when_neither_set(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert resolve_pexels_api_key({}) == ""


from short_bot.pexels import ARCHETYPE_BG_QUERIES, pick_query_for_archetype


def test_archetype_pool_covers_all_archetypes():
    """BG_QUERIES must have an entry for every archetype in the registry."""
    from short_bot.dna import ARCHETYPES
    assert set(ARCHETYPE_BG_QUERIES.keys()) == set(ARCHETYPES)


def test_each_archetype_pool_has_at_least_three_queries():
    for arch, queries in ARCHETYPE_BG_QUERIES.items():
        assert len(queries) >= 3, f"{arch} has fewer than 3 queries"


def test_pick_query_returns_member_of_pool():
    q = pick_query_for_archetype("newscast")
    assert q in ARCHETYPE_BG_QUERIES["newscast"]


def test_pick_query_unknown_archetype_falls_back_to_generic():
    q = pick_query_for_archetype("nonexistent-xyz")
    assert q == "abstract motion background"


from unittest.mock import patch, MagicMock

from short_bot.pexels import PexelsCandidate, search_videos


def _mock_response(json_payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_payload
    return r


def test_search_videos_returns_candidates_from_api_payload():
    payload = {
        "videos": [
            {
                "id": 111,
                "duration": 12,
                "video_files": [
                    {"link": "https://x/lo.mp4", "width": 540,  "height": 960,  "file_type": "video/mp4"},
                    {"link": "https://x/hd.mp4", "width": 1080, "height": 1920, "file_type": "video/mp4"},
                ],
            },
            {
                "id": 222,
                "duration": 8,
                "video_files": [
                    {"link": "https://y/hd.mp4", "width": 720, "height": 1280, "file_type": "video/mp4"},
                ],
            },
        ]
    }
    with patch("short_bot.pexels.requests.get", return_value=_mock_response(payload)):
        out = search_videos("query", api_key="KEY", max_results=5)
    assert len(out) == 2
    assert out[0].id == 111
    assert out[0].url == "https://x/hd.mp4"
    assert out[0].duration_s == 12
    assert out[1].url == "https://y/hd.mp4"


def test_search_videos_returns_empty_on_http_error():
    with patch("short_bot.pexels.requests.get", return_value=_mock_response({}, status=429)):
        out = search_videos("q", api_key="KEY")
    assert out == []


def test_search_videos_returns_empty_on_request_exception():
    import requests
    with patch("short_bot.pexels.requests.get", side_effect=requests.RequestException("boom")):
        out = search_videos("q", api_key="KEY")
    assert out == []


def test_search_videos_returns_empty_when_no_videos_field():
    with patch("short_bot.pexels.requests.get", return_value=_mock_response({"videos": []})):
        out = search_videos("q", api_key="KEY")
    assert out == []


def test_search_videos_skips_candidates_without_mp4_files():
    payload = {"videos": [{"id": 333, "duration": 5, "video_files": []}]}
    with patch("short_bot.pexels.requests.get", return_value=_mock_response(payload)):
        out = search_videos("q", api_key="KEY")
    assert out == []


def test_search_videos_passes_authorization_header_and_orientation():
    captured = {}
    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        return _mock_response({"videos": []})
    with patch("short_bot.pexels.requests.get", side_effect=fake_get):
        search_videos("query", api_key="MYKEY", max_results=3)
    assert captured["headers"]["Authorization"] == "MYKEY"
    assert captured["params"]["query"] == "query"
    assert captured["params"]["orientation"] == "portrait"
    assert captured["params"]["per_page"] == 3


from short_bot.pexels import download_video


def test_download_video_returns_cached_path_when_already_present(tmp_path):
    cache = tmp_path / "videos"
    cache.mkdir()
    import hashlib
    url = "https://example.com/clip.mp4"
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    cached = cache / f"{key}.mp4"
    cached.write_bytes(b"already-here")

    with patch("short_bot.pexels.requests.get") as gm:
        out = download_video(url, cache)
    assert out == cached
    gm.assert_not_called()


def test_download_video_writes_response_body_to_cache(tmp_path):
    cache = tmp_path / "videos"
    fake = MagicMock()
    fake.status_code = 200
    fake.iter_content.return_value = iter([b"chunk1", b"chunk2"])
    fake.__enter__ = lambda self: self
    fake.__exit__ = lambda *a: None

    with patch("short_bot.pexels.requests.get", return_value=fake):
        out = download_video("https://example.com/x.mp4", cache)
    assert out is not None
    assert out.exists()
    assert out.read_bytes() == b"chunk1chunk2"


def test_download_video_returns_none_on_http_error(tmp_path):
    fake = MagicMock()
    fake.status_code = 404
    fake.__enter__ = lambda self: self
    fake.__exit__ = lambda *a: None
    with patch("short_bot.pexels.requests.get", return_value=fake):
        out = download_video("https://example.com/x.mp4", tmp_path / "videos")
    assert out is None


def test_download_video_returns_none_on_request_exception(tmp_path):
    import requests
    with patch("short_bot.pexels.requests.get",
               side_effect=requests.RequestException("boom")):
        out = download_video("https://example.com/x.mp4", tmp_path / "videos")
    assert out is None
