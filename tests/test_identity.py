import pytest

from tariff_app.identity import IdentityError, actor_email, forwarded_email


def test_forwarded_databricks_email_is_case_insensitive_and_trimmed():
    headers = {"x-FoRwArDeD-eMaIl": "  manager@example.com "}

    assert forwarded_email(headers) == "manager@example.com"
    assert actor_email(headers, fallback="local@example.com") == "manager@example.com"


def test_local_identity_is_used_only_when_forwarded_identity_is_absent():
    assert actor_email({}, fallback="local@example.com") == "local@example.com"


def test_actor_identity_requires_an_explicit_local_fallback():
    with pytest.raises(IdentityError, match="explicit local identity"):
        actor_email({})


def test_forwarded_identity_cannot_be_blank():
    with pytest.raises(IdentityError, match="identity"):
        actor_email({"X-Forwarded-Email": "  "}, fallback="  ")
