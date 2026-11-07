"""Стабильные ключи вуза и направления для ссылок «Поделиться» (F-01).

id в базе меняются при каждой пересборке, а названия из таблицы — нет. Поэтому ссылка
хранит ключ из названий: вуз, направление, профиль программы и коды направлений. Ключ
считается из полей направления на лету, отдельной колонки в базе нет — значит, нечего
заполнять при обновлении стенда, и пересборка не может ключ «потерять».
"""

import re

from .textutils import squash

RE_CODE = re.compile(r"\d{2}\.\d{2}\.\d{2}")


def university_key(name: str) -> str:
    """Ключ вуза — squash полного названия (оно уникально в справочнике)."""
    return squash(name)


def program_stable_key(university_name: str, name: str, profile: str = "", code: str = "") -> str:
    """Ключ направления: «вуз|направление|профиль|коды».

    Коды берутся и из названия, и из колонки кода: у части вузов название направления —
    это и есть перечень кодов («09.03.01, 09.03.04»), тогда squash названия пустой.
    """
    codes = sorted(set(RE_CODE.findall(name)) | set(RE_CODE.findall(code)))
    return "|".join(
        (
            university_key(university_name),
            squash(RE_CODE.sub(" ", name)),
            squash(profile),
            ",".join(codes),
        )
    )


def university_of_key(key: str) -> str:
    """Ключ вуза, которому принадлежит ключ направления."""
    return key.split("|", 1)[0]
