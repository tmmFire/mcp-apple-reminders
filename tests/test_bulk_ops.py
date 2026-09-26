"""Bulk create + Slice 3.4 complete/move/delete operations.

Unit-level coverage of input handling and the empty-input fast path.
Live bulk round-trips are intentionally not exercised here — they'd
require fabricating dozens of test reminders and policing cleanup
across multiple bridge paths. The per-item paths (complete, move,
delete) are exercised by other tests; bulk just wraps them with
progress reporting + elicitation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_apple_reminders.server import mcp


def _list_tools():
    return asyncio.run(mcp.list_tools())


def test_four_bulk_tools_registered():
    names = {t.name for t in _list_tools()}
    assert {"bulk_create_reminders", "bulk_complete", "bulk_move", "bulk_delete_completed"}.issubset(names)


def test_bulk_create_with_empty_list_returns_zero_processed():
    from mcp_apple_reminders.tools.bulk import bulk_create_reminders

    out = asyncio.run(bulk_create_reminders(reminders=[], calendar_id="cal-1", ctx=None))
    assert out.processed == 0
    assert out.created == []
    assert out.failed == []
    assert out.target_calendar_id == "cal-1"


def test_bulk_create_preserves_successes_and_reports_failures():
    from mcp_apple_reminders.tools.bulk import ReminderCreateInput, bulk_create_reminders

    native = SimpleNamespace(
        id="rem-1",
        title="Carrots 2",
        due_date=None,
        notes="Meal plan 2026-09-28",
        completed=False,
        url=None,
        priority=0,
        list_id="cal-1",
        created_date=None,
        modified_date=None,
        flagged=False,
    )
    bridge = MagicMock()
    bridge.create_reminder.side_effect = [native, RuntimeError("write failed")]
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    ctx.info = AsyncMock()

    inputs = [
        ReminderCreateInput(title="Carrots 2", notes="Meal plan 2026-09-28"),
        ReminderCreateInput(title="Milk 1L"),
    ]
    with patch("mcp_apple_reminders.tools.bulk._app_context", return_value=SimpleNamespace(bridge=bridge)):
        out = asyncio.run(bulk_create_reminders(reminders=inputs, calendar_id="cal-1", ctx=ctx))

    assert out.processed == 1
    assert [item.id for item in out.created] == ["rem-1"]
    assert out.failed[0].input_index == 1
    assert out.failed[0].title == "Milk 1L"
    assert out.failed[0].error == "write failed"
    assert bridge.create_reminder.call_args_list[0].kwargs == {
        "title": "Carrots 2",
        "calendar_id": "cal-1",
        "notes": "Meal plan 2026-09-28",
    }
    assert ctx.report_progress.await_count == 2


def test_bulk_delete_completed_validates_window():
    """end < start raises ValueError synchronously."""
    from mcp_apple_reminders.tools.bulk import bulk_delete_completed

    async def go():
        # ctx is None — we expect the validation to fire before we touch it.
        try:
            await bulk_delete_completed(start="2026-05-01T00:00:00", end="2026-04-01T00:00:00", ctx=None)
        except ValueError as e:
            return str(e)
        return None

    msg = asyncio.run(go())
    assert msg is not None
    assert "end" in msg


def test_bulk_complete_with_empty_list_returns_zero_processed():
    """Empty input returns the canonical empty report without touching the bridge."""
    from mcp_apple_reminders.tools.bulk import bulk_complete

    out = asyncio.run(bulk_complete(reminder_ids=[], ctx=None))
    assert out.processed == 0
    assert out.failed == []


def test_bulk_move_with_empty_list_returns_zero_processed():
    from mcp_apple_reminders.tools.bulk import bulk_move

    out = asyncio.run(bulk_move(reminder_ids=[], calendar_id="X", ctx=None))
    assert out.processed == 0
    assert out.failed == []


# pytest config — we don't yield from any external state, suppress xdist warnings.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
