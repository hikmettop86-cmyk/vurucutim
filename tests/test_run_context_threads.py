"""Paralel vision çağrılarının logları run dosyasına DÜŞMELİ.

GERÇEK ÖLÇÜM YANILSAMASI: run log handler'ında iş parçacığına özel bir filtre var
(eşzamanlı koşular birbirinin logunu kirletmesin diye). Vision çağrılarını
ThreadPoolExecutor'a taşıyınca worker thread'lerde o bağlam OLMADIĞI için kapı
logları run dosyasına HİÇ DÜŞMEDİ.

Teşhis yanlış yere baktı: "12 klip için 1 vision yargısı" diye okundu — oysa 24
yargı yapılmış, bütçe dolmuştu; loglar yalnızca GÖRÜNMÜYORDU.

Filtreyi gevşetmek YANLIŞ çözüm olurdu (eşzamanlı koşuların izolasyonunu bozar).
Doğrusu: bağlamı worker'a TAŞIMAK.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from short_bot.pipeline import (_clear_active_run_log_path, _setup_logger,
                                _set_active_run_log_path, _teardown_logger)
from short_bot.run_context import get_log_path, pool_initializer


def test_worker_threads_write_into_the_active_run_log(tmp_path):
    """Havuzdaki worker, ebeveynin koşu logunu DEVRALMALI."""
    log_path = tmp_path / "run.log"
    logger = _setup_logger(log_path)
    sub = logging.getLogger("short_bot.footage_matcher")
    try:
        _set_active_run_log_path(str(log_path))
        with ThreadPoolExecutor(
                max_workers=3, initializer=pool_initializer,
                initargs=(get_log_path(),)) as ex:
            list(ex.map(lambda i: sub.info(f"PARALEL_YARGI_{i}"), range(3)))
    finally:
        _clear_active_run_log_path()
        _teardown_logger(logger)

    text = log_path.read_text(encoding="utf-8")
    missing = [i for i in range(3) if f"PARALEL_YARGI_{i}" not in text]
    assert not missing, f"worker logları run dosyasına düşmedi: {missing}"


def test_without_inheritance_the_logs_are_lost(tmp_path):
    """Regresyon bekçisi: initializer OLMADAN loglar KAYBOLUR (hatanın kendisi)."""
    log_path = tmp_path / "run2.log"
    logger = _setup_logger(log_path)
    sub = logging.getLogger("short_bot.footage_matcher")
    try:
        _set_active_run_log_path(str(log_path))
        with ThreadPoolExecutor(max_workers=2) as ex:   # initializer YOK
            list(ex.map(lambda i: sub.info(f"KAYIP_{i}"), range(2)))
    finally:
        _clear_active_run_log_path()
        _teardown_logger(logger)

    text = log_path.read_text(encoding="utf-8")
    assert "KAYIP_0" not in text, (
        "filtre worker'ı geçiriyor — eşzamanlı koşu izolasyonu bozulmuş olabilir")


def test_pipeline_and_run_context_share_the_same_thread_local(tmp_path):
    """pipeline'ın thread-local'i ile run_context AYNI olmalı — iki ayrı depo olursa
    devralma çalışmaz."""
    _set_active_run_log_path("/x/y.log")
    try:
        assert get_log_path() == "/x/y.log"
    finally:
        _clear_active_run_log_path()
    assert get_log_path() is None
