"""Türkçe DIŞI kanallar için dil denetimi: yerli okur yargısı + geri çeviri.

NEDEN VAR: operatör Japonca bilmiyor. Türkçe kanalda "bu anlatım anlamsız" diyebildiği
geri bildirim döngüsü yabancı dilde KOPUYOR — bozuk bir cümle sessizce yayına gider ve
hiçbir kapı onu görmez (sadakat kapısı GÖRÜNTÜYE bakar, netlik kapısı MANTIĞA; ikisi de
dilin DOĞALLIĞINA bakmaz).

İki ayrı iş, ikisi de gerekli:
  • yerli okur — metni HEDEF DİLDE yargılar: doğal mı, kayıt (keigo/です・ます) tutarlı mı,
    çeviri kokuyor mu. Bunu geri çeviri YAKALAYAMAZ: bozuk bir Japonca cümle Türkçeye
    gayet düzgün geri çevrilir.
  • geri çeviri — ANLAMI operatöre gösterir. Panelde Japoncanın yanında durur.
"""
import pytest
from pydantic import ValidationError

from short_bot.lang_review import (NativeVerdict, back_translate,
                                   judge_native_text)


class _Boom:
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise RuntimeError("backend down")


def _fake_run_json(payload):
    def _run(prompt, schema, **kw):
        _run.prompt = prompt
        return schema.model_validate(payload)
    return _run


# ------------------------------------------------------------------ yerli okur

def test_natural_is_required_so_empty_json_fails_closed():
    """Şema default'u OLMAMALI: model {} dönünce 'doğal' sayılmak SESSİZ geçiştir."""
    with pytest.raises(ValidationError):
        NativeVerdict.model_validate({})


def test_judge_returns_verdict(monkeypatch):
    monkeypatch.setattr("short_bot.lang_review.run_json",
                        _fake_run_json({"natural": False, "issue": "çeviri kokuyor"}))
    v = judge_native_text("この文は変です", language="ja")
    assert v is not None and v.natural is False
    assert "çeviri" in v.issue


def test_judge_prompt_names_the_target_language(monkeypatch):
    fake = _fake_run_json({"natural": True, "issue": ""})
    monkeypatch.setattr("short_bot.lang_review.run_json", fake)
    judge_native_text("テスト文です", language="ja")
    assert "Japanese" in fake.prompt


def test_judge_returns_none_on_backend_failure(monkeypatch):
    boom = _Boom()
    monkeypatch.setattr("short_bot.lang_review.run_json", boom)
    assert judge_native_text("テスト", language="ja") is None
    assert boom.calls >= 2, "geçici hatada en az bir kez yeniden denenmeli"


def test_judge_skips_empty_text(monkeypatch):
    boom = _Boom()
    monkeypatch.setattr("short_bot.lang_review.run_json", boom)
    assert judge_native_text("   ", language="ja") is None
    assert boom.calls == 0


def test_judge_rejects_unknown_language():
    """Bilinmeyen dilde SESSİZCE 'Turkish' varsayma — yargı anlamsızlaşır."""
    with pytest.raises(ValueError):
        judge_native_text("test", language="xx")


# ------------------------------------------------------------------ geri çeviri

def test_back_translate_returns_turkish(monkeypatch):
    monkeypatch.setattr("short_bot.lang_review.run_json",
                        _fake_run_json({"turkish": "Bu çocuk yalnızdı."}))
    assert back_translate("この子は一人だった", language="ja") == "Bu çocuk yalnızdı."


def test_back_translate_is_fail_open(monkeypatch):
    """Çeviri patlarsa üretim DURMAZ — geri çeviri bir kolaylık, bir kapı değil."""
    monkeypatch.setattr("short_bot.lang_review.run_json", _Boom())
    assert back_translate("テスト", language="ja") == ""


def test_back_translate_skips_turkish_source():
    """Türkçe kanalda çağrılırsa boş döner — çeviriye gerek yok, para harcama."""
    assert back_translate("Bu çocuk yalnızdı.", language="tr") == ""
