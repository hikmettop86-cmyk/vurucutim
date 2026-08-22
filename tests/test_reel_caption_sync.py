"""Karaoke altyazılarının SESE kilitlenmesi.

Gerçek hata (short 757/758): zamanlar yalnız ``len(asr) == len(senaryo)`` ise
kullanılıyordu; aksi hâlde hepsi atılıp süreye eşit dağıtılıyordu. Ama whisper
senaryoyla aynı kelimelere bölmez — "altı"yı "6" yazar, "Amerika'nın"ı ikiye
ayırır — yani sayı çoğu zaman tutmaz ve karaoke aslında hiç hizalanmıyordu.
TTS bir öbeği okumadan geçip sonda sessizlik bırakınca kalan kelimeler tüm
süreye yayıldı, altyazı sesin gerisine düştü.
"""
from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)


def _narr():
    return ReelNarration(
        hook="Altı metre kanat açıklığı var.",
        beats=[ReelBeat(text="Kondor zirvede süzülür.", visual_query="condor sky", keyword="ZİRVE"),
               ReelBeat(text="Leşle beslenir bu kuş.", visual_query="condor eat", keyword="LEŞ"),
               ReelBeat(text="Yetmiş yıl yaşayabilir.", visual_query="condor old", keyword="ÖMÜR")],
        close="İşte kondorun sırrı.", mood="upbeat")


def _asr(pairs):
    return [TimedWord(word=w, start_s=s, end_s=e, seg=-1) for w, s, e in pairs]


def test_kelime_sayisi_tutmasa_da_asr_zamanlari_kullanilir():
    # Whisper "Altı"yı "6" yazıp "açıklığı var." derken kelimeleri farklı böler:
    # sayı tutmaz. Eskiden bu, TÜM hizalamayı çöpe atıyordu.
    n = _narr()
    script = n.full_text().split()
    asr = _asr([(w, float(i) * 2, float(i) * 2 + 1.5) for i, w in enumerate(script)]
               + [("fazladan", 100.0, 101.0)])          # ASR'de 1 kelime FAZLA
    tl = build_reel_timeline(n, asr, duration_s=120.0)
    # İlk kelime ASR'nin gerçek zamanını almalı — oransal dağıtımın değil.
    assert tl.words[0].start_s == 0.0
    assert tl.words[1].start_s == 2.0
    assert tl.words[5].start_s == 10.0


def test_farkli_yazilan_kelime_yine_eslesir():
    # "Altı" (senaryo) ↔ "6" (whisper): normalize edilince eşleşir, zamanı alır.
    n = _narr()
    script = n.full_text().split()
    heard = ["6" if w == "Altı" else w for w in script]
    asr = _asr([(w, float(i), float(i) + 0.8) for i, w in enumerate(heard)])
    tl = build_reel_timeline(n, asr, duration_s=90.0)
    assert tl.words[0].word == "Altı"
    assert tl.words[0].start_s == 0.0        # ASR zamanı, oransal değil


def test_okunmayan_kelimeler_araya_sikistirilir_kalan_kaymaz():
    # TTS ortadaki 3 kelimeyi okumadı. Okunmayanlar iki komşu arasına sıkışmalı;
    # ÖNEMLİSİ: sonrasındaki kelimeler gerçek ses zamanlarında KALMALI.
    n = _narr()
    script = n.full_text().split()
    kayip = set(range(4, 7))
    heard = [(w, float(i) * 0.5, float(i) * 0.5 + 0.4)
             for i, w in enumerate(script) if i not in kayip]
    tl = build_reel_timeline(n, _asr(heard), duration_s=40.0)
    # Okunan kelime kendi ses zamanında:
    assert tl.words[8].start_s == 4.0
    # Okunmayanlar komşuların ARASINDA kaldı (sonrasını itmedi):
    for i in sorted(kayip):
        assert tl.words[3].end_s <= tl.words[i].start_s <= tl.words[7].start_s


def test_asr_yoksa_oransal_dagitima_duser():
    n = _narr()
    tl = build_reel_timeline(n, [], duration_s=30.0)
    assert tl.words[0].start_s == 0.0
    assert tl.words[-1].end_s == 30.0


def test_hicbiri_eslesmezse_oransal_dagitima_duser():
    n = _narr()
    asr = _asr([(f"zzz{i}", float(i), float(i) + 0.5) for i in range(5)])
    tl = build_reel_timeline(n, asr, duration_s=30.0)
    assert tl.words[-1].end_s == 30.0
