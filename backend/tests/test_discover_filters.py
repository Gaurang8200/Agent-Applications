"""Tests for the Discover filter engine — pure logic, no network."""

from datetime import datetime, timedelta, timezone

from app.agents.discover.filters import (
    JobFilterConfig,
    evaluate,
    is_excluded_company,
    is_in_germany,
    is_recent,
    matched_skills,
    matches_role,
    min_required_years,
)

CONFIG = JobFilterConfig()
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def test_matches_role_substring_case_insensitive():
    assert matches_role("Senior Backend Developer", CONFIG.role_keywords)
    assert matches_role("Agentic AI Engineer", CONFIG.role_keywords)
    assert matches_role("Full Stack Developer (m/w/d)", CONFIG.role_keywords)
    assert not matches_role("Warehouse Logistics Clerk", CONFIG.role_keywords)


def test_matched_skills_word_boundary():
    skills = ["Go", "Python", "C++", "React"]
    text = "We use Python and React with a Go microservice and some C++"
    assert set(matched_skills(text, skills)) == {"Go", "Python", "C++", "React"}
    # "Go" must not match inside "Django"; nothing else here contains the skills.
    assert matched_skills("Django Angular", ["Go", "R"]) == []


def test_excluded_company():
    assert is_excluded_company("SAP SE", ["sap"])
    assert is_excluded_company("sap labs", ["sap"])
    assert not is_excluded_company("Zalando", ["sap"])


def test_min_required_years_variants():
    assert min_required_years("at least 5 years of experience") == 5
    assert min_required_years("3+ years Python") == 3
    assert min_required_years("2-4 years in backend") == 2  # lower bound
    assert min_required_years("mindestens 4 Jahre Berufserfahrung") == 4
    assert min_required_years("3 Jahre Erfahrung") == 3
    # Range picks the lower bound; multiple mentions pick the smallest.
    assert min_required_years("5 years leadership and 2 years Python") == 2


def test_min_required_years_unspecified_is_none():
    assert min_required_years("several years of experience") is None
    assert min_required_years("einschlägige Berufserfahrung erwünscht") is None
    assert min_required_years("no experience requirement mentioned") is None


def test_is_recent():
    assert is_recent(NOW - timedelta(days=3), 7, now=NOW)
    assert not is_recent(NOW - timedelta(days=10), 7, now=NOW)
    # Missing date is not grounds for exclusion.
    assert is_recent(None, 7, now=NOW)


def _eval(title, company, text, posted_delta_days, skills, location="Berlin", country=None, **over):
    return evaluate(
        title=title,
        company=company,
        text=text,
        posted_at=NOW - timedelta(days=posted_delta_days),
        skills=skills,
        config=JobFilterConfig(**over),
        now=NOW,
        location=location,
        country=country,
    )


# --- Germany filter ------------------------------------------------------


def test_country_code_decides_when_present():
    assert is_in_germany(None, "DE")
    assert is_in_germany("London", "DE")  # explicit country wins over text
    assert not is_in_germany("Berlin", "AT")


def test_german_cities_and_states_recognised():
    for place in ["Berlin", "München", "Munich, Bavaria", "Frankfurt am Main",
                  "Hamburg, Germany", "Deutschland", "Nordrhein-Westfalen",
                  "Ingolstadt", "Stuttgart"]:
        assert is_in_germany(place, None), place


def test_nearby_countries_rejected():
    for place in ["London", "Vienna, Austria", "Zurich", "Amsterdam",
                  "Paris, France", "New York", "Remote - UK"]:
        assert not is_in_germany(place, None), place


def test_ambiguous_or_missing_location_rejected():
    # An unplaceable posting is not worth an application.
    assert not is_in_germany(None, None)
    assert not is_in_germany("", None)
    assert not is_in_germany("Remote", None)


def test_german_city_named_inside_a_foreign_location_is_not_matched():
    # Substring matching would wrongly accept these; word boundaries prevent it.
    assert not is_in_germany("Hamburg Township, New Jersey, USA", None)


def test_evaluate_rejects_non_german_posting():
    d = _eval("Backend Engineer", "Z", "Python", 1, ["Python"], location="London")
    assert not d.keep
    assert "Germany" in d.reason


def test_germany_filter_can_be_disabled():
    d = _eval(
        "Backend Engineer", "Z", "Python", 1, ["Python"],
        location="London", germany_only=False,
    )
    assert d.keep


def test_evaluate_keeps_a_good_posting():
    d = _eval(
        "Backend Engineer",
        "Zalando",
        "Backend Engineer. We use Python and FastAPI. 2 years experience.",
        2,
        ["Python", "FastAPI", "Rust"],
    )
    assert d.keep
    assert set(d.matched_skills) == {"Python", "FastAPI"}


def test_evaluate_rejects_each_rule():
    # excluded company
    assert not _eval("Backend Engineer", "SAP", "Python", 1, ["Python"]).keep
    # too old
    assert not _eval("Backend Engineer", "Z", "Python", 30, ["Python"]).keep
    # wrong role
    assert not _eval("Sales Manager", "Z", "Python", 1, ["Python"]).keep
    # too much experience
    assert not _eval(
        "Backend Engineer", "Z", "Python, 6 years required", 1, ["Python"]
    ).keep
    # no skill match
    assert not _eval("Backend Engineer", "Z", "We use Cobol", 1, ["Python"]).keep


def test_evaluate_keeps_unspecified_experience():
    d = _eval(
        "Backend Engineer",
        "Z",
        "Python role. Several years of experience desired.",
        1,
        ["Python"],
    )
    assert d.keep
