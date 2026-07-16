"""Görüntü-öncelikli mod entegrasyonu (produce_reel_video iki dallanma)."""
from short_bot.reel import ReelDeps


def test_reeldeps_footage_driven_alanlari_var():
    d = ReelDeps()
    assert callable(d.write_footage_driven_narration)
    assert callable(d.footage_search_queries)


from pathlib import Path

from short_bot.reel import _footage_driven_clip_count, _footage_driven_seg_clip


def test_klip_sayisi_sureden_turer():
    assert _footage_driven_clip_count((45, 60)) == 5   # ort 52.5 / 11 ≈ 5
    assert _footage_driven_clip_count((25, 45)) == 3   # ort 35 / 11 ≈ 3
    assert _footage_driven_clip_count((10, 12)) == 3   # taban 3
    assert _footage_driven_clip_count((160, 180)) == 6 # tavan 6


def test_footage_driven_duration_klipten_turer():
    # LOOP TEŞHİSİ (short 874): süre klip sayısından türer → gerilme/loop yok.
    from short_bot.reel import _footage_driven_duration, FD_MIN_DURATION_S
    lo, hi = _footage_driven_duration(3, (30, 45))
    assert 15 <= hi <= 20 and lo < hi            # 3 klip → ~16sn sıkı video
    _, hi6 = _footage_driven_duration(6, (30, 45))
    assert hi6 == 33                             # 6 klip → 33sn
    _, hi_cap = _footage_driven_duration(20, (30, 45))
    assert hi_cap == 45                          # kanal üst süresini aşmaz
    _, hi_min = _footage_driven_duration(1, (30, 45))
    assert hi_min == FD_MIN_DURATION_S           # min taban korunur
    for n in range(1, 12):                       # her zaman geçerli pencere
        a, b = _footage_driven_duration(n, (30, 45))
        assert 10 <= a < b <= 45


def test_beat_klip_eslemesi():
    # 3 klip → 5 segment (hook + 3 beat + close). hook=clips[0], close=clips[-1].
    clips = [Path("c0.mp4"), Path("c1.mp4"), Path("c2.mp4")]
    n_segs = 5
    got = [_footage_driven_seg_clip(clips, si, n_segs) for si in range(n_segs)]
    assert got == [Path("c0.mp4"),   # seg 0 hook  → clips[0]
                   Path("c0.mp4"),   # seg 1 beat0 → clips[0]
                   Path("c1.mp4"),   # seg 2 beat1 → clips[1]
                   Path("c2.mp4"),   # seg 3 beat2 → clips[2]
                   Path("c2.mp4")]   # seg 4 close → clips[-1]


def test_beat_klip_kelepce_beat_fazlaysa():
    # LLM 4 beat yazdı ama 2 klip var (n_segs=6) → fazla beat son klibe kelepçelenir.
    clips = [Path("c0.mp4"), Path("c1.mp4")]
    n_segs = 6
    got = [_footage_driven_seg_clip(clips, si, n_segs) for si in range(n_segs)]
    assert got == [Path("c0.mp4"), Path("c0.mp4"), Path("c1.mp4"),
                   Path("c1.mp4"), Path("c1.mp4"), Path("c1.mp4")]


import short_bot.reel as REEL
from short_bot.reel import ReelDeps, _prepare_footage_driven


def _fd_channel():
    from types import SimpleNamespace
    reel = SimpleNamespace(target_duration_s=(45, 60), persona="vahsi_mizah",
                           verify_footage=True, footage_anchor="chimpanzee jungle")
    return SimpleNamespace(reel=reel, language="tr", dna=None)


def test_prepare_indirir_ve_tarif_eder(tmp_path, monkeypatch):
    # match_beat_clip her çağrıda FARKLI klip döndürür (exclude ile ayrık).
    sayac = {"n": 0}

    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for i in range(10):
            p = tmp_path / f"clip{i}.mp4"
            if str(p) not in excl:
                p.write_bytes(b"mp4")
                sayac["n"] += 1
                return p
        return None

    d = ReelDeps(
        footage_search_queries=lambda topic, **k: ["chimpanzee", "chimpanzee fighting"],
        match_beat_clip=fake_match, discover_subject=lambda **k: None)
    # vision tarifini deterministik yap
    monkeypatch.setattr(REEL, "_describe_clip",
                        lambda c, **k: f"a chimpanzee ({c.name})")

    clips, descs, queries, _topic = _prepare_footage_driven(
        topic="şempanze", channel=_fd_channel(), reel=_fd_channel().reel, d=d,
        work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
        footage_priority=["pexels"],
        vision_call=object(), ffmpeg_path="ffmpeg",
        llm_claude_path="claude", llm_model="default",
        llm_backend="claude_cli", llm_api_key=None)

    assert len(clips) == 5                       # (45,60) → 5 klip
    assert len(descs) == 5 and len(queries) == 5 # üçü index-hizalı
    assert len(set(map(str, clips))) == 5        # hepsi AYRIK (exclude çalıştı)
    assert all("chimpanzee" in dsc for dsc in descs)


def test_prepare_hic_footage_yoksa_hata(tmp_path, monkeypatch):
    d = ReelDeps(
        footage_search_queries=lambda topic, **k: ["nonexistent"],
        match_beat_clip=lambda q, **kw: None, discover_subject=lambda **k: None)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: "")
    import pytest
    with pytest.raises(RuntimeError, match="footage bulunamadı"):
        _prepare_footage_driven(
            topic="x", channel=_fd_channel(), reel=_fd_channel().reel, d=d,
            work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
            footage_priority=["pexels"],
            vision_call=object(), ffmpeg_path="ffmpeg", llm_claude_path="claude",
            llm_model="default", llm_backend="claude_cli", llm_api_key=None)


from short_bot.reel import produce_reel_video
from short_bot.reel_models import ReelBeat, ReelNarration
from short_bot.config import ReelConfig


def _fd_narr():
    return ReelNarration(
        hook="Hop bakalım!", cover_title="ŞEMPANZE",
        beats=[ReelBeat(text="Şempanze sağ kroşeyi patlatıyor.",
                        visual_query="chimpanzee", keyword="KROŞE"),
               ReelBeat(text="Rakip köşeye kaçıyor.",
                        visual_query="chimpanzee fighting", keyword="KAÇIŞ"),
               ReelBeat(text="Zafer şempanzenin.",
                        visual_query="chimpanzee running", keyword="ZAFER")],
        close="Hop işte böyle biter.", mood="upbeat")


class _FDChannel:
    slug = "mahalle"; language = "tr"; handle = "@mahalle"; dna = None
    colors = {"primary": "#0ea5e9", "accent": "#facc15",
              "bg_gradient": ["#0f172a", "#020617"]}
    reel = ReelConfig(enabled=True, voice_id="v1", target_duration_s=(45, 60),
                      persona="vahsi_mizah", footage_driven=True)


def _fd_deps(calls, tmp_path):
    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for i in range(20):
            p = Path(kw["cache_dir"]); p.mkdir(parents=True, exist_ok=True)
            f = p / f"c{i}.mp4"
            if str(f) not in excl:
                f.write_bytes(b"mp4")
                return f
        return None

    return ReelDeps(
        write_reel_narration=lambda *a, **kw: calls.append("SENARYO-ONCE"),  # ÇAĞRILMAMALI
        write_footage_driven_narration=lambda *a, **kw: (
            calls.append("gorunti-once-narr"), _fd_narr())[1],
        # curiosity varsayılanı AÇIK: fixture LLM'e gitmez, aynı sahte narr +
        # kimlik permütasyonu döner (eski testlerin davranış sözleşmesi korunur).
        write_curious_narration=lambda *a, **kw: (
            calls.append("gorunti-once-narr"), (_fd_narr(), [0, 1, 2]))[1],
        footage_search_queries=lambda topic, **k: (
            calls.append("sorgu"), ["chimpanzee", "chimpanzee fighting"])[1],
        health_check=lambda **kw: "healthy",
        synthesize=lambda text, **kw: (Path(kw["out_path"]).write_bytes(b"mp3"),
                                       Path(kw["out_path"]))[1],
        probe_duration_s=lambda p, **kw: 30.0,
        trailing_silence_s=lambda p, **kw: 0.0,
        transcribe_words=lambda p, **kw: [],
        retime=lambda src, out, zones, **kw: (Path(out).write_bytes(b"m"), Path(out))[1],
        insert_pause=lambda src, out, **kw: (Path(out).write_bytes(b"m"), Path(out))[1],
        match_beat_clip=fake_match, discover_subject=lambda **k: None,
        render_reel_overlay_frames=lambda tl, out, **kw: 900,
        assemble_reel=lambda **kw: (calls.append(("assemble", kw)), kw["out_path"])[1])


def test_footage_driven_gorunti_once_senaryo_yazar(tmp_path, monkeypatch):
    import short_bot.reel as R
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")
    calls = []
    out = produce_reel_video(
        topic="şempanze kavgası", channel=_FDChannel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=_fd_deps(calls, tmp_path))
    assert out == tmp_path / "out.mp4"
    # Görüntü-önce senaryo çağrıldı, senaryo-önce ÇAĞRILMADI
    assert "gorunti-once-narr" in calls
    assert "SENARYO-ONCE" not in calls
    assert "sorgu" in calls
    # Montaja giden klipler önden indirilenlerden (cN.mp4)
    _, kw = next(c for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    assert kw["clip_paths"], "montaja klip gitmedi"
    assert all(Path(p).name.startswith("c") for p in kw["clip_paths"])
    assert len(kw["clip_paths"]) == len(kw["seg_spans"])


# --- TARİF-SONRASI ELEME (short 845/846 dersleri) --------------------------
# 846: 'bağlama uyan' bataklık b-roll'ü + telefon (scroll) klibi + mantis kabul
# edildi → senaryo çöpü anlatıp konudan koptu, statik mantis 8sn donuk kuyruk yaptı.
# 845: kapı 'örümcek ≈ atlayan örümcek' saydı → 5 klipten 3'ü ağ ören örümcek.
import short_bot.footage_matcher as FM
from short_bot.footage_matcher import find_offsubject_clips


def test_find_offsubject_kurallar_promptta_ve_indeks_doner():
    yakalanan = {}

    def fake_invoke(prompt, schema):
        from types import SimpleNamespace
        yakalanan["p"] = prompt
        return SimpleNamespace(outlier_indices=[1, 3])

    out = find_offsubject_clips(
        ["an archerfish in murky water", "a person holding a smartphone",
         "a school of archerfish", "a praying mantis on a flower"],
        ["archerfish swimming", "rippling water", "archerfish school", "mantis"],
        "okçu balığı (EN: archerfish)", invoke=fake_invoke)
    assert out == [1, 3]
    p = yakalanan["p"]
    assert "EKRAN" in p                      # ekran-içi-ekran kuralı (846 telefon)
    assert "TÜR" in p                        # tür-düzeyi kuralı (845 örümcek)
    assert "DERLEME" in p or "derleme" in p  # baş/son kare uyuşmazlığı (scroll klip)
    assert "BAŞ" in p and "SON" in p         # iki kare de yargıca gidiyor
    assert "a person holding a smartphone" in p


def test_find_offsubject_cokerse_fail_open():
    def patlar(prompt, schema):
        raise RuntimeError("LLM down")
    assert find_offsubject_clips(["a", "b"], ["", ""], "x", invoke=patlar) == []


def _fd_prep_kwargs(tmp_path):
    ch = _fd_channel()
    return dict(topic="okçu balığı", channel=ch, reel=ch.reel,
                work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
                footage_priority=["pexels"],
                vision_call=object(), ffmpeg_path="ffmpeg",
                llm_claude_path="claude", llm_model="default",
                llm_backend="claude_cli", llm_api_key=None)


def test_prepare_konu_disi_klip_yerine_konulu_gelir(tmp_path, monkeypatch):
    # Çöp tarifli klip (telefon) senaryoya girmeden elenir; yerine DÜZ özne
    # sorgusuyla (queries[0]) klip gelir ve üç liste hizalı kalır.
    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for i in range(20):
            f = tmp_path / f"{q.replace(' ', '_')}_{i}.mp4"
            if str(f) not in excl:
                f.write_bytes(b"mp4")
                return f
        return None

    def fake_desc(c, **k):
        n = Path(c).name
        return ("a person holding a smartphone" if "spitting" in n
                else f"an archerfish ({n})")

    d = ReelDeps(
        footage_search_queries=lambda t, **k: ["archerfish", "archerfish spitting"],
        match_beat_clip=fake_match, discover_subject=lambda **k: None)
    monkeypatch.setattr(REEL, "_describe_clip", fake_desc)
    monkeypatch.setattr(FM, "find_offsubject_clips",
                        lambda descs, tails, subject, **k: [
                            i for i, x in enumerate(descs) if "smartphone" in x])

    clips, descs, queries, _topic = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
    assert len(clips) == len(descs) == len(queries) == 5
    assert all("archerfish" in x for x in descs)          # çöp tarif kalmadı
    assert all("smartphone" not in x for x in descs)
    # yerine konan klipler düz özne sorgusuyla etiketli (beat=klip sorgusu doğru)
    yeniler = [q for q, c in zip(queries, clips) if "spitting" not in Path(c).name]
    assert all(q == "archerfish" for q in yeniler)
    assert len(set(map(str, clips))) == 5                 # tekrar sızmadı


def test_prepare_yerine_konulamayan_konu_disi_klip_dusurulur(tmp_path, monkeypatch):
    # Havuz tükendi (yenisi yok) → çöp klip DÜŞER; kalanlar hizalı ve konulu.
    havuz = [tmp_path / f"p{i}.mp4" for i in range(5)]
    for p in havuz:
        p.write_bytes(b"mp4")

    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for p in havuz:
            if str(p) not in excl:
                return p
        return None                                   # havuz bitti → yenisi yok

    def fake_desc(c, **k):
        n = Path(c).name
        return "a marsh landscape" if n in ("p1.mp4", "p3.mp4") else f"an archerfish ({n})"

    d = ReelDeps(
        footage_search_queries=lambda t, **k: ["archerfish", "archerfish spitting"],
        match_beat_clip=fake_match, discover_subject=lambda **k: None)
    monkeypatch.setattr(REEL, "_describe_clip", fake_desc)
    monkeypatch.setattr(FM, "find_offsubject_clips",
                        lambda descs, tails, subject, **k: [
                            i for i, x in enumerate(descs) if "marsh" in x])

    clips, descs, queries, _topic = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
    assert all("marsh" not in x for x in descs)           # çöp düştü
    assert len(clips) == len(descs) == len(queries)       # hizalı
    assert len(clips) >= 3                                # min 3 korunur (pad)


def test_prepare_bos_tarif_yargicsiz_da_elenir(tmp_path, monkeypatch):
    # Boş tarif = grounding kaybı (846: beat 'bataklık' uydurdu) → yargıç hiç
    # işaretlemese bile boş tarifli klip elenir/yenilenir.
    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for i in range(20):
            f = tmp_path / f"{q.replace(' ', '_')}_{i}.mp4"
            if str(f) not in excl:
                f.write_bytes(b"mp4")
                return f
        return None

    def fake_desc(c, **k):
        n = Path(c).name
        return "" if n == "archerfish_spitting_0.mp4" else f"an archerfish ({n})"

    d = ReelDeps(
        footage_search_queries=lambda t, **k: ["archerfish", "archerfish spitting"],
        match_beat_clip=fake_match, discover_subject=lambda **k: None)
    monkeypatch.setattr(REEL, "_describe_clip", fake_desc)
    monkeypatch.setattr(FM, "find_offsubject_clips", lambda *a, **k: [])

    clips, descs, queries, _topic = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
    assert all((x or "").strip() for x in descs)          # boş tarif kalmadı


def test_prepare_statik_klip_atlanir(tmp_path, monkeypatch):
    # 846: statik mantis klibi kapanışta 8.1sn DONUK kare yaptı — görüntü-önce
    # prep'te hareket kontrolü yoktu (eski akışın reddi order-döngüsünde kalıyor).
    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for name in ["static0.mp4", "mov1.mp4", "mov2.mp4", "mov3.mp4",
                     "mov4.mp4", "mov5.mp4"]:
            f = tmp_path / name
            if str(f) not in excl:
                f.write_bytes(b"mp4")
                return f
        return None

    d = ReelDeps(
        footage_search_queries=lambda t, **k: ["archerfish", "archerfish spitting"],
        match_beat_clip=fake_match, discover_subject=lambda **k: None)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: f"an archerfish ({Path(c).name})")
    monkeypatch.setattr(REEL, "measure_motion",
                        lambda c, *a, **k: 0.001 if "static" in Path(c).name else 1.0)
    monkeypatch.setattr(FM, "find_offsubject_clips", lambda *a, **k: [])

    clips, descs, queries, _topic = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
    assert all("static" not in Path(c).name for c in clips)   # statik seçilmedi
    assert len(clips) == 5                                     # hareketlilerle doldu


def test_fd_motion_min_kuyrugu_durgun_klibi_yakalar(tmp_path):
    # measure_motion yalnız İLK ~4sn'yi örnekler; görüntü-önce bir klip 2 segmenti
    # (son beat + close ~13sn) taşır ve offsetler klibin SONUNA yayılır. Başı
    # hareketli sonu durgun klip kapıdan geçip kapanışta 8sn DONUK kare bıraktı
    # (okçu balığı repro'su, freeze 44.4-52.5). Baş+son pencerenin MİNİMUMU esas.
    import subprocess
    from short_bot.reel import _fd_motion_min
    from short_bot.reel_grade import MOTION_MIN
    klip = tmp_path / "yari_statik.mp4"
    # 4sn hareketli (testsrc) + 4sn durgun (tek renk) birleştirilmiş klip
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=4:size=160x120:rate=8",
         "-f", "lavfi", "-i", "color=c=gray:duration=4:size=160x120:rate=8",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
         str(klip)], check=True, capture_output=True, timeout=60)
    assert _fd_motion_min(klip, "ffmpeg") < MOTION_MIN     # durgun kuyruk yakalanır


def test_fd_motion_min_okunamazsa_fail_open(tmp_path):
    # Bozuk dosyada eleme YAPILMAZ (measure_motion fail-open sözleşmesiyle aynı).
    from short_bot.reel import _fd_motion_min
    from short_bot.reel_grade import MOTION_MIN
    bozuk = tmp_path / "bozuk.mp4"
    bozuk.write_bytes(b"mp4")
    assert _fd_motion_min(bozuk, "ffmpeg") >= MOTION_MIN


def test_prepare_hepsi_statikse_URETIM_DUSER(tmp_path, monkeypatch):
    # 858 dersi: tek (üstelik statik) klibin loop'u en kötü video. Hepsi statikse
    # yedek kabul edip sevk etmek yerine üretim NET hatayla düşer.
    havuz = [tmp_path / f"static{i}.mp4" for i in range(2)]
    for p in havuz:
        p.write_bytes(b"mp4")

    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for p in havuz:
            if str(p) not in excl:
                return p
        return None

    d = ReelDeps(
        footage_search_queries=lambda t, **k: ["archerfish"],
        match_beat_clip=fake_match, discover_subject=lambda **k: None)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: "an archerfish")
    monkeypatch.setattr(REEL, "measure_motion", lambda c, *a, **k: 0.001)
    monkeypatch.setattr(FM, "find_offsubject_clips", lambda *a, **k: [])

    import pytest
    with pytest.raises(RuntimeError, match="ayrık"):
        _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))


def test_prepare_az_ayrik_klip_URETIMI_DUSURUR(tmp_path, monkeypatch):
    # GERÇEK HATA (short 858, kullanıcı yakaladı: 'aynı görüntü sürekli looplanmış'):
    # havuz 1 ayrık klibe düşünce eski kural klibi 3'e kopyalayıp LOOPLU videoyu
    # sevk etti. Looplu video, video yokluğundan YEĞ DEĞİL — 3'ten az AYRIK klip
    # kaldıysa üretim DÜŞER (net hatayla; konu/slot başka koşuda değerlendirilir).
    havuz = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for p in havuz:
        p.write_bytes(b"mp4")

    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for p in havuz:
            if str(p) not in excl:
                return p
        return None                       # havuz 2'de tükendi

    d = ReelDeps(
        footage_search_queries=lambda topic, **k: ["chimpanzee", "chimpanzee fighting"],
        match_beat_clip=fake_match, discover_subject=lambda **k: None)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: f"desc {c.name}")

    import pytest
    with pytest.raises(RuntimeError, match="ayrık"):
        _prepare_footage_driven(
            topic="şempanze", channel=_fd_channel(), reel=_fd_channel().reel, d=d,
            work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
            footage_priority=["pexels"],
            vision_call=object(), ffmpeg_path="ffmpeg", llm_claude_path="claude",
            llm_model="default", llm_backend="claude_cli", llm_api_key=None)


# --- KEŞİF MODU: konu stoktan doğar (kullanıcı önerisi, 2026-07-16) -----------

def test_prepare_kesif_basarili_konuyu_stoktan_turetir(tmp_path, monkeypatch):
    from short_bot.footage_discovery import DiscoveredSubject
    from short_bot.footage_sources import FootageCandidate

    cands = [FootageCandidate(url=f"http://x/{i}.mp4", duration_s=15,
                              image=f"http://x/{i}.jpg", source="pexels",
                              ident=str(i)) for i in range(5)]
    subj = DiscoveredSubject(subject_en="mantis shrimp",
                             topic_tr="Bizimki tek yumrukla akvaryum camı çatlatıyor",
                             clip_indices=[0, 1, 2, 3])

    def fake_download(src, cand, cache_dir):
        f = Path(cache_dir) / f"disc_{cand.ident}.mp4"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"mp4")
        return f

    d = ReelDeps(
        footage_search_queries=lambda t, **k: (_ for _ in ()).throw(
            AssertionError("keşif başarılıyken eski konu-yolu ÇAĞRILMAMALI")),
        match_beat_clip=lambda q, **kw: None,
        discover_subject=lambda **k: (subj, cands),
        download_candidate=fake_download)
    monkeypatch.setattr(REEL, "_describe_clip",
                        lambda c, **k: f"a mantis shrimp ({Path(c).name})")
    monkeypatch.setattr(FM, "find_offsubject_clips", lambda *a, **k: [])

    clips, descs, queries, topic = _prepare_footage_driven(
        d=d, **_fd_prep_kwargs(tmp_path))
    assert topic == "Bizimki tek yumrukla akvaryum camı çatlatıyor"   # konu stoktan
    assert len(clips) >= 3
    assert all(q == "mantis shrimp" for q in queries)                 # sorgu = özne
    assert all("disc_" in Path(c).name for c in clips)                # keşif klipleri


def test_prepare_kesif_bos_donerse_eski_yola_duser(tmp_path, monkeypatch):
    cagri = {"eski_yol": False}

    def fake_queries(t, **k):
        cagri["eski_yol"] = True
        return ["archerfish"]

    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for i in range(10):
            f = tmp_path / f"c{i}.mp4"
            if str(f) not in excl:
                f.write_bytes(b"mp4")
                return f
        return None

    d = ReelDeps(footage_search_queries=fake_queries, match_beat_clip=fake_match,
                 discover_subject=lambda **k: None)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: "an archerfish")
    monkeypatch.setattr(FM, "find_offsubject_clips", lambda *a, **k: [])

    clips, descs, queries, topic = _prepare_footage_driven(
        d=d, **_fd_prep_kwargs(tmp_path))
    assert cagri["eski_yol"] is True                  # fail-open: konu-yolu devrede
    assert topic == "okçu balığı"                     # konu değişmedi
    assert len(clips) >= 3


def test_prepare_eleme_dusurunce_kesif_yedegi_devreye_girer(tmp_path, monkeypatch):
    # Panel koşusu dersi: eleme klipleri düşürünce keşfin İNDİRİLMEMİŞ adayları
    # dururken üretim düşüyordu ('yalnız 2 ayrık klip'). Yedek havuz önce denenir.
    from short_bot.footage_discovery import DiscoveredSubject
    from short_bot.footage_sources import FootageCandidate

    cands = [FootageCandidate(url=f"http://x/{i}.mp4", duration_s=15,
                              image=f"http://x/{i}.jpg", source="pexels",
                              ident=str(i)) for i in range(8)]
    subj = DiscoveredSubject(subject_en="pufferfish",
                             topic_tr="Bizimki akvaryumun raconunu kesiyor",
                             clip_indices=[0, 1, 2, 3, 4, 5, 6, 7])

    def fake_download(src, cand, cache_dir):
        f = Path(cache_dir) / f"disc_{cand.ident}.mp4"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"mp4")
        return f

    def fake_desc(c, **k):
        n = Path(c).name
        # ilk indirilen 5'ten biri (disc_2) ÇÖP tarifli; yedekler temiz
        return "a person holding a phone" if n == "disc_2.mp4" else f"a pufferfish ({n})"

    d = ReelDeps(
        footage_search_queries=lambda t, **k: (_ for _ in ()).throw(
            AssertionError("keşif varken eski yol çağrılmamalı")),
        match_beat_clip=lambda q, **kw: (_ for _ in ()).throw(
            AssertionError("yedek varken düz-sorgu aramasına gidilmemeli")),
        discover_subject=lambda **k: (subj, cands),
        download_candidate=fake_download)
    monkeypatch.setattr(REEL, "_describe_clip", fake_desc)
    monkeypatch.setattr(FM, "find_offsubject_clips",
                        lambda descs, tails, subject, **k: [
                            i for i, x in enumerate(descs) if "phone" in x])

    clips, descs, queries, topic = _prepare_footage_driven(
        d=d, **_fd_prep_kwargs(tmp_path))
    assert all("phone" not in x for x in descs)          # çöp gitti
    assert len(clips) == 5                               # yedekten tamamlandı
    assert len(set(map(str, clips))) == 5                # hepsi ayrık
    assert any("disc_5" in Path(c).name or "disc_6" in Path(c).name
               or "disc_7" in Path(c).name for c in clips)   # yedek aday kullanıldı


# --- MERAK MİMARİSİ kablolaması (spec 2026-07-16) -----------------------------
from dataclasses import replace


def test_curiosity_acikken_yarisma_hatti_cagrilir(tmp_path, monkeypatch):
    import short_bot.reel as R
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")
    calls = []
    deps = _fd_deps(calls, tmp_path)

    def fake_curious(topic, descs, queries, **kw):
        calls.append("merak-hatti")
        return _fd_narr(), [0, 1, 2]

    deps = replace(deps, write_curious_narration=fake_curious)
    out = produce_reel_video(
        topic="şempanze kavgası", channel=_FDChannel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    assert out == tmp_path / "out.mp4"
    assert "merak-hatti" in calls
    assert "gorunti-once-narr" not in calls     # tek-çağrı yol ÇAĞRILMADI


def test_curiosity_kapaliyken_eski_tek_cagri(tmp_path, monkeypatch):
    import short_bot.reel as R
    from short_bot.config import ReelConfig
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")

    class _Kapali(_FDChannel):
        reel = ReelConfig(enabled=True, voice_id="v1", target_duration_s=(45, 60),
                          persona="vahsi_mizah", footage_driven=True,
                          curiosity_pipeline=False)

    calls = []
    deps = replace(_fd_deps(calls, tmp_path),
                   write_curious_narration=lambda *a, **k: (_ for _ in ()).throw(
                       AssertionError("kapalıyken çağrılmamalı")))
    produce_reel_video(
        topic="şempanze kavgası", channel=_Kapali(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    assert "gorunti-once-narr" in calls


def test_curiosity_permutasyonu_klipleri_yeniden_dizer(tmp_path, monkeypatch):
    # perm=[2,0,1] → montaja giden klip sırası da o dramaturjiyle dizilmeli.
    # DİKKAT: perm uzunluğu == klip sayısı olmalı (guard aksi hâlde atlar) →
    # 3 kliplik kanal ((25,45) → 3 klip hedefi) kullanılır.
    import short_bot.reel as R
    from short_bot.config import ReelConfig
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")

    class _UcKlip(_FDChannel):
        reel = ReelConfig(enabled=True, voice_id="v1", target_duration_s=(25, 45),
                          persona="vahsi_mizah", footage_driven=True)

    calls = []
    deps = _fd_deps(calls, tmp_path)

    def fake_curious(topic, descs, queries, **kw):
        return _fd_narr(), [2, 0, 1]

    rec = {}
    deps = replace(deps, write_curious_narration=fake_curious,
                   assemble_reel=lambda **kw: (rec.update(kw), kw["out_path"])[1])
    produce_reel_video(
        topic="şempanze", channel=_UcKlip(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    # hook klibi = permütasyon sonrası ilk klip = orijinal c2.mp4
    assert Path(rec["clip_paths"][0]).name == "c2.mp4"


def test_soru_cipi_render_cagrisina_gecer(tmp_path, monkeypatch):
    import short_bot.reel as R
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")
    calls = []
    deps = _fd_deps(calls, tmp_path)

    def fake_curious(topic, descs, queries, **kw):
        n = _fd_narr().model_copy(update={"open_question": "Kim kazanacak dersin?",
                                          "reveal_beat": 2, "peak_beat": 1})
        return n, [0, 1, 2]

    rec = {}
    deps = replace(deps, write_curious_narration=fake_curious,
                   render_reel_overlay_frames=lambda tl, out, **kw: (
                       rec.update(kw), 900)[1])
    produce_reel_video(
        topic="şempanze", channel=_FDChannel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    assert rec["question_text"] == "Kim kazanacak dersin?"
    assert rec["reveal_at_s"] and rec["reveal_at_s"] > 0


def test_reveal_beat_sifir_sizinti_korkulugu(tmp_path, monkeypatch):
    # reveal_beat=0 → payoff hook klibiyle aynı → sızıntı. En az 1'e itilir.
    import short_bot.reel as R
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")
    calls = []

    def fake_curious(topic, descs, queries, **kw):
        n = _fd_narr().model_copy(update={"open_question": "Soru bu mu?",
                                          "reveal_beat": 0, "peak_beat": 0})
        return n, [0, 1, 2]

    rec = {}
    deps = replace(_fd_deps(calls, tmp_path), write_curious_narration=fake_curious,
                   render_reel_overlay_frames=lambda tl, out, **kw: (
                       rec.update(kw), 900)[1])
    produce_reel_video(
        topic="şempanze", channel=_FDChannel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    assert rec["reveal_at_s"] > 0     # segment 2 başlangıcı (hook'tan sonra)


def test_soru_yoksa_cip_parametreleri_bos(tmp_path, monkeypatch):
    import short_bot.reel as R
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")
    calls = []
    rec = {}
    deps = replace(_fd_deps(calls, tmp_path),
                   render_reel_overlay_frames=lambda tl, out, **kw: (
                       rec.update(kw), 900)[1])
    produce_reel_video(
        topic="şempanze", channel=_FDChannel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    assert rec["question_text"] == ""
    assert rec["reveal_at_s"] is None


# --- DURGUN KLİP KAPISI v2 (keçi videosu dersi: 24-56s hareket ~0.003) --------

def _sentetik(tmp_path, adi, hareketli_s, durgun_s, *, once_hareketli=True):
    """testsrc (hareketli) + tek renk (durgun) birleştirilmiş sentetik klip."""
    import subprocess
    p = tmp_path / adi
    a = f"testsrc=duration={hareketli_s}:size=160x120:rate=8"
    b = f"color=c=gray:duration={durgun_s}:size=160x120:rate=8"
    ilk, son = (a, b) if once_hareketli else (b, a)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", ilk,
         "-f", "lavfi", "-i", son,
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
         str(p)], check=True, capture_output=True, timeout=120)
    return p


def test_fd_static_fraction_cogu_durgun_klibi_olcer(tmp_path):
    # Keçi videosu dersi: klip başta hareketli, ortası/sonu 30sn bakışma →
    # baş/son penceresi kapıdan geçirdi, izleyici 'donuyor' dedi. Tüm klip
    # taranır; durgun pencere ORANI ölçülür.
    from short_bot.reel import _fd_static_fraction
    cogu_durgun = _sentetik(tmp_path, "cd.mp4", 3, 12)     # 12/15 durgun
    assert _fd_static_fraction(cogu_durgun, "ffmpeg") > 0.5
    cogu_hareketli = _sentetik(tmp_path, "ch.mp4", 12, 3)  # 3/15 durgun
    assert _fd_static_fraction(cogu_hareketli, "ffmpeg") < 0.5


def test_fd_static_fraction_okunamazsa_fail_open(tmp_path):
    from short_bot.reel import _fd_static_fraction
    bozuk = tmp_path / "bozuk.mp4"
    bozuk.write_bytes(b"mp4")
    assert _fd_static_fraction(bozuk, "ffmpeg") == 0.0     # eleme YAPMA


def test_fd_clip_ok_birlesik_kapi(tmp_path, monkeypatch):
    import short_bot.reel as R
    from short_bot.reel import _fd_clip_ok
    # hareket iyi + durgunluk az → geçer
    monkeypatch.setattr(R, "_fd_motion_min", lambda c, f: 0.05)
    monkeypatch.setattr(R, "_fd_static_fraction", lambda c, f: 0.2)
    assert _fd_clip_ok("x.mp4", "ffmpeg") is True
    # çoğunluğu durgun → elenir (baş/son hareketli olsa bile)
    monkeypatch.setattr(R, "_fd_static_fraction", lambda c, f: 0.7)
    assert _fd_clip_ok("x.mp4", "ffmpeg") is False
    # kuyruk donuk → elenir
    monkeypatch.setattr(R, "_fd_static_fraction", lambda c, f: 0.1)
    monkeypatch.setattr(R, "_fd_motion_min", lambda c, f: 0.001)
    assert _fd_clip_ok("x.mp4", "ffmpeg") is False


def test_fd_motion_min_kuyruk_sondasi_reencode(tmp_path):
    # GERÇEK HATA (keçi videosu, son 8sn 0.0000 donuk): kuyruk sondası -c copy
    # ile çıkarılıyordu; stok kliplerde keyframe sınırı boş dosya verip fail-open
    # 1.0 döndürüyordu. Sonda artık yeniden-kodlar — sentetik donuk kuyruk her
    # kapsayıcıda yakalanmalı.
    from short_bot.reel import _fd_motion_min
    from short_bot.reel_grade import MOTION_MIN
    klip = _sentetik(tmp_path, "dk.mp4", 4, 4)             # son 4sn DONUK
    assert _fd_motion_min(klip, "ffmpeg") < MOTION_MIN


# --- DURGUN OFSET DÜZELTMESİ (karınca videosu: kapanışın 5.6sn'si klip İÇİNDEKİ
# donmuş bekleme bölümüne denk geldi — kapı klibi geçirdi, ofset yanlış yere düştü)

def test_fd_motion_profile_pencere_listesi(tmp_path):
    from short_bot.reel import _fd_motion_profile
    klip = _sentetik(tmp_path, "mp.mp4", 6, 6)      # 6sn hareketli + 6sn donuk
    prof = _fd_motion_profile(klip, "ffmpeg")
    assert len(prof) >= 4                            # 2sn pencereler
    assert max(prof[:3]) > 0.01                      # baş hareketli
    assert min(prof[-2:]) < 0.005                    # kuyruk donuk


def test_fd_fix_static_offsets_uzun_kesimi_hareketli_pencereye_kaydirir(tmp_path):
    from short_bot.reel import _fd_fix_static_offsets
    klip = _sentetik(tmp_path, "fx.mp4", 6, 6)
    # kapanış alt-kesimi 5sn ve ofset 8. saniyeye (donuk yarıya) düşmüş
    subcuts = [(0, 0.0, 3.0), (1, 3.0, 8.0)]
    clip_paths = [klip, klip]
    starts = [0.0, 8.0]
    yeni = _fd_fix_static_offsets(clip_paths, subcuts, starts, "ffmpeg")
    assert yeni[1] < 6.0                             # hareketli yarıya kaydı
    assert yeni[0] == 0.0                            # kısa/temiz kesime dokunulmadı


def test_fd_fix_static_offsets_olculemezse_dokunmaz(tmp_path):
    from short_bot.reel import _fd_fix_static_offsets
    bozuk = tmp_path / "b.mp4"
    bozuk.write_bytes(b"mp4")
    starts = [2.0]
    yeni = _fd_fix_static_offsets([bozuk], [(0, 0.0, 5.0)], starts, "ffmpeg")
    assert yeni == [2.0]                             # fail-open
