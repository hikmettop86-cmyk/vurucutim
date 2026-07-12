from pathlib import Path

from short_bot.footage_matcher import FootageDeps, match_beat_clip
from short_bot.footage_sources import FootageCandidate


class _Src:
    """Tek kaynaklı stub: search_map'ten aday döndürür, çağrıları kaydeder."""
    name = "stub"

    def __init__(self, search_map, calls, downloaded=b"mp4", avail=True):
        self._map = search_map
        self._calls = calls
        self._downloaded = downloaded
        self._avail = avail

    def available(self):
        return self._avail

    def search(self, q, *, max_results, orientation):
        self._calls["search"].append(q)
        return self._map.get(q, [])

    def download(self, cand, cache_dir):
        self._calls["download"].append(cand.url)
        p = Path(cache_dir) / (cand.url.split("/")[-1] or "c.mp4")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self._downloaded)
        return p


def _deps(search_map, downloaded=b"mp4"):
    """FootageDeps(sources=[stub]) + çağrı kaydı. verify her zaman True döner."""
    calls = {"search": [], "verify": [], "download": []}

    def verify(url, query, **kw):
        calls["verify"].append((url, query))
        return True

    src = _Src(search_map, calls, downloaded=downloaded)
    d = FootageDeps(sources=[src], verify_footage=verify)
    return d, calls


def test_match_returns_first_candidate(tmp_path):
    cands = [FootageCandidate(url="https://x/a.mp4", duration_s=10)]
    d, calls = _deps({"bee flower": cands})
    clip = match_beat_clip("bee flower", api_key="k", cache_dir=tmp_path,
                           verify=False, deps=d)
    assert clip is not None and clip.exists()
    assert calls["search"] == ["bee flower"]
    assert calls["verify"] == []            # verify=False -> vision yok


def test_match_uses_vision_when_enabled(tmp_path):
    # thumbnail (image) VAR → indirmeden önce pre-gate çalışır
    cands = [FootageCandidate(url="https://x/a.mp4", duration_s=10, image="https://x/a.jpg")]
    d, calls = _deps({"bee flower": cands})
    match_beat_clip("bee flower", api_key="k", cache_dir=tmp_path,
                    verify=True, vision_call=object(), deps=d)
    assert len(calls["verify"]) == 1


def test_match_frame_gate_when_no_thumbnail_rejects(tmp_path):
    # thumbnail YOK (Storyblocks gibi) → indirdikten SONRA kare-gate; off-topic → reddet
    cands = [FootageCandidate(url="https://x/a.mp4", duration_s=10)]   # image=""
    calls = {"search": [], "verify": [], "download": [], "frame": []}

    def verify(url, query, **kw):
        calls["verify"].append(url); return True

    def frame_gate(clip, query, **kw):
        calls["frame"].append(str(clip)); return False    # off-topic

    src = _Src({"whale": cands}, calls)
    d = FootageDeps(sources=[src], verify_footage=verify, verify_clip_frame=frame_gate)
    clip = match_beat_clip("whale", api_key="k", cache_dir=tmp_path, verify=True,
                           vision_call=object(), deps=d, topic_pool={"whale"})
    assert calls["verify"] == []           # thumbnail yok → pre-gate ATLANDI
    assert len(calls["frame"]) >= 1        # kare-gate çağrıldı (portrait+landscape denenir)
    assert clip is None                    # off-topic → reddedildi (başka aday yok)


def test_match_frame_gate_accepts_on_topic(tmp_path):
    cands = [FootageCandidate(url="https://x/a.mp4", duration_s=10)]   # image=""
    calls = {"search": [], "verify": [], "download": [], "frame": []}

    def frame_gate(clip, query, **kw):
        calls["frame"].append(str(clip)); return True      # on-topic

    src = _Src({"whale": cands}, calls)
    d = FootageDeps(sources=[src], verify_clip_frame=frame_gate)
    clip = match_beat_clip("whale", api_key="k", cache_dir=tmp_path, verify=True,
                           vision_call=object(), deps=d, topic_pool={"whale"})
    assert len(calls["frame"]) == 1 and clip is not None and clip.exists()


def test_match_skips_rejected_by_vision(tmp_path):
    # image=url → verify url'e bakabilir; sadece 2. aday uyar.
    cands = [FootageCandidate(url="https://x/a.mp4", duration_s=10, image="https://x/a.mp4"),
             FootageCandidate(url="https://x/b.mp4", duration_s=8, image="https://x/b.mp4")]
    calls = {"search": [], "verify": [], "download": []}

    def verify(url, query, **kw):
        calls["verify"].append(url); return url.endswith("b.mp4")   # sadece 2. uyar

    src = _Src({"bee flower": cands}, calls)
    d = FootageDeps(sources=[src], verify_footage=verify)
    match_beat_clip("bee flower", api_key="k", cache_dir=tmp_path,
                    verify=True, vision_call=object(), deps=d)
    assert calls["download"] == ["https://x/b.mp4"]   # reddedileni atladı


def test_match_returns_none_when_no_candidates(tmp_path):
    d, calls = _deps({})
    assert match_beat_clip("nothing", api_key="k", cache_dir=tmp_path,
                           verify=False, deps=d) is None


# ── gerçek verify_clip_matches (vision) doğrulaması ──────────────────────
def test_pexels_candidate_has_image_default():
    from short_bot.pexels import PexelsCandidate
    assert PexelsCandidate(id=1, url="u", duration_s=5).image == ""
    assert PexelsCandidate(id=1, url="u", duration_s=5, image="http://x/p.jpg").image \
        == "http://x/p.jpg"


def test_verify_clip_matches_guards():
    from short_bot.footage_matcher import verify_clip_matches
    assert verify_clip_matches("", "bee") is True                       # thumbnail yok
    assert verify_clip_matches("http://x/t.jpg", "bee", vision_call=None) is True  # vision yok


def test_describe_footage_returns_content(monkeypatch):
    from short_bot.footage_matcher import _FootageDescription, describe_footage

    class _Resp:
        status_code = 200
        content = b"\xff\xd8\xff-fake-jpeg"
    monkeypatch.setattr("requests.get", lambda url, timeout=15: _Resp())

    class _VC:
        claude_path = "claude"; model = "gemini"; backend = "openrouter"; api_key = "k"

    def fake_run_json(prompt, schema, **kw):
        return _FootageDescription(content="a human baby in a swimming pool")
    monkeypatch.setattr("short_bot.claude_cli.run_json", fake_run_json)
    assert describe_footage("http://x/t.jpg", vision_call=_VC()) == \
        "a human baby in a swimming pool"
    assert describe_footage("", vision_call=_VC()) == ""          # thumbnail yok
    assert describe_footage("http://x/t.jpg", vision_call=None) == ""  # vision yok


def test_verify_clip_matches_uses_strict_vision_verdict(monkeypatch):
    """Karar vision'ın per-sorgu KATI yargısı — kelime havuzu DEĞİL.

    Gerçek hata: havuz-kapısı soyut alanda ('science history') mükemmel klipleri
    bile reddediyordu; artık vision 'ana özne görünüyor mu' diye karar veriyor."""
    from short_bot.footage_matcher import _FootageVerdict, verify_clip_matches

    class _Resp:
        status_code = 200
        content = b"\xff\xd8\xff-fake-jpeg"
    monkeypatch.setattr("requests.get", lambda url, timeout=15: _Resp())

    class _VC:
        claude_path = "claude"; model = "gemini"; backend = "openrouter"; api_key = "k"

    seen = {}

    def verdict(matches, content):
        def _run(prompt, schema, **kw):
            seen["prompt"] = prompt
            return _FootageVerdict(content=content, matches=matches, reason="r")
        return _run

    # insan bebeği ≠ balina yavrusu → vision reddeder
    monkeypatch.setattr("short_bot.claude_cli.run_json",
                        verdict(False, "a human baby in a swimming pool"))
    assert verify_clip_matches("http://x/t.jpg", "baby whale",
                               vision_call=_VC()) is False
    assert "baby whale" in seen["prompt"]          # sorgu prompt'a girdi

    # soyut alan REGRESYONU: beyin klibi 'human brain anatomy' için KABUL edilmeli
    monkeypatch.setattr("short_bot.claude_cli.run_json",
                        verdict(True, "a glowing holographic human brain"))
    assert verify_clip_matches("http://x/t.jpg", "human brain anatomy",
                               vision_call=_VC(), pool={"science", "history"}) is True


def test_match_passes_pool_to_verify(tmp_path):
    cands = [FootageCandidate(url="https://x/a.mp4", duration_s=10, image="https://x/a.jpg")]
    seen = {}

    def verify(url, query, **kw):
        seen["pool"] = kw.get("pool")
        return True

    src = _Src({"whale": cands}, {"search": [], "verify": [], "download": []})
    d = FootageDeps(sources=[src], verify_footage=verify)
    match_beat_clip("whale", api_key="k", cache_dir=tmp_path, verify=True,
                    vision_call=object(), deps=d, topic_pool={"whale", "ocean"})
    assert seen["pool"] == {"whale", "ocean"}


def test_match_budget_caps_gate_and_downloads(tmp_path):
    """Tarama bütçesi: gate hepsini reddetse bile sınırsız indirme YOK."""
    from short_bot.footage_matcher import MAX_GATE_CHECKS, MAX_PER_SOURCE
    cands = [FootageCandidate(url=f"https://x/{i}.mp4", duration_s=10,
                              image=f"https://x/{i}.jpg") for i in range(50)]
    calls = {"search": [], "verify": [], "download": []}

    def verify(url, query, **kw):
        calls["verify"].append(url); return False       # her adayı reddet

    src = _Src({"q": cands}, calls)
    d = FootageDeps(sources=[src], verify_footage=verify)
    budget = {"gate": 0, "dl": 0}
    clip = match_beat_clip("q", api_key="k", cache_dir=tmp_path, verify=True,
                           vision_call=object(), deps=d, budget=budget)
    assert clip is None
    assert calls["download"] == []                      # hiç indirme yok (pre-gate)
    # kaynak başına aday sınırı çalıştı (bütçe tavanının da altında)
    assert len(calls["verify"]) <= MAX_PER_SOURCE
    assert budget["gate"] <= MAX_GATE_CHECKS


def test_match_budget_shared_across_sources(tmp_path):
    """Storyblocks (thumbnail'sız) tekelleşemez: kaynak başına aday sınırı +
    paylaşılan bütçe → sıradaki kaynağa (pexels) sıra gelir."""
    sb = [FootageCandidate(url=f"https://sb/{i}.mp4", duration_s=10) for i in range(20)]
    px = [FootageCandidate(url="https://px/ok.mp4", duration_s=10,
                           image="https://px/ok.jpg")]
    calls = {"search": [], "verify": [], "download": [], "frame": []}

    def frame_gate(clip, query, **kw):
        calls["frame"].append(str(clip)); return False   # storyblocks hep reddedilir

    def verify(url, query, **kw):
        calls["verify"].append(url); return True         # pexels kabul

    s_sb = _Src({"q": sb}, calls); s_sb.name = "storyblocks"
    s_px = _Src({"q": px}, calls); s_px.name = "pexels"
    d = FootageDeps(sources=[s_sb, s_px], verify_footage=verify,
                    verify_clip_frame=frame_gate)
    clip = match_beat_clip("q", api_key="k", cache_dir=tmp_path, verify=True,
                           vision_call=object(), deps=d, budget={"gate": 0, "dl": 0})
    assert clip is not None and "ok.mp4" in str(clip)    # pexels'e sıra geldi
    from short_bot.footage_matcher import MAX_PER_SOURCE
    assert len(calls["frame"]) <= MAX_PER_SOURCE         # storyblocks sınırlandı


def test_match_passes_thumbnail_not_mp4(tmp_path):
    """Vision doğrulama mp4'e değil, klibin THUMBNAIL'ına (image) gitmeli."""
    cands = [FootageCandidate(url="https://x/a.mp4", duration_s=10,
                              image="https://x/poster.jpg")]
    calls = {"search": [], "verify": [], "download": []}

    def verify(url, query, **kw):
        calls["verify"].append(url); return True

    src = _Src({"bee": cands}, calls)
    d = FootageDeps(sources=[src], verify_footage=verify)
    match_beat_clip("bee", api_key="k", cache_dir=tmp_path, verify=True,
                    vision_call=object(), deps=d)
    assert calls["verify"] == ["https://x/poster.jpg"]


def test_match_excludes_already_taken_clips(tmp_path):
    """Aynı beat için 2. klip istenince İLK klip tekrar gelmemeli (çoklu klip)."""
    cands = [FootageCandidate(url="https://x/a.mp4", duration_s=10, image="https://x/a.jpg"),
             FootageCandidate(url="https://x/b.mp4", duration_s=10, image="https://x/b.jpg")]
    calls = {"search": [], "verify": [], "download": []}

    def verify(url, query, **kw):
        calls["verify"].append(url); return True

    src = _Src({"q": cands}, calls)
    d = FootageDeps(sources=[src], verify_footage=verify)
    clip = match_beat_clip("q", api_key="k", cache_dir=tmp_path, verify=True,
                           vision_call=object(), deps=d,
                           exclude={"https://x/a.mp4"})
    assert calls["download"] == ["https://x/b.mp4"]     # a atlandı
    assert clip is not None


def test_gate_rejects_dark_murky_clip_even_when_topic_matches(monkeypatch):
    """Konuya UYSA bile karanlık/bulanık klip reddedilir.

    Gerçek üretim (short 170): 6 saniye boyunca ne olduğu anlaşılmayan siyah
    kütle gösterildi — konuyla ilişkiliydi ama izleyici hiçbir şey göremedi."""
    from short_bot.footage_matcher import _FootageVerdict, verify_clip_matches

    class _Resp:
        status_code = 200
        content = b"\xff\xd8\xff-fake-jpeg"
    monkeypatch.setattr("requests.get", lambda url, timeout=15: _Resp())

    class _VC:
        claude_path = "claude"; model = "gemini"; backend = "openrouter"; api_key = "k"

    # konuya uyuyor AMA görsel bulanık/karanlık → REDDET
    monkeypatch.setattr("short_bot.claude_cli.run_json",
        lambda p, s, **kw: _FootageVerdict(
            content="an indistinct dark blurry mass", matches=True, clear=False,
            reason="çok karanlık"))
    assert verify_clip_matches("http://x/t.jpg", "invisible warrior",
                               vision_call=_VC()) is False

    # karanlık AMA net (siyah zeminde parlayan mikroplar) → KABUL
    monkeypatch.setattr("short_bot.claude_cli.run_json",
        lambda p, s, **kw: _FootageVerdict(
            content="glowing microbes on a dark background", matches=True,
            clear=True))
    assert verify_clip_matches("http://x/t.jpg", "microbes",
                               vision_call=_VC()) is True


def test_gate_rejects_out_of_context_clip_metaphor_trap(monkeypatch):
    """METAFOR TUZAĞI: anlatım 'görünmez savaşçılar' (=bakteriyofaj) deyince sorgu
    metafora kayıyor ve stok kütüphane kelimeyi DÜZ anlıyor → ESKRİMCİ geliyor.

    Gate'e videonun GERÇEK konusu (context) verilince vision bunu eler."""
    from short_bot.footage_matcher import _FootageVerdict, _judge_prompt, \
        verify_clip_matches

    # bağlam prompt'a giriyor mu
    p = _judge_prompt("invisible warrior", context="bakteriyofaj virüsü bakteri avlar")
    assert "VİDEONUN KONUSU" in p and "bakteriyofaj virüsü" in p
    assert "BAĞLAM" in p
    # bağlam yoksa o blok hiç yok (geriye uyum)
    assert "VİDEONUN KONUSU" not in _judge_prompt("invisible warrior")

    class _Resp:
        status_code = 200
        content = b"\xff\xd8\xff-fake-jpeg"
    monkeypatch.setattr("requests.get", lambda url, timeout=15: _Resp())

    class _VC:
        claude_path = "claude"; model = "gemini"; backend = "openrouter"; api_key = "k"

    seen = {}

    def _run(prompt, schema, **kw):
        seen["prompt"] = prompt
        # vision bağlamı görüp eskrimciyi konu-dışı sayar
        return _FootageVerdict(content="a fencer in a dark mask", matches=False,
                               clear=True, reason="konu bakteriyofaj, eskrimci ilgisiz")
    monkeypatch.setattr("short_bot.claude_cli.run_json", _run)
    ok = verify_clip_matches("http://x/t.jpg", "invisible warrior",
                             vision_call=_VC(),
                             context="bakteriyofaj virüsü bakteri avlar")
    assert ok is False
    assert "bakteriyofaj" in seen["prompt"]      # bağlam vision'a ulaştı
