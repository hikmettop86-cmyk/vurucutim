"""Başlık alanı bir karakter taşınca ÜRETİM DÜŞMEMELİ — kırpılmalı.

GERÇEK HATA (bilim kanalı, 3 deneme de aynı sebeple düştü):
  script.header_top max 25 karakter; LLM "VÜCUDUN GİZEMLİ MEKANİZMASI" (26) yazdı
  → pydantic ValidationError → 3/3 deneme başarısız → ÜRETİM İPTAL.

Üstelik bu alan REEL kanalında hiç KULLANILMIYOR (klasik short şablonunun başlığı).
Bir karakterlik taşma yüzünden koca bir üretim (LLM + TTS + footage + montaj)
çöpe gitmemeli. Görsel taşma riski kırpmayla zaten yok.
"""
import pytest
from pydantic import ValidationError

from short_bot.models import Script


def _script(**over):
    base = dict(header_top="BASLIK", header_bottom="ALT BASLIK",
                photo_overlay="foto", body_paragraph="Bu bir gövde paragrafıdır.",
                category="bilim", mood="neutral")
    base.update(over)
    return Script(**base)


def test_one_char_overflow_is_trimmed_not_fatal():
    """26 karakterlik başlık üretimi DÜŞÜRMEZ — 25'e kırpılır."""
    s = _script(header_top="VÜCUDUN GİZEMLİ MEKANİZMASI")   # 26
    assert len(s.header_top) <= 25
    assert s.header_top.startswith("VÜCUDUN GİZEMLİ")


def test_trimming_does_not_leave_a_dangling_space():
    s = _script(header_top="A" * 24 + " KELIME")
    assert not s.header_top.endswith(" ")


def test_other_header_fields_are_trimmed_too():
    s = _script(header_bottom="B" * 60, photo_overlay="C" * 90,
                category="D" * 50)
    assert len(s.header_bottom) <= 35
    assert len(s.photo_overlay) <= 60
    assert len(s.category) <= 30


def test_body_paragraph_is_NOT_silently_trimmed():
    """Gövde metni ANLATIMIN kendisi — sessizce kırpmak cümleyi yarım bırakır.
    Uzunsa hata ver ki LLM yeniden yazsın."""
    with pytest.raises(ValidationError):
        _script(body_paragraph="x" * 900)


def test_empty_header_still_rejected():
    """Boş başlık kırpmayla düzelmez — gerçek bir hata."""
    with pytest.raises(ValidationError):
        _script(header_top="")
