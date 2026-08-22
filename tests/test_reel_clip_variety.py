"""Video-genelinde klip ÇEŞİTLİLİĞİ.

GERÇEK HATA (short_id=171, dil-yiyen parazit): 43sn'lik videonun 22 saniyesi TEK,
HAREKETSİZ bir insan-anatomi illüstrasyonuydu. Chip etiketi 5 kez değişiyor
(segmentler ilerliyor) ama arka plan hiç değişmiyordu.

İki kusur birden:
  1) ``exclude`` SEGMENT kapsamlıydı — her segmentin başında sıfırlanıyordu. Sorgular
     birbirine benzediği için arama her segmentte AYNI en-iyi klibi döndürüyordu.
  2) Kapıdan aday geçmeyince ``reuse_clips[-1]`` ile hep SON klip tekrarlanıyordu.
     Bir kez sıkışınca video donuyordu.
"""
from pathlib import Path

from short_bot.config import ReelConfig
from short_bot.reel import ReelDeps, produce_reel_video
from short_bot.reel_models import ReelBeat, ReelNarration


def _narr():
    return ReelNarration(
        hook="Bir balık parazitle yaşayabilir mi?",
        beats=[
            ReelBeat(text="İşgalci Cymothoa exigua.", visual_query="cymothoa exigua",
                     keyword="PARAZİT"),
            ReelBeat(text="Balığın diline yapışır.", visual_query="fish tongue parasite",
                     keyword="DİL"),
            ReelBeat(text="Kanını emer ve dil ölür.", visual_query="parasite fish mouth",
                     keyword="KAYIP"),
            ReelBeat(text="Parazit yeni dil olur.", visual_query="isopod fish",
                     keyword="YENİ DİL"),
        ],
        close="Denizin sessiz kabusu.", mood="neutral",
    )


class _Channel:
    slug = "test-reel"; language = "tr"; handle = "@test"
    colors = {"primary": "#0ea5e9", "accent": "#facc15",
              "bg_gradient": ["#0f172a", "#020617"]}
    reel = ReelConfig(enabled=True, voice_id="elevenlabs_v1",
                      target_duration_s=(25, 45), ai_director=False)


def _base_deps(calls, match):
    return ReelDeps(
        write_reel_narration=lambda *a, **kw: _narr(),
        health_check=lambda **kw: "healthy",
        synthesize=lambda text, **kw: (Path(kw["out_path"]).write_bytes(b"mp3"),
                                       Path(kw["out_path"]))[1],
        probe_duration_s=lambda p, **kw: 40.0,
        transcribe_words=lambda p, **kw: [],
        match_beat_clip=match,
        render_reel_overlay_frames=lambda tl, out, **kw: 1200,
        assemble_reel=lambda **kw: (calls.append(kw), kw["out_path"])[1],
    )


def _run(deps, tmp_path):
    return produce_reel_video(
        topic="dil yiyen parazit", channel=_Channel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg", deps=deps)


def _clip(cache_dir, name) -> Path:
    d = Path(cache_dir); d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.mp4"; p.write_bytes(b"mp4")
    return p


def test_greedy_source_cannot_freeze_the_video(tmp_path):
    """Arama her sorgu için AYNI 'en iyi' klibi döndürse bile video donmamalı.

    Kaynakta 6 klip var ama sıralama hep aynı → exclude video-geneli olmazsa
    her segment 'top1'i alır ve video tek görüntüye kilitlenir (gerçek hata).
    """
    POOL = [f"clip{i}" for i in range(6)]
    calls = []

    def match(q, **kw):
        exclude = kw.get("exclude") or set()
        for name in POOL:            # sıralama SABİT — hep aynı 'en iyi' önce
            p = _clip(kw["cache_dir"], name)
            if str(p) not in exclude:
                return p
        return None

    _run(_base_deps(calls, match), tmp_path)
    clips = calls[0]["clip_paths"]
    distinct = {str(c) for c in clips}
    assert len(distinct) >= 5, (
        f"video {len(distinct)} farklı klipte kilitlendi (havuzda 6 var): "
        f"{sorted(distinct)}")


def test_reuse_rotates_instead_of_freezing_on_one_clip(tmp_path):
    """GERÇEK SENARYONUN BİREBİRİ: ilk beat klip buluyor, sonrakiler bulamıyor.

    short_id=171'de tam bu oldu — kalan segmentlerin hepsi ``reuse_clips[-1]``
    ile AYNI klibi aldı ve video 22 saniye dondu. Tekrar kaçınılmaz, ama elde
    3 kabul edilmiş klip varken hepsi dönüşümlü kullanılmalı.
    """
    POOL = ["a", "b", "c"]
    calls = []
    seen_queries: set = set()

    def match(q, **kw):
        # Yalnız İLK sorgu klip bulur; sonraki tüm sorgular boş döner
        # (kaynakta o beat'e uyan görüntü yok — 'Cymothoa exigua' durumu).
        if seen_queries and q not in seen_queries:
            return None
        seen_queries.add(q)
        exclude = kw.get("exclude") or set()
        for name in POOL:
            p = _clip(kw["cache_dir"], name)
            if str(p) not in exclude:
                return p
        return None

    _run(_base_deps(calls, match), tmp_path)
    clips = [str(c) for c in calls[0]["clip_paths"]]
    assert len({*clips}) == 3, f"3 kabul edilmiş klibin hepsi kullanılmalıydı: {set(clips)}"

    # DONMA METRİĞİ: ekranda kesintisiz kaç kesim boyunca aynı görüntü kalıyor.
    # Dağınık tekrar sorun değil (motif hissi); ARKA ARKAYA tekrar videoyu dondurur.
    # Eski kod burada 8 kesim üst üste aynı klibi gösteriyordu (= 22sn donma).
    longest, run = 1, 1
    for a, b in zip(clips, clips[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    assert longest <= 3, (
        f"aynı klip {longest} kesim ÜST ÜSTE ekranda kaldı → video donuyor: {clips}")
