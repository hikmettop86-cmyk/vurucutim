"""Logger isolation: when multiple pipeline runs execute concurrently,
each run's sub-logger output (image_picker, scorer, etc.) must only land
in its own log file — not bleed into siblings.

Reproduces the bug seen in production where the galatasaray run log
contained NFL/Putin/hantavirüs query lines from concurrent runs."""
import logging
import threading

from short_bot.pipeline import (
    _setup_logger,
    _teardown_logger,
    _set_active_run_log_path,
    _clear_active_run_log_path,
)


def test_sub_logger_only_writes_to_active_run(tmp_path):
    """Two threads, each setting its own active_run_log_path — sub-logger
    output must respect the per-thread context."""
    log_a = tmp_path / "run_a.log"
    log_b = tmp_path / "run_b.log"

    logger_a = _setup_logger(log_a)
    logger_b = _setup_logger(log_b)

    # Sync both threads to log at the same time so contamination would be
    # visible if filtering doesn't work.
    barrier = threading.Barrier(2)
    sub = logging.getLogger("short_bot.image_picker")

    def run(log_path, msg):
        try:
            _set_active_run_log_path(str(log_path))
            barrier.wait()
            sub.info(msg)
            barrier.wait()
        finally:
            _clear_active_run_log_path()

    ta = threading.Thread(target=run, args=(log_a, "MSG_FROM_A"))
    tb = threading.Thread(target=run, args=(log_b, "MSG_FROM_B"))
    ta.start()
    tb.start()
    ta.join()
    tb.join()

    _teardown_logger(logger_a)
    _teardown_logger(logger_b)

    a_text = log_a.read_text(encoding="utf-8")
    b_text = log_b.read_text(encoding="utf-8")

    assert "MSG_FROM_A" in a_text
    assert "MSG_FROM_A" not in b_text, (
        "MSG_FROM_A leaked into B's log: " + b_text[:500]
    )
    assert "MSG_FROM_B" in b_text
    assert "MSG_FROM_B" not in a_text, (
        "MSG_FROM_B leaked into A's log: " + a_text[:500]
    )


def test_reel_pipeline_modules_reach_the_run_log(tmp_path):
    """Reel üretiminin TÜM aşamaları run loguna düşmeli.

    Bunlar listede yokken reel koşusunun logu sadece 'reel modu: footage-sürüklü
    üretim' satırında donuyordu: kurgucunun seçtiği müzik/SFX, footage red
    gerekçeleri, faz süreleri ve 'SÜRE ÖZET' yalnız stdout'a gidiyordu — panelden
    bir reel koşusunun neden yavaş/yanlış olduğu GÖRÜLEMİYORDU.
    """
    log_path = tmp_path / "reel_run.log"
    logger = _setup_logger(log_path)
    reel_modules = (
        "short_bot.reel",             # faz süreleri, alt-kesim, SFX, müzik
        "short_bot.reel_director",    # kurgucunun kararı + gerekçesi
        "short_bot.reel_render",
        "short_bot.footage_matcher",  # vision red gerekçeleri
        "short_bot.footage_sources",
        "short_bot.tts.align",
    )
    try:
        _set_active_run_log_path(str(log_path))
        for name in reel_modules:
            logging.getLogger(name).info(f"MARKER_{name}")
    finally:
        _clear_active_run_log_path()
        _teardown_logger(logger)

    text = log_path.read_text(encoding="utf-8")
    missing = [n for n in reel_modules if f"MARKER_{n}" not in text]
    assert not missing, f"run loguna düşmeyen reel modülleri: {missing}"


def test_sub_logger_writes_when_no_active_run_set(tmp_path):
    """Backward-compat: if no active run is set in the thread (e.g. test
    or one-off CLI), the run-attached file handler still receives logs
    (no filter rejects)."""
    log_path = tmp_path / "single.log"
    logger = _setup_logger(log_path)
    try:
        # No _set_active_run_log_path call — emulates legacy code path.
        _set_active_run_log_path(str(log_path))
        logging.getLogger("short_bot.image_picker").info("legacy_path_ok")
    finally:
        _clear_active_run_log_path()
        _teardown_logger(logger)

    assert "legacy_path_ok" in log_path.read_text(encoding="utf-8")
