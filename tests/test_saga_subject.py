"""Saga sınırı: özne anahtarının biçimi ve eşleşme kuralı."""
from __future__ import annotations

from short_bot.topic_taxonomy import normalize_subject, subject_matches


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
