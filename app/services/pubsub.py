"""Fan-out for live message delivery.

Uses Redis pub/sub when `REDIS_URL` is reachable (the real multi-process/
multi-instance path). Falls back to an in-process broker (plain asyncio
queues) when Redis isn't configured or isn't reachable — this keeps local
dev and tests working without a running Redis, at the cost of only fanning
out within a single process.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import settings

logger = logging.getLogger("zent.pubsub")


class _LocalBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, message: dict) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(channel, ()))
        for q in queues:
            q.put_nowait(message)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(channel, set()).add(q)
        try:
            yield q
        finally:
            async with self._lock:
                self._subscribers.get(channel, set()).discard(q)


class _RedisBroker:
    def __init__(self, client) -> None:
        self._client = client

    async def publish(self, channel: str, message: dict) -> None:
        await self._client.publish(channel, json.dumps(message))

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[asyncio.Queue]:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel)
        q: asyncio.Queue = asyncio.Queue()

        async def _pump() -> None:
            try:
                async for raw in pubsub.listen():
                    if raw.get("type") != "message":
                        continue
                    try:
                        q.put_nowait(json.loads(raw["data"]))
                    except (TypeError, ValueError):
                        continue
            except Exception:  # noqa: BLE001 - connection dropped etc.
                logger.warning("redis pubsub listener stopped for %s", channel, exc_info=True)

        task = asyncio.create_task(_pump())
        try:
            yield q
        finally:
            task.cancel()
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()


_broker: _LocalBroker | _RedisBroker | None = None
_broker_lock = asyncio.Lock()


async def get_broker() -> _LocalBroker | _RedisBroker:
    global _broker
    if _broker is not None:
        return _broker
    async with _broker_lock:
        if _broker is not None:
            return _broker
        if settings.REDIS_URL:
            try:
                import redis.asyncio as redis

                client = redis.from_url(settings.REDIS_URL, decode_responses=True)
                await client.ping()
                _broker = _RedisBroker(client)
                logger.info("messaging: using Redis pub/sub at %s", settings.REDIS_URL)
                return _broker
            except Exception:  # noqa: BLE001 - any connection/import failure
                logger.warning(
                    "messaging: Redis unavailable, falling back to in-process pub/sub",
                    exc_info=True,
                )
        _broker = _LocalBroker()
        return _broker


async def reset_broker_for_tests() -> None:
    global _broker
    _broker = None
