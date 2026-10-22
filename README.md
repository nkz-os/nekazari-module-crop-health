# Crop Health Engine — NKZ Module

Real-time biophysical inference engine for the [Nekazari](https://nkz-os.org) precision agriculture platform.

## What it does

Follows each sown crop through its campaign:

- **Crop state**: water and thermal stress, vigour, phenology, disease and compaction risk, per parcel and per management zone. It combines parcel weather, satellite indices, soil data and, when present, IoT sensors, with phenology parameters from [BioOrchestrator](https://github.com/nkz-os/nekazari-module-bioorchestrator).
- **Expected harvest**: the in-season yield forecast of each sown parcel, computed by BioOrchestrator's crop engine, refreshed every night and on demand.

It publishes `CropHealthAssessment` entities to Orion-LD with full data fidelity tracing. A parcel is followed once a sowing is recorded (in Field Operations); before that it shows no assessment, and the forecast says why.

## User guide

Open **Crop Health** and pick a parcel in the list, or select a parcel in the 3D viewer to see the same detail in the side panel.

- **Summary**: severity (*Healthy*, *Monitor*, *Stressed*, *Critical*) with the recommended action, the current stage and alerts for frost, heat or low vigour.
- **Management zones**: when the parcel is split into zones, the panel lists them as *Zone 1*, *Zone 2*… in map order (north to south, then west to east). The map label of each zone shows the same number and the value of the active layer (`2 · M`). Point at or click a zone in the panel to light it up on the map.
- **Phenology timeline**: the crop stages with their projected dates.
- **Active risks**: disease and soil compaction.
- **Tabs**: *Water*, *Plant*, *Yield & action* and *Analytics* (NDVI–CWSI correlation, CSV export).
- **Expected harvest** (first block of *Yield & action*): one row per model, never averaged, with its range in t/ha and a label: *Experimental* while the season runs, *Validated* once it is complete, *Ceiling* for the water-limited potential. *Update* recomputes it in a minute or two; *View simulation detail* opens the full simulation in Crop planning. Without a figure, the block gives the reason (crop not sown, not validated in this area, missing regime…). If the regime is missing it asks *Rainfed or irrigated?* in place.
- **Yield potential utilization (FAO-33)**: an instantaneous indicator (today's water stress applied to the current stage), not a forecast. It carries that label until the indicator accumulates the whole season.
- **Data source diagnostics**: which sources reach the parcel (soil, IoT, weather, NDVI, SAR, crop, BioOrchestrator) and which fail.

In the viewer the module also adds map layers (severity, CWSI, composite, vigour), a *Composite stress* timeline track and dashboard cards for all parcels.

## Engines (9 motors)

### State engines (real-time, sensor-driven)

| Engine | Sensor | Output | Formula |
|--------|--------|--------|---------|
| **CWSI** | IR canopy temperature | Water stress [0-1] | `(Tc-Ta-D1)/(D2-D1)` — Jackson et al. 1981 |
| **MDS** | Dendrometer (trunk Ø) | Cellular shrinkage | `max(Ø,24h)-min(Ø,24h)` vs `MDS_ref` — Moriana et al. 2003 |
| **Water Balance** | TDR soil moisture + weather | Deficit/surplus (mm) | `Precip − (ETo × Kc)` — FAO-56 |
| **Thermal Stress** | IR + air temperature | Heat/frost risk | Hours above/below species thresholds — Connor & Fereres 2005 |
| **Vigor** | Vegetation indices | Crop vigor [0-1] | VI composite − CWSI penalty. Auto-selects optimal index per stage |

### Compound engines (computed from state engines)

| Engine | Output | Source |
|--------|--------|--------|
| **Composite Stress** | Weighted index [0-100] | Ky FAO-33 per phenological stage |
| **Yield Gap** | % potential utilization | Doorenbos-Kassam FAO-33. **No es predicción de cosecha** |
| **Phenology Progress** | GDD vs expected curve | McMaster & Wilhelm 1997 |
| **WUE** | kg biomass / m³ water | Conditional: operational with irrigation meter, suppressed otherwise |

## Architecture

```
IoT Sensors (MQTT)
    │
    ▼
Orion-LD (DeviceMeasurement)
    │  NGSI-LD subscription
    ▼
Crop-Health Webhook ←── Redis sliding window (48h)
    │
    ├── BioOrchestrator ←── phenology params (Kc, D1, D2) · in-season yield forecast
    ├── Weather         ←── weather-map parcel stats · weather-api parcel daily series (season GDD)
    ├── Vegetation      ←── VegetationIndex entities (NDVI, EVI, SAVI...)
    ├── Crop cycles     ←── SDK crop timeline (sowing recorded in Field Operations)
    │
    ▼
Pipeline: 9 engines → CropHealthAssessment
    │
    ├── Orion-LD (upsert entity)
    ├── Redis Streams (crop:events → email, push, webhook)
    └── telemetry-worker → telemetry_events → DataHub visualization
```

## Frontend

| Component | Slot | Description |
|-----------|------|-------------|
| **CropHealthWidget** | `dashboard-widget` | Dashboard card per parcel: severity, CWSI, stress, vigour, yield indicator, action |
| **DiseaseRiskWidget** | `dashboard-widget` | Active disease alerts (Mills, Magarey, TomCast, Gubler) |
| **CompactionRiskWidget** | `dashboard-widget` | Parcels with soil compaction risk |
| **CropHealthMapModeWidget** · **CropHealthLayerToggle** | `dashboard-widget` · `layer-toggle` | Map layer mode: severity, CWSI, composite, vigour, off |
| **CropHealthContextPanel** | `context-panel` | 3D viewer side panel: the parcel workbench (summary, zones, phenology, risks, tabs, expected harvest, data sources) |
| **CropHealthLayer** | `map-layer` | Parcels and numbered management zones coloured by the active mode; a zone pointed at in the panel is highlighted |
| **CropHealthTimelineTrack** | `timeline-track` | Composite stress over time for the selected parcel |

i18n: 6 locales (es, en, ca, eu, fr, pt).

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (includes Redis status) |
| POST | `/webhooks/fiware-sensors` | Receive DeviceMeasurement from Orion-LD |
| GET | `/api/crop-health/assessments/latest` | Latest assessment per parcel |
| GET | `/api/crop-health/assessments/history` | Time series CWSI/MDS/balance (sparklines) |
| GET | `/api/crop-health/assessments/correlation` | NDVI/CWSI paired data |
| GET | `/api/crop-health/assessments/all` | All parcel assessments (heatmap) |
| GET | `/api/crop-health/assessments/export` | CSV export with source metadata |
| GET | `/api/crop-health/diseases/active` | Active disease risks |
| GET | `/api/crop-health/parcels` | Parcels with their latest assessment |
| GET | `/api/crop-health/parcels/{id}/phenology-status` | Current stage and projected stage dates |
| GET | `/api/crop-health/parcels/{id}/yield-forecast` | Stored in-season forecast (or `not_computed`), plus `refreshing` |
| POST | `/api/crop-health/parcels/{id}/yield-forecast/refresh` | Recompute one parcel in the background (202) |
| POST | `/api/crop-health/internal/run-scheduled-assessments` | Nightly assessments, one page of parcels (internal secret) |
| POST | `/api/crop-health/internal/run-yield-forecasts` | Nightly forecasts, one parcel per page (internal secret) |

User routes accept only an identity signed by the api-gateway (`X-Auth-Signature`); internal routes take `X-Internal-Service-Secret`.

## Scheduled jobs

| Job | Schedule | What it does |
|-----|----------|--------------|
| `crop-health-scheduled-assessments` | daily 04:00 UTC | Assessment of every parcel with a crop in the field |
| `crop-health-yield-forecasts` | daily 05:00 UTC | In-season forecast of every parcel, one at a time; a failure or a busy engine never overwrites a stored forecast |

Both read the tenants from `SCHEDULED_TENANTS`. Templates with placeholders are in `k8s/`.

## dataFidelity

Every assessment carries a `dataFidelity` attribute:

| Level | Meaning |
|-------|---------|
| `onsite_calibrated` | Own sensor, verified calibration |
| `onsite_uncalibrated` | Own/ingested sensor, unverified |
| `local_proxy` | Source <2km |
| `regional_proxy` | Station 2-10km or interpolated |
| `modeled_opendata` | Reanalysis, satellite, models |

Fidelity propagates: assessment inherits the minimum of its inputs.

## Integration points

| Service | Direction | Method |
|---------|-----------|--------|
| **Orion-LD** | IN (webhook) + OUT (upsert) | NGSI-LD |
| **BioOrchestrator** | Read | REST: phenology, soil, heat tolerance, in-season yield forecast |
| **Weather** | Read | weather-map parcel statistics; weather-api parcel daily series for the season GDD |
| **Field Operations** | Read (via broker) | Recorded sowings and harvests define the crop cycle (SDK crop timeline) |
| **Redis** | Read/Write | Sliding window + event streams |
| **Vegetation Prime** | Read | VegetationIndex via Orion-LD |
| **DataHub** | OUT | CropHealthAssessment → telemetry_events → auto-plottable |

## Quick Start

```bash
cp env.example .env
docker-compose up -d  # backend + Redis

cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Configuration

| Variable | Required | Purpose |
|----------|----------|---------|
| `REDIS_URL` | yes | Sliding window, forecast store and refresh locks |
| `HMAC_SECRET` + `REQUIRE_HMAC_SIGNATURE=true` | yes | Verify the api-gateway signature on user routes; the service refuses to start without both |
| `INTERNAL_SERVICE_SECRET` | yes | Internal routes and calls to BioOrchestrator's in-season endpoint |
| `BIOORCHESTRATOR_URL` | recommended | Phenology parameters and the in-season forecast |
| `SCHEDULED_TENANTS` | CronJobs | Comma-separated tenants for the nightly jobs |

## Deployment

CI builds the backend image on every push to `main` and publishes the frontend to the platform through OIDC. The `k8s/` folder holds reference manifests with placeholders (backend and the two CronJobs); a production deployment pins the image by digest in its own configuration repository.

## Related modules

- [BioOrchestrator](https://github.com/nkz-os/nekazari-module-bioorchestrator) — Crop planning, knowledge graph, phenology API and the in-season forecast engine
- [Field Operations](https://github.com/nkz-os/nkz-module-field-operations) — Records sowings and harvests
- [IkerKeta](https://github.com/nkz-os/ikerketa) — ETL pipeline (25 connectors)
- [Nekazari Platform](https://github.com/nkz-os/nkz) — Main platform

## License

AGPL-3.0-or-later.
