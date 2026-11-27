from app.config import Settings


def test_blank_env_lines_use_defaults(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=x\nMTA_PROVIDER=\nMTA_MODEL=\nMTA_MAX_CALLS=\n")
    s = Settings(_env_file=env)
    assert (s.provider, s.model, s.max_calls) == ("synthetic", "claude-sonnet-5-5", 10)
