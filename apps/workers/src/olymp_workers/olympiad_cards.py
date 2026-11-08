"""Загрузка карточек олимпиад из data/olympiad_cards.json (T-082).

Вызывается из olymp-ingest в той же транзакции, что и остальная сборка. Файл лежит в
репозитории и проходит ревью, поэтому олимпиада или профиль, которых нет в базе, останавливают
сборку с понятным сообщением, а не теряются молча.
"""

from pathlib import Path
from typing import Any

import psycopg
from olymp_domain import squash
from olymp_domain.olympiad_cards import CardError, load_cards

CARDS_FILE = "olympiad_cards.json"


def load_olympiad_cards(conn: psycopg.Connection[Any], data_dir: Path) -> dict[str, int]:
    """Заполняет olympiad_info и olympiad_tracks. Таблицы к этому моменту очищены."""
    path = data_dir / CARDS_FILE
    cards = load_cards(path)
    olympiads = {
        name: oid for oid, name in conn.execute("SELECT id, canonical_name FROM olympiads")
    }
    tracks = 0
    for card in cards:
        where = f"{CARDS_FILE}, «{card.olympiad}»"
        olympiad_id = olympiads.get(card.olympiad)
        if olympiad_id is None:
            raise CardError(f"{where}: олимпиады с таким canonical_name нет в базе")
        conn.execute(
            """INSERT INTO olympiad_info (olympiad_id, site_url, summary, grades, formats,
                                          stages, source_url, checked)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                olympiad_id,
                card.site_url,
                card.summary,
                card.grades,
                list(card.formats),
                list(card.stages),
                card.source_url,
                card.checked,
            ),
        )
        profiles = {
            key: pid
            for pid, key in conn.execute(
                "SELECT id, squash_key FROM olympiad_profiles WHERE olympiad_id = %s",
                (olympiad_id,),
            )
        }
        for track in card.tracks:
            profile_id = profiles.get(squash(track.profile))
            if profile_id is None:
                raise CardError(
                    f"{where}, трек «{track.name}»: у олимпиады нет профиля «{track.profile}»"
                )
            conn.execute(
                """INSERT INTO olympiad_tracks (olympiad_id, profile_id, name, squash_key,
                                                topics, source_url, checked)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    olympiad_id,
                    profile_id,
                    track.name,
                    squash(track.name),
                    list(track.topics),
                    track.source_url,
                    track.checked,
                ),
            )
            tracks += 1
    return {"cards": len(cards), "tracks": tracks}
