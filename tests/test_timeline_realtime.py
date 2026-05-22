import asyncio
import json
from datetime import datetime, timezone

from services.timeline_realtime import TimelineRealtimeBus


def test_unsubscribe_removes_empty_channel():
    bus = TimelineRealtimeBus()

    async def scenario() -> None:
        queue = await bus.subscribe(42)
        assert 42 in bus._channels

        await bus.unsubscribe(42, queue)
        assert 42 not in bus._channels

    asyncio.run(scenario())


def test_close_clears_all_channels():
    bus = TimelineRealtimeBus()

    async def scenario() -> None:
        await bus.subscribe(1)
        await bus.subscribe(2)
        assert set(bus._channels) == {1, 2}

        await bus.close()
        assert bus._channels == {}

    asyncio.run(scenario())


def test_publish_normalizes_datetimes_to_utc_iso():
    bus = TimelineRealtimeBus()

    async def scenario() -> None:
        queue = await bus.subscribe(7)

        await bus.publish(
            7,
            {
                "type": "timeline_event",
                "case_id": 7,
                "timestamp": datetime(2026, 5, 22, 10, 30, tzinfo=timezone.utc),
                "metadata": {
                    "nested_timestamp": datetime(2026, 5, 22, 10, 31),
                },
            },
        )

        payload = await queue.get()
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        assert decoded["timestamp"] == "2026-05-22T10:30:00+00:00"
        assert decoded["metadata"]["nested_timestamp"] == "2026-05-22T10:31:00+00:00"

    asyncio.run(scenario())