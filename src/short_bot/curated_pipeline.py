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
# STORYBOARD KALİTE eşiği (short 992: 'hiç komik bir şey yok, çok zayıf'). tone-fit klibin DOĞRU
# tonda mı olduğuna bakar, GÜÇLÜ mü olduğuna değil; thumbnail-skoru 'gülen yüz' kapağına aldanır.
# judge_clip_quality GERÇEK storyboard'dan izlenme-değeri yargılar → engaging=False veya bundan
# düşük skor = sıradan/zayıf → oto-üretimde ATLA (DUYGU_MIN_SCORE'un tüm-tonlar/storyboard karşılığı).
CURATED_QUALITY_MIN = 6
# FİNAL QA eşiği (kullanıcı: 'zevksiz/anlamsız videolar çıkabiliyor'): bitmiş (render edilmiş)
# video storyboard'dan 'yayınlanır mı' yargısı — bundan düşükse dosya silinir, klip atlanır.
FINAL_QA_MIN = 6


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

    # ELENEN-HAFIZASI: bu klibin KALICI yargısını (produced/watermark/heavy-text/off-tone) kaydet
    # → aynı klip bir daha indirilip vision'la kontrol edilmesin (funnel israfı). Geçici hatada
    # (indirme 403 / vision None) ÇAĞRILMAZ → tekrar denensin.
    from short_bot.curated_pool import clip_key as _pool_clip_key, mark_seen as _mark_seen_fn

    def _remember(verdict: str):
        try:
            _mark_seen_fn(init_db(db_path), channel.slug, _pool_clip_key(video_url), verdict)
        except Exception:  # noqa: BLE001 — hafıza best-effort
            pass

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
            # KALICI ÖLÜ KLİP: v.redd.it 403/404/410 = post silinmiş/medya gitmiş — hatırla,
            # yoksa aynı klip her koşuda en-iyi-aday seçilip yeniden 403 alıyor (tek güçlü
            # adaysa koşu hep 'temiz cevher yok'a kilitleniyor). Timeout/5xx/ağ = geçici → hatırlama.
            if getattr(getattr(e, "response", None), "status_code", None) in (403, 404, 410):
                _remember("gone")
            raise CuratedClipError(f"klip indirilemedi ({video_url}): {e}") from e
        # TEMİZLİK (SP4): hafif/kenar watermark → delogo (yazılı klip de kullanılabilir);
        # ağır kaplama temizlenmez. Kanal flag'i kapalıysa atlanır.
        if getattr(reel, "curated_clean", True) and vision is not None:
            from short_bot.curated_clean import clean_if_needed, watermark_uncleanable
            clip, _wm = clean_if_needed(clip, vision_call=vision,
                                        ffmpeg_path=settings.ffmpeg_path,
                                        out_path=td / "clean.mp4")
            # TEMİZLİK FAIL-CLOSED (short 968: TikTok logolu klip, tespit None dönünce fail-OPEN
            # ile geçmişti). _wm None = vision temizliği DOĞRULAYAMADI (hata) → klibi KULLANMA
            # (kirli olabilir). Yalnız vision TEMİZ dedi (_wm.present=False) ya da temiz
            # kırpıldıysa devam. Oto: çağıran sıradaki adaya geçer; manuel: net hata.
            if _wm is None:
                raise CuratedWatermarkError(
                    "Klip temizliği DOĞRULANAMADI (vision hatası) → atlanıyor (kirli/logolu "
                    "olabilir; güvenlik için fail-closed).")
            if _wm.present:
                log.info(f"  kürate: watermark {_wm.regions} (kaplıyor={_wm.covers_subject})")
                # Temizlenemeyen (hareketli TikTok / kaplayan) → bu klip WATERMARK'LI
                # kalır; kullanma. Manuel: net hata. Oto: çağıran sıradaki adaya geçer.
                if watermark_uncleanable(_wm):
                    _remember("watermark")
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
            # GÖMÜLÜ-YAZI REDDİ (kullanıcı: 'sadece temiz görüntü'; short 968 'THIS IS JAPAN'
            # banner + İngilizce/Japonca altyazılar geçmişti). Banner KIRPILDIKTAN SONRA çalışır:
            # kırpılabilir tek caption kurtulur, kırpılamayan altyazı/çoklu-katman (editlenmiş
            # repost) elenir. Doğrulanamazsa (None) → fail-CLOSED reddet. Ağır gömülü yazı çoğu
            # zaman sorunlu/repost içeriğe de işaret eder (bkz. 968 rencide edici altyazılar).
            from short_bot.curated_clean import detect_heavy_text
            _ht = detect_heavy_text(clip, vision_call=vision, ffmpeg_path=settings.ffmpeg_path)
            if _ht is None:
                raise CuratedWatermarkError(
                    "Gömülü-yazı DOĞRULANAMADI (vision hatası) → klip atlanıyor (fail-closed).")
            if _ht.heavy:
                _remember("heavy-text")
                raise CuratedWatermarkError(
                    f"Klip gömülü yazıyla dolu ({_ht.kinds}) — editlenmiş repost, temiz görüntü "
                    "değil (kırpılamayan altyazı/banner). Temiz bir klip seç.")
        # NOT: Kürate klibi renk grade'i (reel_assembler, GRADE_TARGET_LUMA≈0.45'e normalize
        # + vignette) diğer kanallarla AYNI uygulanır. Bir ara gölge-kaldıran ön-aydınlatma
        # (brighten_if_dark) eklenmiş + grade kapatılmıştı ama çıktı FAZLA açık/yıkanmış
        # oluyordu (short 917, YAVG 150) → kullanıcı isteğiyle GERİ ALINDI, eski grade look.
        clip_dur = _clip_duration_s(clip, settings.ffmpeg_path)

        log.info("  kürate: vision ile GERÇEK aksiyon okunuyor…")
        desc = _describe_clip(clip, vision_call=vision, ffmpeg_path=settings.ffmpeg_path)
        if not desc.strip():
            # CuratedClipError (RuntimeError DEĞİL): geçici vision hatası oto-loop'ta SIRADAKİ
            # adaya geçsin, TÜM run'ı çökertmesin (denetim bulgusu: çıplak RuntimeError loop'un
            # except'lerine takılmayıp auto_produce_curated'ı öldürüyordu).
            raise CuratedClipError("kürate: vision klibi tarif edemedi (geçici hata) → atlanıyor")
        log.info(f"  kürate: vision → {desc}")

        # TON-KLİP UYUM KAPISI (DUYGU kanalı stadyumda Viking-kask komik klibini seçip zorla
        # 'kayıp/yas' draması yazdı — thumbnail emotion-skoru aldatıldı). Vision TARİFİNDEN klip
        # kanalın TONUNA gerçekten uyuyor mu (DUYGU=dokunaklı, mizah=komik) yargıla; UYMUYORSA
        # klip YANLIŞ kanalda → atla (oto: sıradaki aday; manuel: net neden). Fail-open (None→devam).
        _tone = getattr(reel, "curated_tone", "mizah")

        # POST-İNDİRME SÜRE KAPISI (denetim M3): harici kaynaklar (redgifs/streamable/gfycat) gem
        # duration=0 raporlayıp SEÇİM süre-filtrelerini (min-süre) ATLIYORDU → 5sn'lik derp DUYGU'ya
        # seçilebiliyordu (short 934 dersi 'zorlama'). GERÇEK indirilmiş süreyle doğrula: tona göre
        # çok kısaysa (mikro-dram/espri kurulamaz) atla. Objektif → seen'e yaz (tekrar denenmez).
        _min_s = CURATED_DUYGU_MIN_S if _tone == "duygu" else CURATED_MIZAH_MIN_S
        if 0 < clip_dur < _min_s:
            _remember("too-short")
            raise CuratedClipError(
                f"Klip çok kısa ({clip_dur:.0f}s < {_min_s}s, {_tone}) → atlanıyor "
                f"(kurulum+tırmanma+ödül için yer yok).")

        from short_bot.reel_narration import judge_tone_fit
        _tf = judge_tone_fit(desc, _tone, title=gem.get("title", ""), backend=llm.backend,
                             model=llm.model, api_key=llm.api_key, claude_path=llm.claude_path)
        if _tf is not None and not _tf.fits:
            _remember("off-tone")
            raise CuratedClipError(
                f"Klip '{_tone}' tonuna uymuyor ({_tf.reason}) → atlanıyor (yanlış kanal için).")

        # STORYBOARD KALİTE KAPISI (kullanıcı short 992: 'hiç komik bir şey yok, çok zayıf'):
        # tone-fit DOĞRU-ton'a bakar, GÜÇLÜ'ye değil; score_curiosity thumbnail'dan skorluyor →
        # 'gülen yüz' kapağı yüksek merak alıyor ama muted video sıradan (contagiouslaughter komik-
        # liği SESTE, biz sesi atıyoruz). judge_clip_quality GERÇEK 6-kare storyboard'dan izlenme-
        # değeri yargılar (992 → engaging=False, skor 3, 'iç şaka, kanca yok'). Zayıfsa oto-üretimde
        # ATLA → DUYGU_MIN_SCORE'un tüm-tonlar/storyboard karşılığı (zayıfı zorlama). Fail-open (None→devam).
        if vision is not None:
            from short_bot.curated_clean import judge_clip_quality
            _q = judge_clip_quality(clip, vision_call=vision,
                                    ffmpeg_path=settings.ffmpeg_path, tone=_tone,
                                    title=gem.get("title", ""))
            if _q is not None and (not _q.engaging or _q.score < CURATED_QUALITY_MIN):
                _remember("mundane")
                raise CuratedClipError(
                    f"Klip sıradan/zayıf (izlenme-skoru {_q.score}<{CURATED_QUALITY_MIN}: "
                    f"{_q.reason}) → atlanıyor (izlenesi/güçlü klip seç).")
            # SES-YÜKÜ KAPISI (kullanıcı: 'anlamsız videolar'): klibin etkisi SESTE ise
            # (kahkaha/diyalog/müzik — contagiouslaughter sınıfı) sessiz izlenince sıradanlaşır;
            # biz orijinal sesi atıp TTS basıyoruz → bu klip üretilmez. Klip özelliği KALICI.
            if _q is not None and not getattr(_q, "works_muted", True):
                _remember("audio-payload")
                raise CuratedClipError(
                    f"Klibin yükü SESTE ({_q.reason or 'kahkaha/diyalog'}) — orijinal ses "
                    f"atılıyor, sessiz hâli sıradan → atlanıyor (görsel-taşıyan klip seç).")

        # ZAMAN-SIRALI BEAT SHEET (kullanıcı short 990: 'sahneler ile cümleler oturmuyor'):
        # _describe_clip tüm klibi TEK BLOK özetliyor → zaman çizgisi eriyor, anlatıcı ödülü
        # (yardım/kavuşma) ERKEN açıyor (görüntü hâlâ 'düşüş'teyken) ve 'ikisi' derken kalabalık
        # taşıyor. KANITLANDI: ücretsiz vision bütünü verince olayları BİRLEŞTİRİYOR ama klibi
        # ÜÇE bölüp AYRI sorunca her dilimi DOĞRU/zaman-sıralı anlatıyor (sarı-tişört detayı +
        # 'kalabalık' sayısı doğru). Beat sheet'ten yazılan senaryo footage sırasına oturur;
        # boşsa blok desc'e düşer (fail-open, mevcut davranış). tone-fit'ten SONRA: yalnız
        # tonu geçen klip için hesaplanır (boşuna vision harcanmaz).
        narr_desc = desc
        if vision is not None:
            from short_bot.curated_clean import describe_clip_beats
            _beats = describe_clip_beats(clip, vision_call=vision,
                                         ffmpeg_path=settings.ffmpeg_path, duration_s=clip_dur)
            if _beats:
                narr_desc = _beats
                # İÇERİĞİ DE LOGLA: anlatımın TEK kaynağı bu metin. Eskiden yalnız '3 dilim'
                # yazıyordu ve 'anlatım neden böyle çıktı?' sorusu ancak klibi yeniden
                # indirip vision harcayarak yanıtlanabiliyordu (short 1140 ve 1154'te iki
                # kez gerekti; klip silinmişse imkânsız).
                log.info(f"  kürate: zaman-sıralı beat sheet ({_beats.count(chr(10)) + 1} "
                         f"dilim) → anlatım footage sırasına oturur\n{_beats}")

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

        # REVEAL ÇIPASI: klipteki ödül/dönüm anının oranı → render'da anlatımın ödül
        # cümlesiyle ÇAKIŞTIRILIR (short 1078: kucaklaşma ~%41'de görünüyor, anlatım
        # ~%61'de söylüyordu). 2 sahneli klipte geçiş ZATEN dönüm anıdır → o oranı
        # yeniden kullan (boşuna vision harcama); tek sahnede ayrı tespit gerekir.
        reveal_frac = scene_split
        if vision is not None and reveal_frac is None:
            from short_bot.curated_clean import detect_reveal_anchor
            reveal_frac = detect_reveal_anchor(clip, vision_call=vision,
                                               ffmpeg_path=settings.ffmpeg_path)
            if reveal_frac is not None:
                log.info(f"  kürate: dönüm anı ~%{round(reveal_frac*100)} → reveal çıpası "
                         f"(ödül cümlesi o kareye oturtulacak)")

        target = curated_target(clip_dur, reel.target_duration_s)
        log.info(f"  kürate: klip {clip_dur:.1f}s → video hedefi {target} (loop önleme)")
        narration = write_curated_narration(
            title_seed, narr_desc, channel=channel, subject="clip",
            claude_path=narr_llm.claude_path, model=narr_llm.model,
            backend=narr_llm.backend, api_key=narr_llm.api_key,
            seed=seed, target_duration_s=target, scene_split=scene_split,
            comments=comments, reveal_frac=reveal_frac)
        from short_bot.reel_narration import budget_unit as _bu
        _unit = "karakter" if _bu(channel.language) == "characters" else "kelime"
        log.info(f"  kürate: senaryo {narration.word_count()} {_unit} | "
                 f"başlık='{narration.title}' kapak='{narration.cover_title}'")

        # SADAKAT KAPISI (kullanıcı: 'teyit edecek yapı lazım'): anlatım GERÇEK videoyu mu
        # anlatıyor yoksa olay mı uydurdu (short 962: olmayan 'yavru bırakıldı→geri döndü')?
        # Storyboard + anlatıma bak; uydurmuşsa GERİ BİLDİRİMLE bir kez yeniden yaz. Fail-open.
        if vision is not None:
            from short_bot.curated_clean import verify_curated_narration
            _chk = verify_curated_narration(clip, narration.full_text(),
                                            vision_call=vision, ffmpeg_path=settings.ffmpeg_path,
                                            title=gem.get("title", ""))
            # not-faithful İSE yeniden yaz — mismatch BOŞ OLSA BİLE (denetim bulgusu: zayıf model
            # 'faithful=false, mismatch=""' dönünce eski AND-guard rewrite'ı ATLAYIP uydurma
            # anlatımı YAYINLIYORDU). Reason boşsa jenerik geri bildirim ver.
            if _chk is not None and not _chk.faithful:
                # DİREKTİF geri bildirim (denetim short 999): sadece 'X yok' demek yetmiyordu,
                # rewrite uydurmayı KORUYABİLİYORDU. Net emir: o varlığı/olayı TAMAMEN ÇIKAR.
                _why = _chk.mismatch or ("Anlatımda ekranda GÖRÜNMEYEN bir olay/varlık var.")
                _fb = (f"SADAKAT HATASI: {_why} Bu UYDURMA varlığı/olayı anlatımdan TAMAMEN SİL; "
                       f"onunla ilgili tüm cümleleri çıkar. YALNIZ karelerde GERÇEKTEN görüneni "
                       f"anlat — olmayan ikinci hayvan/nesne/kişi ya da alt-olay EKLEME.")
                log.info(f"  kürate[sadakat]: anlatım sadık DEĞİL ({_chk.mismatch or 'reason yok'}) "
                         f"→ direktif geri bildirimle yeniden yazılıyor")
                narration = write_curated_narration(
                    title_seed, narr_desc, channel=channel, subject="clip",
                    claude_path=narr_llm.claude_path, model=narr_llm.model,
                    backend=narr_llm.backend, api_key=narr_llm.api_key,
                    seed=seed, target_duration_s=target, scene_split=scene_split,
                    comments=comments, feedback=_fb, reveal_frac=reveal_frac)
                _chk2 = verify_curated_narration(clip, narration.full_text(),
                                                 vision_call=vision,
                                                 ffmpeg_path=settings.ffmpeg_path,
                                                 title=gem.get("title", ""))
                if _chk2 is not None and not _chk2.faithful:
                    # KALICI UYDURMA → çöp YAYINLAMA, klibi ATLA (denetim 999: direktif rewrite'a
                    # rağmen uydurma kalırsa fail-open çöpü basıyordu). Oto-loop sıradaki adaya
                    # geçer. seen'e YAZMA: klip iyi, anlatım rastgele kötü çıktı — sonraki koşuda
                    # (farklı seed) düzgün anlatılabilir, kalıcı blacklist HAKSIZ olur.
                    raise CuratedClipError(
                        f"Anlatım iki denemede de UYDURMA içeriyor ({_chk2.mismatch}) → "
                        f"atlanıyor (çöp yayınlanmaz, klip hatırlanmaz).")
                else:
                    log.info("  kürate[sadakat]: yeniden yazım SADIK ✓")

        # NETLİK/TUTARLILIK KAPISI (short 980: 'videodan hiçbir şey anlamadım'): anlatım
        # TUTARLI + ANLAŞILIR mı (izleyici olayı takip eder mi). METİN-tabanlı İKİNCİ LLM (yazan
        # Sonnet değil, ucuz metin backend 'llm' → bağımsız perspektif) 'akıllı ama anlamsız'
        # varyansını yakalar; değilse geri bildirimle bir kez yeniden yaz. Fail-open.
        from short_bot.reel_narration import judge_narration_clarity
        _clr = judge_narration_clarity(narration.full_text(), narr_desc, tone=_tone,
                                       backend=llm.backend, model=llm.model, api_key=llm.api_key,
                                       claude_path=llm.claude_path)
        if _clr is not None and not _clr.clear:  # reason BOŞ olsa bile yeniden yaz (denetim)
            # DİREKTİF + VISION-ANCHORED (denetim short 1000: netlik yakaladı ama rewrite yine
            # kopuk hikâye yazdı → fail-open yayınladı). Modele NET emir + neyin GERÇEK olduğunu
            # hatırlat: yalnız beat sheet'teki GÖRÜNENİ anlat, uydurma geçmiş/sebep/varlık EKLEME.
            _reason = _clr.reason or "İzleyici olayı takip edemiyor."
            _cfb = (f"{_reason} DÜZELT: yukarıdaki 'WHAT IS ACTUALLY ON SCREEN' beat sheet'inde "
                    f"GERÇEKTEN ne varsa YALNIZ onu, BASİT ve NET anlat. (a) Uydurma geçmiş/sebep "
                    f"('neden geç çıkar', 'gece yürürdü', 'çünkü şöyleydi') ve olmayan varlık "
                    f"EKLEME; kopuk sebep-sonuç kurma. (b) ZORLAMA/ÜST ÜSTE BENZETME YIĞMA "
                    f"('kaleci pozu', 'kanat gibi', 'cesaret kaydı' gibi sahneye oturmayan laflar "
                    f"— short 1004): olayı DÜZ ve net anlat, EN FAZLA bir yerini bulan benzetme + "
                    f"tek NET punchline. Her cümle sahnedeki ana bağlı ve gerçekten anlamlı olsun.")
            log.info(f"  kürate[netlik]: anlatım net DEĞİL ({_clr.reason or 'reason yok'}) "
                     f"→ direktif geri bildirimle yeniden yazılıyor")
            narration = write_curated_narration(
                title_seed, narr_desc, channel=channel, subject="clip",
                claude_path=narr_llm.claude_path, model=narr_llm.model,
                backend=narr_llm.backend, api_key=narr_llm.api_key,
                seed=seed, target_duration_s=target, scene_split=scene_split,
                comments=comments, feedback=f"ANLAŞILIRLIK: {_cfb}",
                reveal_frac=reveal_frac)
            _clr2 = judge_narration_clarity(narration.full_text(), narr_desc, tone=_tone,
                                            backend=llm.backend, model=llm.model, api_key=llm.api_key,
                                            claude_path=llm.claude_path)
            if _clr2 is not None and not _clr2.clear:
                # FAIL-CLOSED (kullanıcı: 'anlamsız videolar çıkabiliyor'): iki denemede de
                # net değilse ÇÖP YAYINLAMA — klibi atla (sadakat kapısıyla aynı sözleşme).
                # seen'e YAZMA: klip iyi olabilir, anlatım şanssız çıktı — sonraki koşuda
                # (farklı seed) düzgün anlatılabilir; kalıcı blacklist haksız olur.
                _r2 = _clr2.reason or "izleyici olayı takip edemiyor"
                raise CuratedClipError(
                    f"Anlatım iki denemede de NET değil ({_r2}) → atlanıyor "
                    f"(çöp yayınlanmaz, klip hatırlanmaz).")
            log.info("  kürate[netlik]: yeniden yazım NET ✓")

        # DİL KAPISI — YALNIZ TÜRKÇE DIŞI KANALLAR (operatör metni okuyamıyor).
        #
        # Buraya kadarki iki kapı bu boşluğu KAPATMAZ: sadakat kapısı anlatımı GÖRÜNTÜYLE
        # karşılaştırır, netlik kapısı MANTIĞA bakar. Hedef dilde bozuk ama tutarlı bir
        # cümle ikisini de geçer — ve Türkçe kanalda operatörün yakaladığı o kusuru burada
        # yakalayacak kimse yok. Bu yüzden yerli-okur yargısı KAPI (fail-closed), geri
        # çeviri ise PENCERE (fail-open, panelde gösterilir).
        back_tr = ""
        if channel.language != "tr":
            from short_bot.lang_review import back_translate, judge_native_text
            def _judge_native():
                return judge_native_text(narration.full_text(), language=channel.language,
                                         backend=llm.backend, model=llm.model,
                                         api_key=llm.api_key, claude_path=llm.claude_path)

            _nat = _judge_native()
            # ONARIM TURU SAYISI. Yargıç her çağrıda YALNIZ EN KÖTÜ tek kusuru bildiriyor
            # (prompt öyle istiyor: net ve uygulanabilir olsun). Yani iki kusurlu bir
            # metin tek onarımla temizlenemez — ölçüldü (aday 71): 1. onarım '支え続ける'i
            # düzeltti, hemen ardından CTA kalıbı işaretlendi ve klip kaybedildi.
            # KAPI GEVŞEMİYOR: video yine 'doğal' yargısını almadan çıkamıyor; değişen
            # tek şey iyi bir klibi kaç denemede kurtarmaya çalıştığımız.
            _LANG_REPAIRS = 2
            _try = 0
            while _nat is not None and not _nat.natural and _try < _LANG_REPAIRS:
                _try += 1
                _iss = _nat.issue or "Metin hedef dilde doğal değil."
                # ONARIM, YENİDEN YAZIM DEĞİL. Ölçüldü (2026-07-24, iki klip): her
                # yeniden yazım SIFIRDAN yeni bir taslak üretiyor ve YENİ bir dil kusuru
                # getiriyor (1. deneme nezaket karışıklığı → 2. deneme farklı bir çeviri
                # kokusu) — yani yakınsamıyor, klip boşuna kaybediliyor. Modele önceki
                # metni geri verip SADECE işaretlenen ifadeyi değiştirmesini söylemek
                # yakınsayan tek yol.
                _prev = narration.full_text()
                _lfb = (f"DİL ONARIMI (yeniden yazım DEĞİL).\n\n"
                        f"ÖNCEKİ METİN:\n{_prev}\n\n"
                        f"YERLİ OKUR ŞUNU İŞARETLEDİ: {_iss}\n\n"
                        f"YAP: yukarıdaki metni AYNEN yeniden üret, YALNIZCA işaretlenen "
                        f"ifadeyi ana dili o dil olan birinin söyleyeceği hâliyle değiştir. "
                        f"Başka hiçbir cümleyi, kelimeyi, sırayı ya da noktalamayı DEĞİŞTİRME. "
                        # KRİTİK: bu kapı EN SONDA; tetiklediği yeniden yazım sadakat ve
                        # netlik kapılarından BİR DAHA GEÇMİYOR. Yani burada eklenen bir
                        # uydurma kimseye yakalanmaz. Kilidi geri bildirime koyuyoruz.
                        f"Anlatılan olaylar, sıraları, sayılar ve ton AYNEN kalsın — yeni "
                        f"olay/varlık/detay EKLEME, hiçbirini çıkarma. Yeni bir taslak "
                        f"yazma; bu bir DÜZELTMEDİR.")
                log.info(f"  kürate[dil]: anlatım {channel.language} dilinde DOĞAL değil "
                         f"({_iss}) → onarım {_try}/{_LANG_REPAIRS}")
                narration = write_curated_narration(
                    title_seed, narr_desc, channel=channel, subject="clip",
                    claude_path=narr_llm.claude_path, model=narr_llm.model,
                    backend=narr_llm.backend, api_key=narr_llm.api_key,
                    seed=seed, target_duration_s=target, scene_split=scene_split,
                    comments=comments, feedback=_lfb, reveal_frac=reveal_frac)
                _nat = _judge_native()

            if _nat is not None and not _nat.natural:
                # FAIL-CLOSED: operatör bu kusuru göremez, sonradan da fark etmez.
                # seen'e YAZMA — klip iyi, anlatım şanssız çıktı (netlik kapısıyla aynı).
                raise CuratedClipError(
                    f"Anlatım {_LANG_REPAIRS} onarımda da {channel.language} dilinde doğal "
                    f"değil ({_nat.issue or 'gerekçe yok'}) → atlanıyor.")
            elif _nat is not None and _try:
                log.info(f"  kürate[dil]: onarım sonrası DOĞAL ✓ ({_try} tur)")
            elif _nat is None:
                log.warning("  kürate[dil]: yerli okur YARGILAYAMADI → metin yargısız "
                            "geçiyor (fail-open) — geri çeviriden elle kontrol et")
            else:
                log.info("  kürate[dil]: anlatım doğal ✓")

            # PENCERE: anlatımın Türkçesi. Kapı değil — patlarsa üretim sürer.
            back_tr = back_translate(narration.full_text(), language=channel.language,
                                     backend=llm.backend, model=llm.model,
                                     api_key=llm.api_key, claude_path=llm.claude_path)
            if back_tr:
                log.info(f"  kürate[dil] geri çeviri: {back_tr}")

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
            curated_clip=clip, curated_narration=narration,
            curated_reveal_frac=reveal_frac)
        render_ms = int((time.perf_counter() - t0) * 1000)

    # FİNAL QA KAPISI (kullanıcı: 'zevksiz/anlamsız videolar çıkabiliyor'): buraya kadarki
    # tüm kapılar render ÖNCESİ proxy'lerde (ham klip storyboard'ı + metin) çalıştı — bitmiş
    # ürünü (kesim + altyazı çipleri + tempo + vurgular) kimse izlemiyordu. BİTMİŞ videoyu
    # vision'la yargıla; izlenmez/senkronsuz/ton-dışıysa dosyayı sil, Short kaydı AÇMA, klibi
    # atla. None (vision hıçkırığı) → fail-open: tüm kapılardan geçmiş render çöpe atılmaz.
    # seen'e YAZMA: klip iyi olabilir, anlatım/kurgu şanssız çıktı (sonraki koşu farklı seed).
    if vision is not None:
        from short_bot.curated_clean import judge_final_video
        _fq = judge_final_video(out_path, narration.full_text(), vision_call=vision,
                                ffmpeg_path=settings.ffmpeg_path, tone=_tone, log=log)
        if _fq is not None and (not _fq.watchable or not _fq.sync_ok or not _fq.tone_ok
                                or _fq.score < FINAL_QA_MIN):
            try:
                Path(out_path).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 — silinemese de kayıt açılmaz
                pass
            raise CuratedClipError(
                f"FİNAL QA: bitmiş video yayınlanabilir değil (skor {_fq.score}, "
                f"izlenir={_fq.watchable}, senkron={_fq.sync_ok}, ton={_fq.tone_ok}: "
                f"{_fq.reason}) → dosya silindi, klip atlanıyor (çöp yayınlanmaz).")
        if _fq is not None:
            log.info(f"  kürate[final-qa]: yayınlanabilir ✓ (skor {_fq.score})")
        else:
            # Fail-open KORUNUR (render çöpe atılmaz) ama SESSİZ DEĞİL: bu video
            # yayına yargılanmadan gitti, operatör elle baksın (short 1077).
            log.warning("  kürate[final-qa]: YARGILANAMADI → video yargısız kaydediliyor "
                        "(fail-open) — elle kontrol et")

    # Short kaydı: /shorts'ta görünür + mevcut yükleme yolu kullanılabilir.
    # script_json yükleme anında YT başlık/açıklamasını besler (bkz. youtube route).
    seo = (narration.title or title_seed)[:100]
    script_json = json.dumps({
        "header_top": narration.cover_title or narration.hook,
        "header_bottom": "",
        "body_paragraph": narration.full_text(),
        # Türkçe DIŞI kanallarda anlatımın Türkçesi — panelde yan yana gösterilir.
        # Operatörün videoyu YAYINLAMADAN ÖNCE "bu ne diyor" sorusunu yanıtlayabilmesi
        # için tek yol bu (bkz. lang_review). Türkçe kanalda boş kalır.
        "body_paragraph_tr": back_tr,
        "title": seo,
        # İngilizce başlık → YouTube çok-dilli başlık (küresel Shorts akışı). Boşsa yok sayılır.
        "title_en": (getattr(narration, "title_en", "") or "")[:100],
        "source_permalink": gem.get("permalink", ""),
        "source_video_url": video_url,   # dedup: aynı klip iki kez üretilmesin
    }, ensure_ascii=False)
    # SÜRE = YAYINLANAN videonun süresi, kaynak klibin değil. Kürate klibi setpts ile
    # videoya oturtuluyor (hızlandırma/yavaşlatma) → ikisi tutmuyor: short 1140'ta panel
    # 55sn gösteriyordu, video 41.3sn'ydi. Ölçülemezse (ffprobe hıçkırığı) kaynak süreye düş.
    _pub_dur = _clip_duration_s(out_path, settings.ffmpeg_path) or clip_dur
    eng = init_db(db_path)
    short_id = record_short(
        eng, channel=channel.slug, rss_item_guid=None, title=seo,
        file_path=str(out_path), duration_s=int(round(_pub_dur)) or None,
        script_json=script_json, render_ms=render_ms)
    log.info(f"  kürate: Short kaydedildi id={short_id} → {out_path.name}")
    _remember("produced")   # elenen-hafızası: üretileni de hatırla (çift üretimi önler)
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
    from short_bot.reddit_gems import (DEFAULT_DUYGU_SUBS, DEFAULT_KARMA_SUBS,
                                        DEFAULT_SUBS, find_gems)
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
        DEFAULT_DUYGU_SUBS if tone == "duygu"
        else DEFAULT_KARMA_SUBS if tone == "karma"
        else DEFAULT_SUBS)
    t = getattr(reel, "curated_time", "week")
    # ELENEN-HAFIZASI + PENCERE ROTASYONU: seen (kalıcı yargılanmış) büyüdükçe zaman penceresini
    # GENİŞLET (month → +year → +all) → önceki koşularda görülenler tükendikçe DAHA DERİN dilim
    # keşfet ('aynılar geliyor' biter). Fresh, üretilmiş + seen'e karşı dedup'lanır → elenen klip
    # bir daha İNDİRİLİP vision'la kontrol edilmez (funnel israfı biter). Yalnız KALICI yargılar
    # hafızada; geçici indirme/vision hatası kaydedilmez → tekrar denenir.
    from short_bot.curated_pool import clip_key as _pool_clip_key
    from short_bot.curated_pool import mark_seen as _mark_seen
    from short_bot.curated_pool import seen_keys
    from short_bot.db import init_db as _init_db
    _seen = seen_keys(_init_db(db_path), channel.slug)
    _n = len(_seen)
    _tws = ["month"] + (["year"] if _n >= 150 else []) + (["all"] if _n >= 400 else [])
    log.info(f"  kürate[oto]: {len(subs)} sub taranıyor (ton={tone}, pencere={_tws}, "
             f"elenen-hafızası={_n})")
    gems = find_gems(cid, csec, subreddits=subs, t=t, t_windows=_tws,
                     min_ups=getattr(reel, "curated_min_ups", 500),
                     max_duration=getattr(reel, "curated_max_duration", 90))
    produced = _produced_clip_keys(db_path)
    fresh = [g for g in gems if not _gem_produced(g, produced)
             and _pool_clip_key(g.get("video_url", "")) not in _seen]
    log.info(f"  kürate[oto]: {len(gems)} ham → {len(fresh)} taze (üretilmiş+elenen düşüldü)")
    if tone == "duygu":
        # DUYGU: kısa klip mikro-dramı taşımaz (~30-40sn ister) → bilinen-kısa klibi ELE.
        fresh = [g for g in fresh
                 if not (0 < (g.get("duration") or 0) < CURATED_DUYGU_MIN_S)]
    elif tone in ("mizah", "karma"):
        # MİZAH/KARMA: çok kısa klip espri/comeuppance kurulumuna yer bırakmaz (short 947) → ELE.
        fresh = [g for g in fresh
                 if not (0 < (g.get("duration") or 0) < CURATED_MIZAH_MIN_S)]
    if not fresh:
        log.warning("  kürate[oto]: taze cevher yok (hepsi üretilmiş / havuz boş / kısa)")
        return None, None
    fresh.sort(key=lambda g: -_gem_rank(g))
    # TONA-DUYARLI SEÇİM: en iyi adayları vision ile kanalın tonuna göre skorla — mizah
    # kanalı 'merak/gülme', DUYGU kanalı 'kahramanlık/kurtarma' klibi seçer (@NedenHayvan).
    _vis = None
    _score_fn = None
    try:
        from short_bot.curated_rank import score_curiosity
        from short_bot.pipeline import resolve_ai_call
        _score_fn = score_curiosity
        _vis = resolve_ai_call(settings, secrets, "vision")
        # DERİN HAVUZ (find_gems ~1200 taze) → GENİŞ skorla ki temiz+kaliteli aday havuzu
        # geniş olsun (watermark'lı viral repost'lar elenince altında temizi kalsın). 30→60:
        # DUYGU eşiği (emotion≥7) + yazı-kapak elemesi top_n'i sertçe daraltıyordu; 30'da güçlü
        # aday ~5'e düşüp hepsi kirli çıkınca 'temiz cevher yok' (run 1143). 60 skorlanınca güçlü
        # havuz ~2x → biri temiz çıkma olasılığı belirgin artar (skor bedava, Google havuz).
        fresh = score_curiosity(fresh, vision_call=_vis, top_n=60, tone=tone, log=log)
    except Exception as e:  # noqa: BLE001 — skor düşerse engagement sırası (fail-open)
        log.info(f"  kürate[oto]: ton-skoru atlandı ({e})")

    def _remember_scored():
        """Skor-aşaması KALICI yargılarını hafızaya yaz (kullanıcı: 'milyonlarca video var,
        bulamıyor'). Eskiden yalnız üretim-aşaması yargıları seen'e yazılıyordu (~1-3/koşu) →
        top-60 skor penceresi her koşu AYNI (ay-topu statik) klipleri yeniden skorluyor, 1100+
        taze aday pencereye hiç giremiyordu. Yazılı-kapak + eşik-altı skor kalıcıdır (thumbnail
        değişmez) → hatırla; seen büyüyünce pencere rotasyonu (year/all) da devreye girer.
        Geçici skor hatası (score_err) yazılMAZ. Idempotent (OR IGNORE) — iki kez çağrılabilir."""
        try:
            _eng = _init_db(db_path)
            _weak = (lambda c: c < DUYGU_MIN_SCORE) if tone == "duygu" else (lambda c: c <= 3)
            for g in gems:
                _k = _pool_clip_key(g.get("video_url", ""))
                if not _k or _k in _seen or g.get("score_err"):
                    continue
                _c = g.get("curiosity")
                if g.get("has_text"):
                    _mark_seen(_eng, channel.slug, _k, "heavy-text")
                elif _c is not None and _weak(_c):
                    _mark_seen(_eng, channel.slug, _k, "weak-score")
        except Exception as e:  # noqa: BLE001 — hafıza best-effort, koşuyu düşürmez
            log.info(f"  kürate[oto]: skor-yargısı hafızaya yazılamadı ({e})")

    if tone == "duygu":
        # EŞİK: güçlü duygusal klip yoksa ÜRETME (zayıf derp'i zorlama — short 934 dersi).
        # AMA yalnız vision GERÇEKTEN skorladıysa: skorlama çökerse (hepsi curiosity=None) sert
        # eşik üretimi SESSİZCE engelliyordu (kullanıcı: 'no_candidates') → o zaman fail-open.
        _scored = any(g.get("curiosity") is not None for g in fresh)
        _strong = [g for g in fresh if (g.get("curiosity") or 0) >= DUYGU_MIN_SCORE]
        if not _strong and _scored and _vis is not None and _score_fn is not None:
            # DERİN TİER (denetim H4): top-60'ta güçlü YOK diye HEMEN pes etme — havuzda yüzlerce
            # aday 61+ sırada henüz skorlanmadı. Skorlanmamış kuyruğu bir kez daha skorla, güçlü ara
            # (aksi halde top-60 watermark-yoğun/zayıfsa devasa havuza rağmen 'no_candidates').
            _tail = [g for g in fresh if g.get("curiosity") is None]
            if _tail:
                try:
                    log.info(f"  kürate[oto]: top-60'ta güçlü duygusal yok → derin tier "
                             f"({min(60, len(_tail))} aday daha skorlanıyor)")
                    _tail = _score_fn(_tail, vision_call=_vis, top_n=60, tone=tone, log=log)
                    fresh = sorted(
                        [g for g in fresh if g.get("curiosity") is not None] + _tail,
                        key=lambda g: -g.get("final_score", 0))
                    _strong = [g for g in fresh if (g.get("curiosity") or 0) >= DUYGU_MIN_SCORE]
                except Exception as e:  # noqa: BLE001
                    log.info(f"  kürate[oto]: derin tier skorlanamadı ({e})")
        if _strong:
            fresh = _strong
        elif _scored:
            best = max((g.get("curiosity") or 0) for g in fresh) if fresh else 0
            log.warning(f"  kürate[oto]: yeterince güçlü duygusal klip yok (en iyi skor "
                        f"{best}<{DUYGU_MIN_SCORE}, derin tier dahil) → üretim atlandı")
            _remember_scored()   # boş koşuda da elenenler hatırlansın (pencere tıkanmasın)
            return None, None
        else:
            log.info("  kürate[oto]: vision skorlanamadı → engagement sırasıyla deneniyor "
                     "(fail-open, sessiz-boş önlendi)")
    elif tone in ("mizah", "karma"):
        # HAFİF MİZAH/KARMA TABANI (denetim H1): merak-baskın sıralama zaten zayıfı alta itiyor +
        # kalite kapısı eliyor; yine de vision'ın AÇIKÇA zayıf (skor≤3: komik-değil / karma-yok)
        # dediği klibi hiç DENEME. Skorlanmamış (None) klip KORUNUR (fail-open).
        _kept = [g for g in fresh if (g.get("curiosity") is None or g.get("curiosity") > 3)]
        if _kept:
            fresh = _kept
    _remember_scored()   # üretime geçmeden elenenleri hatırla (sonraki koşu taze dilim görsün)
    # En iyi adayları sırayla dene; WATERMARK'LI (temizlenemeyen) olanı ATLA → temiz video.
    # 8→20: DUYGU kaynakları (r/MadeMeSmile) watermark-yoğun repost; derin havuzda temiz olanı
    # bulana kadar dene (kirli aday watermark kapısında ~8sn'de erken elenir, pahalı değil).
    for gem in fresh[:20]:
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
            # ETİKET NÖTR OLMALI: CuratedClipError yalnız 'indirilemedi' değil — ton
            # uyumsuzluğu, sıradan/zayıf klip, ses-yükü, uydurma/anlaşılmaz anlatım ve
            # final QA reddi de bunu atıyor. Eski 'indirilemedi → atlandı' etiketi
            # operatörü ağ hatası aramaya yönlendiriyordu (koşu 1327 izlenirken yakalandı:
            # neden 'izlenme-skoru 4<6' iken satır 'indirilemedi' diyordu). Gerçek neden
            # zaten istisna metninde — etiket onu ezmesin.
            log.info(f"  kürate[oto]: aday elendi → sıradakine geçiliyor ({e})")
            continue
        except Exception as e:  # noqa: BLE001 — GÜVENLİK AĞI (denetim bulgusu): beklenmedik bir
            # hata (render/ffmpeg/vision) tek adayda patlarsa TÜM run'ı ÖLDÜRMESİN; logla, sıradaki
            # adaya geç. Geçici hata seen'e YAZILMAZ (tekrar denenebilir).
            log.warning(f"  kürate[oto]: beklenmedik hata ({type(e).__name__}: {e}) → sıradaki aday")
            continue
    log.warning("  kürate[oto]: denenen adayların hepsi elendi (temizlik/kalite/ton/anlatım "
                "kapıları — nedenler yukarıdaki satırlarda) → temiz cevher yok")
    return None, None
