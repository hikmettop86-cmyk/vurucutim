import dataclasses
from pathlib import Path

from short_bot.config import ReelConfig, load_channel
from short_bot.footage_matcher import SubjectPos
from short_bot.reel import ReelDeps, produce_reel_video
from short_bot.reel_models import ReelBeat, ReelNarration, TimedWord

_CH = """slug: t
name: Test
keywords: [a]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#0a2540', accent: '#2de2e6', bg_gradient: ['#0A2540','#04121F']}
handle: '@t'
output_dir: out
enabled: false
content_source: generator
generator: {topic: 'test konusu'}
"""


def _channel(tmp_path, **reel_kw):
    y = tmp_path / "ch.yaml"
    y.write_text(_CH, encoding="utf-8")
    ch = load_channel(y)
    return dataclasses.replace(ch, reel=ReelConfig(
        enabled=True, voice_id="v", arrows_enabled=False,
        transitions_whoosh=False, **reel_kw))


def _narration():
    beats = [ReelBeat(text=f"Beat {i} cumlesi burada uzun", visual_query=f"q{i}",
                      keyword=f"K{i}") for i in range(3)]
    return ReelNarration(hook="Hook cumlesi burada", beats=beats,
                         close="Close cumlesi burada", mood="neutral",
                         hook_visual="hq", close_visual="cq")


def _deps(tmp_path):
    calls = {"match": [], "captured": {}}

    def match(q, **kw):
        calls["match"].append((q, kw.get("exclude")))
        p = Path(kw["cache_dir"]); p.mkdir(parents=True, exist_ok=True)
        f = p / f"{len(calls['match'])}.mp4"; f.write_bytes(b"m")
        return f

    def transcribe(mp3, **kw):
        # 5 segment × 6 kelime, 30sn → beat'ler bölünecek kadar uzun
        out = []
        for i in range(30):
            out.append(TimedWord(word=f"w{i}", start_s=i * 1.0, end_s=i * 1.0 + 0.8,
                                 seg=min(4, i // 6)))
        return out

    def assemble(**kw):
        calls["captured"].update(kw)
        Path(kw["out_path"]).write_bytes(b"mp4")
        return kw["out_path"]

    def render(timeline, out_dir, **kw):
        calls["captured"]["numbers"] = kw.get("numbers")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        return 1

    d = ReelDeps(
        write_reel_narration=lambda topic, **kw: _narration(),
        health_check=lambda **kw: "healthy",
        synthesize=lambda text, **kw: Path(kw["out_path"]).write_bytes(b"a"),
        probe_duration_s=lambda p, **kw: 30.0,
        transcribe_words=transcribe,
        match_beat_clip=match,
        locate_subject=lambda *a, **kw: SubjectPos(),
        render_reel_overlay_frames=render,
        assemble_reel=assemble,
    )
    return d, calls


def _produce(tmp_path, d, **reel_kw):
    produce_reel_video(
        topic="konu", channel=_channel(tmp_path, **reel_kw),
        templates_dir=tmp_path, work_dir=tmp_path / "w",
        out_path=tmp_path / "o.mp4", music_path=None, ai33_api_key="k",
        pexels_api_key="k", deps=d)


def test_fast_cuts_produce_more_segments_than_beats(tmp_path):
    """Hızlı kesim: 5 segment → çok daha fazla alt-kesim (b-roll sık değişir)."""
    d, calls = _deps(tmp_path)
    _produce(tmp_path, d, fast_cuts=True)
    cap = calls["captured"]
    assert len(cap["clip_paths"]) == len(cap["seg_spans"])
    assert len(cap["seg_spans"]) > 5              # 5 segment'ten fazla parça
    assert cap["hook_punch"] is True              # açılış kalıp kırıcı
    assert len(cap["clip_starts"]) == len(cap["clip_paths"])
    assert len(cap["cut_times"]) == len(cap["seg_spans"]) - 1


def test_fast_cuts_requests_multiple_clips_per_beat(tmp_path):
    """Beat başına birden çok klip istenir ve exclude ile tekrar önlenir."""
    d, calls = _deps(tmp_path)
    _produce(tmp_path, d, fast_cuts=True)
    # aynı beat sorgusu ('q0') birden çok kez, 2.'de exclude dolu
    q0 = [(q, ex) for q, ex in calls["match"] if q == "q0"]
    assert len(q0) >= 2
    assert q0[1][1]                                # 2. çağrıda exclude dolu


def test_visual_loop_close_uses_hook_clip(tmp_path):
    # visual_loop-close artık KOŞULLU: yalnız kapanış span'i KAPANIS_LOOP_MAX_S(=5s)
    # altındaysa hook klibi loop edilir (short 821: uzun kapanışta 12sn freeze olmasın).
    # 5 segment 30s'e yayılınca kapanış ~5.3s>5 → loop atlanır. Toplam süreyi 24s'e çekersek
    # kapanış ~4.3s≤5 → loop tetiklenir (bu testin niyeti: loop KOŞULU sağlanınca çalışıyor mu).
    d, calls = _deps(tmp_path)
    d = dataclasses.replace(d, probe_duration_s=lambda p, **kw: 24.0)
    _produce(tmp_path, d, fast_cuts=False, visual_loop=True)
    cap = calls["captured"]
    assert len(cap["seg_spans"]) == 5             # fast_cuts kapalı → segment sayısı
    assert cap["clip_paths"][0] == cap["clip_paths"][-1]   # kısa kapanış → hook klibi loop


def _narration_with_numbers():
    """Sayılar ANLATIM METNİNDEN gelir (timeline.words narration'dan kurulur)."""
    beats = [ReelBeat(text="Beyni 240 parçaya bölündü tam olarak",
                      visual_query="q0", keyword="K0"),
             ReelBeat(text="Toplam 24 milyon kişi bunu izledi",
                      visual_query="q1", keyword="K1"),
             ReelBeat(text="Sıradan bir cumle burada duruyor",
                      visual_query="q2", keyword="K2")]
    return ReelNarration(hook="Hook cumlesi burada", beats=beats,
                         close="Close cumlesi burada", mood="neutral",
                         hook_visual="hq", close_visual="cq")


def test_number_pop_passed_to_render(tmp_path):
    d, calls = _deps(tmp_path)
    d = dataclasses.replace(
        d, write_reel_narration=lambda topic, **kw: _narration_with_numbers())
    _produce(tmp_path, d, number_pop=True)
    nums = calls["captured"]["numbers"]
    texts = [n["text"] for n in nums]
    assert "240 parçaya" in texts
    assert "24 milyon" in texts


def test_number_pop_off_gives_empty(tmp_path):
    d, calls = _deps(tmp_path)
    d = dataclasses.replace(
        d, write_reel_narration=lambda topic, **kw: _narration_with_numbers())
    _produce(tmp_path, d, number_pop=False)
    assert calls["captured"]["numbers"] == []
