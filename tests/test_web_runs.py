import pytest
from unittest.mock import patch, MagicMock

from short_bot.web import create_app
from short_bot.web.runs import launch_pipeline


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo-tr.yaml").write_text(
        "slug: demo-tr\nname: Demo TR\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: '0 * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}\n"
        "handle: '@demo'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite", scheduler=False)


def test_shorts_run_now_starts_pipeline(app):
    """POST /shorts/run-now calls launch_pipeline with the requested channel."""
    client = app.test_client()
    with patch("short_bot.web.routes.shorts.launch_pipeline") as mock_launch:
        mock_thread = MagicMock()
        mock_launch.return_value = mock_thread
        resp = client.post("/shorts/run-now", data={"slug": "demo-tr"})
    assert resp.status_code == 200
    assert mock_launch.called
    call_kwargs = mock_launch.call_args.kwargs
    assert call_kwargs["channel"].slug == "demo-tr"
    assert call_kwargs["trigger"] == "manual"


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
