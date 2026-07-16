"""Merak mimarisi: 3 aday senaryo -> rubrik yargici -> doktor (spec 2026-07-16)."""
from types import SimpleNamespace


def _kanal():
    reel = SimpleNamespace(target_duration_s=(45, 60), persona="vahsi_mizah",
                           mascot_name="", mascot_animal="", mascot_trait="")
    return SimpleNamespace(reel=reel, language="tr")


def _fake_draft(hook="hook cümlesi burada", oq="Bu tip neden korkutuyor?"):
    from short_bot.reel_models import FDDraftNarration
    return FDDraftNarration.model_validate({
        "hook": hook, "cover_title": "MANŞET",
        "beats": [{"text": "beat sıfır metni burada", "visual_query": "", "keyword": "K0"},
                  {"text": "beat bir metni burada", "visual_query": "", "keyword": "K1"},
                  {"text": "beat iki metni burada", "visual_query": "", "keyword": "K2"}],
        "close": "hook cümlesi kapanış", "mood": "upbeat",
        "open_question": oq, "reveal_beat": 2, "clip_order": [1, 0, 2]})


def test_iskeletler_uc_farkli_strateji():
    from short_bot.reel_curiosity import CURIOSITY_SKELETONS
    assert len(CURIOSITY_SKELETONS) == 3
    etiketler = [e for e, _ in CURIOSITY_SKELETONS]
    assert len(set(etiketler)) == 3
    talimatlar = " ".join(t for _, t in CURIOSITY_SKELETONS)
    # üç strateji: gizem-önce / tırmanan bahis / sahte çözüm+twist
    assert "SONA SAKLA" in talimatlar or "sona sakla" in talimatlar.lower()
    assert "DAHA BÜYÜK" in talimatlar or "daha büyük" in talimatlar.lower()
    assert "TERS KÖŞE" in talimatlar or "twist" in talimatlar.lower()


def test_rubrik_kritik_maddeleri_iceriyor():
    # NOT .lower() ile arama YAPMA: Python'da "AÇIK".lower() == "açik" (ı değil i)
    # — Türkçe kavramları rubrikteki YAZILDIĞI hâliyle ara.
    from short_bot.reel_curiosity import RUBRIC
    for kavram in ("AÇIK DÖNGÜ", "SIZINTI", "KANCASI", "TIRMANIŞ", "ÖDEME",
                   "MİZAH", "GÖRÜNTÜ SADAKATİ", "KLİŞE"):
        assert kavram in RUBRIC, f"rubrikte eksik kavram: {kavram}"


# --- Task 4: write_candidates ------------------------------------------------

def test_write_candidates_uc_iskelet_uc_prompt():
    from short_bot.reel_curiosity import CURIOSITY_SKELETONS, write_candidates
    promptlar = []

    def inv(p, schema):
        promptlar.append(p)
        return _fake_draft()

    adaylar = write_candidates("kartal", ["a", "b", "c"], channel=_kanal(),
                               seed=3, invoke=inv)
    assert len(adaylar) == 3
    assert len(promptlar) == 3
    # her promptta TAM BİR iskelet etiketi var (adaylar ayrışıyor)
    for p in promptlar:
        assert sum(1 for e, _ in CURIOSITY_SKELETONS if e in p) == 1
    # merak alanları prompt'ta isteniyor
    assert all('"open_question"' in p and '"reveal_beat"' in p
               and '"clip_order"' in p for p in promptlar)
    # persona bloğu adaylara da giriyor (tek bileşim noktası _fd_prompt)
    assert all("PERSONA" in p or "SAHNE MODU" in p for p in promptlar)


def test_write_candidates_coken_aday_dusurulur():
    from short_bot.reel_curiosity import write_candidates
    sayac = {"n": 0}

    def inv(p, schema):
        sayac["n"] += 1
        if sayac["n"] == 2:
            raise RuntimeError("LLM down")
        return _fake_draft()

    adaylar = write_candidates("kartal", ["a", "b", "c"], channel=_kanal(),
                               seed=0, invoke=inv)
    assert len(adaylar) == 2          # çöken düştü, kalanlar yaşıyor


# --- Task 5: judge_scripts ----------------------------------------------------

def test_judge_kazanani_secer_ve_sikayetleri_dondurur():
    from short_bot.reel_curiosity import JudgeVerdict, judge_scripts
    adaylar = [_fake_draft(hook=f"hook varyant {i} burada") for i in range(3)]
    yakalanan = {}

    def inv(p, schema):
        yakalanan["p"] = p
        return JudgeVerdict(winner=1, scores=[4, 8, 6],
                            complaints=["beat 2 cevabı erken sızdırıyor"])

    kazanan, verdict = judge_scripts(adaylar, topic="kartal", invoke=inv)
    assert kazanan is adaylar[1]
    assert verdict.complaints
    p = yakalanan["p"]
    assert "RUBRİĞ" in p                                # rubrik promptta
    assert "hook varyant 0" in p and "hook varyant 2" in p


def test_judge_cokerse_ilk_aday():
    from short_bot.reel_curiosity import judge_scripts
    adaylar = [_fake_draft(), _fake_draft()]

    def patlar(p, s):
        raise RuntimeError("down")

    kazanan, verdict = judge_scripts(adaylar, topic="x", invoke=patlar)
    assert kazanan is adaylar[0]
    assert verdict is None


def test_judge_gecersiz_winner_kelepcelenir():
    from short_bot.reel_curiosity import JudgeVerdict, judge_scripts
    adaylar = [_fake_draft(), _fake_draft()]

    def inv(p, s):
        return JudgeVerdict(winner=9, scores=[5, 5], complaints=[])

    kazanan, _ = judge_scripts(adaylar, topic="x", invoke=inv)
    assert kazanan is adaylar[0]      # aralık dışı → ilk aday


def test_judge_tek_aday_direkt_gecer():
    from short_bot.reel_curiosity import judge_scripts
    tek = _fake_draft()
    kazanan, verdict = judge_scripts(
        [tek], topic="x",
        invoke=lambda p, s: (_ for _ in ()).throw(AssertionError("çağrılmamalı")))
    assert kazanan is tek and verdict is None


# --- Task 6: doctor_pass -------------------------------------------------------

def test_doctor_sikayetleri_promptlar_ve_sonucu_dondurur():
    from short_bot.reel_curiosity import doctor_pass
    kazanan = _fake_draft()
    duzeltilmis = _fake_draft(hook="düzeltilmiş hook cümlesi burada")
    yakalanan = {}

    def inv(p, schema):
        yakalanan["p"] = p
        return duzeltilmis

    out = doctor_pass(kazanan, ["beat 2 cevabı erken sızdırıyor"],
                      topic="kartal", invoke=inv)
    assert out is duzeltilmis
    assert "erken sızdırıyor" in yakalanan["p"]         # şikâyet promptta
    assert "beat sıfır metni burada" in yakalanan["p"]  # orijinal senaryo promptta


def test_doctor_beat_sayisi_degisirse_kazanan_kalir():
    from short_bot.reel_models import FDDraftNarration
    from short_bot.reel_curiosity import doctor_pass
    kazanan = _fake_draft()
    bozuk = FDDraftNarration.model_validate({
        "hook": "hook cümlesi burada", "beats": [
            {"text": "tek beat kaldı ama dört beat lazımdı", "visual_query": "", "keyword": "K"},
            {"text": "iki beat kaldı ama dört beat lazımdı", "visual_query": "", "keyword": "K"},
            {"text": "üç beat kaldı ama dört beat lazımdı", "visual_query": "", "keyword": "K"},
            {"text": "dört beat oldu ama kazanan üç beatti", "visual_query": "", "keyword": "K"}],
        "close": "kapanış cümlesi burada", "mood": "upbeat"})

    out = doctor_pass(kazanan, ["x"], topic="k", invoke=lambda p, s: bozuk)
    assert out is kazanan             # klip bağı bozulamaz


def test_doctor_sikayet_yoksa_dokunmaz():
    from short_bot.reel_curiosity import doctor_pass
    kazanan = _fake_draft()
    out = doctor_pass(kazanan, [], topic="k",
                      invoke=lambda p, s: (_ for _ in ()).throw(AssertionError("çağrılmamalı")))
    assert out is kazanan


# --- Task 7: write_curious_narration (orkestratör) ------------------------------

def test_orkestrator_zincir_ve_permutasyon():
    from short_bot.reel_curiosity import JudgeVerdict, write_curious_narration
    cagri = {"aday": 0, "yargic": 0, "doktor": 0}

    def inv(p, schema):
        if schema is JudgeVerdict:
            cagri["yargic"] += 1
            return JudgeVerdict(winner=0, scores=[7], complaints=["beat 1 kancasız"])
        if "ŞİKÂYETLER" in p:
            cagri["doktor"] += 1
            return _fake_draft(hook="doktor düzeltti bu hook cümlesini")
        cagri["aday"] += 1
        return _fake_draft()

    narr, perm = write_curious_narration(
        "kartal", ["tarif a", "tarif b", "tarif c"],
        ["eagle soaring", "eagle diving", "eagle landing"],
        channel=_kanal(), seed=1, invoke=inv)
    assert cagri == {"aday": 3, "yargic": 1, "doktor": 1}
    assert narr.hook == "doktor düzeltti bu hook cümlesini"
    # _fake_draft clip_order=[1,0,2] → permütasyon dönüyor, sorgular ona göre pinli
    assert perm == [1, 0, 2]
    assert [b.visual_query for b in narr.beats] == \
        ["eagle diving", "eagle soaring", "eagle landing"]
    assert narr.hook_visual == "eagle diving"
    from short_bot.reel_models import ReelNarration
    assert type(narr) is ReelNarration          # dönüş KATI şema


def test_orkestrator_tum_adaylar_cokerse_tek_cagri_yola_duser(monkeypatch):
    import short_bot.reel_curiosity as RC
    from short_bot.reel_models import ReelBeat, ReelNarration

    def tek_cagri(topic, descs, queries, **kw):
        return ReelNarration(
            hook="tek çağrı hook cümlesi", beats=[
                ReelBeat(text="beat sıfır metni burada", visual_query=queries[0], keyword="A"),
                ReelBeat(text="beat bir metni burada", visual_query=queries[1], keyword="B"),
                ReelBeat(text="beat iki metni burada", visual_query=queries[2], keyword="C")],
            close="tek çağrı kapanış cümlesi", mood="upbeat")

    monkeypatch.setattr(RC, "_fallback_single", tek_cagri)

    def hep_patlar(p, s):
        raise RuntimeError("down")

    narr, perm = RC.write_curious_narration(
        "kartal", ["a", "b", "c"], ["q0", "q1", "q2"],
        channel=_kanal(), seed=0, invoke=hep_patlar)
    assert narr.hook == "tek çağrı hook cümlesi"
    assert perm == [0, 1, 2]                     # kimlik permütasyonu
