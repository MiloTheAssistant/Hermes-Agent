"""Tests for Telegram forum supergroup topic discovery.

Group topics are created by an admin in the Telegram UI, so unlike DM topics
Hermes can't create them. It can still learn their thread_ids as messages
arrive, which is what removes the "read the id out of a t.me/c/ link" step.

Covers:
- _discover_group_topic: persisting newly seen topics into config.yaml
- _extract_forum_topic_name: naming via forum_topic_created / edited / reply
- _persist_group_topic: not clobbering operator-set skill bindings
- known_group_topics: the listing behind /topics
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from gateway.config import PlatformConfig


def _ensure_telegram_mock():
    telegram_mod = MagicMock()
    telegram_mod.ext.ContextTypes.DEFAULT_TYPE = type(None)

    constants_mod = MagicMock()
    constants_mod.ParseMode.MARKDOWN_V2 = "MarkdownV2"
    constants_mod.ChatType.GROUP = "group"
    constants_mod.ChatType.SUPERGROUP = "supergroup"
    constants_mod.ChatType.CHANNEL = "channel"
    constants_mod.ChatType.PRIVATE = "private"

    sys.modules["telegram"] = telegram_mod
    sys.modules["telegram.ext"] = telegram_mod.ext
    sys.modules["telegram.constants"] = constants_mod
    sys.modules["telegram.request"] = telegram_mod.request

    sys.modules.pop("gateway.platforms.telegram", None)


_ensure_telegram_mock()

from gateway.platforms.telegram import TelegramAdapter  # noqa: E402
from telegram.constants import ChatType as _ChatType  # noqa: E402

CHAT_ID = -1001234567890


def _make_adapter(group_topics_config=None):
    extra = {}
    if group_topics_config is not None:
        extra["group_topics"] = group_topics_config
    return TelegramAdapter(PlatformConfig(enabled=True, token="***", extra=extra))


def _config_path():
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "config.yaml"


def _write_config(data):
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return path


def _read_group_topics():
    with open(_config_path(), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return (
        config.get("platforms", {})
        .get("telegram", {})
        .get("extra", {})
        .get("group_topics", [])
    )


def _group_message(
    *,
    chat_id=CHAT_ID,
    thread_id=5,
    text="hello",
    forum_topic_created=None,
    forum_topic_edited=None,
    reply_to_message=None,
):
    return SimpleNamespace(
        message_id=42,
        text=text,
        caption=None,
        entities=[],
        caption_entities=[],
        message_thread_id=thread_id,
        is_topic_message=thread_id is not None,
        chat=SimpleNamespace(
            id=chat_id,
            type=_ChatType.SUPERGROUP,
            title="Hermes HQ",
            is_forum=True,
        ),
        from_user=SimpleNamespace(id=111, full_name="Alice Example"),
        reply_to_message=reply_to_message,
        date=None,
        forum_topic_created=forum_topic_created,
        forum_topic_edited=forum_topic_edited,
    )


# ── _extract_forum_topic_name ────────────────────────────────────────────


def test_extract_name_from_forum_topic_created():
    adapter = _make_adapter()
    msg = _group_message(forum_topic_created=SimpleNamespace(name="briefs"))

    assert adapter._extract_forum_topic_name(msg) == "briefs"


def test_extract_name_from_forum_topic_edited():
    adapter = _make_adapter()
    msg = _group_message(forum_topic_edited=SimpleNamespace(name="projects"))

    assert adapter._extract_forum_topic_name(msg) == "projects"


def test_extract_name_from_reply_to_topic_opening_message():
    """Pre-existing topics get named via the reply anchor, not creation."""
    adapter = _make_adapter()
    msg = _group_message(
        reply_to_message=SimpleNamespace(
            forum_topic_created=SimpleNamespace(name="ideas"),
        )
    )

    assert adapter._extract_forum_topic_name(msg) == "ideas"


def test_extract_name_returns_none_for_plain_message():
    adapter = _make_adapter()

    assert adapter._extract_forum_topic_name(_group_message()) is None


# ── discovery persistence ────────────────────────────────────────────────


def test_discovery_persists_named_topic():
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _make_adapter()

    adapter._discover_group_topic(str(CHAT_ID), "7", "briefs")

    assert _read_group_topics() == [
        {"chat_id": CHAT_ID, "topics": [{"thread_id": 7, "name": "briefs"}]}
    ]


def test_discovery_persists_unnamed_topic():
    """A thread_id with no name is still worth recording — it's the half you
    can't get from the Telegram UI, and it gives the operator a stanza to
    hang a skill on."""
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _make_adapter()

    adapter._discover_group_topic(str(CHAT_ID), "9", None)

    assert _read_group_topics() == [
        {"chat_id": CHAT_ID, "topics": [{"thread_id": 9}]}
    ]


def test_discovery_upgrades_unnamed_topic_when_name_is_learned():
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _make_adapter()

    adapter._discover_group_topic(str(CHAT_ID), "9", None)
    adapter._discover_group_topic(str(CHAT_ID), "9", "general")

    topics = _read_group_topics()[0]["topics"]
    assert topics == [{"thread_id": 9, "name": "general"}]


def test_discovery_preserves_operator_skill_binding_on_rename():
    _write_config({
        "platforms": {
            "telegram": {
                "extra": {
                    "group_topics": [
                        {
                            "chat_id": CHAT_ID,
                            "topics": [
                                {"thread_id": 5, "name": "eng", "skill": "software-development"},
                            ],
                        }
                    ]
                }
            }
        }
    })
    adapter = _make_adapter()

    adapter._discover_group_topic(str(CHAT_ID), "5", "engineering")

    topics = _read_group_topics()[0]["topics"]
    assert topics == [
        {"thread_id": 5, "name": "engineering", "skill": "software-development"}
    ]


def test_discovery_appends_to_existing_chat_entry():
    _write_config({
        "platforms": {
            "telegram": {
                "extra": {
                    "group_topics": [
                        {"chat_id": CHAT_ID, "topics": [{"thread_id": 5, "name": "general"}]}
                    ]
                }
            }
        }
    })
    adapter = _make_adapter()

    adapter._discover_group_topic(str(CHAT_ID), "6", "briefs")

    topics = _read_group_topics()[0]["topics"]
    assert topics == [
        {"thread_id": 5, "name": "general"},
        {"thread_id": 6, "name": "briefs"},
    ]


def test_discovery_is_idempotent_for_known_topics():
    """Repeat traffic in a known topic must not rewrite config.yaml."""
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _make_adapter()

    adapter._discover_group_topic(str(CHAT_ID), "5", "general")
    mtime = _config_path().stat().st_mtime_ns

    for _ in range(3):
        adapter._discover_group_topic(str(CHAT_ID), "5", "general")

    assert _config_path().stat().st_mtime_ns == mtime


def test_discovery_survives_missing_config_file():
    """No config.yaml (fresh install) must not raise on an inbound message."""
    adapter = _make_adapter()

    adapter._discover_group_topic(str(CHAT_ID), "5", "general")  # must not raise

    assert not _config_path().exists()


# ── discovery runs independently of the mention gate ─────────────────────


def _adapter_with_gates(**extra):
    config = PlatformConfig(enabled=True, token="***", extra=extra)
    adapter = TelegramAdapter(config)
    adapter._bot = MagicMock()
    adapter._bot.username = "hermes_bot"
    return adapter


def test_unmentioned_message_still_discovers_topic():
    """The whole point: a mention-gated group still gets its topics recorded."""
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _adapter_with_gates(require_mention=True)
    msg = _group_message(thread_id=7, text="no mention here")

    assert adapter._should_process_message(msg) is False  # not answered...
    assert _read_group_topics()[0]["topics"] == [{"thread_id": 7}]  # ...but recorded


def test_discovery_skipped_for_chat_outside_allowed_chats():
    """Hermes must not record structure for chats it was told to ignore."""
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _adapter_with_gates(require_mention=False, allowed_chats="-100999")
    msg = _group_message(chat_id=CHAT_ID, thread_id=7)

    assert adapter._should_process_message(msg) is False
    assert _read_group_topics() == []


def test_discovery_skipped_for_topic_outside_allowed_topics():
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _adapter_with_gates(require_mention=False, allowed_topics=["2"])
    msg = _group_message(thread_id=7)

    assert adapter._should_process_message(msg) is False
    assert _read_group_topics() == []


def test_discovery_skipped_for_ignored_thread():
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _adapter_with_gates(require_mention=False, ignored_threads="7")
    msg = _group_message(thread_id=7)

    assert adapter._should_process_message(msg) is False
    assert _read_group_topics() == []


def test_discovery_ignores_plain_reply_anchor_in_non_forum_group():
    """message_thread_id is also set for ordinary reply anchors (#3206)."""
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _adapter_with_gates(require_mention=False)
    msg = _group_message(thread_id=7)
    msg.chat.is_forum = False
    msg.is_topic_message = False

    adapter._should_process_message(msg)

    assert _read_group_topics() == []


def test_discovery_records_general_topic_without_thread_id():
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _adapter_with_gates(require_mention=False)
    msg = _group_message(thread_id=None)
    msg.chat.is_forum = True

    adapter._should_process_message(msg)

    assert _read_group_topics()[0]["topics"] == [{"thread_id": 1}]


def test_dm_never_discovers_group_topics():
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _adapter_with_gates(require_mention=True)
    msg = _group_message(thread_id=7)
    msg.chat.type = "private"

    assert adapter._should_process_message(msg) is True
    assert _read_group_topics() == []


# ── _build_message_event integration ─────────────────────────────────────


def test_build_message_event_discovers_topic_and_sets_name():
    from gateway.platforms.base import MessageType

    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _make_adapter()
    msg = _group_message(
        thread_id=11,
        forum_topic_created=SimpleNamespace(name="projects"),
    )

    event = adapter._build_message_event(msg, MessageType.TEXT)

    assert event.source.thread_id == "11"
    assert event.source.chat_topic == "projects"
    assert _read_group_topics()[0]["topics"] == [{"thread_id": 11, "name": "projects"}]


def test_build_message_event_still_binds_configured_skill():
    """Regression: discovery must not displace group_topics skill binding."""
    from gateway.platforms.base import MessageType

    adapter = _make_adapter(group_topics_config=[
        {
            "chat_id": CHAT_ID,
            "topics": [{"name": "Engineering", "thread_id": 5, "skill": "software-development"}],
        }
    ])
    msg = _group_message(thread_id=5)

    event = adapter._build_message_event(msg, MessageType.TEXT)

    assert event.auto_skill == "software-development"
    assert event.source.chat_topic == "Engineering"


def test_reload_does_not_clobber_in_memory_config():
    """A config.yaml without a group_topics key must leave extra-supplied
    bindings intact — otherwise the first unknown topic wipes them."""
    _write_config({"platforms": {"telegram": {"extra": {"allowed_chats": "-100"}}}})
    adapter = _make_adapter(group_topics_config=[
        {
            "chat_id": CHAT_ID,
            "topics": [{"name": "Engineering", "thread_id": 5, "skill": "software-development"}],
        }
    ])

    # Miss on an unrelated thread forces the hot-reload path.
    assert adapter._get_group_topic_info(str(CHAT_ID), "99") is None

    assert adapter._get_group_topic_info(str(CHAT_ID), "5") == {
        "name": "Engineering", "thread_id": 5, "skill": "software-development"
    }


# ── known_group_topics (backs /topics) ───────────────────────────────────


def test_known_group_topics_sorted_by_thread_id():
    _write_config({
        "platforms": {
            "telegram": {
                "extra": {
                    "group_topics": [
                        {
                            "chat_id": CHAT_ID,
                            "topics": [
                                {"thread_id": 12, "name": "projects"},
                                {"thread_id": 3, "name": "general", "skill": "morning"},
                                {"thread_id": 7, "name": "briefs"},
                            ],
                        }
                    ]
                }
            }
        }
    })
    adapter = _make_adapter()

    topics = adapter.known_group_topics(str(CHAT_ID))

    assert [t["thread_id"] for t in topics] == [3, 7, 12]
    assert topics[0]["skill"] == "morning"


def test_known_group_topics_unknown_chat_is_empty():
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _make_adapter()

    assert adapter.known_group_topics("-100999") == []


def test_known_group_topics_skips_entries_without_thread_id():
    _write_config({
        "platforms": {
            "telegram": {
                "extra": {
                    "group_topics": [
                        {
                            "chat_id": CHAT_ID,
                            "topics": [{"name": "half-written"}, {"thread_id": 4, "name": "ok"}],
                        }
                    ]
                }
            }
        }
    })
    adapter = _make_adapter()

    assert adapter.known_group_topics(str(CHAT_ID)) == [{"thread_id": 4, "name": "ok"}]


def test_known_group_topics_hot_reloads_config():
    """A topic added to config.yaml mid-run shows up without a restart."""
    _write_config({"platforms": {"telegram": {"extra": {}}}})
    adapter = _make_adapter()
    assert adapter.known_group_topics(str(CHAT_ID)) == []

    _write_config({
        "platforms": {
            "telegram": {
                "extra": {
                    "group_topics": [
                        {"chat_id": CHAT_ID, "topics": [{"thread_id": 2, "name": "ideas"}]}
                    ]
                }
            }
        }
    })

    assert adapter.known_group_topics(str(CHAT_ID)) == [{"thread_id": 2, "name": "ideas"}]
