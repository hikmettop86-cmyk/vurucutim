from short_bot.reel_director import EditPlan, plan_edit, validate_plan

_LIB = {"sfx": {"whoosh": ["a.mp3"], "impact": ["b.mp3"], "cinematic": ["c.mp3"]},
        "music": {"tense": ["t.mp3"], "calm": ["c.mp3"]}}


def test_validate_keeps_valid_fields():
    p = EditPlan(mood="tense", cut_effect="glitch", music_mood="tense",
                 sfx_plan=["whoosh", "impact"], reason="r")
    v = validate_plan(p, library_index=_LIB, n_cuts=2)
    assert v.mood == "tense" and v.cut_effect == "glitch"
    assert v.music_mood == "tense" and v.sfx_plan == ["whoosh", "impact"]


def test_validate_clears_hallucinated_values():
    """LLM uydurma değer üretirse o alan BOŞALIR → çağıran seed-hash'e düşer."""
    p = EditPlan(cut_effect="explode", music_mood="jazz",
                 sfx_plan=["airhorn", "whoosh"])
    v = validate_plan(p, library_index=_LIB, n_cuts=2)
    assert v.cut_effect == ""                                 # havuzda yok
    assert v.music_mood == ""                                 # kütüphanede jazz yok
    assert v.sfx_plan == ["whoosh", "whoosh"]                 # airhorn elendi, döngü


def test_mode_collapse_fields_are_always_left_to_seed_hash():
    """cut_pacing/layout/marker_kit kurgucuya SORULMAZ — LLM doldursa bile boşalır.

    Canlı ölçüm (3 zıt konu): flash-lite tempoda 3/3 "medium", layout'ta 2/2
    "classic", marker'da 2/2 "spotlight" dedi. Ayrım yapamadığı alanda bilgi
    katmaz, yalnız yanlılık katar — ve her video aynı değeri alır, yani tam da
    kırmak istediğimiz parmak izini üretir. Seed-hash orada çeşitliliği GARANTİ eder.
    """
    p = EditPlan(cut_pacing="fast", layout="top_heavy", marker_kit=["ring", "pulse"])
    v = validate_plan(p, library_index=_LIB, n_cuts=2)
    assert v.cut_pacing == "" and v.layout == "" and v.marker_kit == []


def test_prompt_does_not_ask_for_mode_collapse_fields(monkeypatch):
    """Sormadığımız alanı prompt'ta da SUNMAYIZ — token ve yanlılık israfı."""
    import short_bot.reel_director as rd
    seen = {}

    def fake(prompt, schema, **kw):
        seen["p"] = prompt
        return EditPlan()
    monkeypatch.setattr(rd, "run_json", fake)

    class _N:
        hook = "h"; close = "c"
        beats = [type("B", (), {"text": "t"})()]

    class _VC:
        claude_path = "c"; model = "m"; backend = "openrouter"; api_key = "k"

    plan_edit(_N(), topic="k", n_cuts=3, library_index=_LIB, llm_call=_VC())
    assert "cut_pacing" not in seen["p"] and "layout" not in seen["p"]
    assert "marker_kit" not in seen["p"]
    assert "cut_effect" in seen["p"] and "music_mood" in seen["p"]


def test_validate_normalizes_sfx_plan_length():
    p = EditPlan(sfx_plan=["whoosh", "impact"])
    # kısa plan → döngüyle tamamlanır
    v = validate_plan(p, library_index=_LIB, n_cuts=5)
    assert v.sfx_plan == ["whoosh", "impact", "whoosh", "impact", "whoosh"]
    # uzun plan → kırpılır
    p2 = EditPlan(sfx_plan=["whoosh"] * 9)
    assert len(validate_plan(p2, library_index=_LIB, n_cuts=3).sfx_plan) == 3
    # hiç geçerli kategori yoksa boş (çağıran eski davranışa düşer)
    p3 = EditPlan(sfx_plan=["airhorn"])
    assert validate_plan(p3, library_index=_LIB, n_cuts=3).sfx_plan == []


def test_plan_edit_calls_llm_and_validates(monkeypatch):
    import short_bot.reel_director as rd

    class _VC:
        claude_path = "claude"; model = "flash-lite"; backend = "openrouter"
        api_key = "k"

    seen = {}

    def fake_run_json(prompt, schema, **kw):
        seen["prompt"] = prompt
        return EditPlan(mood="dark", cut_effect="lightleak", music_mood="tense",
                        sfx_plan=["impact", "airhorn"],
                        reason="konu karanlık ve ağır")
    monkeypatch.setattr(rd, "run_json", fake_run_json)

    class _N:
        hook = "Merak uyandiran soru"
        close = "Kapanis"
        mood = "neutral"
        beats = [type("B", (), {"text": "Beat bir"})(),
                 type("B", (), {"text": "Beat iki"})()]

    out = plan_edit(_N(), topic="karanlık konu", n_cuts=3,
                    library_index=_LIB, llm_call=_VC())
    assert out is not None
    assert out.cut_effect == "lightleak" and out.music_mood == "tense"
    assert out.sfx_plan == ["impact", "impact", "impact"]   # airhorn elendi + döngü
    # prompt kütüphanenin KATEGORİLERİNİ içermeli (dosya adlarını DEĞİL)
    assert "whoosh" in seen["prompt"] and "impact" in seen["prompt"]
    assert "a.mp3" not in seen["prompt"]
    assert "Beat bir" in seen["prompt"]      # anlatım bağlamı verildi


def test_plan_edit_returns_none_on_llm_error(monkeypatch):
    import short_bot.reel_director as rd

    def boom(*a, **kw):
        raise RuntimeError("llm patladı")
    monkeypatch.setattr(rd, "run_json", boom)

    class _N:
        hook = "h"; close = "c"; mood = "neutral"
        beats = [type("B", (), {"text": "t"})()]

    assert plan_edit(_N(), topic="k", n_cuts=2, library_index=_LIB,
                     llm_call=object()) is None


def test_plan_edit_skipped_without_library():
    class _N:
        hook = "h"; close = "c"; mood = "neutral"
        beats = [type("B", (), {"text": "t"})()]
    assert plan_edit(_N(), topic="k", n_cuts=2, library_index={"sfx": {}, "music": {}},
                     llm_call=object()) is None


def test_channel_music_folders_are_not_offered_as_moods(monkeypatch):
    """assets/music/<kanal-slug>/ bir RUH HALİ DEĞİL — pick_music orayı kanal
    klasörü olarak kullanır. Kurgucu bir bilim videosuna kanal marşı seçemez."""
    import short_bot.reel_director as rd

    lib = {"sfx": {"whoosh": ["a.mp3"]},
           "music": {"tense": ["t.mp3"], "galatasaray": ["marş.mp3"]}}

    # 1) Doğrulama: kanal klasörünü ruh hali diye kabul ETMEZ
    assert validate_plan(EditPlan(music_mood="galatasaray"),
                         library_index=lib, n_cuts=2).music_mood == ""
    assert validate_plan(EditPlan(music_mood="tense"),
                         library_index=lib, n_cuts=2).music_mood == "tense"

    # 2) Prompt: kanal klasörünü kurgucuya SUNMAZ
    seen = {}

    def fake_run_json(prompt, schema, **kw):
        seen["prompt"] = prompt
        return EditPlan(music_mood="tense")
    monkeypatch.setattr(rd, "run_json", fake_run_json)

    class _N:
        hook = "h"; close = "c"; mood = "neutral"
        beats = [type("B", (), {"text": "t"})()]

    class _VC:
        claude_path = "claude"; model = "m"; backend = "openrouter"; api_key = "k"

    plan_edit(_N(), topic="bilim", n_cuts=2, library_index=lib, llm_call=_VC())
    assert "tense" in seen["prompt"] and "galatasaray" not in seen["prompt"]
