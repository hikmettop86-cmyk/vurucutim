"""Kalıp tekrarı: otomasyon parmak izinin en görünür kaynağı.

Prompt mikro-döngü bağlaçlarını BİREBİR CÜMLE olarak veriyordu ("Ama asıl garip
olan şu:" / "Ve burada iş çığırından çıkıyor.") ve LLM onları kopyalıyordu.
ÖLÇÜLDÜ: kayda geçen üç anlatımın ikisinde aynı iki cümle kelimesi kelimesine
geçiyor. İki videoyu üst üste izleyen biri bunu anında fark eder.
"""
from short_bot.lang_pack import load_pack
from short_bot.reel_phrases import find_overused, pick_styles

# Yönergeler ve kalıplar artık DİL PAKETİNDE (tr.json = eski sabitlerin birebir
# kopyası; bkz. test_lang_pack_tr_golden.py). Bu testlerin beklentileri DEĞİŞMEDİ.
TR = load_pack("tr")
CONNECTIVE_STYLES = TR.connective_styles
OVERUSED = TR.overused


def test_asinmis_kalip_yakalanir():
    metin = ("And Kondoru altı metre kanat açar. Ama asıl garip olan şu: "
             "ana besini leştir.")
    assert "ama asıl garip olan şu" in find_overused(metin, pack=TR)


def test_noktalama_ve_buyuk_harf_kalibi_gizleyemez():
    # Model kalıbı farklı noktalamayla kurabiliyor; eşleşme normalize edilmeli.
    assert find_overused("AMA ASIL GARİP OLAN ŞU, kondorlar leşle beslenir.", pack=TR)


def test_turkce_buyuk_i_eslesmeyi_kirmaz():
    # "İ".lower() birleşik nokta üretir (i̇) → naif karşılaştırma kaçırır.
    assert find_overused("İnanılmaz ama gerçek: kondorlar yetmiş yıl yaşar.", pack=TR)


def test_temiz_metin_gecer():
    metin = ("Kondor yetmiş yıl yaşar. Bu ömrün bedelini ise kimse konuşmuyor. "
             "Kanat açıklığı altı metreye ulaşır.")
    assert find_overused(metin, pack=TR) == []


# --- KALIP (dizge değil) ----------------------------------------------------
# GERÇEK KAÇAK (bölüm #2): yasak listesinde "bunu biliyor muydunuz" vardı; LLM
# "...sahip olduğunu biliyor muydunuz?" yazdı ve DENETİMDEN GEÇTİ. Yasak olan şey
# bir dizge değil, KALIP: cevaplanabilir evet/hayır sorusu hook değildir — izleyici
# onu 200 milisaniyede içinden cevaplar, gerilim çöker.

def test_gercek_kacak_artik_yakalaniyor():
    kacan = ("Ev kedilerinin sanılanın aksine çok daha vahşi bir içgüdüye sahip "
             "olduğunu biliyor muydunuz?")
    assert find_overused(kacan, pack=TR), "gerçek koşuda denetimden geçen hook hâlâ geçiyor"


def test_kalibin_butun_cekimleri():
    for h in ["Bunu biliyor muydun?",
              "Peki kondorların yetmiş yıl yaşadığını biliyor muydunuz?",
              "Bu sesi hiç duymuş muydunuz?",
              "Merhaba arkadaşlar, bugün sizlere kondorları anlatacağım.",
              "Hazır mısınız? Başlıyoruz."]:
        assert find_overused(h, pack=TR), f"kalıp kaçtı: {h!r}"


def test_masum_cumleler_yanlis_alarm_vermez():
    for h in ["Kondorlar leşi kilometrelerce uzaktan bulur.",
              "Bilim insanları bunu yıllarca açıklayamadı.",
              "Bu bilgi çoğu kitapta yanlış yazılmış."]:
        assert find_overused(h, pack=TR) == [], f"yanlış alarm: {h!r}"


def test_yakalanan_kalip_LLM_e_ANLASILIR_bildirilir():
    """Geri bildirim regex değil, İNSAN CÜMLESİ olmalı — LLM'e ne yaptığını söylemeli."""
    b = find_overused("Bunu biliyor muydunuz?", pack=TR)
    assert b and all("\\b" not in x and "(?" not in x for x in b), b


def test_yonergeler_seede_gore_donuyor():
    # Aynı dört örneği her videoya vermek, kalıbı yeniden üretmenin ta kendisiydi.
    a = pick_styles(1, 4, pack=TR)
    b = pick_styles(2, 4, pack=TR)
    assert a != b


def test_ayni_seed_ayni_yonerge():
    assert pick_styles(7, 4, pack=TR) == pick_styles(7, 4, pack=TR)


def test_yonergeler_havuzdan_ve_tekrarsiz():
    s = pick_styles(3, 4, pack=TR)
    assert len(s) == 4 and len(set(s)) == 4
    assert all(x in CONNECTIVE_STYLES for x in s)


def test_yonergeler_hazir_cumle_degil():
    # Havuzdaki bir yönerge kopyalanabilir bir cümle OLMAMALI — yoksa yeni kalıp
    # üretmiş oluruz. Hiçbiri aşınmış listesiyle eşleşmemeli.
    for s in CONNECTIVE_STYLES:
        assert not find_overused(s, pack=TR)


def test_prompt_yasak_listesini_ve_yonergeleri_icerir():
    from short_bot.config import ReelConfig
    from short_bot.reel_narration import build_reel_prompt

    class Ch:
        language = "tr"
        reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(25, 45))

    p = build_reel_prompt("kondor", Ch(), seed=5)
    assert OVERUSED[0] in p                       # yasak listesi prompt'ta
    assert any(s[:20] in p for s in pick_styles(5, 4, pack=TR))   # o seed'in yönergeleri
    # Kalıp artık YALNIZ yasak listesinde geçiyor — "böyle yaz" örneği olarak DEĞİL.
    # Eskiden prompt onu örnek verip "her beat'in sonuna birini koy" diyordu.
    assert p.count(OVERUSED[0]) == 1
    assert "her beat'in sonuna birini koy" not in p


# ——— boru hattı: linter gerçekten yeniden yazdırıyor mu ———

class _Ch:
    from short_bot.config import ReelConfig as _RC
    language = "tr"
    reel = _RC(enabled=True, voice_id="v", target_duration_s=(25, 45))


def _n(hook, beat_text):
    from short_bot.reel_models import ReelBeat, ReelNarration
    # bütçe 45-81 kelime → beat metinlerini dolduruyoruz
    dolgu = " ".join(f"kelime{i}" for i in range(18))
    return ReelNarration(
        hook=hook,
        beats=[ReelBeat(text=f"{beat_text} {dolgu}", visual_query="condor sky", keyword="A"),
               ReelBeat(text=f"Kondor leşle beslenir. {dolgu}", visual_query="condor eat", keyword="B"),
               ReelBeat(text=f"Yetmiş yıl yaşar. {dolgu}", visual_query="condor old", keyword="C")],
        close="İşte kondorun sırrı.", mood="neutral", peak_beat=1)


KIRLI = _n("Kondor gökyüzünün avcısı.", "Ama asıl garip olan şu:")
TEMIZ = _n("Kondor gökyüzünün avcısı.", "Bu ölçünün bedeli ise henüz konuşulmadı.")


def test_asinmis_kalipli_senaryo_yeniden_yazdirilir(monkeypatch):
    from short_bot import reel_narration
    cagrilar = []
    seq = iter([KIRLI, TEMIZ])

    def _fake(prompt, *a, **kw):
        cagrilar.append(prompt)
        return next(seq)

    monkeypatch.setattr(reel_narration, "run_json", _fake)
    out = reel_narration.write_reel_narration("kondor", channel=_Ch())
    assert len(cagrilar) == 2, "kalıp yakalandı ama yeniden yazdırılmadı"
    assert "HAZIR KALIP" in cagrilar[1], "LLM'e NE yaptığı söylenmeli"
    assert "ama asıl garip olan şu" in cagrilar[1].lower()
    assert find_overused(out.full_text(), pack=TR) == []


def test_temiz_senaryo_tek_seferde_gecer(monkeypatch):
    from short_bot import reel_narration
    cagrilar = []

    def _fake(prompt, *a, **kw):
        cagrilar.append(prompt)
        return TEMIZ

    monkeypatch.setattr(reel_narration, "run_json", _fake)
    reel_narration.write_reel_narration("kondor", channel=_Ch())
    assert len(cagrilar) == 1


def test_israrli_kalip_uretimi_oldurmez(monkeypatch):
    # İkinci deneme de kirliyse video YİNE üretilmeli — kusurlu metin, video
    # yokluğundan yeğdir (uyarı loglanır).
    from short_bot import reel_narration
    monkeypatch.setattr(reel_narration, "run_json", lambda p, *a, **kw: KIRLI)
    out = reel_narration.write_reel_narration("kondor", channel=_Ch())
    assert out.hook == KIRLI.hook
