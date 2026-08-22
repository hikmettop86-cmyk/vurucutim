"""/output/<file> route must return 200 + video/mp4 for existing mp4 files."""
from pathlib import Path

from short_bot.web import create_app


def test_output_route_serves_existing_mp4(tmp_path):
    """Regression: relative output_root caused send_from_directory to look under
    app.root_path (src/short_bot/web/output), not project cwd."""
    # Build a minimal output tree with a fake mp4
    (tmp_path / "output" / "ch").mkdir(parents=True)
    (tmp_path / "output" / "ch" / "v.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
    (tmp_path / "config" / "channels").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text(
        "claude_cli_path: claude\n"
        "ffmpeg_path: ffmpeg\n"
        "playwright_browser: chromium\n"
        "web_host: 127.0.0.1\n"
        "web_port: 5005\n"
        "fuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\n"
        "claude_models:\n  default: haiku\n  dna: opus\n",
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "assets" / "music").mkdir(parents=True)
    (tmp_path / "logs" / "runs").mkdir(parents=True)
    (tmp_path / "data" / "cache").mkdir()
    (tmp_path / "data" / "locks").mkdir()

    app = create_app(
        config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "short_bot.sqlite",
        templates_dir=tmp_path / "templates",
        music_root=tmp_path / "assets" / "music",
        cache_dir=tmp_path / "data" / "cache",
        lock_dir=tmp_path / "data" / "locks",
        logs_dir=tmp_path / "logs" / "runs",
        output_root=tmp_path / "output",   # absolute
        scheduler=False,
    )

    client = app.test_client()
    resp = client.get("/output/ch/v.mp4")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert resp.headers["Content-Type"] == "video/mp4"


def test_output_route_serves_with_relative_output_root():
    """The defaults (config_dir='config', output_root='output') are RELATIVE.
    Verify the route still works when caller passes a relative path."""
    # Use a relative output_root pointing to the real project tree
    app = create_app(scheduler=False, output_root="output")
    client = app.test_client()
    # Pick any existing mp4 from the real tree
    real_outputs = list(Path("output").rglob("*.mp4"))
    if not real_outputs:
        import pytest
        pytest.skip("no real mp4 files to test against")
    rel = real_outputs[0].relative_to("output").as_posix()
    resp = client.get(f"/output/{rel}")
    assert resp.status_code == 200, f"relative output_root broke: {resp.status_code}"
