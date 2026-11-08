from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from olymp_domain.diplomas import CAMPAIGN_YEAR, DIPLOMA_YEARS
from olymp_domain.ege import SUBJECTS
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import data_version, get_session
from olymp_api.max_auth import MaxUser, max_user
from olymp_api.redis_support import cache_get, cache_set

from . import service
from .schemas import AchievementsMatch, DiplomaForm, MaxConfig, MyDiplomas, MyDiplomasUpdate

router = APIRouter(tags=["achievements"])

EGE_HELP = (
    "Баллы ЕГЭ «предмет:балл», повторяемый: ege=inf:82&ege=math:90. Предметы: "
    + ", ".join(SUBJECTS)
    + ". С баллами у строк есть статус подтверждения льготы, в итогах — сводка ege."
)

DIPLOMA_HELP = (
    "Диплом: ключ олимпиады, ключ профиля (- — не указан), степень (w — победитель, "
    "p — призёр), класс (0 — не указан) и год олимпиады (0 — не указан), например "
    "«высшаяпроба.математика.w.11.2025». Ключи отдаёт /v1/achievements/olympiads/{id}."
)


def parse_scores(values: list[str]) -> dict[str, int]:
    """«inf:82» → {"inf": 82}; неизвестный предмет или балл вне 0–100 — 422."""
    scores: dict[str, int] = {}
    for value in values:
        subject, _, score = value.partition(":")
        if subject not in SUBJECTS or not score.isdigit() or not 0 <= int(score) <= 100:
            raise HTTPException(422, f"Неверный балл ЕГЭ: {value[:20]}")
        scores[subject] = int(score)
    return scores


@router.get("/achievements/olympiads/{olympiad_id}", response_model=DiplomaForm)
async def diploma_form(olympiad_id: int, session: AsyncSession = Depends(get_session)) -> Any:
    """Олимпиада для формы диплома: ключ и профили без мусора разбора таблиц."""
    return await service.diploma_form(session, olympiad_id)


@router.get("/achievements/match", response_model=AchievementsMatch)
async def match(
    request: Request,
    diploma: list[str] = Query(..., description=DIPLOMA_HELP),
    benefit_type: str | None = None,
    university_id: int | None = None,
    ege: list[str] = Query(
        [],
        description=EGE_HELP,
    ),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """«Мои дипломы»: где дипломы дают льготы с учётом условий вуза — степени диплома,
    класса и года олимпиады. Список вузов, а с university_id — строки выбранного вуза."""
    specs = service.parse_specs(diploma)
    scores = parse_scores(ege)
    if scores:
        # баллы ЕГЭ — личные данные: ответ с ними не кладём в общий кэш
        data = AchievementsMatch.model_validate(
            await service.match_diplomas(session, specs, benefit_type, university_id, scores)
        )
        return data.model_dump(mode="json")
    key = ":".join(
        str(part)
        for part in (
            "v1:achievements",
            await data_version(session),
            ",".join(map(str, specs)),
            benefit_type,
            university_id,
        )
    )
    if (hit := await cache_get(request, key)) is not None:
        return hit
    data = AchievementsMatch.model_validate(
        await service.match_diplomas(session, specs, benefit_type, university_id)
    )
    payload = data.model_dump(mode="json")
    await cache_set(request, key, payload, request.app.state.settings.cache_ttl)
    return payload


@router.get("/max/config", response_model=MaxConfig)
async def max_config(request: Request) -> Any:
    """Настроен ли вход через MAX и как называется бот мини-приложения."""
    settings = request.app.state.settings
    return {
        "enabled": bool(settings.max_bot_token),
        "bot_name": settings.max_bot_name or None,
        "campaign_year": CAMPAIGN_YEAR,
        "valid_years": list(DIPLOMA_YEARS),
    }


@router.get("/me/diplomas", response_model=MyDiplomas)
async def my_diplomas(
    user: MaxUser = Depends(max_user), session: AsyncSession = Depends(get_session)
) -> Any:
    """Дипломы пользователя MAX. Нужен заголовок X-Max-Init-Data — данные запуска
    мини-приложения, подписанные токеном бота."""
    return await service.my_diplomas(session, user)


@router.put("/me/diplomas", response_model=MyDiplomas)
async def save_my_diplomas(
    body: MyDiplomasUpdate,
    user: MaxUser = Depends(max_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Сохраняет список дипломов пользователя MAX целиком; баллы ЕГЭ — если переданы
    (без поля ege сохранённые баллы не меняются)."""
    ege = {str(k): v for k, v in body.ege.items()} if body.ege is not None else None
    specs = service.parse_specs(body.diplomas)
    return await service.save_my_diplomas(session, user, specs, ege, body.ege_is_mock)
