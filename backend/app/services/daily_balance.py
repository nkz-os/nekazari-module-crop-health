"""Daily FAO-56 soil water bucket: one step per closed day, corrected by probes.

The state is ``{"date", "sw_mm"}`` in Redis. Only this module advances it, under
a short lock shared with the sensor correction, so a webhook arriving during the
04:00 step skips instead of racing it and the saved date never moves backwards.
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
BALANCE_LOCK_TTL_S = 120
# The day's flows saved with the state: all four, or the read-back has none.
DAY_FLOWS = ("precip_mm", "etc_mm", "actual_et_mm", "deep_percolation_mm")
# Everything a correction must carry over unchanged.
STATE_EXTRAS = DAY_FLOWS + ("root_depth_mm",)


def _lock_key(tenant_id: str, parcel_id: str) -> str:
    return f"swd-lock:{tenant_id}:{parcel_id}"


def step_day(
    sw_prev: float | None,
    precip_mm: float,
    et0_mm: float,
    kc: float,
    soil,
    root_depth_mm: float,
    depletion_p: float,
) -> SoilWaterBalanceResult:
    """One closed day; ``sw_prev=None`` is the engine cold start."""
    return soil_water_balance(
        sw_yesterday=sw_prev,
        precip_mm=precip_mm,
        irrigation_mm=0.0,
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
) -> SoilWaterBalanceResult | None:
    """Step the stored balance up to yesterday; None when nothing trustworthy exists."""
    key = _lock_key(tenant_id, parcel_id)
    acquired = await redis_state.try_lock(key, BALANCE_LOCK_TTL_S)
    if not acquired:
        logger.info(
            "daily_balance: lock not acquired (%s) for %s/%s, skipping", acquired, tenant_id, parcel_id
        )
        return None
    try:
        try:
            state = await redis_state.get_balance_state(tenant_id, parcel_id)
        except StoreError as exc:
            logger.warning(
                "daily_balance: state unreadable for %s/%s, skipping: %s", tenant_id, parcel_id, exc
            )
            return None

        yesterday = today - timedelta(days=1)
        state_result = None
        if state is not None and date.fromisoformat(state["date"]) >= yesterday - timedelta(days=SPINUP_DAYS):
            # Only a state inside the replay window may stand in for today's balance.
            state_result = balance_from_stored(state, soil, root_depth_mm, depletion_p)
            last_saved = date.fromisoformat(state["date"])
            start = last_saved + timedelta(days=1)
            sw = state["sw_mm"]
        else:
            start = yesterday - timedelta(days=SPINUP_DAYS - 1)
            sw = None

        if start > yesterday:
            return state_result

        daily = await fetch(tenant_id, parcel_id, start, yesterday)
        if daily is None:
            logger.warning(
                "daily_balance: weather unavailable for %s/%s, keeping previous state",
                tenant_id, parcel_id,
            )
            return _low(state_result) if state_result is not None else None

        result = None
        last_day = None
        day = start
        while day <= yesterday:
            precip, et0 = daily.get(day.isoformat(), (None, None))
            if precip is None or et0 is None:
                logger.warning(
                    "daily_balance: no rain/ET0 for %s/%s on %s, stepping stopped",
                    tenant_id, parcel_id, day.isoformat(),
                )
                break
            result = step_day(sw, precip, et0, kc, soil, root_depth_mm, depletion_p)
            sw = result.sw_mm
            last_day = day
            day += timedelta(days=1)

        if result is None:
            return _low(state_result) if state_result is not None else None

        await redis_state.set_balance_state(
            tenant_id, parcel_id, last_day.isoformat(), result.sw_mm,
            root_depth_mm=root_depth_mm, **day_flows(result),
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
) -> float | None:
    """Pull the stored water toward the probe mean; the state date is unchanged."""
    used = valid_theta_readings(readings, now_ts)
    if not used:
        return None
    theta = sum(t for _, t in used) / len(used)
    sw = min(max((theta - soil.wilting_point) * root_depth_mm, 0.0), awc_mm)

    key = _lock_key(tenant_id, parcel_id)
    if not await redis_state.try_lock(key, BALANCE_LOCK_TTL_S):
        return None
    try:
        try:
            state = await redis_state.get_balance_state(tenant_id, parcel_id)
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
        )
        return sw
    finally:
        await redis_state.unlock(key)
