import pytest
from pydantic import ValidationError

from short_bot.reel_models import (ReelBeat, ReelNarration, ReelTimeline,
                                   TimedWord)


def _narr(**kw):
    base = dict(
        hook="Bir kaşık bal için arılar ne yapıyor biliyor musun?",
        beats=[
            ReelBeat(text="İşçi arılar çiçekten nektar toplar.",
                     visual_query="bee on flower macro", keyword="NEKTAR TOPLAR"),
            ReelBeat(text="Nektarı midelerinde enzimlerle işler.",
                     visual_query="honey bee closeup", keyword="MİDEDE İŞLENİR"),
            ReelBeat(text="Kovanda peteğe biriktirir.",
                     visual_query="honeycomb bees", keyword="PETEĞE DOLAR"),
        ],
        close="Yani bir kaşık bal binlerce arının emeği.",
        mood="upbeat",
    )
    base.update(kw)
    return ReelNarration(**base)


def test_segments_order_and_queries():
    n = _narr()
    assert n.segments()[0] == n.hook
    assert n.segments()[-1] == n.close
    assert len(n.segments()) == 5           # hook + 3 beat + close
    # görsel sorgular: hook/close için None, beat'ler için query
    assert n.segment_queries()[0] is None
    assert n.segment_queries()[1] == "bee on flower macro"
    assert n.segment_queries()[-1] is None


def test_full_text_and_word_count():
    n = _narr()
    assert n.full_text() == " ".join(n.segments())
    assert n.word_count() == len(n.full_text().split())


def test_beats_min_three():
    with pytest.raises(ValidationError):
        _narr(beats=[ReelBeat(text="Tek beat cümlesi burada.",
                              visual_query="xy", keyword="X")])


def test_beats_max_six():
    b = ReelBeat(text="Bir beat cümlesi.", visual_query="xy", keyword="X")
    with pytest.raises(ValidationError):
        _narr(beats=[b] * 7)


def test_visual_query_required_nonempty():
    with pytest.raises(ValidationError):
        ReelBeat(text="Cümle burada yeterince uzun.", visual_query="  ", keyword="X")


def test_turkish_preserved():
    n = _narr()
    assert "İşçi" in n.beats[0].text and "çiçekten" in n.beats[0].text


def test_timeline_holds_words_and_beats():
    tl = ReelTimeline(
        words=[TimedWord(word="Bir", start_s=0.0, end_s=0.2, seg=0)],
        seg_spans=[(0.0, 1.0), (1.0, 3.0)],
        seg_queries=[None, "bee on flower macro"],
        seg_keywords=["", "NEKTAR TOPLAR"],
        duration_s=12.0, hook="Bir?", close="Son.",
    )
    assert tl.duration_s == 12.0
    assert tl.seg_queries[1] == "bee on flower macro"


def test_hook_and_close_get_own_visual_queries():
    """Hook videonun en kritik karesi — kendi görsel sorgusunu kullanmalı.

    Gerçek şikâyet: "ilk girişteki görüntü alakasız" — hook, soyut bir beat
    sorgusunun çöp fallback'ini ödünç alıyordu."""
    from short_bot.reel_models import ReelBeat, ReelNarration
    beats = [ReelBeat(text="Beat bir cumlesi burada", visual_query="body scan",
                      keyword="A"),
             ReelBeat(text="Beat iki cumlesi burada", visual_query="muscle fiber",
                      keyword="B"),
             ReelBeat(text="Beat uc cumlesi burada", visual_query="runner legs",
                      keyword="C")]
    n = ReelNarration(hook="Merak uyandiran soru", beats=beats,
                      close="Kapanis cumlesi burada", mood="neutral",
                      hook_visual="exhausted runner collapsing",
                      close_visual="marathon finish line")
    q = n.segment_queries()
    assert q[0] == "exhausted runner collapsing"     # hook kendi sorgusu
    assert q[-1] == "marathon finish line"           # close kendi sorgusu
    assert q[1:-1] == ["body scan", "muscle fiber", "runner legs"]

    # geriye-uyum: alanlar boşsa None → çağıran ilk/son beat'e düşer
    n2 = ReelNarration(hook="Merak uyandiran soru", beats=beats,
                       close="Kapanis cumlesi burada", mood="neutral")
    assert n2.segment_queries()[0] is None and n2.segment_queries()[-1] is None


# --- YORUM SORUSU close'a SIZMASIN ------------------------------------------
# GERÇEK HATA (short 801 ve 802, gartengeheimnisse, Almanca): prompt kendisiyle
# çelişiyordu — şema "yorum sorusunu close'a KOYMA, ayrı 'comment' alanı var"
# derken enjekte edilen yönerge "soruyu close'un SONUNA ekle" diyordu ('comment'
# ayrı alan olarak çıkarıldığında enjeksiyon metni güncellenmemişti).
# Model ikisini de doldurdu → soru İKİ KEZ soruldu, ve dev kapanış KARTI (yalnız
# close'u basar) 7 satırlık metin duvarına döndü: videonun ÜÇTE BİRİ boyunca ekranda.
# Ayrıca yönergedeki örnek kalıbın META-TALİMATI ("Schreib nur den Buchstaben")
# senaryoya "Nur A oder B." diye sızdı ve SESLİ okundu.

def _beats():
    from short_bot.reel_models import ReelBeat
    return [ReelBeat(text="Die Pflanze ist nicht nur ein Unkraut.",
                     visual_query="dandelion", keyword="A"),
            ReelBeat(text="Ihre gelben Blueten schmecken ueberraschend suess.",
                     visual_query="dandelion", keyword="B"),
            ReelBeat(text="Geroestet diente die Wurzel als Kaffeeersatz.",
                     visual_query="coffee", keyword="C")]


# short 802'nin GERÇEK çıktısı
HOOK_802 = "Jeder Teil vom Loewenzahn ist essbar, doch warum landete er in der Tasse?"
CLOSE_802 = ("So wurde Loewenzahn zum Kaffeeersatz. "
             "Was schmeckt besser: Wurzel A oder Bluete B? Nur A oder B.")
COMMENT_802 = "Was schmeckt wohl besser: Wurzel A oder Bluete B?"


def test_close_icindeki_soru_comment_e_tasinir():
    from short_bot.reel_models import ReelNarration
    n = ReelNarration(hook=HOOK_802, beats=_beats(), close=CLOSE_802,
                      comment=COMMENT_802, mood="neutral")
    assert "?" not in n.close, f"kapanış kartında hâlâ soru var: {n.close!r}"
    assert n.close == "So wurde Loewenzahn zum Kaffeeersatz."


def test_kalibin_talimat_parcasi_senaryoya_girmez():
    """'Nur A oder B.' bir izleyici cümlesi değil, kalıbın meta-talimatı."""
    from short_bot.reel_models import ReelNarration
    n = ReelNarration(hook=HOOK_802, beats=_beats(), close=CLOSE_802,
                      comment=COMMENT_802, mood="neutral")
    konusulan = " ".join(n.segments())
    assert "Nur A oder B" not in konusulan, "kalıp talimatı SESLİ okunuyor"


def test_soru_iki_kez_sorulmaz():
    from short_bot.reel_models import ReelNarration
    n = ReelNarration(hook=HOOK_802, beats=_beats(), close=CLOSE_802,
                      comment=COMMENT_802, mood="neutral")
    assert n.segments()[-1].count("?") == 1, n.segments()[-1]


def test_soru_kaybolmaz_comment_bossa_oraya_tasinir():
    from short_bot.reel_models import ReelNarration
    n = ReelNarration(hook=HOOK_802, beats=_beats(), close=CLOSE_802,
                      comment="", mood="neutral")
    assert n.comment == "Was schmeckt besser: Wurzel A oder Bluete B?"
    assert "?" not in n.close
    assert n.comment in n.segments()[-1], "soru SESLİ sorulmalı, yalnız karta girmemeli"


def test_loop_callback_yok_edilmez():
    """Model sırayı ters kurduysa (soru ÖNDE) close'a DOKUNMA — bozuk ama yıkmaktan iyi."""
    from short_bot.reel_models import ReelNarration
    ters = "Was schmeckt besser: Wurzel oder Bluete? So wurde Loewenzahn zum Kaffee."
    n = ReelNarration(hook=HOOK_802, beats=_beats(), close=ters, mood="neutral")
    assert n.close == ters


def test_sorusuz_kapanis_bozulmaz():
    """Regresyon: normal (sorusuz) kapanışa dokunulmamalı."""
    from short_bot.reel_models import ReelNarration
    temiz = "Ve iste bu yuzden, piramitleri koleler yapmadi."
    n = ReelNarration(hook="Piramitleri koleler yapmadi.", beats=_beats(),
                      close=temiz, mood="neutral")
    assert n.close == temiz and n.comment == ""


def test_comment_yalniz_soru_cumlesini_tutar():
    from short_bot.reel_models import ReelNarration
    n = ReelNarration(hook=HOOK_802, beats=_beats(), close="Kapanis cumlesi burada.",
                      comment="Was ist besser: A oder B? Schreib nur den Buchstaben.",
                      mood="neutral")
    assert n.comment == "Was ist besser: A oder B?"


def test_title_varsayilan_bos_ve_asiri_uzun_kirpilir():
    from short_bot.reel_models import TITLE_MAX_CHARS
    assert _narr().title == ""                       # varsayılan boş (geriye uyum)
    # Aşırı uzun başlık üretimi DÜŞÜRMEZ, KIRPILIR (bkz. comment/cover_title dersi)
    n = _narr(title="Elektrikli Yilan Baligi Voltaj Kabadayi " * 8)
    assert 0 < len(n.title) <= TITLE_MAX_CHARS


def test_mood_serbest_metni_kovaya_zorlar():
    # GERÇEK HATA (keşif modu): model mood='mizahi ve enerjik' yazdı → Literal
    # doğrulaması 3 denemeyi de yaktı. mood ipucudur, üretimi öldüremez.
    assert _narr(mood="mizahi ve enerjik").mood == "upbeat"
    assert _narr(mood="sakin ve huzurlu").mood == "calm"
    assert _narr(mood="nötr anlatım").mood == "neutral"
    assert _narr(mood="upbeat").mood == "upbeat"      # geçerli değer dokunulmaz


def test_merak_alanlari_varsayilan_ve_dogrulama():
    # Merak mimarisi (spec 2026-07-16): hepsi varsayılan-boş → geriye uyum.
    n = _narr()
    assert n.open_question == ""
    assert n.reveal_beat == -1
    assert n.clip_order == []
    # open_question kırpılır, reddedilmez (comment/cover_title dersi)
    n2 = _narr(open_question="Bu balık neden herkesi korkutuyor acaba " * 4)
    assert 0 < len(n2.open_question) <= 48
    # reveal_beat aralığa kelepçelenir (3 beat -> 0..2)
    assert _narr(reveal_beat=7).reveal_beat == 2
    assert _narr(reveal_beat=1).reveal_beat == 1


def test_clip_order_permutasyon_degilse_bosalir():
    # Geçersiz clip_order üretimi DÜŞÜREMEZ — kimlik sırasına (boş) düşer.
    assert _narr(clip_order=[0, 1, 2]).clip_order == [0, 1, 2]
    assert _narr(clip_order=[0, 0, 1]).clip_order == []     # tekrar → geçersiz
    assert _narr(clip_order=[0, 1]).clip_order == []        # eksik → geçersiz
    assert _narr(clip_order=[0, 1, 5]).clip_order == []     # aralık dışı → geçersiz


def test_content_words_matches_turkish_suffixed_forms():
    """LOOP DENETİMİ TÜRKÇE EKLERİNİ GÖRMELİ (ölçüm: 5 kapanışın 2'si yanlış 'YOK').

    _content_words TAM kelime eşleştiriyordu; Türkçe sondan eklemeli bir dil olduğu
    için 'damat' ile 'damadı', 'dostları' ile 'dostluktu' eşleşmiyordu. Sonuç:
    close_echoes_hook gerçekte hook'u geri çağıran kapanışlara 'geri çağırmıyor'
    uyarısı veriyordu — operatöre yanlış sinyal, üstelik open_loop_spoken da aynı
    fonksiyona dayanıyor.
    """
    from short_bot.reel_models import _content_words

    # gerçek koşu çiftleri (check_close ölçümü, seed 5 ve 2)
    assert _content_words("damadı ayakta tutan kollar") & _content_words(
        "Bu damat kendi ayakları üstünde duramıyordu")
    assert _content_words("Damadı ayakta tutan bu dostluktu") & _content_words(
        "yanında öyle dostları vardı")
    # alakasız metinler EŞLEŞMEMELİ (kök kırpma yanlış pozitif üretmesin)
    assert not (_content_words("Bu kedi kutuda uyuyor")
                & _content_words("Sence kaç kişi bunu görünce güldü"))


def test_close_echoes_hook_tolerates_suffixes():
    from short_bot.reel_models import ReelBeat, ReelNarration

    def _n(hook, close):
        return ReelNarration(
            hook=hook,
            beats=[ReelBeat(text="Birinci beat cumlesi burada", visual_query="clip"),
                   ReelBeat(text="Ikinci beat cumlesi burada", visual_query="clip"),
                   ReelBeat(text="Ucuncu beat cumlesi burada", visual_query="clip")],
            close=close, mood="upbeat")

    assert _n("Bu damat kendi ayakları üstünde duramıyordu",
              "Düğün bitti ama damadı ayakta tutan o kollar hiç açılmadı.").close_echoes_hook()
    assert not _n("Bu kedi kutunun içinde mışıl mışıl uyuyor",
                  "Sence kaç kişi bunu görünce güldü?").close_echoes_hook()


def test_audit_text_covers_on_screen_titles_but_full_text_unchanged():
    """DENETİM METNİ = KONUŞULAN + EKRANDA YAZAN (short 1254 boşluğu).

    Sadakat/netlik kapılarına ``full_text()`` veriliyordu; o yalnız hook+beat+kapanışı
    döndürür. Ama ``cover_title`` videonun ilk saniyelerinde EKRANDA duran bir MANŞET,
    ``title`` da YouTube'a giden başlıktır — ikisi de izleyiciye bir İDDİA sunar ve
    hiçbir kapıdan geçmiyordu. Konuşulan metin tertemizken kapak uydurma bir dram
    ilan edebilirdi ('İki Gün Ayrı Kaldılar').

    ``full_text()`` TTS'e ve kelime bütçesine gidiyor — ona DOKUNULMAZ; denetim ayrı
    bir metin üzerinden yapılır."""
    n = _narr(cover_title="Kapak Mansedi", title="Video basligi burada")
    spoken = n.full_text()
    audit = n.audit_text()

    # konuşulan metin denetim metninin İÇİNDE, ama kendisi DEĞİŞMEDİ
    assert spoken in audit
    assert n.full_text() == " ".join(n.segments())
    assert n.word_count() == len(spoken.split())   # bütçe ölçüsü etkilenmedi
    # ekranda/başlıkta duran iddialar denetime GİRDİ, etiketli (yargıç ayırt edebilsin)
    assert "Kapak Mansedi" in audit and "Video basligi burada" in audit
    assert "EKRAN MANŞETİ" in audit and "VİDEO BAŞLIĞI" in audit
    # başlık/kapak yoksa denetim metni konuşulan metnin AYNISI (sıfır regresyon)
    assert _narr().audit_text() == _narr().full_text()
