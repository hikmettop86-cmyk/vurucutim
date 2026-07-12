"""Reel (footage-sürüklü) üretim orkestratörü.

Zincir: preflight → reel senaryosu → TTS → hizalama → footage eşleştirme →
montaj. Tüm dış bağımlılıklar ReelDeps üzerinden enjekte edilir.
TTS/footage/montaj başarısızsa net Türkçe hatayla durur (sessiz fallback yok).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from short_bot.audio_probe import probe_duration_s as _probe
from short_bot.footage_matcher import FootageDeps, SubjectPos
from short_bot.footage_matcher import locate_subject as _locate
from short_bot.footage_matcher import match_beat_clip as _match
from short_bot.footage_sources import build_footage_sources
from short_bot.reel_assembler import assemble_reel as _assemble
from short_bot.reel_markers import _marker_worthy_segs, build_markers
from short_bot.reel_models import build_reel_timeline
from short_bot.reel_narration import write_reel_narration as _write_narr
from short_bot.reel_numbers import find_numbers
from short_bot.reel_pacing import plan_subcuts, subcut_clip_index
from short_bot.reel_render import render_reel_overlay_frames as _render
from short_bot.reel_sfx import discover_sfx, pick_sfx_per_cut
from short_bot.tts.ai33_client import health_check as _health
from short_bot.tts.ai33_client import synthesize as _synth
from short_bot.tts.align import transcribe_words as _transcribe

log = logging.getLogger(__name__)

_PREFLIGHT = {
    "no-key": "ai33 için AI33_API_KEY tanımlı değil (Ayarlar → API anahtarları).",
    "auth": "ai33 reddetti: AI33_API_KEY geçersiz ya da kredi bitmiş.",
    "no-voice": "reel.voice_id boş — panelden bir ses seç.",
    "stalled": "ai33 kuyruk takılı (preflight zaman aşımı); üretim iptal, kredi harcanmadı.",
    "error": "ai33 preflight başarısız — servis yanıt vermiyor.",
}


@dataclass(frozen=True)
class ReelDeps:
    write_reel_narration: Callable = _write_narr
    health_check: Callable = _health
    synthesize: Callable = _synth
    probe_duration_s: Callable = _probe
    transcribe_words: Callable = _transcribe
    match_beat_clip: Callable = _match
    locate_subject: Callable = _locate
    render_reel_overlay_frames: Callable = _render
    assemble_reel: Callable = _assemble


def _match_with_fallback(d, query, *, topic_q, api_key, cache_dir, verify,
                         vision_call, footage_deps=None, topic_pool=None, anchor="",
                         ffmpeg_path="ffmpeg", budget=None, reuse_clips=None,
                         exclude=None):
    """Footage eşleştirmeyi kademeli, KONUDA-KALAN yedeklerle dener.

    Sıra: (1) tam sorgu, (2) ilk 2 kelime, (3) konu tohumu, (4) kanal çıpası —
    hepsi vision + topic_pool gate'li. Son çare (5): çıpa sorgusu vision'sız
    (arama TERİMİ çıpa olduğundan sonuç konuda; ham ilk-2-kelime garbage grab YOK).
    ``footage_deps`` kaynak zincirini (öncelik-sıralı) taşır.
    """
    words = query.split()
    stages = [query]
    if len(words) > 2:
        stages.append(" ".join(words[:2]))
    if topic_q and topic_q.lower() not in (s.lower() for s in stages):
        stages.append(topic_q)
    if anchor and anchor.lower() not in (s.lower() for s in stages):
        stages.append(anchor)
    # Tarama bütçesi SEGMENT boyunca paylaşılır: tüm fallback aşamaları aynı
    # kovadan yer → tek segment onlarca Storyblocks indirmesiyle dakikalar yakamaz.
    b = budget if budget is not None else {"gate": 0, "dl": 0}
    for q in stages:
        clip = d.match_beat_clip(q, api_key=api_key, cache_dir=cache_dir,
                                 verify=verify, vision_call=vision_call,
                                 deps=footage_deps, topic_pool=topic_pool,
                                 ffmpeg_path=ffmpeg_path, budget=b,
                                 exclude=exclude)
        if clip is not None:
            return clip
    # Vision kapısından geçen aday YOK. Çıpayı vision'sız aramak ÇÖP getiriyor
    # (gerçek hata: soyut 'oto-kanibalizm' beat'i → çıpa 'science history' →
    # tablo pazarı açılış karesi). Bunun yerine: bu videoda ZATEN kabul edilmiş
    # (konuda) bir klibi tekrar kullan — tekrar, alakasızdan iyidir.
    if reuse_clips:
        log.info(f"  footage: '{query[:30]}' için kapıdan geçen aday yok → "
                 f"bu videonun kabul edilmiş klibi tekrar kullanılıyor")
        return reuse_clips[-1]
    # Hiç klip yoksa (ilk segment) — mecburen çıpa sorgusu, vision'sız.
    last_q = anchor or (" ".join(words[:2]) if len(words) >= 2 else (words[0] if words else topic_q))
    return d.match_beat_clip(last_q, api_key=api_key, cache_dir=cache_dir,
                             verify=False, vision_call=None, deps=footage_deps,
                             topic_pool=None, ffmpeg_path=ffmpeg_path,
                             budget={"gate": 0, "dl": 0})


def produce_reel_video(
    *, topic: str, channel, templates_dir: Path, work_dir: Path,
    out_path: Path, music_path: Path | None, ai33_api_key: str,
    pexels_api_key: str, pixabay_api_key: str = "",
    footage_priority: list | None = None,
    storyblocks_session: str | None = None,
    ffmpeg_path: str = "ffmpeg", fps: int = 30,
    browser: str = "chromium",
    llm_claude_path: str = "claude", llm_model: str = "default",
    llm_backend: str = "claude_cli", llm_api_key: str | None = None,
    whisper_quality: str = "auto", whisper_device: str = "auto",
    vision_call=None, seed: int = 0, deps: ReelDeps | None = None,
    hook_patterns=None,
) -> Path:
    reel = getattr(channel, "reel", None)
    if reel is None or not reel.enabled:
        raise ValueError("produce_reel_video: channel.reel etkin değil")
    d = deps or ReelDeps()
    work_dir = Path(work_dir); work_dir.mkdir(parents=True, exist_ok=True)

    # Varyasyon profili (deterministik: aynı seed → aynı profil). Reel etkin
    # kontrolünden SONRA hesaplanır; saf fonksiyon (çağrı zincirine girmez).
    from short_bot.reel_variation import build_variation_profile
    profile = build_variation_profile(channel, seed)

    # Abone bitleri (deterministik: aynı seed → aynı seri/yorum/cta).
    from short_bot.reel_subscribe import build_subscribe_bits
    bits = build_subscribe_bits(channel, seed)

    # Faz zamanlayıcı: hangi aşama ne kadar sürdü (üretim yavaşlığı teşhisi).
    import time as _time
    _t0 = _time.perf_counter()
    _phase_t = {}

    def _phase(name: str) -> None:
        nonlocal _t0
        dt = _time.perf_counter() - _t0
        _phase_t[name] = dt
        _t0 = _time.perf_counter()
        log.info(f"  reel[süre] {name}: {dt:.1f}s")

    # 1) Preflight (LLM/TTS kredisi harcamadan)
    verdict = d.health_check(voice_id=reel.voice_id, api_key=ai33_api_key, tmp_dir=work_dir)
    if verdict != "healthy":
        raise RuntimeError(_PREFLIGHT.get(verdict, f"ai33 preflight: {verdict}"))
    log.info("  reel: ai33 preflight healthy")
    _phase("preflight")

    # 2) Senaryo
    narration = d.write_reel_narration(topic, channel=channel,
                                       claude_path=llm_claude_path, model=llm_model,
                                       backend=llm_backend, api_key=llm_api_key,
                                       hook_angle=profile.hook_angle,
                                       series_directive=bits.series_directive,
                                       comment_line=bits.comment_line,
                                       hook_patterns=hook_patterns)
    log.info(f"  reel: {narration.word_count()} kelime, {len(narration.beats)} beat")
    _phase("senaryo(LLM)")

    # 3) TTS
    mp3 = work_dir / "narration.mp3"
    d.synthesize(narration.full_text(), voice_id=reel.voice_id, api_key=ai33_api_key,
                 out_path=mp3, speed=reel.speed)
    _phase("tts(ai33)")

    # 4) Süre + hizalama + zaman çizelgesi
    duration_s = d.probe_duration_s(mp3, ffprobe_path="ffprobe")
    words = d.transcribe_words(mp3, language=channel.language,
                               quality=whisper_quality, device=whisper_device)
    timeline = build_reel_timeline(narration, words, duration_s=duration_s)
    log.info(f"  reel: ses {duration_s:.1f}s, {len(timeline.words)} kelime")
    _phase("whisper-hizalama")

    # 5) Beat başına footage (+ belirteç-uygun segmentlerde nesne konumu)
    # Öncelik-sıralı kaynak zinciri (Pexels + opsiyonel Pixabay): biri bulamazsa
    # sıradaki denenir. Anahtarları olmayan kaynaklar atlanır.
    sources = build_footage_sources(
        footage_priority or ["pexels"],
        pexels_key=pexels_api_key, pixabay_key=pixabay_api_key,
        storyblocks_session=storyblocks_session)
    footage_deps = FootageDeps(sources=sources)
    # Konu-havuzu + kanal çıpası (footage alaka gate'i için). Çıpa boşsa
    # dna.search_query_template'ten İngilizce token türetilir (ör. "whale ocean").
    from short_bot.reel_relevance import build_topic_pool, derive_footage_anchor
    anchor = (getattr(reel, "footage_anchor", "") or "").strip()
    if not anchor:
        tmpl = getattr(getattr(channel, "dna", None), "search_query_template", "") or ""
        anchor = derive_footage_anchor(tmpl)
    topic_pool = build_topic_pool([b.visual_query for b in narration.beats], anchor=anchor)
    log.info(f"  reel: footage anchor='{anchor}' | queries={[b.visual_query for b in narration.beats]}")
    log.info(f"  reel: topic_pool={sorted(topic_pool) if topic_pool else None}")
    clips_cache = work_dir / "clips"
    seg_positions: list[SubjectPos] = []
    _first_q = next((q for q in timeline.seg_queries if q), "abstract background")
    _last_q = next((q for q in reversed(timeline.seg_queries) if q), _first_q)
    _topic_q = (topic.split(",")[0].strip()[:40] or "nature")
    # Belirteç-uygun segmentleri ÖNCE hesapla → yalnız onlarda vision konum çağır
    # (hook/close ve 'off'/kapalı durumda gereksiz vision maliyeti yok).
    n_segs = len(timeline.seg_queries)
    worthy = (set(_marker_worthy_segs(n_segs, reel.arrow_frequency))
              if reel.arrows_enabled else set())
    # SIRA: önce BEAT'ler, sonra hook + close. Böylece hook'un kendi sorgusu
    # kapıdan geçemezse konudaki bir beat klibine düşer — çıpa-çöpüne değil
    # (gerçek şikâyet: "ilk girişteki görüntü alakasız" → tablo pazarı).
    order = list(range(1, max(1, n_segs - 1))) + [0] + (
        [n_segs - 1] if n_segs > 1 else [])
    # Hızlı kesim açıksa beat başına 2-3 klip çekilir (gerçek b-roll çeşitliliği);
    # kapalıysa tek klip (eski davranış).
    clips_per_beat = 3 if getattr(reel, "fast_cuts", True) else 1
    clips_by_seg: dict[int, list[Path]] = {}
    pos_by_seg: dict[int, SubjectPos] = {}
    for si in order:
        query = timeline.seg_queries[si]
        if query is None:
            # hook/close kendi sorgusunu vermediyse ilk/son beat'inkini ödünç al
            query = _first_q if si == 0 else _last_q
        _seg_t0 = _time.perf_counter()
        want = clips_per_beat if 0 < si < n_segs - 1 else 1
        got: list[Path] = []
        taken_urls: set = set()
        for _k in range(want):
            clip = _match_with_fallback(
                d, query, topic_q=_topic_q, api_key=pexels_api_key,
                cache_dir=clips_cache, verify=reel.verify_footage,
                vision_call=vision_call, footage_deps=footage_deps,
                topic_pool=topic_pool, anchor=anchor, ffmpeg_path=ffmpeg_path,
                budget={"gate": 0, "dl": 0},
                reuse_clips=[c for k in sorted(clips_by_seg)
                             for c in clips_by_seg[k]],
                exclude=set(taken_urls))
            if clip is None or clip in got:
                break        # yeni klip gelmedi → mevcutlarla yetin (fail-open)
            got.append(clip)
            taken_urls.add(str(clip))
        if not got:
            raise RuntimeError(f"reel: '{query}' için footage bulunamadı (segment {si}).")
        log.info(f"  reel[süre] footage seg{si} ('{query[:30]}'): {len(got)} klip, "
                 f"{_time.perf_counter() - _seg_t0:.1f}s")
        clips_by_seg[si] = got
        if si in worthy:
            pos_by_seg[si] = d.locate_subject(got[0], query, vision_call=vision_call,
                                              ffmpeg_path=ffmpeg_path)
        else:
            pos_by_seg[si] = SubjectPos(found=False)
    # GÖRSEL LOOP: kapanış klibi = hook klibi → video başa sarınca sahne zıplamaz.
    if getattr(reel, "visual_loop", True) and n_segs > 1 and 0 in clips_by_seg:
        clips_by_seg[n_segs - 1] = [clips_by_seg[0][0]]
    seg_positions = [pos_by_seg[i] for i in range(n_segs)]
    _phase("footage+vision")

    # ALT-KESİM PLANI: segment-içi hızlı kesim (1.5-3sn) — ölü cut_pacing canlanır.
    if getattr(reel, "fast_cuts", True):
        subcuts = plan_subcuts(timeline.seg_spans, timeline.words, profile.cut_pacing)
    else:
        subcuts = [(i, a, b) for i, (a, b) in enumerate(timeline.seg_spans)]
    clip_idx = subcut_clip_index(
        subcuts, {si: len(cs) for si, cs in clips_by_seg.items()})
    clip_paths: list[Path] = [clips_by_seg[si][k]
                              for (si, _a, _b), k in zip(subcuts, clip_idx)]
    seg_spans = [(a, b) for (_si, a, b) in subcuts]
    # Aynı klibin farklı alt-kesimi FARKLI saniyeden başlasın (klip-içi çeşitlilik)
    clip_starts: list[float] = []
    _seen_clip: dict[str, int] = {}
    for c in clip_paths:
        k = _seen_clip.get(str(c), 0)
        clip_starts.append(min(6.0, 1.5 * k))
        _seen_clip[str(c)] = k + 1
    cut_times = [a for (_si, a, _b) in subcuts[1:]]
    log.info(f"  reel: {len(subcuts)} alt-kesim ({profile.cut_pacing} tempo), "
             f"{len(set(map(str, clip_paths)))} farklı klip")

    # SAYI VURGUSU: anlatımdaki sayılar ekranda büyük pop.
    numbers = (find_numbers(timeline.words)
               if getattr(reel, "number_pop", True) else [])
    if numbers:
        log.info(f"  reel: {len(numbers)} sayı vurgusu → {[n['text'] for n in numbers]}")

    # Belirteçler: nesne konumuna göre per-segment (kapalıysa boş → arrow_frequency='off')
    markers = (build_markers(seg_positions, marker_kit=profile.marker_kit,
                             frequency=reel.arrow_frequency, seed=seed)
               if reel.arrows_enabled else [])

    # Storyblocks footage için açılmış olabilecek kalıcı sync_playwright'ı KAPAT:
    # aksi hâlde aynı thread'de reel_render'ın sync_playwright'ı "Playwright Sync
    # API inside the asyncio loop" hatası verir. close() idempotent; kullanılmadıysa
    # no-op, sonraki reel'de gerekirse yeniden başlar.
    try:
        from short_bot.storyblocks_browser import close as _sb_close
        _sb_close()
    except Exception:
        pass

    # 6) Overlay render
    frames_dir = work_dir / "frames"
    d.render_reel_overlay_frames(
        timeline, frames_dir, fps=fps, browser=browser, templates_dir=templates_dir,
        layout=profile.layout,
        highlight_color=profile.accent, arrow_color=reel.arrow_color,
        arrow_frequency=reel.arrow_frequency if reel.arrows_enabled else "off",
        cut_effect=profile.cut_effect, handle=channel.handle,
        cta_text=bits.cta_text,
        font=reel.font,
        markers=markers,
        numbers=numbers,
    )
    _phase("overlay-render")

    # 7) Montaj (cut_times alt-kesim planından geldi — segment sınırı DEĞİL)
    sfx_dir = Path("assets/sfx")
    # SFX kanal bayrağıyla açık/kapalı (per-video varyasyon setine bağlı DEĞİL) —
    # açıksa HER video havuzdan çeşitli SFX alır (kullanıcı: "aynı sfx" şikâyeti).
    pool = discover_sfx(sfx_dir) if reel.transitions_whoosh else []
    sfx_at_cut = pick_sfx_per_cut(pool, seed, len(cut_times))
    d.assemble_reel(
        clip_paths=clip_paths, seg_spans=seg_spans, frames_dir=frames_dir,
        narration_path=mp3, music_path=music_path, out_path=out_path,
        cut_times=cut_times, duration_s=duration_s, fps=fps, ffmpeg_path=ffmpeg_path,
        music_volume=reel.music_volume,
        sfx_at_cut=sfx_at_cut,
        zoom=("zoom" in profile.transitions),
        clip_starts=clip_starts,
        hook_punch=True,
    )
    _phase("montaj(ffmpeg)")
    _total = sum(_phase_t.values())
    _brk = " | ".join(f"{k} {v:.0f}s(%{100 * v / max(_total, 1):.0f})"
                      for k, v in sorted(_phase_t.items(), key=lambda kv: -kv[1]))
    log.info(f"  reel[SÜRE ÖZET] toplam {_total / 60:.1f}dk → {_brk}")
    return out_path
