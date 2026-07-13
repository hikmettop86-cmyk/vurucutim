from dataclasses import dataclass
from pathlib import Path

import pytest

from short_bot.config import ReelConfig
from short_bot.reel import ReelDeps, produce_reel_video
from short_bot.reel_models import ReelBeat, ReelNarration


def _narr():
    return ReelNarration(
        hook="Bal nasıl olur?",
        beats=[
            ReelBeat(text="Arılar nektar toplar.", visual_query="bee flower", keyword="NEKTAR"),
            ReelBeat(text="Enzimlerle işler bunu.", visual_query="bee macro", keyword="ENZİM"),
            ReelBeat(text="Peteğe biriktirir.", visual_query="honeycomb", keyword="PETEK"),
        ],
        close="İşte arının emeği.", mood="upbeat",
    )


class _Channel:
    slug = "test-reel"; language = "tr"; handle = "@test"
    colors = {"primary": "#0ea5e9", "accent": "#facc15", "bg_gradient": ["#0f172a", "#020617"]}
    reel = ReelConfig(enabled=True, voice_id="elevenlabs_v1", target_duration_s=(25, 45))


def _deps(calls, health="healthy"):
    return ReelDeps(
        write_reel_narration=lambda *a, **kw: (calls.append("narr"), _narr())[1],
        health_check=lambda **kw: (calls.append("health"), health)[1],
        synthesize=lambda text, **kw: (calls.append(("tts", text)),
                                       Path(kw["out_path"]).write_bytes(b"mp3"),
                                       Path(kw["out_path"]))[2],
        probe_duration_s=lambda p, **kw: (calls.append("probe"), 30.0)[1],
        trailing_silence_s=lambda p, **kw: 0.0,
        retime=lambda src, out, zones, **kw: (Path(out).write_bytes(b"mp3"),
                                              Path(out))[1],
        insert_pause=lambda src, out, **kw: (Path(out).write_bytes(b"mp3"),
                                             Path(out))[1],
        transcribe_words=lambda p, **kw: (calls.append("asr"), [])[1],
        match_beat_clip=lambda q, **kw: (calls.append(("match", q)),
                                         Path(kw["cache_dir"]).joinpath(f"{q[:3]}.mp4"))[1]
                        if _mk(kw["cache_dir"], q) else None,
        render_reel_overlay_frames=lambda tl, out, **kw: (calls.append("render"), 900)[1],
        assemble_reel=lambda **kw: (calls.append(("assemble", kw)), kw["out_path"])[1],
    )


def _mk(cache_dir, q):
    p = Path(cache_dir); p.mkdir(parents=True, exist_ok=True)
    (p / f"{q[:3]}.mp4").write_bytes(b"mp4"); return True


def _call(deps, tmp_path, **over):
    kwargs = dict(
        topic="bal ilginç bilgi", channel=_Channel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        deps=deps,
    )
    kwargs.update(over)
    return produce_reel_video(**kwargs)


def test_happy_path_chain_order(tmp_path):
    calls = []
    out = _call(_deps(calls), tmp_path)
    assert out == tmp_path / "out.mp4"
    names = [c if isinstance(c, str) else c[0] for c in calls]
    # preflight ÖNCE, sonra narration, tts, probe, asr, match'ler, render, assemble
    # (5 segment = hook + 3 beat + close; fast_cuts açıkken beat başına 2-3 klip
    # çekilir → match sayısı segment sayısından FAZLA)
    assert names[0] == "health" and names[1] == "narr"
    assert names.count("match") >= 5
    assert names[-2:] == ["render", "assemble"]


def test_tts_gets_full_text(tmp_path):
    calls = []
    _call(_deps(calls), tmp_path)
    tts = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "tts")
    assert tts == _narr().full_text()


def test_assemble_gets_subcut_clips(tmp_path):
    """fast_cuts (varsayılan açık): 5 segment → segment-içi alt-kesimlerle DAHA
    ÇOK parça. clip_paths ve seg_spans daima aynı boyda."""
    calls = []
    _call(_deps(calls), tmp_path)
    _, kw = next(c for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    assert len(kw["clip_paths"]) == len(kw["seg_spans"])
    assert len(kw["clip_paths"]) > 5       # alt-kesim → 5 segment'ten fazla
    assert kw["duration_s"] == 30.0


@pytest.mark.parametrize("verdict,match,n_health", [
    # GEÇİCİ ("stalled"): yeniden denenir — ai33 üç kez anlık kesinti verip koşuyu
    # düşürdü, hemen ardından SAĞLIKLI çıktı. KALICI (auth/no-key): anında dur,
    # beklemenin faydası yok.
    ("stalled", "kuyruk", 3),
    ("auth", "AI33_API_KEY", 1),
    ("no-key", "AI33_API_KEY", 1)])
def test_preflight_failure_stops_before_llm(tmp_path, verdict, match, n_health,
                                            monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a: None)   # geri çekilmeyi hızlandır
    calls = []
    with pytest.raises(RuntimeError, match=match):
        _call(_deps(calls, health=verdict), tmp_path)
    assert calls == ["health"] * n_health
    assert "narr" not in calls, "preflight geçmeden LLM kredisi harcandı"


def test_requires_reel_enabled(tmp_path):
    class NoReel(_Channel):
        reel = None
    with pytest.raises(ValueError, match="reel"):
        _call(_deps([]), tmp_path, channel=NoReel())


def test_match_with_fallback_simplifies_query(tmp_path):
    from short_bot.reel import _match_with_fallback
    tries = []

    class D:
        def match_beat_clip(self, q, **kw):
            tries.append((q, kw.get("verify")))
            return Path("clip.mp4") if q == "storm cloud" else None

    clip, gated = _match_with_fallback(
        D(), "storm cloud interior ice crystals turbulence", topic_q="lightning",
        api_key="k", cache_dir=tmp_path, verify=True, vision_call=object())
    assert clip == Path("clip.mp4") and gated is True
    assert tries[0][0] == "storm cloud interior ice crystals turbulence"  # önce tam
    assert tries[1][0] == "storm cloud"                                   # sonra ilk 2 kelime


def test_match_with_fallback_last_resort_drops_vision(tmp_path):
    from short_bot.reel import _match_with_fallback
    tries = []

    class D:
        def match_beat_clip(self, q, **kw):
            tries.append(kw.get("verify"))
            return Path("c.mp4") if kw.get("verify") is False else None  # yalnız son çare

    clip, gated = _match_with_fallback(
        D(), "very rare specific subject phrase", topic_q="nature",
        api_key="k", cache_dir=tmp_path, verify=True, vision_call=object())
    assert clip == Path("c.mp4")
    assert tries[-1] is False        # son çağrı vision'sız (boş dönmesin)
    assert gated is False            # DOĞRULANMADI → tekrar havuzuna girmemeli


@dataclass(frozen=True)
class _W:
    """Whisper kelimesi. DATACLASS olmalı: duraklama kaydırması dataclasses.replace
    kullanıyor (üretimdeki TimedWord da dataclass'tır)."""

    word: str
    start_s: float
    end_s: float

    @staticmethod
    def at(word, i):
        return _W(word=word, start_s=float(i), end_s=i + 0.9)


def _heard_deps(calls, transcripts):
    """Her TTS çağrısında sıradaki whisper çözümünü döndüren sahte bağımlılıklar."""
    d = _deps(calls)
    seq = iter(transcripts)
    return type(d)(**{**d.__dict__,
                      "transcribe_words": lambda p, **kw: (
                          calls.append("asr"),
                          [_W.at(w, i) for i, w in enumerate(next(seq).split())])[1]})


def test_tts_okumadigi_obek_icin_yeniden_seslendirir(tmp_path):
    # ai33 arada bir metnin bir öbeğini sessizce atlıyor (gerçek vaka: short 757).
    # Whisper zaten hizalama için çalıştığından bunu bedava yakalayabiliyoruz.
    full = _narr().full_text()
    eksik = " ".join(full.split()[:2] + full.split()[8:])  # ortadan 6 kelime düşür
    calls = []
    _call(_heard_deps(calls, [eksik, full]), tmp_path)
    assert sum(1 for c in calls if isinstance(c, tuple) and c[0] == "tts") == 2


def test_saglam_seslendirme_tek_seferde_gecer(tmp_path):
    full = _narr().full_text()
    calls = []
    _call(_heard_deps(calls, [full]), tmp_path)
    assert sum(1 for c in calls if isinstance(c, tuple) and c[0] == "tts") == 1


def test_israrli_tts_arizasi_uretimi_oldurmez(tmp_path):
    # Denemeler tükenirse video ÜRETİLMELİ: kusurlu video, video yokluğundan yeğdir.
    full = _narr().full_text()
    eksik = " ".join(full.split()[:2])
    calls = []
    out = _call(_heard_deps(calls, [eksik] * 3), tmp_path)
    assert out == tmp_path / "out.mp4"
    assert sum(1 for c in calls if isinstance(c, tuple) and c[0] == "tts") == 3


def _tail_deps(calls, tails):
    """Her TTS çağrısında sıradaki 'sondaki sessizlik' değerini döndürür."""
    d = _deps(calls)
    seq = iter(tails)
    full = _narr().full_text()
    return type(d)(**{**d.__dict__,
                      "trailing_silence_s": lambda p, **kw: next(seq),
                      "transcribe_words": lambda p, **kw: (
                          calls.append("asr"),
                          [_W.at(w, i) for i, w in enumerate(full.split())])[1]})


def test_sondaki_uzun_sessizlik_yeniden_seslendirtir(tmp_path):
    # ai33 öbek düşürünce dosyayı sessizlikle dolduruyor. Duyulan metin TEMİZ
    # görünse bile (whisper sessizlikte uydurabiliyor) bu işaret yakalar.
    calls = []
    _call(_tail_deps(calls, [5.0, 0.2]), tmp_path)
    assert sum(1 for c in calls if isinstance(c, tuple) and c[0] == "tts") == 2


def test_kisa_sessizlik_yeniden_seslendirtmez(tmp_path):
    calls = []
    _call(_tail_deps(calls, [0.3]), tmp_path)
    assert sum(1 for c in calls if isinstance(c, tuple) and c[0] == "tts") == 1


def _tempo_dur(base_dur: float) -> float:
    """Sahte ASR çizelgesine tempo bölgeleri uygulanınca çıkan süre.

    Süre iddiaları artık üç etkiyi ÜST ÜSTE taşıyor (ölü hava kesimi → tempo
    bölgeleri → tepe duraklaması); beklenen değeri elle yazmak yerine aynı saf
    fonksiyonlardan türetiyoruz.
    """
    from short_bot.reel_models import TimedWord, build_reel_timeline
    from short_bot.reel_tempo import plan_zones, retimed_duration_s
    n = _narr()
    asr = [TimedWord(word=w, start_s=float(i), end_s=i + 0.9, seg=-1)
           for i, w in enumerate(n.full_text().split())]
    tl = build_reel_timeline(n, asr, duration_s=base_dur)
    z = plan_zones(tl.seg_spans, peak_seg=n.peak_segment(), duration_s=base_dur)
    return retimed_duration_s(z) if z else base_dur


def test_olu_hava_video_suresinden_kesilir(tmp_path):
    # Sondaki sessizlik kesilmezse video konuşmasız akar (döngü kırılır) ve
    # altyazılar o boşluğa yayılıp sesin gerisine düşer.
    calls = []
    _call(_tail_deps(calls, [5.0, 5.0, 5.0]), tmp_path)   # hiç düzelmiyor
    from short_bot.reel_pause import REVEAL_PAUSE_S
    kw = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    # ölü hava kesilir (-4.6sn) → tempo bölgeleri → tepe duraklaması (+0.45sn)
    kirpilmis = 30.0 - (5.0 - 0.4)
    assert kw["duration_s"] == pytest.approx(_tempo_dur(kirpilmis) + REVEAL_PAUSE_S)


def test_montaja_vurgu_darbeleri_gecer(tmp_path):
    """TEPE anı montaja punch olarak gitmeli — yoksa görüntü ritmi sesle kilitlenmez."""
    calls = []
    _call(_deps(calls), tmp_path)
    kw = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    assert kw["punch_at"], "vurgu darbesi montaja hiç geçmedi"
    assert all(0 <= t <= kw["duration_s"] for t in kw["punch_at"])


def test_tepe_oncesi_duraklama_eklenir_ve_altyazi_kayar(tmp_path):
    """Tepe beat'inden hemen önce sessizlik; sonraki altyazılar TAM o kadar kayar.

    İnsan anlatıcı en büyük açıklamadan önce susar. Kritik olan senkron: saf
    sessizlik konuşmayı bozmaz, dolayısıyla kaydırma KESİNDİR.
    """
    from short_bot.reel_pause import REVEAL_PAUSE_S
    full = _narr().full_text()
    calls = []
    d = _heard_deps(calls, [full])
    pauses = []
    d = type(d)(**{**d.__dict__,
                   "insert_pause": lambda src, out, **kw: (pauses.append(kw["at_s"]),
                                                           Path(out).write_bytes(b"m"),
                                                           Path(out))[2]})
    _call(d, tmp_path)
    assert pauses, "tepe öncesi duraklama hiç eklenmedi"
    kw = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    # Video süresi duraklama kadar uzamalı (sahte probe 30.0 sn döndürüyor; araya
    # tempo bölgeleri de giriyor — bkz. _tempo_dur)
    assert kw["duration_s"] == pytest.approx(_tempo_dur(30.0) + REVEAL_PAUSE_S)


def test_duraklama_basarisiz_olursa_uretim_devam_eder(tmp_path):
    # Duraklama KOZMETİK: ffmpeg patlarsa video yine üretilmeli.
    full = _narr().full_text()
    calls = []
    d = _heard_deps(calls, [full])

    def _patla(*a, **kw):
        raise RuntimeError("ffmpeg yok")

    d = type(d)(**{**d.__dict__, "insert_pause": _patla})
    out = _call(d, tmp_path)
    assert out == tmp_path / "out.mp4"


# --- TEMPO BÖLGELERİ (orkestratör bağlantısı) ------------------------------

def test_tempo_bolgeleri_uygulanir_ve_sure_yeniden_hesaplanir(tmp_path):
    """Hook hızlansın, tepe yavaşlasın — ve montaj YENİ süreyi görsün.

    Süre yanlış geçerse ffmpeg videoyu sesten uzun/kısa keser (ölü hava ya da
    yarıda kesilen kapanış).
    """
    from short_bot.reel_pause import REVEAL_PAUSE_S
    from short_bot.reel_tempo import BODY_TEMPO, HOOK_TEMPO, PEAK_TEMPO
    calls, zones_seen = [], []
    d = _heard_deps(calls, [_narr().full_text()])
    d = type(d)(**{**d.__dict__,
                   "retime": lambda src, out, zones, **kw: (
                       zones_seen.append(zones), Path(out).write_bytes(b"m"),
                       Path(out))[2]})
    _call(d, tmp_path)
    assert zones_seen, "tempo bölgeleri hiç uygulanmadı"
    z = zones_seen[0]
    assert [x.tempo for x in z] == [HOOK_TEMPO, BODY_TEMPO, PEAK_TEMPO, BODY_TEMPO]
    kw = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    assert kw["duration_s"] == pytest.approx(_tempo_dur(30.0) + REVEAL_PAUSE_S)


def test_tempo_basarisiz_olursa_uretim_devam_eder(tmp_path):
    """Tempo KOZMETİK: ffmpeg patlarsa video tek tempoyla yine üretilmeli."""
    calls = []
    d = _heard_deps(calls, [_narr().full_text()])

    def _patla(*a, **kw):
        raise RuntimeError("atempo yok")

    d = type(d)(**{**d.__dict__, "retime": _patla})
    out = _call(d, tmp_path)
    assert out == tmp_path / "out.mp4"


def test_asr_yoksa_tempo_uygulanmaz(tmp_path):
    """Kelime zamanı olmadan bölge sınırları tahmindir — hız bir hecenin ortasında
    değişirse duyulur bir kayma bırakır. Tahmine göre ses kesmeyiz."""
    calls, cagrildi = [], []
    d = _deps(calls)   # transcribe_words → [] (kelime yok)
    d = type(d)(**{**d.__dict__,
                   "retime": lambda *a, **kw: cagrildi.append(1)})
    _call(d, tmp_path)
    assert not cagrildi, "ASR yokken tempo uygulanmamalı"


# --- KOORDİNELİ KESİNTİ (orkestratör bağlantısı) ---------------------------

def test_kesinti_anlari_dort_kanala_da_gidiyor(tmp_path):
    """Kesinti ancak DÖRT kanal aynı karede ateşlenirse 'olay' olur."""
    calls, overlay = [], []
    d = _heard_deps(calls, [_narr().full_text()])
    d = type(d)(**{**d.__dict__,
                   "render_reel_overlay_frames": lambda tl, out, **kw: (
                       overlay.append(kw), 900)[1]})
    _call(d, tmp_path)
    kw = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    kesinti = overlay[0]["interrupts"]
    assert kesinti, "kesinti anı hiç seçilmedi"
    # 1) overlay (efekt + altyazı darbesi)  2) montaj punch  3) SFX seviyesi
    assert all(t in kw["punch_at"] for t in kesinti), "kesintide görüntü punch'ı yok"
    assert kw["sfx_gains"], "kesim başına SFX seviyesi montaja geçmedi"
    from short_bot.reel_interrupt import LOUD_SFX_GAIN, QUIET_SFX_GAIN
    assert set(kw["sfx_gains"]) <= {LOUD_SFX_GAIN, QUIET_SFX_GAIN}
    assert LOUD_SFX_GAIN in kw["sfx_gains"], "hiçbir kesim yükseltilmemiş"
    assert QUIET_SFX_GAIN in kw["sfx_gains"], "hiçbir kesim kısılmamış → kontrast yok"


def test_muzik_profili_montaja_gecer(tmp_path, monkeypatch):
    """Müziğin sessiz girişi atlanmalı ve seviyesi eşitlenmeli.

    Parçaları 0:00'dan başlatınca müzik konuşmanın 37 dB altında kalıyordu
    (gerçek video, 571.mp3) — yani hiç duyulmuyordu.
    """
    from short_bot.music_profile import MUSIC_UNDER_SPEECH_DB, MusicProfile
    monkeypatch.setattr("short_bot.reel.profile_music",
                        lambda p, **kw: MusicProfile(12.5, -24.0))
    monkeypatch.setattr("short_bot.reel.speech_lufs", lambda p, **kw: -16.0)
    calls = []
    _call(_deps(calls), tmp_path)
    kw = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    assert kw["music_start_s"] == 12.5          # sessiz giriş atlandı
    # müzik konuşmanın (-16) sabit mesafe altına oturdu — parçadan bağımsız
    assert -24.0 + kw["music_gain_db"] == pytest.approx(-16.0 + MUSIC_UNDER_SPEECH_DB,
                                                        abs=4.1)


def test_muzik_profili_cikmazsa_uretim_devam_eder(tmp_path, monkeypatch):
    # Müzik KOZMETİK: profil çıkarılamazsa ham parçayla devam edilmeli.
    def _patla(p, **kw):
        raise RuntimeError("ffmpeg yok")

    monkeypatch.setattr("short_bot.reel.profile_music", _patla)
    calls = []
    out = _call(_deps(calls), tmp_path)
    assert out == tmp_path / "out.mp4"
    kw = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    assert kw["music_start_s"] == 0.0 and kw["music_gain_db"] == 0.0
