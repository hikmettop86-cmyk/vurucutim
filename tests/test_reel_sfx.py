from short_bot.reel_sfx import discover_sfx, pick_sfx_per_cut


def test_discover_sfx(tmp_path):
    (tmp_path/"a.mp3").write_bytes(b"x"); (tmp_path/"b.mp3").write_bytes(b"y")
    (tmp_path/"c.txt").write_bytes(b"z")
    got = discover_sfx(tmp_path)                     # kategori -> dosyalar
    assert list(got) == ["_root"]                    # duz mp3'ler _root'a duser
    assert len(got["_root"]) == 2
    assert all(p.suffix == ".mp3" for p in got["_root"])
    assert discover_sfx(tmp_path/"yok") == {}


def test_pick_sfx_per_cut_deterministic(tmp_path):
    pool = [tmp_path/"a.mp3", tmp_path/"b.mp3", tmp_path/"c.mp3"]
    a = pick_sfx_per_cut(pool, seed=7, n_cuts=4)
    b = pick_sfx_per_cut(pool, seed=7, n_cuts=4)
    assert a == b and len(a) == 4 and all(x in pool for x in a)
    assert pick_sfx_per_cut([], seed=7, n_cuts=3) == []
