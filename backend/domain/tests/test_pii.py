import pytest
from olymp_domain.pii import mask_personal_data


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("пиши на vasya.ivanov@mail.ru", "пиши на [email]"),
        ("мой телефон +7 (916) 123-45-67", "мой телефон [телефон]"),
        ("звони 89161234567!", "звони [телефон]!"),
        ("я в vk.com/vasya2009", "я в [контакт]"),
        ("мой ник @vasya_2009", "мой ник [контакт]"),
        ("Меня зовут Вася Иванов, 10 класс", "Меня зовут [имя], 10 класс"),
        ("моё имя Анна-Мария", "моё имя [имя]"),
        ("Привет, я Вася Иванов", "Привет, я [имя]"),
        ("учусь в школе № 57", "учусь в [школа]"),
        ("ученик лицея 239", "ученик [школа]"),
        ("я из 57-й школы", "я из [школа]"),
    ],
)
def test_masks_personal_data(text: str, expected: str) -> None:
    assert mask_personal_data(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "10 класс, призёр НТО 2025 года",
        "ЕГЭ: математика 85, информатика 90, русский 78",
        "Всероссийская олимпиада школьников по физике",
        "хочу в ВШЭ на ПМИ, профиль 01.03.02",
        "я Призёр",
        "ищу олимпиады для школы",
    ],
)
def test_keeps_ordinary_text(text: str) -> None:
    assert mask_personal_data(text) == text
