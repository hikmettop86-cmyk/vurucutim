"""Google AI Studio rotasyonlu anahtar havuzu — vision için (faceless-2 portu).

Durum makinesi (key:model başına): active | rpm-cooldown | daily-exhausted;
anahtar başına: banned. Kota Google'da PerProjectPerModel — 500/gün/key/model
(canlı 429 ölçümü), PT-geceyarısı sıfırlar, 15 RPM. Tükenince
``GoogleStudioExhausted`` fırlar → çağıran OpenRouter gemma'ya düşer.

Kaynak tasarım: faceless-2/src/google-key-pool.js (leaner port — bizim vision
yükümüz ~8 paralel işçi, faceless'in 12-anahtar fırtına yükünün çok altında;
learnedCaps/overflow-şerit gibi ağır telemetri YAGNI'yle atlandı).
"""
from __future__ import annotations

import base64
import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

DAILY_CAP = 500          # key:model başına bedava/gün (canlı 429 ölçümü)
RPM = 15                 # Google bedava PerMinute
RPM_MARGIN = 0.8         # güvenli pace payı → ceil(12)/dk/key
# ÖLÇÜLDÜ (2026-07-18 canlı): ücretsiz-tier'ın 429'u genelde DETAYSIZ 'RESOURCE_EXHAUSTED'
# (violations/retryDelay YOK) = anahtar/gün kotası DEĞİL, Google'ın PAYLAŞILAN ücretsiz-tier
# kapasite reddi (burst throttle). Rotasyon bunu ÇÖZMEZ (per-key değil). 8-16 paralel çağrı
# bu limiti tetikliyor → onlarca çağrı erkence gemma'ya düşüyordu (bkz. _gemini_prod.log).
# Çözüm: (a) global eşzamanlılık tavanı ile Google'ı burst'e zorlama, (b) capacity 429'da
# SABIRLI retry (uzun deadline + artan geri-çekilme) → gemma yalnız gerçek uzun throttle'da.
# KISA sabırlı retry: KISA throttle dalgasını (birkaç sn) atlat AMA SÜREKLİ throttle'da
# hızla gemma'ya bail (ÖLÇÜLDÜ 2026-07-18: 30s deadline sürekli throttle'da boşa dönüp
# uncapped'ten kötü olabiliyordu). 18s ~ birkaç retry'lık pencere; geçmezse gemma doğru karar.
WAIT_FOR_SLOT_S = 18.0
RPM_FALLBACK_COOLDOWN_S = 60.0    # sunucu retryDelay vermezse
MAX_TRANSIENT_ATTEMPTS = 3
CAPACITY_PAUSE_BASE_S = 0.5       # capacity 429 geri-çekilme tabanı (0.25→0.5, Google dinlensin)
CAPACITY_PAUSE_MAX_S = 3.0        # azami duraklama (deadline 18s içinde birkaç retry sığsın)

# GLOBAL EŞZAMANLILIK TAVANI: aynı anda en çok bu kadar HTTP çağrısı Google'a gider —
# çağıran havuz kaç thread açarsa açsın (footage GATE_WORKERS=8, feeds=10, birden çok
# pipeline aynı anda). ÖLÇÜLDÜ: sıralı ~0 429; 8-paralel ~%38 429 → erken gemma. Tavan tüm
# çağıranları TEK noktadan sınırlar → burst kapasite-reddi büyük ölçüde kaybolur. set_pool_dir
# gibi başlangıçta set_max_concurrency ile ayarlanır (settings.google_studio.max_concurrency).
MAX_CONCURRENCY = 4

# PT (America/Los_Angeles): yaz UTC-7 (PDT). Sabit ofset — kota penceresi gün-kaba;
# DST geçiş anındaki ~1sn'lik kayma kota için önemsiz. stdlib-only (bağımlılık yok).
_PT_OFFSET_H = -7

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Güvenlik filtrelerini KAPAT: girdi stok DOĞA görüntüsü (avcı/kavga/av), çıktı nötr TARİF.
# Gemini varsayılanı hayvan-şiddeti thumbnail'larını bloklayıp BOŞ dönüyordu → gemma'ya
# ücretli fallback (ölçüldü: 42 vision'ın ~10'u). BLOCK_NONE ile hepsi ücretsiz Google'da kalır.
_SAFETY_OFF = [
    {"category": c, "threshold": "BLOCK_NONE"} for c in (
        "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
]


class GoogleStudioError(Exception):
    """google_studio HTTP/istek hatası (status + gövde taşır)."""

    def __init__(self, message: str, *, status: int | None = None,
                 body: dict | None = None, is_timeout: bool = False):
        super().__init__(message)
        self.status = status
        self.body = body
        self.is_timeout = is_timeout


class GoogleStudioExhausted(Exception):
    """Havuzda kurtarılabilir anahtar kalmadı → çağıran fallback etmeli."""


# ── PT tarih + gün sıfırlama ─────────────────────────────────────────────────
def _pt_date_string(now_s: float) -> str:
    dt = datetime.fromtimestamp(now_s, tz=timezone.utc) + timedelta(hours=_PT_OFFSET_H)
    return dt.strftime("%Y-%m-%d")


def _maybe_reset_day(state: dict, *, now: float) -> bool:
    """PT günü değiştiyse günlük sayaçları sıfırla + gün-tükenmişleri dirilt."""
    today = _pt_date_string(now)
    if state.get("ptDate") != today:
        state["ptDate"] = today
        for e in state.get("usage", {}).values():
            e["dayCount"] = 0
            if e.get("status") == "daily-exhausted":
                e["status"] = "active"
        return True
    return False


# ── 429 sınıflandırma (faceless classify429 sadeleştirilmiş) ─────────────────
def _parse_retry_delay_ms(body: dict | None):
    """RetryInfo.retryDelay ('12s' / '4.5s') → ms; yoksa None (0 DEĞİL)."""
    for d in (((body or {}).get("error") or {}).get("details") or []):
        delay = d.get("retryDelay") or d.get("retry_delay")
        if isinstance(delay, str):
            m = re.match(r"^(\d+(?:\.\d+)?)s$", delay)
            if m:
                return round(float(m.group(1)) * 1000)
    return None


def _quota_violations(body: dict | None) -> list:
    out: list = []
    for d in (((body or {}).get("error") or {}).get("details") or []):
        out.extend(d.get("violations") or [])
    return out


def _classify_429(body: dict | None):
    """Döner: (cls, retry_ms). cls: 'daily' | 'rpm' | 'capacity'.

    daily    → PerDay quota → anahtar bugünlük bitti.
    rpm      → PerMinute quota → retryDelay kadar cooldown.
    capacity → detaysız gövde (violations yok) → paylaşılan servis reddi, anahtar
               sağlam; havuz-geneli kısa duraklama.
    """
    retry_ms = _parse_retry_delay_ms(body)
    violations = _quota_violations(body)
    if not violations:
        return "capacity", retry_ms
    for v in violations:
        ident = f"{v.get('quotaId', '')} {v.get('quotaMetric', '')}"
        if re.search(r"PerDay", ident, re.I):
            return "daily", retry_ms
        if re.search(r"PerMinute", ident, re.I):
            return "rpm", retry_ms
    # quotaId tanınmadı (Google yeniden adlandırdı) → nesirden çapraz-oku.
    try:
        raw = json.dumps(body)
    except (TypeError, ValueError):
        raw = ""
    if re.search(r"per.?day|\bdaily\b|\bRPD\b", raw, re.I):
        return "daily", retry_ms
    return "rpm", retry_ms


def _rpm_limit() -> int:
    return math.ceil(RPM * RPM_MARGIN)


# ── Havuz ────────────────────────────────────────────────────────────────────
class Pool:
    """Thread-safe rotasyonlu anahtar havuzu. Durum diske (state.json) yazılır."""

    def __init__(self, pool_dir, *, now=time.time, daily_cap: int = DAILY_CAP):
        self._dir = Path(pool_dir)
        self._now = now
        self._cap = daily_cap
        self._lock = threading.RLock()
        self._cursor = 0
        self._capacity_until = 0.0
        self._capacity_streak = 0
        self._banned_streak: dict = {}
        self._keys = self._load_keys()
        self._state = self._load_state()
        _maybe_reset_day(self._state, now=now())

    def _load_keys(self) -> list:
        raw = json.loads((self._dir / "google-keys.json").read_text(encoding="utf-8"))
        keys = raw.get("keys", raw) if isinstance(raw, dict) else raw
        return [k for k in keys if k and k.get("enabled") is not False]

    def _load_state(self) -> dict:
        f = self._dir / "state.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        return {"ptDate": "", "usage": {}, "banned": {},
                "stats": {"freeCalls": 0, "fallbackCalls": 0}}

    def _save(self):
        # Disk hatası ASLA üretimi düşürmez (best-effort; Windows EPERM/disk-full).
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / "state.json").write_text(json.dumps(self._state), encoding="utf-8")
        except OSError as e:
            log.warning(f"  [google-pool] state kaydedilemedi ({e}) — best-effort, devam")

    def _entry(self, key_id: str, model: str) -> dict:
        eid = f"{key_id}:{model}"
        u = self._state.setdefault("usage", {})
        if eid not in u:
            u[eid] = {"dayCount": 0, "status": "active", "cooldownUntil": 0,
                      "windowTs": [], "lastEvent": ""}
        return u[eid]

    def _banned(self, key_id: str) -> bool:
        return key_id in self._state.get("banned", {})

    def _eff_status(self, e: dict) -> str:
        if e["status"] == "rpm-cooldown" and self._now() >= e["cooldownUntil"]:
            e["status"] = "active"
            e["cooldownUntil"] = 0
        return e["status"]

    def _trim(self, e: dict):
        cut = self._now() - 60.0
        e["windowTs"] = [t for t in e.get("windowTs", []) if t > cut]

    def acquire(self, model: str):
        """En yakın uygun anahtarı verir (round-robin) ya da None (dolu/tükenmiş).

        Günlük sayaç BURADA artar: Google isteği sonuçtan bağımsız sayar
        (429/transient/boş-200 de kotayı yer — ölçülmüş).
        """
        with self._lock:
            _maybe_reset_day(self._state, now=self._now())
            if self._now() < self._capacity_until:
                return None
            keys, n, lim = self._keys, len(self._keys), _rpm_limit()
            for i in range(n):
                k = keys[(self._cursor + i) % n]
                if self._banned(k["id"]):
                    continue
                e = self._entry(k["id"], model)
                st = self._eff_status(e)
                if st in ("daily-exhausted", "rpm-cooldown"):
                    continue
                if e["dayCount"] >= self._cap:
                    e["status"] = "daily-exhausted"
                    e["lastEvent"] = "cap"
                    continue
                self._trim(e)
                if len(e["windowTs"]) >= lim:
                    continue
                e["windowTs"].append(self._now())
                e["dayCount"] += 1
                self._cursor = (self._cursor + i + 1) % n
                self._save()
                return {"keyId": k["id"], "key": k["key"]}
            return None

    def next_rpm_slot_s(self, model: str):
        """Sonraki slotun kaç sn sonra doğacağı. 0=şimdi boş, None=kurtarılamaz."""
        with self._lock:
            _maybe_reset_day(self._state, now=self._now())
            lim, best = _rpm_limit(), None
            for k in self._keys:
                if self._banned(k["id"]):
                    continue
                e = self._entry(k["id"], model)
                st = self._eff_status(e)
                if st == "daily-exhausted" or e["dayCount"] >= self._cap:
                    continue
                if st == "rpm-cooldown":
                    w = max(0.0, e["cooldownUntil"] - self._now())
                    best = w if best is None else min(best, w)
                    continue
                self._trim(e)
                if len(e["windowTs"]) < lim:
                    return 0.0
                w = max(0.0, min(e["windowTs"]) + 60.0 - self._now())
                best = w if best is None else min(best, w)
            if best is None:
                return None
            return max(best, max(0.0, self._capacity_until - self._now()))

    def report_success(self, key_id: str, model: str):
        with self._lock:
            _maybe_reset_day(self._state, now=self._now())
            e = self._entry(key_id, model)
            e["lastEvent"] = "ok"
            s = self._state.setdefault("stats", {})
            s["freeCalls"] = s.get("freeCalls", 0) + 1
            self._capacity_streak = 0
            self._banned_streak.pop(key_id, None)
            self._save()

    def report_429(self, key_id: str, model: str, body):
        with self._lock:
            _maybe_reset_day(self._state, now=self._now())
            e = self._entry(key_id, model)
            cls, retry_ms = _classify_429(body)
            if cls == "capacity":
                # Anahtara DOKUNMA: paylaşılan kapasite reddi anahtarı bozmaz.
                self._capacity_streak += 1
                pause = min(CAPACITY_PAUSE_BASE_S * max(1, self._capacity_streak),
                            CAPACITY_PAUSE_MAX_S)
                self._capacity_until = self._now() + pause
                e["lastEvent"] = "429 kapasite"
                self._save()
                return
            if cls == "daily":
                e["status"] = "daily-exhausted"
                e["cooldownUntil"] = 0   # gün-ölüsüne cooldown YOK (retryDelay çöp)
                e["lastEvent"] = "429 RPD"
            elif e["status"] != "daily-exhausted":   # gün-ölüsünü DİRİLTME (yarış)
                e["status"] = "rpm-cooldown"
                cd = (retry_ms / 1000.0) if retry_ms is not None else RPM_FALLBACK_COOLDOWN_S
                e["cooldownUntil"] = self._now() + cd
                e["lastEvent"] = "429 RPM"
            self._banned_streak.pop(key_id, None)
            self._save()

    def report_transient(self, key_id: str, model: str):
        with self._lock:
            e = self._entry(key_id, model)
            if e["status"] != "daily-exhausted":
                e["status"] = "rpm-cooldown"
                e["cooldownUntil"] = self._now() + 60.0
                e["lastEvent"] = "transient"
            self._save()

    def report_auth_error(self, key_id: str, status: int):
        with self._lock:
            self._banned_streak[key_id] = self._banned_streak.get(key_id, 0) + 1
            if self._banned_streak[key_id] >= 2:
                self._state.setdefault("banned", {})[key_id] = {
                    "since": self._now(), "reason": f"{status} x{self._banned_streak[key_id]}"}
            self._save()


# ── Modül-düzeyi havuz + HTTP + generate ─────────────────────────────────────
_POOL: Pool | None = None
_POOL_DIR = Path("data/google_pool")

# Global eşzamanlılık tavanı (bkz. MAX_CONCURRENCY notu). BoundedSemaphore ile üretim
# genelinde aynı anda çağrı sayısını sınırla. _SEM_LIMIT yeniden kurmada karşılaştırma için.
_SEM_LIMIT = MAX_CONCURRENCY
_SEM = threading.BoundedSemaphore(MAX_CONCURRENCY)
_SEM_LOCK = threading.Lock()


_VARSAYILAN_POOL_DIR = _POOL_DIR


def set_pool_dir(path):
    """Havuz dizinini ayarla (web/pipeline başlangıcında; Electron'da data taşınır).

    `None` → varsayılana dön (testlerin küresel durumu geri alması için).
    """
    global _POOL, _POOL_DIR
    _POOL_DIR = _VARSAYILAN_POOL_DIR if path is None else Path(path)
    _POOL = None   # sonraki _get_pool yeniden kurar


def set_max_concurrency(n: int):
    """Global eşzamanlılık tavanını ayarla (başlangıçta, çağrılar başlamadan önce).

    settings.google_studio.max_concurrency ile beslenir. n<1 → 1'e sıkışır. Yalnız
    başlangıçta çağrılmalı (uçuşta değişim eski semaphore release'lerini bozabilir)."""
    global _SEM, _SEM_LIMIT
    n = max(1, int(n))
    with _SEM_LOCK:
        if n != _SEM_LIMIT:
            _SEM = threading.BoundedSemaphore(n)
            _SEM_LIMIT = n


def _get_sem() -> threading.BoundedSemaphore:
    return _SEM


def _get_pool() -> Pool:
    global _POOL
    if _POOL is None:
        _POOL = Pool(_POOL_DIR)
    return _POOL


def _http_generate(api_key: str, model: str, prompt: str, *,
                   image_path=None, timeout_s: int = 90, max_tokens: int = 1024) -> str:
    """Tek anahtarla generateContent çağrısı. Metin döner ya da GoogleStudioError."""
    parts = [{"text": prompt}]
    if image_path is not None:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens},
            "safetySettings": _SAFETY_OFF}
    # x-goog-api-key: hem AIza... hem AQ.... formatında çalışır (Google önerilen yol).
    try:
        r = requests.post(_ENDPOINT.format(model=model), json=body,
                          headers={"Content-Type": "application/json",
                                   "x-goog-api-key": api_key}, timeout=timeout_s)
    except requests.Timeout as e:
        raise GoogleStudioError("timeout", is_timeout=True) from e
    except requests.RequestException as e:
        raise GoogleStudioError(str(e)) from e
    if r.status_code != 200:
        try:
            eb = r.json()
        except ValueError:
            eb = None
        raise GoogleStudioError(f"HTTP {r.status_code}", status=r.status_code, body=eb)
    data = r.json()
    cps = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    texts = [p.get("text", "") for p in cps if not p.get("thought")]
    return texts[-1] if texts else ""


def generate(prompt: str, *, model: str, image_path=None, timeout_s: int = 90,
             max_tokens: int = 1024, wait_for_slot_s: float = WAIT_FOR_SLOT_S) -> str:
    """Vision çağrısı: havuzdan anahtar al, HTTP yap, 429/transient'te başka anahtara dön.

    Kurtarılamazsa (hepsi tükenmiş/banlı/dolu ya da boş yanıt) ``GoogleStudioExhausted``
    → çağıran OpenRouter gemma'ya düşer.

    Global eşzamanlılık tavanı (``_SEM``) burst kapasite-reddini engeller: çağıran havuz
    kaç thread açarsa açsın aynı anda en çok ``MAX_CONCURRENCY`` çağrı Google'a gider.
    """
    pool = _get_pool()
    deadline = time.time() + wait_for_slot_s
    transient = 0
    reason = "no-slot"   # neden fallback: throttle mı gerçek tükenme mi (yanıltıcı 'Exhausted' netleşsin)
    while True:
        key = pool.acquire(model)
        if key is not None:
            try:
                # Semaphore YALNIZ HTTP çağrısını sarar → aynı anda en çok MAX_CONCURRENCY
                # istek Google'a gider. Bekleme/uyku semaphore DIŞINDA (bir throttle'a takılan
                # çağrı slotu tıkamaz — head-of-line blocking yok; ÖLÇÜLDÜ: slot boyunca tutmak
                # 4 mahkûm çağrının tüm slotları 40s tıkamasına yol açıyordu).
                with _get_sem():
                    text = _http_generate(key["key"], model, prompt, image_path=image_path,
                                          timeout_s=timeout_s, max_tokens=max_tokens)
            except GoogleStudioError as err:
                if err.status == 429:
                    pool.report_429(key["keyId"], model, err.body)
                    # capacity/rpm 429 sonrası deadline'a kadar SABIRLA — hemen pes edip
                    # gemma'ya düşme (bkz. MAX_CONCURRENCY notu). Slot yoksa aşağıda beklenir.
                    reason = "throttle-429"
                    if time.time() >= deadline:
                        break
                    continue
                if err.status in (401, 403):
                    pool.report_auth_error(key["keyId"], err.status)
                    continue
                if err.is_timeout or (err.status and 500 <= err.status < 600):
                    pool.report_transient(key["keyId"], model)
                    transient += 1
                    reason = "transient"
                    if transient >= MAX_TRANSIENT_ATTEMPTS or time.time() >= deadline:
                        break
                    continue
                raise   # non-retryable → yukarı (fallback)
            pool.report_success(key["keyId"], model)
            if text and text.strip():
                return text
            reason = "empty-response"   # boş yanıt (güvenlik bloğu / MAX_TOKENS) → fallback
            break
        slot = pool.next_rpm_slot_s(model)
        if slot is None:
            reason = "all-keys-exhausted"   # GERÇEK tükenme: hepsi gün-tükenmiş/banlı
            break
        if (time.time() + slot) > deadline:
            reason = "throttle-deadline"     # slot var ama deadline'ı aşıyor (throttle/RPM dalgası)
            break
        time.sleep(max(slot, CAPACITY_PAUSE_BASE_S))   # slot=0 olsa bile Google'ı hemen dövme
    raise GoogleStudioExhausted(reason)


def pool_durumu(pool_dir=None) -> dict:
    """Havuzun panelde gösterilecek özeti — anahtar/kota/ban sayıları.

    Havuz 38 anahtarla çalışıyordu ama ayarlar ekranında HİÇ görünmüyordu.
    Tükendiğinde sistem sessizce OpenRouter'a düşüyor ve kullanıcı bunu
    faturada görüyor; sayılar görünürse önceden anlaşılır.

    Hiçbir hata YÜKSELTMEZ: ayarlar sayfası bozuk bir state.json yüzünden
    açılmamalı.
    """
    d = Path(pool_dir) if pool_dir is not None else _POOL_DIR
    out = {"var": False, "anahtar": 0, "etkin": 0, "bugun": 0,
           "gunluk_tavan": 0, "tukenen": 0, "banli": 0, "dizin": str(d),
           "hata": ""}
    try:
        ham = json.loads((d / "google-keys.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        out["hata"] = f"anahtar dosyası okunamadı: {e}"
        return out

    keys = ham.get("keys", ham) if isinstance(ham, dict) else ham
    keys = [k for k in (keys or []) if isinstance(k, dict)]
    out["var"] = True
    out["anahtar"] = len(keys)
    out["etkin"] = sum(1 for k in keys if k.get("enabled") is not False)
    out["gunluk_tavan"] = out["etkin"] * DAILY_CAP

    try:
        state = json.loads((d / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out          # state yoksa/bozuksa sayılar sıfır kalır, sayfa açılır

    kullanim = state.get("usage") or {}
    out["bugun"] = sum(int(v.get("dayCount") or 0)
                       for v in kullanim.values() if isinstance(v, dict))
    out["tukenen"] = sum(1 for v in kullanim.values()
                         if isinstance(v, dict) and v.get("status") == "exhausted")
    out["banli"] = len(state.get("banned") or {})
    out["gun"] = state.get("ptDate", "")
    return out
