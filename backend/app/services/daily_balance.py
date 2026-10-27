"""Daily FAO-56 soil water bucket: one step per closed day, corrected by probes.

The state in Redis is ``{"date", "sw_mm"}`` plus the last day's flows, the root
depth and an anchor (``anchor_date``, ``anchor_sw_mm``, ``anchor_root_depth_mm``):
the water at the end of an older day. Each scheduled run replays from the anchor
to yesterday with the latest rain, ET0 and irrigation, so late records reach the
balance, then moves the anchor to the latest stepped day <= yesterday - 7. A probe
correction becomes the anchor, so the replay never undoes it. A replay stopped by a
gap on an already-stepped day steps on from the saved day and keeps the anchor.
Only the scheduled run writes the state (step, then correction), each under a
short lock, and the saved date never moves backwards.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date, timedelta

from app.engines.soil_water_balance import SoilWaterBalanceResult, soil_water_balance
from app.engines.under_panel_stress import valid_theta_readings
from app.services.redis_state import StoreError

logger = logging.getLogger(__name__)

SPINUP_DAYS = 30
REPLAY_DAYS = 7
BALANCE_LOCK_TTL_S = 120
# The day's flows saved with the state: all four, or the read-back has none.
DAY_FLOWS = ("precip_mm", "etc_mm", "actual_et_mm", "deep_percolation_mm")
# Everything a correction must carry over unchanged.
STATE_EXTRAS = DAY_FLOWS + ("root_depth_mm",)


def _lock_key(tenant_id: str, parcel_id: str, zone_id: str | None = None) -> str:
    base = f"swd-lock:{tenant_id}:{parcel_id}"
    return f"{base}:{zone_id}" if zone_id else base


def soil_with_overrides(soil, fc: float | None, wp: float | None):
    """The soil with a zone's own field capacity / wilting point where given."""
    update = {}
    if fc is not None:
        update["field_capacity"] = fc
    if wp is not None:
        update["wilting_point"] = wp
    return soil.model_copy(update=update) if update else soil


def _zone_kwargs(zone_id: str | None) -> dict:
    """Extra Redis arguments for a zone's state; none for the parcel's (as before zones)."""
    return {"zone_id": zone_id} if zone_id else {}


def step_day(
    sw_prev: float | None,
    precip_mm: float,
    et0_mm: float,
    kc: float,
    soil,
    root_depth_mm: float,
    depletion_p: float,
    irrigation_mm: float = 0.0,
) -> SoilWaterBalanceResult:
    """One closed day; ``sw_prev=None`` is the engine cold start."""
    return soil_water_balance(
        sw_yesterday=sw_prev,
        precip_mm=precip_mm,
        irrigation_mm=irrigation_mm,
        etc_mm=et0_mm * kc,
        fc=soil.field_capacity,
        wp=soil.wilting_point,
        root_depth_mm=root_depth_mm,
        depletion_fraction_p=depletion_p,
        eto_mm=et0_mm,
        kc=kc,
    )


def balance_from_state(
    sw_mm: float,
    soil,
    root_depth_mm: float,
    depletion_p: float,
    flows: dict | None = None,
) -> SoilWaterBalanceResult:
    """The stored state read as a balance: Ks and stress from it, without stepping.

    Inflow, ETc, ETa and percolation (= excess) are the saved day's when all four
    are in ``flows``; otherwise they are unknown (``day_flows_known=False``),
    never a 0 mm read as real.
    """
    result = soil_water_balance(
        sw_yesterday=sw_mm,
        precip_mm=0.0,
        irrigation_mm=0.0,
        etc_mm=0.0,
        fc=soil.field_capacity,
        wp=soil.wilting_point,
        root_depth_mm=root_depth_mm,
        depletion_fraction_p=depletion_p,
    )
    if not flows or any(flows.get(k) is None for k in DAY_FLOWS):
        return dataclasses.replace(result, day_flows_known=False)
    percolation = round(flows["deep_percolation_mm"], 2)
    return dataclasses.replace(
        result,
        inflow_mm=round(flows["precip_mm"], 2),
        etc_mm=round(flows["etc_mm"], 2),
        actual_et_mm=round(flows["actual_et_mm"], 2),
        deep_percolation_mm=percolation,
        excess_mm=percolation,  # the engine's excess is the percolation
    )


def day_flows(result: SoilWaterBalanceResult) -> dict | None:
    """The day's flows of a balance, in the state's keys; None when unknown."""
    if not result.day_flows_known:
        return None
    return {
        "precip_mm": result.inflow_mm,
        "etc_mm": result.etc_mm,
        "actual_et_mm": result.actual_et_mm,
        "deep_percolation_mm": result.deep_percolation_mm,
    }


def balance_from_stored(
    state: dict, soil, root_depth_mm: float, depletion_p: float
) -> SoilWaterBalanceResult:
    """A stored state read as a balance.

    The water refers to the root depth it was saved with; ``root_depth_mm`` (the
    caller's) applies only to a state saved without one.
    """
    saved_root = state.get("root_depth_mm")
    if isinstance(saved_root, (int, float)) and saved_root > 0:
        root_depth_mm = float(saved_root)
    return balance_from_state(state["sw_mm"], soil, root_depth_mm, depletion_p, state)


def _low(result: SoilWaterBalanceResult) -> SoilWaterBalanceResult:
    return dataclasses.replace(result, soil_moisture_confidence="low")


def _positive(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _anchor(state: dict | None, tenant_id: str, parcel_id: str) -> tuple[date, float, float | None] | None:
    """The state's anchor (day, water, root depth); None when absent or malformed."""
    if not state or state.get("anchor_date") is None:
        return None
    sw = state.get("anchor_sw_mm")
    try:
        day = date.fromisoformat(state["anchor_date"])
        if isinstance(sw, bool) or not isinstance(sw, (int, float)):
            raise ValueError("anchor_sw_mm is not a number")
    except (TypeError, ValueError) as exc:
        logger.warning("daily_balance: malformed anchor for %s/%s, ignored: %s", tenant_id, parcel_id, exc)
        return None
    return day, float(sw), _positive(state.get("anchor_root_depth_mm"))


async def advance_daily_balance(
    redis_state,
    tenant_id: str,
    parcel_id: str,
    *,
    soil,
    root_depth_mm: float,
    depletion_p: float,
    kc: float,
    today: date,
    fetch,
    fetch_irrigation=None,
    zone_id: str | None = None,
    zone_version: str | None = None,
    eto_daily: dict[date, float] | None = None,
    fc: float | None = None,
    wp: float | None = None,
) -> SoilWaterBalanceResult | None:
    """Replay the stored balance from its anchor up to yesterday; None when nothing trustworthy exists.

    ``fetch_irrigation=None`` means no irrigation source (every day 0 mm).

    With ``zone_id`` the state is the zone's own. ``eto_daily`` replaces the
    parcel ET0 on the days it has, ``fc``/``wp`` the soil's; rain, irrigation, Kc
    and root depth stay the parcel's. A stored ``zone_version`` different from
    ``zone_version`` (the zone changed) restarts from the parcel's state.
    """
    soil = soil_with_overrides(soil, fc, wp)
    zkw = _zone_kwargs(zone_id)
    key = _lock_key(tenant_id, parcel_id, zone_id)
    acquired = await redis_state.try_lock(key, BALANCE_LOCK_TTL_S)
    if not acquired:
        logger.info(
            "daily_balance: lock not acquired (%s) for %s/%s, skipping", acquired, tenant_id, parcel_id
        )
        return None
    try:
        try:
            state = await redis_state.get_balance_state(tenant_id, parcel_id, **zkw)
            if zone_id and state is not None and state.get("zone_version") != zone_version:
                logger.info(
                    "daily_balance: reason=zone_version_changed tenant=%s parcel=%s zone=%s stored=%s received=%s",
                    tenant_id, parcel_id, zone_id, state.get("zone_version"), zone_version,
                )
                parcel_state = await redis_state.get_balance_state(tenant_id, parcel_id)
                if parcel_state is None:
                    logger.info(
                        "daily_balance: reason=zone_version_changed fallback=fresh tenant=%s parcel=%s zone=%s",
                        tenant_id, parcel_id, zone_id,
                    )
                # No parcel state: the old zone state is dropped too (fresh anchor).
                state = parcel_state
        except StoreError as exc:
            logger.warning(
                "daily_balance: state unreadable for %s/%s, skipping: %s", tenant_id, parcel_id, exc
            )
            return None

        yesterday = today - timedelta(days=1)
        window_start = yesterday - timedelta(days=SPINUP_DAYS)
        state_result = None
        state_day = None
        if state is not None and date.fromisoformat(state["date"]) >= window_start:
            # Only a state inside the replay window may stand in for today's balance.
            state_result = balance_from_stored(state, soil, root_depth_mm, depletion_p)
            state_day = date.fromisoformat(state["date"])

        # Replay base: the anchor, else the state itself (saved before anchors), else spin-up.
        # The anchor root only records the depth its water was saved at; steps use the caller's.
        anchor = _anchor(state, tenant_id, parcel_id)
        if anchor is not None and anchor[0] >= window_start:
            base = anchor
        elif state_day is not None:
            base = (state_day, state["sw_mm"], _positive(state.get("root_depth_mm")) or root_depth_mm)
        else:
            base = None
        if base is not None:
            start = base[0] + timedelta(days=1)
            sw = base[1]
        else:
            start = yesterday - timedelta(days=SPINUP_DAYS - 1)
            sw = None

        if start > yesterday:
            return state_result

        daily = await fetch(tenant_id, parcel_id, start, yesterday)
        if daily is not None and eto_daily:
            daily = dict(daily)
            for day, eto in eto_daily.items():
                row = daily.get(day.isoformat())
                if row is not None and row[0] is not None:
                    daily[day.isoformat()] = (row[0], eto)
        if daily is None:
            logger.warning(
                "daily_balance: weather unavailable for %s/%s, keeping previous state",
                tenant_id, parcel_id,
            )
            return _low(state_result) if state_result is not None else None
        irrigation = {}
        if fetch_irrigation is not None:
            irrigation = await fetch_irrigation(tenant_id, parcel_id, start, yesterday)
            if irrigation is None:
                logger.warning(
                    "daily_balance: irrigation unavailable for %s/%s, keeping previous state",
                    tenant_id, parcel_id,
                )
                return _low(state_result) if state_result is not None else None

        anchor_limit = yesterday - timedelta(days=REPLAY_DAYS)

        def step_from(day: date, sw: float | None):
            """Step from ``day`` to yesterday; stops at the first day without rain or ET0."""
            result = last_day = anchor = gap = None
            while day <= yesterday:
                precip, et0 = daily.get(day.isoformat(), (None, None))
                if precip is None or et0 is None:
                    logger.warning(
                        "daily_balance: no rain/ET0 for %s/%s on %s, stepping stopped",
                        tenant_id, parcel_id, day.isoformat(),
                    )
                    gap = day
                    break
                result = step_day(
                    sw, precip, et0, kc, soil, root_depth_mm, depletion_p,
                    irrigation_mm=irrigation.get(day.isoformat(), 0.0),
                )
                sw = result.sw_mm
                last_day = day
                if day <= anchor_limit:
                    anchor = (day, result.sw_mm, root_depth_mm)
                day += timedelta(days=1)
            return result, last_day, anchor, gap

        result, last_day, stepped_anchor, gap = step_from(start, sw)
        new_anchor = stepped_anchor or base
        if state_day is not None and gap is not None and gap <= state_day:
            # A gap on an old, already-stepped day: never move the state backwards; step on
            # from the saved day and keep the anchor so the next run retries the replay.
            logger.warning(
                "daily_balance: replay of %s/%s stopped at %s before the saved %s, stepping on from the saved day",
                tenant_id, parcel_id, gap.isoformat(), state_day.isoformat(),
            )
            result, last_day, _, _ = step_from(state_day + timedelta(days=1), state["sw_mm"])
            new_anchor = base

        if result is None:
            return _low(state_result) if state_result is not None else None

        await redis_state.set_balance_state(
            tenant_id, parcel_id, last_day.isoformat(), result.sw_mm,
            root_depth_mm=root_depth_mm, **day_flows(result),
            anchor_date=new_anchor[0].isoformat(), anchor_sw_mm=new_anchor[1],
            anchor_root_depth_mm=new_anchor[2],
            **zkw, **({"zone_version": zone_version} if zone_id else {}),
        )
        return _low(result) if last_day < yesterday else result
    finally:
        await redis_state.unlock(key)


async def correct_balance_state(
    redis_state,
    tenant_id: str,
    parcel_id: str,
    readings: list,
    soil,
    root_depth_mm: float,
    awc_mm: float,
    now_ts: float,
    zone_id: str | None = None,
) -> float | None:
    """Pull the stored water toward the probe mean; the state date is unchanged.

    With ``zone_id`` it corrects that zone's state only.

    The corrected water becomes the anchor, so the next replay starts from it.
    """
    used = valid_theta_readings(readings, now_ts)
    if not used:
        return None
    theta = sum(t for _, t in used) / len(used)
    sw = min(max((theta - soil.wilting_point) * root_depth_mm, 0.0), awc_mm)

    key = _lock_key(tenant_id, parcel_id, zone_id)
    zkw = _zone_kwargs(zone_id)
    if not await redis_state.try_lock(key, BALANCE_LOCK_TTL_S):
        return None
    try:
        try:
            state = await redis_state.get_balance_state(tenant_id, parcel_id, **zkw)
        except StoreError as exc:
            logger.warning(
                "daily_balance: state unreadable for %s/%s, no correction: %s", tenant_id, parcel_id, exc
            )
            return None
        if state is None:
            return None
        await redis_state.set_balance_state(
            tenant_id, parcel_id, state["date"], sw,
            **{k: state.get(k) for k in STATE_EXTRAS},
            anchor_date=state["date"], anchor_sw_mm=sw, anchor_root_depth_mm=root_depth_mm,
            **zkw, **({"zone_version": state.get("zone_version")} if zone_id else {}),
        )
        return sw
    finally:
        await redis_state.unlock(key)
