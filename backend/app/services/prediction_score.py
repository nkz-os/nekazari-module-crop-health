"""Compare logged yield predictions with the harvest recorded for the same crop cycle.

Pure functions, no I/O: they only read the values they are given and never
write anything. A value that is missing or not numeric stays None and nothing
is computed from it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.prediction_log import PredictionRecord

# Same value as the SDK's lifecycle marker for perennial crops (nkz_platform_sdk.crop_cycles).
PERENNIAL = "perennial"
SCORED_UNIT = "t/ha"


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _date(v: Any) -> date | None:
    if not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def _bound(cycle: dict, side: str) -> date | None:
    block = cycle.get(side)
    return _date(block.get("date")) if isinstance(block, dict) else None


def _prefer(candidates: list[dict], species: str | None) -> dict:
    if species:
        for c in candidates:
            if c.get("species") == species:
                return c
    return candidates[0]


def pick_cycle(cycles: list[dict], season_start: date, last_as_of: date | None,
               species: str | None = None) -> tuple[dict | None, str | None]:
    """The cycle starting on season_start ("exact"), else one covering last_as_of ("by_date").

    Several cycles can share a start date or overlap (a cover crop next to the
    main crop, an annual under a perennial): the one of the predicted species wins.
    """
    exact = [c for c in cycles if _bound(c, "start") == season_start]
    if exact:
        return _prefer(exact, species), "exact"
    if last_as_of is not None:
        covering = []
        for c in cycles:
            start, end = _bound(c, "start"), _bound(c, "end")
            if start is not None and start <= last_as_of and (end is None or end >= last_as_of):
                covering.append(c)
        if covering:
            return _prefer(covering, species), "by_date"
    return None, None


def observed_harvest(cycle: dict | None, parcel: dict | None) -> tuple[dict | None, str | None]:
    """Observed yield in t/ha from the cycle's harvested kg and the parcel area (ha), or a reason."""
    if cycle is None:
        return None, "cycle_not_found"
    if cycle.get("lifecycle") == PERENNIAL:
        return None, "perennial_not_supported"
    weight = _num(cycle.get("harvested_weight_kg"))
    if weight is None or weight <= 0:
        return None, "no_harvest_recorded"
    area = _num(parcel.get("area")) if isinstance(parcel, dict) else None
    if area is None or area <= 0:
        return None, "area_unavailable"
    end = cycle.get("end")
    return {
        "harvest_date": end.get("date") if isinstance(end, dict) else None,
        "weight_kg": weight,
        "area_ha": area,
        "yield_t_ha": round(weight / area / 1000, 3),
        "basis": "as_delivered",
        "completeness": "unknown",
    }, None


def score_estimate(est: dict, observed_t_ha: float | None) -> dict:
    """One estimate of a logged row against the observed yield; unknowns stay None."""
    pct = est.get("percentiles") if isinstance(est.get("percentiles"), dict) else {}
    rng = est.get("range") if isinstance(est.get("range"), dict) else {}
    moist = est.get("moisture") if isinstance(est.get("moisture"), dict) else {}
    val = est.get("validation") if isinstance(est.get("validation"), dict) else {}
    p10, p50, p90 = _num(pct.get("p10")), _num(pct.get("p50")), _num(pct.get("p90"))
    low, high = _num(rng.get("low")), _num(rng.get("high"))
    unit = est.get("unit")
    obs = _num(observed_t_ha) if unit == SCORED_UNIT else None

    error_t = error_pct = within_pct = within_rng = distance = None
    if obs is not None:
        if p50 is not None:
            error_t = round(p50 - obs, 3)
            if obs != 0:
                error_pct = round(100 * (p50 - obs) / obs, 1)
        if p10 is not None and p90 is not None:
            within_pct = p10 <= obs <= p90
        if low is not None and high is not None:
            within_rng = low <= obs <= high
            distance = 0.0 if within_rng else (round(obs - high, 3) if obs > high else round(obs - low, 3))
    return {
        "provider_id": est.get("provider_id"), "basis": est.get("basis"),
        "validation_status": val.get("status"), "unit": unit, "moisture_pct": _num(moist.get("pct")),
        "p10": p10, "p50": p50, "p90": p90, "low": low, "high": high,
        "error_t_ha": error_t, "error_pct": error_pct, "within_p10_p90": within_pct,
        "within_range": within_rng, "distance_to_range_t_ha": distance,
    }


def score_rows(records: list[PredictionRecord], observed: dict | None) -> list[dict]:
    """One item per logged row with every estimate scored against the observed yield."""
    obs_yield = observed.get("yield_t_ha") if observed else None
    harvest = _date(observed.get("harvest_date")) if observed else None
    out = []
    for r in records:
        ests = r.payload.get("estimates") if isinstance(r.payload, dict) else None
        out.append({
            "as_of": r.as_of.isoformat(),
            "emitted_at": r.emitted_at.isoformat() if r.emitted_at else None,
            "model": r.model, "model_version": r.model_version,
            "lead_days": (harvest - r.as_of).days if harvest else None,
            "estimates": [score_estimate(e, obs_yield) for e in ests if isinstance(e, dict)]
            if isinstance(ests, list) else [],
        })
    return out
