from korean.config import Settings


def test_linked_model_config_and_explicit_precedence(tmp_path, monkeypatch):
    source = tmp_path / 'provider.env'
    source.write_text(
        'DEEPSEEK_MODEL=linked-model\n'
        'DEEPSEEK_API_KEY=test-linked-secret\n'
        'DEEPSEEK_BASE_URL=https://provider.example/v1\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('RESEARCH_MODEL_ENV_FILE', str(source))
    for key in ('RESEARCH_MODEL', 'OPENAI_API_KEY', 'OPENAI_BASE_URL'):
        monkeypatch.delenv(key, raising=False)
    linked = Settings.env()
    assert (linked.model, linked.api_key, linked.base_url) == (
        'linked-model', 'test-linked-secret', 'https://provider.example/v1'
    )

    monkeypatch.setenv('RESEARCH_MODEL', 'explicit-model')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-explicit-secret')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://explicit.example/v1')
    explicit = Settings.env()
    assert (explicit.model, explicit.api_key, explicit.base_url) == (
        'explicit-model', 'test-explicit-secret', 'https://explicit.example/v1'
    )
