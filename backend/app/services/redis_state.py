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
import math
import time
from dataclasses import dataclass

import redis.asyncio as aioredis

from app.config import get_settings
from app.schemas import TimeseriesPoint

logger = logging.getLogger(__name__)


PARCEL_READING_TTL_S = 7200
SHADE_TTL_S = 3 * 86400
# Readings stamped further ahead than this are gateway clock skew, not data.
MAX_FUTURE_SKEW_S = 300.0


@dataclass(frozen=True)
class ParcelReading:
    device_id: str
    ts: float
    value: float
    unit_code: str | None


class StoreError(Exception):
    """Redis could not be read: never confuse it with an absent key."""


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

    async def set_parcel_reading(
        self,
        tenant_id: str,
        parcel_id: str,
        context: str,
        metric: str,
        device_id: str,
        ts: float,
        value: float,
        unit_code: str | None,
    ) -> None:
        """Latest reading of a metric per device, grouped by parcel (TTL 2 h)."""
        if self._client is None:
            return
        key = f"{self._prefix}parcel:{tenant_id}:{parcel_id}:{context}:{metric}"
        now = time.time()
        if ts - now > MAX_FUTURE_SKEW_S:
            logger.warning(
                "redis_state.set_parcel_reading: future-stamped reading ignored "
                "(device=%s metric=%s ts=%s)", device_id, metric, ts,
            )
            return
        try:
            # An older, out-of-order reading must not replace a newer one.
            prev = await self._client.hget(key, device_id)
            if prev:
                try:
                    prev_ts = float(json.loads(prev)["ts"])
                    # A stored entry itself from the future is poison: replace it.
                    if prev_ts > ts and prev_ts - now <= MAX_FUTURE_SKEW_S:
                        return
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    logger.debug("Corrupt Redis entry in %s overwritten: %s", key, exc)
            await self._client.hset(
                key, device_id, json.dumps({"ts": ts, "v": value, "u": unit_code})
            )
            await self._client.expire(key, PARCEL_READING_TTL_S)
        except Exception as exc:
            logger.warning("redis_state.set_parcel_reading: failed for %s: %s", key, exc)

    async def get_parcel_readings(
        self,
        tenant_id: str,
        parcel_id: str,
        context: str,
        metric: str,
        max_age_s: float,
        now_ts: float,
    ) -> list[ParcelReading]:
        """Readings of the parcel no older than max_age_s and not from the future."""
        if self._client is None:
            return []
        key = f"{self._prefix}parcel:{tenant_id}:{parcel_id}:{context}:{metric}"
        try:
            raw = await self._client.hgetall(key)
        except Exception as exc:
            logger.warning("redis_state.get_parcel_readings: failed for %s: %s", key, exc)
            return []
        out: list[ParcelReading] = []
        for device_id, member in raw.items():
            try:
                data = json.loads(member)
                ts = float(data["ts"])
                value = float(data["v"])
                unit = data.get("u")
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Corrupt Redis entry in %s: %s", key, exc)
                continue
            if now_ts - ts > max_age_s or ts - now_ts > MAX_FUTURE_SKEW_S:
                continue
            out.append(ParcelReading(device_id=device_id, ts=ts, value=value, unit_code=unit))
        return out

    async def add_shade_sample(
        self, tenant_id: str, parcel_id: str, day: str, par_under: float, par_open: float,
        ts: float | None = None,
    ) -> None:
        """Add one (under-panel, open-sky) PAR pair to the parcel's daily sums.

        ``ts`` is the PAR sample time; the latest one seen that day is kept.
        """
        if self._client is None:
            return
        key = f"{self._prefix}shade:{tenant_id}:{parcel_id}:{day}"
        try:
            newest = None
            if ts is not None and math.isfinite(ts):
                prev = await self._client.hget(key, "last_ts")
                try:
                    prev_ts = float(prev) if prev is not None else None
                except (TypeError, ValueError):
                    prev_ts = None
                newest = ts if prev_ts is None or ts > prev_ts else None
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.hincrbyfloat(key, "under", par_under)
                pipe.hincrbyfloat(key, "open", par_open)
                if newest is not None:
                    pipe.hset(key, "last_ts", str(newest))
                pipe.expire(key, SHADE_TTL_S)
                await pipe.execute()
        except Exception as exc:
            logger.warning("redis_state.add_shade_sample: failed for %s: %s", key, exc)

    async def get_daily_shade(self, tenant_id: str, parcel_id: str, day: str) -> float | None:
        """1 - sum(under)/sum(open) clamped to [0, 1]; None without open-sky light."""
        if self._client is None:
            return None
        key = f"{self._prefix}shade:{tenant_id}:{parcel_id}:{day}"
        try:
            raw = await self._client.hgetall(key)
            open_sum = float(raw.get("open", 0) or 0)
            under_sum = float(raw.get("under", 0) or 0)
        except Exception as exc:
            logger.warning("redis_state.get_daily_shade: failed for %s: %s", key, exc)
            return None
        if open_sum <= 0:
            return None
        return min(1.0, max(0.0, 1.0 - under_sum / open_sum))

    async def get_daily_shade_ts(self, tenant_id: str, parcel_id: str, day: str) -> float | None:
        """Timestamp of the latest PAR sample behind the day's shade; None if unknown."""
        if self._client is None:
            return None
        key = f"{self._prefix}shade:{tenant_id}:{parcel_id}:{day}"
        try:
            raw = await self._client.hget(key, "last_ts")
            return float(raw) if raw is not None else None
        except Exception as exc:
            logger.warning("redis_state.get_daily_shade_ts: failed for %s: %s", key, exc)
            return None

    @property
    def available(self) -> bool:
        return self._client is not None

    async def get_json(self, key: str) -> dict | None:
        """JSON value under the module prefix; None only when the key is absent.

        Raises StoreError when Redis or the stored JSON cannot be read, so a
        caller never takes a failed read for "nothing stored" and overwrites it.
        """
        if self._client is None:
            raise StoreError("redis not connected")
        try:
            raw = await self._client.get(f"{self._prefix}{key}")
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("redis_state.get_json: failed for %s: %s", key, exc)
            raise StoreError(str(exc)) from exc

    async def set_json(self, key: str, value: dict, ttl_s: int) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.set(f"{self._prefix}{key}", json.dumps(value), ex=ttl_s)
            return True
        except Exception as exc:
            logger.warning("redis_state.set_json: failed for %s — not stored: %s", key, exc)
            return False

    async def get_balance_state(self, tenant_id: str, parcel_id: str) -> dict | None:
        """Daily soil water state ``{"date", "sw_mm"}``; raises StoreError like get_json."""
        return await self.get_json(f"swd:{tenant_id}:{parcel_id}")

    async def set_balance_state(
        self,
        tenant_id: str,
        parcel_id: str,
        day: str,
        sw_mm: float,
        precip_mm: float | None = None,
        etc_mm: float | None = None,
        actual_et_mm: float | None = None,
        deep_percolation_mm: float | None = None,
        root_depth_mm: float | None = None,
        anchor_date: str | None = None,
        anchor_sw_mm: float | None = None,
        anchor_root_depth_mm: float | None = None,
    ) -> bool:
        """Store the soil water (mm) at the end of ``day``; TTL 40 days.

        The day's flows, the root depth the water refers to and the replay anchor
        (water at the end of an older day) are stored when given.
        """
        value: dict = {"date": day, "sw_mm": sw_mm}
        extras = {
            "precip_mm": precip_mm,
            "etc_mm": etc_mm,
            "actual_et_mm": actual_et_mm,
            "deep_percolation_mm": deep_percolation_mm,
            "root_depth_mm": root_depth_mm,
            "anchor_date": anchor_date,
            "anchor_sw_mm": anchor_sw_mm,
            "anchor_root_depth_mm": anchor_root_depth_mm,
        }
        value.update({k: v for k, v in extras.items() if v is not None})
        return await self.set_json(f"swd:{tenant_id}:{parcel_id}", value, 40 * 86400)

    async def try_lock(self, key: str, ttl_s: int) -> bool | None:
        """True if acquired, False if held by someone else, None if Redis is down."""
        if self._client is None:
            return None
        try:
            return bool(await self._client.set(f"{self._prefix}{key}", "1", ex=ttl_s, nx=True))
        except Exception as exc:
            logger.warning("redis_state.try_lock: failed for %s: %s", key, exc)
            return None

    async def unlock(self, key: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.delete(f"{self._prefix}{key}")
        except Exception as exc:
            logger.warning("redis_state.unlock: failed for %s: %s", key, exc)

    async def is_locked(self, key: str) -> bool:
        if self._client is None:
            return False
        try:
            return bool(await self._client.exists(f"{self._prefix}{key}"))
        except Exception as exc:
            logger.warning("redis_state.is_locked: failed for %s: %s", key, exc)
            return False

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
