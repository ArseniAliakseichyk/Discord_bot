"""How the command error handler classifies failures.

A dead interaction is not a bug in the command, and logging it as one buries
the errors that are. These tests pin which failures get a user-facing reply,
which get a traceback, and which get neither.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import discord
import pytest
from discord import app_commands

from core.bot import MusicBot, _is_expired_interaction
from tests.interaction_harness import FakeInteraction, make_channel, make_guild, make_member
from utils import checks


@pytest.fixture
def bot(make_settings):
    return MusicBot(make_settings())


def interaction(command_name: str = "search") -> FakeInteraction:
    guild = make_guild()
    ix = FakeInteraction(
        user=make_member(1, guild=guild), guild=guild, channel=make_channel(guild=guild)
    )
    ix.command = MagicMock(qualified_name=command_name)
    return ix


def http_error(code: int, status: int = 404) -> discord.NotFound:
    response = MagicMock(status=status, reason="Not Found")
    return discord.NotFound(response, {"code": code, "message": "Unknown interaction"})


class TestExpiredInteraction:
    def test_recognises_10062_wrapped_in_a_command_error(self) -> None:
        wrapped = app_commands.CommandInvokeError(MagicMock(), http_error(10062))
        assert _is_expired_interaction(wrapped) is True

    def test_recognises_a_bare_10062(self) -> None:
        assert _is_expired_interaction(http_error(10062)) is True

    def test_other_not_found_errors_are_not_treated_as_expiry(self) -> None:
        """10008 is a deleted message - a real problem worth a traceback."""
        wrapped = app_commands.CommandInvokeError(MagicMock(), http_error(10008))
        assert _is_expired_interaction(wrapped) is False

    def test_unrelated_errors_are_not_matched(self) -> None:
        wrapped = app_commands.CommandInvokeError(MagicMock(), RuntimeError("boom"))
        assert _is_expired_interaction(wrapped) is False

    async def test_logs_a_warning_and_does_not_try_to_reply(
        self, bot, caplog
    ) -> None:
        """Replying would fail the same way; the token is already gone."""
        ix = interaction("search")
        error = app_commands.CommandInvokeError(MagicMock(), http_error(10062))

        with caplog.at_level(logging.WARNING, logger="bot"):
            await bot.on_app_command_error(ix, error)

        assert not ix.record.acknowledged, "must not attempt a reply on a dead token"
        assert any("expired" in r.message for r in caplog.records)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records), (
            "an expired interaction must not be logged as an internal error"
        )

    async def test_names_the_command_in_the_warning(self, bot, caplog) -> None:
        ix = interaction("play")
        error = app_commands.CommandInvokeError(MagicMock(), http_error(10062))
        with caplog.at_level(logging.WARNING, logger="bot"):
            await bot.on_app_command_error(ix, error)
        assert any("/play" in r.getMessage() for r in caplog.records)


class TestOtherErrors:
    async def test_a_real_failure_still_logs_a_traceback_and_replies(
        self, bot, caplog
    ) -> None:
        ix = interaction()
        error = app_commands.CommandInvokeError(MagicMock(), RuntimeError("boom"))
        with caplog.at_level(logging.ERROR, logger="bot"):
            await bot.on_app_command_error(ix, error)
        assert ix.record.acks == ["send_message"]
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    async def test_cooldown_tells_the_user_how_long(self, bot) -> None:
        ix = interaction()
        await bot.on_app_command_error(
            ix, app_commands.CommandOnCooldown(MagicMock(), 4.2)
        )
        assert ix.record.acks == ["send_message"]

    async def test_check_failures_answer_without_a_traceback(self, bot, caplog) -> None:
        ix = interaction()
        with caplog.at_level(logging.ERROR, logger="bot"):
            await bot.on_app_command_error(ix, checks.NotAuthorized("нет доступа"))
        assert ix.record.acks == ["send_message"]
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)

    async def test_wrong_channel_names_the_channel(self, bot) -> None:
        ix = interaction()
        await bot.on_app_command_error(ix, checks.WrongChannel(12345))
        assert ix.record.acks == ["send_message"]
