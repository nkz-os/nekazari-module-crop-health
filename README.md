# Crop Health Engine — NKZ Module

Real-time biophysical inference engine for the [Nekazari](https://nkz-os.org) precision agriculture platform.

## What it does

Monitors crop health in real time by combining IoT sensor data, scientific phenology parameters from [BioOrchestrator](https://github.com/nkz-os/nekazari-module-bioorchestrator), and weather data from the platform Weather API.

Publishes `CropHealthAssessment` entities to Orion-LD with full data fidelity tracing.

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
    ├── BioOrchestrator ←── GET /api/graph/phenology-params (Kc, D1, D2)
    ├── Weather API     ←── GET /api/weather/current (T, HR, precip, ETo)
    ├── Vegetation      ←── VegetationIndex entities (NDVI, EVI, SAVI...)
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
| **CropHealthWidget** | `dashboard-widget` | Dashboard card: CWSI, MDS, water balance, thermal, vigor, severity, irrigation recommendation |
| **CropHealthContextPanel** | `context-panel` | 3D viewer right panel: full detail per parcel (all 9 engines + phenology provenance + NDVI correlation) |
| **CropHealthLayer** | `map-layer` | CesiumMap heatmap: parcels colored by CWSI (green→yellow→orange→red) |
| **DiseaseRiskWidget** | `dashboard-widget` | Active disease alerts (Mills, Magarey, TomCast, Gubler) |

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
| **BioOrchestrator** | Read | REST → Neo4j (phenology, soil, heat tolerance) |
| **Weather API** (timeseries-reader) | Read | `/api/weather/current` |
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

## Deployment

```bash
docker build --network=host --no-cache \
  -t ghcr.io/nkz-os/crop-health-backend:v1.0.0 \
  -f backend/Dockerfile backend/
docker push ghcr.io/nkz-os/crop-health-backend:v1.0.0

kubectl apply -f k8s/backend-deployment.yaml -n nekazari

# Frontend IIFE
npm install && npx vite build
mc cp dist/nkz-module.js minio/frontend-static/modules/crop-health/nkz-module.js
```

## Related modules

- [BioOrchestrator](https://github.com/nkz-os/nekazari-module-bioorchestrator) — Knowledge graph + phenology API
- [IkerKeta](https://github.com/nkz-os/ikerketa) — ETL pipeline (25 connectors)
- [Nekazari Platform](https://github.com/nkz-os/nkz) — Main platform

## License

AGPL-3.0-or-later.
