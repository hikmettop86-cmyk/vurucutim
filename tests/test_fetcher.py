from pathlib import Path
from unittest.mock import patch

from short_bot.fetcher import fetch_rss, build_rss_url


def test_build_rss_url_single_keyword():
    url = build_rss_url(["faiz"], "hl=tr&gl=TR&ceid=TR:tr")
    assert "q=faiz" in url
    assert "hl=tr&gl=TR&ceid=TR:tr" in url


def test_build_rss_url_multi_keyword_or_joined():
    url = build_rss_url(["faiz", "dolar", "deprem"], "hl=tr")
    assert "q=faiz+OR+dolar+OR+deprem" in url


def test_fetch_rss_parses_fixture():
    fixture = Path(__file__).parent / "fixtures" / "rss_son_dakika.xml"
    raw = fixture.read_bytes()
    with patch("short_bot.fetcher.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = raw
        items = fetch_rss(["faiz"], "hl=tr&gl=TR&ceid=TR:tr")
    assert len(items) == 2
    first = items[0]
    assert first.guid == "CBMxxx"
    assert first.source == "Reuters TR"
    assert first.thumb_url == "https://lh3.googleusercontent.com/proxy/abc.jpg"
    assert items[1].thumb_url is None


def test_fetch_rss_retries_on_failure():
    from requests.exceptions import ConnectionError
    with patch("short_bot.fetcher.requests.get",
               side_effect=[ConnectionError(), ConnectionError(),
                            type("R", (), {"status_code": 200, "content": b"<rss version='2.0'><channel></channel></rss>"})()]):
        items = fetch_rss(["x"], "hl=tr", max_retries=3, backoff=0)
    assert items == []


def test_build_rss_url_uses_language_param():
    from short_bot.fetcher import build_rss_url_for_language
    url = build_rss_url_for_language(["x"], "de")
    assert "hl=de" in url
    assert "gl=DE" in url


def test_build_rss_url_for_language_invalid():
    import pytest
    from short_bot.fetcher import build_rss_url_for_language
    with pytest.raises(KeyError):
        build_rss_url_for_language(["x"], "xx")


# --- Çok anahtarlı besleme ---------------------------------------------------

def _rss_bytes(*guids: str) -> bytes:
    items = "".join(
        f"<item><title>Baslik {g} - Kaynak</title><link>http://x/{g}</link>"
        f"<guid>{g}</guid></item>"
        for g in guids
    )
    return f"<rss version='2.0'><channel>{items}</channel></rss>".encode()


def test_multi_keyword_issues_one_request_per_keyword():
    """OR sorgusu havuzu genişletmiyor: ölçümde q=galatasaray 110 sonuç
    verirken 4 terimli OR 100'e DÜŞÜYOR. Ayrı sorgu ise %92 yeni haber
    getiriyor — her anahtar kendi sorgusunu almalı."""
    with patch("short_bot.fetcher.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = _rss_bytes("a")
        fetch_rss(["galatasaray", "Galatasaray Şampiyonlar Ligi"], "hl=tr")

    assert mock_get.call_count == 2
    urls = [c.args[0] for c in mock_get.call_args_list]
    assert any("q=galatasaray&" in u for u in urls)
    assert any("%C5%9Eampiyonlar" in u for u in urls)
    assert not any("+OR+" in u for u in urls)


def test_multi_keyword_merges_and_dedupes_by_guid():
    """Aynı haber iki sorgudan da gelebilir — tek kez sayılmalı."""
    from unittest.mock import MagicMock
    responses = [
        MagicMock(status_code=200, content=_rss_bytes("a", "shared")),
        MagicMock(status_code=200, content=_rss_bytes("shared", "b")),
    ]
    with patch("short_bot.fetcher.requests.get", side_effect=responses):
        items = fetch_rss(["k1", "k2"], "hl=tr")

    assert [i.guid for i in items] == ["a", "shared", "b"]


def test_multi_keyword_interleaves_so_first_key_cannot_eat_the_window():
    """Anahtarlar sırayla eklenirse ilk anahtar puanlama penceresini yutar.

    pipeline `new_items[:max_candidates_per_run]` ile havuzun BAŞINDAN dilim
    alıyor. Anahtar sonuçları ardışık eklendiğinde bu dilim tamamen ilk
    anahtardan gelir: gerçek koşuda 96 taze haberlik havuzda pencerenin
    10/10'u "galatasaray" sorgusundandı, kanalın en iyi kategorilerini
    beslemek için eklenen ŞL/yönetim/hukuk anahtarları hiç puanlanmadı ve
    kanal üretimi durdu. Sonuçlar anahtarlar arasında dönüşümlü dizilmeli.
    """
    from unittest.mock import MagicMock
    responses = [
        MagicMock(status_code=200,
                  content=_rss_bytes(*[f"a{i}" for i in range(10)])),
        MagicMock(status_code=200, content=_rss_bytes("b0", "b1", "b2")),
    ]
    with patch("short_bot.fetcher.requests.get", side_effect=responses):
        items = fetch_rss(["k1", "k2"], "hl=tr")

    pencere = [i.guid for i in items[:6]]
    assert sum(1 for g in pencere if g.startswith("b")) >= 2, pencere
    assert len(items) == 13, "hiçbir haber düşmemeli, yalnız sıra değişmeli"


def test_single_keyword_still_issues_one_request():
    """Tek anahtarlı kanallar (mevcut tüm kanallar) aynı davranışta kalır."""
    with patch("short_bot.fetcher.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = _rss_bytes("a")
        items = fetch_rss(["galatasaray"], "hl=tr")

    assert mock_get.call_count == 1
    assert len(items) == 1
