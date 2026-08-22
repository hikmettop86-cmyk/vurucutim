from short_bot.config import load_channel
from short_bot.reel_narration import build_reel_prompt
from short_bot.youtube.metadata_writer import build_metadata_prompt

_PATS = ["sayı + beklenmedik iddia", "merak sorusu"]

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
reel:
  enabled: true
  voice_id: test-voice
"""


def _channel():
    # repo config/channels'a bağımlı DEĞİL (kullanıcı kanal YAML'larını silebilir)
    import tempfile
    from pathlib import Path
    p = Path(tempfile.mkdtemp()) / "balinalar.yaml"
    p.write_text(_CH_YAML, encoding="utf-8")
    return load_channel(p)


def test_reel_prompt_hook_patterns_block():
    ch = _channel()
    base = build_reel_prompt("balina göçü", ch)
    with_p = build_reel_prompt("balina göçü", ch, hook_patterns=_PATS)
    assert base == build_reel_prompt("balina göçü", ch, hook_patterns=[])  # boş → aynı
    assert "sayı + beklenmedik iddia" in with_p
    assert "KANITLANMIŞ HOOK" in with_p


def test_metadata_prompt_hook_patterns_and_ctr():
    ch = _channel()
    script = {"header_top": "BALİNA", "header_bottom": "GÖÇÜ",
              "body_paragraph": "gövde", "category": "doğa"}
    base = build_metadata_prompt(channel=ch, script=script,
                                 rss_source=None, rss_link=None)
    with_p = build_metadata_prompt(channel=ch, script=script,
                                   rss_source=None, rss_link=None,
                                   hook_patterns=_PATS)
    assert base == build_metadata_prompt(channel=ch, script=script,
                                         rss_source=None, rss_link=None,
                                         hook_patterns=None)
    assert "merak sorusu" in with_p
    assert "İlk 3 kelime" in with_p          # CTR kuralı bloğu


def test_reel_prompt_forbids_metaphor_visual_queries():
    """METAFOR YASAĞI: anlatım metafor kullanabilir ama görsel sorgu videonun
    BİREBİR öznesini tarif etmeli. Gerçek hata: 'görünmez savaşçılar'
    (=bakteriyofaj) → sorgu 'invisible warrior' → stok kütüphane ESKRİMCİ döndürdü."""
    ch = _channel()
    p = build_reel_prompt("bakteriyofajlar", ch)
    assert "METAFOR YASAĞI" in p
    assert "ESKRİMCİ" in p or "eskrimci" in p.lower()
    assert "bacteriophage" in p          # doğru örnek prompt'ta
