"""Tests for the /topics gateway slash command.

/topics answers "which topic is which" from inside Telegram: thread id, name,
any bound skill, and the deliver target to point a cron job at a topic.
"""

from unittest.mock import MagicMock

import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource

CHAT_ID = "-1001234567890"


def _make_event(platform=Platform.TELEGRAM, chat_type="group", thread_id=None,
                chat_id=CHAT_ID, chat_name="Hermes HQ"):
    source = SessionSource(
        platform=platform,
        user_id="12345",
        chat_id=chat_id,
        chat_name=chat_name,
        chat_type=chat_type,
        thread_id=thread_id,
        user_name="testuser",
    )
    return MessageEvent(text="/topics", source=source)


def _make_runner(topics=None, with_adapter=True):
    from gateway.run import GatewayRunner
    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner._session_db = None
    runner.session_store = MagicMock()

    if with_adapter:
        adapter = MagicMock()
        adapter.known_group_topics.return_value = topics if topics is not None else []
        runner.adapters[Platform.TELEGRAM] = adapter
    return runner


FOUR_TOPICS = [
    {"thread_id": 2, "name": "general"},
    {"thread_id": 5, "name": "briefs", "skill": "morning"},
    {"thread_id": 9, "name": "ideas"},
    {"thread_id": 14, "name": "projects"},
]


class TestHandleTopicsCommand:

    @pytest.mark.asyncio
    async def test_lists_every_known_topic(self):
        runner = _make_runner(topics=FOUR_TOPICS)

        result = await runner._handle_topics_command(_make_event())

        for name in ("general", "briefs", "ideas", "projects"):
            assert name in result
        for thread_id in ("2", "5", "9", "14"):
            assert f"`{thread_id}`" in result
        assert "Hermes HQ" in result

    @pytest.mark.asyncio
    async def test_each_topic_is_a_markdown_list_item(self):
        """Chat renderers collapse a single newline, which would run the whole
        list onto one line. List syntax keeps the rows separate."""
        runner = _make_runner(topics=FOUR_TOPICS)

        result = await runner._handle_topics_command(_make_event())

        rows = [line for line in result.splitlines() if line.startswith("- ")]
        assert len(rows) == 4
        assert rows[0].startswith("- `2`")

    @pytest.mark.asyncio
    async def test_shows_skill_binding(self):
        runner = _make_runner(topics=FOUR_TOPICS)

        result = await runner._handle_topics_command(_make_event())

        assert "skill: `morning`" in result

    @pytest.mark.asyncio
    async def test_marks_current_topic(self):
        runner = _make_runner(topics=FOUR_TOPICS)

        result = await runner._handle_topics_command(_make_event(thread_id="9"))

        ideas_line = next(line for line in result.splitlines() if "ideas" in line)
        assert "you are here" in ideas_line
        briefs_line = next(line for line in result.splitlines() if "briefs" in line)
        assert "you are here" not in briefs_line

    @pytest.mark.asyncio
    async def test_footer_offers_deliver_target_for_current_topic(self):
        runner = _make_runner(topics=FOUR_TOPICS)

        result = await runner._handle_topics_command(_make_event(thread_id="9"))

        assert f"telegram:{CHAT_ID}:9" in result

    @pytest.mark.asyncio
    async def test_footer_falls_back_to_first_topic_outside_a_thread(self):
        runner = _make_runner(topics=FOUR_TOPICS)

        result = await runner._handle_topics_command(_make_event(thread_id=None))

        assert f"telegram:{CHAT_ID}:2" in result

    @pytest.mark.asyncio
    async def test_unnamed_topic_renders_placeholder(self):
        runner = _make_runner(topics=[{"thread_id": 4}])

        result = await runner._handle_topics_command(_make_event())

        assert "(unnamed)" in result
        assert "`4`" in result

    @pytest.mark.asyncio
    async def test_no_topics_yet_explains_how_to_populate(self):
        runner = _make_runner(topics=[])

        result = await runner._handle_topics_command(_make_event())

        assert "No topics discovered yet" in result

    @pytest.mark.asyncio
    async def test_rejects_non_telegram_platforms(self):
        runner = _make_runner(topics=FOUR_TOPICS)

        result = await runner._handle_topics_command(_make_event(platform=Platform.DISCORD))

        assert "only available on Telegram" in result

    @pytest.mark.asyncio
    async def test_dm_points_at_topic_command_instead(self):
        """DM topics live in a different table — /topic owns that mode."""
        runner = _make_runner(topics=FOUR_TOPICS)

        result = await runner._handle_topics_command(_make_event(chat_type="dm"))

        assert "/topic" in result

    @pytest.mark.asyncio
    async def test_missing_adapter_does_not_raise(self):
        runner = _make_runner(with_adapter=False)

        result = await runner._handle_topics_command(_make_event())

        assert isinstance(result, str) and result

    @pytest.mark.asyncio
    async def test_adapter_failure_degrades_to_empty_listing(self):
        runner = _make_runner()
        runner.adapters[Platform.TELEGRAM].known_group_topics.side_effect = RuntimeError("boom")

        result = await runner._handle_topics_command(_make_event())

        assert "No topics discovered yet" in result
