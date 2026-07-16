# Hibrit AI Backend — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Metin çağrıları Claude CLI (Sonnet 5 / DNA Opus), vision Google AI Studio
rotasyonlu havuz (gemini-3.1-flash-lite); CLI yoksa → OpenRouter Sonnet 5, havuz
tükenirse → OpenRouter gemma-4-26b-a4b-it.

**Architecture:** `ai_backend: "hybrid"` modu `resolve_ai_call`'a eklenir; yeni
`google_studio.py` faceless-2'nin key-pool.js'ini Python'a port eder (500/gün/key,
PT reset, 15 RPM, 429 sınıfları); fallback zinciri `claude_cli._invoke_raw` içinde
merkezî registry ile — 36+ çağrı noktası DEĞİŞMEZ.

**Tech Stack:** Python 3.14, requests, pydantic, pytest, threading.

---

## Dosya Yapısı

- **Create:** `src/short_bot/google_studio.py` — havuz + HTTP + generate()
- **Create:** `tests/test_google_studio.py`
- **Modify:** `src/short_bot/claude_cli.py` — `_invoke_raw` → `_invoke_primary` + fallback registry + google_studio dalı
- **Modify:** `src/short_bot/config.py` — `Settings.google_studio` alanı + `resolve_ai_call` hybrid dalı
- **Modify:** `config/settings.yaml` — `ai_backend: hybrid` + google_studio bloğu + fallback modelleri
- **Modify:** `src/short_bot/web/__init__.py` — `set_pool_dir` bağla
- **Test:** `tests/test_hybrid_routing.py` (config + dispatch)
- **Setup (git-dışı):** `data/google_pool/google-keys.json` — 38 anahtar kopyalanır

---

## Task 1: google_studio — PT tarih/reset yardımcıları

**Files:** Create `src/short_bot/google_studio.py`, Test `tests/test_google_studio.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_google_studio.py
from short_bot import google_studio as GS

def test_pt_date_string_ve_reset():
    # 2026-07-16 08:00 UTC = 2026-07-16 01:00 PT (aynı gün)
    assert GS._pt_date_string(1768550400.0) == "2026-07-16"
    # PT gün dönümü: state ptDate eskiyse used sıfırlanır
    st = {"ptDate": "2026-07-15", "usage": {"k:m": {"dayCount": 40, "status": "daily-exhausted",
          "cooldownUntil": 0, "windowTs": [], "lastEvent": ""}}, "banned": {}, "stats": {}}
    GS._maybe_reset_day(st, now=1768550400.0)
    assert st["ptDate"] == "2026-07-16"
    assert st["usage"]["k:m"]["dayCount"] == 0
    assert st["usage"]["k:m"]["status"] == "active"   # gün-tükenmişi diriltir
```

- [ ] **Step 2: Run → FAIL** `python -m pytest tests/test_google_studio.py::test_pt_date_string_ve_reset -v`

- [ ] **Step 3: Implement**

```python
"""Google AI Studio rotasyonlu anahtar havuzu — vision için (faceless-2 portu).

Durum makinesi (key:model başına): active | rpm-cooldown | daily-exhausted;
anahtar başına: banned. Kota Google'da PerProjectPerModel — 500/gün/key/model
(canlı 429 ölçümü), PT-geceyarısı sıfırlar, 15 RPM. Tükenince GoogleStudioExhausted
→ çağıran OpenRouter gemma'ya düşer.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

DAILY_CAP = 500          # key:model başına bedava/gün (ölçülmüş)
RPM = 15                 # Google bedava PerMinute
RPM_MARGIN = 0.8         # güvenli pace payı
WAIT_FOR_SLOT_S = 20.0   # RPM-dolu havuzda slot için azami bekleme
RPM_FALLBACK_COOLDOWN_S = 60.0
MAX_TRANSIENT_ATTEMPTS = 3
CAPACITY_PAUSE_BASE_S = 0.25
CAPACITY_PAUSE_MAX_S = 2.0

# PT (America/Los_Angeles): yaz UTC-7 (PDT). Basit sabit ofset — kota penceresi
# gün-kaba; DST geçiş anındaki ~1 saatlik kayma kota için önemsiz (faceless Intl
# kullanıyordu; burada stdlib-only kalıp bağımlılık eklemiyoruz).
_PT_OFFSET_H = -7


def _pt_date_string(now_s: float) -> str:
    dt = datetime.fromtimestamp(now_s, tz=timezone.utc) + timedelta(hours=_PT_OFFSET_H)
    return dt.strftime("%Y-%m-%d")


def _maybe_reset_day(state: dict, *, now: float) -> bool:
    today = _pt_date_string(now)
    if state.get("ptDate") != today:
        state["ptDate"] = today
        for e in state.get("usage", {}).values():
            e["dayCount"] = 0
            if e.get("status") == "daily-exhausted":
                e["status"] = "active"
        return True
    return False


class GoogleStudioError(Exception):
    """google_studio backend HTTP/istek hatası (status taşır)."""
    def __init__(self, message: str, *, status: int | None = None,
                 body: dict | None = None, is_timeout: bool = False):
        super().__init__(message)
        self.status = status
        self.body = body
        self.is_timeout = is_timeout


class GoogleStudioExhausted(Exception):
    """Havuzda kurtarılabilir anahtar kalmadı → çağıran fallback etmeli."""
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** `git add -f src/short_bot/google_studio.py tests/test_google_studio.py && git commit -m "feat(reel): google_studio PT-reset yardimcilari + hata tipleri"`

---

## Task 2: 429 sınıflandırma (classify429 portu)

**Files:** Modify `src/short_bot/google_studio.py`, Test `tests/test_google_studio.py`

- [ ] **Step 1: Failing test**

```python
def test_classify_429_gunluk_dakika_kapasite():
    daily = {"error": {"message": "Quota exceeded", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
    assert GS._classify_429(daily)[0] == "daily"
    rpm = {"error": {"message": "rate", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
        {"@type": "...RetryInfo", "retryDelay": "12s"}]}}
    cls, retry_ms = GS._classify_429(rpm)
    assert cls == "rpm" and retry_ms == 12000
    capacity = {"error": {"code": 429, "message": "Resource has been exhausted",
                          "status": "RESOURCE_EXHAUSTED"}}
    assert GS._classify_429(capacity)[0] == "capacity"
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

```python
def _parse_retry_delay_ms(body: dict | None):
    for d in (((body or {}).get("error") or {}).get("details") or []):
        delay = d.get("retryDelay") or d.get("retry_delay")
        if isinstance(delay, str):
            m = re.match(r"^(\d+(?:\.\d+)?)s$", delay)
            if m:
                return round(float(m.group(1)) * 1000)
    return None


def _quota_violations(body: dict | None):
    out = []
    for d in (((body or {}).get("error") or {}).get("details") or []):
        out.extend(d.get("violations") or [])
    return out


def _classify_429(body: dict | None):
    """Döner: (cls, retry_ms). cls: 'daily' | 'rpm' | 'capacity'."""
    retry_ms = _parse_retry_delay_ms(body)
    violations = _quota_violations(body)
    if not violations:
        return "capacity", retry_ms          # detaysız → paylaşılan kapasite reddi
    for v in violations:
        ident = f"{v.get('quotaId', '')} {v.get('quotaMetric', '')}"
        if re.search(r"PerDay", ident, re.I):
            return "daily", retry_ms
        if re.search(r"PerMinute", ident, re.I):
            return "rpm", retry_ms
    # quotaId tanınmadı: nesir/limit çapraz-oku (faceless FIX-3 sadeleştirilmiş)
    raw = json.dumps(body) if body else ""
    if re.search(r"per.?day|\bdaily\b|\bRPD\b", raw, re.I):
        return "daily", retry_ms
    return "rpm", retry_ms
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `git add -f && git commit -m "feat(reel): google_studio 429 siniflandirma (daily/rpm/capacity)"`

---

## Task 3: Pool sınıfı — acquire/rotation/RPM/reset

**Files:** Modify `src/short_bot/google_studio.py`, Test `tests/test_google_studio.py`

- [ ] **Step 1: Failing test**

```python
def _pool(tmp_path, keys=("k1", "k2"), now=1000.0, cap=3):
    (tmp_path / "google-keys.json").write_text(json.dumps(
        {"keys": [{"id": k, "key": f"AIza-{k}", "enabled": True} for k in keys]}))
    clock = {"t": now}
    p = GS.Pool(tmp_path, now=lambda: clock["t"], daily_cap=cap)
    return p, clock

def test_acquire_rotasyon_ve_gunluk_cap(tmp_path):
    p, clock = _pool(tmp_path, cap=2)
    got = [p.acquire("m")["keyId"] for _ in range(4)]
    assert got == ["k1", "k2", "k1", "k2"]     # round-robin
    assert p.acquire("m") is None              # ikisi de cap=2 → tükendi
    assert p.next_rpm_slot_s("m") is None       # kurtarılamaz

def test_rpm_penceresi_slot_bekletir(tmp_path):
    p, clock = _pool(tmp_path, keys=("k1",), cap=100)
    lim = -(-int(GS.RPM * GS.RPM_MARGIN))       # ceil
    for _ in range(lim):
        assert p.acquire("m") is not None
    assert p.acquire("m") is None              # pencere doldu
    w = p.next_rpm_slot_s("m")
    assert 0 < w <= 60

def test_pt_reset_gunluk_capi_temizler(tmp_path):
    p, clock = _pool(tmp_path, keys=("k1",), cap=1)
    assert p.acquire("m") is not None
    assert p.acquire("m") is None              # cap=1 doldu
    clock["t"] += 86400                        # +1 gün → PT tarihi değişir
    assert p.acquire("m") is not None          # reset
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** (Pool sınıfı; not: `windowTs` diske yazılır ama trim edilir)

```python
import math

def _rpm_limit() -> int:
    return math.ceil(RPM * RPM_MARGIN)


class Pool:
    def __init__(self, pool_dir: Path, *, now=time.time, daily_cap: int = DAILY_CAP):
        self._dir = Path(pool_dir)
        self._now = now
        self._cap = daily_cap
        self._lock = threading.RLock()
        self._cursor = 0
        self._capacity_until = 0.0
        self._capacity_streak = 0
        self._keys = self._load_keys()
        self._state = self._load_state()
        _maybe_reset_day(self._state, now=now())

    def _load_keys(self):
        raw = json.loads((self._dir / "google-keys.json").read_text(encoding="utf-8"))
        keys = raw.get("keys", raw) if isinstance(raw, dict) else raw
        return [k for k in keys if k and k.get("enabled") is not False]

    def _load_state(self):
        f = self._dir / "state.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        return {"ptDate": "", "usage": {}, "banned": {}, "stats": {"freeCalls": 0, "fallbackCalls": 0}}

    def _save(self):
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / "state.json").write_text(
                json.dumps(self._state), encoding="utf-8")
        except OSError as e:      # disk hatası ASLA üretimi düşürmez (best-effort)
            log.warning(f"  [google-pool] state kaydedilemedi: {e}")

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
            e["status"] = "active"; e["cooldownUntil"] = 0
        return e["status"]

    def _trim(self, e: dict):
        cut = self._now() - 60.0
        e["windowTs"] = [t for t in e.get("windowTs", []) if t > cut]

    def acquire(self, model: str):
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
                    e["status"] = "daily-exhausted"; e["lastEvent"] = "cap"; continue
                self._trim(e)
                if len(e["windowTs"]) >= lim:
                    continue
                e["windowTs"].append(self._now())
                e["dayCount"] += 1          # istek başına say (Google isteği sayar)
                self._cursor = (self._cursor + i + 1) % n
                self._save()
                return {"keyId": k["id"], "key": k["key"]}
            return None

    def next_rpm_slot_s(self, model: str):
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
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `git add -f && git commit -m "feat(reel): google_studio Pool acquire/rotasyon/RPM/PT-reset"`

---

## Task 4: report_* (429/success/transient/auth)

**Files:** Modify `src/short_bot/google_studio.py`, Test `tests/test_google_studio.py`

- [ ] **Step 1: Failing test**

```python
def test_report_daily_gun_boyu_kapatir(tmp_path):
    p, clock = _pool(tmp_path, keys=("k1",), cap=100)
    p.acquire("m")
    p.report_429("k1", "m", {"error": {"details": [
        {"violations": [{"quotaId": "X-PerDay-FreeTier"}]}]}})
    assert p.acquire("m") is None              # gün-tükendi
    assert p.next_rpm_slot_s("m") is None

def test_report_rpm_cooldown_ve_kurtulur(tmp_path):
    p, clock = _pool(tmp_path, keys=("k1",), cap=100)
    p.acquire("m")
    p.report_429("k1", "m", {"error": {"details": [
        {"violations": [{"quotaId": "X-PerMinute-FreeTier"}]},
        {"retryDelay": "5s"}]}})
    assert p.acquire("m") is None
    assert abs(p.next_rpm_slot_s("m") - 5.0) < 0.6
    clock["t"] += 6
    assert p.acquire("m") is not None          # cooldown bitti

def test_report_auth_iki_kez_banlar(tmp_path):
    p, clock = _pool(tmp_path, keys=("k1", "k2"), cap=100)
    p.report_auth_error("k1", 403)
    assert p.acquire("m")["keyId"] == "k1"     # ilk hata ban DEĞİL
    p.report_auth_error("k1", 403)
    assert all(p.acquire("m")["keyId"] == "k2" for _ in range(3))  # k1 banlı
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**

```python
    def report_success(self, key_id: str, model: str):
        with self._lock:
            _maybe_reset_day(self._state, now=self._now())
            e = self._entry(key_id, model); e["lastEvent"] = "ok"
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
                self._capacity_streak += 1
                pause = min(CAPACITY_PAUSE_BASE_S * max(1, self._capacity_streak),
                            CAPACITY_PAUSE_MAX_S)
                self._capacity_until = self._now() + pause
                e["lastEvent"] = "429 kapasite"; self._save(); return
            if cls == "daily":
                e["status"] = "daily-exhausted"; e["cooldownUntil"] = 0
                e["lastEvent"] = "429 RPD"
            elif e["status"] != "daily-exhausted":
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
```

Ayrıca `__init__`'e `self._banned_streak: dict = {}` ekle.

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `git add -f && git commit -m "feat(reel): google_studio report_* durum gecisleri"`

---

## Task 5: HTTP çağrısı + generate() acquire-döngüsü

**Files:** Modify `src/short_bot/google_studio.py`, Test `tests/test_google_studio.py`

- [ ] **Step 1: Failing test** (HTTP enjekte edilir)

```python
def test_generate_basari_ve_sayac(tmp_path, monkeypatch):
    p, clock = _pool(tmp_path, keys=("k1",), cap=100)
    monkeypatch.setattr(GS, "_get_pool", lambda: p)
    calls = {}
    def fake_http(api_key, model, prompt, *, image_path, timeout_s, max_tokens):
        calls["key"] = api_key; return '{"ok": 1}'
    monkeypatch.setattr(GS, "_http_generate", fake_http)
    out = GS.generate("tarif et", model="m")
    assert out == '{"ok": 1}' and calls["key"] == "AIza-k1"
    assert p._state["usage"]["k1:m"]["lastEvent"] == "ok"

def test_generate_tukenince_exhausted(tmp_path, monkeypatch):
    p, clock = _pool(tmp_path, keys=("k1",), cap=0)   # kota sıfır
    monkeypatch.setattr(GS, "_get_pool", lambda: p)
    monkeypatch.setattr(GS, "_http_generate", lambda *a, **k: '{}')
    import pytest
    with pytest.raises(GS.GoogleStudioExhausted):
        GS.generate("x", model="m", wait_for_slot_s=0)

def test_generate_429_donup_gecerli_keye(tmp_path, monkeypatch):
    p, clock = _pool(tmp_path, keys=("k1", "k2"), cap=100)
    monkeypatch.setattr(GS, "_get_pool", lambda: p)
    seq = {"n": 0}
    def http(api_key, model, prompt, **k):
        seq["n"] += 1
        if api_key == "AIza-k1":
            raise GS.GoogleStudioError("rate", status=429, body={"error": {"details": [
                {"violations": [{"quotaId": "X-PerMinute"}]}]}})
        return "OK"
    monkeypatch.setattr(GS, "_http_generate", http)
    assert GS.generate("x", model="m") == "OK"   # k1 429 → k2 başarı
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**

```python
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_POOL = None
_POOL_DIR = Path("data/google_pool")


def set_pool_dir(path):
    global _POOL, _POOL_DIR
    _POOL_DIR = Path(path); _POOL = None    # sonraki generate yeniden kurar


def _get_pool() -> "Pool":
    global _POOL
    if _POOL is None:
        _POOL = Pool(_POOL_DIR)
    return _POOL


def _http_generate(api_key: str, model: str, prompt: str, *,
                   image_path=None, timeout_s: int = 90, max_tokens: int = 1024) -> str:
    parts = [{"text": prompt}]
    if image_path is not None:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens}}
    # x-goog-api-key: hem AIza... hem AQ.... formatinda calisir (Google onerilen).
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
    cps = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    texts = [p.get("text", "") for p in cps if not p.get("thought")]
    return texts[-1] if texts else ""


def generate(prompt: str, *, model: str, image_path=None, timeout_s: int = 90,
             max_tokens: int = 1024, wait_for_slot_s: float = WAIT_FOR_SLOT_S) -> str:
    """Vision çağrısı: havuzdan anahtar al, HTTP yap, 429/transient'te dön.
    Kurtarılamazsa GoogleStudioExhausted (çağıran OpenRouter'a düşer)."""
    pool = _get_pool()
    deadline = time.time() + wait_for_slot_s
    transient = 0
    while True:
        key = pool.acquire(model)
        if key is not None:
            try:
                text = _http_generate(key["key"], model, prompt, image_path=image_path,
                                      timeout_s=timeout_s, max_tokens=max_tokens)
            except GoogleStudioError as err:
                if err.status == 429:
                    pool.report_429(key["keyId"], model, err.body); continue
                if err.status in (401, 403):
                    pool.report_auth_error(key["keyId"], err.status); continue
                if err.is_timeout or (err.status and 500 <= err.status < 600):
                    pool.report_transient(key["keyId"], model)
                    transient += 1
                    if transient >= MAX_TRANSIENT_ATTEMPTS or time.time() >= deadline:
                        break
                    continue
                raise                       # non-retryable → fallback
            pool.report_success(key["keyId"], model)
            if text and text.strip():
                return text
            break                           # boş yanıt (güvenlik/MAX_TOKENS) → fallback
        slot = pool.next_rpm_slot_s(model)
        if slot is None or slot <= 0 or (time.time() + slot) > deadline:
            break
        time.sleep(slot)
    raise GoogleStudioExhausted()
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `git add -f && git commit -m "feat(reel): google_studio generate() HTTP + acquire dongusu"`

---

## Task 6: claude_cli fallback registry + google_studio dalı

**Files:** Modify `src/short_bot/claude_cli.py`, Test `tests/test_hybrid_routing.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_hybrid_routing.py
import short_bot.claude_cli as CC

def test_fallback_cli_yoksa_openrouter(monkeypatch):
    CC.clear_fallbacks()
    CC.register_fallback("claude_cli", "sonnet", "openrouter",
                         "anthropic/claude-sonnet-5", "or-key")
    seen = {}
    def fake_primary(prompt, *, backend, model, claude_path, api_key, timeout_s, image_path=None):
        if backend == "claude_cli":
            raise FileNotFoundError("claude yok")
        seen.update(backend=backend, model=model, api_key=api_key)
        return "OR CEVAP"
    monkeypatch.setattr(CC, "_invoke_primary", fake_primary)
    out = CC._invoke_raw("selam", backend="claude_cli", model="sonnet",
                         claude_path="claude", api_key=None, timeout_s=10)
    assert out == "OR CEVAP"
    assert seen == {"backend": "openrouter", "model": "anthropic/claude-sonnet-5", "api_key": "or-key"}

def test_fallback_kayitsizken_hata_gecer(monkeypatch):
    CC.clear_fallbacks()
    def fake_primary(prompt, **k):
        raise FileNotFoundError("claude yok")
    monkeypatch.setattr(CC, "_invoke_primary", fake_primary)
    import pytest
    with pytest.raises(FileNotFoundError):    # kayıt yok → davranış birebir
        CC._invoke_raw("x", backend="claude_cli", model="sonnet",
                       claude_path="claude", api_key=None, timeout_s=10)

def test_google_studio_exhausted_fallback(monkeypatch):
    CC.clear_fallbacks()
    CC.register_fallback("google_studio", "gemini-3.1-flash-lite", "openrouter",
                         "google/gemma-4-26b-a4b-it", "or-key")
    import short_bot.google_studio as GS
    def gs_gen(prompt, **k):
        raise GS.GoogleStudioExhausted()
    monkeypatch.setattr(GS, "generate", gs_gen)
    def or_primary(prompt, *, backend, model, **k):
        return f"OR:{model}" if backend == "openrouter" else None
    # google_studio dalını da gerçek _invoke_primary çağırsın; sadece OR'ı yala
    monkeypatch.setattr("short_bot.openrouter_client.complete",
                        lambda prompt, **k: f"OR:{k['model']}")
    out = CC._invoke_raw("tarif", backend="google_studio", model="gemini-3.1-flash-lite",
                         claude_path="claude", api_key=None, timeout_s=10)
    assert out == "OR:google/gemma-4-26b-a4b-it"
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — mevcut `_invoke_raw` gövdesini `_invoke_primary`'ye taşı, `google_studio` dalı ekle, `_invoke_raw`'ı fallback sarmalayıcı yap:

```python
import threading as _threading
_FALLBACKS: dict = {}
_FALLBACKS_LOCK = _threading.Lock()


def register_fallback(primary_backend, primary_model, fb_backend, fb_model, fb_api_key):
    with _FALLBACKS_LOCK:
        _FALLBACKS[(primary_backend, primary_model)] = (fb_backend, fb_model, fb_api_key)


def clear_fallbacks():
    with _FALLBACKS_LOCK:
        _FALLBACKS.clear()


def _invoke_primary(prompt, *, backend, model, claude_path, api_key, timeout_s, image_path=None):
    """Tek-atış ham çıktı (fallback YOK). Eski _invoke_raw gövdesi + google_studio dalı."""
    if backend == "google_studio":
        from short_bot import google_studio
        return google_studio.generate(prompt, model=model, image_path=image_path,
                                      timeout_s=timeout_s)
    if backend == "openrouter":
        from short_bot import openrouter_client
        return openrouter_client.complete(prompt, model=model, api_key=api_key,
                                          timeout_s=timeout_s, image_path=image_path)
    # ... mevcut claude_cli gövdesi birebir ...


def _invoke_raw(prompt, *, backend, model, claude_path, api_key, timeout_s, image_path=None):
    """Birincil backend + kayıtlı fallback (tek deneme). Kayıt yoksa davranış birebir."""
    try:
        return _invoke_primary(prompt, backend=backend, model=model, claude_path=claude_path,
                               api_key=api_key, timeout_s=timeout_s, image_path=image_path)
    except Exception as e:
        from short_bot.google_studio import GoogleStudioExhausted
        fb = _FALLBACKS.get((backend, model))
        # Yalnız düşme-yolu olan gerçek başarısızlıklarda fallback; kayıt yoksa yükselt.
        if fb is None:
            raise
        fb_backend, fb_model, fb_key = fb
        log.warning(f"fallback: {backend}/{model} -> {fb_backend}/{fb_model} ({type(e).__name__})")
        return _invoke_primary(prompt, backend=fb_backend, model=fb_model, claude_path=claude_path,
                               api_key=fb_key, timeout_s=timeout_s, image_path=image_path)
```

**Not:** `run_json`'ın `except FileNotFoundError` dalı korunur (kayıtsız CLI modu için).
`_invoke_raw` FileNotFoundError'ı kayıt varsa yutar (fallback), yoksa yükseltir → run_json yakalar.

- [ ] **Step 4: Run → PASS** (+ mevcut `python -m pytest tests/test_claude_cli.py -q` regresyon)
- [ ] **Step 5: Commit** `git add -f && git commit -m "feat(reel): claude_cli merkezi fallback registry + google_studio dispatch"`

---

## Task 7: config — Settings.google_studio + resolve_ai_call hybrid dalı

**Files:** Modify `src/short_bot/config.py`, Test `tests/test_hybrid_routing.py`

- [ ] **Step 1: Failing test**

```python
def test_resolve_hybrid_vision_ve_metin(tmp_path):
    import short_bot.claude_cli as CC
    from short_bot.config import resolve_ai_call, Settings
    CC.clear_fallbacks()
    s = Settings(ffmpeg_path="ffmpeg", claude_cli_path="claude", claude_models={
        "dna": "opus", "default": "sonnet", "script": "sonnet", "vision": "default"},
        ai_backend="hybrid",
        openrouter_models={"dna": "anthropic/claude-opus-4.8",
                           "default": "anthropic/claude-sonnet-5",
                           "vision": "google/gemma-4-26b-a4b-it"},
        google_studio={"vision_model": "gemini-3.1-flash-lite"})
    vis = resolve_ai_call(s, {"openrouter_api_key": "or"}, "vision")
    assert vis.backend == "google_studio" and vis.model == "gemini-3.1-flash-lite"
    assert CC._FALLBACKS[("google_studio", "gemini-3.1-flash-lite")] == (
        "openrouter", "google/gemma-4-26b-a4b-it", "or")
    txt = resolve_ai_call(s, {"openrouter_api_key": "or"}, "script")
    assert txt.backend == "claude_cli" and txt.model == "sonnet"
    assert CC._FALLBACKS[("claude_cli", "sonnet")] == (
        "openrouter", "anthropic/claude-sonnet-5", "or")
    dna = resolve_ai_call(s, {"openrouter_api_key": "or"}, "dna")
    assert dna.backend == "claude_cli" and dna.model == "opus"
```

Not: `Settings` alan sırasını gerçek dataclass'a göre düzelt (test yazarken kontrol et).

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**
  - `Settings`'e `google_studio: dict = field(default_factory=dict)` ekle
  - `load_settings`'e `google_studio=dict(data.get("google_studio", {}))` ekle
  - `resolve_ai_call`'a hybrid dalı (spec §1):

```python
    if settings.ai_backend == "hybrid":
        from short_bot import claude_cli
        or_key = secrets.get("openrouter_api_key", "") or None
        if role == "vision":
            gs_model = settings.google_studio.get("vision_model", "gemini-3.1-flash-lite")
            claude_cli.register_fallback("google_studio", gs_model, "openrouter",
                settings.openrouter_models.get("vision", "google/gemma-4-26b-a4b-it"), or_key)
            return AICall(backend="google_studio", model=gs_model, api_key=None,
                          claude_path=settings.claude_cli_path)
        cli_model = settings.claude_models.get(role, "sonnet")
        fb_model = (settings.openrouter_models.get(role)
                    or settings.openrouter_models.get("default", "anthropic/claude-sonnet-5"))
        claude_cli.register_fallback("claude_cli", cli_model, "openrouter", fb_model, or_key)
        return AICall(backend="claude_cli", model=cli_model, api_key=None,
                      claude_path=settings.claude_cli_path)
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `git add -f && git commit -m "feat(reel): config hybrid ai_backend + Settings.google_studio"`

---

## Task 8: settings.yaml + web pool-dir + anahtar göçü

**Files:** Modify `config/settings.yaml`, `src/short_bot/web/__init__.py`; Setup `data/google_pool/`

- [ ] **Step 1:** settings.yaml düzenle:

```yaml
claude_models:
  dna: opus
  default: sonnet
  script: sonnet
  vision: default
ai_backend: hybrid
openrouter_models:
  dna: anthropic/claude-opus-4.8
  default: anthropic/claude-sonnet-5
  script: anthropic/claude-sonnet-5
  vision: google/gemma-4-26b-a4b-it
google_studio:
  vision_model: gemini-3.1-flash-lite
```

- [ ] **Step 2:** web `create_app` sonuna (paths stash bloğu):

```python
    try:
        from short_bot import google_studio
        google_studio.set_pool_dir(Path(db_path).parent / "google_pool")
    except Exception:   # havuz opsiyonel; kurulamazsa vision fallback devrede
        pass
```

- [ ] **Step 3:** Anahtar göçü (git-DIŞI; data/ gitignore'da):

```bash
mkdir -p data/google_pool
cp "C:/Users/Hiko/AppData/Roaming/agbey/google-pool/google-keys.json" data/google_pool/google-keys.json
python -c "import json;d=json.load(open('data/google_pool/google-keys.json',encoding='utf-8'));print('anahtar:', len(d.get('keys',d)))"
```

- [ ] **Step 4: Doğrula** anahtarlar commit'e GİRMEZ: `git status --porcelain data/` boş/ignored.
- [ ] **Step 5: Commit** yalnız kod: `git add config/settings.yaml && git add -f src/short_bot/web/__init__.py && git commit -m "feat(reel): settings hybrid moda gecti + web havuz-dizini"`

---

## Task 9: Canlı doğrulama (smoke + üretim)

- [ ] **Step 1:** CLI-Sonnet tek atış: `python -c "from short_bot import claude_cli; print(claude_cli.run_text..." ` yoksa `run_json` ile küçük şema.
- [ ] **Step 2:** Google Studio vision tek describe: bir frame ile `google_studio.generate(...)` → JSON tarif döner.
- [ ] **Step 3:** Gerçek reel üretim koşusu (tek video) → log'da `backend=google_studio` vision izleri + CLI metin; frame montajıyla donma/uyum kontrolü (bu oturumun standardı).
- [ ] **Step 4:** MEMORY güncelle: hibrit backend aktif; anahtar havuzu data/google_pool.

---

## Self-Review (plan yazımı sonrası)

- Spec kapsamı: §1 resolve_ai_call→T7; §2 dispatch fallback→T6; §3 google_studio→T1-5;
  §4 settings→T8; fallback zincirleri→T6; anahtar göçü→T8. ✔ hepsi bir task'a bağlı.
- Placeholder yok; her kod adımı tam.
- Tip tutarlılığı: `Pool`, `generate`, `register_fallback`, `_invoke_primary`,
  `GoogleStudioExhausted` isimleri task'lar arası birebir aynı.
