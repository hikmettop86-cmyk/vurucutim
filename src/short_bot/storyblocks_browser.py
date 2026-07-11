"""Storyblocks Playwright tekil tarayıcı tutucu (sync_playwright).

faceless-2 `storyblocks-browser.js` portu. Süreç ömrü boyunca TEK playwright +
browser + context tutar; her ``with_page`` çağrısı paylaşılan context'te yeni bir
Page açar.

TASARIM NOTLARI:
- LAZY: playwright modül-üstünde İÇE AKTARILMAZ. Bu modülü import etmek Chrome
  AÇMAZ ve playwright'ın kurulu olmasını GEREKTIRMEZ. İlk ``with_page`` çağrısına
  kadar tarayıcı başlatılmaz.
- ``channel="chrome"`` (kullanıcının Chrome'u) + anti-detect argümanlar Storyblocks
  AWS-WAF bot kontrolünü geçmek için (faceless-2 spike-onaylı). Chrome kurulu
  değilse bundled Chromium'a düşer.
- ``sync_playwright`` iş parçacığı-güvenli değil → tek kilit tüm ``with_page``
  çağrılarını serialize eder. Semaphore(SB_MAX_CONCURRENT) limiter sözleşmesini
  korur (üretim tek iş parçacıklı; port sadakati için tutulur).
"""
from __future__ import annotations

import atexit
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# EŞZAMANLILIK: faceless-2 Fortaleza build → varsayılan 3. SB_MAX_CONCURRENT ile
# geçersiz kılınır. Sorun olursa 1'e düşür.
try:
    SB_MAX_CONCURRENT = max(1, int(os.environ.get("SB_MAX_CONCURRENT", "3") or "3"))
except (TypeError, ValueError):
    SB_MAX_CONCURRENT = 3

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Modül-seviyesi tekil durum (tek browser + tek context)
# ---------------------------------------------------------------------------
_pw = None
_browser = None
_ctx = None
_lock = threading.Lock()
_sema = threading.Semaphore(SB_MAX_CONCURRENT)


def is_ready(session_path) -> bool:
    """Session dosyası var + >50 bayt ise True. Çağıranlar tarayıcıya dokunmadan
    kısa devre yapar (faceless-2 ``isReady`` karşılığı)."""
    if not session_path:
        return False
    try:
        p = Path(session_path)
        return p.exists() and p.stat().st_size > 50
    except Exception:
        return False


def _ensure_context(session_path):
    """Browser + context'i tam bir kez başlat (playwright'ı burada, LAZY import et).

    channel="chrome" (spike-onaylı) önce; başarısızsa bundled Chromium'a düş
    (faceless-2 try/except fallback'i)."""
    global _pw, _browser, _ctx
    if _ctx is not None:
        return _ctx
    from playwright.sync_api import sync_playwright

    # Kısmi başlatma (ör. bozuk storage_state → new_context patlar) süreç sızıntısı
    # bırakmasın: hata olursa close() ile _pw/_browser'ı kapat + tekili sıfırla.
    try:
        _pw = sync_playwright().start()
        anti_detect = ["--disable-blink-features=AutomationControlled"]
        ignore_defaults = ["--enable-automation"]
        try:
            _browser = _pw.chromium.launch(
                channel="chrome", headless=True,
                args=anti_detect, ignore_default_args=ignore_defaults)
        except Exception:
            _browser = _pw.chromium.launch(
                headless=True, args=anti_detect, ignore_default_args=ignore_defaults)
        _ctx = _browser.new_context(
            storage_state=str(session_path),
            user_agent=_USER_AGENT,
            accept_downloads=True,
        )
        # navigator.webdriver'ı gizle (faceless-2 stealth init script'i).
        _ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        return _ctx
    except Exception:
        close()   # kısmi _pw/_browser'ı kapat, tekili sıfırla → sonraki çağrı temiz kurar
        raise


def with_page(session_path, fn):
    """Paylaşılan context'te yeni Page aç, ``fn(page)`` çağır, page'i kapat.

    Session yoksa hemen None döner (tarayıcı AÇILMAZ). fn içindeki istisnalar
    çağırana bırakılır — çağıran (storyblocks_source) try/except ile None/[]'e
    çevirir, böylece bozuk oturum/WAF üretimi durdurmaz."""
    if not is_ready(session_path):
        return None
    with _sema:
        with _lock:
            try:
                ctx = _ensure_context(session_path)
                page = ctx.new_page()
            except Exception:
                # başlatma / ölü context (tarayıcı çökmüş) → tekili sıfırla ki
                # bir sonraki çağrı taze bir tarayıcı kursun (kalıcı devre-dışı olmasın)
                close()
                raise
            try:
                return fn(page)
            finally:
                try:
                    page.close()
                except Exception:
                    pass


def close() -> None:
    """Tarayıcıyı kapat + tekil durumu sıfırla. Idempotent; tüm hataları yutar.
    atexit'e kayıtlı — Chrome zombi kalmasın."""
    global _pw, _browser, _ctx
    ctx, browser, pw = _ctx, _browser, _pw
    _ctx = _browser = _pw = None
    for obj in (ctx, browser):
        if obj is not None:
            try:
                obj.close()
            except Exception:
                pass
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass


atexit.register(close)
