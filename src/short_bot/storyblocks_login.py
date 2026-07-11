"""Storyblocks headed login → storage_state kaydı (faceless-2 `storyblocks-login.js` portu).

BU MODÜL GERÇEK, GÖRÜNÜR (headed) bir Chrome AÇAR — YALNIZ ``storyblocks-login`` CLI
komutundan çağrılır, ASLA testlerden. playwright modül-üstünde import EDİLMEZ (lazy).

Akış (faceless-2 _runLogin portu):
  1. anti-detect headed Chrome başlat (channel="chrome", bulunmazsa bundled).
  2. storyblocks.com/login'e git.
  3. ≤300sn ``a[href*="/member/"]`` için poll (giriş kanıtı = SAYFA DURUMU, WAF-safe).
  4. Görülünce ``context.storage_state()`` → session dosyasına yaz.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

LOGIN_URL = "https://www.storyblocks.com/login"
TIMEOUT_SECONDS = 300
POLL_INTERVAL_S = 2.0
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def session_status(session_path) -> dict:
    """Oturum dosyası durum özeti (tarayıcı AÇMAZ)."""
    p = Path(session_path)
    has = p.exists()
    size = None
    age = None
    if has:
        try:
            st = p.stat()
            size = st.st_size
            age = int(time.time() - st.st_mtime)
        except Exception:
            has = False
    return {"has_session": has, "path": str(p), "size": size, "age_seconds": age}


def delete_session(session_path) -> bool:
    """Kayıtlı oturum dosyasını sil. Yoksa False (idempotent)."""
    p = Path(session_path)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except Exception:
        return False


def run_login(session_path, *, timeout_s: int = TIMEOUT_SECONDS) -> dict:
    """Headed Chrome ile giriş akışı; başarıda storage_state'i kaydeder.

    GERÇEK tarayıcı açar — testlerde çağrılmaz. Dönüş: {ok, state, message}.
    """
    session_path = Path(session_path)
    from playwright.sync_api import sync_playwright

    anti_detect = ["--disable-blink-features=AutomationControlled"]
    ignore_defaults = ["--enable-automation"]
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                channel="chrome", headless=False,
                args=anti_detect, ignore_default_args=ignore_defaults)
            channel_used = "chrome"
        except Exception:
            browser = pw.chromium.launch(
                headless=False, args=anti_detect,
                ignore_default_args=ignore_defaults)
            channel_used = "chromium"
        try:
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900}, user_agent=_USER_AGENT)
            # navigator.webdriver'ı gizle (anti-detect).
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page = ctx.new_page()
            try:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass  # ağ hatası — kullanıcı manuel yönlendirebilir
            print(f"Tarayıcı açıldı ({channel_used}) — Storyblocks giriş formuyla "
                  f"devam et.")
            print("E-posta + şifre önerilir (Google girişi bot filtrelerine "
                  "takılabilir).")

            # Giriş kanıtı = SAYFA DURUMU (member-nav). a[href*="/member/"] yalnız
            # başarılı giriş sonrası belirir → WAF-safe.
            deadline = time.time() + timeout_s
            detected = False
            while time.time() < deadline:
                try:
                    detected = page.query_selector('a[href*="/member/"]') is not None
                except Exception:
                    detected = False  # sayfa yönleniyor/kapandı — sonraki poll'da dene
                if detected:
                    break
                time.sleep(POLL_INTERVAL_S)

            if not detected:
                return {"ok": False, "state": "timeout",
                        "message": f"{timeout_s // 60} dakikada giriş tamamlanmadı"}

            try:
                session_path.parent.mkdir(parents=True, exist_ok=True)
                ctx.storage_state(path=str(session_path))
            except Exception as e:
                return {"ok": False, "state": "error",
                        "message": f"Oturum kaydedilemedi: {e}"}
            return {"ok": True, "state": "ok",
                    "message": f"Giriş başarılı — oturum kaydedildi: {session_path}"}
        finally:
            try:
                browser.close()
            except Exception:
                pass
