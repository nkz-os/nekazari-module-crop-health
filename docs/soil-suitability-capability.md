# Soil-suitability capability (Crop-Health) — data contract & frontend guide

> **Audience:** frontend designers and module integrators. This documents *what*
> the soil-suitability capability exposes and *how* to surface it, so its value
> reaches the farmer instead of being buried in the backend.

## 1. What it answers

**Does the parcel's *committed* crop fit the parcel's *real* soil?** A graded
verdict — `suitable` / `marginal` / `unsuitable` / `unknown` — over three
agronomic dimensions: **pH**, **texture**, **drainage**.

- The **crop's inherent tolerance** (pH range, preferred textures, drainage class)
  is reference biology from the BioOrchestrator knowledge graph (`CropSoilSuitability`,
  fed by EcoCrop).
- The **parcel's real soil** is read live from the Soil module (`AgriSoilExtended`:
  pH, USDA texture, SCS hydrologic group / Ksat → drainage class).
- BioOrchestrator computes the verdict **once** (in its `crop-context` assembly);
  Crop-Health **reads** it and delivers it through its assessment pipeline →
  Orion → the assessments API. Crop-Health never recomputes soil state.

**Boundary — do not confuse with neighbours:**
- **≠ `waterlogging_risk`** (also in Crop-Health): that is *dynamic, weather-driven*
  anoxia risk *right now* (crop-agnostic). Soil-suitability is *static selection fit*
  for the committed crop, weather-independent.
- **≠ Soil module data**: Soil owns the soil *state*; this is a *judgment* over
  crop × soil that only exists once a crop is committed.

## 2. Data contract

### 2a. NGSI-LD attributes on `CropHealthAssessment` (Orion)
Emitted only when a verdict exists (absent → the crop/parcel had no assessable data):

| Attribute | Type | Value |
|---|---|---|
| `soilSuitabilityVerdict` | Property | `suitable` \| `marginal` \| `unsuitable` \| `unknown` |
| `soilSuitabilityReason` | Property | human-readable explanation (string) |
| `soilSuitabilityConfidence` | Property | `high` \| `medium` \| `low` |
| `soilSuitabilitySource` | Property | provenance string (crop tolerance × parcel soil) |
| `soilSuitabilityDetail` | Property | object `{ ph, texture, drainage }`, each `{ value, verdict, ... }` or null |

### 2b. Frontend JSON (`GET /assessments/latest`)
`map_entity_to_assessment` maps the attrs above into each assessment item:

```jsonc
"soilSuitability": {
  "verdict": "marginal",           // suitable | marginal | unsuitable | unknown
  "reason": "Soil pH 7.4 above crop max 7.0",
  "confidence": "medium",          // high | medium | low  (or null)
  "source": "crop tolerance (EcoCrop) × parcel soil (soilgrids)",
  "detail": {                      // any of ph/texture/drainage may be null
    "ph":       { "value": 7.4, "min": 5.0, "max": 7.0, "verdict": "marginal" },
    "texture":  { "value": "Loam", "verdict": "suitable" },
    "drainage": { "value": "well_drained", "verdict": "suitable" }
  }
}
// null when the assessment carries no verdict.
```

### 2c. Verdict semantics
- **suitable** — pH, texture and drainage within the crop's tolerance.
- **marginal** — near a bound (e.g. pH just outside range, one texture/drainage step off). Keep + flag.
- **unsuitable** — a hard mismatch (pH far outside range; extreme texture/drainage incompatibility, e.g. rice on free-draining sand). The crop is a poor fit for this land.
- **unknown** — the crop has no tolerance data, or the parcel soil is unavailable. **Never** rendered as "fine"; show it as *no data*.

**Confidence** is the trust qualifier: `medium` when ≥2 dimensions agree, `low` for a single dimension or `unknown`. The tolerance is generic reference biology, so `high` is not used here.

## 3. Display guidance

- **Severity → tone** (use existing design tokens / ui-kit intents; no custom CSS):
  `suitable` → positive/green, `marginal` → warning/amber, `unsuitable` → negative/red,
  `unknown` → muted/gray.
- **Honest unknown:** always show the `noData` message for `unknown`; never leave it
  blank (blank reads as "fine").
- **Reason** is the one-line explanation — show it as supporting text under the verdict.
- **Confidence** is a small muted qualifier, not a headline.
- **Per-dimension breakdown (`detail`)** is available for a richer view (pH / texture /
  drainage each with its own value + verdict). i18n keys `soilSuitability.dimension.*`
  are already provided for this; the baseline component does not yet render the
  breakdown — that is the natural next enhancement for designers.
- **i18n:** all copy lives under the `crop-health` namespace: `soilSuitability.title`,
  `soilSuitability.verdict.{suitable,marginal,unsuitable,unknown}`,
  `soilSuitability.confidence.{high,medium,low}`,
  `soilSuitability.dimension.{ph,texture,drainage}`, `soilSuitability.noData`.
- **Where it sits:** the baseline renders in the parcel detail view
  (`CropHealthDetail.tsx`), between the compaction and soil-sensor sections.

## 4. Baseline vs. polish
The shipped component is a *functional, honest baseline* (verdict badge + reason +
confidence + honest unknown). Final visual design — layout, the per-dimension
breakdown, iconography — is designer territory; this contract is stable to build on.
