---
title: Crop Health Engine — Guía de Uso
description: Manual para agricultores y agrónomos — seguimiento del cultivo sembrado, zonas de gestión, cosecha prevista y sensores IoT.
---

# Crop Health Engine — Guía de Uso

## Antes de empezar

Salud del cultivo sigue los cultivos **sembrados**. El recorrido habitual es:

1. Planificar el cultivo en **Planificación de cultivos** (casilla ○).
2. Registrar la siembra en **Operaciones de campo → Registrar siembra**, con su fecha real. La casilla pasa a ●.
3. Desde esa noche, Salud del cultivo evalúa la parcela cada día y calcula la cosecha prevista.

Una parcela sin siembra registrada aparece con *Sin datos de salud para esta parcela*, y la cosecha prevista explica el motivo (por ejemplo, *La parcela no tiene cultivo asignado* o *El cultivo aún no está sembrado*).

Los sensores IoT son **opcionales**: sin ellos el motor trabaja con el tiempo de la parcela, el satélite y el suelo. Con ellos gana precisión (ver más abajo).

## La ficha de la parcela

Abre **Salud del cultivo** y elige una parcela, o selecciónala en el visor 3D para verla en el panel lateral. De arriba abajo:

- **Estado**: *Saludable*, *Vigilar*, *Estresado* o *Crítico*, con la acción recomendada, la fase del cultivo y avisos de helada, calor o vigor.
- **Zonas de gestión** (si la parcela tiene zonas): se listan como *Zona 1*, *Zona 2*… en el orden del mapa (de norte a sur y de oeste a este). En el mapa, la etiqueta de cada zona lleva el mismo número y el valor de la capa activa (`2 · M`). Pasa el ratón por una zona del panel, o púlsala, para iluminarla en el mapa.
- **Línea fenológica**: las fases del cultivo con su fecha prevista.
- **Riesgos activos**: enfermedades y compactación del suelo.
- **Pestañas** *Agua*, *Planta*, *Rendimiento y acción* y *Analítica*.
- **Diagnóstico de fuentes de datos**: qué fuentes llegan a la parcela y cuáles fallan.

## Cosecha prevista

Es el primer bloque de la pestaña **Rendimiento y acción**.

- **Una fila por modelo**, nunca promediadas, con la horquilla en t/ha y una etiqueta: *Experimental* mientras la campaña está en curso, *Validada* cuando termina, *Techo* para el máximo que permite el agua.
- **Actualizar** recalcula la previsión en uno o dos minutos. Además se recalcula sola cada noche.
- **Ver detalle de la simulación** abre la simulación completa (curvas, suelo, tiempo y avisos) en Planificación de cultivos.
- **Sin cifra**, el bloque dice por qué. Hoy solo da cifra el trigo de secano en España; para el resto indica *Este cultivo aún no está validado en esta zona*.
- Si falta el régimen hídrico, pregunta **¿Secano o regadío?** ahí mismo y recalcula al responder.
- Al registrar la cosecha, el bloque pasa a *Campaña terminada* y conserva la última previsión.

Debajo aparece el **Aprovechamiento de Potencial (Yield Gap FAO-33)** con la nota *Indicador instantáneo*: es el estrés hídrico del día aplicado a la etapa actual, no una previsión de cosecha.

## Sensores IoT (opcional)

### ¿Qué mide?

| Indicador | Sensor | Qué significa |
|-----------|--------|---------------|
| **CWSI** (Crop Water Stress Index) | Sensor IR de temperatura foliar | 0 = sin estrés, 1 = estrés máximo. Mide la diferencia entre la temperatura de la hoja y el aire. |
| **MDS** (Maximum Daily Shrinkage) | Dendrómetro (mide contracción del tronco) | Contracción diaria del tronco en micrómetros (µm). A más estrés, más contracción. |
| **Balance Hídrico** | Sonda de suelo TDR | Precipitación − evapotranspiración del cultivo (mm). Valores negativos indican déficit. |

Los tres indicadores se combinan en una **severidad global** (LOW → MEDIUM → HIGH → CRITICAL) con recomendación de riego automática.

### ¿Qué necesito instalar?

#### 1. Sensor IR de temperatura foliar

- Mide la temperatura del dosel vegetal (Tc) para calcular CWSI
- Se instala apuntando al cultivo, con ángulo de visión adecuado
- El datalogger debe publicar en MQTT con atributo `leafTemperature` en °C

#### 2. Dendrómetro

- Mide la contracción/expansión del tronco en micrómetros
- Se instala en un tronco representativo del cultivo
- El datalogger debe publicar en MQTT con atributo `trunkDiameter` en µm

#### 3. Sonda de suelo TDR

- Mide humedad volumétrica del suelo
- Se instala en la zona radicular del cultivo
- El datalogger debe publicar en MQTT con atributo `soilMoisture` en %

#### Configuración técnica

Tu administrador de plataforma debe:
1. Crear un **Device Profile** en Nekazari que mapee los datos de tu datalogger a atributos NGSI-LD
2. Activar las **suscripciones** para que Orion-LD envíe los datos al motor Crop Health
3. Asociar el sensor a la **parcela** correspondiente

Consulta la [Guía de Administración](./admin-guide.md) para el procedimiento detallado.

## La tarjeta del panel de control

En el **panel de control** de Nekazari, la tarjeta "Salud del Cultivo" resume todas las parcelas:

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

### No veo datos de la parcela
- Comprueba que la siembra está registrada en Operaciones de campo: sin ella la parcela no se evalúa
- La primera evaluación llega la noche siguiente a la siembra
- Si tienes sensores, verifica con tu administrador que están publicando datos

### El widget dice "Parámetros genéricos"
- BioOrchestrator no tiene datos específicos para tu cultivo/variedad
- Los cálculos usan valores conservadores de FAO-56
- Contacta con el soporte para añadir tu cultivo a la base de conocimiento

### ¿Cada cuánto se actualiza?
- Evaluación de cada parcela sembrada: cada noche (04:00 UTC)
- Cosecha prevista: cada noche (05:00 UTC) y cuando pulsas *Actualizar*
- Con sensores: cada lectura se procesa al llegar (suelen publicar cada 15-30 minutos)
- Las pantallas se refrescan cada 5 minutos
