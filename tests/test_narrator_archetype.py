import json
from pathlib import Path

TPL = Path("templates/narrator.html.j2")


def test_narrator_template_exists():
    assert TPL.exists()


def test_narrator_registered_in_archetypes_json():
    data = json.loads(Path("config/archetypes.json").read_text(encoding="utf-8"))
    entry = next((a for a in data if a["slug"] == "narrator"), None)
    assert entry is not None, "narrator archetypes.json'da kayitli degil"
    assert entry["defaults"]["colors"]["primary"]
    assert entry["defaults"]["font_headline"]
    assert entry["pexels_queries"]


def test_narrator_prompt_generated_for_script_writer():
    """Designed arketip oldugu icin script_writer promptu otomatik olusur."""
    from short_bot.script_writer import ARCHETYPE_PROMPTS
    assert "narrator" in ARCHETYPE_PROMPTS


def test_narrator_in_dna_archetypes():
    from short_bot.dna import ARCHETYPES
    assert "narrator" in ARCHETYPES


def test_template_has_seek_lead_and_progress():
    html = TPL.read_text(encoding="utf-8")
    assert "window.__seek" in html
    assert "LEAD_MS" in html          # kelime konusulmadan once yanar
    assert "__progress" in html       # ilerleme cubugu elemani
