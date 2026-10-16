from __future__ import annotations

import pytest

from kspo_ingest.api.auth.password import validate_password_complexity


def test_valid_password():
    validate_password_complexity("Passw0rd!")  # Should not raise


def test_too_short():
    with pytest.raises(ValueError, match="8"):
        validate_password_complexity("Pa1!")


def test_missing_letter():
    with pytest.raises(ValueError, match="영문"):
        validate_password_complexity("12345678!")


def test_missing_digit():
    with pytest.raises(ValueError, match="숫자"):
        validate_password_complexity("Password!")


def test_missing_special():
    with pytest.raises(ValueError, match="특수문자"):
        validate_password_complexity("Password1")


def test_all_requirements_met():
    validate_password_complexity("MyP@ssw0rd")
    validate_password_complexity("a1!bcdef")


def test_long_password_valid():
    validate_password_complexity("VeryL0ng!Password#123")
