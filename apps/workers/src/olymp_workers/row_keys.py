"""Стабильный ключ строки льготы.

id льготы — порядковый номер сборки и сдвигается при любой правке разбора. Ключ строки
считается от смысловых полей, поэтому по нему видно, какая именно строка выдачи появилась,
исчезла или поменялась.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

KEY_LENGTH = 12
_SEP = "\x1f"


@dataclass(frozen=True)
class RowFields:
    """Смысловые поля строки льготы.

    olympiads — канонические ключи олимпиад строки. tiebreak — остальное содержимое строки:
    по нему упорядочиваются строки с совпавшим ключом, чтобы суффикс не зависел от id.
    """

    id: int
    university: str
    program_code: str
    program_name: str
    benefit_type: str
    layer: str
    olympiads: Sequence[str]
    profile: str
    level: str
    role: str
    grade: str
    ege_subject: str
    ege_min: str
    source: str
    tiebreak: Sequence[str] = ()

    def base_key(self) -> str:
        parts = [
            self.university,
            self.program_code,
            self.program_name,
            self.benefit_type,
            self.layer,
            "|".join(sorted(set(self.olympiads))),
            self.profile,
            self.level,
            self.role,
            self.grade,
            self.ege_subject,
            self.ege_min,
            self.source,
        ]
        digest = hashlib.sha256(_SEP.join(parts).encode()).hexdigest()
        return digest[:KEY_LENGTH]


def assign_row_keys(rows: Sequence[RowFields]) -> dict[int, str]:
    """id строки -> ключ. Совпавшие ключи получают суффикс -2, -3… в порядке (tiebreak, id)."""
    groups: dict[str, list[RowFields]] = defaultdict(list)
    for row in rows:
        groups[row.base_key()].append(row)
    keys: dict[int, str] = {}
    for base, group in groups.items():
        group.sort(key=lambda r: (tuple(r.tiebreak), r.id))
        for number, row in enumerate(group, start=1):
            keys[row.id] = base if number == 1 else f"{base}-{number}"
    return keys
