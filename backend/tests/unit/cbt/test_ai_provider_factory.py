"""Factory selection and resolver wiring without external provider calls."""

import pytest

from app.modules.cbt.ai.authoring.providers import factory


@pytest.fixture(autouse=True)
def optional_credentials(monkeypatch):
    for name in (
        "GEMINI_API_KEY",
        "MINIMAX_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.setattr(factory.settings, name, None)


@pytest.mark.parametrize("name", ["gemini", "minimax", "openrouter"])
def test_question_and_evaluation_selection(monkeypatch, name):
    monkeypatch.setattr(factory.settings, "CBT_AI_QUESTION_PROVIDER", name)
    monkeypatch.setattr(factory.settings, "CBT_AI_IMAGE_EVALUATION_PROVIDER", name)
    monkeypatch.setattr(
        factory.settings, "CBT_AI_IMAGE_PROVIDER", "minimax" if name == "gemini" else "gemini"
    )
    question = factory.CBTProviderFactory.get_question_provider()
    evaluation = factory.CBTProviderFactory.get_image_evaluation_provider()
    assert isinstance(question, factory.BaseQuestionGenerationProvider)
    assert isinstance(evaluation, factory.BaseImageEvaluationProvider)
    assert question.provider_name == evaluation.provider_name == name
    assert not question.is_configured()


@pytest.mark.parametrize("name", ["gemini", "minimax", "openrouter"])
def test_image_generation_selection(monkeypatch, name):
    monkeypatch.setattr(factory.settings, "CBT_AI_IMAGE_PROVIDER", name)
    result = factory.CBTProviderFactory.get_image_generation_provider()
    assert isinstance(result, factory.BaseImageGenerationProvider)
    assert result.provider_name == name


def test_search_selection(monkeypatch):
    monkeypatch.setattr(factory.settings, "CBT_AI_IMAGE_SEARCH_PROVIDER", "ddgs")
    result = factory.CBTProviderFactory.get_image_search_provider()
    assert isinstance(result, factory.BaseImageSearchProvider)
    assert result.is_configured()


@pytest.mark.parametrize(
    "setting,method",
    [
        ("CBT_AI_QUESTION_PROVIDER", "get_question_provider"),
        ("CBT_AI_IMAGE_EVALUATION_PROVIDER", "get_image_evaluation_provider"),
        ("CBT_AI_IMAGE_PROVIDER", "get_image_generation_provider"),
        ("CBT_AI_IMAGE_SEARCH_PROVIDER", "get_image_search_provider"),
    ],
)
def test_unsupported_provider(monkeypatch, setting, method):
    monkeypatch.setattr(factory.settings, setting, "unsupported")
    with pytest.raises(factory.CBTProviderFactoryError, match="Unsupported CBT AI"):
        getattr(factory.CBTProviderFactory, method)()


def test_resolver_wiring_forces_qwen_and_skips_search_and_vision(monkeypatch):
    # Legacy provider configuration must not cause a fallback to Gemini.
    monkeypatch.setattr(factory.settings, "CBT_AI_IMAGE_PROVIDER", "minimax")
    monkeypatch.setattr(factory.settings, "CBT_AI_IMAGE_EVALUATION_PROVIDER", "gemini")
    monkeypatch.setattr(factory.settings, "CBT_AI_IMAGE_SEARCH_PROVIDER", "ddgs")

    result = factory.CBTProviderFactory.get_image_resolver()

    assert isinstance(result, factory.GenerationOnlyImageResolver)
    assert isinstance(result.generation_provider, factory.OpenRouterImageGenerationProvider)
    assert not hasattr(result, "search_provider")
    assert not hasattr(result, "evaluation_provider")


def test_resolver_never_invokes_old_provider_selectors():
    class SearchDisabledFactory(factory.CBTProviderFactory):
        @staticmethod
        def get_image_search_provider():
            raise AssertionError("DDGS image search must not be invoked")

        @staticmethod
        def get_image_evaluation_provider():
            raise AssertionError("Qwen Vision image evaluation must not be invoked")

        @staticmethod
        def get_image_generation_provider():
            raise AssertionError("No fallback image provider selection permitted")

    assert isinstance(
        SearchDisabledFactory.get_image_resolver(),
        factory.GenerationOnlyImageResolver,
    )
