"""Статистика для olymp-metrics: интервалы Уилсона, бутстреп, процентили. Без внешних библиотек."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

Interval = tuple[float, float]

Z95 = 1.959964  # квантиль нормального распределения для 95%
RESAMPLES = 2000
SEED = 20261128


def share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def wilson(successes: int, total: int, z: float = Z95) -> Interval | None:
    """Интервал Уилсона для доли: в отличие от обычного, не выходит за 0 и 1 и честен на малых выборках."""
    if total <= 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Процентиль q (0..1) по ближайшему рангу, как в метриках помощника."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _band(samples: list[float], level: float = 0.95) -> Interval | None:
    if not samples:
        return None
    tail = (1 - level) / 2
    low, high = percentile(samples, tail), percentile(samples, 1 - tail)
    assert low is not None and high is not None
    return low, high


def bootstrap_mean(
    flags: Sequence[bool], resamples: int = RESAMPLES, seed: int = SEED
) -> Interval | None:
    """Бутстреп-интервал доли по записям: каждую запись пересэмплируем независимо."""
    n = len(flags)
    if not n:
        return None
    rng = random.Random(seed)
    data = list(flags)
    samples = [sum(rng.choices(data, k=n)) / n for _ in range(resamples)]
    return _band(samples)


def bootstrap_clusters(
    clusters: Sequence[tuple[int, ...]],
    statistic: Callable[[tuple[int, ...]], float | None],
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> Interval | None:
    """Бутстреп по документам: пересэмплируем целые документы, суммы по ним считает statistic.

    Документ — кортеж чисел (например, эталон, извлечено, совпало); statistic получает их суммы.
    Если в пересэмплированном наборе статистика не определена, он пропускается."""
    n = len(clusters)
    if not n:
        return None
    rng = random.Random(seed)
    width = len(clusters[0])
    samples: list[float] = []
    for _ in range(resamples):
        picked = rng.choices(clusters, k=n)
        value = statistic(tuple(sum(c[i] for c in picked) for i in range(width)))
        if value is not None:
            samples.append(value)
    return _band(samples)


def interval_json(value: float | None, interval: Interval | None) -> dict[str, float | None]:
    return {
        "value": _r(value),
        "low": _r(interval[0]) if interval else None,
        "high": _r(interval[1]) if interval else None,
    }


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)
