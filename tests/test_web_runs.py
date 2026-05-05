from unittest.mock import patch, MagicMock

from short_bot.web.runs import launch_pipeline


def test_launch_pipeline_starts_thread(tmp_path):
    fake_settings = MagicMock()
    fake_channel = MagicMock()
    fake_channel.slug = "test"

    with patch("short_bot.web.runs.run_pipeline") as m_run:
        m_run.return_value = MagicMock(run_id=42, status="success", short_path=None, error=None)
        thread = launch_pipeline(
            channel=fake_channel, settings=fake_settings,
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path / "music",
            templates_dir=tmp_path / "templates",
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks",
            logs_dir=tmp_path / "logs",
            trigger="manual",
        )
    # Thread runs in background — wait for it
    thread.join(timeout=5)
    assert m_run.called
    assert m_run.call_args.kwargs["channel"] is fake_channel
    assert m_run.call_args.kwargs["trigger"] == "manual"
