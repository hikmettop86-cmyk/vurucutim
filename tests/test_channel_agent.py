"""Kanal planı: kullanıcı GÖRMEDEN hiçbir şey yazılmaz.

build_plan HİÇBİR DOSYA YAZMAZ (dil paketi hariç — o dile ait, kanala değil).
Kullanıcı planı görüp "Kur"a basar; apply_plan yazar.

NEDEN BU AYRIM: ajan yanlış ses seçer, ismi tutmaz ya da niş kaymışsa, kullanıcı bunu
KANAL KURULMADAN görmeli. Kurulmuş bir kanalı geri almak (YAML sil, banka temizle,
CSS sil) kullanıcının işi olmamalı.
"""
import pytest

from short_bot.channel_agent import ChannelPlan, apply_plan, build_plan
from short_bot.dna import DnaFonts, DnaPalette, DnaSpec, DnaTone


def _dna(archetype="stat-hero"):
    return DnaSpec(
        archetype=archetype,
        palette=DnaPalette(primary="#0a2540", accent="#2de2e6",
                           bg_gradient=["#0A2540", "#04121F"],
                           body_bg=["#0A2540", "#04121F"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="net anlatıcı", style="merak uyandıran"),
        persona_summary="bira meraklısı anlatıcı")


class _Settings:
    claude_cli_path = "claude"
    openrouter_models = {"script": "anthropic/claude-sonnet-5",
                         "dna": "anthropic/claude-opus-4.8"}
    ai_backend = "openrouter"
    claude_models = {"dna": "opus", "default": "haiku"}


def _llm(**cevaplar):
    """Sahte Sonnet: şema adına göre farklı cevap döndürür."""
    def _f(prompt, schema, **kw):
        ad = schema.__name__
        if ad == "_Niche":                     # niş temizliği
            return schema.model_validate(cevaplar.get("niche", {
                "niche": "Überraschende Fakten über Bier und Brauerei"}))
        if ad == "_Pick":                      # voice_picker
            return schema.model_validate(cevaplar.get("voice", {
                "voice_id": "elevenlabs_de1", "reason": "anlatıcı tonu"}))
        if ad == "_Name":                      # kanal adı
            return schema.model_validate(cevaplar.get("name", {"name": "Bierwissen"}))
        if ad == "_Verdicts":                  # doğrulama kapısı
            n = len(cevaplar.get("topics", {}).get(
                "topics", [{"topic": "Bier braucht neun Monate im Keller"}]))
            return schema.model_validate({"verdicts": [
                {"index": i, "solid": True} for i in range(n)]})
        if ad == "_Proposed":                  # konu önerisi
            return schema.model_validate(cevaplar.get("topics", {"topics": [
                {"topic": "Bier braucht neun Monate im Keller", "source_title": "",
                 "views": 0, "subs": 0, "hook_pattern": ""}]}))
        raise AssertionError(f"beklenmeyen şema: {ad}")
    return _f


DE_VOICES = [{"voice_id": "elevenlabs_de1", "name": "Daniel - Teacher",
              "description": "calm narrator", "language": "de", "gender": "male",
              "accent": "german"}]


@pytest.fixture
def _sahte(monkeypatch, tmp_path):
    """Dış dünyayı kes: ses listesi + DNA. (Dil paketi 'de' zaten kodla geliyor.)"""
    import short_bot.channel_agent as CA
    monkeypatch.setattr(CA, "voices_for", lambda lang, **kw: DE_VOICES)
    monkeypatch.setattr(CA, "generate_dna", lambda **kw: _dna())
    kanallar = tmp_path / "channels"
    kanallar.mkdir()
    return kanallar


# --- NİŞ TEMİZLİĞİ ---------------------------------------------------------
# GERÇEK HATA (ilk canlı koşu): kullanıcı "Almanca bahçe ile ilgilenen insanların
# bahçecilik üzerine merak uyandıran niş bir short kanal kurmak istiyorum" yazdı ve bu
# cümle olduğu gibi generator.topic'e kaydedildi. YouTube arama sorgusu
# "Almanca bahce ile" oldu — hiçbir şey bulamaz. O kanalda kanıt madenciliği KALICI
# OLARAK ÖLÜ. İnsan doğal olarak İSTEĞİNİ yazar, nişini değil.

def test_HAM_ISTEK_temiz_NISE_cevrilir(_sahte):
    ham = ("Almanca bahce ile ilgilenen insanlarin bahcecilik uzerine merak "
           "uyandiran nis bir short kanal kurmak istiyorum")
    p = build_plan(ham, language="de", channels_dir=_sahte, ai33_key="K",
                   settings=_Settings(), secrets={},
                   llm=_llm(niche={"niche": "Überraschende Fakten über Gartenpflanzen"}))
    assert p.niche == "Überraschende Fakten über Gartenpflanzen"
    assert "kurmak istiyorum" not in p.niche, "ham istek nişe sızdı"
    # HAM CÜMLE de saklanır — kullanıcı ne yazdığını planda görsün.
    assert p.intent == ham


def test_TEMIZ_NIS_generator_topic_olur(_sahte, tmp_path):
    """Kanal YAML'ına TEMİZ niş yazılmalı — YouTube sorgusu ondan türetiliyor."""
    from short_bot.config import load_channel
    p = build_plan("bahce ile ilgili kanal kurmak istiyorum", language="de",
                   channels_dir=_sahte, ai33_key="K", settings=_Settings(),
                   secrets={},
                   llm=_llm(niche={"niche": "Überraschende Fakten über Gartenpflanzen"}))
    slug = apply_plan(p, channels_dir=_sahte, templates_dir=tmp_path / "t",
                      db_path=tmp_path / "db.sqlite", settings=_Settings(),
                      secrets={}, llm=_llm())
    cfg = load_channel(_sahte / f"{slug}.yaml")
    assert cfg.generator.topic == "Überraschende Fakten über Gartenpflanzen"


def test_nis_TEMIZLENEMEZSE_ham_metin_kullanilir(_sahte, monkeypatch):
    """Temizleme kanalı bozmaz — LLM patlarsa ham metinle devam."""
    import short_bot.channel_agent as CA
    monkeypatch.setattr(CA, "_normalize_niche",
                        lambda intent, lang, llm: intent)
    p = build_plan("bahce ile ilgili kanal kurmak istiyorum", language="de",
                   channels_dir=_sahte, ai33_key="K", settings=_Settings(),
                   secrets={}, llm=_llm())
    assert p.niche == "bahce ile ilgili kanal kurmak istiyorum"


def test_nis_temizligi_HEDEF_DILI_ister():
    """Niş HEDEF DİLDE olmalı: arama sorguları ondan türetiliyor, Türkçe bir cümle
    Almanca aramada hiçbir şey bulmaz."""
    import short_bot.channel_agent as CA
    gorulen = {}

    def _llm2(prompt, schema, **kw):
        gorulen["p"] = prompt
        return schema.model_validate({"niche": "Fakten über Gärten"})

    CA._normalize_niche("bahce kanali istiyorum", "de", _llm2)
    p = gorulen["p"]
    assert "Deutsch" in p
    assert "arama sorguları" in p          # NEDEN hedef dil, prompt'ta yazıyor


# --- build_plan: HİÇBİR ŞEY YAZMAZ -----------------------------------------

def test_plan_TUM_ALANLARI_doldurur(_sahte):
    p = build_plan("bira bahcesi kulturu ve bira uretimi", language="de",
                   channels_dir=_sahte, ai33_key="K", settings=_Settings(),
                   secrets={}, llm=_llm(), evidence="8 outlier; en iyi 175x")
    assert isinstance(p, ChannelPlan)
    assert p.language == "de"
    assert p.niche == "Überraschende Fakten über Bier und Brauerei"
    assert p.name == "Bierwissen"
    assert p.slug == "bierwissen"
    assert p.voice.voice_id == "elevenlabs_de1"
    assert p.voice.reason, "ses GEREKÇESİ boş — kullanıcı neden bu ses bilmeli"
    assert p.dna.archetype == "stat-hero"
    assert p.evidence == "8 outlier; en iyi 175x"
    assert p.sample_topics == ["Bier braucht neun Monate im Keller"]


def test_plan_HICBIR_DOSYA_YAZMAZ(_sahte):
    build_plan("bira bahcesi kulturu", language="de", channels_dir=_sahte,
               ai33_key="K", settings=_Settings(), secrets={}, llm=_llm())
    assert list(_sahte.glob("*.yaml")) == [], "build_plan kanal YAML'ı yazdı"


def test_KANIT_YOKSA_UYDURMAZ(_sahte):
    """YouTube ölçümü yoksa evidence BOŞ kalır — panel 'kanıt yok' der."""
    p = build_plan("bira bahcesi kulturu", language="de", channels_dir=_sahte,
                   ai33_key="K", settings=_Settings(), secrets={}, llm=_llm())
    assert p.evidence == ""


def test_SLUG_cakismasi_cozulur(_sahte):
    (_sahte / "bierwissen.yaml").write_text("x", encoding="utf-8")
    p = build_plan("bira bahcesi kulturu", language="de", channels_dir=_sahte,
                   ai33_key="K", settings=_Settings(), secrets={}, llm=_llm())
    assert p.slug == "bierwissen-2"


def test_KISA_nis_reddedilir(_sahte):
    with pytest.raises(ValueError, match="10 karakter"):
        build_plan("bira", language="de", channels_dir=_sahte, ai33_key="K",
                   settings=_Settings(), secrets={}, llm=_llm())


def test_ORNEK_KONULAR_DOGRULAMA_kapisindan_gecer(_sahte):
    """Planda gösterilen konular GERÇEK — propose + verify'den geçmiş."""
    llm = _llm(topics={"topics": [
        {"topic": "Saglam konu bir", "source_title": "", "views": 0, "subs": 0,
         "hook_pattern": ""},
        {"topic": "Saglam konu iki", "source_title": "", "views": 0, "subs": 0,
         "hook_pattern": ""}]})
    p = build_plan("bira bahcesi kulturu", language="de", channels_dir=_sahte,
                   ai33_key="K", settings=_Settings(), secrets={}, llm=llm)
    assert p.sample_topics == ["Saglam konu bir", "Saglam konu iki"]


def test_ORNEK_KONU_URETILEMEZSE_plan_YINE_kurulur(_sahte, monkeypatch):
    """Konu üretimi patlarsa kanal yine kurulabilmeli — banka sonra dolar."""
    import short_bot.channel_agent as CA

    def _patla(*a, **kw):
        raise RuntimeError("sonnet yok")

    monkeypatch.setattr(CA, "propose_topics", _patla)
    p = build_plan("bira bahcesi kulturu", language="de", channels_dir=_sahte,
                   ai33_key="K", settings=_Settings(), secrets={}, llm=_llm())
    assert p.sample_topics == []
    assert p.slug                              # plan YİNE kuruldu


def test_HEDEF_DILDE_SES_YOKSA_plan_KURULMAZ(_sahte, monkeypatch):
    """SESSİZ BOZULMA YASAĞI: kanalı bozuk kurmaktansa kurmamak yeğdir."""
    import short_bot.channel_agent as CA

    def _yok(lang, **kw):
        raise RuntimeError("Almanca konuşan ses bulunamadı")

    monkeypatch.setattr(CA, "voices_for", _yok)
    with pytest.raises(RuntimeError, match="ses"):
        build_plan("bira bahcesi kulturu", language="de", channels_dir=_sahte,
                   ai33_key="K", settings=_Settings(), secrets={}, llm=_llm())


# --- apply_plan: PLANI GERÇEĞE ÇEVİR ---------------------------------------

def _plan(_sahte, llm=None):
    return build_plan("bira bahcesi kulturu", language="de", channels_dir=_sahte,
                      ai33_key="K", settings=_Settings(), secrets={},
                      llm=llm or _llm())


def _apply(p, _sahte, tmp_path, **kw):
    return apply_plan(p, channels_dir=_sahte, templates_dir=tmp_path / "t",
                      db_path=tmp_path / "db.sqlite", settings=_Settings(),
                      secrets={}, llm=_llm(), **kw)


def test_apply_KANAL_YAMLINI_yazar(_sahte, tmp_path):
    from short_bot.config import load_channel
    p = _plan(_sahte)
    slug = _apply(p, _sahte, tmp_path)
    assert slug == p.slug
    cfg = load_channel(_sahte / f"{slug}.yaml")
    assert cfg.language == "de"
    assert cfg.reel.voice_id == "elevenlabs_de1"
    # NİŞ TEMİZLENMİŞ hâliyle yazılır (ham istek değil).
    assert cfg.generator.topic == "Überraschende Fakten über Bier und Brauerei"
    assert cfg.template == "stat-hero"
    assert cfg.enabled is True


def test_apply_AUTOPILOT_ACMAZ(_sahte, tmp_path):
    """YouTube'a otomatik yükleme BÜYÜK bir taahhüt — kullanıcı bilinçli açar."""
    from short_bot.config import load_channel
    p = _plan(_sahte)
    slug = _apply(p, _sahte, tmp_path)
    cfg = load_channel(_sahte / f"{slug}.yaml")
    ap = getattr(cfg, "autopilot", None)
    assert ap is None or ap.enabled is False


def test_apply_SERIYI_KAPALI_kurar(_sahte, tmp_path):
    from short_bot.config import load_channel
    p = _plan(_sahte)
    slug = _apply(p, _sahte, tmp_path)
    assert load_channel(_sahte / f"{slug}.yaml").reel.series_enabled is False


def test_apply_KONU_BANKASINI_tohumlar(_sahte, tmp_path, monkeypatch):
    import short_bot.channel_agent as CA
    cagri = {}

    def _fake_refresh(eng, slug, niche, **kw):
        cagri.update(slug=slug, niche=niche, llm=kw.get("llm"))
        return {"added": 5, "skipped_dup": 0, "rejected": 0}

    monkeypatch.setattr(CA, "refresh_topic_bank", _fake_refresh)
    p = _plan(_sahte)
    _apply(p, _sahte, tmp_path)
    assert cagri["slug"] == p.slug
    assert cagri["niche"] == "Überraschende Fakten über Bier und Brauerei", \
        "banka HAM istekle değil TEMİZ nişle tohumlanmalı"
    assert cagri["llm"] is not None, "banka SONNET ile tohumlanmalı"


def test_apply_BANKA_PATLASA_da_kanal_KURULUR(_sahte, tmp_path, monkeypatch):
    """YAML yazıldıysa kanal VARDIR. Banka 4 saatte bir kendini doldurur."""
    import short_bot.channel_agent as CA

    def _patla(*a, **kw):
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(CA, "refresh_topic_bank", _patla)
    p = _plan(_sahte)
    slug = _apply(p, _sahte, tmp_path)
    assert (_sahte / f"{slug}.yaml").exists()


def test_apply_CSS_override_yazar(_sahte, tmp_path):
    """Arketip önizlemesi için (sihirbazla parite)."""
    p = _plan(_sahte)
    slug = _apply(p, _sahte, tmp_path)
    assert (tmp_path / "t" / "css" / f"{slug}.css").exists()
