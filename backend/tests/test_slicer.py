# backend/tests/test_slicer.py
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


def _msg(id: int, ts_offset_min: int, reply_to: int | None = None) -> MagicMock:
    m = MagicMock()
    m.id = id
    m.group_id = 1
    m.text = f"msg {id}"
    m.ts = datetime(2026, 1, 1, 12, tzinfo=timezone.utc) + timedelta(minutes=ts_offset_min)
    m.reply_to_id = reply_to
    return m


def test_single_message_becomes_one_slice():
    from app.pipeline.slicer import slice_messages
    msgs = [_msg(1, 0)]
    slices = slice_messages(msgs)
    assert len(slices) == 1
    assert slices[0] == [msgs[0]]


def test_reply_chain_stays_together():
    from app.pipeline.slicer import slice_messages
    msgs = [_msg(1, 0), _msg(2, 5, reply_to=1), _msg(3, 10, reply_to=2)]
    slices = slice_messages(msgs)
    assert len(slices) == 1
    assert len(slices[0]) == 3


def test_time_gap_splits_independent_messages():
    from app.pipeline.slicer import slice_messages
    msgs = [_msg(1, 0), _msg(2, 35)]
    slices = slice_messages(msgs)
    assert len(slices) == 2


def test_messages_within_window_stay_together():
    from app.pipeline.slicer import slice_messages
    msgs = [_msg(1, 0), _msg(2, 20)]
    slices = slice_messages(msgs)
    assert len(slices) == 1


def test_reply_chain_bridges_time_gap():
    from app.pipeline.slicer import slice_messages
    msgs = [_msg(1, 0), _msg(2, 120, reply_to=1)]
    slices = slice_messages(msgs)
    assert len(slices) == 1


def test_empty_messages_returns_empty():
    from app.pipeline.slicer import slice_messages
    assert slice_messages([]) == []
