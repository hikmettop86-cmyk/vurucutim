"""Bozuk bir LLM yanıtı, deneme hakkı VARKEN koşuyu öldürmemeli.

GERÇEK HATA (run 830): 3 deneme hakkı vardı.
  deneme 1 → konu tekrar çıktı (banka tükenmişti) → atıldı
  deneme 2 → LLM'in ürettiği vurgu paragrafta birebir geçmedi → pydantic
             ValidationError → generate_quote FIRLATTI → tüm koşu düştü.
  deneme 3 → hiç çalışmadı.

Doğrulama hatası bir LLM kaprisidir; sonraki deneme büyük ihtimalle geçerli bir
yanıt üretir. Tekrar (duplicate) nasıl bir deneme tüketip devam ediyorsa, geçersiz
yanıt da öyle davranmalı.
"""
from short_bot.pipeline import _safe_generate


class _Log:
    def __init__(self):
        self.msgs = []

    def info(self, m):
        self.msgs.append(m)

    def warning(self, m):
        self.msgs.append(m)


def test_invalid_llm_response_returns_none_instead_of_raising():
    """Geçersiz yanıt → None (çağıran sonraki denemeye geçer), FIRLATMAZ."""
    log = _Log()

    def boom():
        raise ValueError("Highlight paragrafta birebir geçmiyor")

    assert _safe_generate(boom, log=log, attempt=2) is None
    assert any("geçersiz" in m.lower() for m in log.msgs), "sebep loglanmadı"
    assert any("Highlight" in m for m in log.msgs), "asıl hata loglanmadı"


def test_valid_response_passes_through():
    log = _Log()
    assert _safe_generate(lambda: "sonuç", log=log, attempt=1) == "sonuç"
    assert log.msgs == []          # sessiz başarı


def test_keyboard_interrupt_is_not_swallowed():
    """Kullanıcı Ctrl+C yaptıysa YUTMA — üretim gerçekten dursun."""
    import pytest

    def interrupted():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _safe_generate(interrupted, log=_Log(), attempt=1)
