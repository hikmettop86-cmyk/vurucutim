"""Anlatım olgu denetimi.

GERÇEK HATA (Almanca kanal, short 795 — kare kare incelendi):
    konu bankasındaki cümle DOĞRUYDU:
        "Frischer Kaffeesatz um junge Pflanzen? Koffein HEMMT dort das Wachstum."
        (kafein büyümeyi ENGELLER — allelopati, bilimsel olarak doğru)
    ama ANLATIM onu yükseltti:
        "...der deine grünen Freunde im Topf langsam VERGIFTET."  (ZEHİRLİYOR)
        ekran kartı: "VERGIFTUNGSGEFAHR"                           (ZEHİRLENME TEHLİKESİ)
    Kafein bitkiyi zehirlemez. Video YANLIŞ oldu.

    Ve kare-sıfır manşeti "KAFFEESATZ ALS NATÜRLICHER DÜNGER" (doğal gübre olarak
    kahve telvesi) diyordu — video tam TERSİNİ söylüyor.

Konu bankasında doğrulama kapısı VARDI ve konuyu doğru bulmuştu. Boşluk ANLATIMDAYDI.
"""
import pytest

from short_bot.reel_factcheck import Issue, check_narration, fact_feedback

KONU = ("Frischer Kaffeesatz um junge Pflanzen? Vorsicht: Koffein hemmt dort das "
        "Wachstum statt es zu fördern.")
ABARTAN = ("Das im Satz enthaltene Koffein wirkt als Wachstumshemmer. Es ist ein "
           "schleichender Prozess, der deine grünen Freunde im Topf langsam vergiftet.")
SADIK = ("Das im Kaffeesatz enthaltene Koffein wirkt als Wachstumshemmer und bremst "
         "die Wurzeln deiner Jungpflanzen. Erst kompostiert ist er unbedenklich.")


def _llm(issues):
    def _f(prompt, schema):
        _f.prompt = prompt
        return schema.model_validate({"issues": issues})
    _f.prompt = ""
    return _f


def test_ABARTMA_yakalanir():
    """'engelliyor' → 'zehirliyor'. Bu bir yükseltme ve YANLIŞ."""
    out = check_narration(
        KONU, cover_title="Koffein-Falle", text=ABARTAN, language="de",
        invoke=_llm([{"claim": "langsam vergiftet",
                      "problem": "Kafein büyümeyi engeller, zehirlemez"}]))
    assert len(out) == 1
    assert isinstance(out[0], Issue)
    assert "vergiftet" in out[0].claim


def test_SADIK_metin_TEMIZ_gecer():
    out = check_narration(KONU, cover_title="Koffein-Falle", text=SADIK,
                          language="de", invoke=_llm([]))
    assert out == []


def test_MANSET_CELISKISI_denetlenir():
    """Manşet videonun SONUCUNU yalanlıyor mu? Feed'de kaydıran biri onu ONAY sanar."""
    out = check_narration(
        KONU, cover_title="KAFFEESATZ ALS NATÜRLICHER DÜNGER", text=SADIK,
        language="de",
        invoke=_llm([{"claim": "KAFFEESATZ ALS NATÜRLICHER DÜNGER",
                      "problem": "Manşet videonun sonucunu yalanlıyor"}]))
    assert len(out) == 1


def test_prompt_KONUYU_ve_MANSETI_gorur():
    llm = _llm([])
    check_narration(KONU, cover_title="Koffein-Falle", text=ABARTAN, language="de",
                    invoke=llm)
    p = llm.prompt
    assert KONU in p, "konu tohumu denetime verilmedi"
    assert "Koffein-Falle" in p, "manşet denetime verilmedi"
    assert ABARTAN in p


def test_prompt_GERCEK_HATAYI_ornek_verir():
    """Ölçülen gerçek hata prompt'ta ÖRNEK olarak duruyor — model neyi arayacağını
    bilsin."""
    llm = _llm([])
    check_narration(KONU, cover_title="x", text=ABARTAN, language="de", invoke=llm)
    p = llm.prompt
    assert "ZEHİRLİYOR" in p or "zehirl" in p.lower()
    assert "ENGELLER" in p or "engelle" in p.lower()
    assert "MANŞET ÇELİŞKİSİ" in p


def test_prompt_YANLIS_ALARMDAN_kacinmayi_ister():
    """Retorik vurgu ('inanılmaz') sorun DEĞİL — her senaryoyu boşuna yeniden
    yazdırmak da bir hata."""
    llm = _llm([])
    check_narration(KONU, cover_title="x", text=ABARTAN, language="de", invoke=llm)
    assert "ŞÜPHEDEYSEN SORUN YOK SAY" in llm.prompt


def test_BOS_metin_LLM_CAGIRMAZ():
    def _patla(*a, **kw):
        raise AssertionError("boş metin için LLM çağrıldı")
    assert check_narration(KONU, cover_title="x", text="", language="de",
                           invoke=_patla) == []


def test_DENETIM_PATLARSA_uretim_DURMAZ():
    """Tek bir LLM arızası yüzünden video üretmemek yanlış olurdu — ama loglanır."""
    def _patla(*a, **kw):
        raise RuntimeError("model yok")
    assert check_narration(KONU, cover_title="x", text=ABARTAN, language="de",
                           invoke=_patla) == []


def test_BOS_claim_elenir():
    out = check_narration(
        KONU, cover_title="x", text=ABARTAN, language="de",
        invoke=_llm([{"claim": "   ", "problem": "y"},
                     {"claim": "vergiftet", "problem": "yanlış"}]))
    assert len(out) == 1


# --- GERİ BİLDİRİM ---------------------------------------------------------

def test_geri_bildirim_SORUNU_ALINTILAR():
    """Soyut 'abartma' uyarısı işe yaramıyor; ne yaptığını BİREBİR söylemek yarıyor
    (aşınmış-kalıp kapısında ölçüldü)."""
    fb = fact_feedback([Issue(claim="langsam vergiftet",
                              problem="Kafein zehirlemez, engeller")])
    assert "langsam vergiftet" in fb
    assert "Kafein zehirlemez" in fb
    assert "OTORİTESİ" in fb
    assert "manşet" in fb.lower()


# --- ANLATIM HATTINA BAĞLI MI? ---------------------------------------------
# Kapı yazıldı ama write_reel_narration onu ÇAĞIRMIYORSA hiçbir işe yaramaz.

def test_prompt_OLGUSAL_SADAKAT_kurali_TASIR():
    """Prompt 'TEPE = EN ŞOK EDİCİ bilgi' diyerek abartmayı fiilen TEŞVİK ediyordu.
    Karşı kural eklendi mi?"""
    from short_bot.config import ReelConfig
    from short_bot.reel_narration import build_reel_prompt

    class _Ch:
        language = "tr"
        reel = ReelConfig(enabled=True, voice_id="v")

    p = build_reel_prompt("kalp günde 100 bin kez atar", _Ch(), seed=1)
    assert "OLGUSAL SADAKAT" in p
    assert "zehirliyor" in p.lower()          # ölçülen gerçek hata örnek olarak
    assert "UYDURMA SAYI" in p
    assert "YALANLAYAMAZ" in p                # manşet çelişkisi kuralı


def test_ABARTAN_senaryo_YENIDEN_YAZDIRILIR(monkeypatch):
    """Kapı gerçekten hatta mı? Abartan senaryo bir kez yeniden yazdırılmalı."""
    import short_bot.reel_narration as RN
    from short_bot.config import ReelConfig
    from short_bot.reel_models import ReelBeat, ReelNarration

    class _Ch:
        language = "tr"
        reel = ReelConfig(enabled=True, voice_id="v")

    def _nar(text):
        return ReelNarration(
            hook="Kahve telvesini bitkine dökme.",
            cover_title="Kahve telvesi tuzagi",
            beats=[ReelBeat(text=text, visual_query="coffee grounds", keyword="KAHVE"),
                   ReelBeat(text="Kafein kokleri baskilar ve fideyi durdurur.",
                            visual_query="seedling soil", keyword="FIDE"),
                   ReelBeat(text="Once kompostla, sonra topraga ver bunu.",
                            visual_query="compost heap", keyword="KOMPOST")],
            peak_beat=1,
            close="Taze telve genc bitkiye gitmez, kompostlanmisi gider.",
            hook_visual="coffee grounds", close_visual="compost heap",
            mood="neutral")

    cagri = {"n": 0}

    def _fake_run_json(prompt, schema, **kw):
        cagri["n"] += 1
        # 1. deneme ABARTIYOR, 2. deneme (geri bildirimden sonra) SADIK.
        return _nar("Kafein bitkiyi yavas yavas zehirliyor ve oldurur bunu."
                    if cagri["n"] == 1 else
                    "Kafein bitkinin buyumesini engeller, oldurmez bunu.")

    denetim = {"n": 0}

    def _fake_check(topic, *, cover_title, text, language, **kw):
        denetim["n"] += 1
        from short_bot.reel_factcheck import Issue
        if "zehirliyor" in text:
            return [Issue(claim="zehirliyor", problem="Kafein zehirlemez, engeller")]
        return []

    monkeypatch.setattr(RN, "run_json", _fake_run_json)
    monkeypatch.setattr(RN, "check_narration", _fake_check)

    out = RN.write_reel_narration("kafein buyumeyi engeller", channel=_Ch(), seed=1)
    assert "zehirliyor" not in out.full_text(), "abartan senaryo yayına gitti"
    assert denetim["n"] == 2, "kapı yeniden yazdıktan sonra TEKRAR denetlemedi"


def test_IKINCI_denemede_de_gecmezse_URETIM_DURUR(monkeypatch):
    """Yanlış bir video yayınlamak, hiç video yayınlamamaktan KÖTÜDÜR.
    Kanalın otoritesi ürünüdür."""
    import short_bot.reel_narration as RN
    from short_bot.config import ReelConfig
    from short_bot.reel_factcheck import Issue
    from short_bot.reel_models import ReelBeat, ReelNarration

    class _Ch:
        language = "tr"
        reel = ReelConfig(enabled=True, voice_id="v")

    nar = ReelNarration(
        hook="Kahve telvesini bitkine dokme sakin.",
        cover_title="Kahve telvesi tuzagi",
        beats=[ReelBeat(text="Kafein bitkiyi zehirliyor ve oldurur bunu hemen.",
                        visual_query="coffee grounds", keyword="KAHVE"),
               ReelBeat(text="Kokler baskilaniyor ve fide duruyor boylece.",
                        visual_query="seedling soil", keyword="FIDE"),
               ReelBeat(text="Once kompostla sonra topraga ver bunu.",
                        visual_query="compost heap", keyword="KOMPOST")],
        peak_beat=1,
        close="Taze telve genc bitkiye gitmez asla bu yuzden.",
        hook_visual="coffee grounds", close_visual="compost heap", mood="neutral")

    monkeypatch.setattr(RN, "run_json", lambda *a, **kw: nar)
    monkeypatch.setattr(
        RN, "check_narration",
        lambda *a, **kw: [Issue(claim="zehirliyor", problem="yanlış")])

    with pytest.raises(ValueError, match="olgu denetiminden geçemedi"):
        RN.write_reel_narration("kafein buyumeyi engeller", channel=_Ch(), seed=1)


# --- ORANTILILIK: manşet videoyu ÖLDÜRMEZ ----------------------------------
# GERÇEK OLAY: konu "yapraklardaki su damlaları güneşte yakar EFSANESİ YANLIŞ" idi.
# Model manşeti "WASSER TROPFEN GEFAHR GARTEN" yazdı — efsaneyi DOĞRUYMUŞ gibi ilan
# etti. Kapı haklıydı ama tepki ORANTISIZDI: 4 kelimelik bir manşet yüzünden 7
# dakikalık üretim çöpe gitti.

EFSANE_KONU = ("Der Garten-Mythos, Wassertropfen auf Blättern wirkten in der "
               "Mittagssonne wie eine Lupe, ist falsch.")


def test_MANSET_sorunu_URETIMI_OLDURMEZ(monkeypatch):
    """Anlatım sağlamken manşet yüzünden videoyu öldürmek orantısız."""
    import short_bot.reel_narration as RN
    from short_bot.config import ReelConfig
    from short_bot.reel_factcheck import Issue
    from short_bot.reel_models import ReelBeat, ReelNarration

    class _Ch:
        language = "de"
        reel = ReelConfig(enabled=True, voice_id="v")

    nar = ReelNarration(
        hook="Wassertropfen verbrennen keine Blaetter.",
        cover_title="WASSER TROPFEN GEFAHR GARTEN",     # efsaneyi ONAYLIYOR
        beats=[ReelBeat(text="Der Mythos haelt sich seit Jahrzehnten hartnaeckig.",
                        visual_query="water drops leaf", keyword="MYTHOS"),
               ReelBeat(text="Studien zeigen keinerlei Brandflecken auf Blaettern.",
                        visual_query="sunlight leaf", keyword="STUDIE"),
               ReelBeat(text="Die Tropfen verdunsten laengst vor jedem Schaden.",
                        visual_query="evaporation leaf", keyword="VERDUNSTEN")],
        peak_beat=1,
        close="Giess ruhig mittags, deine Blaetter verbrennen nicht.",
        hook_visual="water drops leaf", close_visual="watering garden",
        mood="neutral")

    monkeypatch.setattr(RN, "run_json", lambda *a, **kw: nar)
    # Kapı ısrarla MANŞET sorunu bildiriyor (kind="cover"), olgu sorunu YOK.
    monkeypatch.setattr(
        RN, "check_narration",
        lambda *a, **kw: [Issue(claim="WASSER TROPFEN GEFAHR GARTEN",
                                problem="Manşet efsaneyi onaylıyor, video tersini diyor",
                                kind="cover")])
    monkeypatch.setattr(RN, "rewrite_cover_title", lambda *a, **kw: "DER LUPEN-MYTHOS")

    out = RN.write_reel_narration(EFSANE_KONU, channel=_Ch(), seed=1)
    assert out.cover_title == "DER LUPEN-MYTHOS", "manşet yenilenmedi"
    assert out.full_text(), "video öldürüldü — orantısız"


def test_MANSET_yenilenemezse_BOSALTILIR(monkeypatch):
    """Çelişen bir manşetten, manşetsiz bir kare-sıfır iyidir."""
    import short_bot.reel_narration as RN
    from short_bot.config import ReelConfig
    from short_bot.reel_factcheck import Issue
    from short_bot.reel_models import ReelBeat, ReelNarration

    class _Ch:
        language = "de"
        reel = ReelConfig(enabled=True, voice_id="v")

    nar = ReelNarration(
        hook="Wassertropfen verbrennen keine Blaetter.",
        cover_title="WASSER TROPFEN GEFAHR GARTEN",
        beats=[ReelBeat(text="Der Mythos haelt sich seit Jahrzehnten hartnaeckig.",
                        visual_query="water drops leaf", keyword="MYTHOS"),
               ReelBeat(text="Studien zeigen keinerlei Brandflecken auf Blaettern.",
                        visual_query="sunlight leaf", keyword="STUDIE"),
               ReelBeat(text="Die Tropfen verdunsten laengst vor jedem Schaden.",
                        visual_query="evaporation leaf", keyword="VERDUNSTEN")],
        peak_beat=1,
        close="Giess ruhig mittags, deine Blaetter verbrennen nicht.",
        hook_visual="water drops leaf", close_visual="watering garden",
        mood="neutral")

    monkeypatch.setattr(RN, "run_json", lambda *a, **kw: nar)
    monkeypatch.setattr(
        RN, "check_narration",
        lambda *a, **kw: [Issue(claim="x", problem="çelişiyor", kind="cover")])
    monkeypatch.setattr(RN, "rewrite_cover_title", lambda *a, **kw: "")

    out = RN.write_reel_narration(EFSANE_KONU, channel=_Ch(), seed=1)
    assert out.cover_title == ""
    assert out.full_text(), "video öldürüldü"


def test_OLGU_sorunu_ISRAR_EDERSE_URETIM_DURUR(monkeypatch):
    """Anlatımdaki olgusal hata ciddi — orada durmak DOĞRU."""
    import short_bot.reel_narration as RN
    from short_bot.config import ReelConfig
    from short_bot.reel_factcheck import Issue
    from short_bot.reel_models import ReelBeat, ReelNarration

    class _Ch:
        language = "tr"
        reel = ReelConfig(enabled=True, voice_id="v")

    nar = ReelNarration(
        hook="Kahve telvesini bitkine dokme sakin.",
        cover_title="Kahve telvesi tuzagi",
        beats=[ReelBeat(text="Kafein bitkiyi zehirliyor ve oldurur bunu hemen.",
                        visual_query="coffee grounds", keyword="KAHVE"),
               ReelBeat(text="Kokler baskilaniyor ve fide duruyor boylece.",
                        visual_query="seedling soil", keyword="FIDE"),
               ReelBeat(text="Once kompostla sonra topraga ver bunu.",
                        visual_query="compost heap", keyword="KOMPOST")],
        peak_beat=1,
        close="Taze telve genc bitkiye gitmez asla bu yuzden.",
        hook_visual="coffee grounds", close_visual="compost heap", mood="neutral")

    monkeypatch.setattr(RN, "run_json", lambda *a, **kw: nar)
    monkeypatch.setattr(
        RN, "check_narration",
        lambda *a, **kw: [Issue(claim="zehirliyor", problem="yanlış", kind="fact")])

    with pytest.raises(ValueError, match="olgu denetiminden geçemedi"):
        RN.write_reel_narration("kafein buyumeyi engeller", channel=_Ch(), seed=1)


def test_manset_yeniden_uretimi_EFSANEYI_ogretir():
    """Model bir efsaneyi nasıl manşete koyacağını bilmiyordu — öğretiyoruz."""
    from short_bot.reel_factcheck import rewrite_cover_title
    gorulen = {}

    def _llm(prompt, schema):
        gorulen["p"] = prompt
        return schema.model_validate({"cover_title": "DER LUPEN-MYTHOS"})

    out = rewrite_cover_title(
        EFSANE_KONU, text="Die Tropfen verbrennen nichts.",
        bad_title="WASSER TROPFEN GEFAHR GARTEN",
        problem="efsaneyi onaylıyor", language="de", invoke=_llm)
    assert out == "DER LUPEN-MYTHOS"
    p = gorulen["p"]
    assert "EFSANE" in p
    assert "SORGULA" in p
    assert "WASSER TROPFEN GEFAHR GARTEN" in p, "reddedilen manşet gösterilmedi"
    assert "efsaneyi onaylıyor" in p, "red SEBEBİ gösterilmedi"


def test_manset_yeniden_uretimi_PATLARSA_bos_doner():
    from short_bot.reel_factcheck import rewrite_cover_title

    def _patla(*a, **kw):
        raise RuntimeError("model yok")

    assert rewrite_cover_title(EFSANE_KONU, text="x", bad_title="y", problem="z",
                               language="de", invoke=_patla) == ""


def test_ANA_PROMPT_efsane_manset_kuralini_tasir():
    from short_bot.config import ReelConfig
    from short_bot.reel_narration import build_reel_prompt

    class _Ch:
        language = "tr"
        reel = ReelConfig(enabled=True, voice_id="v")

    p = build_reel_prompt("su damlalari yakar efsanesi yanlis", _Ch(), seed=1)
    assert "EFSANEYİ YIKIYORSAN" in p
    assert "SORGULAMAKTAN" in p
