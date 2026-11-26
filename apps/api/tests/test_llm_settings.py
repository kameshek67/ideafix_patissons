import pytest
from olymp_api.llm import OpenAICompatibleProvider, make_provider, provider_name
from olymp_api.settings import Settings


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"llm_base_url": "https://x/v1", "llm_model": "m"},
        {"llm_base_url": "https://x/v1", "llm_api_key": "k"},
        {
            "llm_base_url": "https://x/v1",
            "llm_api_key": "k",
            "llm_model": "m",
            "llm_enabled": False,
        },
    ],
)
def test_provider_is_off_without_settings(overrides: dict[str, object]) -> None:
    assert make_provider(Settings(_env_file=None, **overrides)) is None


def test_provider_is_on_with_settings() -> None:
    settings = Settings(_env_file=None, llm_base_url="https://x/v1", llm_api_key="k", llm_model="m")
    assert make_provider(settings) is not None


def test_settings_pass_low_temperature() -> None:
    settings = Settings(_env_file=None, llm_base_url="https://x/v1", llm_api_key="k", llm_model="m")
    p = make_provider(settings)
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.temperature == 0.2
    assert p.top_p is None


def test_eval_picks_profile_and_model() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://x/v1",
        llm_api_key="k",
        llm_model="main",
        llm_fallback_model="spare",
        llm_profiles={
            "giga": {"base_url": "https://giga/v1", "api_key": "g", "model": "gm", "price_in": 1.5}
        },
    )
    default = make_provider(settings)
    assert isinstance(default, OpenAICompatibleProvider) and default.models == ["main", "spare"]
    chosen = make_provider(settings, profile="giga", include_usage=True)
    assert isinstance(chosen, OpenAICompatibleProvider)
    assert (chosen.url, chosen.models, chosen.include_usage) == (
        "https://giga/v1/chat/completions",
        ["gm"],
        True,
    )
    # подмена модели в отчёте — одна модель, без резервной
    swapped = make_provider(settings, model="other")
    assert isinstance(swapped, OpenAICompatibleProvider) and swapped.models == ["other"]
    assert make_provider(settings, profile="нет такого") is None
    assert provider_name(settings, "giga") == "giga"
    assert provider_name(settings) == "x"
    assert settings.llm_profiles["giga"].price_in == 1.5
