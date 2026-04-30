---
title: Crop Health Engine — Guía de Administración
description: Configuración, arquitectura y troubleshooting del motor de inferencia biofísica para administradores de plataforma.
---

# Crop Health Engine — Guía de Administración

## Arquitectura

```
Sensores IoT → MQTT (Mosquitto) → IoT Agent → Orion-LD
                                                  │
                    ┌─────────────────────────────┤
                    │   NGSI-LD Subscription      │
                    ▼                             │
            crop-health webhook                   │
            POST /webhooks/fiware-sensors         │
                    │                             │
                    ├── Redis (buffer 48h)        │
                    ├── BioOrchestrator (fenología)│
                    ├── TimescaleDB (weather)      │
                    │                             │
                    ▼                             │
            Pipeline: CWSI / MDS / Water Balance  │
                    │                             │
                    ▼                             │
            Orion-LD ← CropHealthAssessment       │
                    │                             │
                    ├── telemetry-worker          │
                    │   (persiste a TimescaleDB)   │
                    │                             │
                    ▼                             │
            Dashboard Widget (frontend)           │
```

## Requisitos previos

### Servicios necesarios

| Servicio | URL interna | Obligatorio |
|----------|------------|-------------|
| Orion-LD | `http://orion-ld-service:1026` | Sí |
| Redis | `redis://redis-service:6379/0` | Sí |
| BioOrchestrator | `http://bioorchestrator-api-service:8420` | No (usa defaults si no disponible) |
| TimescaleDB | `postgresql://.../nekazari` | Recomendado (balance hídrico sin VPD si no) |
| Email Service | `http://email-service:5000` | Opcional (alertas por email) |

### Variables de entorno

```bash
# Requeridas
REDIS_URL=redis://:password@redis-service:6379/0

# Recomendadas
WEATHER_DB_URL=postgresql://nekazari:password@postgresql-service:5432/nekazari
BIOORCHESTRATOR_URL=http://bioorchestrator-api-service:8420

# Opcionales
ORION_LD_URL=http://orion-ld-service:1026
KEYCLOAK_URL=https://auth.robotika.cloud/auth
```

## Configuración de sensores

### 1. Crear Device Profile

El Device Profile define cómo los datos raw del datalogger se transforman en atributos NGSI-LD. Debe incluir al menos uno de estos atributos:

| Atributo NGSI-LD | Tipo | Unidad | Sensor físico |
|-----------------|------|--------|---------------|
| `leafTemperature` | Property, Number | °C | IR termómetro |
| `trunkDiameter` | Property, Number | µm | Dendrómetro |
| `soilMoisture` | Property, Number | % | Sonda TDR |

Usa el wizard de Entidades en Nekazari (Dashboard → "+ New Sensor") y selecciona `AgriSensor`. Importa un Device Profile JSON o créalo manualmente.

### 2. Asociar sensor a parcela

La entidad `DeviceMeasurement` que publique el IoT Agent debe incluir una relación `refAgriParcel`:

```json
{
  "refAgriParcel": {
    "type": "Relationship",
    "object": "urn:ngsi-ld:AgriParcel:tu-parcela-id"
  }
}
```

Si esta relación no existe, el pipeline intenta extraer el ID de parcela del `entity_id` usando heurística (último segmento tras `:`).

### 3. Activar suscripciones Orion-LD

Ejecuta el script de registro:

```bash
cd nkz-module-crop-health
python scripts/register_subscriptions.py
```

O verifica manualmente desde Orion-LD:

```bash
curl http://orion-ld-service:1026/ngsi-ld/v1/subscriptions?type=Subscription \
  | jq '.[] | select(.description | contains("CropHealth"))'
```

## Troubleshooting

### Redis no conectado

El health check muestra `"redis":"not_connected"`:

```bash
kubectl exec -n nekazari deploy/crop-health-backend -- \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read())"
```

Causas:
- La contraseña de Redis no está en la URL (`redis://:PASSWORD@host:port/db`)
- El servicio Redis no es accesible desde el namespace

Solución:
```bash
kubectl set env deployment/crop-health-backend -n nekazari \
  REDIS_URL="redis://:$(kubectl get secret redis-secret -n nekazari -o jsonpath='{.data.password}' | base64 -d)@redis-service:6379/0"
kubectl rollout restart deployment/crop-health-backend -n nekazari
```

### Sin datos de weather

El balance hídrico no se calcula (solo CWSI y MDS). Verifica:
```bash
kubectl get env deployment/crop-health-backend -n nekazari | grep WEATHER_DB_URL
```

Si está vacío:
```bash
kubectl set env deployment/crop-health-backend -n nekazari \
  WEATHER_DB_URL="postgresql://nekazari:$(kubectl get secret postgresql-secret -n nekazari -o jsonpath='{.data.password}' | base64 -d)@postgresql-service:5432/nekazari"
```

### Parámetros fenológicos genéricos

El dashboard muestra "Parámetros genéricos" cuando BioOrchestrator no tiene datos específicos.

Verificar conectividad:
```bash
kubectl exec -n nekazari deploy/crop-health-backend -- python -c "
import httpx, asyncio
async def check():
    async with httpx.AsyncClient() as c:
        r = await c.get('http://bioorchestrator-api-service:8420/healthz')
        print(r.status_code, r.json())
asyncio.run(check())
"
```

Verificar datos fenológicos:
```bash
kubectl exec -n nekazari deploy/bioorchestrator-backend -- python -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://bioorchestrator-neo4j:7687', auth=('neo4j','bioorchestrator'))
with d.session() as s:
    r = s.run('MATCH (s:Species) RETURN s.name, s.scientificName')
    for rec in r: print(rec[0], '-', rec[1])
d.close()
"
```

### CropHealthAssessment no aparece en telemetry_events

Verificar que la suscripción existe:
```bash
kubectl exec -n nekazari deploy/telemetry-worker -- python -c "
import urllib.request, json
r = urllib.request.urlopen('http://orion-ld-service:1026/ngsi-ld/v1/subscriptions?type=Subscription')
subs = json.loads(r.read())
for s in subs:
    entities = str(s.get('entities', []))
    if 'CropHealthAssessment' in entities:
        print('OK:', s.get('id'), '-', s.get('description'), '- active:', s.get('isActive'))
"
```

Si no existe, reinicia el telemetry-worker para que cree las suscripciones:
```bash
kubectl rollout restart deployment/telemetry-worker -n nekazari
```

## API tokens y secretos

| Token | Dónde se configura | Estado típico |
|-------|-------------------|---------------|
| EPPO (BioOrchestrator) | `bioorchestrator-secrets` / `EPPO_API_TOKEN` | Solicitar en data.eppo.int |
| IUCN (BioOrchestrator) | `bioorchestrator-secrets` / `IUCN_API_TOKEN` | Requiere aprobación |
| DAD-IS (BioOrchestrator) | `bioorchestrator-secrets` / `bioorchestrator-dadis-token` | Pendiente FAO |
| Redis password | `REDIS_URL` env var | Leer de `redis-secret` |
| Weather DB | `WEATHER_DB_URL` env var | Leer de `postgresql-secret` |

## Monitoreo

```bash
# Logs
kubectl logs -n nekazari -l app=crop-health-backend --tail=50

# Métricas de pipeline
kubectl logs -n nekazari -l app=crop-health-backend --tail=100 | grep "Pipeline triggered"
```
