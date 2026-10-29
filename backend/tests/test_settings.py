from local_rag.settings import Settings


def test_default_answer_model_and_tokenizer_match(monkeypatch, tmp_path):
    monkeypatch.setattr('local_rag.settings.ROOT', tmp_path)
    for key in ['LLM_MODEL', 'LLM_TOKENIZER_MODEL', 'RETRIEVAL_CAP']:
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.llm_model == 'lfm3:1.7b'
    assert settings.llm_tokenizer_model == 'LiquidAI/LFM3-1.7B'
    assert settings.retrieval_cap == 3


def test_other_answer_models_require_their_own_tokenizer_and_preserve_cap(monkeypatch, tmp_path):
    monkeypatch.setattr('local_rag.settings.ROOT', tmp_path)
    monkeypatch.setenv('LLM_MODEL', 'user-selected-model')
    monkeypatch.delenv('LLM_TOKENIZER_MODEL', raising=False)
    monkeypatch.setenv('RETRIEVAL_CAP', '7')
    settings = Settings.from_env()
    assert settings.llm_model == 'user-selected-model'
    assert settings.llm_tokenizer_model == ''
    assert settings.retrieval_cap == 7
    monkeypatch.setenv('LLM_TOKENIZER_MODEL', 'user/verified-tokenizer')
    assert Settings.from_env().llm_tokenizer_model == 'user/verified-tokenizer'
