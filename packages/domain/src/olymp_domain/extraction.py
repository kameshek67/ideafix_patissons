"""Единый JSON-формат льгот, извлечённых из документов вузов (docs/plan.md, «Извлечение»).

Файл = документ + записи. Одна запись — одна льгота. Тот же формат у эталона
(data/eval/extraction), у результата извлечения (data/extracted) и у выгрузки из базы.

    uv run python -m olymp_domain.extraction > data/eval/extraction/schema.json

Ключ совпадения записи: (вуз, код направления, олимпиада, профиль, тип льготы) — всё, кроме
кода, в нормализованном виде, поэтому «Высшая проба» и «ВСЕРОССИЙСКАЯ ОЛИМПИАДА ШКОЛЬНИКОВ
«ВЫСШАЯ ПРОБА»» — одна и та же олимпиада.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .ege import SUBJECTS
from .olympiad_seeds import SEEDS
from .textutils import clean_profile, squash
from .verify import normalize

BenefitType = Literal["bvi", "100", "extra_points"]
WinnerRole = Literal["winner", "prizewinner", "both"]

SCHEMA_FILE = "schema.json"
RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _norm_sha(value: str) -> str:
    value = value.strip().lower()
    if not RE_SHA256.match(value):
        raise ValueError("sha256 — ровно 64 шестнадцатеричных символа")
    return value


class _Model(BaseModel):
    # опечатка в имени поля — ошибка, а не молча потерянные данные
    model_config = ConfigDict(extra="forbid")


class Document(_Model):
    university: str = Field(min_length=1, description="Вуз, как он назван в документе")
    campaign: int = Field(ge=2020, le=2040, description="Год приёмной кампании, например 2027")
    url: str = Field(min_length=1, description="Адрес документа")
    sha256: str = Field(description="SHA-256 файла документа, 64 шестнадцатеричных символа")
    title: str = Field(default="", description="Название документа")
    pages: list[Annotated[int, Field(ge=1)]] = Field(
        default_factory=list,
        description="Номера размеченных страниц с единицы; у HTML-страницы — [1]. "
        "В эталоне обязательны: на остальных страницах предсказания не штрафуются",
    )

    @field_validator("sha256")
    @classmethod
    def _sha(cls, value: str) -> str:
        return _norm_sha(value)

    @field_validator("pages")
    @classmethod
    def _pages(cls, value: list[int]) -> list[int]:
        return sorted(set(value))


class Ege(_Model):
    subjects: list[str] = Field(
        default_factory=list,
        description="Коды предметов ЕГЭ для подтверждения: " + ", ".join(SUBJECTS),
    )
    min: int | None = Field(default=None, ge=0, le=100, description="Минимальный балл ЕГЭ")

    @field_validator("subjects")
    @classmethod
    def _subjects(cls, value: list[str]) -> list[str]:
        unknown = [s for s in value if s not in SUBJECTS]
        if unknown:
            raise ValueError(f"неизвестные коды предметов: {unknown}; допустимы {list(SUBJECTS)}")
        return list(dict.fromkeys(value))


class Source(_Model):
    url: str = Field(min_length=1, description="Адрес документа (как в document.url)")
    sha256: str = Field(description="SHA-256 документа (как в document.sha256)")
    page: int = Field(ge=1, description="Страница документа с единицы")
    quote: str = Field(
        min_length=1,
        description="Дословная цитата со страницы, из которой видна запись (строка таблицы или "
        "абзац); пробелы, переносы и кавычки при проверке не важны",
    )

    @field_validator("sha256")
    @classmethod
    def _sha(cls, value: str) -> str:
        return _norm_sha(value)


class Record(_Model):
    university: str = Field(min_length=1)
    campaign: int = Field(ge=2020, le=2040)
    program_code: str = Field(min_length=1, description="Код направления, например 01.03.02")
    program_name: str = Field(default="", description="Название направления")
    benefit_type: BenefitType = Field(
        description="bvi — без вступительных; 100 — 100 баллов; extra_points — баллы за ИД"
    )
    olympiad: str = Field(min_length=1, description="Название олимпиады, как в документе")
    profile: str = Field(default="", description="Профиль олимпиады; пусто, если не указан")
    levels: list[Annotated[int, Field(ge=1, le=3)]] = Field(
        default_factory=list, description="Уровни олимпиады из перечня: 1, 2, 3; пусто — не указан"
    )
    winner_role: WinnerRole | None = Field(
        default=None,
        description="winner — победители, prizewinner — призёры, both — и те и другие; "
        "null — в документе не сказано (пустое значение лучше догадки)",
    )
    grades: list[Annotated[int, Field(ge=1, le=11)]] = Field(
        default_factory=list, description="Классы диплома; пусто — не указаны"
    )
    ege: Ege | None = Field(default=None, description="Подтверждение ЕГЭ; null — не требуется")
    source: Source
    note: str = Field(default="", description="Оговорки документа, которые не влезли в поля")

    @field_validator("program_code", "olympiad")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("пустое значение")
        return value

    @field_validator("levels", "grades")
    @classmethod
    def _sorted(cls, value: list[int]) -> list[int]:
        return sorted(set(value))


class ExtractionFile(_Model):
    document: Document
    records: list[Record]

    @model_validator(mode="after")
    def _consistent(self) -> ExtractionFile:
        doc = self.document
        for i, rec in enumerate(self.records):
            where = f"records[{i}] ({rec.program_code} {rec.olympiad})"
            if rec.university != doc.university or rec.campaign != doc.campaign:
                raise ValueError(f"{where}: вуз или кампания не совпадают с document")
            if rec.source.url != doc.url or rec.source.sha256 != doc.sha256:
                raise ValueError(f"{where}: source.url и source.sha256 должны быть как в document")
            if doc.pages and rec.source.page not in doc.pages:
                raise ValueError(
                    f"{where}: страница {rec.source.page} не входит в document.pages {doc.pages}"
                )
        return self


# ---------------------------------------------------------------- ключ совпадения


@cache
def _seed_index() -> tuple[
    dict[str, str], list[tuple[str, tuple[tuple[str, ...], ...], tuple[str, ...]]]
]:
    aliases: dict[str, str] = {}
    patterns = []
    for seed in SEEDS:
        key = squash(seed.short)
        for alias in (seed.short, seed.full, *seed.aliases):
            aliases.setdefault(squash(alias), key)
        patterns.append(
            (key, tuple(tuple(p) for p in seed.patterns), tuple(seed.exclude)),
        )
    return aliases, patterns


def olympiad_key(name: str) -> str:
    """Устойчивый ключ олимпиады: справочник (якоря и алиасы), иначе squash названия."""
    sq = squash(name)
    aliases, patterns = _seed_index()
    if sq in aliases:
        return aliases[sq]
    for key, pattern_sets, exclude in patterns:
        if any(bad in sq for bad in exclude):
            continue
        if any(all(p in sq for p in pset) for pset in pattern_sets):
            return key
    return sq


def profile_key(profile: str) -> str:
    return squash(clean_profile(profile))


def record_key(record: Record) -> tuple[str, str, str, str, str]:
    return (
        squash(record.university),
        record.program_code.strip(),
        olympiad_key(record.olympiad),
        profile_key(record.profile),
        record.benefit_type,
    )


def quote_found(quote: str, page_text: str) -> bool:
    """Цитата есть на странице с точностью до пробелов, переносов, кавычек и регистра."""
    key = normalize(quote)
    return bool(key) and key in normalize(page_text)


# ---------------------------------------------------------------- файлы


class ExtractionError(ValueError):
    """Файл не разобран или не прошёл проверку; текст — что и где не так."""


def load_file(path: Path) -> ExtractionFile:
    try:
        return ExtractionFile.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExtractionError(f"{path}: {exc.strerror}") from None
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        more = len(exc.errors()) - 5
        raise ExtractionError(
            f"{path}: {details}" + (f" (и ещё {more})" if more > 0 else "")
        ) from None


def load_dir(directory: Path) -> dict[str, ExtractionFile]:
    """Все *.json каталога (кроме schema.json) по имени файла без расширения.

    Ошибки собираются по всем файлам и поднимаются одним исключением."""
    if not directory.is_dir():
        raise ExtractionError(f"{directory}: нет такого каталога")
    files: dict[str, ExtractionFile] = {}
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")):
        if path.name == SCHEMA_FILE:
            continue
        try:
            files[path.stem] = load_file(path)
        except ExtractionError as exc:
            errors.append(str(exc))
    if errors:
        raise ExtractionError("\n".join(errors))
    return files


def json_schema() -> dict[str, object]:
    return ExtractionFile.model_json_schema()


def schema_text() -> str:
    return json.dumps(json_schema(), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    print(schema_text(), end="")
