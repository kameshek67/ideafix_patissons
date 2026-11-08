"""Поддельный провайдер для тестов API: живёт в olymp_llm, путь сохранён для старых импортов."""

from olymp_llm.fake import FakeProvider

__all__ = ["FakeProvider"]
