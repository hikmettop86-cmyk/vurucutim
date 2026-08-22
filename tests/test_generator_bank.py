from short_bot.config import load_channel
from short_bot.generator import GeneratorResult, build_generator_prompt

_CH_YAML = """slug: balinalar
name: Balina Dünyası
keywords: [balina, deniz]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#0a2540', accent: '#2de2e6', bg_gradient: ['#0A2540', '#04121F']}
handle: '@balina'
output_dir: output/balinalar
enabled: false
content_source: generator
generator: {topic: 'balinalar hakkında ilginç bilgiler'}
"""


def _channel(tmp_path=None):
    # repo config/channels'a bağımlı DEĞİL (kullanıcı kanal YAML'larını silebilir)
    import tempfile
    from pathlib import Path
    from short_bot.dna import DnaFonts, DnaPalette, DnaSpec, DnaTone
    p = Path(tempfile.mkdtemp()) / "balinalar.yaml"
    p.write_text(_CH_YAML, encoding="utf-8")
    import dataclasses
    ch = load_channel(p)
    dna = DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#0a2540", accent="#2de2e6",
                           bg_gradient=["#0A2540", "#04121F"],
                           body_bg=["#0E2E4D", "#0A2440"]),
        fonts=DnaFonts(headline="Inter", body="Inter"),
        tone=DnaTone(voice="meraklı", style="net"),
        category_icon="🐳",
        persona_summary="balina kanalı",
        search_query_template="{header_top} {header_bottom} whale ocean",
    )
    return dataclasses.replace(ch, dna=dna)


_PROVEN = [{"id": 12, "topic": "Balinalar neden şarkı söyler",
            "views": 2100000, "subs": 15000},
           {"id": 15, "topic": "Orkalar köpekbalığı avlıyor",
            "views": 900000, "subs": 8000}]


def test_prompt_has_proven_block_when_given():
    ch = _channel()
    p = build_generator_prompt(channel=ch, dna=ch.dna, forbidden_texts=[],
                               topic_distribution={}, proven_topics=_PROVEN)
    assert "KANITLANMIŞ KONULAR" in p
    assert "[id=12]" in p and "Balinalar neden şarkı söyler" in p
    assert "2.1M izlenme" in p and "15K abonelik" in p
    assert '"bank_id"' in p


def test_prompt_unchanged_when_bank_empty():
    ch = _channel()
    base = build_generator_prompt(channel=ch, dna=ch.dna, forbidden_texts=[],
                                  topic_distribution={})
    empty = build_generator_prompt(channel=ch, dna=ch.dna, forbidden_texts=[],
                                   topic_distribution={}, proven_topics=[])
    assert base == empty and "KANITLANMIŞ" not in base


def test_prompt_forbids_free_generation_when_bank_full():
    """Kaçış kapısı YOK: banka doluysa seçim zorunlu (halüsinasyon kök nedeni)."""
    ch = _channel()
    p = build_generator_prompt(channel=ch, dna=ch.dna, forbidden_texts=[],
                               topic_distribution={}, proven_topics=_PROVEN)
    assert "ZORUNLU" in p and "null OLAMAZ" in p
    assert "UYDURMA YASAĞI" in p
    assert "serbest üret" not in p.lower()          # eski kaçış kapısı kalmadı


def _fake_result(bank_id):
    from short_bot.generator import GeneratorResult
    return GeneratorResult(
        text="Balinalar okyanusta şarkılarla iletişim kurar bunu biliyor muydun",
        topic_tag="iletisim",
        script={"header_top": "BALİNA ŞARKISI", "header_bottom": "OKYANUS SIRRI",
                "photo_overlay": "derin ses",
                "body_paragraph": "Balinalar okyanusta şarkılarla iletişim kurar "
                                  "bunu biliyor muydun",
                "highlights": [{"text": "şarkılarla", "color": "yellow"}],
                "category": "doğa", "mood": "neutral"},
        image_keywords=["whale ocean"], bank_id=bank_id)


def test_generate_quote_retries_when_bank_ignored(monkeypatch):
    """LLM bankayı yok sayarsa (bank_id=None) düzeltici tekrar yapılır."""
    from short_bot import generator
    calls = []

    def fake_run_json(prompt, schema, **kw):
        calls.append(prompt)
        return _fake_result(None if len(calls) == 1 else 12)
    monkeypatch.setattr(generator, "run_json", fake_run_json)
    ch = _channel()
    out = generator.generate_quote(channel=ch, dna=ch.dna, forbidden_texts=[],
                                   topic_distribution={}, proven_topics=_PROVEN)
    assert len(calls) == 2                       # düzeltici tekrar yapıldı
    assert "HATA:" in calls[1] and "12, 15" in calls[1]
    assert out.bank_id == 12


def test_generate_quote_rejects_hallucinated_bank_id(monkeypatch):
    """Uydurma id (listede yok) → tekrar; yine kötüyse None (mark_used no-op)."""
    from short_bot import generator
    monkeypatch.setattr(generator, "run_json",
                        lambda prompt, schema, **kw: _fake_result(999))
    ch = _channel()
    out = generator.generate_quote(channel=ch, dna=ch.dna, forbidden_texts=[],
                                   topic_distribution={}, proven_topics=_PROVEN)
    assert out.bank_id is None                   # 999 listede yok → temizlendi


def test_generate_quote_no_retry_when_bank_empty(monkeypatch):
    from short_bot import generator
    calls = []
    monkeypatch.setattr(generator, "run_json",
                        lambda prompt, schema, **kw: (calls.append(1),
                                                      _fake_result(None))[1])
    ch = _channel()
    generator.generate_quote(channel=ch, dna=ch.dna, forbidden_texts=[],
                             topic_distribution={}, proven_topics=[])
    assert len(calls) == 1                       # banka boş → tek çağrı


def test_generator_result_bank_id_optional():
    data = {"text": "Balinalar okyanusta şarkılarla iletişim kurar bunu biliyor muydun",
            "topic_tag": "iletisim",
            "script": {"header_top": "BALİNA ŞARKISI", "header_bottom": "OKYANUS SIRRI",
                       "photo_overlay": "derin ses", "body_paragraph":
                       "Balinalar okyanusta şarkılarla iletişim kurar bunu biliyor muydun",
                       "highlights": [{"text": "şarkılarla", "color": "yellow"}],
                       "category": "doğa", "mood": "neutral"},
            "image_keywords": ["whale ocean"]}
    assert GeneratorResult(**data).bank_id is None
    assert GeneratorResult(**data, bank_id=12).bank_id == 12
    assert GeneratorResult(**data, bank_id=None).bank_id is None
