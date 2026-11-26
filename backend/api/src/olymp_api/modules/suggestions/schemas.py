from typing import Annotated, Literal

from pydantic import BaseModel, Field

from olymp_api.schemas import ResponseModel


class SuggestionIn(BaseModel):
    """Ссылка на страницу или документ вуза с олимпиадными льготами."""

    url: Annotated[str, Field(min_length=8, max_length=2000)]
    university: Annotated[str, Field(min_length=2, max_length=300)]
    comment: Annotated[str, Field(max_length=500)] = ""


class SuggestionCreated(ResponseModel):
    # created — взяли в проверку, exists — такая ссылка у нас уже есть
    status: Literal["created", "exists"]
