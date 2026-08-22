from short_bot.reel_sfx import discover_sfx, pick_sfx_per_cut


def _lib(tmp_path, cats):
    for cat, n in cats.items():
        d = tmp_path / cat
        d.mkdir(parents=True)
        for i in range(n):
            (d / f"{cat}{i}.mp3").write_bytes(b"x")
    return tmp_path


def test_discover_reads_categories_and_legacy_root(tmp_path):
    _lib(tmp_path, {"whoosh": 2, "impact": 3})
    (tmp_path / "eski.mp3").write_bytes(b"x")      # eski düz kütüphane
    d = discover_sfx(tmp_path)
    assert set(d) == {"whoosh", "impact", "_root"}
    assert len(d["impact"]) == 3 and len(d["_root"]) == 1


def test_no_repeat_within_video(tmp_path):
    """AYNI SES bir videoda tekrar ÇALMAZ (parmak izinin ana kaynağıydı)."""
    pool = discover_sfx(_lib(tmp_path, {"whoosh": 10, "impact": 10}))
    picks = pick_sfx_per_cut(pool, seed=7, n_cuts=18)
    assert len(picks) == 18
    assert len(set(map(str, picks))) == 18        # 18 kesim → 18 FARKLI dosya


def test_plan_drives_category_choice(tmp_path):
    pool = discover_sfx(_lib(tmp_path, {"whoosh": 5, "impact": 5}))
    plan = ["impact", "whoosh", "impact"]
    picks = pick_sfx_per_cut(pool, seed=3, n_cuts=3, sfx_plan=plan)
    assert [p.parent.name for p in picks] == plan   # kurgucunun planına uydu


def test_exhausted_category_falls_back_gracefully(tmp_path):
    pool = discover_sfx(_lib(tmp_path, {"whoosh": 2}))
    picks = pick_sfx_per_cut(pool, seed=1, n_cuts=5, sfx_plan=["whoosh"] * 5)
    assert len(picks) == 5          # tükenince tekrar serbest (çökme yok)


def test_legacy_flat_list_pool_still_works(tmp_path):
    """Eski çağıranlar düz liste veriyordu — kırılmamalı."""
    files = []
    for i in range(3):
        f = tmp_path / f"a{i}.mp3"; f.write_bytes(b"x"); files.append(f)
    picks = pick_sfx_per_cut(files, seed=2, n_cuts=3)
    assert len(picks) == 3 and len(set(map(str, picks))) == 3


def test_empty_pool_returns_empty(tmp_path):
    assert pick_sfx_per_cut({}, seed=1, n_cuts=5) == []
    assert pick_sfx_per_cut(discover_sfx(tmp_path), seed=1, n_cuts=5) == []
