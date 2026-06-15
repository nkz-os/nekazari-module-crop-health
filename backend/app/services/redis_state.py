"""
Redis State — Sliding window for temporal sensor data.

Uses Redis Sorted Sets (ZADD) with UNIX timestamp as score.
All keys are prefixed with the configured key prefix for logical isolation
in the shared Redis instance.

Purging: ZREMRANGEBYSCORE removes entries older than the sliding window
on every write to prevent memory leaks.
"""

from __future__ import annotations

import json
import logging
import time

import redis.asyncio as aioredis

from app.config import get_settings
from app.schemas import TimeseriesPoint

logger = logging.getLogger(__name__)


class RedisState:
    """Async Redis client for temporal sensor data storage."""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client
        settings = get_settings()
        self._prefix = settings.redis_key_prefix
        self._window_hours = settings.sliding_window_hours

    @classmethod
    async def create(cls) -> "RedisState":
        """Factory: connect to Redis using configured URL."""
        settings = get_settings()
        client = aioredis.from_url(
            settings.redis_url,
            password=settings.redis_password or None,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        # Test connection
        await client.ping()
        logger.info("Redis connected: %s", settings.redis_url)
        return cls(client=client)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            logger.info("Redis connection closed")

    def _key(self, device_id: str, metric: str) -> str:
        """Build a namespaced Redis key."""
        return f"{self._prefix}{device_id}:{metric}"

    async def store_reading(
        self,
        device_id: str,
        metric: str,
        timestamp: float,
        value: float,
    ) -> None:
        """Store a sensor reading in the sliding window.

        Uses ZADD with UNIX timestamp as score.
        Immediately purges entries older than sliding_window_hours.

        Args:
            device_id: Sensor/device NGSI-LD entity ID.
            metric: Metric name (e.g. 'trunkDiameter').
            timestamp: UNIX timestamp of the reading.
            value: Sensor value.
        """
        if self._client is None:
            raise RuntimeError("Redis client not initialised — call RedisState.create()")

        key = self._key(device_id, metric)
        member = json.dumps({"ts": timestamp, "v": value})

        async with self._client.pipeline(transaction=True) as pipe:
            # Add the new reading
            pipe.zadd(key, {member: timestamp})

            # Purge expired entries
            cutoff = time.time() - (self._window_hours * 3600)
            pipe.zremrangebyscore(key, "-inf", cutoff)

            # Set TTL on the key as safety net (2x window)
            pipe.expire(key, self._window_hours * 3600 * 2)

            await pipe.execute()

        logger.debug("Stored %s:%s ts=%.0f v=%.2f", device_id, metric, timestamp, value)

    async def get_window(
        self,
        device_id: str,
        metric: str,
        hours: int | None = None,
    ) -> list[TimeseriesPoint]:
        """Retrieve readings within a time window.

        Args:
            device_id: Sensor/device NGSI-LD entity ID.
            metric: Metric name.
            hours: Window size in hours (default: sliding_window_hours from config).

        Returns:
            List of TimeseriesPoint sorted by timestamp ascending.
        """
        if self._client is None:
            raise RuntimeError("Redis client not initialised")

        key = self._key(device_id, metric)
        window = hours if hours is not None else self._window_hours
        ts_min = time.time() - (window * 3600)

        raw = await self._client.zrangebyscore(key, ts_min, "+inf")

        points: list[TimeseriesPoint] = []
        for member in raw:
            try:
                data = json.loads(member)
                points.append(TimeseriesPoint(ts=data["ts"], value=data["v"]))
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Corrupt Redis entry in %s: %s — %s", key, member, exc)
                continue

        return points

    async def get_max_min_in_window(
        self,
        device_id: str,
        metric: str,
        hours: int = 24,
    ) -> tuple[float, float] | None:
        """Get max and min values in a time window.

        Optimised for MDS calculation: max(D_tallo) - min(D_tallo).

        Returns:
            (max_value, min_value) tuple, or None if insufficient data.
        """
        points = await self.get_window(device_id, metric, hours)
        if len(points) < 2:
            return None
        values = [p.value for p in points]
        return (max(values), min(values))

    async def get_latest(
        self,
        device_id: str,
        metric: str,
    ) -> TimeseriesPoint | None:
        """Retrieve the most recent reading for a metric.

        Args:
            device_id: Sensor/device NGSI-LD entity ID.
            metric: Metric name.

        Returns:
            TimeseriesPoint if data exists, None otherwise.
        """
        if self._client is None:
            raise RuntimeError("Redis client not initialised")

        key = self._key(device_id, metric)
        raw = await self._client.zrevrange(key, 0, 0)

        if raw:
            try:
                data = json.loads(raw[0])
                return TimeseriesPoint(ts=data["ts"], value=data["v"])
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Corrupt Redis entry in %s: %s — %s", key, raw[0], exc)
        return None

    async def get_soil_water(self, parcel_id: str) -> float | None:
        """Get stored soil water content for a parcel (mm)."""
        if self._client is None:
            return None
        try:
            val = await self._client.get(f"{self._prefix}sw:{parcel_id}")
            return float(val) if val else None
        except Exception as exc:
            logger.warning("redis_state.get_soil_water: failed for parcel %s — returning None: %s", parcel_id, exc)
            return None

    async def set_soil_water(self, parcel_id: str, sw_mm: float) -> None:
        """Store soil water content for a parcel (mm). TTL 7 days."""
        if self._client is None:
            return
        try:
            await self._client.set(
                f"{self._prefix}sw:{parcel_id}",
                str(sw_mm),
                ex=86400 * 7,
            )
        except Exception as exc:
            logger.warning("redis_state.set_soil_water: failed for parcel %s — state not persisted: %s", parcel_id, exc)

    async def get_irrigation_24h(self, entity_id: str) -> float:
        """Total irrigation volume in last 24h from Redis sliding window."""
        if self._client is None:
            return 0.0
        try:
            readings = await self.get_window(entity_id, "irrigationVolume", hours=24)
            if readings:
                return sum(r.value for r in readings)
        except Exception as exc:
            logger.warning("redis_state.get_irrigation_24h: failed for entity %s — returning 0.0: %s", entity_id, exc)
        return 0.0

    async def health_check(self) -> dict:
        """Check Redis connectivity."""
        if self._client is None:
            return {"redis": "not_connected"}
        try:
            await self._client.ping()
            return {"redis": "connected"}
        except Exception as exc:
            return {"redis": "error", "detail": str(exc)}
