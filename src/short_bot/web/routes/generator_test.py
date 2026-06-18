"""POST /channels/<slug>/generator-test — preview generator output without persisting."""
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template

from short_bot.config import load_channel, resolve_ai_call
from short_bot.db import init_db
from short_bot.generated_db import recent_generated_texts, topic_distribution
from short_bot.generator import generate_quote
from short_bot.pexels import load_secrets as _load_secrets

bp = Blueprint("generator_test", __name__)


@bp.route("/channels/<slug>/generator-test", methods=["POST"])
def test(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    cfg = load_channel(cfg_path)
    if cfg.content_source != "generator" or cfg.generator is None:
        abort(400, description="Test üret sadece generator kanallarında çalışır.")

    settings = current_app.config["SHORTBOT_SETTINGS"]
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    forbidden = recent_generated_texts(eng, slug,
                                        limit=cfg.generator.forbidden_lookback)
    topic_dist = topic_distribution(eng, slug, days=7)
    eng.dispose()

    # Resolve the active AI backend (claude_cli default; openrouter when configured).
    # In claude_cli mode keep the existing channel-aware model precedence
    # (channel.script_model wins) — same as pipeline._run_generator.
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    secrets = _load_secrets(Path(secrets_path)) if secrets_path else {}
    call = resolve_ai_call(settings, secrets, "default")
    if call.backend == "claude_cli":
        model = (cfg.script_model
                 or settings.claude_models.get("default", "sonnet"))
    else:
        model = call.model

    try:
        result = generate_quote(
            channel=cfg, dna=cfg.dna,
            forbidden_texts=forbidden, topic_distribution=topic_dist,
            claude_path=call.claude_path,
            model=model,
            backend=call.backend,
            api_key=call.api_key,
        )
    except Exception as e:
        return render_template(
            "_partials/generator_test_result.html.j2",
            error=str(e), result=None,
        )
    return render_template(
        "_partials/generator_test_result.html.j2",
        error=None, result=result,
    )
