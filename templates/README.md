# Device Profile Templates — Crop Health Sensors

Estos templates de Device Profile permiten configurar sensores para el motor de salud de cultivo (Crop Health Engine) sin necesidad de conocer los nombres exactos de atributos NGSI-LD.

## Cómo usar

1. En Nekazari, ve al Dashboard → "+ New Sensor"
2. Selecciona `AgriSensor` como tipo de entidad
3. En el paso de configuración IoT, haz clic en **"Importar JSON"**
4. Selecciona uno de los templates de esta carpeta
5. El wizard rellenará automáticamente el Device Profile con los atributos correctos
6. Continúa con la geometría (ubicación del sensor)
7. Al finalizar, recibirás las credenciales MQTT

## Templates disponibles

| Template | Sensor físico | Atributo NGSI-LD | Para qué motor |
|----------|--------------|-----------------|----------------|
| `ir-canopy-sensor.json` | Termómetro IR | `leafTemperature` | CWSI (Crop Water Stress Index) |
| `dendrometer.json` | Dendrómetro | `trunkDiameter` | MDS (Maximum Daily Shrinkage) |
| `tdr-soil-probe.json` | Sonda TDR | `soilMoisture` | Water Balance |

## Atributos MQTT que debe publicar el datalogger

### IR Canopy Sensor
```json
{
  "leaf_temp": 28.5,
  "air_temp": 26.0
}
```

### Dendrometer
```json
{
  "diameter_um": 1250
}
```

### TDR Soil Probe
```json
{
  "vwc_pct": 22.5,
  "soil_temp": 24.0,
  "bulk_ec": 0.8
}
```
