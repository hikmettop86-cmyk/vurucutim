"""Storyblocks footage kaynağı: giriş-yapılmış tarayıcıyla arama-sayfası kazıma.

faceless-2 `src/providers/storyblocks-video.js` portu. Storyblocks bir API DEĞİL —
giriş yapılmış Chrome ile arama sayfaları kazınır ve üye "Download" düğmesine
tıklanır (``storyblocks_browser`` tekili üzerinden).

TASARIM NOTLARI:
- LAZY: playwright bu modülde modül-üstünde import EDİLMEZ. ``import
  short_bot.storyblocks_source`` Chrome AÇMAZ. Tarayıcıya dokunan TEK metotlar
  ``_scrape_page`` ve ``_member_download``; ikisi de ``storyblocks_browser``'ı
  fonksiyon-içi import eder.
- HER tarayıcı çağrısı try/except ile []/None'a çevrilir — bozuk oturum/WAF asla
  reel üretimini ABORT ETMEZ (çağıran zincirde sıradaki kaynağa düşer).
- Testler ``_scrape_page`` / ``_member_download``'ı örnek üstünde monkeypatch'ler;
  saf mantık (query sadeleştirme, kart eşleme, filigran reddi) tarayıcısız sınanır.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import quote

from short_bot.footage_sources import FootageCandidate

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Query sadeleştirme (faceless-2 _simplifyQuery portu)
# Storyblocks tag-tabanlı; uzun cümle 0 sonuç → stopword sil + ilk 5 içerik kelimesi.
# ---------------------------------------------------------------------------
STOPWORDS = set((
    "a an the and or but of in on at to for with by from as is are was were be "
    "been being have has had do does did will would could should may might must "
    "can shall this that these those it its into onto about after before between "
    "during over under through we you they their our us them his her him she he i "
    "me my mine story stories video videos footage"
).split())
MAX_QUERY_WORDS = 5

# ---------------------------------------------------------------------------
# Seçici + URL sabitleri — Storyblocks grid'ini yeniden tasarlarsa BURAYI değiştir.
# faceless-2 _SEARCH_URL / _HYDRATE_SELECTOR / _MAX_PAGES / _COLLECT_LIMIT aynası.
# ---------------------------------------------------------------------------
_SEARCH_URL = ("https://www.storyblocks.com/video/search/{query}"
               "?orientation=horizontal&content-type=footage&page={page}")
_HYDRATE_SELECTOR = "[data-stock-id]"
_MAX_PAGES = 4
_COLLECT_LIMIT = 15
# WATERMARK-GUARD: temiz üye-indirmesi (paid, HD) tipik birkaç MB+. Plan-kapsamı-dışı
# asset'lerde "Download" CTA temiz dosya yerine preview-COMP (watermark'lı, ~KB–1MB)
# verir. Bu eşiğin altı watermark'lı sayılır → reddet (çağıran temiz kaynağa düşer).
SB_MIN_CLEAN_BYTES = 1_500_000

# Kart kazıma JS'i (faceless-2 page.evaluate portu). Tek eval çağrısı; per-element
# Locator zincirleri eksik iç öğede 30sn bloklar, JS eval mikrosaniyedir.
# Dönüş şekli: [{id, href, thumb, title}] — _map_card ile birebir.
_EXTRACT_JS = r"""(maxN) => {
  const containers = document.querySelectorAll(
    '[data-stock-id], [data-testid="video-stock-item-card"]'
  );
  const out = [];
  const seen = new Set();
  for (const el of containers) {
    if (out.length >= maxN) break;
    let id = el.getAttribute('data-stock-id') || '';
    let href = '';
    const innerLink = el.querySelector('a[href*="/video/stock/"]');
    if (innerLink) {
      href = innerLink.href || innerLink.getAttribute('href') || '';
    } else if (el.tagName === 'A') {
      href = el.href || el.getAttribute('href') || '';
    }
    if (!href) continue;
    if (!id) {
      const m = href.match(/-(\d+)(?:[?#/]|$)/);
      if (!m) continue;
      id = m[1];
    }
    if (seen.has(id)) continue;
    seen.add(id);
    const img = el.querySelector('img');
    let title = '';
    let thumb = '';
    if (img) {
      title = (img.getAttribute('alt') || '').trim();
      thumb = img.src || img.getAttribute('src') || '';
    }
    if (!title) {
      title = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
    }
    out.push({ id, href, thumb, title });
  }
  return out;
}"""


def _simplify_query(query: str) -> str:
    """Stopword sil + ilk 5 içerik kelimesi (faceless-2 _simplifyQuery portu)."""
    if not query:
        return ""
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(query).lower())
    words = [w for w in cleaned.split() if w and len(w) > 1 and w not in STOPWORDS]
    if not words:
        return " ".join(str(query).split()[:MAX_QUERY_WORDS])
    return " ".join(words[:MAX_QUERY_WORDS])


class StoryblocksSource:
    """FootageSource protokolü: giriş-yapılmış tarayıcıyla Storyblocks kazıma.

    ``session_path`` yoksa (dağıtılan kullanıcılar) ``available()`` False döner →
    kaynak zincirde sessizce atlanır.
    """
    name = "storyblocks"

    def __init__(self, session_path=None, max_concurrent: int = 3):
        self.session_path = session_path
        self.max_concurrent = max_concurrent

    # -- protokol -----------------------------------------------------------
    def available(self) -> bool:
        """Session dosyası var + >50 bayt (faceless-2 isAvailable karşılığı)."""
        p = self.session_path
        if not p:
            return False
        try:
            p = Path(p)
            return p.exists() and p.stat().st_size > 50
        except Exception:
            return False

    def search(self, query, *, max_results, orientation):
        """Sayfa 1.._MAX_PAGES kazı, kartları FootageCandidate'e eşle (≤ limit).

        orientation yok sayılır (URL her zaman horizontal footage). Boş sayfa ya da
        yeni-ID-yok → erken dur. Her hata []'e çevrilir (üretim durmaz)."""
        try:
            q = _simplify_query(query)
            if not q:
                return []
            if not self.available():
                return []
            limit = min(int(max_results or 0) or _COLLECT_LIMIT, _COLLECT_LIMIT)
            seen: set[str] = set()
            out: list[FootageCandidate] = []
            for page_num in range(1, _MAX_PAGES + 1):
                if len(out) >= limit:
                    break
                url = _SEARCH_URL.format(query=quote(q[:200]), page=page_num)
                try:
                    cards = self._scrape_page(url)
                except Exception as e:
                    log.warning(f"storyblocks sayfa kazıma hatası: {e}")
                    cards = []
                added = 0
                for card in (cards or []):
                    if len(out) >= limit:
                        break
                    cand = self._map_card(card)
                    if cand is None:
                        continue
                    if cand.ident in seen:
                        continue
                    seen.add(cand.ident)
                    out.append(cand)
                    added += 1
                # Sayfa boş ya da hep-dup (katalog tükendi / sonuç döngüsü) → dur.
                if not cards or added == 0:
                    break
            return out
        except Exception as e:
            log.warning(f"storyblocks arama hatası: {e}")
            return []

    def download(self, cand, cache_dir):
        """SHA-1(url) önbellek → yoksa üye-indirmesi. <1.5MB (filigran) → sil, None.

        Herhangi bir hata → None (çağıran temiz kaynağa düşer)."""
        try:
            cache_dir = Path(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            out = self._cache_path_for(cand.url, cache_dir)
            # Cache-hit: yalnız filigran-eşiğini GEÇEN dosya yeniden kullanılır
            # (eşik-altı comp yok sayılır → taze indirme denenir).
            try:
                if out.exists() and out.stat().st_size >= SB_MIN_CLEAN_BYTES:
                    return out
            except Exception:
                pass
            saved = self._member_download(cand.url, out)
            if saved is None:
                return None
            saved = Path(saved)
            try:
                size = saved.stat().st_size
            except Exception:
                size = 0
            if size < SB_MIN_CLEAN_BYTES:
                # WATERMARK-GUARD: temiz üye-indirmesi birkaç MB+; eşik-altı =
                # plan-kapsamı-dışı asset'in preview-COMP'u (watermark'lı). Reddet.
                log.info(
                    f"storyblocks: indirme çok küçük "
                    f"({size // 1024}KB < {SB_MIN_CLEAN_BYTES // 1024}KB) — "
                    f"filigran şüphesi, reddedildi")
                try:
                    saved.unlink()
                except Exception:
                    pass
                return None
            return saved
        except Exception as e:
            log.warning(f"storyblocks indirme hatası: {e}")
            return None

    # -- saf yardımcılar (tarayıcısız) --------------------------------------
    def _map_card(self, card) -> "FootageCandidate | None":
        """Ham kart dict'i → FootageCandidate. Süre bilinmiyor → 6 (MIN_CLIP_S üstü)."""
        ident = str(card.get("id") or "").strip()
        if not ident:
            return None
        href = card.get("href") or ""
        if not href:
            return None
        if href.startswith("/"):
            href = "https://www.storyblocks.com" + href
        thumb = str(card.get("thumb") or "")
        return FootageCandidate(url=href, duration_s=6, image=thumb,
                                source="storyblocks", ident=ident)

    def _cache_path_for(self, detail_url, cache_dir) -> Path:
        """Asset başına kararlı önbellek anahtarı: SHA-1(detail URL) ilk 16 hex."""
        h = hashlib.sha1(str(detail_url or "").encode("utf-8")).hexdigest()[:16]
        return Path(cache_dir) / f"sb-cache-{h}.mp4"

    # -- tarayıcı metotları (TEK browser dokunuşu; testlerde monkeypatch'lenir) --
    def _scrape_page(self, url, deadline=None):
        """Bir arama sayfasını kaz → [{id, href, thumb, title}]. Hata → []."""
        try:
            from short_bot import storyblocks_browser as sb

            def _job(page):
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                # React grid'i hydrate olsun (domcontentloaded çok erken tetiklenir).
                try:
                    page.wait_for_selector(_HYDRATE_SELECTOR, timeout=12000)
                except Exception:
                    return []   # kart yok → boş sayfa
                try:
                    raw = page.evaluate(_EXTRACT_JS, _COLLECT_LIMIT)
                except Exception:
                    return []
                return raw or []

            res = sb.with_page(self.session_path, _job)
            return res or []
        except Exception as e:
            log.warning(f"storyblocks _scrape_page hatası: {e}")
            return []

    def _member_download(self, detail_url, out):
        """Üye (paid, temiz) indirme: detay sayfası → member CTA → download event.

        ``.memberDownloadCta-cta button.PrimaryButton`` (member "Download") tıklanır;
        ``.previewButton`` ("Download Watermarked") DEĞİL. Hata → None."""
        try:
            from short_bot import storyblocks_browser as sb
            out = Path(out)

            def _job(page):
                page.goto(detail_url, wait_until="domcontentloaded", timeout=25000)
                # MEMBER (paid, TEMİZ) indirme düğmesi — brand-yellow "Download".
                try:
                    btn = page.wait_for_selector(
                        ".memberDownloadCta-cta button.PrimaryButton", timeout=12000)
                except Exception:
                    btn = None
                if btn is None:
                    return None   # member CTA yok (login değil/kapsam-dışı) → degrade
                # expect_download tıklamadan ÖNCE event'i kurar (yarışı önler).
                try:
                    with page.expect_download(timeout=45000) as dl_info:
                        btn.click()
                    dl = dl_info.value
                except Exception:
                    return None   # timeout / page-close → degrade
                if dl is None:
                    return None
                dl.save_as(str(out))
                return out

            return sb.with_page(self.session_path, _job)
        except Exception as e:
            log.warning(f"storyblocks _member_download hatası: {e}")
            return None
