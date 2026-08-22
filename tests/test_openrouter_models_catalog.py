import json
from pathlib import Path


def test_catalog_is_valid_json_with_groups():
    p = Path("config/openrouter_models.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "groups" in data and isinstance(data["groups"], list)
    labels = {g["label"] for g in data["groups"]}
    assert any("Claude" in l for l in labels)
    assert any("Gemini" in l for l in labels)
    assert any("OpenAI" in l for l in labels)
    for g in data["groups"]:
        for m in g["models"]:
            assert "/" in m["id"] and m["label"]


def test_catalog_has_gemma_vision_models():
    import json
    from pathlib import Path
    data = json.loads(Path("config/openrouter_models.json").read_text(encoding="utf-8"))
    ids = [m["id"] for g in data["groups"] for m in g["models"]]
    assert "google/gemma-4-31b-it" in ids


def test_static_catalog_gemma_has_vision_flag():
    import json
    from pathlib import Path
    data = json.loads(Path("config/openrouter_models.json").read_text(encoding="utf-8"))
    by_id = {m["id"]: m for g in data["groups"] for m in g["models"]}
    assert by_id["google/gemma-4-31b-it"].get("vision") is True
