"""SP4: kürate klip temizleme (hafif/kenar watermark → delogo)."""
import subprocess
from pathlib import Path

import pytest

from short_bot.curated_clean import WatermarkDetect, _REGION_BOX, clean_clip


def _make_clip(path: Path):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc=size=720x1280:rate=15:duration=2", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=60)


def test_clean_clip_skips_when_absent():
    assert clean_clip("x.mp4", WatermarkDetect(present=False), out_path="o.mp4") is None


def test_clean_clip_skips_heavy_cover():
    # Yazı özneyi kaplıyorsa temizleme artefakt bırakır → dokunma.
    d = WatermarkDetect(present=True, regions=["top-right"], covers_subject=True)
    assert clean_clip("x.mp4", d, out_path="o.mp4") is None


def test_clean_clip_skips_unknown_region():
    d = WatermarkDetect(present=True, regions=["none"], covers_subject=False)
    assert clean_clip("x.mp4", d, out_path="o.mp4") is None


def test_region_boxes_cover_corners_and_edges():
    for r in ("top-left", "top-right", "bottom-left", "bottom-right", "top", "bottom"):
        assert r in _REGION_BOX


def test_clean_clip_delogo_runs(tmp_path):
    src = tmp_path / "src.mp4"
    _make_clip(src)
    out = tmp_path / "clean.mp4"
    d = WatermarkDetect(present=True, regions=["top-right"], covers_subject=False)
    res = clean_clip(src, d, out_path=out)
    assert res == out and out.exists()
    # geçerli, oynatılabilir video mü (delogo bozmadı)
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(out)],
                       capture_output=True, text=True, timeout=20)
    assert float((p.stdout or "0").strip()) > 1.0


def test_crop_source_banner_edges_only(tmp_path):
    """Kaynak yazı-bandı: ÜST/ALT kenara yapışık şerit kırpılır; ORTADA yüzen atlanır."""
    from short_bot.curated_clean import SourceBanner, crop_source_banner
    src = tmp_path / "src.mp4"
    _make_clip(src)
    # ÜST kenar (tepede) → kırpılır, süre korunur
    top = crop_source_banner(src, SourceBanner(present=True, y_center=0.05, frac=0.08),
                             out_path=tmp_path / "top.mp4")
    assert top is not None and top.exists()
    # ÜST BÖLGE ama tepede küçük boşluk (short 967: y≈0.12, top_edge≈0.09) → yine KIRPILIR
    # (bandın dibi üst %20 içinde; eskiden 'ortada yüzüyor' sanılıp kaçıyordu)
    top2 = crop_source_banner(src, SourceBanner(present=True, y_center=0.12, frac=0.06),
                              out_path=tmp_path / "top2.mp4")
    assert top2 is not None and top2.exists()
    # ALT kenar (dipte) → kırpılır
    bot = crop_source_banner(src, SourceBanner(present=True, y_center=0.95, frac=0.08),
                             out_path=tmp_path / "bot.mp4")
    assert bot is not None and bot.exists()
    # ORTADA yüzen bant → temiz kırpılamaz → None (dokunma, içerik koru)
    mid = crop_source_banner(src, SourceBanner(present=True, y_center=0.48, frac=0.08),
                             out_path=tmp_path / "mid.mp4")
    assert mid is None
    # yok / ihmal edilebilir ince → None
    assert crop_source_banner(src, SourceBanner(present=False),
                              out_path=tmp_path / "n.mp4") is None
    assert crop_source_banner(src, SourceBanner(present=True, y_center=0.02, frac=0.02),
                              out_path=tmp_path / "n2.mp4") is None
    # kırpılan üst şerit gerçekten daha kısa (yükseklik azaldı)
    def _h(p):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=height", "-of", "csv=p=0", str(p)],
                           capture_output=True, text=True, timeout=20)
        return int((r.stdout or "0").strip())
    assert _h(top) < _h(src)


def test_quality_and_faith_judges_use_dense_storyboard(monkeypatch, tmp_path):
    """D) Kritik yargılar (kalite + sadakat) 6 değil ≥9 kare görmeli — 6-kare örneklem
    klibin asıl öznesini kaçırabiliyor (çöpçü klibinde köpek hiç kareye düşmedi)."""
    import short_bot.reel as reel_mod
    from short_bot.curated_clean import judge_clip_quality, verify_curated_narration

    calls = []

    def _rec(clip, out, ffmpeg, *, cols=3, rows=2, frame_w=256):
        calls.append(cols * rows)
        return False   # storyboard kurulamadı → yargı None döner, vision hiç çağrılmaz

    monkeypatch.setattr(reel_mod, "_storyboard_frames", _rec)

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    assert judge_clip_quality(tmp_path / "c.mp4", vision_call=_V()) is None
    assert verify_curated_narration(tmp_path / "c.mp4", "anlatım", vision_call=_V()) is None
    assert len(calls) == 2 and all(n >= 9 for n in calls)


def test_quality_prompt_asks_muted_watchability():
    """C) Kalite prompt'u 'ses olmadan da işliyor mu' (works_muted) sorusunu SORMALI —
    orijinal ses atılıyor; ses-yüklü klip (kahkaha/diyalog) sessiz izlenince sıradanlaşır."""
    from short_bot.curated_clean import _quality_prompt
    for tone in ("mizah", "duygu", "karma"):
        assert "works_muted" in _quality_prompt(tone)


def test_faith_prompt_rejects_unseen_action_inferred_backwards():
    """C) SADAKAT: GÖRÜNMEYEN EYLEM de uydurmadır.

    GERÇEK HATA (short 1077): anne karelerde BAŞTAN SONA cübbeli yatıyor, oğlun kepi
    hiç başından çıkmıyor; anlatım ise 'oğlu kepini çıkarıp annesinin üstüne örttü,
    mezuniyetini ona giydirdi' dedi. Yargıç 'sadık' geçti — çünkü kural yalnız
    uydurma VARLIK arıyordu, sonuç durumundan geriye dönük uydurulan DEĞİŞİM'i değil.
    """
    from short_bot.curated_clean import _FAITH_PROMPT

    def _norm(s: str) -> str:
        # Türkçe tuzağı: "GERİYE".lower() → "geri̇ye" (İ, birleşik noktalı i'ye düşer)
        return s.replace("İ", "i").replace("I", "ı").lower()

    low = _norm(_FAITH_PROMPT)
    assert "değişim" in low, "görünmeyen değişim/eylem kuralı yok"
    assert "geriye dönük" in low, "sonuç durumundan geriye çıkarım yasağı yok"


def test_faith_prompt_rejects_invented_roles_and_relations():
    """D) SADAKAT: var olan kişilere UYDURMA ROL/İLİŞKİ atamak da uydurmadır.

    GERÇEK HATA (short 1140, kullanıcı: 'senaryoda çelişkiler'): klipte tekerlekli
    sandalyedeki DAMAT ve onunla dans eden GELİN var (Reddit başlığı: 'Have you some
    friends like he does' — arkadaşları onu ayağa kaldırıyor). Anlatım ise 'Ayakta
    duramayan bir BABA, o gece KIZININ kollarında dans etti' dedi ve aynı metinde
    'gelin ile damat' diye ÜÇÜNCÜ bir çift icat etti — kendi içinde çelişti.
    Yargıç 'sadık' geçti: kural yalnız olmayan VARLIK arıyordu, var olan kişiye
    yanlış KİMLİK/AKRABALIK atamayı 'yorum' sayıyordu. Oysa izleyici için hikâyenin
    ta kendisi değişiyor.
    """
    from short_bot.curated_clean import _FAITH_PROMPT

    def _norm(s: str) -> str:
        return s.replace("İ", "i").replace("I", "ı").lower()

    low = _norm(_FAITH_PROMPT)
    assert "akrabalık" in low or "ilişki" in low, "uydurma rol/ilişki kuralı yok"
    assert "başlık" in low, "başlığın ilişkiyi belirlediği (arkadaş/kızı) uyarısı yok"


def test_judge_final_video_reports_failure_to_given_logger(tmp_path, monkeypatch):
    """B) Yargıç patlarsa NEDENİ koşu loguna düşsün — modül logger'ı koşu dosyasına
    bağlı değil, bu yüzden çağıranın logger'ı kabul edilmeli."""
    import short_bot.curated_clean as cc

    import short_bot.claude_cli as cli

    clip = tmp_path / "c.mp4"
    _make_clip(clip)

    def _boom(*a, **k):
        raise RuntimeError("vision patladı")

    monkeypatch.setattr(cli, "run_json", _boom)
    seen = []

    class _Log:
        def info(self, msg, *a, **k):
            seen.append(str(msg))

        def warning(self, msg, *a, **k):
            seen.append(str(msg))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    out = cc.judge_final_video(clip, "anlatım", vision_call=_V(),
                               ffmpeg_path="ffmpeg", tone="duygu", log=_Log())
    assert out is None
    assert any("vision patladı" in m for m in seen), f"neden koşu loguna düşmedi: {seen}"


def test_judge_final_video_builds_storyboard_and_returns(monkeypatch, tmp_path):
    """A) judge_final_video: bitmiş videodan storyboard kurup vision'a anlatımla birlikte
    sorar; yargıyı döndürür. Hata yolunda None (fail-open kararı çağıranın)."""
    import short_bot.claude_cli as cli
    from short_bot.curated_clean import FinalVideoQA, judge_final_video

    src = tmp_path / "final.mp4"
    _make_clip(src)
    seen = {}

    def _fake_run_json(prompt, schema, *, image_path=None, **k):
        seen["prompt"] = prompt
        assert image_path is not None and Path(image_path).exists()
        return FinalVideoQA(watchable=True, score=8)

    monkeypatch.setattr(cli, "run_json", _fake_run_json)

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    q = judge_final_video(src, "yavru fil bakıcısına sarılıyor", vision_call=_V(),
                          tone="duygu")
    assert q is not None and q.watchable and q.score == 8
    assert "yavru fil" in seen["prompt"]          # anlatım metni yargıya veriliyor


def test_watermark_uncleanable_moving_vs_static():
    from short_bot.curated_clean import watermark_uncleanable
    # tek SABİT köşe → temizlenebilir
    assert not watermark_uncleanable(WatermarkDetect(present=True, regions=["top-right"]))
    # HAREKETLİ (birden çok bölge, TikTok) → temizlenemez
    assert watermark_uncleanable(WatermarkDetect(present=True,
        regions=["bottom-left", "bottom-right", "center"]))
    # köşe-DIŞI kenar strip → temizlenemez
    assert watermark_uncleanable(WatermarkDetect(present=True, regions=["mid-left"]))
    # özneyi KAPLAYAN → temizlenemez
    assert watermark_uncleanable(WatermarkDetect(present=True, regions=["top-right"],
                                                 covers_subject=True))
    # TikTok PLATFORM logosu (moving=True): tek köşe raporlansa BİLE temizlenemez say
    # (short 937: vision 'bottom-right' dedi ama logo gezdiği için delogo ıskaladı)
    assert watermark_uncleanable(WatermarkDetect(present=True, regions=["bottom-right"],
                                                 moving=True))
    assert not watermark_uncleanable(WatermarkDetect(present=False))


def test_judge_clip_quality_gates_mundane(monkeypatch, tmp_path):
    """judge_clip_quality: storyboard vision → ClipQuality (engaging+score) döner; sıradan
    (düşük) klip ayırt edilebilsin. run_json/_storyboard_frames fonksiyon-içi import'lanır →
    KAYNAK modüllerinde patch'le."""
    import short_bot.claude_cli as cli
    import short_bot.reel as reel
    from short_bot.curated_clean import ClipQuality, judge_clip_quality

    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    monkeypatch.setattr(cli, "run_json",
                        lambda prompt, schema, **kw: ClipQuality(engaging=False, score=3))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    q = judge_clip_quality(tmp_path / "clip.mp4", vision_call=_V(), tone="mizah")
    assert q is not None and q.engaging is False and q.score == 3


def test_verify_narration_faithfulness(monkeypatch, tmp_path):
    """verify_curated_narration: storyboard + anlatım → NarrationCheck; kaba uyumsuzlukta
    faithful=False. run_json/_storyboard_frames fonksiyon-içi import → kaynakta patch."""
    import short_bot.claude_cli as cli
    import short_bot.reel as reel
    from short_bot.curated_clean import NarrationCheck, verify_curated_narration

    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    monkeypatch.setattr(cli, "run_json",
                        lambda prompt, schema, **kw: NarrationCheck(faithful=False,
                                                                    mismatch="köpek yok"))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    c = verify_curated_narration(tmp_path / "c.mp4", "bir köpek koşuyor", vision_call=_V())
    assert c is not None and c.faithful is False and c.mismatch == "köpek yok"
    # boş anlatım → None (yargılanmaz)
    assert verify_curated_narration(tmp_path / "c.mp4", "  ", vision_call=_V()) is None


def test_detect_heavy_text_flags_burned_captions(monkeypatch, tmp_path):
    """detect_heavy_text: storyboard → HeavyText; gömülü altyazı/banner DOLU (editlenmiş
    repost) klip yakalanır (short 968). run_json/_storyboard_frames kaynakta patch'lenir."""
    import short_bot.claude_cli as cli
    import short_bot.reel as reel
    from short_bot.curated_clean import HeavyText, detect_heavy_text

    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    monkeypatch.setattr(cli, "run_json",
                        lambda prompt, schema, **kw: HeavyText(heavy=True,
                                                               kinds=["subtitle", "banner"]))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    r = detect_heavy_text(tmp_path / "c.mp4", vision_call=_V())
    assert r is not None and r.heavy is True and "subtitle" in r.kinds


def test_safety_schemas_reject_empty_json():
    """Güvenlik şemaları (WatermarkDetect/HeavyText/ClipQuality) BOŞ {} yanıtı REDDETMELİ →
    model_validate({}) ValidationError atsın ki run_json None dönsün → gate fail-closed/open
    DOĞRU çalışsın. Eskiden default'lar sessizce geçiyordu (kirli klip geçer / iyi klip elenir)."""
    import pytest
    from pydantic import ValidationError

    from short_bot.curated_clean import ClipQuality, HeavyText, WatermarkDetect

    for schema in (WatermarkDetect, HeavyText, ClipQuality):
        with pytest.raises(ValidationError):
            schema.model_validate({})
    # karar alanı VERİLİRSE geçerli (diğer alanlar default'lu kalır)
    assert WatermarkDetect.model_validate({"present": True}).present is True
    assert HeavyText.model_validate({"heavy": False}).heavy is False
    assert ClipQuality.model_validate({"engaging": True, "score": 8}).score == 8


def test_describe_clip_beats_time_ordered(monkeypatch, tmp_path):
    """describe_clip_beats: klibi segment'lere bölüp her dilimi AYRI tarif eder → zaman-sıralı
    beat sheet (BAŞ/ORTA/SON). Böylece anlatım footage SIRASINA oturur, ödül erken açılmaz
    (short 990: kullanıcı 'sahneler ile cümleler oturmuyor'). subprocess/storyboard/describe
    fonksiyon-içi import → kaynakta patch."""
    import subprocess
    import short_bot.footage_matcher as fm
    import short_bot.reel as reel
    from short_bot.curated_clean import describe_clip_beats

    # ffmpeg segment kesme → çıktı dosyasını yarat (başarı simüle); ffprobe çağrılmaz (duration_s verili)
    def _fake_run(cmd, *a, **k):
        try:
            Path(cmd[-1]).write_bytes(b"x")
        except Exception:  # noqa: BLE001
            pass
        class _R:
            returncode = 0; stdout = ""; stderr = ""
        return _R()
    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    # her segment FARKLI (zaman-sıralı) tarif döndür
    _descs = iter(["a runner collapses, others pass",
                   "a yellow-shirt runner stops to help",
                   "several runners carry him to the finish"])
    monkeypatch.setattr(fm, "describe_storyboard", lambda board, **k: (next(_descs), False))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    out = describe_clip_beats(tmp_path / "c.mp4", vision_call=_V(), duration_s=30, segments=3)
    # üç dilim de var, zaman-sıralı, her biri kendi tarifiyle
    assert "BAŞ" in out and "ORTA" in out and "SON" in out
    assert "collapses" in out and "yellow-shirt" in out and "carry him" in out
    assert out.index("BAŞ") < out.index("ORTA") < out.index("SON")
    # süre çok kısa / segment<2 → boş (fail-open, blok desc'e düşülür)
    assert describe_clip_beats(tmp_path / "c.mp4", vision_call=_V(), duration_s=3) == ""


def test_describe_clip_beats_passes_title_to_describer(monkeypatch, tmp_path):
    """DİLİM TARİFÇİSİ DE BAŞLIĞI GÖRMELİ (short 1216): SON dilimi 'yeni Jordan'ları
    GİYİYOR' idi; başlıksız vision aynı kareleri 'sırt çantalarını karıştırıyor' diye
    okudu. Anlatımın TEK kaynağı beat sheet olduğu için yazar o dilimi kullanamadı ve
    videonun son üçte biri anlatımsız (jenerik moral) kaldı. Sadakat/kalite/netlik
    kapıları başlığı ZATEN alıyor (short 1140/1154 dersi) — aynı körlük tarifçide de
    vardı. Başlık TANIMA bağlamıdır; görünmeyen olayı ekletmez (prompt'taki koruma)."""
    import subprocess
    import short_bot.footage_matcher as fm
    import short_bot.reel as reel
    from short_bot.curated_clean import describe_clip_beats

    def _fake_run(cmd, *a, **k):
        try:
            Path(cmd[-1]).write_bytes(b"x")
        except Exception:  # noqa: BLE001
            pass
        class _R:
            returncode = 0; stdout = ""; stderr = ""
        return _R()
    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    seen = []
    monkeypatch.setattr(
        fm, "describe_storyboard",
        lambda board, **k: (seen.append(k.get("context", "")) or ("desc", False)))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    describe_clip_beats(tmp_path / "c.mp4", vision_call=_V(), duration_s=30, segments=3,
                        title="Their gym teacher wore Jordan 13s he got in 1998")
    assert len(seen) == 3 and all("Jordan 13" in c for c in seen), \
        f"başlık dilim tarifçisine geçmiyor: {seen}"
    # başlıksız çağrı → bağlam boş (mevcut çağıranlar için sıfır regresyon)
    seen.clear()
    describe_clip_beats(tmp_path / "c.mp4", vision_call=_V(), duration_s=30, segments=3)
    assert len(seen) == 3 and all(not c for c in seen)


def test_describe_storyboard_context_is_guarded(monkeypatch, tmp_path):
    """describe_storyboard bağlamı KORUMALI enjekte eder: nesne/rol TANIMA için serbest,
    karelerde GÖRÜNMEYEN olayı bağlamdan ekleme YASAK (arc-tamamlama sızıntısı olmasın).
    Bağlamsız çağrıda prompt bire bir eski hâli (footage keşif yolu — sıfır regresyon)."""
    import short_bot.claude_cli as cli
    from short_bot.footage_matcher import _StoryboardDescription, describe_storyboard

    seen = {}

    def _fake(prompt, schema, **k):
        seen["prompt"] = prompt
        return _StoryboardDescription(content="desc", is_static=False)
    monkeypatch.setattr(cli, "run_json", _fake)
    board = tmp_path / "b.jpg"
    board.write_bytes(b"x")

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    describe_storyboard(board, vision_call=_V(), n_frames=9,
                        context="Their gym teacher wore Jordan 13s")
    assert "Jordan 13" in seen["prompt"], "bağlam prompt'a girmiyor"
    assert "GÖRÜNMEYEN" in seen["prompt"], "bağlam korumasız (görünmeyen-olay yasağı yok)"
    describe_storyboard(board, vision_call=_V(), n_frames=9)
    assert "Jordan 13" not in seen["prompt"] and "BAĞLAM" not in seen["prompt"]


def test_final_qa_prompt_demands_frame_by_frame_caption_check():
    """FİNAL QA SENKRONU KARE KARE SORMALI (short 1216): global 'örtüşüyor mu?' sorusu
    sync_ok=True geçirdi — oysa 'öğrenciler etrafını sardı' altyazısı akarken ekranda
    adam TEK BAŞINA kutu açıyordu ve videonun son üçte biri (ayakkabıyı giyip kutlama)
    altyazıda hiç yoktu. Kareler altyazı ÇİPLERİYLE render edilmiş → yargıç her karenin
    içindeki altyazıyı O karenin görüntüsüyle karşılaştırabilir ve karşılaştırMALIDIR."""
    from short_bot.curated_clean import _final_qa_prompt

    p = _final_qa_prompt("duygu", "anlatım metni")
    assert "KARE KARE" in p, "senkron yargısı kare-kare istenmiyor"
    assert "geç" in p and "erken" in p, \
        "olayın klipte başka anda olsa bile o karede yoksa false sayılacağı söylenmiyor"


def test_faith_prompt_rejects_outcome_flipping_exaggeration():
    """E) SADAKAT: abartı SERBEST ama olayın SONUCUNU ters çeviremez.

    GERÇEK HATA (short 1146): vision 'sendeleyip savruldular ama üçü de AYAKTA KALDI'
    diyordu; anlatım 'bacakları boşaldı, sarsılarak YIĞILDI' yazdı. Yargıç 'sadık' geçti
    çünkü prompt abartıyı koşulsuz serbest bırakıyordu — oysa izleyici o saniyede
    adamları ayakta ve gülerken görüyor. 'Neredeyse düştü' ≠ 'düştü'."""
    from short_bot.curated_clean import _FAITH_PROMPT

    def _norm(s: str) -> str:
        return s.replace("İ", "i").replace("I", "ı").lower()

    low = _norm(_FAITH_PROMPT)
    assert "neredeyse" in low, "'neredeyse düştü' → 'düştü' çevirme yasağı yok"
    assert "sonuc" in low.replace("ç", "c"), "sonucu ters çevirme kuralı yok"


def test_storyboard_prompt_asks_action_direction():
    """EYLEMİN YÖNÜ SORULMALI (short 1154/1156 — kullanıcı: 'senaryo hep alakasız').

    GERÇEK HATA: klipte adam duvarı kaplayan gazeteleri SÖKÜYOR ve altından üvey kızının
    bıraktığı sarı notlar çıkıyor (0.3s'de duvar tamamen gazete, 19.5s'de tamamen not).
    Beat sheet bunu TERS okudu: 'presses them flat against the wall' (yapıştırıyor).
    Anlatım o yanlışı devraldı, iki ayrı üretimde de 'duvara kağıt yapıştırıyor/dolduruyor'
    dedi — izleyici için hikâyenin tamamı ters döndü (sürprizi HAZIRLAYAN mı, kendisine
    hazırlananı AÇAN mı).

    Storyboard'da hareket yönü tek kareden okunamaz; İLK ve SON kare karşılaştırılmalı:
    ekranda ne ÇOĞALDI, ne EKSİLDİ. Ekleme/çıkarma, takma/sökme, açma/kapama çiftlerinde
    yönü ters yazmak en sık vision hatası."""
    from short_bot.footage_matcher import _STORYBOARD_PROMPT

    low = _STORYBOARD_PROMPT.replace("İ", "i").replace("I", "ı").lower()
    assert "yön" in low, "eylemin yönü sorulmuyor"
    assert "ilk" in low and "son" in low, "ilk/son kare karşılaştırması istenmiyor"
    assert "sök" in low or "çıkar" in low, "ekleme/çıkarma çifti örneklenmiyor"


def test_faith_prompt_checks_action_direction():
    """SADAKAT KAPISI da yönü sorgulamalı — beat sheet yanılırsa ikinci savunma odur.

    short 1156: kapı ilk denemede yönü DOĞRU yakaladı ('SÖKÜP açığa çıkarıyor') ama
    yeniden yazım gene 'dolduruyor' dedi ve ikinci yargı bu sefer 'sadık' geçti.
    Yön ölçütü açıkça yazılmadığı için yargı denemeden denemeye oynuyor."""
    from short_bot.curated_clean import _FAITH_PROMPT

    low = _FAITH_PROMPT.replace("İ", "i").replace("I", "ı").lower()
    assert "yön" in low, "sadakat kapısı eylemin yönünü sormuyor"


def test_describe_clip_beats_uses_dense_storyboard(monkeypatch, tmp_path):
    """BEAT SHEET 6 DEĞİL ≥9 KARE GÖRMELİ — seyrek örneklem detayı kaçırıyor.

    GERÇEK HATA (short 1154 klibi): BAŞ dilimi 20 saniye ve o dilimde adam gazeteyi
    söküp altındaki SARI NOT duvarını açığa çıkarıyor. 6 kareyle vision duvarı
    'bare tan wall with a framed photograph' diye tarif etti — notları hiç görmedi.
    Sonuç: anlatım (DOĞRU olarak) 'notlar çıkıyor' deyince netlik kapısı bunu beat
    sheet'te olmadığı için UYDURMA sayıp reddetti — yani eksik beat sheet İYİ anlatımı
    eledi. Sadakat kapısı aynı klipte 9 kareyle bakıp yönü/detayı doğru okumuştu
    (bkz. test_quality_and_faith_judges_use_dense_storyboard — aynı ders)."""
    import short_bot.reel as reel_mod
    from short_bot.curated_clean import describe_clip_beats

    calls = []

    def _rec(clip, out, ffmpeg, *, cols=3, rows=2, frame_w=256):
        calls.append(cols * rows)
        return False   # storyboard kurulamadı → dilim atlanır, vision hiç çağrılmaz

    monkeypatch.setattr(reel_mod, "_storyboard_frames", _rec)

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    clip = tmp_path / "c.mp4"
    _make_clip(clip)          # gerçek klip: segment kesimi ffmpeg ile yapılıyor
    describe_clip_beats(clip, vision_call=_V(), ffmpeg_path="ffmpeg", duration_s=6.0)
    assert calls, "storyboard hiç kurulmadı"
    assert all(n >= 9 for n in calls), f"beat sheet seyrek örneklem kullanıyor: {calls}"


def test_faith_prompt_title_cannot_justify_offscreen_outcome():
    """BAŞLIK EKRANDAKİNİ AÇIKLAR, EKRANDA OLMAYAN OLAYI EKLEYEMEZ (short 1164).

    short 1140/1154'te kapılara başlık besledim: kişilerin kim olduğu ve beat sheet'in
    kaçırdığı detaylar ancak başlıktan okunuyordu ve o kural doğru işi yaptı (notlar
    EKRANDAYDI, vision görememişti).

    Ama kural fazla açıktı: short 1164'te klip 18 saniye boyunca kafeste miyavlayan bir
    kediden ibaretti — ne sahiplenme, ne çıkış, ne dönüş vardı. Başlık 'Came for a dog
    and left with him' dediği için anlatım 'Sonunda fark edildi; köpek yerine onunla
    döndüler' yazdı ve kapı bunu 'başlıkta var' diye geçirdi. İzleyici o dönüşü
    GÖRMEDİĞİ için videodan hiçbir şey anlamadı (kullanıcı bildirimi).

    AYRIM: başlık ekranda GÖRÜNEN bir şeyi adlandırabilir/açıklayabilir; ekranda HİÇ
    OLMAYAN bir olayı, sonucu ya da devamını anlattıramaz."""
    from short_bot.curated_clean import _FAITH_PROMPT

    low = _FAITH_PROMPT.replace("İ", "i").replace("I", "ı").lower()
    assert "başlıkta olsa" in low, \
        "'başlıkta olsa BİLE ekranda yoksa uydurmadır' kuralı yok"
    assert "başlığın sınırı" in low, "başlığın rolü açıkça sınırlandırılmamış"
