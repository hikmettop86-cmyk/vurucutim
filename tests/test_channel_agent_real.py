"""GERÇEK Sonnet + GERÇEK ai33 ile KALİTE KAPISI.

Diğer testler sahte LLM kullanır — akışı kanıtlarlar, KALİTEYİ değil.
Bu dosya ajanın gerçekten çalışan bir Almanca kanal planı kurduğunu kanıtlar.

ÖLÇÜLDÜ (ilk gerçek koşu):
    kanal adı : Hopfenrausch
    ses       : Peter - Deep, calm German narrator
    gerekçe   : "sakin, derin dokümanter anlatıcı tonu... satış/reklam havasına
                 kaçmadan"
    konu      : "Am 4. Januar 1812 verbot König Maximilian I. von Bayern den
                 Bierkellern, Speisen zu verkaufen – seitdem bringen Gäste im
                 Biergarten bis heute ihre eigene Brotzeit mit."

YAVAŞ (~3-5 dk) ve gerçek API kotası harcar. Kırılırsa KODU düzelt, testi değil.
"""
from pathlib import Path

import pytest
import yaml

from short_bot.channel_agent import build_plan
from short_bot.config import load_settings
from short_bot.llm_sonnet import sonnet_json
from short_bot.tts.ai33_client import resolve_ai33_api_key
from short_bot.voice_picker import voices_for


def _sonnet(prompt, schema, **kw):
    return sonnet_json(prompt, schema)


@pytest.mark.slow
def test_ALMANCA_kanal_plani_GERCEKTEN_kurulur(tmp_path):
    settings = load_settings(Path("config/settings.yaml"))
    sp = Path("data/secrets.yaml")
    if not sp.exists():
        pytest.skip("secrets.yaml yok")
    secrets = yaml.safe_load(sp.read_text(encoding="utf-8")) or {}
    ai33 = resolve_ai33_api_key(secrets)
    if not ai33:
        pytest.skip("ai33 anahtarı yok")

    p = build_plan(
        "bira bahcesi kulturu ve bira uretiminin sasirtici gercekleri",
        language="de", channels_dir=tmp_path, ai33_key=ai33,
        settings=settings, secrets=secrets, llm=_sonnet)

    # SES: ALMANCA konuşan bir ses olmalı — İngilizceye DÜŞMEMELİ.
    de_ids = {v["voice_id"] for v in voices_for("de", api_key=ai33)}
    assert p.voice.voice_id in de_ids, \
        f"seçilen ses Almanca değil: {p.voice.voice_id} ({p.voice.name})"
    assert p.voice.reason, "ses gerekçesi boş — kullanıcı neden bu ses bilmeli"

    # İSİM + KİMLİK
    assert p.name and len(p.name) <= 40
    assert p.slug
    assert p.dna.archetype

    # ÖRNEK KONULAR: Almanca ve somut
    assert len(p.sample_topics) >= 2, f"yalnız {len(p.sample_topics)} konu üretildi"
    birlesik = " ".join(p.sample_topics)
    assert "ABONE" not in birlesik.upper(), "Türkçe sızıntı"
    assert any(x in birlesik.lower() for x in
               ("bier", " die ", " der ", " das ", "ä", "ö", "ü", "ß")), \
        "konular Almanca görünmüyor"

    # KANIT UYDURULMAZ: niş bulucu koşmadı → evidence BOŞ.
    assert p.evidence == ""

    # HİÇBİR DOSYA YAZILMAMIŞ olmalı — kullanıcı planı görüp onaylayacak.
    assert list(tmp_path.glob("*.yaml")) == [], "build_plan kanal YAML'ı yazdı"
