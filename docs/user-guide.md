---
title: Crop Health Engine — Guía de Uso
description: Manual para agricultores y agrónomos sobre monitorización de estrés hídrico en cultivos con sensores IoT.
---

# Crop Health Engine — Guía de Uso

## ¿Qué mide?

| Indicador | Sensor | Qué significa |
|-----------|--------|---------------|
| **CWSI** (Crop Water Stress Index) | Sensor IR de temperatura foliar | 0 = sin estrés, 1 = estrés máximo. Mide la diferencia entre la temperatura de la hoja y el aire. |
| **MDS** (Maximum Daily Shrinkage) | Dendrómetro (mide contracción del tronco) | Contracción diaria del tronco en micrómetros (µm). A más estrés, más contracción. |
| **Balance Hídrico** | Sonda de suelo TDR | Precipitación − evapotranspiración del cultivo (mm). Valores negativos indican déficit. |

Los tres indicadores se combinan en una **severidad global** (LOW → MEDIUM → HIGH → CRITICAL) con recomendación de riego automática.

## ¿Qué necesito instalar?

### 1. Sensor IR de temperatura foliar

- Mide la temperatura del dosel vegetal (Tc) para calcular CWSI
- Se instala apuntando al cultivo, con ángulo de visión adecuado
- El datalogger debe publicar en MQTT con atributo `leafTemperature` en °C

### 2. Dendrómetro

- Mide la contracción/expansión del tronco en micrómetros
- Se instala en un tronco representativo del cultivo
- El datalogger debe publicar en MQTT con atributo `trunkDiameter` en µm

### 3. Sonda de suelo TDR

- Mide humedad volumétrica del suelo
- Se instala en la zona radicular del cultivo
- El datalogger debe publicar en MQTT con atributo `soilMoisture` en %

### Configuración técnica

Tu administrador de plataforma debe:
1. Crear un **Device Profile** en Nekazari que mapee los datos de tu datalogger a atributos NGSI-LD
2. Activar las **suscripciones** para que Orion-LD envíe los datos al motor Crop Health
3. Asociar el sensor a la **parcela** correspondiente

Consulta la [Guía de Administración](./admin-guide.md) para el procedimiento detallado.

## ¿Cómo veo los resultados?

Los resultados aparecen en el **dashboard** de Nekazari como un widget "Crop Health":

- **Barra CWSI**: verde (<0.3) → amarillo (0.3-0.6) → rojo (>0.6)
- **Severidad MDS**: badge de color (LOW → CRITICAL)
- **Balance hídrico**: déficit en mm (rojo) o superávit (verde)
- **Recomendación**: acción sugerida (Monitorizar / Programar riego / Regar inmediatamente)

### Significado de los colores

| Color | Severidad | Acción recomendada |
|-------|-----------|-------------------|
| Verde | LOW — Sin estrés | No se necesita acción |
| Amarillo | MEDIUM — Estrés ligero | Monitorizar evolución |
| Naranja | HIGH — Estrés significativo | Programar riego |
| Rojo | CRITICAL — Estrés severo | Regar inmediatamente |

## ¿De dónde vienen los parámetros?

El motor utiliza parámetros fenológicos específicos para cada cultivo, etapa y variedad:

- **Kc** (coeficiente de cultivo): determina la evapotranspiración
- **D1/D2** (líneas base CWSI): umbrales de estrés para el cultivo
- **MDS ref**: contracción máxima diaria de referencia

Estos parámetros provienen de **BioOrchestrator**, una base de conocimiento que integra:
- **FAO-56** (Allen et al., 1998) — valores estándar internacionales
- **Publicaciones científicas** con DOI y condiciones de ensayo
- **Ensayos de campo** de instituciones colaboradoras (CSIC, INTIA)

Si los parámetros provienen de una fuente genérica (no específica para tu variedad), el widget lo indica. En ese caso, puedes solicitar que se añadan parámetros específicos para tu cultivo/variedad/zona.

## Preguntas frecuentes

### No veo datos en el widget
- Verifica que los sensores están publicando datos (consulta con tu administrador)
- Los datos tardan hasta 5 minutos en reflejarse
- Si la parcela no tiene sensores, el widget aparecerá vacío

### El widget dice "Parámetros genéricos"
- BioOrchestrator no tiene datos específicos para tu cultivo/variedad
- Los cálculos usan valores conservadores de FAO-56
- Contacta con el soporte para añadir tu cultivo a la base de conocimiento

### ¿Cada cuánto se actualiza?
- Los sensores publican típicamente cada 15-30 minutos
- El widget se refresca cada 5 minutos
- Las suscripciones Orion-LD procesan los datos en tiempo real
