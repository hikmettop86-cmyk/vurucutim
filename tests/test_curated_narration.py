"""SP3: kürate senaryo yazıcısı + klip-uzunluğundan süre türetme (loop önleme)."""
from types import SimpleNamespace

from short_bot.config import ReelConfig
from short_bot.reel_narration import (_CuratedDraft, curated_target,
                                      write_curated_narration)


def test_judge_narration_clarity(monkeypatch):
    """judge_narration_clarity: metin → NarrationClarity; tutarsız/kopuk anlatım clear=False
    (short 980: 'fizikçiler elektron ararken...'). Metin-tabanlı, vision GEREKMEZ."""
    from short_bot.reel_narration import NarrationClarity, judge_narration_clarity

    monkeypatch.setattr("short_bot.reel_narration.run_json",
                        lambda prompt, schema, **kw: NarrationClarity(clear=False,
                                                                      reason="kopuk metafor"))
    r = judge_narration_clarity("bağlamsız akıllı laf", "A man races a toy car",
                                backend="openrouter", model="m", api_key="k")
    assert r is not None and r.clear is False and "kopuk" in r.reason
    # boş anlatım → None (yargılanmaz)
    assert judge_narration_clarity("  ", "video", backend="openrouter", model="m") is None


def test_judge_tone_fit(monkeypatch):
    """judge_tone_fit: klip kanal tonuna uyuyor mu (DUYGU=dokunaklı, mizah=komik) — vision
    tarifinden metin yargısı; DUYGU kanalına komik klip fits=False (Viking-kask dersi)."""
    from short_bot.reel_narration import ToneFit, judge_tone_fit

    monkeypatch.setattr("short_bot.reel_narration.run_json",
                        lambda prompt, schema, **kw: ToneFit(fits=False, reason="komik, duygusuz"))
    r = judge_tone_fit("stadyumda Viking kask komik", "duygu",
                       backend="openrouter", model="m", api_key="k")
    assert r is not None and r.fits is False and "komik" in r.reason
    # boş tarif → None (yargılanmaz)
    assert judge_tone_fit("  ", "duygu", backend="openrouter", model="m") is None


def test_curated_target_derives_from_clip_length():
    assert curated_target(6, (30, 45)) == (12, 16)     # kısa → ~klip×2.6 (yavaşlatma kapsar)
    assert curated_target(20, (30, 45)) == (16, 20)    # yeterince uzun → ~klip boyu
    assert curated_target(60, (30, 45)) == (41, 45)    # kanal üstüyle capped
    assert curated_target(0, (30, 45)) == (30, 45)     # okunamadı → kanal hedefi


def test_write_curated_narration_faithful_build(monkeypatch):
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    draft = _CuratedDraft(
        hook="Su tipe bak hele", beats=["Bir kedi burada", "Iki goz kirpar",
                                        "Uc makine saray"],
        close="Kapanis cumlesi", mood="upbeat",
        title="Kedi basligi seo", cover_title="EN RAHAT TIP")
    monkeypatch.setattr("short_bot.reel_narration.run_json", lambda *a, **k: draft)
    n = write_curated_narration("You'll do the laundry later",
                                "A cat resting in a dryer.", channel=ch, subject="cat")
    assert n.hook == "Su tipe bak hele"
    assert len(n.beats) == 3
    assert all(b.visual_query == "cat" for b in n.beats)   # tek hazır klibe sabit
    assert n.title == "Kedi basligi seo"
    assert n.cover_title == "EN RAHAT TIP"


def test_write_curated_narration_single_call_deterministic_budget(monkeypatch):
    # CLI Sonnet ~50sn/çağrı → TEK LLM çağrısı (burst yok, maliyet yok). Taşan senaryo
    # LLM YERİNE deterministik (fit_word_budget) kısaltılır: SONDAN beat atar, MIN_BEATS'e
    # (3) sığdırır. Böylece klip gerilip loop'lamaz ve ekstra çağrı yapılmaz.
    long_beats = ["kelime " * 20 for _ in range(5)]   # 5 taşkın beat
    over = _CuratedDraft(hook="cok uzun bir hook cumlesi buraya", beats=long_beats,
                         close="cok uzun bir kapanis cumlesi", mood="upbeat")
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return over
    monkeypatch.setattr("short_bot.reel_narration.run_json", fake)
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    n = write_curated_narration("t", "d", channel=ch, subject="cat",
                                target_duration_s=(8, 12))
    assert calls["n"] == 1              # TEK çağrı (CLI Sonnet: burst yok, ücret yok)
    assert len(n.beats) == 3           # deterministik kısaltma MIN_BEATS'e indirdi (5→3)


def test_curated_prompt_includes_crowd_comments():
    # Üst Reddit yorumları prompt'a 'WHAT THE CROWD SAYS' bloğu olarak girer (vision'a
    # alternatif olay-bağlamı). Boş yorumda blok YAZILMAZ.
    from short_bot.reel_narration import build_curated_prompt
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    p = build_curated_prompt("t", "d", channel=ch,
                             comments=["he inserted it into the trachea", "poor turtle"])
    assert "ARKA-PLAN BAĞLAMI" in p and "trachea" in p
    # yorumlar bağlam; anlatıma META olarak sokulmaması UYARISI da olmalı
    assert "SOKMA" in p
    assert "ARKA-PLAN BAĞLAMI" not in build_curated_prompt("t", "d", channel=ch,
                                                           comments=[])


def test_strip_bard_removes_ozan_leading_and_trailing():
    from short_bot.reel_narration import _strip_bard
    assert _strip_bard("Ozan der ki; saray dediğin makine içiymiş!") == "Saray dediğin makine içiymiş!"
    assert _strip_bard("Bu rahatlık vergiye tabi olmalı, Ozan yazdı.") == "Bu rahatlık vergiye tabi olmalı."
    assert _strip_bard("Aşık Kedi der ki: sıcak köşeyi bulan kazanır") == "Sıcak köşeyi bulan kazanır."
    assert _strip_bard("Tapu onda. Ozan der ki; krallar beklenir.") == "Tapu onda."   # nokta-sonrası
    # ozan yok → dokunma
    assert _strip_bard("Çamaşır yıkanır, amca uyanmaz.") == "Çamaşır yıkanır, amca uyanmaz."


def test_humor_style_config_round_trips(tmp_path):
    from short_bot.config import ReelConfig
    assert ReelConfig(enabled=False).humor_style == ""      # varsayılan boş


def test_curated_prompt_carries_reveal_position():
    """REVEAL-SENKRON: klipteki dönüm ORANI prompt'a girmeli — ödül cümlesi metnin AYNI
    oranında başlasın (short 1140).

    KÖK: reveal_frac yalnız RENDER'a veriliyordu (fit_clip_with_anchor), anlatım yazarı
    dönümün klibin neresinde olduğunu BİLMİYORDU. Yazar ödülü metnin %37'sine koyunca
    (klipte dönüm %61'de) çıpa hız sınırına sığmadı ve klibin başı kırpıldı — anlatımın
    1. cümlesinin anlattığı açılış anı yok oldu. Yazar oranı bilirse çıpa kırpmasız oturur.
    """
    from short_bot.reel_narration import build_curated_prompt
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    p = build_curated_prompt("t", "d", channel=ch, reveal_frac=0.61)
    assert "REVEAL-SENKRON" in p and "%61" in p
    # dönüm tespit edilmediyse kural YOK (mevcut davranış korunur)
    assert "REVEAL-SENKRON" not in build_curated_prompt("t", "d", channel=ch)
    # 2 sahneli klipte SAHNE-SENKRON zaten aynı hizayı kuruyor → kural İKİ KEZ yazılmaz
    p2 = build_curated_prompt("t", "d", channel=ch, scene_split=0.5, reveal_frac=0.5)
    assert "SAHNE-SENKRON" in p2 and "REVEAL-SENKRON" not in p2


def test_write_curated_narration_passes_reveal_frac(monkeypatch):
    """write_curated_narration reveal_frac'ı prompt'a geçirmeli (produce_curated → yazar)."""
    from short_bot.reel_narration import write_curated_narration
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    seen = {}
    draft = _CuratedDraft(hook="Hook cumlesi",
                          beats=["Birinci beat", "Ikinci beat", "Ucuncu beat"],
                          close="Kapanis cumlesi", mood="upbeat",
                          title="Baslik", cover_title="Kapak")

    def _fake(prompt, schema, **kw):
        seen["prompt"] = prompt
        return draft

    monkeypatch.setattr("short_bot.reel_narration.run_json", _fake)
    write_curated_narration("t", "d", channel=ch, subject="clip", reveal_frac=0.61)
    assert "REVEAL-SENKRON" in seen["prompt"] and "%61" in seen["prompt"]


def test_curated_cta_style_rotates_with_seed():
    """YORUM-YEMİ ŞABLONU KIRILMALI (kullanıcı: 'senaryo sonu hep tek düze, dokunduysa
    kalp bırak gibi şablon mantığı olmamalı').

    ÖLÇÜM: DUYGU tonlu 7 kürate short'un 7'si de 'yorumlara bir kalp bırak' ile bitti.
    KÖK: cta_hint TEK bir LİTERAL örnek veriyordu ('Bu dokunduysa yorumlara bir kalp
    bırak.') — model onu kopyalıyordu. Çözüm persona.signature_style'ın kanıtlanmış
    deseni: ton başına stil HAVUZU + seed rotasyonu (aynı klip → aynı stil, farklı
    klip → farklı stil)."""
    from short_bot.reel_narration import CURATED_CTA_STYLES, curated_cta_style

    assert len(CURATED_CTA_STYLES["duygu"]) >= 4, "tek stil = yine şablon"
    # deterministik: aynı seed + ton → aynı stil
    assert curated_cta_style(7, "duygu") == curated_cta_style(7, "duygu")
    # ardışık seed'ler farklı stil görmeli (formül kırılır)
    got = {curated_cta_style(s, "duygu") for s in range(8)}
    assert len(got) >= 3, f"seed rotasyonu çeşitlenmiyor: {len(got)} stil"
    # her ton kendi havuzunu kullanır
    assert curated_cta_style(0, "mizah") in CURATED_CTA_STYLES["mizah"]
    assert curated_cta_style(0, "karma") in CURATED_CTA_STYLES["karma"]
    # bilinmeyen ton → mizah havuzuna düş (çökme yok)
    assert curated_cta_style(0, "bilinmeyen") in CURATED_CTA_STYLES["mizah"]


def test_curated_prompt_bans_canned_closings_and_varies_by_seed():
    """Prompt ARTIK literal 'kalp bırak' örneği vermemeli; kalıp yasağı taşımalı ve
    seed'e göre farklı yorum-yemi talimatı üretmeli."""
    from short_bot.reel_narration import build_curated_prompt
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    p0 = build_curated_prompt("t", "d", channel=ch, tone="duygu", seed=0)
    p1 = build_curated_prompt("t", "d", channel=ch, tone="duygu", seed=1)

    low = p0.replace("İ", "i").replace("I", "ı").lower()
    # 'kalp bırak' artık ÖRNEK olarak değil, YASAK listesinde geçmeli
    assert "kalıp" in low and "tekrarlama" in low, "kapanış şablonu yasağı yok"
    _i = low.find("kalp bırak")
    assert _i > 0 and "yasak" in low[max(0, _i - 400):_i + 200], \
        "'kalp bırak' hâlâ taklit edilecek bir ÖRNEK olarak duruyor (yasak bağlamında değil)"
    # seed değişince yorum-yemi talimatı da değişmeli
    assert p0 != p1, "CTA seed'e göre çeşitlenmiyor → her video aynı kapanış"


def test_curated_prompt_bans_outcome_flipping_exaggeration():
    """ABARTI SONUCU TERS ÇEVİREMEZ (short 1146): beat sheet 'nearly falls backward …
    end up standing' diyordu, anlatım 'bacakları boşaldı, sarsılarak YIĞILDI' yazdı —
    ekranda 23.7s'de adamlar ayakta ve gülüyor. Abartı serbest ama SONUÇ değişemez."""
    from short_bot.reel_narration import build_curated_prompt
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    low = build_curated_prompt("t", "d", channel=ch, tone="duygu").replace("İ", "i").lower()
    assert "neredeyse" in low, "'neredeyse düştü' → 'düştü' çevirme yasağı yok"
    assert "sonuc" in low.replace("ç", "c"), "sonucu değiştirme yasağı yok"


def test_fit_close_chars_keeps_payoff_drops_bait():
    """KAPANIŞ ŞEMASI ÜRETİMİ DÜŞÜRMESİN (gerçek koşu 1320): model 'close' alanına
    120 karakteri aşan bir kapanış yazdı, geri bildirimli 2. denemede de aştı →
    run_json ValidationError → klip indirilmiş, vision harcanmış hâlde TÜM üretim çöpe.

    CJK'de deterministik kırpma vardı (trim_cjk_close) ama YALNIZ CJK dillerinde;
    Türkçede kod tarafında hiçbir güvenlik ağı yoktu. Kırpma BAŞTAN korur: payoff
    (hikâyenin son vuruşu) kalır, yorum-yemi düşer — yem zaten opsiyonel (CTA
    havuzunda 'yem yok' stili de var), payoff değil."""
    from short_bot.reel_narration import fit_close_chars

    # sınır içindeyse dokunma
    kisa = "O gece damat dostlarının bacaklarıyla yürüdü."
    assert fit_close_chars(kisa, 120) == kisa

    # payoff + uzun yem → yem düşer, payoff kalır
    uzun = ("O gece damat kendi ayaklarıyla değil, dostlarının bacaklarıyla yürüdü. "
            "Bu sahne senin de içini ısıttıysa yorumlara mutlaka bir kalp bırak ve "
            "bu videoyu böyle bir dostu olan herkese gönder.")
    out = fit_close_chars(uzun, 120)
    assert len(out) <= 120
    assert out.startswith("O gece damat"), f"payoff düştü: {out}"
    assert "kalp bırak" not in out

    # tek cümle bile uzunsa kelime sınırında kesilir, yarım kelime kalmaz
    tek = "Bu damat " + "uzun " * 40 + "yürüdü."
    out2 = fit_close_chars(tek, 120)
    assert len(out2) <= 120 and out2.endswith(".")
    assert not out2.rstrip(".").endswith("uz"), "kelime ortasından kesilmiş"

    # boş/kısa girdi güvenli
    assert fit_close_chars("", 120) == ""


def test_curated_draft_schema_tolerates_long_close():
    """Şema artık uzun kapanışta PATLAMAMALI — kod tarafı budayacak. (Şema hâlâ absürt
    uzunluğu reddeder; amaç üretimi ayakta tutmak.)"""
    from short_bot.reel_narration import _CuratedDraft
    d = _CuratedDraft(hook="Hook cumlesi burada", beats=["Bir beat", "Iki beat", "Uc beat"],
                      close="A" * 300, mood="upbeat")
    assert len(d.close) == 300


def test_write_curated_narration_trims_overlong_close(monkeypatch):
    """Uçtan uca: model uzun kapanış yazsa bile üretim SÜRER ve close sınıra iner."""
    from short_bot.reel_models import CLOSE_MAX_CHARS
    from short_bot.reel_narration import write_curated_narration
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    draft = _CuratedDraft(
        hook="Bu damat ayaga kalkamiyordu",
        beats=["Birinci beat cumlesi", "Ikinci beat cumlesi", "Ucuncu beat cumlesi"],
        close=("O gece damat dostlarinin bacaklariyla yurudu. Bu sahne senin de icini "
               "isittiysa yorumlara mutlaka bir kalp birak ve herkese gonder."),
        mood="upbeat", title="Baslik", cover_title="Kapak")
    monkeypatch.setattr("short_bot.reel_narration.run_json", lambda *a, **k: draft)
    n = write_curated_narration("t", "d", channel=ch, subject="clip")
    assert len(n.close) <= CLOSE_MAX_CHARS
    assert n.close.startswith("O gece damat")


def test_curated_prompt_requires_payoff_and_loop_callback():
    """KAPANIŞ İKİ İŞİ DE YAPMALI: payoff (son vuruş) + hook'a geri çağrı (loop).

    ÖLÇÜM (short 1150): kapanış yalnızca yemden ibaret çıktı — 'Senin yanında böyle
    biri var mı?'. Payoff yok, hook'la ortak sözcük yok → close_echoes_hook denetimi
    'video biter, izleyici döngüye girmez' uyarısı verdi. KÖK: ana reel promptu
    callback'i AÇIKÇA istiyor (bkz. build_reel_prompt), kürate promptu hiç istemiyordu;
    denetim ise ikisine de uygulanıyor.

    Yem OPSİYONEL, payoff DEĞİL — fit_close_chars taşmada yemi düşürüp payoff'u
    koruyor; prompt da aynı önceliği söylemeli."""
    from short_bot.reel_narration import build_curated_prompt
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    # Türkçe tuzağı: "GERİ".lower() → "geri̇" (İ, birleşik noktalı i'ye düşer);
    # "YALNIZCA".lower() → "yalnizca" (I, ı DEĞİL i olur). Projedeki _norm deseni.
    p = build_curated_prompt("t", "d", channel=ch, tone="duygu")
    low = p.replace("İ", "i").replace("I", "ı").lower()
    assert "geri çağır" in low, "kapanışta hook'a geri çağrı (loop callback) kuralı yok"
    assert "yalnızca yem" in low or "sadece yem" in low, \
        "kapanışın yalnız yemden ibaret olamayacağı söylenmiyor"


def test_curated_prompt_anchors_hook_to_first_frame():
    """HOOK EKRANDA GÖRÜNENİ İŞARET ETMELİ (short 1154).

    Anlatım şöyle başlıyordu: 'Ortaokulda bir kız, kapısında her sabah aynı notu
    buluyordu' — ekranda ortaokul da kız da kapı da YOK; şapkalı bir adam duvara kağıt
    yapıştırıyor. Bilgi başlıktan geldiği için sadakat kapısı 'uydurma değil' deyip
    geçirdi, ama DOĞRU olması EKRANDA olması demek değil: izleyici ilk saniyede
    'kız nerede?' diye düşünüyor ve kayıyor. Geçmiş/bağlam 2. cümleden itibaren serbest."""
    from short_bot.reel_narration import build_curated_prompt
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    low = build_curated_prompt("t", "d", channel=ch, tone="duygu").replace(
        "İ", "i").replace("I", "ı").lower()
    assert "ilk kare" in low or "ilk saniye" in low, "hook'u ekrana bağlayan kural yok"
    assert "geçmiş" in low and "hook" in low, "geçmişin hook'ta yasak olduğu söylenmiyor"


def test_curated_prompt_bans_filler_beats():
    """DOLGU BEAT YASAĞI: beat OLAY anlatır, mimik/el hareketi TARİF etmez (short 1154).

    Klip 62sn ama içinde iki olay var (notları duvara yapıştırma + ağlama); beat sheet'in
    SON dilimi zaten tekrar ('eli ağzında, öne eğilmiş'). Şablon üç beat yazdırdığı için
    üçüncüsü dolguya dönüştü: 'Elini ağzından an ayırıp titretse de hemen geri götürüyor,
    başını eğip o duygunun içinde eriyor.' — hikâyeyi ilerletmiyor, aynı anı tekrar
    tarif ediyor. Az olaylı klipte cümle UZATMAK değil KISALTMAK gerekir."""
    from short_bot.reel_narration import build_curated_prompt
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    low = build_curated_prompt("t", "d", channel=ch, tone="duygu").replace(
        "İ", "i").replace("I", "ı").lower()
    assert "dolgu" in low, "dolgu cümle yasağı yok"
    assert "mimik" in low or "el hareketi" in low, \
        "mimik/el hareketi tarifinin beat sayılmadığı söylenmiyor"


def test_clarity_prompt_catches_filler_sentence():
    """NETLİK KAPISI dolguyu da yakalamalı: metin kendi içinde tutarlı olduğu için
    (short 1154) 'clear' geçiyordu — oysa bir cümle hiç yeni bilgi taşımıyordu."""
    from short_bot.reel_narration import _CLARITY_PROMPT
    low = _CLARITY_PROMPT.replace("İ", "i").replace("I", "ı").lower()
    assert "yeni bilgi" in low or "dolgu" in low, \
        "netlik kapısı 'yeni bilgi taşımayan cümle' ölçütünü sormuyor"


def test_clarity_gate_sees_title(monkeypatch):
    """NETLİK KAPISI BAŞLIĞI GÖRMELİ — yoksa DOĞRU anlatımı uydurma sanıp eliyor.

    GERÇEK HATA (short 1154 klibi): beat sheet duvarı 'bare tan wall with a framed
    photograph' diye tarif etti (sarı notları kaçırdı). Anlatım — başlıktan bilerek,
    DOĞRU olarak — 'duvardan notlar çıkıyor' dedi. Netlik kapısı bunu beat sheet'te
    göremeyince 'sahnede olmayan detay uyduruluyor' deyip reddetti; iki denemede de
    reddedilince klip komple elendi. Sadakat kapısına başlık beslenmişti (short 1140),
    netlik kapısına beslenmemişti — aynı körlük.
    """
    from short_bot.reel_narration import judge_narration_clarity, NarrationClarity

    seen = {}

    def _fake(prompt, schema, **kw):
        seen["prompt"] = prompt
        return NarrationClarity(clear=True)

    monkeypatch.setattr("short_bot.reel_narration.run_json", _fake)
    judge_narration_clarity("anlatım metni", "bare wall with a framed photograph",
                            tone="duygu", backend="openrouter", model="m", api_key="k",
                            title="Sophia's stepdad used to leave her a note every day")
    assert "note every day" in seen["prompt"], "başlık netlik kapısına geçmiyor"
