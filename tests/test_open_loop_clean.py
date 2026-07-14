"""Açık kapı META dilinden temizlenmeli: alan bir KONU, konuşulan cümle değil.

GERÇEK KOŞUDA OLDU (bölüm #1): LLM open_loop alanına
  "Ev kedilerinden çok daha iyi olmalarının bilimsel sırrını 2. bölümde açıklıyoruz."
yazdı. Bu metin bir SONRAKİ bölümün ÜRETİM KONUSU olarak kullanılıyor — içinde bölüm
numarası ve "açıklıyoruz" geçen bir konu tohumu senaryo yazıcısını yanıltır (video
kendi kendine "2. bölümde açıklıyoruz" diye bir konu üretmeye kalkar).

Prompt'ta yasakladık. Ama LLM'e güvenmiyoruz: temizliyoruz.
"""
from short_bot.reel_series import clean_open_loop

# Metinler artık DİL PAKETİNDE (tr.json = eski sabitlerin birebir kopyası;
# bkz. test_lang_pack_tr_golden.py). Beklentiler DEĞİŞMEDİ.
from short_bot.lang_pack import load_pack
TR = load_pack("tr")



def test_gercek_kosudaki_kuyruk_ayiklaniyor():
    ham = ("Ev kedilerinden cok daha iyi olmalarinin bilimsel sirrini "
           "2. bolumde acikliyoruz.")
    t = clean_open_loop(ham, pack=TR)
    assert "bolum" not in t.lower()
    assert "acikli" not in t.lower()
    assert "bilimsel sirri" in t.lower() or "bilimsel sirrini" in t.lower()


def test_cesitli_meta_kuyruklari():
    for ham in [
        "Fener baliginin isigini ureten bakteriyi sonraki bolumde anlatiyorum.",
        "Bu refleks hizinin ardindaki sinir yapisini bir sonraki bolumde gosterecegim.",
        "Piramitleri kimin yaptigini yarin anlatacagim.",
        "O bakterinin nasil oraya gittigini 48. bolumde acikliyorum.",
    ]:
        t = clean_open_loop(ham, pack=TR)
        assert "bolum" not in t.lower(), f"{ham!r} → {t!r}"
        assert "yarin" not in t.lower(), f"{ham!r} → {t!r}"
        assert len(t.split()) >= 3, f"fazla kirpildi: {ham!r} → {t!r}"


def test_temiz_konu_DOKUNULMADAN_gecer():
    temiz = "Fener baliginin isigini ureten simbiyotik bakteri"
    assert clean_open_loop(temiz, pack=TR) == temiz


def test_asiri_kirpma_yerine_HAM_metin():
    """Cümlenin tamamı metaysa kırpmak geriye hiçbir şey bırakmaz.

    Gürültülü bir tohum, BOŞ bir tohumdan iyidir: boş olursa ark kopar.
    """
    ham = "Bunu 2. bolumde anlatiyorum."
    t = clean_open_loop(ham, pack=TR)
    assert t, "boş dönerse ark kopar"


def test_bos_girdi():
    assert clean_open_loop("", pack=TR) == ""
    assert clean_open_loop(None, pack=TR) == ""
