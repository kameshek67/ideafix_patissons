from olymp_domain.goals import BVI, HUNDRED, GoalLink, PairInfo, build_goal


def pair(oid: int, profile: int | None = None, **kw: object) -> PairInfo:
    base = {"name": f"О{oid}", "level": "I", "in_list": True, "kind": "rsosh"}
    return PairInfo(olympiad_id=oid, profile_id=profile, **{**base, **kw})  # type: ignore[arg-type]


def link(
    p: PairInfo, program: int, kind: str = BVI, role: str = "победители и призёры", **kw: object
):
    return GoalLink(pair=p.key, program_id=program, benefit_type=kind, role=role, **kw)  # type: ignore[arg-type]


def names(items) -> list[str]:
    return [i.pair.name for i in items]


def test_coverage_first_then_bvi_then_access_then_level() -> None:
    a, b, c, d, e = (pair(i) for i in range(1, 6))
    b = pair(2, level="III")
    d = pair(4, level="II")
    pairs = {p.key: p for p in (a, b, c, d, e)}
    links = [
        link(a, 1),  # 1 направление, БВИ, призёрам, уровень I
        link(b, 1),
        link(b, 2),  # 2 направления
        link(c, 1, HUNDRED),  # 1 направление, только 100 баллов
        link(d, 1, role="победители"),  # 1 БВИ, только победителям
        link(e, 1),
    ]
    got = build_goal(pairs, links)
    # b покрывает два направления; дальше БВИ, где призёрам тоже, уровень I раньше II; 100 баллов в конце
    assert names(got) == ["О2", "О1", "О5", "О4", "О3"]
    assert got[0].bvi_programs == [1, 2]
    assert got[-1].hundred_programs == [1] and got[-1].bvi_programs == []


def test_out_of_list_goes_last_even_with_wider_coverage() -> None:
    inside, outside = pair(1), pair(2, in_list=False)
    links = [link(inside, 1), link(outside, 1), link(outside, 2)]
    got = build_goal({inside.key: inside, outside.key: outside}, links)
    assert names(got) == ["О1", "О2"]
    assert not got[1].pair.in_list


def test_program_with_both_types_counts_once_as_bvi() -> None:
    a = pair(1)
    got = build_goal({a.key: a}, [link(a, 1), link(a, 1, HUNDRED), link(a, 2, HUNDRED)])
    assert got[0].bvi_programs == [1]
    assert got[0].hundred_programs == [2]
    assert got[0].coverage == 2


def test_who_and_ege() -> None:
    a = pair(1)
    winners = build_goal({a.key: a}, [link(a, 1, role="только победители")])[0]
    assert winners.who == "winners" and winners.prize_programs == []
    team = build_goal({a.key: a}, [link(a, 1, role="члены сборных команд РФ")])[0]
    assert team.who == "team"
    got = build_goal(
        {a.key: a},
        [
            link(a, 1, HUNDRED, confirm_subject="математика", min_score=75),
            link(a, 2, HUNDRED, confirm_subject="математика", min_score=70),
        ],
    )[0]
    assert (got.ege_subject, got.ege_min_score) == ("математика", 70)


def test_threshold_taken_from_best_benefit_type() -> None:
    a = pair(1)
    got = build_goal(
        {a.key: a}, [link(a, 1, BVI, min_score=None), link(a, 2, HUNDRED, min_score=90)]
    )[0]
    assert got.ege_min_score is None


def test_prize_hundred_2027() -> None:
    a = pair(1)
    assert build_goal({a.key: a}, [link(a, 1, has_subject=True)])[0].prize_hundred_2027
    # нет профильного предмета — только «проверить», не обещаем
    assert not build_goal({a.key: a}, [link(a, 1)])[0].prize_hundred_2027
    # победителям БВИ остаётся
    win = link(a, 1, role="победители", has_subject=True)
    assert not build_goal({a.key: a}, [win])[0].prize_hundred_2027
    # ВсОШ и международные правила 2027 не затрагивают
    for kind in ("vsosh", "international"):
        v = pair(2, kind=kind)
        assert not build_goal({v.key: v}, [link(v, 1, has_subject=True)])[0].prize_hundred_2027
    # 100 баллов и так не БВИ
    assert not build_goal({a.key: a}, [link(a, 1, HUNDRED, has_subject=True)])[0].prize_hundred_2027


def test_ignores_other_benefits_and_unknown_pairs() -> None:
    a = pair(1)
    other = GoalLink(pair=a.key, program_id=1, benefit_type="ИД (доп. баллы)", role="")
    ghost = GoalLink(pair=(9, None), program_id=1, benefit_type=BVI, role="")
    assert build_goal({a.key: a}, [other, ghost]) == []
