# Per-Channel YouTube Proxy Support — Design Spec

**Tarih**: 2026-05-08
**Status**: Approved (brainstorming) → Implementation pending

## Problem

short-bot şu anda YouTube Data API v3 üzerinden upload yapıyor; tüm kanallar
aynı makineden, dolayısıyla **aynı public IP**'den. YouTube spam algoritması
farklı kanalların aynı IP'den upload yapmasını şüpheli görebilir (pattern:
"network of accounts coordinated from one source"). Kullanıcı bu riski
azaltmak için her kanala özel proxy üzerinden upload yapabilmek istiyor.

## Hedefler

1. Her kanal için opsiyonel olarak proxy URL tanımlanabilsin
2. Tanımlıysa **tüm** YouTube API çağrıları (upload, channels.list, analytics,
   token refresh) o proxy üzerinden gitmeli
3. Proxy fail olursa upload **abort** edilmeli (kullanıcının net isteği —
   aynı IP'den fallback yapma)
4. UI: kanal edit ekranında proxy URL girilebilir + Test Et butonu
5. Proxy credentials kanal yaml'a değil, secrets dosyasına yazılmalı

## Kapsam Dışı

- Otomatik proxy rotation (single static proxy per channel yeterli)
- Proxy pool/load balancing
- IPv6 specific handling
- Browser automation (Playwright) için proxy — sadece YouTube API path'i

## Tasarım

### Veri Modeli

`data/secrets.yaml` (mevcut dosya — `pexels_api_key` zaten orada) yeni anahtar:

```yaml
pexels_api_key: "..."
channel_proxies:
  galatasaray: "http://user:pass@proxy.host.com:8080"
  fenerbahce:  "socks5://user:pass@another.host:1080"
  ekonomi:     "https://1.2.3.4:3128"     # IP-whitelist (auth yok)
```

URL şeması protokolü belirler:
- `http://`, `https://` — HTTP CONNECT proxy
- `socks5://` — SOCKS5 (PySocks via httplib2.socks)
- `socks4://` — SOCKS4 (rare ama destek dahil)

Userinfo (`user:pass@`) opsiyonel — IP-whitelist proxy ise yazılmaz.

`channel_proxies` anahtarı yoksa veya kanal slug'ı yoksa → o kanal için
proxy yok, plain HTTP kullanılır.

### Yeni Modül: `src/short_bot/youtube/proxy.py`

Tek sorumluluğu: kanal slug verince proxy URL'sini secrets'tan okuyup
proxy-aware HTTP transport objeleri üretmek.

```python
from urllib.parse import urlparse
import httplib2
import requests

def load_channel_proxy_url(slug: str, secrets_path: Path) -> str | None:
    """data/secrets.yaml -> channel_proxies[slug] oku.

    Returns:
        proxy URL string veya None (yoksa).
    """

def parse_proxy_url(url: str) -> tuple[int, str, int, str | None, str | None]:
    """URL'i (proxy_type, host, port, user, pass) tuple'ına çevir.

    proxy_type: httplib2.socks.PROXY_TYPE_* sabitleri
        - http://, https:// -> PROXY_TYPE_HTTP
        - socks5://         -> PROXY_TYPE_SOCKS5
        - socks4://         -> PROXY_TYPE_SOCKS4
    """

def build_proxied_http(proxy_url: str | None, *, timeout: int = 60) -> httplib2.Http:
    """httplib2.Http(proxy_info=...) ile proxy-aware http.

    proxy_url None ise plain Http döner (caller direkt geçebilir).
    """

def build_proxied_requests_session(proxy_url: str | None) -> requests.Session:
    """requests.Session(proxies={'http': ..., 'https': ...}).

    google.auth.transport.requests.Request(session=...) için kullanılır
    (token refresh path'i requests bekler, httplib2 değil).
    """
```

### Entegrasyon Noktaları

Mevcut 4 `build("youtube", "v3", credentials=...)` çağrısı + 1 `Request()`
çağrısı her biri proxy-aware versiyona geçer.

| Dosya | Satır | Değişiklik |
|---|---|---|
| `youtube/auth.py` | ~51 | `creds.refresh(Request(session=proxied_session))` |
| `youtube/auth.py` | ~89 | `build("youtube", v3, http=AuthorizedHttp(creds, http=proxied_http))` |
| `youtube/uploader.py` | ~58 | aynı |
| `youtube/data_api.py` | ~18, ~37 | aynı |

Tüm bu fonksiyonlar `slug` parametresi alır, `proxy.py`'yi çağırır,
http+session üretir, geçirir.

`google_auth_httplib2.AuthorizedHttp` zaten Credentials + httplib2.Http alıyor;
yeni dependency yok.

### Web UI Değişikliği

`src/short_bot/web/templates/channel_edit.html` içinde **YouTube Bağlantı**
bölümünün altına:

```html
<div class="form-row">
  <label for="yt_proxy_url">
    Proxy URL
    <small>(opsiyonel — same-IP riski için)</small>
  </label>
  <input type="text" id="yt_proxy_url" name="yt_proxy_url"
         value="{{ proxy_url|e }}"
         placeholder="http://user:pass@host:8080 veya socks5://...">
  <button type="button" id="btn-test-proxy" class="secondary">Test Et</button>
  <span id="proxy-test-result"></span>
</div>
```

Inline JS:

```js
document.getElementById('btn-test-proxy').addEventListener('click', async () => {
  const url = document.getElementById('yt_proxy_url').value.trim();
  const slug = '{{ cfg.slug }}';
  const r = await fetch(`/channels/${slug}/test-proxy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proxy_url: url }),
  });
  const j = await r.json();
  const el = document.getElementById('proxy-test-result');
  el.textContent = j.ok
    ? `✓ Proxy çalışıyor — IP: ${j.ip}${j.country ? ' (' + j.country + ')' : ''}`
    : `✗ ${j.error}`;
  el.className = j.ok ? 'ok' : 'err';
});
```

### Yeni Endpoint: `POST /channels/<slug>/test-proxy`

```python
@bp.post("/channels/<slug>/test-proxy")
def test_proxy(slug):
    payload = request.get_json(silent=True) or {}
    proxy_url = (payload.get("proxy_url") or "").strip()
    if not proxy_url:
        return jsonify(ok=False, error="proxy URL boş"), 400
    try:
        sess = build_proxied_requests_session(proxy_url)
        r = sess.get("https://api.ipify.org?format=json", timeout=10)
        ip = r.json().get("ip")
        # Country lookup (opsiyonel — best effort)
        country = None
        try:
            r2 = sess.get(f"https://ipapi.co/{ip}/country_name/", timeout=5)
            if r2.status_code == 200:
                country = r2.text.strip()
        except Exception:
            pass
        return jsonify(ok=True, ip=ip, country=country)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])
```

10s timeout. Hata mesajı 200 char'a trim. Country lookup best-effort
(başarısız olsa da IP gösterilir).

### Form Save Akışı

`channel_edit.py`'de yt_present bloğu sonrası ek:

```python
yt_proxy_url = (request.form.get("yt_proxy_url") or "").strip() or None
# Save proxy in secrets.yaml (NOT channel yaml — credentials don't belong there)
from short_bot.secrets_io import update_channel_proxy
update_channel_proxy(secrets_path, slug, yt_proxy_url)
```

`secrets_io` modülü atomic yaml yazma helper (zaten varsa kullan, yoksa
küçük bir helper yarat). Idempotent: None geçilirse o key silinir.

### Hata Akışı

```
pipeline.py YouTube upload step:
  proxy_url = load_channel_proxy_url(slug, secrets_path)
  http = build_proxied_http(proxy_url)               # None → plain Http
  session = build_proxied_requests_session(proxy_url) # None → plain Session

  # Token refresh proxy üzerinden (expired ise) — proxy fail buradan yakalanır
  request = Request(session=session)
  try:
      if creds.expired and creds.refresh_token:
          creds.refresh(request)
  except (requests.exceptions.ProxyError,
          requests.exceptions.ConnectionError) as e:
      raise UploadAbortError(
          f"YouTube upload abort: proxy fail ({slug}): {_redact_err(e)}"
      )

  try:
      upload_video(credentials=creds, http=http, ...)  # build(http=...) içeride
  except httplib2.HttpLib2Error as e:
      raise UploadAbortError(
          f"YouTube upload abort: proxy/network fail ({slug}): {_redact_err(e)}"
      )
```

`UploadAbortError` yeni bir exception class — mevcut try/except'in özel bir
alt türü. UI'da kırmızı banner: "Upload başarısız — proxy bağlantısı
kurulamadı. Edit sayfasından Test Et ile proxy'yi doğrulayın."

**DB state**: Mevcut `videos` tablosunda upload status nasıl saklanıyor
plan aşamasında doğrulanır. Şu an muhtemelen text/enum — yeni değer
`'proxy_failed'` eklenir. Migration gerekirse Alembic-style basit ALTER.
Plan dökümanı bu noktayı `videos` modelini okuyup karara bağlar.

### Dependency Ekleme

`pyproject.toml`:

```diff
     "google-auth-httplib2>=0.1.0",
     "cryptography>=42.0",
+    "PySocks>=1.7",
 ]
```

`PySocks` httplib2'nin SOCKS5 desteği için runtime gerek. httplib2 kendi
`socks.py` modülünde PROXY_TYPE_SOCKS5 sabitini export eder ama gerçek
socket-level bağlantı kurmak için PySocks paketinin kurulu olması şart;
`socks.create_connection` PySocks'tan geliyor. PySocks pure-Python, wheel
universal — Windows install'da sorun çıkmaz.

HTTP/HTTPS proxy için PySocks gerekmiyor (httplib2 native CONNECT desteği
var). Yani: PySocks olmadan HTTP/HTTPS proxy çalışır, SOCKS5 fail eder.
Spec gereği SOCKS5 zorunlu olduğu için dep eklenir.

### Logging — Credentials Sızıntısı Önleme

`proxy.py`'de tüm log mesajlarında URL **redact** edilmeli:

```python
import re

_CRED_RE = re.compile(r"://[^:/]+:[^@]+@")  # ://user:pass@

def _redact(url: str) -> str:
    """URL içindeki user:pass'ı maskele."""
    p = urlparse(url)
    if p.username or p.password:
        netloc = f"***:***@{p.hostname}:{p.port}"
        return f"{p.scheme}://{netloc}"
    return url

def _redact_err(exc: BaseException) -> str:
    """Exception mesajındaki tüm URL credentials'ları maskele.
    requests/httplib2 hata mesajları bazen tam URL içerir."""
    return _CRED_RE.sub("://***:***@", str(exc))
```

Tüm log/error path'lerinde kullanılır:
- `logger.info(f"using proxy {_redact(proxy_url)}")`
- `raise UploadAbortError(f"... {_redact_err(e)}")`
- Test endpoint response: `error: _redact_err(e)[:200]`

### Test Stratejisi

`tests/test_youtube_proxy.py` (yeni):

1. **URL parsing**:
   - `http://user:pass@h:8080` → `(PROXY_TYPE_HTTP, "h", 8080, "user", "pass")`
   - `socks5://1.2.3.4:1080` → `(PROXY_TYPE_SOCKS5, "1.2.3.4", 1080, None, None)`
   - `socks4://...`, `https://...`, invalid URL hata fırlat
2. **load_channel_proxy_url**:
   - secrets.yaml'da slug var → URL döner
   - secrets.yaml'da slug yok → None
   - secrets.yaml hiç yok → None
   - `channel_proxies` anahtarı yok → None
3. **build_proxied_http**:
   - Mock `httplib2.Http` ile ProxyInfo doğru sabitlerle çağrılıyor mu
4. **_redact**:
   - Credentials gizleniyor mu (`user:pass@` → `***:***@`)
   - Yoksa olduğu gibi (idempotent)
5. **Integration test (skip if no live proxy)**:
   - Test endpoint mock proxy başlatıp gerçek IP dönüyor mu
   - `marker: "slow"` ile dev tarafından opt-in

`tests/test_secrets_io.py`: update_channel_proxy idempotent (None silinir,
str eklenir/güncellenir, diğer keys etkilenmez).

## Risk Listesi

| Risk | Etki | Mitigasyon |
|---|---|---|
| Proxy URL log/error mesajlarında sızar | Credentials leak | `_redact()` her log/error mesajına |
| `MediaFileUpload` resumable proxy timeout'u | Upload yarıda kalır | httplib2 timeout=60s + existing retry loop (max_retries=5) |
| PySocks Windows wheel? | Install fail | PySocks pure-Python, wheel zaten universal |
| secrets.yaml format breakage | Eski user'lar bozulur | `channel_proxies` opsiyonel — yoksa eski davranış |
| Proxy değişti ama token cache'i eski | İlk istekte 407 | `build_proxied_requests_session`'a yeni session her seferinde |

## Migration Notu

Mevcut `secrets.yaml` formatı bozulmuyor — `channel_proxies` opsiyonel yeni
anahtar. Eski kurulumlar (proxy tanımlamayan kullanıcılar) hiçbir şey
değişmeden çalışmaya devam eder.

## Açık Olmayan Kararlar — Karar

- **`secrets.yaml`'da `channel_proxies` formatı**: dict<slug, url_string>.
  List/object value seçeneği değil — tek URL yeter, rotation kapsam dışı.
- **Test endpoint için public IP probe**: `api.ipify.org` (basit, hızlı,
  rate-limit yok). Country için `ipapi.co` (best-effort fallback).
- **httplib2 timeout**: 60s (resumable upload chunk'larında uzun
  upload'lar olabilir). PR-time'da daha küçük yapılabilir.
- **SOCKS4**: SOCKS5 ile beraber gelir (httplib2.socks aynı modül).
  Ekstra effort yok, dahil ettim.

## Implementation Sırası (Plan İçin)

1. `proxy.py` modülü + tests — pure logic, side-effect yok
2. `secrets_io.py` `update_channel_proxy` helper + tests
3. `auth.py`, `uploader.py`, `data_api.py` integrate (slug parametresi
   ekleme + http=, session= geçişi)
4. `pyproject.toml` PySocks ekle
5. Pipeline error path: `UploadAbortError` raise + DB enum
6. Web UI: form field + JS test button
7. Test endpoint: `POST /channels/<slug>/test-proxy`
8. Manual smoke: gerçek proxy ile upload başarılı, fail-case abort doğru

Her adım kendi commit'ine girebilir, küçük PR'lar.
