import pytest
from olymp_api.llm import OpenAICompatibleProvider, make_provider
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
