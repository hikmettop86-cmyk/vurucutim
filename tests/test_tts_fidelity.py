"""TTS sadakat denetimi.

Gerçek vaka (short 757): ai33 hook'un sonunu ve ilk beat'in başını hiç okumadı;
altyazılar o kelimeleri gösterdiği için video ikinci sahnede ileri zıpladı. Ses
dosyası geçerliydi, süresi normaldi, hata dönmedi — tek belirti duyulan metindi.
"""
from short_bot.tts.fidelity import MAX_DROPPED_RUN, normalize_tokens, worst_drop

SCRIPT = ("And Kondoru, altı metre kanat açıklığına sahip sessiz bir katildir. "
          "Güney Amerika'nın zirvesinde süzülen bu dev kuş, en büyük yırtıcı "
          "olarak 12 kiloya ulaşır.")

# 757'nin sesinin whisper çözümü. TTS öbeği atlayınca whisper sınırdaki kelimeleri
# tek bir dolgu kelimesine ("ve") indirgemiş: kayıp 'delete' değil 'replace' görünür.
HEARD_BOZUK = ("Ant kondoru 6 metre kanat açıklığına sahip ve süzülen bu dev kuş "
               "en büyük yırtıcı olarak 12 kiloya ulaşır.")

# Sağlam seslendirmenin whisper çözümü: sayı yazımı ("altı"→"6"), özel ad ("And"→
# "Ant") ve kesme işareti ("Amerika'nın"→"Amerika 'nın") farkları normaldir.
HEARD_SAGLAM = ("Ant kondoru 6 metre kanat açıklığına sahip sessiz bir katildir. "
                "Güney Amerika 'nın zirvesinde süzülen bu dev kuş en büyük yırtıcı "
                "olarak 12 kiloya ulaşır.")


def test_okunmayan_obek_yakalanir():
    drop = worst_drop(SCRIPT, HEARD_BOZUK)
    assert not drop.ok
    assert drop.count >= MAX_DROPPED_RUN
    assert "zirvesinde" in drop.phrase


def test_saglam_seslendirme_temiz_gecer():
    # ASR gürültüsü (sayı/özel ad/kesme işareti) kaybı taklit etmemeli.
    assert worst_drop(SCRIPT, HEARD_SAGLAM).ok


def test_ayni_metin_hic_kayip_vermez():
    assert worst_drop(SCRIPT, SCRIPT).count == 0


def test_sayi_yazimi_iki_tarafta_ayni_bicime_iner():
    assert normalize_tokens("altı") == normalize_tokens("6") == ["6"]


def test_turkce_buyuk_i_kelimeyi_bozmaz():
    # "İ".lower() birleşik nokta üretir (i̇) ve eşleşmeyi kırar.
    assert normalize_tokens("İşte") == normalize_tokens("işte")


def test_kesme_isareti_bolunmesi_kayip_sayilmaz():
    assert worst_drop("Amerika'nın zirvesinde", "Amerika 'nın zirvesinde").ok


def test_bastan_dusen_obek_de_yakalanir():
    # difflib kaybı baş/son sınırda 'delete' olarak görür; oradan da bulunmalı.
    drop = worst_drop("bir iki üç dört beş altı yedi", "beş altı yedi")
    assert not drop.ok
    assert drop.count == 4


# --- DİLE DUYARLILIK -------------------------------------------------------

def test_almanca_BUYUK_I_asimetri_yaratmaz():
    """GERÇEK HATA: _fold Türkçe için I → ı yapıyordu.

    Senaryo "Ich" (büyük, cümle başı), whisper dökümü "ich" (küçük) yazarsa:
    'ıch' vs 'ich' → kelime EŞLEŞMEZ ve sadakat denetimi OLMAYAN bir kayıp bildirir.
    Almanca'da 'Ich/In/Ist/Immer' çok sık.
    """
    from short_bot.tts.fidelity import normalize_tokens
    assert normalize_tokens("Ich", lang="de") == normalize_tokens("ich", lang="de")
    assert normalize_tokens("Ich", lang="de") == ["ich"]


def test_almanca_worst_drop_YANLIS_ALARM_vermez():
    from short_bot.tts.fidelity import worst_drop
    senaryo = "Ich zeige euch heute ein Bier aus Bayern"
    duyulan = "ich zeige euch heute ein bier aus bayern"
    assert worst_drop(senaryo, duyulan, "de").count == 0


def test_turkce_fold_BUGUNKU_davranis_korunur():
    from short_bot.tts.fidelity import normalize_tokens
    assert normalize_tokens("IŞIK") == ["ışık"]
    assert normalize_tokens("İSTANBUL") == ["istanbul"]


def test_dil_baglamdan_okunur():
    """caption_align zinciri dili elden ele taşımıyor — contextvar'dan okuyor."""
    from short_bot.text_normalize import language
    from short_bot.tts.fidelity import normalize_tokens
    with language("de"):
        assert normalize_tokens("Ich") == ["ich"]
    assert normalize_tokens("Ich") == ["ıch"]      # Türkçe bağlam (varsayılan)
