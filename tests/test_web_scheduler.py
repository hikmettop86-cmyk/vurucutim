from unittest.mock import patch, MagicMock


def test_init_scheduler_registers_jobs(tmp_path):
    from flask import Flask
    from short_bot.web.scheduler import init_scheduler

    app = Flask(__name__)
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "channels" / "demo.yaml").write_text(
        "slug: demo\nname: D\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: '0 * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#fff', bg_gradient: ['#000','#111']}\n"
        "handle: '@d'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    app.config["SHORTBOT_CONFIG_DIR"] = cfg_dir
    app.config["SHORTBOT_DB_PATH"] = tmp_path / "db.sqlite"
    app.config["SHORTBOT_MUSIC_ROOT"] = tmp_path / "music"
    app.config["SHORTBOT_TEMPLATES_DIR"] = tmp_path / "templates"
    app.config["SHORTBOT_CACHE_DIR"] = tmp_path / "cache"
    app.config["SHORTBOT_LOCK_DIR"] = tmp_path / "locks"
    app.config["SHORTBOT_LOGS_DIR"] = tmp_path / "logs"
    app.config["SHORTBOT_SETTINGS"] = MagicMock()

    with patch("short_bot.web.scheduler.BackgroundScheduler") as m_sched:
        instance = MagicMock()
        m_sched.return_value = instance
        scheduler = init_scheduler(app)
    # Should have called add_job at least once for demo channel
    assert instance.add_job.called
    # And once for the reload-jobs interval job
    job_ids = [call.kwargs.get("id") for call in instance.add_job.call_args_list]
    assert "demo" in job_ids
    assert "_reload_jobs" in job_ids
