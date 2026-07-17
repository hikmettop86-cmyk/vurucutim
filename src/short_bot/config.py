"""YAML config loader for global settings and per-channel configs."""
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


def _default_trends_settings() -> "TrendsSettings":
    return TrendsSettings(
        enabled=False, refresh_minutes=60,
        default_sources=("google_daily", "youtube"),
        cache_max_age_minutes=90.0,
    )

from short_bot.dna import DnaSpec
from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES

SLUG_RE = re.compile(r"^[a-z0-9\-]+$")


@dataclass(frozen=True)
class TrendsSettings:
    enabled: bool
    refresh_minutes: int
    default_sources: tuple[str, ...]
    cache_max_age_minutes: float


@dataclass(frozen=True)
class Settings:
    ffmpeg_path: str
    claude_cli_path: str
    playwright_browser: str
    web_host: str
    web_port: int
    fuzzy_dedup_threshold: float
    log_level: str
    claude_models: dict
    ai_backend: str = "claude_cli"
    openrouter_models: dict = field(default_factory=dict)
    google_studio: dict = field(default_factory=dict)
    trends: TrendsSettings = field(default_factory=_default_trends_settings)
    whisper_quality: str = "auto"
    whisper_device: str = "auto"
    footage_priority: list = field(default_factory=lambda: ["pexels"])


@dataclass(frozen=True)
class GeneratorConfig:
    topic: str
    forbidden_lookback: int = 50
    max_retries: int = 3
    fuzzy_threshold: float | None = None


class YoutubeChannelConfig(BaseModel):
    auto_upload: bool = False
    ai_content: bool = True
    category_id: str = "24"
    privacy_status: Literal["public", "unlisted", "private"] = "public"
    min_score_for_upload: float = Field(default=8.0, ge=0.0, le=10.0)
    cron_preset: str | None = None


class AutopilotConfig(BaseModel):
    """Otomatik üretim + zamanlı yükleme (bkz. autopilot.py).

    VARSAYILAN KAPALI ve bu KASITLI: açık gelen bir otomasyon, kullanıcının hiç
    istemediği videoları hiç istemediği saatlerde yayınlar. Kapalıyken hiçbir davranış
    değişmez — mevcut cron + anında yükleme aynen sürer (tam geriye uyum).
    """
    enabled: bool = False
    daily_count: int = Field(default=3, ge=1, le=12)
    active_hours: tuple[int, int] = (10, 22)
    timezone: str = "Europe/Istanbul"
    jitter_minutes: int = Field(default=15, ge=0, le=120)
    jitter_step: int = Field(default=6, ge=1, le=60)
    # Üretim ~15 dk sürüyor; 1 saat lead güvenli bir tampon bırakır. Panelden artırılır.
    produce_lead_hours: int = Field(default=1, ge=1, le=12)
    publish_mode: Literal["publish_at", "live_upload"] = "publish_at"
    max_attempts: int = Field(default=3, ge=1, le=5)
    # GÜNDE KAÇ SERİ BÖLÜMÜ. Varsayılan 1 ve bu KRİTİK:
    #
    # Seri bölümü izleyiciye "#2 YARIN" diye söz veriyor (abone çipi). Günde 3 bölüm
    # üretilirse 3 bölümlük ark BİR GÜNDE biter ve #2 aynı gün yayınlanır — söz YALAN
    # olur, abone takası çöker ve Faz 3'ün bütün mekanizması anlamsızlaşır.
    #
    # Kalan slotlar bankadan BAĞIMSIZ konu üretir (seri ilerlemez, ark tüketilmez).
    # 0 = hiç seri bölümü üretme (otomasyon seriyi ilerletmez).
    series_per_day: int = Field(default=1, ge=0, le=3)

    @field_validator("timezone")
    @classmethod
    def _tz_gecerli(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as e:
            raise ValueError(f"geçersiz saat dilimi: {v!r}") from e
        return v

    @model_validator(mode="after")
    def _tutarli(self):
        lo, hi = self.active_hours
        if not (0 <= lo < hi <= 24):
            raise ValueError("active_hours [başlangıç, bitiş] ve başlangıç < bitiş olmalı")
        # SLOTLAR SIĞMALI. Sığmazsa MIN_SLOT_GAP_MIN koruması slotları üst üste iter,
        # son slotlar aktif saatlerin dışına taşar ve jitter tamamen anlamsızlaşır.
        # Bu sessiz bir bozulma olurdu — baştan reddet.
        from short_bot.autopilot import MIN_SLOT_GAP_MIN
        if (hi - lo) * 60 / self.daily_count < MIN_SLOT_GAP_MIN:
            raise ValueError(
                f"{self.daily_count} slot {hi - lo} saate sığmaz "
                f"(slot başına en az {MIN_SLOT_GAP_MIN} dakika gerekir)")
        if self.series_per_day > self.daily_count:
            raise ValueError(
                f"günde {self.series_per_day} seri bölümü isteniyor ama toplam "
                f"{self.daily_count} slot var")
        return self


class BgVideoConfig(BaseModel):
    enabled: bool = False
    scale: Literal[0.88, 0.80] = 0.88
    blur_px: int = Field(ge=0, le=80, default=30)
    # dim=1.0 → orijinal parlaklik, dim=0.0 → tam siyah.
    # Default 0.7 = subtle dim, BG video gorunur kalir ama on plana
    # yer acar. (0.4 default'u "hep siyah video" sikayetine yol aciyordu.)
    dim: float = Field(ge=0.0, le=1.0, default=0.7)


class TrendBoostConfig(BaseModel):
    """Per-channel trend-boost knobs. Score augmentation when a candidate
    headline matches an active trending term in the channel's region."""
    enabled: bool = False
    max_boost: float = Field(default=2.0, ge=0.0, le=5.0)
    # When None, inherits Settings.trends.default_sources.
    sources: list[str] | None = None
    min_term_length: int = Field(default=4, ge=2, le=20)
    fuzzy_threshold: int = Field(default=85, ge=50, le=100)
    exclude_terms: list[str] = Field(default_factory=list)
    # Override the channel-language -> region default (e.g. 'GB' for an
    # English-language channel targeting UK YouTube trending).
    region_override: str | None = None


class VoiceConfig(BaseModel):
    """Voiced (seslendirmeli) üretim ayarları. Blok yoksa kanal sessiz üretir."""
    enabled: bool = False
    voice_id: str = ""          # ai33 voice id (prefix'li ya da ham)
    speed: float = Field(default=1.0, ge=0.5, le=1.5)
    persona: str = "enerjik, meraklı anlatıcı"
    target_duration_s: tuple[int, int] = (45, 60)
    # Anlatım altındaki müzik seviyesi (~-18 dB).
    music_volume: float = Field(default=0.12, ge=0.0, le=1.0)

    @field_validator("target_duration_s", mode="before")
    @classmethod
    def _coerce_tuple(cls, v):
        return tuple(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def _check(self) -> "VoiceConfig":
        lo, hi = self.target_duration_s
        if not (10 <= lo < hi <= 180):
            raise ValueError(
                f"target_duration_s must satisfy 10 <= lo < hi <= 180, got ({lo}, {hi})"
            )
        if self.enabled and not self.voice_id.strip():
            raise ValueError("voice.enabled=true ise voice_id zorunlu")
        return self


class ReelConfig(BaseModel):
    """Footage-sürüklü reel formatı ayarları. Blok yoksa kanal reel üretmez."""
    enabled: bool = False
    voice_id: str = ""
    speed: float = Field(default=1.0, ge=0.5, le=1.5)
    target_duration_s: tuple[int, int] = (25, 45)
    cut_pacing: Literal["auto", "slow", "medium", "fast"] = "auto"
    highlight_color: str = "#ffd400"
    arrows_enabled: bool = True
    arrow_color: str = "#ff2d2d"
    arrow_frequency: Literal["off", "reveal", "beats"] = "beats"
    transitions_flash: bool = True
    transitions_whoosh: bool = True
    transitions_zoom: bool = True
    music_mood: Literal["upbeat", "neutral", "calm"] = "upbeat"
    # Müzik seviyesi = BOŞLUKTAKİ seviye. Ducking açıkken konuşma altında otomatik
    # çekilir, o yüzden 0.10 gibi "gömülü" bir değer gereksiz — müzik hiç enerji
    # taşımaz. 0.30 boşluklarda duyulur, konuşma altında kompresör indirir.
    music_volume: float = Field(default=0.30, ge=0.0, le=1.0)
    music_duck: bool = True     # müzik konuşma altında kısılsın (sidechain)
    # SFX kesim başına çalar (45sn'de ~18 kez). Eskiden assembler'da SABİT 0.6'ydı
    # (anlatım 1.0) → "sfx sesleri çok baskın". Vurgu olmalı, konuşmayla yarışmamalı.
    sfx_volume: float = Field(default=0.22, ge=0.0, le=1.0)
    font: Literal["Montserrat", "Anton", "Bebas Neue", "Oswald",
                  "Poppins", "Inter", "Archivo Black"] = "Montserrat"
    verify_footage: bool = True
    footage_anchor: str = ""   # EN konu çıpası (boşsa dna.search_query_template'ten türetilir)
    # Retention kurgu katmanı (2026-07-12): insan-editör hamleleri
    fast_cuts: bool = True      # segment-içi hızlı kesim (1.5-3sn'de b-roll değişir)
    number_pop: bool = True     # anlatımdaki sayıları ekranda büyük vurgula
    visual_loop: bool = True    # kapanış klibi = hook klibi (loop hissi)
    # ÖZNE-FARKINDA KADRAJ: 16:9 → 9:16 kırpma öznenin ETRAFINDAN yapılır.
    # Merkez-crop, otomatik faceless videonun "1 numaralı görsel ele veren işareti"
    # (özne kenardaysa yarısı kesilir).
    subject_framing: bool = True
    # MASTER RENK GRADE: farklı kaynaklardan gelen kliplerin renk ZIPLAMASI
    # "bunu bir script birleştirdi" diye bağırır. Ortak look + klip normalizasyonu.
    color_grade: bool = True
    # AI kurgucu (2026-07-13): anlatımı okuyup tempo/efekt/SFX/müzik seçer.
    # Kapalıysa kararlar eski seed-hash havuzlarından gelir (içerikten habersiz).
    ai_director: bool = True
    # TEMPO BÖLGELERİ: hook hızlı, tepe yavaş (bkz. reel_tempo). TTS tek hızda okur,
    # insan anlatıcı okumaz — tek hız videoyu "makine okumuş" yapar.
    tempo_zones: bool = True
    # KOORDİNELİ KESİNTİ: 3-5 beat sınırında vuruş+efekt+altyazı darbesi+punch AYNI
    # KAREDE; öteki kesimlerde SFX kısık (bkz. reel_interrupt). Kapalıysa her kesim
    # eşit güçte patlar — yani hiçbiri vurgu olmaz.
    interrupts: bool = True
    # Faz 2 varyasyon knob'ları (per-video deterministik profil)
    layout: Literal["auto", "classic", "lower_left", "top_heavy"] = "auto"
    hook_angle_vary: bool = True
    accent_vary: bool = True
    transition_vary: bool = True
    # Etkileşim mekanikleri (reel_subscribe üzerinden aktif). Beğeni/abone çipleri
    # 2026-07-16'da KALDIRILDI (kullanıcı kararı) — cta_enabled/cta_text_custom
    # alanları yok; eski YAML'lardaki anahtarlar pydantic extra-ignore ile atlanır.
    series_enabled: bool = False
    series_title: str = ""
    comment_question: bool = True
    # SERİ / CLIFFHANGER MİMARİSİ (bkz. reel_series). Bölüm numarası + açık kapı.
    # Ark bu kadar bölümden sonra kesilir ve konu bankasından taze konu
    # gelir — zincir uzadıkça konu kanalın nişinden sürüklenir (sapma birikimli).
    series_arc_length: int = 3
    # ARK MODU (bkz. reel_arc):
    #   "chain"   → her bölüm bir sonrakini KEŞFEDER (kapı → sonraki konu). Planlama
    #               yok, ama sapma birikimli ve vaat yalnız TEK ADIM ileriyi gösterir.
    #   "planned" → ark ÖNCEDEN planlanır ve kullanıcı ONAYLAR. Sıradaki bölümün
    #               konusu planda yazılı olduğu için LLM cliffhanger'ı UYDURMAZ,
    #               SÖYLER → konu sapması yapısal olarak imkânsız. Ayrıca ilk bölüm
    #               "N bölümlük seri" diye İLAN eder: izleyici bir videoya değil bir
    #               SERİYE abone olur.
    # Onaylı ark yoksa üretim DURMAZ — bankadan tek konu üretilir (panel uyarır).
    arc_mode: Literal["chain", "planned"] = "planned"
    # FEED KİMLİĞİ KİLİDİ (bkz. reel_identity). Aksan rengi ve yerleşim per-video
    # DÖNMEZ; kanalın sabit değerine oturur. Kesme efekti/SFX/marker/müzik dönmeye
    # devam eder — izleyici kanalı onlardan tanımaz, FONT ve RENKTEN tanır.
    identity_lock: bool = True
    # Açılış ses imzası (assets/sting/*.mp3). Kanala göre BİR KEZ seçilir, her
    # bölümde aynı çalar — imza ancak tekrarlanınca imza olur.
    sting_enabled: bool = True
    sting_volume: float = 0.35
    # PERSONA: reel anlatım tonu. "" = kişiliksiz (bugünkü "ilginç bilgiler" tonu).
    # "vahsi_mizah" = hayvanı mahalle-karakterine büründüren komik anlatım.
    # Boş varsayılan KRİTİK: mevcut tüm kanallar bugünkü prompt'u alır → sıfır regresyon.
    persona: str = ""
    # MASKOT: kanalın tekrar eden ANA KARAKTERİ (DiscoverNow'un "Porsuk Dumrul"u).
    # Boşsa maskot yok (her video bağımsız). Doluysa persona senaryoyu bu karakter
    # etrafında kurar — izleyici bir videoya değil KARAKTERE bağlanır (retention).
    # Üçü birlikte anlamlı: hepsi doluysa maskot aktif.
    mascot_name: str = ""      # "Deli Kâzım"
    mascot_animal: str = ""    # "bal porsuğu"
    mascot_trait: str = ""     # "Geri Vitesi Olmayan Deli — çılgın, korkusuz, geri vites yok"
    # KÜRATE-KLİP MODU (content_source="curated", pivot 2026-07-17): kanalın cevher
    # çekeceği subreddit listesi. Boşsa reddit_gems.DEFAULT_SUBS. NİŞ = subreddit
    # listesi + persona/ses → aynı hattan birçok kanal (bkz. curated-clip-pivot).
    subreddits: list[str] = Field(default_factory=list)
    curated_min_ups: int = 500       # cevher eşiği (topluluk oyu = kalite sinyali)
    curated_time: str = "week"       # reddit 'top' penceresi: hour/day/week/month/year/all
    curated_max_duration: int = 90   # saniye — daha uzun klipler atlanır
    # Hafif/kenar watermark'ı vision+delogo ile temizle (yazılı klip de kullanılabilir);
    # ağır kaplayan yazı temizlenmez (bkz. curated_clean). Kapatılırsa klip olduğu gibi.
    curated_clean: bool = True
    # KANALIN KENDİ HAS MİZAH SESİ (kullanıcı: 'her kanalın kendi mizahı olacak, belirli
    # kalıp değil'). Serbest metin — bu kanalın komik tonunu tarif eder (ör. 'sakin,
    # ironik, gözlemci' ya da 'coşkulu, abartısız gündelik'). Boşsa: gerçek, klibe özgü
    # gözlem mizahı (kalıpsız). persona'dan AYRI — persona ağzı/karakteri, bu tonu verir.
    humor_style: str = ""

    @field_validator("target_duration_s", mode="before")
    @classmethod
    def _coerce_tuple(cls, v):
        return tuple(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def _check(self) -> "ReelConfig":
        lo, hi = self.target_duration_s
        # YouTube Shorts üst sınırı 2024'ten beri 180sn; referans mizah kanalları
        # 125-160sn yayınlıyor ve sürükleyicilik için o uzunluk gerekiyor (ölçüldü).
        if not (10 <= lo < hi <= 180):
            raise ValueError(
                f"target_duration_s must satisfy 10 <= lo < hi <= 180, got ({lo}, {hi})"
            )
        if self.enabled and not self.voice_id.strip():
            raise ValueError("reel.enabled=true ise voice_id zorunlu")
        return self


@dataclass(frozen=True)
class ChannelConfig:
    slug: str
    name: str
    keywords: list[str]
    rss_locale: str
    schedule_cron: str
    duration_s: int
    min_score: float
    max_candidates_per_run: int
    template: str
    colors: dict
    handle: str
    output_dir: str
    enabled: bool
    # Beğeni/abone CTA alanları KALDIRILDI (2026-07-16, kullanıcı kararı) —
    # eski YAML'lardaki 'cta:' bölümü loader'da okunmaz, sessizce atlanır.
    language: str = "tr"
    # max_age_hours: pipeline drops RSS items older than this many hours
    # (0 = no limit). Default 24h prevents stale articles from being turned
    # into shorts.
    max_age_hours: int = 24
    dynamic_dna: bool = False
    negative_keywords: list[str] = field(default_factory=list)
    dna: DnaSpec | None = None
    script_model: str | None = None
    content_source: Literal["rss", "generator", "feed", "curated"] = "rss"
    generator: GeneratorConfig | None = None
    auto_feed_ids: list[int] = field(default_factory=list)
    youtube: YoutubeChannelConfig | None = None
    # AUTOPILOT: otomatik üretim + zamanlı yükleme (bkz. autopilot.py). None/kapalı
    # iken hiçbir davranış değişmez.
    autopilot: AutopilotConfig | None = None
    bg_video: BgVideoConfig | None = None
    trend_boost: TrendBoostConfig | None = None
    # Per-channel og:image blur radius (0 = crisp original). Up to v0.6.2 a
    # baked-in 8px GaussianBlur was applied to every publisher photo. v0.6.3
    # made this a UI knob: 0 = original, 8 = old behavior, 20 = heavy frosted.
    bg_image_blur: int = 0
    voice: VoiceConfig | None = None
    reel: "ReelConfig | None" = None
    # Referans/rakip kanallar (URL/@handle/UC-id) — konu-bankası madencisi bu
    # kanalların KENDİ medyanına göre patlayan shorts'larını kanıtlanmış konu
    # olarak çeker (format+kitle garantili). Boşsa yalnız arama madenciliği.
    reference_channels: list[str] = field(default_factory=list)


def load_settings(path: Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    web = data.get("web", {})
    wh_data = data.get("whisper", {}) or {}
    tr_data = data.get("trends", {}) or {}
    ft_data = data.get("footage", {}) or {}
    trends = TrendsSettings(
        enabled=bool(tr_data.get("enabled", False)),
        refresh_minutes=int(tr_data.get("refresh_minutes", 60)),
        default_sources=tuple(tr_data.get("default_sources",
                                          ["google_daily", "youtube"])),
        cache_max_age_minutes=float(tr_data.get("cache_max_age_minutes", 90)),
    )
    return Settings(
        ffmpeg_path=data["ffmpeg_path"],
        claude_cli_path=data["claude_cli_path"],
        playwright_browser=data.get("playwright_browser", "chromium"),
        web_host=web.get("host", "127.0.0.1"),
        web_port=int(web.get("port", 5005)),
        fuzzy_dedup_threshold=float(data.get("fuzzy_dedup_threshold", 0.85)),
        log_level=data.get("log_level", "INFO"),
        claude_models=dict(data.get("claude_models", {"dna": "opus", "default": "haiku"})),
        ai_backend=data.get("ai_backend", "claude_cli"),
        openrouter_models=dict(data.get("openrouter_models", {})),
        google_studio=dict(data.get("google_studio", {})),
        trends=trends,
        whisper_quality=wh_data.get("quality", "auto"),
        whisper_device=wh_data.get("device", "auto"),
        # Eski config'lerde 'storyblocks' kalmış olabilir (2026-07-16'da kaldırıldı)
        # → build_footage_sources tanımadığı adı zaten atlar, burada temizlemek şart değil.
        footage_priority=list(ft_data.get("priority", ["pexels"])),
    )


def load_channel(path: Path) -> ChannelConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    slug = data["slug"]
    if not SLUG_RE.match(slug):
        raise ValueError(f"Geçersiz slug '{slug}': sadece [a-z0-9-] izinli")

    # Resolve language (with backward-compat for legacy rss_locale-only YAMLs)
    language = data.get("language", "tr")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language '{language}': must be one of {SUPPORTED_LANGUAGES}"
        )
    rss_locale = data.get("rss_locale") or RSS_LOCALES[language]

    # Backward-compat: 'template: default' → 'newscast'
    template = data.get("template", "newscast")
    if template == "default":
        template = "newscast"

    # Optional DNA block
    dna_data = data.get("dna")
    dna = DnaSpec.model_validate(dna_data) if dna_data else None
    if dna is not None and dna.archetype != template:
        raise ValueError(
            f"channel.template ({template!r}) must match dna.archetype ({dna.archetype!r})"
        )

    content_source = data.get("content_source", "rss")
    if content_source not in ("rss", "generator", "feed", "curated"):
        raise ValueError(
            f"content_source must be 'rss', 'generator', 'feed' or 'curated', "
            f"got {content_source!r}"
        )

    auto_feed_ids = [int(x) for x in (data.get("auto_feed_ids") or [])]
    if content_source == "feed" and not auto_feed_ids:
        raise ValueError(
            f"channel {slug!r} has content_source='feed' but no auto_feed_ids. "
            f"Add at least one feed id from the pool."
        )

    keywords = list(data.get("keywords", []))
    if content_source == "rss" and not keywords:
        raise ValueError(
            f"channel {slug!r} has content_source='rss' but no keywords. "
            f"Either add keywords or set content_source: generator (with a generator block)."
        )

    generator = None
    if content_source == "generator":
        gen_data = data.get("generator")
        if not gen_data:
            raise ValueError(
                "content_source='generator' requires a 'generator' block in YAML"
            )
        topic = (gen_data.get("topic") or "").strip()
        if len(topic) < 10:
            raise ValueError(
                f"generator.topic must be at least 10 chars, got {len(topic)}"
            )
        generator = GeneratorConfig(
            topic=topic,
            forbidden_lookback=int(gen_data.get("forbidden_lookback", 50)),
            max_retries=int(gen_data.get("max_retries", 3)),
            fuzzy_threshold=(float(gen_data["fuzzy_threshold"])
                              if "fuzzy_threshold" in gen_data else None),
        )

    yt_data = data.get("youtube")
    youtube = YoutubeChannelConfig.model_validate(yt_data) if yt_data else None

    autopilot_data = data.get("autopilot")
    autopilot = (AutopilotConfig.model_validate(autopilot_data)
                 if autopilot_data else None)

    bg_video_data = data.get("bg_video")
    bg_video = BgVideoConfig.model_validate(bg_video_data) if bg_video_data else None

    trend_boost_data = data.get("trend_boost")
    trend_boost = (TrendBoostConfig.model_validate(trend_boost_data)
                   if trend_boost_data else None)

    voice_data = data.get("voice")
    voice = VoiceConfig.model_validate(voice_data) if voice_data else None

    reel_data = data.get("reel")
    reel = ReelConfig.model_validate(reel_data) if reel_data else None

    return ChannelConfig(
        slug=slug,
        name=data["name"],
        keywords=keywords,
        rss_locale=rss_locale,
        schedule_cron=data["schedule_cron"],
        duration_s=int(data["duration_s"]),
        min_score=float(data["min_score"]),
        max_candidates_per_run=int(data["max_candidates_per_run"]),
        max_age_hours=int(data.get("max_age_hours", 24)),
        dynamic_dna=bool(data.get("dynamic_dna", False)),
        negative_keywords=list(data.get("negative_keywords") or []),
        reference_channels=list(data.get("reference_channels") or []),
        template=template,
        colors=dict(data["colors"]),
        handle=data["handle"],
        output_dir=data["output_dir"],
        enabled=bool(data.get("enabled", True)),
        language=language,
        dna=dna,
        script_model=data.get("script_model"),
        content_source=content_source,
        generator=generator,
        auto_feed_ids=auto_feed_ids,
        youtube=youtube,
        autopilot=autopilot,
        bg_video=bg_video,
        trend_boost=trend_boost,
        bg_image_blur=int(data.get("bg_image_blur", 0)),
        voice=voice,
        reel=reel,
    )


def save_channel(path: Path, cfg: ChannelConfig) -> None:
    """Write a ChannelConfig back to YAML (inverse of load_channel)."""
    data = {
        "slug": cfg.slug,
        "name": cfg.name,
        "keywords": list(cfg.keywords),
        "language": cfg.language,
        "schedule_cron": cfg.schedule_cron,
        "duration_s": cfg.duration_s,
        "min_score": cfg.min_score,
        "max_candidates_per_run": cfg.max_candidates_per_run,
        "max_age_hours": cfg.max_age_hours,
        "template": cfg.template,
        "colors": dict(cfg.colors),
        "handle": cfg.handle,
        "output_dir": cfg.output_dir,
        "enabled": cfg.enabled,
    }
    if cfg.dynamic_dna:
        data["dynamic_dna"] = True
    if cfg.negative_keywords:
        data["negative_keywords"] = list(cfg.negative_keywords)
    if cfg.reference_channels:
        data["reference_channels"] = list(cfg.reference_channels)
    if cfg.script_model:
        data["script_model"] = cfg.script_model
    if cfg.content_source != "rss":
        data["content_source"] = cfg.content_source
    if cfg.auto_feed_ids:
        data["auto_feed_ids"] = list(cfg.auto_feed_ids)
    if cfg.generator is not None:
        gen_data = {
            "topic": cfg.generator.topic,
            "forbidden_lookback": cfg.generator.forbidden_lookback,
            "max_retries": cfg.generator.max_retries,
        }
        if cfg.generator.fuzzy_threshold is not None:
            gen_data["fuzzy_threshold"] = cfg.generator.fuzzy_threshold
        data["generator"] = gen_data
    if cfg.youtube is not None:
        data["youtube"] = {
            "auto_upload": cfg.youtube.auto_upload,
            "ai_content": cfg.youtube.ai_content,
            "category_id": cfg.youtube.category_id,
            "privacy_status": cfg.youtube.privacy_status,
            "min_score_for_upload": cfg.youtube.min_score_for_upload,
        }
        if cfg.youtube.cron_preset:
            data["youtube"]["cron_preset"] = cfg.youtube.cron_preset
    # AUTOPILOT: blok VARSA yaz. Yoksa YAZMA — autopilot'u hiç kullanmayan bir kanala
    # kaydet'e basınca blok eklemek, geriye uyumu sessizce kırardı.
    if cfg.autopilot is not None:
        ap = cfg.autopilot.model_dump()
        ap["active_hours"] = list(ap["active_hours"])   # YAML tuple yazmasın
        data["autopilot"] = ap
    if cfg.bg_video is not None and cfg.bg_video.enabled:
        data["bg_video"] = {
            "enabled": cfg.bg_video.enabled,
            "scale": cfg.bg_video.scale,
            "blur_px": cfg.bg_video.blur_px,
            "dim": cfg.bg_video.dim,
        }
    if cfg.trend_boost is not None:
        tb = {
            "enabled": cfg.trend_boost.enabled,
            "max_boost": cfg.trend_boost.max_boost,
            "min_term_length": cfg.trend_boost.min_term_length,
            "fuzzy_threshold": cfg.trend_boost.fuzzy_threshold,
        }
        if cfg.trend_boost.sources is not None:
            tb["sources"] = list(cfg.trend_boost.sources)
        if cfg.trend_boost.exclude_terms:
            tb["exclude_terms"] = list(cfg.trend_boost.exclude_terms)
        if cfg.trend_boost.region_override:
            tb["region_override"] = cfg.trend_boost.region_override
        data["trend_boost"] = tb
    if cfg.bg_image_blur:
        data["bg_image_blur"] = cfg.bg_image_blur
    if cfg.voice is not None:
        data["voice"] = {
            "enabled": cfg.voice.enabled,
            "voice_id": cfg.voice.voice_id,
            "speed": cfg.voice.speed,
            "persona": cfg.voice.persona,
            "target_duration_s": list(cfg.voice.target_duration_s),
            "music_volume": cfg.voice.music_volume,
        }
    if cfg.reel is not None:
        data["reel"] = {
            "enabled": cfg.reel.enabled,
            "voice_id": cfg.reel.voice_id,
            "speed": cfg.reel.speed,
            "target_duration_s": list(cfg.reel.target_duration_s),
            "cut_pacing": cfg.reel.cut_pacing,
            "highlight_color": cfg.reel.highlight_color,
            "arrows_enabled": cfg.reel.arrows_enabled,
            "arrow_color": cfg.reel.arrow_color,
            "arrow_frequency": cfg.reel.arrow_frequency,
            "transitions_flash": cfg.reel.transitions_flash,
            "transitions_whoosh": cfg.reel.transitions_whoosh,
            "transitions_zoom": cfg.reel.transitions_zoom,
            "music_mood": cfg.reel.music_mood,
            "music_volume": cfg.reel.music_volume,
            "sfx_volume": cfg.reel.sfx_volume,
            "font": cfg.reel.font,
            "verify_footage": cfg.reel.verify_footage,
            "fast_cuts": cfg.reel.fast_cuts,
            "number_pop": cfg.reel.number_pop,
            "visual_loop": cfg.reel.visual_loop,
            "layout": cfg.reel.layout,
            "hook_angle_vary": cfg.reel.hook_angle_vary,
            "accent_vary": cfg.reel.accent_vary,
            "transition_vary": cfg.reel.transition_vary,
            "series_enabled": cfg.reel.series_enabled,
            "series_title": cfg.reel.series_title,
            "series_arc_length": cfg.reel.series_arc_length,
            "arc_mode": cfg.reel.arc_mode,
            "identity_lock": cfg.reel.identity_lock,
            "sting_enabled": cfg.reel.sting_enabled,
            "comment_question": cfg.reel.comment_question,
            "persona": cfg.reel.persona,
            "mascot_name": cfg.reel.mascot_name,
            "mascot_animal": cfg.reel.mascot_animal,
            "mascot_trait": cfg.reel.mascot_trait,
            "subreddits": list(cfg.reel.subreddits),
            "curated_min_ups": cfg.reel.curated_min_ups,
            "curated_time": cfg.reel.curated_time,
            "curated_max_duration": cfg.reel.curated_max_duration,
            "curated_clean": cfg.reel.curated_clean,
            "humor_style": cfg.reel.humor_style,
        }
    if cfg.dna is not None:
        # mode='json' → tuple becomes list, ready for YAML round-trip
        data["dna"] = cfg.dna.model_dump(mode="json")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def list_channels(channels_dir: Path, enabled_only: bool = False) -> list[ChannelConfig]:
    """List all channels in directory. Invalid channel YAMLs are SKIPPED with a
    warning instead of crashing the whole scheduler — this protects the panel
    boot path when a single channel references a stale archetype/setting.
    """
    import logging
    log = logging.getLogger(__name__)
    out = []
    for p in sorted(Path(channels_dir).glob("*.yaml")):
        try:
            c = load_channel(p)
        except Exception as e:
            log.warning(f"skipping invalid channel {p.name}: {e}")
            continue
        if enabled_only and not c.enabled:
            continue
        out.append(c)
    return out


@dataclass(frozen=True)
class AICall:
    backend: str            # "claude_cli" | "openrouter"
    model: str
    api_key: str | None     # openrouter'da dolu, claude_cli'da None
    claude_path: str


def resolve_ai_call(settings: Settings, secrets: dict, role: str) -> AICall:
    """role: 'dna' | 'default' | 'script' | 'vision'. Aktif backend'e göre model+key çözer."""
    if settings.ai_backend == "hybrid":
        # Metin → OpenRouter (ÖLÇÜLDÜ 2026-07-16: gemini-3.1-flash-lite ~4sn/$0.002 ve
        # persona-sadık; Claude CLI ~7-çağrı burst'te Max-plan rate-limit thrash'ine
        # giriyordu, OR Sonnet ~89sn/$0.10). DNA hariç metin gemini-flash-lite'a gider;
        # DNA (nadir, yüksek bahis) openrouter_models'ta Sonnet 5'e eşlenir.
        # Vision → Google Studio ücretsiz havuz; tükenirse OR gemma fallback (registry).
        from short_bot import claude_cli
        or_key = secrets.get("openrouter_api_key", "") or None
        if role == "vision":
            gs_model = settings.google_studio.get("vision_model", "gemini-3.1-flash-lite")
            claude_cli.register_fallback(
                "google_studio", gs_model, "openrouter",
                settings.openrouter_models.get("vision", "google/gemma-4-26b-a4b-it"), or_key)
            return AICall(backend="google_studio", model=gs_model,
                          api_key=None, claude_path=settings.claude_cli_path)
        or_model = (settings.openrouter_models.get(role)
                    or settings.openrouter_models.get("default", "google/gemini-3.1-flash-lite"))
        return AICall(backend="openrouter", model=or_model,
                      api_key=or_key, claude_path=settings.claude_cli_path)
    if settings.ai_backend == "openrouter":
        model = (settings.openrouter_models.get(role)
                 or settings.openrouter_models.get("default", ""))
        return AICall(
            backend="openrouter",
            model=model,
            api_key=(secrets.get("openrouter_api_key", "") or None),
            claude_path=settings.claude_cli_path,
        )
    cli_fallback = "default" if role == "vision" else "haiku"
    return AICall(
        backend="claude_cli",
        model=settings.claude_models.get(role, cli_fallback),
        api_key=None,
        claude_path=settings.claude_cli_path,
    )
