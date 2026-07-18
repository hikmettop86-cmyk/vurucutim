"""Google AI Studio rotasyonlu havuz — vision backend (faceless-2 portu).

Havuz 38 anahtarı sırayla döndürür, key:model başına 500/gün sayar (PT-geceyarısı
sıfırlar), 15 RPM pace eder, 429'u daily/rpm/capacity olarak sınıflar. Tükenince
GoogleStudioExhausted → çağıran OpenRouter gemma'ya düşer.
"""
import json
import time

import pytest

from short_bot import google_studio as GS


# ── PT tarih + reset ─────────────────────────────────────────────────────────
def test_pt_date_string_ve_reset():
    # 1768550400 = 2026-01-16 08:00 UTC → PT (UTC-7) = 2026-01-16 01:00 (aynı gün)
    assert GS._pt_date_string(1768550400.0) == "2026-01-16"
    # Ofset sınırı: 2026-01-16 00:00 UTC → PT = 2026-01-15 17:00 → bir gün GERİ
    assert GS._pt_date_string(1768521600.0) == "2026-01-15"
    st = {"ptDate": "2026-01-15", "usage": {"k:m": {"dayCount": 40, "status": "daily-exhausted",
          "cooldownUntil": 0, "windowTs": [], "lastEvent": ""}}, "banned": {}, "stats": {}}
    changed = GS._maybe_reset_day(st, now=1768550400.0)
    assert changed is True
    assert st["ptDate"] == "2026-01-16"
    assert st["usage"]["k:m"]["dayCount"] == 0
    assert st["usage"]["k:m"]["status"] == "active"   # gün-tükenmişi diriltir


# ── 429 sınıflandırma ────────────────────────────────────────────────────────
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
    # Ondalık retryDelay (Google canlı gövdede gönderiyor)
    assert GS._parse_retry_delay_ms({"error": {"details": [{"retryDelay": "4.5s"}]}}) == 4500


# ── Pool: acquire / rotasyon / cap / RPM / reset ─────────────────────────────
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
    lim = -(-int(GS.RPM * GS.RPM_MARGIN))       # ceil(15*0.8)=12
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


# ── report_* durum geçişleri ─────────────────────────────────────────────────
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


def test_capacity_havuz_geneli_duraklatir(tmp_path):
    p, clock = _pool(tmp_path, keys=("k1", "k2"), cap=100)
    p.report_429("k1", "m", {"error": {"code": 429, "message": "Resource has been exhausted",
                                       "status": "RESOURCE_EXHAUSTED"}})
    assert p.acquire("m") is None              # havuz-geneli kısa duraklama (anahtar sağlam)
    clock["t"] += 3
    assert p.acquire("m") is not None


def test_state_diske_yazilir_ve_okunur(tmp_path):
    p, clock = _pool(tmp_path, keys=("k1",), cap=100)
    p.acquire("m")
    assert (tmp_path / "state.json").exists()
    p2 = GS.Pool(tmp_path, now=lambda: clock["t"], daily_cap=100)
    assert p2._state["usage"]["k1:m"]["dayCount"] == 1   # sayaç kalıcı


# ── generate() HTTP + acquire döngüsü ────────────────────────────────────────
def test_generate_basari_ve_sayac(tmp_path, monkeypatch):
    p, clock = _pool(tmp_path, keys=("k1",), cap=100)
    monkeypatch.setattr(GS, "_get_pool", lambda: p)
    calls = {}

    def fake_http(api_key, model, prompt, *, image_path, timeout_s, max_tokens):
        calls["key"] = api_key
        return '{"ok": 1}'

    monkeypatch.setattr(GS, "_http_generate", fake_http)
    out = GS.generate("tarif et", model="m")
    assert out == '{"ok": 1}' and calls["key"] == "AIza-k1"
    assert p._state["usage"]["k1:m"]["lastEvent"] == "ok"


def test_generate_tukenince_exhausted(tmp_path, monkeypatch):
    p, clock = _pool(tmp_path, keys=("k1",), cap=0)   # kota sıfır
    monkeypatch.setattr(GS, "_get_pool", lambda: p)
    monkeypatch.setattr(GS, "_http_generate", lambda *a, **k: '{}')
    with pytest.raises(GS.GoogleStudioExhausted) as exc:
        GS.generate("x", model="m", wait_for_slot_s=0)
    assert "all-keys-exhausted" in str(exc.value)   # GERÇEK tükenme (throttle değil)


def test_generate_429_donup_gecerli_keye(tmp_path, monkeypatch):
    p, clock = _pool(tmp_path, keys=("k1", "k2"), cap=100)
    monkeypatch.setattr(GS, "_get_pool", lambda: p)

    def http(api_key, model, prompt, **k):
        if api_key == "AIza-k1":
            raise GS.GoogleStudioError("rate", status=429, body={"error": {"details": [
                {"violations": [{"quotaId": "X-PerMinute"}]}]}})
        return "OK"

    monkeypatch.setattr(GS, "_http_generate", http)
    assert GS.generate("x", model="m") == "OK"   # k1 429 → k2 başarı


def test_generate_bos_yanit_exhausted(tmp_path, monkeypatch):
    p, clock = _pool(tmp_path, keys=("k1",), cap=100)
    monkeypatch.setattr(GS, "_get_pool", lambda: p)
    monkeypatch.setattr(GS, "_http_generate", lambda *a, **k: "")   # güvenlik bloğu
    with pytest.raises(GS.GoogleStudioExhausted) as exc:
        GS.generate("x", model="m", wait_for_slot_s=0)
    assert "empty-response" in str(exc.value)   # boş yanıt — tükenme DEĞİL


# ── Global eşzamanlılık tavanı + capacity 429 sabırlı retry (2026-07-18 fix) ──
def test_set_max_concurrency(monkeypatch):
    monkeypatch.setattr(GS, "_SEM_LIMIT", 4, raising=False)
    GS.set_max_concurrency(2)
    assert GS._SEM_LIMIT == 2 and GS._get_sem()._initial_value == 2
    GS.set_max_concurrency(0)          # <1 → 1'e sıkışır
    assert GS._SEM_LIMIT == 1
    GS.set_max_concurrency(4)          # geri al (diğer testleri etkileme)


def test_eszamanlilik_tavani_http_burst_keser(tmp_path, monkeypatch):
    """Çağıran 12 thread açsa BİLE aynı anda en çok MAX_CONCURRENCY HTTP çağrısı gider."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    p, clock = _pool(tmp_path, keys=tuple(f"k{i}" for i in range(12)), cap=100)
    monkeypatch.setattr(GS, "_get_pool", lambda: p)
    GS.set_max_concurrency(3)
    live = {"cur": 0, "max": 0}
    lock = threading.Lock()

    def slow_http(api_key, model, prompt, **k):
        with lock:
            live["cur"] += 1
            live["max"] = max(live["max"], live["cur"])
        time.sleep(0.05)               # çağrıyı uçuşta tut → eşzamanlılık ölçülsün
        with lock:
            live["cur"] -= 1
        return "OK"

    monkeypatch.setattr(GS, "_http_generate", slow_http)
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = list(ex.map(lambda _: GS.generate("x", model="m"), range(12)))
    GS.set_max_concurrency(4)           # eski hâle
    assert all(r == "OK" for r in res)
    assert live["max"] <= 3, f"eşzamanlı HTTP {live['max']} > tavan 3"


def test_capacity_429_sabirli_retry_sonra_basari(tmp_path, monkeypatch):
    """Detaysız capacity 429 → HEMEN gemma'ya düşme; deadline'a kadar sabırla retry et,
    throttle geçince Google'da başar (short: erken fallback bug'ı)."""
    (tmp_path / "google-keys.json").write_text(json.dumps(
        {"keys": [{"id": "k1", "key": "AIza-k1", "enabled": True}]}))
    p = GS.Pool(tmp_path, now=time.time, daily_cap=100)   # gerçek saat: capacity pause geçsin
    monkeypatch.setattr(GS, "_get_pool", lambda: p)
    GS.set_max_concurrency(4)
    n = {"i": 0}
    cap_body = {"error": {"code": 429, "message": "Resource has been exhausted",
                          "status": "RESOURCE_EXHAUSTED"}}

    def http(api_key, model, prompt, **k):
        n["i"] += 1
        if n["i"] <= 2:                 # ilk 2 çağrı capacity throttle
            raise GS.GoogleStudioError("cap", status=429, body=cap_body)
        return "OK"

    monkeypatch.setattr(GS, "_http_generate", http)
    out = GS.generate("x", model="m", wait_for_slot_s=40)
    assert out == "OK" and n["i"] == 3   # 2 throttle atlatıldı, gemma'ya DÜŞMEDİ
