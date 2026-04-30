# nekazari-module-crop-health

Real-time biophysical inference engine for the [Nekazari](https://github.com/nkz-os/nkz) platform.

## What it does

**Headless CEP (Complex Event Processing) module** — no frontend UI. Ingests IoT sensor telemetry via FIWARE webhooks, applies biophysical models, and publishes standardised `CropHealthAssessment` NGSI-LD entities for downstream consumers.

### Models implemented

| Engine | Input Sensor | Output | Formula |
|--------|-------------|--------|---------|
| **CWSI** | IR leaf temperature | Water stress index [0–1] | `(Tc-Ta-D1)/(D2-D1)` |
| **MDS** | Dendrómetro (trunk diameter) | Cellular-level shrinkage severity | `max(D,24h) - min(D,24h)` vs `MDS_ref` |
| **Water Balance** | Soil moisture (TDR) + weather | Deficit/surplus in mm | `Precip - (ETo × Kc)` |

### Architecture

```text
FIWARE Orion-LD       ──→  Webhook  ──→  Redis Sliding Window
                                              │
BioOrchestrator (Neo4j) ◄──── Context Client ──┤
Weather (TimescaleDB)   ◄─────────────────────┤
                                              │
                           Pipeline ──→  Engines (CWSI, MDS, WB)
                                              │
                                    Publication ──→ Orion-LD
                                                    (CropHealthAssessment)
```

**Complements** (does NOT duplicate) the existing `risk-worker` water stress model, which uses batch meteorological data. This module adds **real-time canopy-level sensing** for precision agriculture.

## Pending (Roadmap)

1. **Integration Testing**: Validate Redis sliding window (ZADD/ZREMRANGEBYSCORE) end-to-end with live `docker-compose up`.
2. **Webhook Verification**: Simulate FIWARE NGSI-LD payload and verify pipeline execution.
3. **Security Audit**: Review un-sanitized inputs, rate limiting on webhooks, and `entity_id` validation.
4. **K8s Deployment**: Deploy to cluster using existing `k8s/` manifests.
5. **Upstream Integration**: BioOrchestrator endpoint for dynamic D1/D2/Kc phenology parameters (currently using FAO-56 fallback).

## Quick Start (local)

```bash
# 1. Copy env
cp env.example .env

# 2. Start backend + Redis
docker-compose up -d

# 3. Run tests
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -v

# 4. Register FIWARE subscriptions (requires Orion-LD)
ORION_LD_URL=http://localhost:1026 python scripts/register_subscriptions.py
```

## Integration Points

| Service | Direction | Method |
|---------|-----------|--------|
| **Orion-LD** | IN (webhook) + OUT (upsert) | HTTP POST/PATCH |
| **Redis** | Read/Write | Sorted Sets (sliding window) |
| **BioOrchestrator** | Read | REST → Neo4j (D1, D2, Kc, MDS_ref) |
| **TimescaleDB** | Read | `weather_observations` table |
| **Downstream** (AgriEnergy, CUE) | Subscribe | Via FIWARE `CropHealthAssessment` |

## Frontend / i18n

This module is **headless** (no UI). If you add a frontend later, follow NKZ module conventions: `useTranslation` from `@nekazari/sdk`, `src/locales/en.json` + `src/locales/es.json` with matching keys, and register the namespace once via `i18n.addResourceBundle` (see other `nkz-module-*` repos).

## License

AGPL-3.0
