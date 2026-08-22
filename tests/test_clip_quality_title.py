"""Storyboard kalite kapısı BAŞLIĞI görmeli — kareyi çıplak yorumlamak niş kanalı öldürüyor.

CANLI KANIT (2026-07-27, pitdayi/F1 kanalı kurulumu): havuz taraması 46 taze cevherden
SIFIR klip geçirdi. Kalite kapısı en güçlü adayı (Oscar Piastri'nin pistte neredeyse
çarpışması) q=3 'sıradan' diye eledi. Kapı 9 kareyi BAŞLIKSIZ görüyordu: karede
'pistte insanlar' var, olayın ne olduğu çözülemiyor → rutin sanılıyor.

İki ayrı kusur ölçüldü:
  1) BAŞLIK KÖRLÜĞÜ: judge_clip_quality'ye başlık HİÇ geçmiyordu (oysa tone-fit'e
     başlık beslendi — aynı gerekçe, aynı düzeltme deseni).
  2) BLANKET SPOR REDDİ: prompt 'rutin spor anı/düşmesi' DÜŞÜK diyordu. O satır bir
     kadın-futbolu pile-up klibi için yazılmıştı (short 957) ama bir SPOR kanalını
     kökten vuruyor.

DÜZELTMENİN SINIRI (bu testlerin asıl işi): başlık, kapının GÖRDÜĞÜ eylemi ÇÖZMESİ
içindir — görsel çıtayı DÜŞÜRMEZ. Görsel olarak ölü bir klip (konuşan kafa, yürüyen
insan) başlık ne kadar ilginç olursa olsun DÜŞÜK kalmalı; yoksa kapı 'anlatım kurtarır'
diye sıradan klip geçirir ve kalite motoru çöker.
"""
import inspect

from short_bot.curated_clean import _quality_prompt, judge_clip_quality


def test_baslik_prompta_giriyor():
    p = _quality_prompt("mizah", "Piastri ignores Zak Brown's congratulations")
    assert "Piastri ignores Zak Brown" in p


def test_baslik_yoksa_prompt_ESKI_HALINDE_kalir():
    """Sıfır regresyon: kanıtlanmış kanallar (dayidiyorki/kaosdayi/karmadayi) başlık
    geçmeyen bir çağrıda bugünkü prompt'u AYNEN almalı."""
    p = _quality_prompt("mizah")
    assert "KLİBİN BAŞLIĞI" not in p
    assert "olayın kimliği" not in p


def test_bos_ve_bosluk_baslik_da_eski_hali():
    for bos in ("", "   ", "\n"):
        assert "KLİBİN BAŞLIĞI" not in _quality_prompt("mizah", bos)


def test_baslik_GORSEL_CITAYI_dusurmuyor():
    """En kritik kural: başlık 'ölü klibi kurtarma' izni DEĞİL."""
    p = _quality_prompt("mizah", "Yuki Tsunoda havaalanında kayboldu")
    assert "GÖRSEL olarak ÖLÜ" in p
    assert "anlatım metni klibi kurtaramaz" in p


def test_spor_reddi_artik_kosullu():
    """'rutin spor anı' blanket reddi bir SPOR kanalını kökten vuruyordu."""
    for tone in ("mizah", "duygu", "karma"):
        p = _quality_prompt(tone, "bir başlık")
        assert "HİKÂYESİ OLMAYAN rutin spor" in p, tone
        # Eski koşulsuz hâli geri gelirse bu yakalar.
        assert "sayılanlar: rutin spor" not in p, tone


def test_ton_merceği_baslikla_birlikte_korunuyor():
    """Başlık bloğu ton merceğini EZMEMELİ (duygu/karma kanalları bozulmasın)."""
    assert "DOKUNAKLI" in _quality_prompt("duygu", "bir başlık")
    assert "oh olsun" in _quality_prompt("karma", "bir başlık")
    assert "komik" in _quality_prompt("mizah", "bir başlık")


def test_judge_clip_quality_title_kwargi_kabul_ediyor():
    sig = inspect.signature(judge_clip_quality)
    assert "title" in sig.parameters
    assert sig.parameters["title"].default == ""


def test_cagiranlar_basligi_gecmeyi_UNUTMAMIS():
    """Kapıya başlığı geçirmek çağıranın işi; biri düşerse o kanal sessizce
    başlıksız (kör) yargıya döner ve kimse fark etmez."""
    import re
    from pathlib import Path
    bulunan = 0
    for mod in ("curated_pool.py", "curated_pipeline.py"):
        metin = (Path("src/short_bot") / mod).read_text(encoding="utf-8")
        # Her çağrıyı KENDİ parantezine kadar oku (dosyadaki başka title= geçişleri —
        # örn. judge_tone_fit'in başlığı — bu sayımı kirletmesin).
        for m in re.finditer(r"judge_clip_quality\((.*?)\)\n", metin, re.S):
            bulunan += 1
            assert "title=" in m.group(1), f"{mod}: bir judge_clip_quality çağrısı başlıksız"
    assert bulunan == 3, f"beklenen 3 çağrı, bulunan {bulunan}"
