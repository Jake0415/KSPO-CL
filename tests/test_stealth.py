"""Tests for crawl.stealth — Stealth profile management."""
from __future__ import annotations

import pytest

from kspo_ingest.crawl.stealth import (
    PROFILES,
    StealthProfile,
    get_profile,
    register_profile,
)


class TestStealthProfile:
    def test_builtin_profiles_exist(self):
        assert "chrome_win" in PROFILES
        assert "chrome_mac" in PROFILES
        assert "edge_win" in PROFILES
        assert "firefox_win" in PROFILES

    def test_get_profile_by_name(self):
        profile = get_profile("chrome_win")
        assert profile.name == "chrome_win"
        assert "Chrome" in profile.user_agent
        assert profile.locale == "ko-KR"

    def test_get_profile_random(self):
        profile = get_profile(None)
        assert profile.name in PROFILES

    def test_get_profile_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown stealth profile"):
            get_profile("nonexistent")

    def test_to_context_kwargs(self):
        profile = get_profile("chrome_win")
        kwargs = profile.to_context_kwargs()
        assert "user_agent" in kwargs
        assert "viewport" in kwargs
        assert kwargs["viewport"]["width"] == 1920
        assert kwargs["locale"] == "ko-KR"
        assert "Accept-Language" in kwargs["extra_http_headers"]

    def test_register_custom_profile(self):
        custom = StealthProfile(
            name="custom_test",
            user_agent="TestAgent/1.0",
            viewport={"width": 800, "height": 600},
            locale="en-US",
            timezone_id="America/New_York",
        )
        register_profile(custom)
        assert "custom_test" in PROFILES
        retrieved = get_profile("custom_test")
        assert retrieved.user_agent == "TestAgent/1.0"

        # cleanup
        del PROFILES["custom_test"]

    def test_frozen_dataclass(self):
        profile = get_profile("chrome_win")
        with pytest.raises(AttributeError):
            profile.name = "changed"  # type: ignore[misc]
