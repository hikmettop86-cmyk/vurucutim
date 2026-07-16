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
        match_beat_clip=fake_match)
    # vision tarifini deterministik yap
    monkeypatch.setattr(REEL, "_describe_clip",
                        lambda c, **k: f"a chimpanzee ({c.name})")

    clips, descs, queries = _prepare_footage_driven(
        topic="şempanze", channel=_fd_channel(), reel=_fd_channel().reel, d=d,
        work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
        footage_priority=["pexels"], storyblocks_session=None,
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
        match_beat_clip=lambda q, **kw: None)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: "")
    import pytest
    with pytest.raises(RuntimeError, match="footage bulunamadı"):
        _prepare_footage_driven(
            topic="x", channel=_fd_channel(), reel=_fd_channel().reel, d=d,
            work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
            footage_priority=["pexels"], storyblocks_session=None,
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
        match_beat_clip=fake_match,
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
                footage_priority=["pexels"], storyblocks_session=None,
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
        match_beat_clip=fake_match)
    monkeypatch.setattr(REEL, "_describe_clip", fake_desc)
    monkeypatch.setattr(FM, "find_offsubject_clips",
                        lambda descs, tails, subject, **k: [
                            i for i, x in enumerate(descs) if "smartphone" in x])

    clips, descs, queries = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
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
        match_beat_clip=fake_match)
    monkeypatch.setattr(REEL, "_describe_clip", fake_desc)
    monkeypatch.setattr(FM, "find_offsubject_clips",
                        lambda descs, tails, subject, **k: [
                            i for i, x in enumerate(descs) if "marsh" in x])

    clips, descs, queries = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
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
        match_beat_clip=fake_match)
    monkeypatch.setattr(REEL, "_describe_clip", fake_desc)
    monkeypatch.setattr(FM, "find_offsubject_clips", lambda *a, **k: [])

    clips, descs, queries = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
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
        match_beat_clip=fake_match)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: f"an archerfish ({Path(c).name})")
    monkeypatch.setattr(REEL, "measure_motion",
                        lambda c, *a, **k: 0.001 if "static" in Path(c).name else 1.0)
    monkeypatch.setattr(FM, "find_offsubject_clips", lambda *a, **k: [])

    clips, descs, queries = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
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


def test_prepare_hepsi_statikse_fail_open(tmp_path, monkeypatch):
    # Havuz tümüyle statikse video ÇÖKMEZ — statik yedek kabul edilir (donuk
    # kuyruk riski, ama video yokluğundan yeğdir; eski akışla aynı ilke).
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
        match_beat_clip=fake_match)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: "an archerfish")
    monkeypatch.setattr(REEL, "measure_motion", lambda c, *a, **k: 0.001)
    monkeypatch.setattr(FM, "find_offsubject_clips", lambda *a, **k: [])

    clips, descs, queries = _prepare_footage_driven(d=d, **_fd_prep_kwargs(tmp_path))
    assert len(clips) >= 3                                # döngüsel tamamlama


def test_prepare_az_klip_uce_kelepcelenir(tmp_path, monkeypatch):
    # Havuz yalnız 2 AYRIK klip veriyor. ReelNarration min 3 beat ister; klipler 3'e
    # döngüsel tamamlanmazsa write_footage_driven_narration'ın "EXACTLY n beats" istemi
    # doğrulamaya takılıp üretimi ÇÖKERTİRDİ (fail-open sözü tutmazdı). Tekrarlı ama
    # üretilen video, video yokluğundan yeğdir.
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
        match_beat_clip=fake_match)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: f"desc {c.name}")

    clips, descs, queries = _prepare_footage_driven(
        topic="şempanze", channel=_fd_channel(), reel=_fd_channel().reel, d=d,
        work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
        footage_priority=["pexels"], storyblocks_session=None,
        vision_call=object(), ffmpeg_path="ffmpeg", llm_claude_path="claude",
        llm_model="default", llm_backend="claude_cli", llm_api_key=None)

    assert len(clips) >= 3                            # min 3 beat için 3'e tamamlandı
    assert len(descs) == len(clips) == len(queries)  # üçü hâlâ index-hizalı
    assert len(set(map(str, clips))) == 2            # yalnız 2 ayrık (tekrarla dolduruldu)
