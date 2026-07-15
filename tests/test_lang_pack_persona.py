"""LangPack.personas — dile özel persona metinleri (few_shot + rules)."""


def test_langpack_personas_alani():
    from short_bot.lang_pack import LangPack
    assert "personas" in LangPack.model_fields


def test_tr_paketinde_vahsi_mizah_var():
    from short_bot.lang_pack import load_pack
    pack = load_pack("tr")
    p = pack.personas["vahsi_mizah"]
    assert p["few_shot"].strip()
    assert len(p["rules"]) >= 5


def test_validate_persona_bos_few_shot_yakalar():
    from short_bot.lang_pack import load_pack, validate_pack
    base = load_pack("tr").model_copy(deep=True)
    base.personas = {"vahsi_mizah": {"few_shot": "", "rules": ["x"]}}
    hatalar = validate_pack(base)
    assert any("few_shot" in h for h in hatalar)


def test_validate_persona_bos_rules_yakalar():
    from short_bot.lang_pack import load_pack, validate_pack
    base = load_pack("tr").model_copy(deep=True)
    base.personas = {"vahsi_mizah": {"few_shot": "dolu", "rules": []}}
    hatalar = validate_pack(base)
    assert any("rules" in h for h in hatalar)
