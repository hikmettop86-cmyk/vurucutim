"""Kürate-klip üretim orkestratörü (SP3): seçilen Reddit cevherini uçtan uca videoya
çevirir ve panelde görünsün/yüklenebilsin diye Short olarak kaydeder.

Zincir: indir (v.redd.it) → vision ile GERÇEK aksiyonu oku → persona ile yeniden-senaryo
(uydurma yok) → produce_reel_video (tek klip; kısa klip loop yerine YAVAŞLATILIR) →
record_short. Metin/vision backend'i hibrit (resolve_ai_call); footage ARANMAZ.
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# DUYGU modu klip-seçim kapıları (short 934 dersi: 11sn'lik derp klibi zorlama çıktı).
CURATED_DUYGU_MIN_S = 18   # bundan kısa klip mikro-dramı taşımaz → oto-seçimde elenir
DUYGU_MIN_SCORE = 7        # emotion skoru bunun altındaysa oto-üretim ATLANIR (zayıfı zorlama)
# MİZAH modu min-süre (short 947 dersi: 12sn klip kurulum+tırmanma+punchline'a yer bırakmıyor
# → narration taşıp klip 3x loop'lanıyor). Kaos/fail snappy olabilir ama iyi espri ~15sn ister.
CURATED_MIZAH_MIN_S = 15


class CuratedWatermarkError(RuntimeError):
    """Klipte temizlenemeyen (hareketli TikTok / özneyi kaplayan) watermark var — bu klip
    kullanılamaz. Manuel seçimde kullanıcıya net hata; oto-seçimde sıradaki adaya geçilir."""


class CuratedClipError(RuntimeError):
    """Klip İNDİRİLEMEDİ (403/404/ağ) — bu cevher kullanılamaz. Reddit CDN bazı v.redd.it
    varyantlarına 403 veriyor; tek bozuk klip tüm run'ı DÜŞÜRMESİN → oto-seçimde sıradaki
    adaya geçilir (watermark eleme deseniyle aynı)."""


def produce_curated(gem: dict, channel, *, settings, secrets, db_path,
                    output_root, music_root, templates_dir, cache_dir=None,
                    seed: int = 0, log=log) -> tuple[int, Path]:
    """Bir cevherden video üretip Short kaydeder. Döner (short_id, out_path).

    gem: find_gems/fetch_post çıktısı (video_url + title şart).
    Reel etkin, persona'lı bir kanal gerekir. Hata olursa net Türkçe RuntimeError.
    """
    from short_bot.assets import pick_music
    from short_bot.db import init_db, record_short
    from short_bot.pipeline import resolve_ai_call, unique_output_path, _slugify
    from short_bot.reddit_gems import download_clip
    from short_bot.reel import (_clip_duration_s, _describe_clip,
                                produce_reel_video)
    from short_bot.reel_narration import curated_target, write_curated_narration
    from short_bot.tts.ai33_client import resolve_ai33_api_key

    reel = getattr(channel, "reel", None)
    if reel is None or not reel.enabled:
        raise ValueError("produce_curated: kanal reel etkin değil")
    video_url = gem.get("video_url")
    if not video_url:
        raise ValueError("produce_curated: cevherde video_url yok")
    title_seed = (gem.get("title") or "kürate klip").strip()

    # KLİP-BAŞINA VARYANT SEED (kullanıcı: 'senaryo hep aynı kalıp'). persona_block
    # açılış/anlatıcı-ses/benzetme-dünyası/kapanış-imzası stillerini SEED'e göre döndürür;
    # kürate hep seed=0 kullanınca hepsi index 0'a (ozan beyti + 'Şu X'e bak') kilitleniyordu.
    # Video-ID hash'i → her klip farklı stil (aynı klip → aynı, deterministik). Görsel
    # varyasyon profili de bu seed'den türer (kesim/marker/tempo da çeşitlenir).
    if not seed:
        import hashlib
        _k = (video_url or gem.get("permalink") or title_seed or "x").encode("utf-8")
        seed = int(hashlib.sha1(_k).hexdigest()[:8], 16)

    vision = resolve_ai_call(settings, secrets, "vision")
    llm = resolve_ai_call(settings, secrets, "script")
    # SENARYO komedi ÇEKİRDEĞİ → EN GÜÇLÜ yazar: Claude CLI Sonnet 5. Kullanıcı: gemini-lite
    # 'tatmin edici değil' (klişe + ozan sızıntısı); Sonnet spesifik/zeki/kültüre oturan mizah
    # yazıyor. CLI backend = Max aboneliği → ÜCRETSİZ (OpenRouter dna rolü ~$0.02/video
    # harcardı; kullanıcı: 'boşa para yazmasın openrouterda'). Tek kısa çağrı/video (~50sn;
    # video zaten ~2dk arka planda üretiliyor) → BURST YOK, eski 7-çağrı Max-plan rate-limit
    # thrash'i geçerli değil. Görsel/kurgu/metadata hızlı OpenRouter backend'inde kalır.
    from short_bot.config import AICall
    narr_llm = AICall(backend="claude_cli", model="sonnet", api_key=None,
                      claude_path=settings.claude_cli_path)
    ai33_key = resolve_ai33_api_key(secrets)

    out_dir = Path(output_root) / channel.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now(timezone.utc):%Y-%m-%d}_{_slugify(title_seed)}"
    out_path = unique_output_path(out_dir, stem)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        log.info(f"  kürate: klip indiriliyor ({video_url})")
        try:
            clip = download_clip(video_url, td / "src.mp4")
        except Exception as e:  # noqa: BLE001 — 403/404/ağ → skippable (sıradaki aday)
            raise CuratedClipError(f"klip indirilemedi ({video_url}): {e}") from e
        # TEMİZLİK (SP4): hafif/kenar watermark → delogo (yazılı klip de kullanılabilir);
        # ağır kaplama temizlenmez. Kanal flag'i kapalıysa atlanır.
        if getattr(reel, "curated_clean", True) and vision is not None:
            from short_bot.curated_clean import clean_if_needed, watermark_uncleanable
            clip, _wm = clean_if_needed(clip, vision_call=vision,
                                        ffmpeg_path=settings.ffmpeg_path,
                                        out_path=td / "clean.mp4")
            if _wm is not None and _wm.present:
                log.info(f"  kürate: watermark {_wm.regions} (kaplıyor={_wm.covers_subject})")
                # Temizlenemeyen (hareketli TikTok / kaplayan) → bu klip WATERMARK'LI
                # kalır; kullanma. Manuel: net hata. Oto: çağıran sıradaki adaya geçer.
                if watermark_uncleanable(_wm):
                    raise CuratedWatermarkError(
                        "Bu klipte temizlenemeyen (hareketli TikTok / kaplayan) watermark "
                        "var — watermark'sız bir klip seç.")
            # KAYNAK YAZI-BANDI: repost başlığı (gömülü metin kutusu) Türkçe altyazımızla
            # çakışır. ÜST/ALT kenara yapışık şerit → temiz KIRP. Ortada yüzen bant (bkz.
            # short 935 tembel-hayvan, y≈0.48) temiz kırpılamaz (delogo=smear, crop=içerik
            # kaybı) → dokunulmaz, olduğu gibi kalır.
            from short_bot.curated_clean import (crop_source_banner,
                                                 detect_source_banner)
            _banner = detect_source_banner(clip, vision_call=vision,
                                           ffmpeg_path=settings.ffmpeg_path)
            _nb = crop_source_banner(clip, _banner, ffmpeg_path=settings.ffmpeg_path,
                                     out_path=td / "nobanner.mp4")
            if _nb is not None:
                clip = _nb
        # NOT: Kürate klibi renk grade'i (reel_assembler, GRADE_TARGET_LUMA≈0.45'e normalize
        # + vignette) diğer kanallarla AYNI uygulanır. Bir ara gölge-kaldıran ön-aydınlatma
        # (brighten_if_dark) eklenmiş + grade kapatılmıştı ama çıktı FAZLA açık/yıkanmış
        # oluyordu (short 917, YAVG 150) → kullanıcı isteğiyle GERİ ALINDI, eski grade look.
        clip_dur = _clip_duration_s(clip, settings.ffmpeg_path)

        log.info("  kürate: vision ile GERÇEK aksiyon okunuyor…")
        desc = _describe_clip(clip, vision_call=vision, ffmpeg_path=settings.ffmpeg_path)
        if not desc.strip():
            raise RuntimeError("kürate: vision klibi tarif edemedi (backend kapalı?)")
        log.info(f"  kürate: vision → {desc}")

        # KALABALIK BAĞLAMI (vision'a ALTERNATİF): vision tek storyboard'dan aleti/olayı
        # kaçırabiliyor (short 923: pipeti görmedi, 'parmakla çöp çıkarıyor' dedi — oysa
        # başlık 'using a straw', yorumlar 'nefes borusuna soktu' diyor). Başlık + üst
        # yorumlar olayın NE olduğunu anlatır → anlatıma gerçek sinyal, vision'a yenilmesin.
        comments: list[str] = []
        _cid, _csec = secrets.get("reddit_client_id"), secrets.get("reddit_client_secret")
        if _cid and _csec and gem.get("permalink"):
            from short_bot.reddit_gems import fetch_top_comments
            comments = fetch_top_comments(gem["permalink"], _cid, _csec, limit=4)
            if comments:
                log.info(f"  kürate: {len(comments)} üst yorum bağlam olarak eklendi")

        # SAHNE-SENKRON: klip 2 sahneliyse (poster→banyo gibi) geçiş oranını tespit et →
        # anlatım temposu sahneye uydurulur (ses görüntünün önüne geçmesin; kullanıcı
        # yakaladı: "banyoda" banyo görünmeden ~3sn önce söyleniyordu). Tek sahne → None.
        scene_split = None
        if vision is not None:
            from short_bot.curated_clean import detect_scene_split
            scene_split = detect_scene_split(clip, vision_call=vision,
                                             ffmpeg_path=settings.ffmpeg_path)
            if scene_split is not None:
                log.info(f"  kürate: 2 sahneli klip → geçiş ~%{round(scene_split*100)} "
                         f"(anlatım tempolanacak)")

        target = curated_target(clip_dur, reel.target_duration_s)
        log.info(f"  kürate: klip {clip_dur:.1f}s → video hedefi {target} (loop önleme)")
        narration = write_curated_narration(
            title_seed, desc, channel=channel, subject="clip",
            claude_path=narr_llm.claude_path, model=narr_llm.model,
            backend=narr_llm.backend, api_key=narr_llm.api_key,
            seed=seed, target_duration_s=target, scene_split=scene_split,
            comments=comments)
        log.info(f"  kürate: senaryo {narration.word_count()} kelime | "
                 f"başlık='{narration.title}' kapak='{narration.cover_title}'")

        try:
            music = pick_music(Path(music_root), mood=reel.music_mood,
                               channel_slug=channel.slug)
        except Exception as e:  # noqa: BLE001 — müziksiz de üretilir
            log.info(f"  kürate: müzik yok ({e})")
            music = None

        t0 = time.perf_counter()
        produce_reel_video(
            topic=title_seed, channel=channel, templates_dir=Path(templates_dir),
            work_dir=td / "work", out_path=out_path, music_path=music,
            ai33_api_key=ai33_key, pexels_api_key="", pixabay_api_key="",
            ffmpeg_path=settings.ffmpeg_path, browser=settings.playwright_browser,
            llm_claude_path=llm.claude_path, llm_model=llm.model,
            llm_backend=llm.backend, llm_api_key=llm.api_key,
            vision_call=vision, seed=seed, assets_root=Path(music_root).parent,
            curated_clip=clip, curated_narration=narration)
        render_ms = int((time.perf_counter() - t0) * 1000)

    # Short kaydı: /shorts'ta görünür + mevcut yükleme yolu kullanılabilir.
    # script_json yükleme anında YT başlık/açıklamasını besler (bkz. youtube route).
    seo = (narration.title or title_seed)[:100]
    script_json = json.dumps({
        "header_top": narration.cover_title or narration.hook,
        "header_bottom": "",
        "body_paragraph": narration.full_text(),
        "title": seo,
        # İngilizce başlık → YouTube çok-dilli başlık (küresel Shorts akışı). Boşsa yok sayılır.
        "title_en": (getattr(narration, "title_en", "") or "")[:100],
        "source_permalink": gem.get("permalink", ""),
        "source_video_url": video_url,   # dedup: aynı klip iki kez üretilmesin
    }, ensure_ascii=False)
    eng = init_db(db_path)
    short_id = record_short(
        eng, channel=channel.slug, rss_item_guid=None, title=seo,
        file_path=str(out_path), duration_s=int(round(clip_dur)) or None,
        script_json=script_json, render_ms=render_ms)
    log.info(f"  kürate: Short kaydedildi id={short_id} → {out_path.name}")
    return short_id, out_path


def _produced_clip_keys(db_path) -> set:
    """Üretilmiş kliplerin dedup anahtarları (video-ID + permalink) — otomatik seçimde
    aynı klip iki kez üretilmesin."""
    import re
    from sqlalchemy import select

    from short_bot.db import init_db, shorts
    keys: set = set()
    try:
        eng = init_db(db_path)
        with eng.connect() as c:
            for r in c.execute(select(shorts.c.script_json)):
                try:
                    d = json.loads(r.script_json or "{}")
                except Exception:  # noqa: BLE001
                    continue
                vu = (d.get("source_video_url") or "").split("?")[0]
                m = re.search(r"v\.redd\.it/([a-z0-9]+)", vu)
                if m:
                    keys.add("vreddit:" + m.group(1))
                elif vu:
                    keys.add(vu)
                if d.get("source_permalink"):
                    keys.add(d["source_permalink"])
    except Exception:  # noqa: BLE001
        pass
    return keys


def _gem_produced(gem: dict, keys: set) -> bool:
    import re
    vu = (gem.get("video_url") or "").split("?")[0]
    m = re.search(r"v\.redd\.it/([a-z0-9]+)", vu)
    k = "vreddit:" + m.group(1) if m else vu
    return k in keys or gem.get("permalink") in keys


def _gem_rank(gem: dict) -> float:
    """Autopilot 'bize uygun' skoru: upvote + yorum-etkileşimi + yumuşak yön/süre.
    Panel'deki manuel sıralamayla (curated_rank.engagement_score) TUTARLI."""
    from short_bot.curated_rank import engagement_score
    return engagement_score(gem)


def auto_produce_curated(channel, *, settings, secrets, db_path, output_root,
                         music_root, templates_dir, log=log):
    """Kürate kanalı için cevheri OTOMATİK seç (kanal subreddit'leri → üretilmemiş →
    en iyi) + üret. Cron/autopilot/'Şimdi üret' bunu kullanır (Cevher onayı gerekmez).

    Döner (short_id, out_path); taze cevher yoksa (None, None)."""
    from short_bot.reddit_gems import DEFAULT_DUYGU_SUBS, DEFAULT_SUBS, find_gems
    reel = channel.reel
    cid = secrets.get("reddit_client_id")
    csec = secrets.get("reddit_client_secret")
    if not (cid and csec):
        raise RuntimeError("kürate: Reddit kimliği yok (data/secrets.yaml: "
                           "reddit_client_id / reddit_client_secret)")
    tone = getattr(reel, "curated_tone", "mizah")
    # HAVUZ: kanal kendi subreddit'ini vermediyse tona göre varsayılan — DUYGU kanalı
    # kurtarma/kahramanlık suları (derp değil; short 934'te derp klibi zorlama çıkmıştı).
    subs = list(getattr(reel, "subreddits", []) or []) or (
        DEFAULT_DUYGU_SUBS if tone == "duygu" else DEFAULT_SUBS)
    t = getattr(reel, "curated_time", "week")
    log.info(f"  kürate[oto]: {len(subs)} subreddit taranıyor (t={t}, ton={tone})")
    gems = find_gems(cid, csec, subreddits=subs, t=t,
                     min_ups=getattr(reel, "curated_min_ups", 500),
                     max_duration=getattr(reel, "curated_max_duration", 90))
    produced = _produced_clip_keys(db_path)
    fresh = [g for g in gems if not _gem_produced(g, produced)]
    if tone == "duygu":
        # DUYGU: kısa klip mikro-dramı taşımaz (~30-40sn ister) → bilinen-kısa klibi ELE.
        fresh = [g for g in fresh
                 if not (0 < (g.get("duration") or 0) < CURATED_DUYGU_MIN_S)]
    elif tone == "mizah":
        # MİZAH: çok kısa klip espri kurulumuna yer bırakmaz (short 947, 12sn) → ELE.
        fresh = [g for g in fresh
                 if not (0 < (g.get("duration") or 0) < CURATED_MIZAH_MIN_S)]
    if not fresh:
        log.warning("  kürate[oto]: taze cevher yok (hepsi üretilmiş / havuz boş / kısa)")
        return None, None
    fresh.sort(key=lambda g: -_gem_rank(g))
    # TONA-DUYARLI SEÇİM: en iyi adayları vision ile kanalın tonuna göre skorla — mizah
    # kanalı 'merak/gülme', DUYGU kanalı 'kahramanlık/kurtarma' klibi seçer (@NedenHayvan).
    try:
        from short_bot.curated_rank import score_curiosity
        from short_bot.pipeline import resolve_ai_call
        _vis = resolve_ai_call(settings, secrets, "vision")
        fresh = score_curiosity(fresh, vision_call=_vis, top_n=12, tone=tone, log=log)
    except Exception as e:  # noqa: BLE001 — skor düşerse engagement sırası (fail-open)
        log.info(f"  kürate[oto]: ton-skoru atlandı ({e})")
    if tone == "duygu":
        # EŞİK: güçlü duygusal klip yoksa ÜRETME (zayıf derp'i zorlama — short 934 dersi).
        _strong = [g for g in fresh if (g.get("curiosity") or 0) >= DUYGU_MIN_SCORE]
        if not _strong:
            best = max((g.get("curiosity") or 0) for g in fresh) if fresh else 0
            log.warning(f"  kürate[oto]: yeterince güçlü duygusal klip yok (en iyi skor "
                        f"{best}<{DUYGU_MIN_SCORE}) → üretim atlandı")
            return None, None
        fresh = _strong
    # En iyi adayları sırayla dene; WATERMARK'LI (temizlenemeyen) olanı ATLA → temiz video.
    for gem in fresh[:8]:
        log.info(f"  kürate[oto]: deneniyor ⬆{gem.get('ups')} {gem.get('orient')} "
                 f"r/{gem.get('sub')} — {gem.get('title', '')[:60]}")
        try:
            return produce_curated(
                gem, channel, settings=settings, secrets=secrets, db_path=db_path,
                output_root=output_root, music_root=music_root,
                templates_dir=templates_dir, log=log)
        except CuratedWatermarkError as e:
            log.info(f"  kürate[oto]: watermark'lı → atlandı ({e})")
            continue
        except CuratedClipError as e:
            log.info(f"  kürate[oto]: indirilemedi → atlandı ({e})")
            continue
    log.warning("  kürate[oto]: denenen adayların hepsi elendi (watermark/indirilemez) "
                "→ temiz cevher yok")
    return None, None
