"""
Pipeline Orchestrator — Webhook → Normalise → Enrich → Compute → Publish.

This is the core orchestration layer that wires together:
1. Redis temporal state
2. Context clients (weather, phenology)
3. Biophysical engines (CWSI, MDS, Water Balance)
4. FIWARE publisher

Architecture note: This module COMPLEMENTS the risk-worker's
water_stress_model.py. The risk-worker uses batch meteorological data
(precip-eto balance); this module adds real-time canopy-level sensing
(IR temperature → CWSI, dendrómetro → MDS) for precision agriculture.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from app.engines.mds_model import calculate_mds_from_readings
from app.engines.phenology_progress import derive_stage_from_gdd
from app.engines.water_stress import cwsi_with_weather
from app.schemas import (
    CropHealthAssessment,
    MetricType,
    RecommendedAction,
    Severity,
    StageTable,
    ThermalStressResult,
    VHIClimatologyWindow,
    VigorResult as VigorResultSchema,
)
from app.services import context_client
from app.services.context_client import get_phenology_params, get_weather_snapshot
from app.services.fiware_publisher import publish_assessment
from app.services.meteo_context import resolve_meteo_context
from app.services.redis_state import RedisState
from app.services.zonation import (
    resolve_zones,
    is_whole_parcel,
    sensors_in_zone,
    consolidate_sensor_readings,
    point_in_polygon,
    Zone,
)

logger = logging.getLogger(__name__)


# FAO-56 Table 22: Depletion fraction p by crop family
_DEPLETION_FRACTION_P: dict[str, float] = {
    "TRZAX": 0.55,  # wheat
    "HORVX": 0.55,  # barley
    "ZEAMX": 0.55,  # maize
    "OLEU": 0.65,   # olive
    "VITIS": 0.45,  # vine
    "ORYSA": 0.20,  # rice
    "SOLTU": 0.30,  # potato
    "ALLCE": 0.30,  # onion
    "LYPES": 0.35,  # tomato
    "MABSD": 0.50,  # apple
    "PRUND": 0.50,  # almond
    "CITSI": 0.50,  # citrus
}

def _resolve_depletion_fraction(crop_context) -> float:
    """Resolve FAO-56 depletion fraction p from crop context.
    
    Uses EPPO code from BioOrchestrator crop context to look up species-specific
    p values from FAO-56 Table 22. Falls back to 0.50 (generic).
    """
    if crop_context and crop_context.crop and crop_context.crop.eppo:
        return _DEPLETION_FRACTION_P.get(crop_context.crop.eppo, 0.50)
    return 0.50


def _determine_overall_severity(assessment: CropHealthAssessment) -> Severity:
    """Determine overall severity from individual engine results.

    Strategy: worst-case (maximum severity) across all available signals.
    """
    severities: list[Severity] = []

    if assessment.cwsi:
        if assessment.cwsi.cwsi >= 0.7:
            severities.append(Severity.CRITICAL)
        elif assessment.cwsi.cwsi >= 0.5:
            severities.append(Severity.HIGH)
        elif assessment.cwsi.cwsi >= 0.3:
            severities.append(Severity.MEDIUM)
        else:
            severities.append(Severity.LOW)

    if assessment.mds:
        severities.append(assessment.mds.severity)

    if assessment.water_balance and assessment.water_balance.deficit:
        if assessment.water_balance.balance_mm < -15:
            severities.append(Severity.CRITICAL)
        elif assessment.water_balance.balance_mm < -5:
            severities.append(Severity.HIGH)
        else:
            severities.append(Severity.MEDIUM)

    if not severities:
        return Severity.LOW

    # Worst-case ordering
    order = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}
    return max(severities, key=lambda s: order[s])


def _determine_action(severity: Severity) -> RecommendedAction:
    """Map overall severity to recommended action."""
    return {
        Severity.LOW: RecommendedAction.NO_ACTION,
        Severity.MEDIUM: RecommendedAction.MONITOR,
        Severity.HIGH: RecommendedAction.IRRIGATE_SCHEDULED,
        Severity.CRITICAL: RecommendedAction.IRRIGATE_IMMEDIATE,
    }[severity]


# ── Root depth resolution ─────────────────────────────────────────────────

_PERENNIAL_EPPO = {
    "OLV", "OLEU", "VITIS", "PRMND", "PRMDO", "PRMPE", "CITRU",
    "PSTCI", "JUREG", "ACTDE", "PRNAR",
}
_DEFAULT_ROOT_DEPTH_PERENNIAL = 800.0
_DEFAULT_ROOT_DEPTH_ANNUAL_INITIAL = 150.0
_DEFAULT_ROOT_DEPTH_ANNUAL_MAX = 800.0
_ROOT_GROWTH_RATE_PER_GDD = 0.7


def _resolve_root_depth(species: str, gdd: float | None, crop_context: any) -> float:
    """Resolve effective root depth for the current crop and stage."""
    if crop_context and hasattr(crop_context, 'phenology'):
        phen = crop_context.phenology
        if phen and hasattr(phen, 'root_depth_mm') and phen.root_depth_mm:
            return float(phen.root_depth_mm)
    species_upper = species.upper() if species else ""
    for p in _PERENNIAL_EPPO:
        if p in species_upper:
            return _DEFAULT_ROOT_DEPTH_PERENNIAL
    if gdd and gdd > 0:
        return min(_DEFAULT_ROOT_DEPTH_ANNUAL_MAX, _DEFAULT_ROOT_DEPTH_ANNUAL_INITIAL + _ROOT_GROWTH_RATE_PER_GDD * gdd)
    return 300.0


async def trigger(
    entity_id: str,
    metric_type: str,
    redis_state: RedisState,
    parcel_id: str | None = None,
    tenant_id: str = "",
) -> CropHealthAssessment | None:
    """Execute the full inference pipeline.

    Called asynchronously when a FIWARE webhook delivers new sensor data.

    Flow:
    1. Identify the parcel associated with the sensor
    2. Fetch phenology params (cached, with fallback defaults)
    3. Fetch weather snapshot from TimescaleDB
    4. Read sensor data from Redis sliding window
    5. Execute relevant engine(s) based on metric_type
    6. Fuse results into CropHealthAssessment
    7. Publish to Orion-LD

    Args:
        entity_id: NGSI-LD device entity ID.
        metric_type: The metric that triggered this pipeline.
        redis_state: Redis client for sliding window access.
        parcel_id: If already known from webhook; else resolved from entity.
        tenant_id: Tenant ID for weather DB query.

    Returns:
        CropHealthAssessment if computed, None on error.
    """
    effective_parcel = parcel_id or _extract_parcel_from_entity(entity_id)
    if not effective_parcel:
        logger.warning("Cannot resolve parcel for entity %s — skipping", entity_id)
        return None

    logger.info(
        "Pipeline triggered: entity=%s metric=%s parcel=%s",
        entity_id,
        metric_type,
        effective_parcel,
    )

    # ── 1. Fetch context ─────────────────────────────────────────────────
    # Resolve crop/variety from BioOrchestrator crop-context
    from app.services.context_client import get_crop_context as fetch_crop_context

    species = "generic"
    variety_name = None
    management = None
    crop_context = None

    try:
        crop_context = await fetch_crop_context(
            parcel_id=effective_parcel,
            tenant_id=tenant_id,
        )
        if crop_context:
            if crop_context.crop and crop_context.crop.eppo != "unknown":
                species = crop_context.crop.eppo
            elif crop_context.crop and crop_context.crop.name:
                species = crop_context.crop.name
            variety_name = crop_context.variety.name if crop_context.variety else None
            management = crop_context.management
            if crop_context.season and crop_context.season.gdd_accumulated:
                gdd = crop_context.season.gdd_accumulated
    except Exception as exc:
        logger.warning("pipeline: crop_context fetch failed for parcel %s — using defaults: %s", effective_parcel, exc)

    # Full ordered stage table for the resolved species — shared with
    # _run_engines so the GDD-derived stage and phenology-progress deviation
    # are computed identically to the scheduled compute_assessment path.
    try:
        stage_table = await context_client.get_phenology_stages(species)
    except Exception as exc:
        logger.warning("pipeline: get_phenology_stages failed for %s — empty table: %s", species, exc)
        stage_table = {}

    # GDD with resolved season start (field-op reality > AgriCrop plan > default)
    gdd = None
    try:
        from app.services.context_client import resolve_season_start

        season_start = await resolve_season_start(effective_parcel, tenant_id)

        gdd_base_temp = stage_table.base_temp if stage_table else 10.0
        gdd_upper_cutoff = stage_table.upper_cutoff if stage_table else None
        gdd_data = await _fetch_gdd(
            tenant_id, season_start, effective_parcel,
            base_temp=gdd_base_temp,
            upper_cutoff=gdd_upper_cutoff,
        )
        if gdd_data and gdd_data.get("gdd_total"):
            gdd = float(gdd_data["gdd_total"])
    except Exception as exc:
        logger.warning("pipeline: GDD fetch failed for parcel %s — proceeding without GDD: %s", effective_parcel, exc)

    phenology = await get_phenology_params(species=species, gdd=gdd)



    from app.services.context_client import _resolve_parcel_coords
    coords = await _resolve_parcel_coords(effective_parcel, tenant_id)
    if coords:
        latitude, longitude = coords
        logger.info("Resolved parcel %s coordinates: (%.4f, %.4f)", effective_parcel, latitude, longitude)
    else:
        latitude, longitude = 0.0, 0.0
        logger.warning("Cannot resolve coordinates for parcel %s — weather from (0,0)", effective_parcel)

    weather = await get_weather_snapshot(
        latitude=latitude,
        longitude=longitude,
        tenant_id=tenant_id,
    )

    now = datetime.now(timezone.utc)

    def _mk_assessment(zone: Zone | None) -> CropHealthAssessment:
        a = CropHealthAssessment(
            parcel_id=effective_parcel,
            assessed_at=now,
            phenology_source=crop_context.phenology_source if crop_context else "default",
            crop_species=species if species != "generic" else None,
            crop_name=crop_context.crop.name if crop_context and crop_context.crop else None,
            variety_name=variety_name,
            phenology_stage=phenology.stage if phenology else None,
            gdd_accumulated=gdd,
            kc=phenology.kc if phenology else None,
            management=management,
        )
        if zone is not None:
            a.zone_id = zone.zone_id
            a.zone_urn = zone.urn
            a.zone_geometry = zone.geometry
        return a

    # ── Soil properties (benefits 1+2) ───────────────────────────────────
    from app.services.context_client import get_soil_properties

    soil = await get_soil_properties(
        parcel_id=effective_parcel,
        tenant_id=tenant_id,
    )

    root_depth_mm = _resolve_root_depth(species, gdd, crop_context)

    # Read previous soil water from Redis
    sw_yesterday = None
    if redis_state:
        try:
            sw_yesterday = await redis_state.get_soil_water(effective_parcel)
        except Exception as exc:
            logger.warning("pipeline: redis get_soil_water failed for parcel %s — sw_yesterday=None: %s", effective_parcel, exc)

    # Read irrigation volume from Redis
    irrigation_mm = 0.0
    if redis_state:
        try:
            irrigation_mm = await redis_state.get_irrigation_24h(entity_id)
        except Exception as exc:
            logger.warning("pipeline: redis get_irrigation_24h failed for entity %s — irrigation_mm=0: %s", entity_id, exc)

    # ── Resolve management zones (weather-map AgriParcelZone) ─────────────
    # Whole-parcel mode (current production reality — no zones exist until
    # weather-map zoning is enabled) is byte-identical to the legacy behaviour:
    # one parcel-level CropHealthAssessment, sensor engines + side-effects via
    # _run_engines(publish=True). The zonal branch only activates once zones
    # exist, attributing the device's window-engines (CWSI/MDS) to the device's
    # zone (point-in-polygon) and publishing per-zone + worst-zone rollup.
    parcel_geom = await context_client._resolve_parcel_geometry(effective_parcel, tenant_id)
    zones = await resolve_zones(effective_parcel, tenant_id, parcel_geom or {})

    if is_whole_parcel(zones):
        assessment = _mk_assessment(None)
        return await _run_engines(
            assessment,
            metric_type=metric_type,
            weather=weather,
            phenology=phenology,
            redis_state=redis_state,
            entity_id=entity_id,
            effective_parcel=effective_parcel,
            tenant_id=tenant_id,
            species=species,
            crop_context=crop_context,
            variety_name=variety_name,
            gdd=gdd,
            soil=soil,
            root_depth_mm=root_depth_mm,
            sw_yesterday=sw_yesterday,
            irrigation_mm=irrigation_mm,
            now=now,
            stage_table=stage_table,
            publish=True,
        )

    # Zonal: the device's window-engines run for its zone; others sensorless.
    device_coords = await _resolve_device_coords(entity_id, tenant_id)
    if device_coords is None:
        logger.warning(
            "trigger: no coordinates for device %s — its window engines (CWSI/MDS) "
            "are not attributed to a zone this event (readings persisted in Redis)",
            entity_id,
        )

    zone_results: list[CropHealthAssessment] = []
    for z in zones:
        is_sensor = device_coords is not None and point_in_polygon(
            device_coords[0], device_coords[1], z.geometry
        )
        a = _mk_assessment(z)
        try:
            await _run_engines(
                a,
                metric_type=metric_type if is_sensor else "",
                weather=weather,
                phenology=phenology,
                redis_state=redis_state if is_sensor else None,
                entity_id=entity_id if is_sensor else effective_parcel,
                effective_parcel=effective_parcel,
                tenant_id=tenant_id,
                species=species,
                crop_context=crop_context,
                variety_name=variety_name,
                gdd=gdd,
                soil=soil,
                root_depth_mm=root_depth_mm,
                sw_yesterday=sw_yesterday if is_sensor else None,
                irrigation_mm=irrigation_mm if is_sensor else 0.0,
                now=now,
                stage_table=stage_table,
                publish=False,
            )
        except Exception as exc:
            logger.warning("trigger: zone %s failed for %s — skipped: %s", z.zone_id, effective_parcel, exc)
            continue
        zone_results.append(a)
        await _publish_assessment(a.to_zone_ngsi_ld(), tenant_id)

    if not zone_results:
        logger.warning("trigger: all zones failed for %s — no assessment", effective_parcel)
        return None

    rollup = _aggregate_rollup(effective_parcel, zone_results)
    await _publish_assessment(rollup.to_ngsi_ld(), tenant_id)
    # Preserve the sensor-path derived events + parent aggregation on the rollup.
    await _emit_assessment_side_effects(
        rollup, tenant_id, now, rollup.phenology_stage or "vegetative"
    )
    return rollup


async def _run_engines(
    assessment: CropHealthAssessment,
    *,
    metric_type: str,
    weather,
    phenology,
    redis_state,
    entity_id: str,
    effective_parcel: str,
    tenant_id: str,
    species: str,
    crop_context,
    variety_name,
    gdd,
    soil,
    root_depth_mm: float,
    sw_yesterday,
    irrigation_mm: float,
    now: datetime,
    stage_table: StageTable | dict[str, tuple[float, float]] | None = None,
    publish: bool = True,
) -> CropHealthAssessment:
    """Shared engine-fusion core.

    Runs the biophysical/epidemiological engines against the pre-built
    ``assessment`` using the resolved context (weather snapshot, phenology
    params, soil, GDD, Redis sliding windows). Fuses results, classifies
    severity/action, publishes to Orion-LD, emits platform events and
    aggregates the parent parcel. Behaviour is identical to the legacy inline
    block in ``trigger`` — extracted verbatim so both the sensor path and the
    parcel-centric ``compute_assessment`` share one implementation.

    Sensorless callers pass ``entity_id == effective_parcel`` (no device);
    metric-gated branches simply do not fire, which is the intended degraded
    behaviour for a parcel with no IoT sensors.
    """

    # ── 1b. Authoritative phenology stage (shared by BOTH write paths) ────
    # When GDD and the full ordered stage table are available, the current
    # stage is derived from GDD — deterministic regardless of which path
    # (sensor webhook vs scheduled compute) writes the daily-keyed entity.
    stage_table = stage_table or {}
    if gdd is not None and stage_table:
        assessment.phenology_stage = derive_stage_from_gdd(gdd, stage_table)

    # ── 2. Execute engines ───────────────────────────────────────────────

    # CWSI (triggered by leaf temperature sensor)
    if metric_type == MetricType.LEAF_TEMPERATURE.value and weather:
        readings = await redis_state.get_window(entity_id, "leafTemperature", hours=1)
        if readings:
            latest_tc = readings[-1].value
            assessment.cwsi = cwsi_with_weather(
                temp_canopy=latest_tc,
                temp_air=weather.temp_air,
                humidity_pct=weather.humidity_pct,
                d1=phenology.d1,
                d2=phenology.d2,
            )

    # MDS (triggered by trunk diameter dendrómetro)
    if metric_type == MetricType.TRUNK_DIAMETER.value:
        readings = await redis_state.get_window(entity_id, "trunkDiameter", hours=24)
        assessment.mds = calculate_mds_from_readings(readings, mds_ref=phenology.mds_ref)

    # Soil water balance (replaces simple water balance with AWC tracking)
    if weather:
        etc_mm = weather.eto_mm * phenology.kc
        from app.engines.soil_water_balance import soil_water_balance

        # FAO-56 depletion fraction p — species-specific, with generic fallback
        depletion_p = _resolve_depletion_fraction(crop_context)

        swb = soil_water_balance(
            sw_yesterday=sw_yesterday,
            precip_mm=weather.precip_mm,
            irrigation_mm=irrigation_mm,
            etc_mm=etc_mm,
            fc=soil.field_capacity,
            wp=soil.wilting_point,
            root_depth_mm=root_depth_mm,
            depletion_fraction_p=depletion_p,
            eto_mm=weather.eto_mm,
            kc=phenology.kc,
        )
        assessment.soil_water_balance = swb
        assessment.soil_properties = soil if soil.has_data else None

        # Backward-compatible water_balance field
        from app.schemas import WaterBalanceResult
        assessment.water_balance = WaterBalanceResult(
            balance_mm=round(swb.sw_mm - swb.awc_mm, 2),
            precip_mm=round(weather.precip_mm, 2),
            etc_mm=round(etc_mm, 2),
            kc=phenology.kc,
            deficit=swb.stress_level != "none",
        )

        # Waterlogging risk (uses excess from water balance)
        if swb.excess_mm > 0:
            from app.engines.waterlogging_risk import waterlogging_risk as wl_risk
            wlr = wl_risk(
                excess_mm=swb.excess_mm,
                ksat_mm_h=soil.ksat_mm_h,
                scs_group=soil.scs_hydrologic_group,
            )
            assessment.waterlogging_risk = wlr

        # Persist current soil water to Redis for next assessment
        if redis_state:
            try:
                await redis_state.set_soil_water(effective_parcel, swb.sw_mm)
            except Exception as exc:
                logger.warning("pipeline: redis set_soil_water failed for parcel %s — state not persisted: %s", effective_parcel, exc)

    # Thermal stress (triggered by leaf temperature or opportunistically with weather)
    if weather:
        try:
            from app.engines.thermal_stress import evaluate_thermal_stress
            leaf_temp = None
            if metric_type == MetricType.LEAF_TEMPERATURE.value:
                readings = await redis_state.get_window(entity_id, "leafTemperature", hours=1)
                if readings:
                    leaf_temp = readings[-1].value
            tr = evaluate_thermal_stress(
                leaf_temp=leaf_temp,
                air_temp=weather.temp_air,
                fidelity="onsite_uncalibrated" if leaf_temp is not None else "regional_proxy",
            )
            assessment.thermal = ThermalStressResult(
                heat_stress_hours=tr.heat_stress_hours,
                frost_hours=tr.frost_hours,
                condition=tr.condition,
                severity=tr.severity,
                data_fidelity=tr.data_fidelity,
            )
        except Exception as exc:
            logger.warning("pipeline: thermal stress evaluation failed for parcel %s — skipped: %s", effective_parcel, exc)

    # Vigor (opportunistic — fetches latest vegetation index for the parcel)
    ndvi_val = None
    try:
        from app.engines.vigor import evaluate_vigor
        ndvi_val = await _fetch_parcel_ndvi(effective_parcel, tenant_id)
        if ndvi_val is not None or assessment.cwsi is not None:
            cwsi_val = assessment.cwsi.cwsi if assessment.cwsi else None
            stage_name = phenology.stage if phenology else "vegetative"
            vr = evaluate_vigor(
                ndvi=ndvi_val,
                cwsi=cwsi_val,
                stage=stage_name,
                fidelity="onsite_uncalibrated" if ndvi_val is not None else "modeled_opendata",
            )
            assessment.vigor = VigorResultSchema(
                vigor_index=vr.vigor_index,
                growth_anomaly=vr.growth_anomaly,
                index_used=vr.index_used,
                condition=vr.condition,
                data_fidelity=vr.data_fidelity,
            )
    except Exception as exc:
        logger.warning("pipeline: vigor evaluation failed for parcel %s — skipped: %s", effective_parcel, exc)

    # ── 2.4 Soil sensor readings (pass-through, no engine) ────────────
    soil_ph_val = None
    soil_ec_val = None
    soil_moisture_val = None
    soil_temp_val = None

    if metric_type in (
        MetricType.SOIL_PH.value,
        MetricType.SOIL_EC.value,
        MetricType.SOIL_MOISTURE.value,
        MetricType.SOIL_TEMPERATURE.value,
    ):
        readings = await redis_state.get_window(entity_id, metric_type, hours=1)
        if readings:
            latest = readings[-1].value
            if metric_type == MetricType.SOIL_PH.value:
                soil_ph_val = latest
            elif metric_type == MetricType.SOIL_EC.value:
                soil_ec_val = latest
            elif metric_type == MetricType.SOIL_MOISTURE.value:
                soil_moisture_val = latest
            elif metric_type == MetricType.SOIL_TEMPERATURE.value:
                soil_temp_val = latest

    # ── 2.5 VHI/ASIS Engine (Agricultural Drought Early Warning) ────────
    try:
        from datetime import datetime as dt
        from app.engines.vhi_asis import evaluate_vhi
        from app.schemas import VHIResult as VHIResultSchema
        from app.services.landsat_lst_client import LandsatTirsClient
        from app.services.context_client import get_ndvi_climatology

        temp_actual = None
        temp_source = "none"
        fidelity = "none"

        if assessment.cwsi and assessment.cwsi.temp_canopy is not None:
            temp_actual = assessment.cwsi.temp_canopy
            temp_source = "iot_canopy"
            fidelity = "onsite_calibrated"
        elif soil_temp_val is not None:
            temp_actual = soil_temp_val
            temp_source = "iot_soil"
            fidelity = "onsite_calibrated"
        else:
            lst_val = await _fetch_parcel_lst(effective_parcel, tenant_id)
            if lst_val is not None:
                temp_actual = lst_val
                temp_source = "satellite_lst"
                fidelity = "modeled_opendata"
            elif weather and weather.temp_air is not None:
                temp_actual = weather.temp_air
                temp_source = "weather_proxy"
                fidelity = "regional_proxy"
            else:
                coords = await context_client._resolve_parcel_coords(
                    effective_parcel, tenant_id,
                )
                if coords:
                    tirs_client = LandsatTirsClient()
                    lst_direct = await tirs_client.get_latest_lst(coords[0], coords[1])
                    if lst_direct is not None:
                        temp_actual = lst_direct
                        temp_source = "landsat_tirs"
                        fidelity = "modeled_opendata"

        temp_min_hist = 10.0
        temp_max_hist = 45.0

        # Resolve crop EPPO for filtered climatology
        eppo_for_climo = None
        if crop_context and crop_context.crop and crop_context.crop.eppo:
            eppo_for_climo = crop_context.crop.eppo

        current_month = dt.now(timezone.utc).month
        climo = await get_ndvi_climatology(
            parcel_id=effective_parcel,
            tenant_id=tenant_id,
            target_month=current_month,
            eppo_code=eppo_for_climo,
        )

        assessment.vhi_climatology_window = VHIClimatologyWindow(
            period_start=climo.get("period_start"),
            period_end=climo.get("period_end"),
            sample_count=climo["sample_count"],
            filter_criteria=climo["filter_criteria"],
            is_reliable=climo["is_reliable"],
            reason=climo.get("reason"),
        )

        if climo["is_reliable"] and ndvi_val is not None:
            vr = evaluate_vhi(
                ndvi_actual=ndvi_val,
                ndvi_min=climo["ndvi_p05"],
                ndvi_max=climo["ndvi_p95"],
                temp_actual=temp_actual,
                temp_min=temp_min_hist,
                temp_max=temp_max_hist,
                temp_source=temp_source,
                fidelity=fidelity,
            )
            if vr.vhi is not None:
                assessment.vhi = VHIResultSchema(
                    vci=vr.vci,
                    tci=vr.tci,
                    vhi=vr.vhi,
                    asi_pct=vr.asi_pct,
                    tci_source=vr.tci_source,
                    data_fidelity=vr.data_fidelity,
                )
        else:
            logger.info(
                "VHI skipped for parcel %s: climatology unreliable (%s)",
                effective_parcel, climo.get("reason", "unknown"),
            )
    except Exception as e:
        logger.error("VHI engine failed: %s", e)

    # ── 2.6 Compound engines (after individual engines have results) ────
    stage_name = "vegetative"  # safe default for Redis event publishing
    
    # SAR Engine
    try:
        from app.engines.sar_moisture import evaluate_sar_moisture
        from app.schemas import SARResult as SARResultSchema
        
        sar_backscatter = await _fetch_parcel_sar(effective_parcel, tenant_id)
        if sar_backscatter is not None:
            vv, vh = sar_backscatter
            sar_res = evaluate_sar_moisture(
                species_eppo=species,
                backscatter_vv=vv,
                backscatter_vh=vh,
                fidelity="modeled_opendata",
            )
            assessment.sar = SARResultSchema(
                is_flooded=sar_res.is_flooded,
                flood_stage=sar_res.flood_stage,
                surface_moisture_index=sar_res.surface_moisture_index,
                waterlogging_risk=sar_res.waterlogging_risk,
                data_fidelity=sar_res.data_fidelity,
            )
    except Exception as e:
        logger.error("SAR engine failed: %s", e)

    try:
        from app.engines.composite import evaluate_composite_stress
        thermal_sev = assessment.thermal.severity if assessment.thermal else None
        vigor_idx = assessment.vigor.vigor_index if assessment.vigor else None
        mds_ratio_val = assessment.mds.ratio if assessment.mds else None
        wb_mm = assessment.water_balance.balance_mm if assessment.water_balance else None
        cwsi_val = assessment.cwsi.cwsi if assessment.cwsi else None
        stage_name = phenology.stage if phenology else "vegetative"
        # Build Ky map from crop-context if available
        ky_by_stage = None
        if crop_context and crop_context.phenology and crop_context.phenology.stage and crop_context.phenology.ky is not None:
            ky_by_stage = {crop_context.phenology.stage: crop_context.phenology.ky}
        assessment.composite_stress = evaluate_composite_stress(
            cwsi=cwsi_val, mds_ratio=mds_ratio_val, water_balance_mm=wb_mm,
            thermal_severity=thermal_sev, vigor_index=vigor_idx,
            stage=stage_name,
            ky_override=ky_by_stage,
        )
    except Exception as exc:
        logger.warning("pipeline: composite stress evaluation failed for parcel %s — skipped: %s", effective_parcel, exc)

    try:
        from app.engines.yield_gap import evaluate_yield_gap
        from app.services.context_client import get_variety_yield_baseline

        _cwsi = assessment.cwsi.cwsi if assessment.cwsi else None
        if _cwsi is not None:
            stage_name = phenology.stage if phenology else "vegetative"
            
            # Fetch baseline yield
            baseline_yield = None
            if variety_name:
                regime = "rainfed"
                if crop_context and crop_context.management:
                    mgt = crop_context.management.lower()
                    if "irrigated" in mgt or "regadío" in mgt or "regadio" in mgt or "riego" in mgt:
                        regime = "irrigated"
                baseline_yield = await get_variety_yield_baseline(variety=variety_name, irrigation_regime=regime)

            assessment.yield_gap = evaluate_yield_gap(
                cwsi_by_stage={stage_name: _cwsi},
                ky_by_stage={stage_name: phenology.ky if phenology and hasattr(phenology, 'ky') else 0.45},
                baseline_yield_kg_ha=baseline_yield,
            )
    except Exception as e:
        logger.error("Yield gap evaluation failed: %s", e)

    try:
        from app.engines.phenology_progress import evaluate_phenology_progress
        if gdd is not None and stage_table:
            # Declared stage drives deviation (ahead/behind vs declared); fall
            # back to the GDD-derived stage when no declared stage is available.
            declared_stage = (
                phenology.stage if (phenology and phenology.stage)
                else derive_stage_from_gdd(gdd, stage_table)
            )
            assessment.phenology_progress = evaluate_phenology_progress(
                gdd_accumulated=gdd,
                current_stage=declared_stage,
                stage_gdd_thresholds=stage_table,
            )
    except Exception as exc:
        logger.warning("pipeline: phenology progress evaluation failed for parcel %s — skipped: %s", effective_parcel, exc)

    # WUE (after composite stress and yield gap, needs NDVI integral + irrigation data)
    try:
        from app.engines.wue import evaluate_wue
        ndvi_val = await _fetch_parcel_ndvi(effective_parcel, tenant_id)
        irrigation_mm = None
        irrigation_source = "none"
        try:
            irr_readings = await redis_state.get_window(entity_id, "irrigationVolume", hours=24)
            if irr_readings:
                irrigation_mm = sum(r.value for r in irr_readings)
                irrigation_source = "measured_flow"
        except Exception as exc:
            logger.warning("pipeline: WUE redis irrigationVolume read failed for entity %s — skipped: %s", entity_id, exc)
        if irrigation_source == "none":
            try:
                declared = await redis_state.get_latest(entity_id, "declaredIrrigation")
                if declared and declared.value:
                    irrigation_mm = declared.value
                    irrigation_source = "declared_volume"
            except Exception as exc:
                logger.warning("pipeline: WUE redis declaredIrrigation read failed for entity %s — skipped: %s", entity_id, exc)
        assessment.wue = evaluate_wue(
            ndvi_integrated=ndvi_val,
            irrigation_applied_mm=irrigation_mm,
            irrigation_source=irrigation_source,
            previous_wue=None,
            fidelity="onsite_uncalibrated" if irrigation_source == "measured_flow" else "regional_proxy",
        )
    except Exception as exc:
        logger.warning("pipeline: WUE evaluation failed for parcel %s — skipped: %s", effective_parcel, exc)

    # ── 2.7 Compaction Risk (cross-module, opportunistic) ────────
    try:
        from app.engines.compaction_risk import evaluate_compaction_risk
        from app.services.context_client import get_soil_susceptibility, get_multiyear_vigor_anomaly
        soil_susc = await get_soil_susceptibility(effective_parcel, tenant_id)
        if soil_susc and soil_susc.get("overall_score", 0) > 25:
            moisture_pct = soil_moisture_val
            sw_stress = (
                assessment.soil_water_balance.stress_level
                if hasattr(assessment, 'soil_water_balance')
                and assessment.soil_water_balance
                else None
            )
            # Phase 3: Multi-year vigor analysis
            multiyear = await get_multiyear_vigor_anomaly(
                effective_parcel, tenant_id, seasons=3
            )
            from app.schemas import CompactionRiskResult
            engine_result = evaluate_compaction_risk(
                soil_susceptibility_score=soil_susc["overall_score"],
                soil_susceptibility_class=soil_susc["overall_class"],
                soil_moisture_pct=moisture_pct,
                soil_moisture_stress=sw_stress,
                vigor_anomaly_multiyear=multiyear["avg_anomaly"] if multiyear else None,
                vigor_anomaly_years=multiyear["seasons_analyzed"] if multiyear else 0,
                traffic_intensity=None,          # Phase 4
                fidelity=assessment.data_fidelity if hasattr(assessment, 'data_fidelity') else "regional_proxy",
            )
            assessment.compaction_risk = CompactionRiskResult(
                risk_level=engine_result.risk_level,
                risk_score=engine_result.risk_score,
                susceptibility_score=engine_result.susceptibility_score,
                contributing_factors=engine_result.contributing_factors,
                moisture_warning=engine_result.moisture_warning,
                vigor_concern=engine_result.vigor_concern,
                traffic_exposure=engine_result.traffic_exposure,
                advisory=engine_result.advisory,
                requires_field_verification=engine_result.requires_field_verification,
                data_fidelity=engine_result.data_fidelity,
            )

            # Phase 4c: check for penetrometer ground truth
            from app.services.context_client import get_penetrometer_data
            penetrometer = await get_penetrometer_data(effective_parcel, tenant_id)
            if penetrometer and penetrometer.get("available"):
                assessment.compaction_risk.requires_field_verification = False
                assessment.compaction_risk.data_fidelity = "onsite_calibrated"
                assessment.compaction_risk.contributing_factors.append(
                    f"penetrometer_verified_{penetrometer['point_count']}p"
                )
    except Exception as exc:
        logger.warning("pipeline: compaction risk evaluation failed for parcel %s — skipped: %s", effective_parcel, exc)

    assessment.data_fidelity = _resolve_data_fidelity(assessment)

    # Soil sensor pass-through values
    assessment.soil_ph = soil_ph_val
    assessment.soil_ec = soil_ec_val
    assessment.soil_moisture_pct = soil_moisture_val
    assessment.soil_temperature_c = soil_temp_val

    # ── 3. Fuse and classify ─────────────────────────────────────────────
    assessment.overall_severity = _determine_overall_severity(assessment)
    assessment.recommended_action = _determine_action(assessment.overall_severity)

    # ── 4. Publish ───────────────────────────────────────────────────────
    # When ``publish`` is False the caller (compute_assessment) owns the Orion
    # write via ``_publish_assessment`` — avoid double-publishing here.
    if publish:
        published = await publish_assessment(assessment, tenant_id)
        if published:
            logger.info(
                "Assessment published: parcel=%s severity=%s action=%s",
                effective_parcel,
                assessment.overall_severity.value,
                assessment.recommended_action.value,
            )
        else:
            logger.warning("Failed to publish assessment for parcel=%s", effective_parcel)

    # ── 5/6. Event bus + parent aggregation (sensor-publish side-effects) ──
    # Skipped when ``publish`` is False; compute_assessment owns its own write
    # and emits no derived events for the daily snapshot path. The zonal sensor
    # rollup re-uses this helper so the webhook path keeps emitting them.
    if publish:
        await _emit_assessment_side_effects(assessment, tenant_id, now, stage_name)

    return assessment


async def _emit_assessment_side_effects(
    assessment: CropHealthAssessment,
    tenant_id: str,
    now: datetime,
    stage_name: str,
) -> None:
    """Platform event-bus publish + parent-parcel composite aggregation.

    Extracted verbatim from the sensor-publish tail of ``_run_engines`` so the
    zonal sensor rollup can emit the same derived events. Best-effort: every
    failure is logged and swallowed (fail-safe).
    """
    effective_parcel = assessment.parcel_id
    # ── 5. Publish to platform event bus ─────────────────────────────
    try:
        event = {
            "event_type": "crop.assessment.completed",
            "tenant_id": tenant_id,
            "parcel_id": effective_parcel,
            "stage": stage_name,
            "cwsi": assessment.cwsi.cwsi if assessment.cwsi else None,
            "mds_severity": assessment.mds.severity.value if assessment.mds else None,
            "overall_severity": assessment.overall_severity.value,
            "recommended_action": assessment.recommended_action.value,
            "phenology_source": assessment.phenology_source,
            "timestamp": now.isoformat(),
        }
        await _publish_redis_event("crop:events", event)

        if assessment.overall_severity.value in ("HIGH", "CRITICAL"):
            breach = {
                "event_type": "crop.stress.breach",
                "tenant_id": tenant_id,
                "parcel_id": effective_parcel,
                "stage": stage_name,
                "overall_severity": assessment.overall_severity.value,
                "recommended_action": assessment.recommended_action.value,
                "timestamp": now.isoformat(),
            }
            await _publish_redis_event("crop:events", breach)
    except Exception as exc:
        logger.warning("pipeline: redis event publish failed for parcel %s — event dropped: %s", effective_parcel, exc)

    # ── 6. Aggregate parent parcel if this is a child ──────────────────
    try:
        from app.config import get_settings as _gs
        from nkz_platform_sdk.orion import OrionClient
        _settings = _gs()
        _client = OrionClient(
            tenant_id,
            base_url=_settings.orion_ld_url,
            context_url=_settings.orion_ld_context,
        )
        try:
            _entity = await _client.get_entity(
                f"urn:ngsi-ld:AgriParcel:{effective_parcel}",
                options="keyValues",
            )
        finally:
            await _client.close()
        _parent = _entity.get("hasAgriParcel")
        if isinstance(_parent, dict):
            _parent_id = _parent.get("object")
        else:
            _parent_id = _parent
        if _parent_id and "AgriParcel" in str(_parent_id):
            await _aggregate_parent_composite(
                _parent_id, tenant_id, now,
            )
    except Exception as exc:
        logger.warning("pipeline: parent composite aggregation failed for parcel %s — skipped: %s", effective_parcel, exc)


async def _read_assigned_crop(parcel_id: str, tenant_id: str) -> dict | None:
    """Read the parcel's assigned crop from Orion (AgriCrop via hasAgriCrop).

    Returns ``{"species", "plantingDate", "variety"}`` or ``None`` when the
    parcel has no assigned AgriCrop. Reuses ``context_client.get_agri_crop``
    (which resolves ``hasAgriParcel``/``refAgriParcel`` and keyValues), then
    extracts the species from the AgriCrop. Never raises.
    """
    parcel_short = parcel_id.split(":")[-1] if parcel_id.startswith("urn:") else parcel_id
    try:
        agri_crop = await context_client.get_agri_crop(parcel_short, tenant_id)
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("_read_assigned_crop: get_agri_crop failed for %s: %s", parcel_id, exc)
        return None
    if not agri_crop:
        return None

    # Species: prefer cropSpecies, then EPPO agroVoc/cropType, then name.
    species = (
        agri_crop.get("cropSpecies")
        or agri_crop.get("species")
        or agri_crop.get("agriCropType")
        or agri_crop.get("cropType")
        or agri_crop.get("description")
        or agri_crop.get("name")
    )
    if not species:
        return None

    variety = agri_crop.get("variety") or agri_crop.get("varietyName")
    if isinstance(variety, dict):
        variety = variety.get("value") or variety.get("object")

    return {
        "species": species,
        "plantingDate": agri_crop.get("plantingDate") or agri_crop.get("datefrom"),
        "variety": variety,
    }


async def _publish_assessment(entity: dict, tenant_id: str) -> bool:
    """Upsert an already-serialised CropHealthAssessment entity to Orion-LD.

    Thin wrapper around the SDK ``OrionClient.upsert_entities_batch`` so the
    parcel-centric path has a single monkeypatchable publish seam. Mirrors the
    fail-safe behaviour of ``fiware_publisher.publish_assessment``.
    """
    if not tenant_id:
        logger.warning("_publish_assessment called without tenant_id; skipping")
        return False
    try:
        from app.config import get_settings
        from nkz_platform_sdk.orion import OrionClient

        settings = get_settings()
        client = OrionClient(
            tenant_id,
            base_url=settings.orion_ld_url,
            context_url=settings.orion_ld_context,
        )
        try:
            result = await client.upsert_entities_batch([entity])
        finally:
            await client.close()
        errors = result.get("errors") or []
        if errors:
            logger.error("Orion-LD upsert errors for %s: %s", entity.get("id"), errors[:3])
            return False
        logger.info("Published CropHealthAssessment %s", entity.get("id"))
        return True
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.error("_publish_assessment failed for %s: %s", entity.get("id"), exc)
        return False


async def _weather_map_meteo(parcel_id: str, tenant_id: str) -> dict:
    """Parcel-level meteo from the weather-map module (fail-safe {}).

    Live contract (verified 2026-06-20 against weather-map-backend:8080):
    - GET /api/weather-map/stats/{parcel_urn}?metrics=<csv>, X-Tenant-ID header required.
    - Valid metric names: temperature_avg, temperature_min, solar_radiation, eto,
      water_balance, frost_risk, soil_moisture. NO humidity metric exists.
    - Response: {"error"?, "metrics": {name: {"mean", "min", "max", ...}}, "parcel_id", ...}.
      When no COG tiles exist for the parcel: {"error": "No COG data available", "metrics": {}}.
    Maps: air_temp_c <- temperature_avg.mean ; et0_mm <- eto.mean. rh_pct is not
    available from weather-map (resolver leaves it to the regional/unavailable tier).
    """
    try:
        from app.config import get_settings
        settings = get_settings()
        if not settings.weather_map_url:
            return {}
        # weather-map resolves the parcel geometry from Orion by its full URN.
        parcel_urn = parcel_id if parcel_id.startswith("urn:") else f"urn:ngsi-ld:AgriParcel:{parcel_id}"
        async with __import__("httpx").AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.weather_map_url}/api/weather-map/stats/{parcel_urn}",
                params={"metrics": "temperature_avg,eto"},
                headers={"X-Tenant-ID": tenant_id} if tenant_id else {},
            )
            if resp.status_code != 200:
                return {}
            data = resp.json() or {}
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("_weather_map_meteo: failed for %s — {}: %s", parcel_id, exc)
        return {}

    metrics = data.get("metrics") or {}  # empty when error/"No COG data available"

    def _mean(name: str):
        m = metrics.get(name)
        if isinstance(m, dict):
            v = m.get("mean", m.get("value"))
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
        return None

    out: dict = {}
    air = _mean("temperature_avg")
    et0 = _mean("eto")
    if air is not None:
        out["air_temp_c"] = air
    if et0 is not None:
        out["et0_mm"] = et0
    return out


async def _regional_meteo(parcel_id: str, tenant_id: str) -> dict:
    """Regional fallback meteo from Orion WeatherObserved (fail-safe {}).

    Queries the latest WeatherObserved for this parcel via Orion-LD.
    Falls back to {} when no data exists or Orion is unreachable.
    """
    try:
        # NOTE: using raw httpx because OrionClient.query_entities does not
        # expose orderBy. The HTTP call uses canonical FIWARE headers
        # (NGSILD-Tenant + Link for context expansion) — same as SDK does.
        import httpx as _httpx
        from app.config import get_settings
        settings = get_settings()
        parcel_urn = parcel_id if parcel_id.startswith("urn:") else f"urn:ngsi-ld:AgriParcel:{parcel_id}"
        link_hdr = f'<{settings.orion_ld_context}>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'
        headers = {"NGSILD-Tenant": tenant_id, "Accept": "application/json", "Link": link_hdr}
        base = settings.orion_ld_url

        async with _httpx.AsyncClient(timeout=8.0) as cl:
            # Try finding by relationship first, ordered by most recent
            rel_q = f'(refAgriParcel=="{parcel_urn}"|hasAgriParcel=="{parcel_urn}")'
            resp = await cl.get(
                f"{base}/ngsi-ld/v1/entities",
                params={"type": "WeatherObserved", "q": rel_q,
                        "limit": 1, "options": "keyValues",
                        "orderBy": "!dateObserved"},
                headers=headers,
            )
            entities = resp.json() if resp.status_code == 200 else []
            # Fallback: latest WeatherObserved in the tenant
            if not entities:
                resp = await cl.get(
                    f"{base}/ngsi-ld/v1/entities",
                    params={"type": "WeatherObserved",
                            "limit": 1, "options": "keyValues",
                            "orderBy": "!dateObserved"},
                    headers=headers,
                )
                entities = resp.json() if resp.status_code == 200 else []

        if not entities:
            return {}

        wo = entities[0]
        out: dict = {}
        temp = wo.get("temperature")
        if temp is not None:
            try:
                out["air_temp_c"] = float(temp)
            except (TypeError, ValueError):
                pass
        et0 = wo.get("et0")
        if et0 is not None:
            try:
                out["et0_mm"] = float(et0)
            except (TypeError, ValueError):
                pass
        rh = wo.get("relativeHumidity")
        if rh is not None:
            try:
                out["rh_pct"] = float(rh)
            except (TypeError, ValueError):
                pass
        precip = wo.get("precipitation")
        if precip is not None:
            try:
                out["precip_mm"] = float(precip)
            except (TypeError, ValueError):
                pass
        return out
    except Exception as exc:  # noqa: BLE001 -- fail-safe
        logger.warning("_regional_meteo: failed for %s — %s", parcel_id, exc)
        return {}


# Severity ordering for the worst-zone rollup (fail-safe: parcel risk = its
# most-compromised zone). Keys are the Severity enum *values* (uppercase).
_SEV_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _sev_rank(assessment: CropHealthAssessment) -> int:
    sev = getattr(assessment.overall_severity, "value", assessment.overall_severity)
    return _SEV_ORDER.get(str(sev), 0)


async def _resolve_device_coords(entity_id: str, tenant_id: str) -> tuple[float, float] | None:
    """Best-effort (lon, lat) of the device/measurement, for zone attribution.

    Reads the entity's ``location`` (Point) from Orion-LD. Returns ``None`` when
    unavailable — the caller then leaves the device's window-engines unattributed
    for that event (zonal mode only; whole-parcel mode never calls this). Richer
    device-location resolution arrives with the QR/GPS onboarding flow.
    """
    try:
        from app.config import get_settings
        from nkz_platform_sdk.orion import OrionClient
        settings = get_settings()
        client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
        try:
            data = await client.get_entity(entity_id, options="keyValues")
        finally:
            await client.close()
        loc = data.get("location") if isinstance(data, dict) else None
        if isinstance(loc, dict):
            if loc.get("type") == "GeoProperty":
                loc = loc.get("value")
            if isinstance(loc, dict) and loc.get("type") == "Point":
                coords = loc.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    return (float(coords[0]), float(coords[1]))  # (lon, lat)
    except Exception as exc:
        logger.warning("_resolve_device_coords: failed for %s — None: %s", entity_id, exc)
    return None


async def _gather_parcel_sensors(parcel_id: str, tenant_id: str) -> list[dict]:
    """Located sensor readings for the parcel, for per-zone consolidation.

    v1: returns ``[]`` — the scheduled path is sensorless and the webhook path
    supplies its triggering measurement directly via ``sensor_ctx``. Gathering
    live device coordinates for full multi-device spatial consolidation is a
    documented follow-up (needs a Device-location query contract).
    """
    return []


async def _assess_zone(
    zone: Zone,
    parcel_id: str,
    parcel_short: str,
    tenant_id: str,
    crop_ctx: dict,
    sensor_ctx: dict | None,
    whole: bool,
) -> CropHealthAssessment:
    """Compute one zone's assessment, reusing the existing engine core.

    Crop/GDD/phenology are parcel-level (in ``crop_ctx``); meteo is resolved
    with this zone's (consolidated) ``sensor_ctx``. v1 reuses parcel-level
    NDVI/SAR/soil for every zone (no zonal raster source yet) — the engine core
    fetches those by ``effective_parcel``. ``publish=False`` so this function
    has no Orion/event/parent side-effects (the caller owns writes).
    """
    phenology = crop_ctx["phenology"]
    thresholds = crop_ctx["thresholds"]
    gdd = crop_ctx["gdd"]
    species = crop_ctx["species"]
    variety_name = crop_ctx["variety_name"]
    now = crop_ctx["now"]

    meteo = await resolve_meteo_context(
        parcel_id, tenant_id,
        sensor_ctx=sensor_ctx,
        weather_map_fn=_weather_map_meteo,
        regional_fn=_regional_meteo,
    )

    weather = None
    if meteo.air_temp_c is not None:
        from app.schemas import WeatherSnapshot
        weather = WeatherSnapshot(
            temp_air=meteo.air_temp_c,
            humidity_pct=meteo.rh_pct if meteo.rh_pct is not None else 50.0,
            precip_mm=0.0,
            eto_mm=meteo.et0_mm if meteo.et0_mm is not None else 0.0,
        )
    else:
        coords = await context_client._resolve_parcel_coords(parcel_short, tenant_id)
        if coords:
            latitude, longitude = coords
            weather = await get_weather_snapshot(
                latitude=latitude, longitude=longitude, tenant_id=tenant_id,
            )

    assessment = CropHealthAssessment(
        parcel_id=parcel_short,
        assessed_at=now,
        phenology_source="gdd_derived",
        crop_species=species,
        crop_name=species,
        variety_name=variety_name,
        gdd_accumulated=gdd,
        kc=phenology.kc if phenology else None,
        season_start=crop_ctx["season_start"],
        meteo_fidelity=meteo.dominant_fidelity,
        zone_id=None if whole else zone.zone_id,
        zone_urn=None if whole else zone.urn,
        zone_geometry=None if whole else zone.geometry,
    )

    if gdd is not None and thresholds:
        assessment.phenology_stage = derive_stage_from_gdd(gdd, thresholds)
    elif phenology:
        assessment.phenology_stage = phenology.stage

    await _run_engines(
        assessment,
        metric_type="",
        weather=weather,
        phenology=phenology,
        redis_state=None,
        entity_id=parcel_short,
        effective_parcel=parcel_short,
        tenant_id=tenant_id,
        species=species,
        crop_context=None,
        variety_name=variety_name,
        gdd=gdd,
        soil=crop_ctx["soil"],
        root_depth_mm=crop_ctx["root_depth_mm"],
        sw_yesterday=None,
        irrigation_mm=0.0,
        now=now,
        stage_table=thresholds,
        publish=False,
    )
    return assessment


def _aggregate_rollup(parcel_short: str, zone_results: list[CropHealthAssessment]) -> CropHealthAssessment:
    """Parcel rollup = the worst (most severe) zone (fail-safe).

    Returns a copy with zone identity stripped so it serialises as the legacy
    parcel-level ``CropHealthAssessment`` (back-compat).
    """
    worst = max(zone_results, key=_sev_rank)
    rollup = worst.model_copy()
    rollup.zone_id = None
    rollup.zone_urn = None
    rollup.zone_geometry = None
    rollup.parcel_id = parcel_short
    return rollup


async def compute_assessment(
    parcel_id: str,
    tenant_id: str,
    *,
    sensor_ctx: dict | None = None,
) -> CropHealthAssessment | None:
    """Parcel assessment, synthesised per management ZONE — sensor-optional.

    Reads the parcel's assigned crop (parcel-level), resolves zones from
    weather-map's ``AgriParcelZone`` (fallback: one whole-parcel zone), and for
    each zone runs the engine core with that zone's (consolidated) meteo. Each
    zone publishes a ``CropHealthZoneAssessment``; the parcel rollup
    (worst zone) publishes the legacy ``CropHealthAssessment`` so existing
    consumers are untouched. Returns the rollup, or ``None`` when no crop.

    In whole-parcel mode (no zones) behaviour is identical to the legacy
    parcel-level path: exactly one ``CropHealthAssessment`` write, no zone
    entities.
    """
    crop = await _read_assigned_crop(parcel_id, tenant_id)
    if not crop:
        logger.info("compute_assessment: no crop on %s — skip", parcel_id)
        return None

    parcel_short = parcel_id.split(":")[-1] if parcel_id.startswith("urn:") else parcel_id
    species = crop["species"]
    variety_name = crop.get("variety")
    from app.services.context_client import resolve_season_start
    season_start = await resolve_season_start(parcel_short, tenant_id)

    # Seasonal GDD (authoritative stage source) — uses crop-specific base_temp/upper_cutoff
    thresholds = await context_client.get_phenology_stages(species)
    gdd_data = await _fetch_gdd(
        tenant_id, season_start, parcel_id,
        base_temp=thresholds.base_temp if thresholds else 10.0,
        upper_cutoff=thresholds.upper_cutoff if thresholds else None,
    ) or {}
    gdd = gdd_data.get("gdd_total")
    if gdd is not None:
        gdd = float(gdd)

    # Phenology params (engine inputs: kc, d1/d2, mds_ref, stage thresholds)
    phenology = await get_phenology_params(species=species, gdd=gdd)

    now = datetime.now(timezone.utc)

    # Soil + root depth for the water-balance engine (parcel-level).
    from app.services.context_client import get_soil_properties
    soil = await get_soil_properties(parcel_id=parcel_short, tenant_id=tenant_id)
    root_depth_mm = _resolve_root_depth(species, gdd, None)

    crop_ctx = {
        "species": species,
        "variety_name": variety_name,
        "season_start": season_start,
        "gdd": gdd,
        "phenology": phenology,
        "thresholds": thresholds,
        "soil": soil,
        "root_depth_mm": root_depth_mm,
        "now": now,
    }

    # Resolve management zones (weather-map AgriParcelZone) or whole-parcel.
    parcel_geom = await context_client._resolve_parcel_geometry(parcel_short, tenant_id)
    zones = await resolve_zones(parcel_id, tenant_id, parcel_geom or {})
    whole = is_whole_parcel(zones)

    # Located sensors for per-zone consolidation (v1: [] for scheduled path).
    all_sensors = await _gather_parcel_sensors(parcel_id, tenant_id)

    zone_results: list[CropHealthAssessment] = []
    for z in zones:
        zone_sensor_ctx = sensor_ctx
        if all_sensors:
            consolidated = consolidate_sensor_readings(sensors_in_zone(z, all_sensors))
            if consolidated:
                zone_sensor_ctx = consolidated
        try:
            za = await _assess_zone(
                z, parcel_id, parcel_short, tenant_id, crop_ctx, zone_sensor_ctx, whole,
            )
        except Exception as exc:  # best-effort per zone — one bad zone must not sink the rest
            logger.warning("compute_assessment: zone %s failed for %s — skipped: %s", z.zone_id, parcel_short, exc)
            continue
        zone_results.append(za)
        if not whole:
            await _publish_assessment(za.to_zone_ngsi_ld(), tenant_id)

    if not zone_results:
        logger.warning("compute_assessment: all zones failed for %s — no assessment", parcel_short)
        return None

    rollup = _aggregate_rollup(parcel_short, zone_results)

    # ── Nutrient recommendation from BioOrch ──
    from app.schemas import CropRequirements
    from app.services.context_client import get_nutrient_recommendation

    soil_data = crop_ctx.get("soil")
    nutrient_rec = await get_nutrient_recommendation(
        species=species,
        stage=rollup.phenology_stage or "vegetative",
        soil_n=getattr(soil_data, "nitrogen_kg_ha", 0) if soil_data else 0,
        soil_p=getattr(soil_data, "phosphorus_kg_ha", 0) if soil_data else 0,
        soil_k=getattr(soil_data, "potassium_kg_ha", 0) if soil_data else 0,
    )

    # Derive irrigation need from soil_water_balance
    irrigation_mm = None
    water_deficit_mm = None
    if rollup.soil_water_balance:
        water_deficit_mm = rollup.soil_water_balance.deficit_mm
        if rollup.soil_water_balance.stress_level in ("high", "critical"):
            irrigation_mm = water_deficit_mm

    def _extract_npk(rec, element):
        if not rec or not rec.get("recommendations"):
            return None
        for r in rec["recommendations"]:
            if r.get("element") == element and r.get("status") in ("deficient", "adequate"):
                return r.get("uptake_kg_ha_day")
        return None

    rollup.crop_requirements = CropRequirements(
        irrigation_mm=irrigation_mm,
        water_deficit_mm=water_deficit_mm,
        n_kg_ha=_extract_npk(nutrient_rec, "nitrogen"),
        p2o5_kg_ha=_extract_npk(nutrient_rec, "phosphorus"),
        k2o_kg_ha=_extract_npk(nutrient_rec, "potassium"),
        bioorch_recommendations=nutrient_rec.get("recommendations") if nutrient_rec else None,
        bioorch_species=nutrient_rec.get("species") if nutrient_rec else None,
        bioorch_stage=nutrient_rec.get("stage") if nutrient_rec else None,
    )

    await _publish_assessment(rollup.to_ngsi_ld(), tenant_id)
    return rollup


async def _build_sensor_ctx(entity_id: str, redis_state) -> dict:
    """Build a windowed sensor meteo context from the Redis sliding window.

    Returns aggregates keyed by ``MeteoContext`` variable names. Best-effort:
    missing/erroring windows are simply omitted (fail-safe {}).
    """
    if redis_state is None:
        return {}
    ctx: dict = {}

    async def _last(metric: str, hours: int = 1):
        try:
            readings = await redis_state.get_window(entity_id, metric, hours=hours)
            if readings:
                return readings[-1].value
        except Exception as exc:  # noqa: BLE001 — fail-safe
            logger.warning("_build_sensor_ctx: window read failed (%s): %s", metric, exc)
        return None

    leaf = await _last("leafTemperature", hours=1)
    if leaf is not None:
        ctx["leaf_temp_c"] = leaf
    air = await _last("airTemperature", hours=1)
    if air is not None:
        ctx["air_temp_c"] = air
    rh = await _last("relativeHumidity", hours=1)
    if rh is not None:
        ctx["rh_pct"] = rh
    return ctx


async def _aggregate_parent_composite(
    parent_parcel_id: str,
    tenant_id: str,
    trigger_time: datetime,
) -> None:
    """Recalculate parent parcel composite as area-weighted avg of children.

    Called after a child parcel's assessment is published.
    Queries Orion-LD for all child parcels (hasAgriParcel -> parent),
    fetches their latest CropHealthAssessment, and computes an
    area-weighted composite index for the parent.
    """
    try:
        from app.config import get_settings as _gs
        from nkz_platform_sdk.orion import OrionClient

        settings = _gs()

        client = OrionClient(
            tenant_id,
            base_url=settings.orion_ld_url,
            context_url=settings.orion_ld_context,
        )
        try:
            # Find all child parcels
            children = await client.query_entities(
                type="AgriParcel",
                q=f'(hasAgriParcel=="{parent_parcel_id}"|refAgriParcel=="{parent_parcel_id}")',
                limit=20,
                options="keyValues",
            )
            if not isinstance(children, list) or len(children) < 2:
                return

            # Fetch latest assessment per child, accumulate weighted composite
            weighted_sum = 0.0
            total_area = 0.0
            count = 0
            dominant = "none"

            for child in children:
                child_id = child["id"]
                child_area_raw = child.get("area")
                if isinstance(child_area_raw, dict):
                    child_area = child_area_raw.get("value", 0)
                else:
                    child_area = child_area_raw or 0
                if not child_area:
                    continue
                total_area += child_area

                try:
                    child_assessments = await client.query_entities(
                        type="CropHealthAssessment",
                        q=f'(hasAgriParcel=="{child_id}"|refAgriParcel=="{child_id}")',
                        limit=1,
                        options="keyValues",
                    )
                except Exception as e:
                    logger.warning(
                        "aggregate: child %s assessment query failed: %s",
                        child_id, e,
                    )
                    continue
                if isinstance(child_assessments, list) and child_assessments:
                    ca = child_assessments[0]
                    csi = ca.get("compositeStressIndex")
                    if isinstance(csi, dict):
                        csi = csi.get("value")
                    dom = ca.get("dominantStressor")
                    if isinstance(dom, dict):
                        dom = dom.get("value", "none")
                    if csi is not None:
                        weighted_sum += float(csi) * child_area
                        count += 1
                        if dom and dom != "none":
                            dominant = dom

            if count == 0 or total_area == 0:
                return

            parent_composite = round(weighted_sum / total_area, 1)

            # Upsert parent aggregated assessment
            parent_id_short = parent_parcel_id.split(":")[-1]
            assessment_id = (
                f"urn:ngsi-ld:CropHealthAssessment:{tenant_id}:"
                f"{parent_id_short}:aggregated"
            )
            body = {
                "id": assessment_id,
                "type": "CropHealthAssessment",
                "hasAgriParcel": {
                    "type": "Relationship",
                    "object": parent_parcel_id,
                },
                "assessedAt": {
                    "type": "Property",
                    "value": trigger_time.isoformat(),
                },
                "compositeStressIndex": {
                    "type": "Property",
                    "value": parent_composite,
                },
                "dominantStressor": {
                    "type": "Property",
                    "value": dominant if dominant != "none" else "aggregated",
                },
                "dataFidelity": {
                    "type": "Property",
                    "value": "aggregated_children",
                },
                "phenologySource": {
                    "type": "Property",
                    "value": f"aggregated_from_{count}_children",
                },
            }

            result = await client.upsert_entities_batch([body])
            if result.get("errors"):
                logger.warning(
                    "Parent composite upsert partial failure for %s: %s",
                    parent_parcel_id, result["errors"][:3],
                )
            else:
                logger.info(
                    "Parent parcel %s composite aggregated from %d children: %.1f",
                    parent_parcel_id, count, parent_composite,
                )
        finally:
            await client.close()

    except Exception as exc:
        logger.warning(
            "Failed to aggregate parent composite for %s: %s",
            parent_parcel_id, exc,
        )


async def _publish_redis_event(stream: str, event: dict) -> None:
    """Publish an event to Redis Streams (best-effort)."""
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings
        _s = get_settings()
        r = aioredis.Redis.from_url(_s.redis_url, password=_s.redis_password or None)
        payload = __import__("json").dumps(event)
        await r.xadd(stream, {"payload": payload}, maxlen=1000)
        await r.aclose()
    except Exception as exc:
        logger.warning("_publish_redis_event: failed to publish to stream %s — dropped: %s", stream, exc)


async def _fetch_gdd(
    tenant_id: str,
    season_start: str,
    parcel_id: str,
    base_temp: float = 10.0,
    upper_cutoff: float | None = None,
) -> dict | None:
    """Fetch accumulated GDD from the weather API (timeseries-reader).

    Args:
        tenant_id: Tenant identifier.
        season_start: ISO date of season start.
        parcel_id: Parcel URN (resolved to lat/lon by the endpoint).
        base_temp: Base temperature for GDD computation (per crop).
        upper_cutoff: Cap Tmax before averaging (per crop; default 30°C on endpoint side).
    """
    try:
        settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
        if not settings.weather_api_url:
            return None
        params: dict[str, str] = {
            "season_start": season_start,
            "base_temp": str(base_temp),
            "parcel_id": parcel_id,
        }
        if upper_cutoff is not None:
            params["upper_cutoff"] = str(upper_cutoff)
        async with __import__("httpx").AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.weather_api_url}/api/weather/gdd",
                params=params,
                headers={"X-Tenant-ID": tenant_id},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(
                "_fetch_gdd: HTTP %d for tenant %s season_start=%s parcel=%s",
                resp.status_code, tenant_id, season_start, parcel_id,
            )
    except Exception as exc:
        logger.warning(
            "_fetch_gdd: failed for tenant %s season_start=%s — returning None: %s",
            tenant_id, season_start, exc,
        )
    return None


def _extract_eoproduct_scalar(entity: dict, attr: str) -> float | None:
    """Read a scalar from a keyValues EOProduct attribute (scalar or Property dict)."""
    raw = entity.get(attr)
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        return None
    return float(raw)


async def _fetch_parcel_lst(parcel_id: str, tenant_id: str) -> float | None:
    """Fetch latest LST (°C) for a parcel from EOProduct.lst (vegetation-health).

    Canonical contract: one EOProduct per (parcel, sensingDate); LST is the
    lowercased `lst` Property with unitCode CEL. Newest by sensingDate wins.
    """
    try:
        from app.config import get_settings
        from nkz_platform_sdk.orion import OrionClient
        settings = get_settings()
        client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
        try:
            entities = await client.query_entities(
                type="EOProduct",
                q=f'hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_id}"|refAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_id}"',
                limit=100,
                options="keyValues",
            )
        finally:
            await client.close()
        if entities and isinstance(entities, list):
            with_lst = [e for e in entities if e.get("lst") is not None]
            if with_lst:
                latest = max(with_lst, key=lambda e: str(e.get("sensingDate", "")))
                lst = _extract_eoproduct_scalar(latest, "lst")
                if lst is not None:
                    return lst
    except Exception as exc:
        logger.warning("_fetch_parcel_lst: failed for parcel %s — returning None: %s", parcel_id, exc)
    return None


async def _fetch_parcel_ndvi(parcel_id: str, tenant_id: str) -> float | None:
    """Fetch latest NDVI mean for a parcel from canonical EOProduct entities.

    Canonical contract (vegetation-health CONTRACT.md): one EOProduct per
    (parcel, sensingDate); NDVI is the named lowercased `ndvi` Property whose
    `value` is the zonal mean. There is no `productType` discriminator on
    optical products and no `ndviMean`/`ndviValue`. Newest by sensingDate wins;
    SAR EOProducts (no `ndvi` attribute) are skipped.
    """
    try:
        from app.config import get_settings
        from nkz_platform_sdk.orion import OrionClient
        settings = get_settings()
        client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
        try:
            entities = await client.query_entities(
                type="EOProduct",
                q=f'hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_id}"|refAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_id}"',
                limit=100,
                options="keyValues",
            )
        finally:
            await client.close()
        if entities and isinstance(entities, list):
            with_ndvi = [e for e in entities if e.get("ndvi") is not None]
            if with_ndvi:
                latest = max(with_ndvi, key=lambda e: str(e.get("sensingDate", "")))
                ndvi = _extract_eoproduct_scalar(latest, "ndvi")
                if ndvi is not None:
                    return ndvi
    except Exception as exc:
        logger.warning("_fetch_parcel_ndvi: failed for parcel %s — returning None: %s", parcel_id, exc)
    return None


async def _fetch_parcel_sar(parcel_id: str, tenant_id: str) -> tuple[float, float] | None:
    """Fetch latest SAR backscatter (VV, VH) for a parcel from Orion-LD.

    Queries EOProduct entities (FIWARE Smart Data Model) filtered by
    productType=GRD (Sentinel-1 Ground Range Detected).
    """
    try:
        from app.config import get_settings
        from nkz_platform_sdk.orion import OrionClient
        settings = get_settings()
        client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
        try:
            entities = await client.query_entities(
                type="EOProduct",
                q=f'(hasAgriParcel==\"urn:ngsi-ld:AgriParcel:{parcel_id}\"|refAgriParcel==\"urn:ngsi-ld:AgriParcel:{parcel_id}\");productType==\"GRD\"',
                limit=1,
                options="keyValues",
            )
        finally:
            await client.close()
        if entities and isinstance(entities, list):
            e = entities[0]
            vv = e.get("backscatterVV")
            vh = e.get("backscatterVH")
            if vv is not None and vh is not None:
                return float(vv), float(vh)
    except Exception as exc:
        logger.warning("_fetch_parcel_sar: failed for parcel %s — returning None: %s", parcel_id, exc)
    return None


def _resolve_data_fidelity(assessment: CropHealthAssessment) -> str:
    """Determine the minimum data fidelity from available inputs."""
    levels = []
    if assessment.cwsi:
        levels.append("onsite_uncalibrated")  # CWSI requires IR sensor
    if assessment.mds:
        levels.append("onsite_uncalibrated")  # MDS requires dendrometer
    if assessment.water_balance:
        levels.append("regional_proxy")  # weather API
    if assessment.thermal:
        levels.append(assessment.thermal.data_fidelity)
    if assessment.vigor:
        levels.append(assessment.vigor.data_fidelity)

    priority = ["onsite_calibrated", "onsite_uncalibrated", "local_proxy",
                "regional_proxy", "modeled_opendata"]
    if not levels:
        return "modeled_opendata"
    # Return the lowest fidelity (highest index in priority list)
    for p in reversed(priority):
        if p in levels:
            return p
    return "mixed"


def _extract_parcel_from_entity(entity_id: str) -> str | None:
    """Extract parcel ID from device entity ID.

    Convention: device entities follow the pattern
    urn:ngsi-ld:DeviceMeasurement:{parcel}-{sensor}
    or carry a hasAgriParcel relationship.

    For now, use a simple heuristic; the webhook handler can
    pass parcel_id directly if resolved upstream.
    """
    # Simple heuristic: extract the first segment after DeviceMeasurement:
    parts = entity_id.split(":")
    if len(parts) >= 4:
        # urn:ngsi-ld:DeviceMeasurement:Parcela-4-sensor-1 → Parcela-4
        sensor_part = parts[3]
        # Take everything before the last dash-delimited segment
        segments = sensor_part.rsplit("-", 1)
        if len(segments) >= 1:
            return segments[0]
    return None
