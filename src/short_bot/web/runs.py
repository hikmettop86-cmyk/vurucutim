"""Threaded pipeline runner — launches pipeline.run_pipeline in a daemon thread."""
import threading
from pathlib import Path

from short_bot.pipeline import run_pipeline


def launch_pipeline(*, channel, settings, db_path: Path,
                    music_root: Path, templates_dir: Path,
                    cache_dir: Path, lock_dir: Path, logs_dir: Path,
                    trigger: str = "manual") -> threading.Thread:
    """Start pipeline in a daemon thread. Returns the thread object."""
    def _runner():
        try:
            run_pipeline(
                channel=channel, settings=settings,
                db_path=db_path, music_root=music_root,
                templates_dir=templates_dir,
                cache_dir=cache_dir, lock_dir=lock_dir,
                logs_dir=logs_dir, trigger=trigger,
            )
        except Exception:
            # Already logged inside pipeline. Swallow to keep daemon thread alive.
            pass

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread
