import pytest
from olymp_domain.extra_points import (
    Claim,
    ExtraRule,
    Skip,
    clean_kind,
    score,
)


def rule(rid: str, kind: str = "gto_badge", points: int = 3, **kw) -> ExtraRule:
    return ExtraRule(rule_id=rid, kind=kind, points=points, admission_year=2026, **kw)


def test_each_rule_counts_once():
    res = score([rule("g", variants=("gold",))], [Claim("gto_badge", "gold")] * 3)
    assert res.total == 3


def test_variant_is_required_and_case_insensitive():
    rules = [rule("g", variants=("gold",))]
    assert score(rules, [Claim("gto_badge", "GOLD")]).total == 3
    assert score(rules, [Claim("gto_badge")]).total == 0


def test_cap_applied_and_unknown_cap_not_applied():
    rules = [rule("a", points=8), rule("b", kind="sport_title", points=8)]
    claims = [Claim("gto_badge"), Claim("sport_title")]
    capped = score(rules, claims, 10)
    assert (capped.raw_total, capped.total, capped.capped) == (16, 10, True)
    unknown = score(rules, claims, None)
    assert (unknown.total, unknown.capped, unknown.max_total) == (16, False, None)


def test_recency_and_years():
    gto = [rule("g", recency_years=1)]
    assert score(gto, [Claim("gto_badge", year=2025)]).total == 3
    old = score(gto, [Claim("gto_badge", year=2024)])
    assert old.total == 0 and old.skipped[0].reason is Skip.TOO_OLD
    assert score(gto, [Claim("gto_badge")]).skipped[0].reason is Skip.YEAR_MISSING
    assert score(gto, [Claim("gto_badge", year=2027)]).skipped[0].reason is Skip.YEAR_IN_FUTURE
    listed = [rule("o", kind="olympiad_other", years=(2025, 2026))]
    res = score(listed, [Claim("olympiad_other", year=2024)])
    assert res.skipped[0].reason is Skip.YEAR_NOT_ALLOWED


def test_second_claim_passes_when_first_is_too_old():
    res = score(
        [rule("g", recency_years=1)], [Claim("gto_badge", year=2020), Claim("gto_badge", year=2026)]
    )
    assert res.total == 3 and not res.skipped


def test_exclusive_group_keeps_best():
    rules = [
        rule("a", kind="volunteer", points=2, exclusive_group="g"),
        rule("b", kind="abilimpics", points=10, exclusive_group="g"),
    ]
    res = score(rules, [Claim("volunteer"), Claim("abilimpics")])
    assert res.total == 10
    assert [(s.rule.rule_id, s.reason) for s in res.skipped] == [("a", Skip.SAME_GROUP_BETTER)]


def test_claim_with_rule_id_matches_only_that_rule():
    rules = [rule("a", kind="olympiad_other", points=5), rule("b", kind="olympiad_other", points=2)]
    assert score(rules, [Claim("olympiad_other", rule_id="b")]).total == 2
    assert score(rules, [Claim("olympiad_other")]).total == 7  # без rule_id подходят оба
    res = score(rules, [Claim("olympiad_other", rule_id="нет такого")])
    assert res.total == 0 and len(res.unmatched) == 1


def test_unmatched_claims_reported():
    res = score([rule("g")], [Claim("volunteer")])
    assert res.unmatched == (Claim("volunteer"),)


@pytest.mark.parametrize(
    ("raw", "kind"), [("gto_badge", "gto_badge"), ("GTO_BADGE ", "gto_badge"), ("x", None)]
)
def test_clean_kind(raw, kind):
    assert clean_kind(raw) == kind
