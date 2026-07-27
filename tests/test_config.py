"""Configuration parsing and validation."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from config import Settings, _parse_id_set


class TestParseIdSet:
    def test_empty_values_give_an_empty_set(self) -> None:
        assert _parse_id_set(None) == set()
        assert _parse_id_set("") == set()

    def test_comma_separated_string(self) -> None:
        assert _parse_id_set("1, 2,3 ") == {1, 2, 3}

    def test_collections_are_coerced(self) -> None:
        assert _parse_id_set([1, 2]) == {1, 2}
        assert _parse_id_set(("3",)) == {3}

    def test_a_typo_is_an_error_not_a_silent_drop(self) -> None:
        # Previously filtered out with isdigit(), which made a typo in OWNER_IDS
        # indistinguishable from leaving it unset.
        with pytest.raises(ValueError, match="not a valid Discord ID"):
            _parse_id_set("123,abc")

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot parse"):
            _parse_id_set(object())


class TestSettings:
    def test_token_is_masked_in_repr(self, make_settings: Callable[..., Settings]) -> None:
        settings = make_settings(DISCORD_TOKEN="super-secret")
        assert "super-secret" not in repr(settings)
        assert settings.discord_token.get_secret_value() == "super-secret"

    def test_id_lists_survive_the_dotenv_source(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        # Regression: pydantic-settings json-decodes complex types coming from a
        # .env file, so a bare "1,2" used to abort startup with a SettingsError.
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DISCORD_TOKEN=t\nEXCLUDED_USER_IDS=111,222\nOWNER_IDS=333\n",
            encoding="utf-8",
        )
        settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]
        assert settings.excluded_user_ids == {111, 222}
        assert settings.owner_ids == {333}

    def test_volume_is_clamped(self, make_settings: Callable[..., Settings]) -> None:
        assert make_settings(DEFAULT_VOLUME=500).default_volume == 200
        assert make_settings(DEFAULT_VOLUME=-5).default_volume == 0

    @pytest.mark.parametrize("field", ["MAX_PLAYLIST_TRACKS", "INACTIVE_TIMEOUT"])
    def test_non_positive_values_are_rejected(
        self, make_settings: Callable[..., Settings], field: str
    ) -> None:
        with pytest.raises(ValidationError):
            make_settings(**{field: 0})

    def test_max_track_length_allows_zero_but_not_negative(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        assert make_settings(MAX_TRACK_LENGTH=0).max_track_length == 0
        with pytest.raises(ValidationError):
            make_settings(MAX_TRACK_LENGTH=-1)

    def test_intents_enable_the_privileged_ones_the_cogs_need(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        intents = make_settings().intents
        assert intents.message_content
        assert intents.members
        assert intents.voice_states
