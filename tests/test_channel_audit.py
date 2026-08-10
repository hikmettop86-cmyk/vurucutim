"""Kanal performans denetimi — ayarları veriyle belirlemek için."""
from __future__ import annotations

from datetime import datetime, timedelta

from short_bot.channel_audit import (headline_truncation_rate, topic_index,
                                     worn_phrases)


def _row(title, category, views, gun=0):
    return {"title": title, "category": category, "views": views,
            "uploaded_at": datetime(2026, 8, 1) + timedelta(days=gun)}


# --- Konu endeksi ------------------------------------------------------------

def test_topic_index_is_relative_to_same_period(topic=None):
    """Endeks, videonun KENDİ dönemindeki medyana oranıdır.

    Kanal büyürken ham görüntülenme karşılaştırması yanıltıyor: eski videolar
    düşük, yeni videolar yüksek çıkıyor ve kategori farkı zaman etkisiyle
    karışıyor.
    """
    rows = ([_row(f"a{i}", "iyi", 200, gun=i) for i in range(4)]
            + [_row(f"b{i}", "kotu", 50, gun=i) for i in range(4)])
    out = {t["category"]: t for t in topic_index(rows)}
    assert out["iyi"]["index"] > 1.0
    assert out["kotu"]["index"] < 1.0
    assert out["iyi"]["n"] == 4


def test_topic_index_skips_thin_samples():
    """n=1-2 kategoriden ayar çıkarılmaz."""
    rows = [_row("a", "genis", 100, gun=i) for i in range(5)]
    rows.append(_row("tek", "ince", 900, gun=0))
    cats = {t["category"] for t in topic_index(rows, min_samples=3)}
    assert "genis" in cats
    assert "ince" not in cats


def test_topic_index_ignores_rows_without_views():
    rows = [_row("a", "x", 100, gun=i) for i in range(3)]
    rows.append({"title": "yeni", "category": "x", "views": None,
                 "uploaded_at": datetime(2026, 8, 1)})
    assert topic_index(rows, min_samples=3)[0]["n"] == 3


# --- Yıpranmış kalıplar ------------------------------------------------------

def test_worn_phrases_flags_overused_underperforming_word():
    """'BOMBA' GS'de 42 kez kullanılıp %82'ye düşmüştü; FB'de 12 kullanımla
    %195'ti. Elle aramak yerine kanalın kendi başlıklarından bulunmalı."""
    rows = ([_row(f"BOMBA haber {i}", "x", 50, gun=i) for i in range(10)]
            + [_row(f"sakin haber {i}", "x", 200, gun=i) for i in range(10)])
    worn = {w["phrase"]: w for w in worn_phrases(rows, min_uses=5)}
    assert "bomba" in worn
    assert worn["bomba"]["index"] < 1.0
    assert worn["bomba"]["uses"] == 10
    # iyi performanslı kelime yıpranmış sayılmamalı
    assert worn["bomba"]["worn"] is True
    assert worn.get("sakin", {}).get("worn", False) is False


def test_worn_phrases_ignores_rare_words():
    rows = [_row(f"tekrar eden {i}", "x", 100, gun=i) for i in range(6)]
    rows.append(_row("nadir kelime burada", "x", 10, gun=0))
    assert "nadir" not in {w["phrase"] for w in worn_phrases(rows, min_uses=5)}


def test_worn_phrases_folds_turkish_case():
    """'BOMBA' ve 'bomba' aynı kalıp; Python .lower() Türkçe I'yı bozar."""
    rows = ([_row(f"HAZIRLIK maçı {i}", "x", 50, gun=i) for i in range(5)]
            + [_row(f"hazırlık maçı {i}", "x", 50, gun=i + 5) for i in range(5)])
    # Kalıplar ASCII'ye katlanmış anahtarla gruplanır (ı→i, ş→s): iki farklı
    # yazım tek kovada toplanmalı.
    worn = {w["phrase"]: w for w in worn_phrases(rows, min_uses=8)}
    assert "hazirlik" in worn
    assert worn["hazirlik"]["uses"] == 10


# --- Anahtar sağlığı ---------------------------------------------------------

def _haber(guid, *, saat_once=1):
    from datetime import timezone
    from short_bot.models import NewsItem
    return NewsItem(
        guid=guid, title=f"baslik {guid}", link=f"http://x/{guid}", source=None,
        pub_date=datetime.now(timezone.utc) - timedelta(hours=saat_once),
        thumb_url=None, description=None)


def test_keyword_health_flags_keyword_with_no_fresh_news():
    """Taze haber getirmeyen anahtar ölüdür.

    Gerçek hata: "Galatasaray başkan yönetim" ve "Galatasaray TFF ceza tahkim"
    100 ve 48 sonuç döndürüyordu ama 148'inin HİÇBİRİ son 24 saatte değildi —
    üç kelimelik sorgular Google News'te dar eşleşip arşiv döndürüyor. Havuz
    dolu göründüğü için aylarca fark edilmedi.
    """
    from short_bot.channel_audit import keyword_health
    besleme = {"ana": [_haber("a1"), _haber("a2")],
               "olu": [_haber("x1", saat_once=200), _haber("x2", saat_once=300)]}
    out = {r["keyword"]: r for r in
           keyword_health(["ana", "olu"], "hl=tr", fetch=lambda k, loc: besleme[k])}

    assert out["olu"]["total"] == 2
    assert out["olu"]["fresh"] == 0
    assert out["olu"]["verdict"] == "ölü"


def test_keyword_health_discounts_news_already_in_the_main_pool():
    """Taze haber getirmek yetmez — ana sorguda zaten varsa katkısı yoktur.

    İlk anahtar referans havuzdur; ek anahtarlar yalnızca ONUN dışında kalan
    haberlerle değerlendirilir. Bu ayrım olmadan örtüşen bir anahtar sağlıklı
    görünür.
    """
    from short_bot.channel_audit import keyword_health
    ortak = _haber("ortak")
    besleme = {"ana": [ortak, _haber("a2")], "kopya": [ortak]}
    out = {r["keyword"]: r for r in
           keyword_health(["ana", "kopya"], "hl=tr", fetch=lambda k, loc: besleme[k])}

    assert out["kopya"]["fresh"] == 1
    assert out["kopya"]["net"] == 0
    assert out["kopya"]["verdict"] == "gereksiz"


def test_keyword_health_credits_only_coverage_the_main_pool_misses():
    from short_bot.channel_audit import keyword_health
    besleme = {"ana": [_haber("a1")], "iyi": [_haber("b1"), _haber("b2")]}
    out = {r["keyword"]: r for r in
           keyword_health(["ana", "iyi"], "hl=tr", fetch=lambda k, loc: besleme[k])}

    assert out["iyi"]["net"] == 2
    assert out["iyi"]["verdict"] == "sağlıklı"


def test_keyword_health_marks_first_keyword_as_the_reference_pool():
    """İlk anahtarın 'net'i kendisine göre ölçülemez — o ana havuzun kendisi."""
    from short_bot.channel_audit import keyword_health
    besleme = {"ana": [_haber("a1"), _haber("a2")]}
    out = keyword_health(["ana"], "hl=tr", fetch=lambda k, loc: besleme[k])

    assert out[0]["verdict"] == "ana havuz"
    assert out[0]["net"] == 2


# --- Manşet kırpması ---------------------------------------------------------

def test_headline_truncation_rate():
    """Kırpma işareti şablon kapasitesinin aşıldığını gösterir."""
    rows = [_row("TAM MANŞET", "x", 100), _row("KESİK…", "x", 100),
            _row("BİR DAHA…", "x", 100), _row("TEMİZ", "x", 100)]
    out = headline_truncation_rate(rows)
    assert out["rate"] == 0.5
    assert out["truncated"] == 2
    assert out["total"] == 4


def test_headline_truncation_rate_empty_is_zero():
    out = headline_truncation_rate([])
    assert out["rate"] == 0.0
    assert out["total"] == 0


# --- Kanal denetimi (DB) + öneriler -----------------------------------------

def _publish(eng, channel, title, category, views, gun=0):
    import json
    from datetime import timezone
    from short_bot.db import (record_short, record_youtube_upload,
                              upsert_video_stats, youtube_uploads)
    sid = record_short(eng, channel=channel, rss_item_guid=f"g{title}",
                       title=title, file_path="x.mp4", duration_s=6,
                       script_json=json.dumps({"category": category}),
                       render_ms=1)
    vid = f"V{sid}"
    record_youtube_upload(eng, short_id=sid, video_id=vid, status="success",
                          error=None, video_url="u")
    ts = datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(days=gun)
    with eng.begin() as conn:
        conn.execute(youtube_uploads.update()
                     .where(youtube_uploads.c.short_id == sid)
                     .values(uploaded_at=ts))
    upsert_video_stats(eng, video_id=vid, snapshot_date=datetime(2026, 8, 20).date(),
                       views=views, likes=0, comments=0, watch_time_min=1.0,
                       avg_view_duration_s=3.0)
    return sid


def test_audit_channel_suggests_quota_for_weak_topic(tmp_path):
    """Kota önerisi performansı KANITLI düşük konuya verilir.

    Gerçek hata buydu: ilk kotayı en ÇOK ÜRETİLEN konuya koydum, oysa o konu
    iki kanalda da ortalama performanslıydı ve kısıtlamak üretimi daha zayıf
    konulara itti.
    """
    from short_bot.db import init_db
    from short_bot.channel_audit import audit_channel
    eng = init_db(tmp_path / "x.sqlite")
    for i in range(6):
        _publish(eng, "c", f"guclu {i}", "iyi-konu", 100_000, gun=i)
    for i in range(6):
        _publish(eng, "c", f"zayif {i}", "kotu-konu", 20_000, gun=i)

    rapor = audit_channel(eng, "c")
    onerilen = {q["category"] for q in rapor["quota_suggestions"]}
    assert "kotu-konu" in onerilen
    assert "iyi-konu" not in onerilen


def test_audit_channel_reports_truncation_and_topics(tmp_path):
    from short_bot.db import init_db
    from short_bot.channel_audit import audit_channel
    eng = init_db(tmp_path / "x.sqlite")
    for i in range(5):
        _publish(eng, "c", f"KESİK…{i}", "konu", 50_000, gun=i)

    rapor = audit_channel(eng, "c")
    assert rapor["headline_truncation"]["rate"] == 1.0
    assert rapor["topics"][0]["category"] == "konu"
    assert rapor["sample_size"] == 5


def test_audit_channel_empty_channel_is_safe(tmp_path):
    from short_bot.db import init_db
    from short_bot.channel_audit import audit_channel
    eng = init_db(tmp_path / "x.sqlite")
    rapor = audit_channel(eng, "yok")
    assert rapor["sample_size"] == 0
    assert rapor["quota_suggestions"] == []


# --- CLI ---------------------------------------------------------------------

def test_cli_analyze_prints_report(tmp_path, capsys):
    """`short-bot analyze --channel X` ayar önerilerini yazdırır."""
    from short_bot.cli import main
    from short_bot.db import init_db
    eng = init_db(tmp_path / "short_bot.sqlite")   # CLI bu adı arar
    for i in range(6):
        _publish(eng, "c", f"BOMBA haber {i}", "zayif-konu", 10_000, gun=i)
    for i in range(6):
        _publish(eng, "c", f"sakin haber {i}", "guclu-konu", 90_000, gun=i)

    rc = main(["analyze", "--channel", "c", "--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "zayif-konu" in out
    assert "guclu-konu" in out
    assert "bomba" in out.lower()       # yıpranmış kalıp raporlanmalı


def _kanal_yaz(tmp_path, *, keywords="['ana', 'olu']"):
    kanal_dir = tmp_path / "channels"
    kanal_dir.mkdir(exist_ok=True)
    (kanal_dir / "c.yaml").write_text(
        f"slug: c\nname: C\nkeywords: {keywords}\nlanguage: tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\nmax_age_hours: 24\ntemplate: default\n"
        "colors:\n  primary: '#111111'\n  accent: '#222222'\n"
        "  bg_gradient: ['#111111', '#222222']\n"
        "handle: '@c'\noutput_dir: output/c\nenabled: true\n", encoding="utf-8")


def test_cli_analyze_reports_dead_keywords(tmp_path, capsys, monkeypatch):
    """Ölü anahtar elle bulunmuş bir hataydı; analyze onu tekrarlanabilir kılar.

    Aynı tuzak her çok anahtarlı kanalda var ve sessiz: havuz dolu görünür,
    yalnız o anahtardan hiç TAZE haber gelmez.
    """
    from short_bot import channel_audit
    from short_bot.cli import main
    from short_bot.db import init_db
    eng = init_db(tmp_path / "short_bot.sqlite")
    for i in range(6):
        _publish(eng, "c", f"haber {i}", "konu", 50_000, gun=i)
    _kanal_yaz(tmp_path)
    monkeypatch.setattr(channel_audit, "keyword_health", lambda kws, loc, **kw: [
        {"keyword": "ana", "total": 110, "fresh": 87, "net": 87,
         "verdict": "ana havuz"},
        {"keyword": "olu", "total": 48, "fresh": 0, "net": 0, "verdict": "ölü"},
    ])

    rc = main(["analyze", "--channel", "c", "--data-dir", str(tmp_path),
               "--config-dir", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "olu" in out
    assert "ölü" in out


def test_cli_analyze_survives_keyword_probe_failure(tmp_path, capsys, monkeypatch):
    """Anahtar ölçümü ağ ister — hatası raporun geri kalanını düşürmemeli."""
    from short_bot import channel_audit
    from short_bot.cli import main
    from short_bot.db import init_db
    eng = init_db(tmp_path / "short_bot.sqlite")
    for i in range(6):
        _publish(eng, "c", f"haber {i}", "konu", 50_000, gun=i)
    _kanal_yaz(tmp_path)

    def patla(*a, **k):
        raise OSError("ağ yok")
    monkeypatch.setattr(channel_audit, "keyword_health", patla)

    rc = main(["analyze", "--channel", "c", "--data-dir", str(tmp_path),
               "--config-dir", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "konu" in out, "konu performansı yine de basılmalı"


def test_cli_analyze_empty_channel_exits_cleanly(tmp_path, capsys):
    from short_bot.cli import main
    from short_bot.db import init_db
    init_db(tmp_path / "short_bot.sqlite")
    rc = main(["analyze", "--channel", "yok", "--data-dir", str(tmp_path)])
    assert rc == 0
    assert "verisi yok" in capsys.readouterr().out.lower()
