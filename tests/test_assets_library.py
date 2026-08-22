import json

from short_bot.assets_library import (MIN_BYTES, MUSIC_MOODS, SFX_CATEGORIES,
                                       build_library, download,
                                       load_library_index, scrape_urls)


class _R:
    def __init__(self, text="", content=b"", status=200):
        self.text = text
        self.content = content
        self.status_code = status


def _page(n, prefix="sfx"):
    urls = "".join(
        f'<a href="https://assets.mixkit.co/active_storage/{prefix}/{i}/{i}-preview.mp3">x</a>'
        for i in range(n))
    return _R(text=f"<html>{urls}</html>")


def test_scrape_urls_unique():
    http_get = lambda u, **kw: _page(3)      # noqa: E731
    urls = scrape_urls("https://mixkit.co/free-sound-effects/whoosh/",
                       http_get=http_get)
    assert len(urls) == 3
    assert all(u.endswith(".mp3") for u in urls)
    # tekrarlar elenir
    dup = lambda u, **kw: _R(text='<a href="https://assets.mixkit.co/a/1/1.mp3">x</a>' * 5)  # noqa: E731
    assert len(scrape_urls("x", http_get=dup)) == 1


def test_download_rejects_tiny_file(tmp_path):
    small = lambda u, **kw: _R(content=b"x" * 100)          # noqa: E731
    assert download("http://a/1.mp3", tmp_path / "a.mp3", http_get=small) is None
    big = lambda u, **kw: _R(content=b"x" * (MIN_BYTES + 1))  # noqa: E731
    out = download("http://a/1.mp3", tmp_path / "b.mp3", http_get=big)
    assert out is not None and out.exists()
    assert out.stat().st_size > MIN_BYTES


def test_build_library_writes_categories_and_manifest(tmp_path):
    def http_get(url, **kw):
        if url.startswith("https://assets.mixkit.co"):
            return _R(content=b"m" * (MIN_BYTES + 10))
        return _page(2)

    res = build_library(tmp_path, per_sfx=2, per_music=2, http_get=http_get)
    assert res["sfx"] == 2 * len(SFX_CATEGORIES)
    assert res["music"] == 2 * len(MUSIC_MOODS)
    # klasör yapısı: assets/sfx/<kategori>/, assets/music/<mood>/
    for cat in SFX_CATEGORIES:
        assert (tmp_path / "sfx" / cat).is_dir()
        assert len(list((tmp_path / "sfx" / cat).glob("*.mp3"))) == 2
    for mood in MUSIC_MOODS:
        assert (tmp_path / "music" / mood).is_dir()
    man = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert set(man["sfx"]) == set(SFX_CATEGORIES)
    assert set(man["music"]) == set(MUSIC_MOODS)
    assert man["built_at"]


def test_build_library_one_category_failure_does_not_stop_others(tmp_path):
    def http_get(url, **kw):
        if "whoosh" in url:
            raise RuntimeError("ağ patladı")
        if url.startswith("https://assets.mixkit.co"):
            return _R(content=b"m" * (MIN_BYTES + 10))
        return _page(1)

    res = build_library(tmp_path, per_sfx=1, per_music=1, http_get=http_get)
    assert res["sfx"] == len(SFX_CATEGORIES) - 1      # whoosh atlandı
    assert res["music"] == len(MUSIC_MOODS)           # müzik etkilenmedi
    assert not (tmp_path / "sfx" / "whoosh").exists() or \
        not list((tmp_path / "sfx" / "whoosh").glob("*.mp3"))


def test_build_library_is_idempotent(tmp_path):
    calls = {"dl": 0}

    def http_get(url, **kw):
        if url.startswith("https://assets.mixkit.co"):
            calls["dl"] += 1
            return _R(content=b"m" * (MIN_BYTES + 10))
        return _page(1)

    build_library(tmp_path, per_sfx=1, per_music=1, http_get=http_get)
    first = calls["dl"]
    build_library(tmp_path, per_sfx=1, per_music=1, http_get=http_get)
    assert calls["dl"] == first          # var olan dosya YENİDEN indirilmedi


def test_load_library_index_from_folders_without_manifest(tmp_path):
    (tmp_path / "sfx" / "whoosh").mkdir(parents=True)
    (tmp_path / "sfx" / "whoosh" / "a.mp3").write_bytes(b"x")
    (tmp_path / "music" / "tense").mkdir(parents=True)
    (tmp_path / "music" / "tense" / "b.mp3").write_bytes(b"x")
    idx = load_library_index(tmp_path)          # manifest YOK → klasör taraması
    assert idx["sfx"]["whoosh"] == ["a.mp3"]
    assert idx["music"]["tense"] == ["b.mp3"]
