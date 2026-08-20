"""TTS sağlayıcı tablosu: kanalın ``voice.provider`` değerini somut çağrılara bağlar.

Tek yerde tutulur ki voiced.py / pipeline / panel aynı eşlemeyi kullansın.
Sağlayıcılar birbirine YEDEK DEĞİLDİR: ses evrenleri farklı, kanalın sesi
sessizce değişmemeli (faceless-2'den taşınan karar).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from short_bot.tts import ai33_client, cartesia_client

PROVIDERS: tuple[str, ...] = ("ai33", "cartesia")


@dataclass(frozen=True)
class TtsProvider:
    name: str
    label: str
    synthesize: Callable
    health_check: Callable
    resolve_api_key: Callable[[dict | None], str]
    speed_range: tuple[float, float]
    # synthesize imzasında bu sağlayıcının KABUL ETTİĞİ ek anahtarlar. ai33'e
    # volume/model geçmek TypeError verirdi; voiced.py yalnız bunları iletir.
    extra_kwargs: tuple[str, ...]
    # Sentez kelime zaman damgası döndürüyorsa whisper hizalaması atlanır.
    returns_words: bool
    key_hint: str


_TABLE: dict[str, TtsProvider] = {
    "ai33": TtsProvider(
        name="ai33", label="ai33",
        synthesize=ai33_client.synthesize,
        health_check=ai33_client.health_check,
        resolve_api_key=ai33_client.resolve_ai33_api_key,
        speed_range=(0.5, 1.5), extra_kwargs=(), returns_words=False,
        key_hint="AI33_API_KEY (Ayarlar → API anahtarları)",
    ),
    "cartesia": TtsProvider(
        name="cartesia", label="Cartesia",
        synthesize=cartesia_client.synthesize,
        health_check=cartesia_client.health_check,
        resolve_api_key=cartesia_client.resolve_cartesia_api_key,
        speed_range=cartesia_client.SPEED_RANGE,
        extra_kwargs=("volume", "model", "emotion", "language", "usage_dir"),
        returns_words=True,
        key_hint="CARTESIA_API_KEY (Ayarlar → API anahtarları)",
    ),
}


def resolve_tts(provider: str) -> TtsProvider:
    try:
        return _TABLE[(provider or "ai33").strip().lower()]
    except KeyError:
        raise ValueError(f"bilinmeyen TTS sağlayıcısı {provider!r}; "
                         f"geçerli: {', '.join(PROVIDERS)}") from None
