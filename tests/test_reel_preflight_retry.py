"""TTS preflight GEÇİCİ kesintide üretimi düşürmemeli — yeniden denemeli.

GERÇEK OLAY (3 kez): ai33 preflight "servis yanıt vermiyor" dedi ve koşu düştü.
Hemen ardından elle kontrol edince servis SAĞLIKLI çıktı — yani anlık bir kesintiydi.

Preflight'ın amacı LLM/TTS kredisi harcamadan ÖNCE durmak (doğru bir amaç). Ama
"error" (servis yanıt vermiyor) GEÇİCİ bir durumdur; "auth" (anahtar geçersiz) ya da
"no-key" KALICIDIR. Geçici olanı yeniden dene, kalıcı olanda ANINDA dur — beklemenin
faydası yok.
"""
import pytest

from short_bot.config import ReelConfig
from short_bot.reel import PREFLIGHT_RETRIES, ReelDeps, produce_reel_video


class _Channel:
    slug = "t"; language = "tr"; handle = "@t"
    colors = {"primary": "#0ea5e9", "accent": "#facc15",
              "bg_gradient": ["#0f172a", "#020617"]}
    reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(25, 45))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Gerçek geri çekilme beklemesi süiti yavaşlatmasın (davranış aynı)."""
    monkeypatch.setattr("time.sleep", lambda *_a: None)


def _call(deps, tmp_path):
    return produce_reel_video(
        topic="konu", channel=_Channel(), templates_dir="templates",
        work_dir=tmp_path, out_path=tmp_path / "o.mp4", music_path=None,
        ai33_api_key="k", pexels_api_key="p", deps=deps)


def test_transient_outage_is_retried(tmp_path):
    """İlk çağrı 'error', ikinci 'healthy' → üretim DEVAM ETMELİ."""
    calls = []

    def health(**kw):
        calls.append(1)
        return "error" if len(calls) == 1 else "healthy"

    # Preflight'tan sonraki ilk adımda kasten dur (asıl testimiz preflight)
    def narr(*a, **kw):
        raise RuntimeError("PREFLIGHT_GECTI")

    deps = ReelDeps(health_check=health, write_reel_narration=narr)
    with pytest.raises(RuntimeError, match="PREFLIGHT_GECTI"):
        _call(deps, tmp_path)
    assert len(calls) == 2, "geçici kesinti yeniden denenmedi"


def test_permanent_failure_does_not_waste_time_retrying(tmp_path):
    """'auth' (anahtar geçersiz) KALICIDIR — beklemenin faydası yok, ANINDA dur."""
    calls = []

    def health(**kw):
        calls.append(1)
        return "auth"

    deps = ReelDeps(health_check=health)
    with pytest.raises(RuntimeError, match="geçersiz"):
        _call(deps, tmp_path)
    assert len(calls) == 1, "kalıcı hata için boşuna yeniden denendi"


def test_gives_up_after_the_retry_budget(tmp_path):
    """Servis gerçekten kapalıysa sonsuza kadar denemez."""
    calls = []

    def health(**kw):
        calls.append(1)
        return "error"

    deps = ReelDeps(health_check=health)
    with pytest.raises(RuntimeError, match="yanıt vermiyor"):
        _call(deps, tmp_path)
    assert len(calls) == PREFLIGHT_RETRIES
