"""Mizah doğrulama kapısı — reel_factcheck.check_narration'ın kardeşi.

Persona'lı (mizah) senaryoyu ikinci bir LLM çağrısıyla denetler: KOMİK mi (zorlama
değil), referanslar GERÇEK mi, biyoloji DOĞRU mu. Boş liste = temiz. Denetim çökerse
BOŞ LİSTE (üretim durmaz) + log — tek LLM arızası üretimi öldürmesin (bu oturumun
kanıtlanmış dersi: güçlü prompt yetmez, kapı şart; ama kapı da fail-open olmalı).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from short_bot.claude_cli import run_json

log = logging.getLogger(__name__)

_LANG_NAMES = {"tr": "Türkçe", "de": "Almanca", "en": "İngilizce"}


class HumorIssue(BaseModel):
    problem: str
    kind: str = "humor"        # "humor" | "reference" | "biology"


class _Issues(BaseModel):
    issues: list[HumorIssue] = []


def _prompt(topic: str, text: str, lang: str) -> str:
    return f"""Aşağıdaki {lang} mizah senaryosunu DENETLE. Konu: {topic}

SENARYO:
{text}

Şu üç ölçütü kontrol et ve YALNIZ GERÇEK sorunları bildir:
1. KOMİK mi? Bir BÜTÜN olarak eğlenceli mi, yoksa düz belgesel mi? (Her cümle şaka
   olmak zorunda DEĞİL — genel tat komikse sorun yok. Gerçekten sıkıcı/zorlama ise
   "humor" sorunu.)
2. REFERANSLAR GERÇEK mi? Uydurma/var olmayan dizi/karakter/olay varsa "reference" sorunu.
   (Gerçek ve tema-uyumlu referanslar SORUN DEĞİL.)
3. BİYOLOJİ DOĞRU mu? Hayvan hakkında NET yanlış bilgi (yanlış ölçü, yanlış sınıf,
   uydurma yetenek) varsa "biology" sorunu. NET yanlışı işaretle — sayılar/ölçüler
   özellikle dikkat.

ÖNEMLİ İSTİSNALAR (bunları SORUN SAYMA):
- Mizahi HİPERBOL olgu hatası DEĞİLDİR: 'özgüven kıtaya sığmıyor', 'Afrika'nın vergi
  memuru', 'kobra zehri ona ayran aşısı' gibi abartılar mizahtır, yanlış bilgi değil.
- 'Aşık [Hayvan] der ki: ...' kapanışı bu kanalın İMZASIDIR (marka), klişe/tekrar SAYMA.
- Karakterleştirme ('mahalle delisi', 'ağır abi') üsluptur, olgu iddiası değil.

Sorun yoksa boş liste döndür. SADECE şu JSON: {{"issues": [{{"problem": "...", "kind": "humor|reference|biology"}}]}}"""


def check_humor(topic: str, *, text: str, language: str, claude_path: str = "claude",
                model: str = "default", backend: str = "claude_cli",
                api_key: str | None = None, invoke=None) -> list[HumorIssue]:
    """Mizah senaryosundaki sorunlar. Boş liste = temiz.

    DENETİM ÇÖKERSE BOŞ LİSTE döner (üretim DURMAZ) + loglanır.
    ``invoke``: test enjeksiyonu (gerçek LLM'siz).
    """
    if not (text or "").strip():
        return []
    lang = _LANG_NAMES.get(language, "Türkçe")
    p = _prompt(topic, text, lang)
    try:
        if invoke is not None:
            v = invoke(p, _Issues)
        else:
            v = run_json(p, _Issues, claude_path=claude_path, model=model,
                         backend=backend, api_key=api_key, retries=1, timeout_s=120)
    except Exception as e:   # noqa: BLE001 — denetim çökse de üretim durmamalı
        log.warning(f"  mizah denetimi çalışmadı ({e}) → atlanıyor")
        return []
    return [i for i in v.issues if (i.problem or "").strip()]


def humor_feedback(issues: list[HumorIssue]) -> str:
    satirlar = "\n".join(f"  - [{i.kind}] {i.problem}" for i in issues)
    return ("\n\nÖNCEKİ DENEME ŞU MİZAH SORUNLARINI TAŞIYORDU — düzelt:\n"
            f"{satirlar}\n"
            "Referanslar GERÇEK olmalı, biyoloji DOĞRU olmalı, mizah zorlama değil "
            "GERÇEKTEN komik olmalı.\n")
