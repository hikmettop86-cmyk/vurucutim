"""Saga sınırı: özne anahtarının biçimi ve eşleşme kuralı."""
from __future__ import annotations

from short_bot.topic_taxonomy import (
    normalize_category, normalize_subject, subject_matches,
)


def test_normalize_folds_turkish_dotted_i():
    """"İ".lower() görünmez birleşik nokta üretir; iki ayrı kovaya bölerdi."""
    assert normalize_subject("İCARDİ") == "icardi"


def test_normalize_does_not_apply_turkish_i_rule():
    """Kanallar çok dilli: "I"→"ı" İspanyolca özneleri bozardı."""
    assert normalize_subject("INTER") == "inter"


def test_normalize_collapses_whitespace():
    assert normalize_subject("  aleksey   batrakov ") == "aleksey batrakov"


def test_normalize_empty_returns_empty_not_placeholder():
    """Bilinmeyen özne 'sayma' demek; kategorideki '?' kovası burada YANLIŞ."""
    assert normalize_subject("") == ""
    assert normalize_subject(None) == ""


def test_matches_identical():
    assert subject_matches("batrakov", "batrakov") is True


def test_matches_short_key_inside_longer_one():
    """LLM bir gün soyadı, ertesi gün tam ad yazarsa sayaç bölünmemeli."""
    assert subject_matches("batrakov", "aleksey batrakov") is True
    assert subject_matches("aleksey batrakov", "batrakov") is True


def test_does_not_match_mere_substring_of_a_word():
    """'sara' ile 'sarabia' AYRI kişi — harf içermesi yetmez, kelime olmalı."""
    assert subject_matches("sara", "sarabia") is False


def test_does_not_match_on_short_tokens():
    """2-3 harflik anahtar rastgele eşleşme üretir."""
    assert subject_matches("ns", "ns transfer") is False


def test_empty_never_matches():
    assert subject_matches("", "batrakov") is False
    assert subject_matches("batrakov", "") is False


def test_disjoint_subjects_do_not_match():
    assert subject_matches("leao", "osimhen") is False


def test_matches_same_words_in_different_order():
    """Aynı özne iki kovaya bölünmemeli; sıra farkı anlam farkı değil."""
    assert subject_matches("real madrid", "madrid real") is True


def test_normalize_strips_turkish_possessive_suffix():
    """Kesmeden sonrası ektir; "batrakov'un" ile "batrakov" aynı öznedir."""
    assert normalize_subject("Batrakov'un") == "batrakov"
    assert normalize_subject("Galatasaray'ın") == "galatasaray"


def test_normalize_strips_typographic_apostrophe_too():
    """LLM düz kesme yerine tipografik kesme yazabilir."""
    assert normalize_subject("Leao’ya") == "leao"


def test_normalize_keeps_apostrophe_that_belongs_to_the_name():
    """"O'Brien"de kesme ek ayırıcı değil; gövde 3 harften kısaysa kesme."""
    assert normalize_subject("O'Brien") == "obrien"


def test_normalize_treats_hyphen_as_word_separator():
    assert normalize_subject("Jean-Claude") == "jean claude"


def test_suffixed_and_bare_forms_match():
    """Asıl kazanım: iki biçim aynı sagaya sayılmalı."""
    assert subject_matches(normalize_subject("Batrakov'un"),
                           normalize_subject("Batrakov")) is True


def test_min_token_boundary_rejects_three_chars():
    """_SUBJECT_MIN_TOKEN sınırı: 3 harf reddedilir, 4 harf kabul edilir."""
    assert subject_matches("leo", "leo messi") is False
    assert subject_matches("leao", "sporting leao") is True


# --- Aksan aynı özneyi iki kovaya bölmemeli -----------------------------------
#
# Bu kanalda anahtar sapmasının EN SIK kaynağı buydu ve hiçbir savunma yoktu.
# Düzeltmeden ÖNCEKİ ölçüm:
#     'Aktürkoğlu' -> 'aktürkoğlu' | 'Akturkoglu' -> 'akturkoglu' | eşleşme YOK
#     'Kılıç'      -> 'kılıç'      | 'Kilic'      -> 'kilic'      | eşleşme YOK
#     'Şahin'      -> 'şahin'      | 'Sahin'      -> 'sahin'      | eşleşme YOK
# LLM aynı soyadı iki koşuda iki türlü yazıyor; sayaç yarı yarıya boş kalıyordu.

def test_diacritics_do_not_split_the_key():
    """Aksanlı ve aksansız yazım AYNI anahtara inmeli."""
    assert normalize_subject("Aktürkoğlu") == normalize_subject("Akturkoglu")
    assert normalize_subject("Kılıç") == normalize_subject("Kilic")
    assert normalize_subject("Şahin") == normalize_subject("Sahin")


def test_diacritic_variants_match_the_same_saga():
    """Asıl kazanım: iki yazım aynı sagaya sayılmalı."""
    assert subject_matches(normalize_subject("Aktürkoğlu"),
                           normalize_subject("Akturkoglu")) is True
    assert subject_matches(normalize_subject("Kılıç"),
                           normalize_subject("Kilic")) is True
    assert subject_matches(normalize_subject("Şahin"),
                           normalize_subject("Sahin")) is True


def test_dotless_i_folds_to_ascii_i():
    """'ı' AYRI bir harf: birleşik işaret ayrışması yok, NFKD tek başına
    düşüremez — elle eşlenmesi şart."""
    assert normalize_subject("Kılıç") == "kilic"


def test_folding_direction_is_ascii_not_turkish_i_rule():
    """Katlama `ı → i` yönünde; Türkçe `I → ı` yönü İspanyolcayı bozardı."""
    assert normalize_subject("INFORMACIÓN") == "informacion"
    assert normalize_subject("INTER") == "inter"


def test_folding_runs_before_stemming_and_hyphen_split():
    """SIRA kanıtı: sökme, kesme/tire adımlarından ÖNCE koşmalı.

    NFKD, o adımların ARADIĞI ayırıcıların uyumluluk biçimlerini ASCII
    karşılığına indirir: tam-genişlik kesme (U+FF07) → "'", tam-genişlik tire
    (U+FF0D) → "-". Sökme sonraya kalsaydı bu karakterler ayırıcı listelerine
    uymaz, `_stem`'in alnum süzgeci onları sessizce yutar ve kelimeler
    yapışırdı. Ölçüldü (sonra sökülen sürümle):

        "Batrakov＇un" → 'batrakovun'  (doğrusu 'batrakov')
        "Jean－Claude" → 'jeanclaude'  (doğrusu 'jean claude')
    """
    assert normalize_subject("Batrakov＇un") == "batrakov"
    assert normalize_subject("Jean－Claude") == "jean claude"
    # DEĞER kanıtı: yapışık hâl sayacı sessizce ikiye bölerdi.
    assert subject_matches(normalize_subject("Batrakov＇un"),
                           normalize_subject("Batrakov")) is True
    assert subject_matches("batrakovun", "batrakov") is False


def test_category_normalisation_is_NOT_folded():
    """`normalize_category` DEĞİŞMEDİ — aksan korunmalı.

    Kategori değerleri kanal config'indeki KAPALI listeden birebir kopyalanıp
    gösteriliyor; özne ise hiç gösterilmeyen saf karşılaştırma anahtarı. Sert
    katlama yalnız öznede doğru.
    """
    assert normalize_category("İLGİNÇ") == "ilginç"
    assert normalize_category("Ünlü Şarkıcı") == "ünlü şarkıcı"


from datetime import datetime

from short_bot.models import NewsItem, ScoredItem, Script


def test_scored_item_subject_defaults_empty():
    item = NewsItem(guid="g", title="t", link="l", source="s",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)
    assert ScoredItem(item=item, score=8.0, reasoning="").subject == ""


def test_scored_item_carries_subject():
    item = NewsItem(guid="g", title="t", link="l", source="s",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)
    s = ScoredItem(item=item, score=8.0, reasoning="", subject="batrakov")
    assert s.subject == "batrakov"


def _script(**kw) -> Script:
    base = dict(header_top="UST", header_bottom="ALT", photo_overlay="foto",
                body_paragraph="Bu bir gövde metnidir, yeterince uzun.",
                category="transfer-gelen", mood="neutral")
    base.update(kw)
    return Script(**base)


def test_script_subject_defaults_empty_and_round_trips():
    """subject script_json'a yazılır; sayaç oradan okur."""
    import json
    assert _script().subject == ""
    dumped = json.loads(_script(subject="batrakov").model_dump_json())
    assert dumped["subject"] == "batrakov"


from short_bot.scorer import apply_saga_penalty


def _si(guid, score, subject):
    item = NewsItem(guid=guid, title=guid, link="l", source="s",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)
    return ScoredItem(item=item, score=score, reasoning="", subject=subject)


def test_penalty_scales_with_repeat_count():
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={"batrakov": 3}, step=1.0)
    assert out[0].score == 6.0


def test_first_appearance_is_free():
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={}, step=1.0)
    assert out[0].score == 9.0


def test_penalty_has_NO_min_score_floor():
    """Kotadan ayrılan nokta: saga cezası adayı eşiğin ALTINA itebilir.

    Gerekçe ölçüm: üretilenin %42'si zaten yayına çıkmıyor, yani boş geçmek
    yüklenmeyecek zayıf video üretmekten ucuz.
    """
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={"batrakov": 5}, step=1.0)
    assert out[0].score == 4.0        # 6.0'lık min_score'un ALTINDA


def test_penalty_never_goes_below_zero():
    scored = [_si("g", 2.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={"batrakov": 9}, step=1.0)
    assert out[0].score == 0.0


def test_empty_subject_is_never_penalised():
    scored = [_si("g", 9.0, "")]
    out = apply_saga_penalty(scored, produced={"batrakov": 5}, step=1.0)
    assert out[0].score == 9.0


def test_step_zero_is_passthrough():
    """Kapalı kanallarda (varsayılan) hiçbir puan değişmez."""
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={"batrakov": 5}, step=0.0)
    assert out[0].score == 9.0


def test_counts_across_matching_key_variants():
    """'batrakov' ve 'aleksey batrakov' AYNI sagadır; sayı toplanır."""
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(
        scored, produced={"batrakov": 1, "aleksey batrakov": 2}, step=1.0)
    assert out[0].score == 6.0


def test_unrelated_subject_untouched():
    scored = [_si("g", 9.0, "osimhen")]
    out = apply_saga_penalty(scored, produced={"batrakov": 5}, step=1.0)
    assert out[0].score == 9.0


import json as _json
from datetime import timezone

from sqlalchemy import update

from short_bot.db import (
    count_recent_subjects, init_db, record_short, record_youtube_upload, shorts,
)


def _rec(eng, subject, **kw):
    return record_short(
        eng, channel="gs", rss_item_guid=kw.get("guid", subject),
        title=subject, file_path="x.mp4", duration_s=6,
        script_json=_json.dumps({"subject": subject}), render_ms=1)


def _sil(eng, short_id):
    """deleted_at'i doğrudan yaz.

    `db.py`'de soft-delete yardımcısı YOK — silme web katmanında ORM ile
    yapılıyor (`web/models.py`). Test tabloyu doğrudan güncelliyor.
    """
    with eng.begin() as conn:
        conn.execute(update(shorts).where(shorts.c.id == short_id)
                     .values(deleted_at=datetime.now(timezone.utc)))


def test_counts_produced_subjects(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _rec(eng, "batrakov", guid="a")
    _rec(eng, "batrakov", guid="b")
    _rec(eng, "leao", guid="c")
    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 2, "leao": 1}


def test_normalises_keys_while_counting(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _rec(eng, "Batrakov", guid="a")
    _rec(eng, "  batrakov ", guid="b")
    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 2}


def test_ignores_records_without_subject(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    record_short(eng, channel="gs", rss_item_guid="a", title="t",
                 file_path="x.mp4", duration_s=6,
                 script_json=_json.dumps({"category": "transfer-gelen"}),
                 render_ms=1)
    assert count_recent_subjects(eng, "gs", days=14) == {}


def test_other_channels_are_not_counted(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    record_short(eng, channel="fb", rss_item_guid="a", title="t",
                 file_path="x.mp4", duration_s=6,
                 script_json=_json.dumps({"subject": "batrakov"}), render_ms=1)
    assert count_recent_subjects(eng, "gs", days=14) == {}


def test_deleted_without_upload_is_not_counted(tmp_path):
    """Operatör akışı: beğenmezse doğrudan siler. Reddedilen video sayılmaz."""
    eng = init_db(tmp_path / "x.sqlite")
    sid = _rec(eng, "batrakov", guid="a")
    _sil(eng, sid)
    assert count_recent_subjects(eng, "gs", days=14) == {}


def test_uploaded_then_deleted_IS_counted(tmp_path):
    """Beğenirse YÜKLER ve listeden siler — izleyici gördü, sayılmalı."""
    eng = init_db(tmp_path / "x.sqlite")
    sid = _rec(eng, "batrakov", guid="a")
    record_youtube_upload(eng, short_id=sid, video_id="v1", status="success",
                          error=None, video_url="u")
    _sil(eng, sid)
    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 1}


def test_multiple_upload_rows_count_the_video_once(tmp_path):
    """Başarısız deneme + yeniden yükleme = 2 satır, ama TEK video.

    Ölçüldü: üretimde 9 short'un birden çok yükleme satırı var. DISTINCT
    olmadan o videonun öznesi iki kez sayılır ve saga cezası hak edilmeden
    iki katına çıkardı.
    """
    eng = init_db(tmp_path / "x.sqlite")
    sid = _rec(eng, "batrakov", guid="a")
    record_youtube_upload(eng, short_id=sid, video_id=None, status="failed",
                          error="boom", video_url=None)
    record_youtube_upload(eng, short_id=sid, video_id="v1", status="success",
                          error=None, video_url="u")
    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 1}


from short_bot.config import ChannelConfig, load_channel, save_channel


def _cfg(**kw) -> ChannelConfig:
    from dataclasses import replace as _replace
    base = ChannelConfig(
        slug="gs", name="GS", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, language="tr",
    )
    return _replace(base, **kw)


def test_saga_fields_default_to_disabled():
    """Varsayılan 0.0 — mevcut kanalların hiçbiri etkilenmez."""
    cfg = _cfg()
    assert cfg.saga_penalty_per_repeat == 0.0
    assert cfg.saga_window_days == 14


def test_saga_fields_round_trip_through_yaml(tmp_path):
    p = tmp_path / "gs.yaml"
    save_channel(p, _cfg(saga_penalty_per_repeat=1.0, saga_window_days=10))
    back = load_channel(p)
    assert back.saga_penalty_per_repeat == 1.0
    assert back.saga_window_days == 10


def test_disabled_channel_yaml_stays_clean(tmp_path):
    """Kapalıyken YAML'a anahtar YAZILMAZ — mevcut dosyalar kirlenmesin."""
    p = tmp_path / "gs.yaml"
    save_channel(p, _cfg())
    assert "saga_penalty_per_repeat" not in p.read_text(encoding="utf-8")


# --- Puanlayıcı prompt'u özne istiyor -----------------------------------------

from short_bot.scorer import build_scoring_prompt


def _ch(**kw):
    return _cfg(name="Aslan Gündem", keywords=["Galatasaray"], **kw)


def _items():
    return [NewsItem(guid="g1", title="Batrakov geldi", link="l", source="s",
                     pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)]


def test_prompt_asks_for_subject_when_saga_enabled():
    p = build_scoring_prompt(_items(), channel=_ch(saga_penalty_per_repeat=1.0))
    assert '"subject"' in p


def test_prompt_stays_unchanged_when_saga_disabled():
    """Kapalı kanalların prompt'u hiç değişmemeli."""
    p = build_scoring_prompt(_items(), channel=_ch())
    assert "subject" not in p


def test_prompt_forbids_the_channel_subject_as_key():
    """Her haberde 'Galatasaray' geçiyor; anahtar olarak işe yaramaz.

    Eski hâli `"Galatasaray" in p` diye bakıyordu ve UYGULAMA YOKKEN DE
    geçiyordu — kanal adı zaten temel şablonun "KANAL:" satırında var.
    Yasak cümlesinin kendisine bakmak gerekiyor.
    """
    acik = build_scoring_prompt(_items(), channel=_ch(saga_penalty_per_repeat=1.0))
    kapali = build_scoring_prompt(_items(), channel=_ch())
    assert "ASLA yazma" in acik
    assert "ASLA yazma" not in kapali


# --- LLM çıktısı normalize edilerek ScoredItem'a düşüyor ----------------------
#
# Asıl risk burada: prompt doğru şeyi istese bile LLM'in ham cevabı
# (büyük/küçük harf, kesme eki, boşluk) normalize edilmeden saklanırsa
# subject_matches hiçbir zaman eşleşmez ve saga sayacı sessizce hiç dolmaz.

from unittest.mock import patch

from short_bot.scorer import _ScoreResponse, score_items


def test_score_items_normalizes_llm_subject_before_storing():
    """LLM ham 'Batrakov'un' yazsa bile ScoredItem.subject normalize hâlde
    saklanmalı — aksi halde db.count_recent_subjects'teki anahtarla asla
    eşleşmez ve saga cezası hiç tetiklenmez."""
    fake = _ScoreResponse(scores=[
        {"guid": "g1", "score": 8.0, "reasoning": "r", "subject": "Batrakov'un"},
    ])
    with patch("short_bot.scorer.run_json", return_value=fake):
        out = score_items(_items(), channel=_ch(saga_penalty_per_repeat=1.0))
    assert out[0].subject == "batrakov"


def test_score_items_subject_empty_when_llm_omits_it():
    """Saga kapalı kanallarda ya da LLM özneyi boş bırakınca subject boş
    kalmalı, kategori gibi '?' yer tutucusuna DÜŞMEMELİ (bkz. normalize_subject
    docstring: boş özne 'hiç sayma' demek, 'bilinmeyen kovası' değil)."""
    fake = _ScoreResponse(scores=[
        {"guid": "g1", "score": 8.0, "reasoning": "r"},
    ])
    with patch("short_bot.scorer.run_json", return_value=fake):
        out = score_items(_items(), channel=_ch())
    assert out[0].subject == ""
