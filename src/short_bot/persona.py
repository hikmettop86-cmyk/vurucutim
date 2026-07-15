"""Reel anlatım personası: few-shot örneği + ton kuralları.

Persona metni DİL PAKETİNDEN gelir (Türk dizisi referansları yalnız tr'de). Bilinmeyen
slug ya da yanlış dil RuntimeError verir — sessizce kişiliksiz'e / yanlış dile düşmek
YASAK: kullanıcı mizah seçtiyse mizah almalı, seçmediyse bugünkü davranışı almalı.
"""
from __future__ import annotations

from pydantic import BaseModel

from short_bot.lang_pack import load_pack


class Persona(BaseModel):
    slug: str
    few_shot: str
    rules: list[str]
    humor_check: bool = True


def load_persona(slug: str, *, language: str) -> Persona | None:
    if not (slug or "").strip():
        return None                      # kişiliksiz: bugünkü prompt, sıfır regresyon
    pack = load_pack(language)
    data = (pack.personas or {}).get(slug)
    if not data:
        raise RuntimeError(
            f"persona '{slug}' {language} dil paketinde yok — "
            f"bu persona bu dilde tanımlı değil (sessiz düşme yok)")
    return Persona(slug=slug, few_shot=data.get("few_shot", ""),
                   rules=list(data.get("rules", [])),
                   humor_check=bool(data.get("humor_check", True)))


def persona_block(persona: Persona) -> str:
    kurallar = "\n".join(f"{i+1}. {r}" for i, r in enumerate(persona.rules))
    return (
        "=== ANLATIM PERSONASI (TON — EN ÖNEMLİ KATMAN) ===\n"
        "Bu videoyu aşağıdaki KOMİK personada yaz. İçerik yapısı (hook→tırmanış→tepe→"
        "callback) AYNI kalır; DEĞİŞEN şey TONDUR. Sıkıcı belgesel anlatıcısı DEĞİL —\n"
        "izleyiciyle mahallede çay içer gibi, racon keserek, kahkaha attırarak konuş.\n"
        "Bilgi GERÇEK, anlatım MAHALLE AĞZI.\n\n"
        f"TARZIN TAM ÖRNEĞİ (aynen bunun tadında yaz):\n---\n{persona.few_shot}\n---\n\n"
        f"KURALLAR (hepsi ZORUNLU):\n{kurallar}\n\n"
        "MİZAH SIKIŞTIRILAMAZ: kelimeleri kısıp esprisiz özet çıkarma. Nefes alanı "
        "olan, kurulup boşalan şakalar yaz. Her beat bir sahne/espri taşısın.\n\n"
        "ÇIKTI DİSİPLİNİ (JSON BOZULMASIN): Senaryo metinlerinde (hook, beat, close, "
        "comment) ASLA çift tırnak (\") kullanma — diyalog/alıntı için TEK tırnak (') "
        "kullan. Örnek: karga 'kırmızı tişörtlü cimrinin teki geçti' der. Yanıt "
        "SADECE geçerli JSON olsun, markdown kod bloğu ekleme.\n")
