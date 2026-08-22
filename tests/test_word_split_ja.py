"""Dile duyarlı kelime bölme — boşluksuz yazan diller (Japonca).

NEDEN VAR: karaoke altyazı, sadakat denetimi ve kelime bütçesi ÜÇÜ DE
``text.split()`` kullanıyordu. Japoncada boşluk yoktur:

    "この犬が飼い主を助けた。誰も信じられなかった。".split()  →  1 eleman (23 karakter)

Sonucu: altyazı kelime kelime değil, TÜM CÜMLE tek blok olarak yanardı (kanalın
görsel kimliği bu vurgudur); ``worst_drop`` senaryoda 1 token görüp whisper'da 20
token bulunca OLMAYAN bir kayıp bildirir ve TTS'i 2 kez boşuna yeniler.

Öbekler dilbilimsel olarak kusursuz olmak zorunda DEĞİL — okunabilir boyda olmalı,
noktalamada kırılmalı ve whisper'ın çıkardığı birimlere yeterince benzemeli ki
``align_to_asr`` demir atacak eşleşme bulsun (bulamazsa orantılı dağıtıma düşer,
yani en kötü hâli bugünkü davranış).
"""
from short_bot.text_normalize import language, split_words


def test_turkish_still_splits_on_whitespace():
    assert split_words("bu çocuk koridorda bekliyordu", "tr") == \
           ["bu", "çocuk", "koridorda", "bekliyordu"]


def test_turkish_default_language_unchanged():
    """Dil verilmezse bağlamdan okunur; Türkçe davranışı birebir eski hâli."""
    with language("tr"):
        assert split_words("iki kelime") == ["iki", "kelime"]


def test_japanese_produces_multiple_chunks():
    """Cümle TEK blok olmamalı — karaoke vurgusunun anlamı bu."""
    got = split_words("この犬が飼い主を助けた。", "ja")
    assert len(got) >= 2, got


def test_long_text_produces_many_chunks():
    got = split_words("この犬が飼い主を助けた。誰も信じられなかった。彼は病院で待っていた。", "ja")
    assert len(got) >= 5, got


def test_japanese_chunks_rejoin_to_original():
    """Hiçbir karakter kaybolmamalı — altyazı metni anlatımın AYNISI olmalı."""
    src = "この犬が飼い主を助けた。誰も信じられなかった。"
    assert "".join(split_words(src, "ja")) == src


def test_japanese_breaks_after_sentence_punctuation():
    got = split_words("助けた。誰も", "ja")
    assert got[0].endswith("。"), got


def test_japanese_chunks_fit_one_subtitle_line():
    """Üst sınır ALTYAZI SATIRINDAN gelir: 82px yazı, 960px kutu, CJK glifleri tam
    genişlik → satıra ~11 karakter. Öbek bunu aşarsa satır taşar."""
    src = "この犬が飼い主を助けた。誰も信じられなかった。彼は病院の廊下で待っていた。"
    got = split_words(src, "ja")
    assert all(len(c) <= 11 for c in got), got
    assert all(c.strip() for c in got), got


def test_japanese_keeps_latin_run_intact():
    """Japonca metne karışan Latin/rakam öbeği ORTADAN bölünmesin."""
    got = split_words("スパイダーマンが2025年に", "ja")
    assert any("2025" in c for c in got), got


def test_japanese_existing_spaces_are_hard_boundaries():
    got = split_words("東京 大阪", "ja")
    assert "東京" in got and "大阪" in got, got


def test_empty_string():
    assert split_words("", "ja") == []
    assert split_words("   ", "ja") == []


def test_no_orphan_tail_chunk():
    """MAX sınırı zorla kırınca 1-2 karakterlik öksüz kuyruk KALMAMALI.

    EKRANDA GÖRÜLDÜ (final QA, zürafa klibi): "近づいてきまし | た。" — kelime ortadan
    bölünüp 'た。' tek başına altyazıya düştü."""
    got = split_words("大きなキリンがそっと近づいてきました。", "ja")
    assert all(len(c) >= 3 or c is got[0] for c in got), got
    assert not any(len(c) <= 2 for c in got[1:]), got


def test_orphan_merge_keeps_text_intact():
    src = "大きなキリンがそっと近づいてきました。"
    assert "".join(split_words(src, "ja")) == src


def test_orphan_merge_does_not_blow_up_chunk_size():
    src = "小さな亀はひとりぼっちでした。大きなキリンが近づいてきました。"
    assert all(len(c) <= 9 for c in split_words(src, "ja")), split_words(src, "ja")
