"""Threaded pipeline runner — launches pipeline.run_pipeline in a daemon thread."""
import logging
import threading
from pathlib import Path

from short_bot.pipeline import run_pipeline

_log = logging.getLogger("short_bot.web.runs")


def launch_pipeline(*, channel, settings, db_path: Path,
                    music_root: Path, templates_dir: Path,
                    cache_dir: Path, lock_dir: Path, logs_dir: Path,
                    trigger: str = "manual",
                    preselected_item=None) -> threading.Thread:
    """Start pipeline in a daemon thread. Returns the thread object."""
    def _runner():
        try:
            run_pipeline(
                channel=channel, settings=settings,
                db_path=db_path, music_root=music_root,
                templates_dir=templates_dir,
                cache_dir=cache_dir, lock_dir=lock_dir,
                logs_dir=logs_dir, trigger=trigger,
                preselected_item=preselected_item,
            )
        except Exception:
            # Pipeline already records its own DB row + per-run log on internal
            # failures. Anything reaching here is a top-level surprise (lock
            # dir missing, init_db failure). Log to console so it isn't lost.
            _log.exception("launch_pipeline thread crashed for %s", channel.slug)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread
