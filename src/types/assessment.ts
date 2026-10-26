export interface PhenologyParams {
  kc?: number;
  d1?: number;
  d2?: number;
  mds_ref?: number;
  match_level?: string;
  stage?: string;
  provenance?: {
    short?: string;
    doi?: string;
    author?: string;
    year?: number;
    conditions?: string;
  };
}

export interface TrendPoint {
  date: string;
  cwsi?: number;
  mds?: number;
  balance?: number;
}

/** One point of `/assessments/history`; attributes the assessment lacks come back as null. */
export interface HistoryPoint {
  date: string;
  cwsi?: number | null;
  mds?: number | null;
  balance?: number | null;
  composite?: number | null;
  severity?: string | null;
}

export interface CorrelationPoint {
  date: string;
  ndvi?: number;
  cwsi?: number;
}

export interface CorrelationStats {
  n: number;
  r2: number | null;
  slope: number | null;
  intercept: number | null;
}

export interface AssessmentData {
  id?: string;
  parcelId?: string;
  parcelName?: string;
  cwsiValue?: number;
  mdsValue?: number;
  mdsSeverity?: string;
  waterBalanceDeficit?: number;
  overallSeverity: string;
  recommendedAction: string;
  phenologySource: string;
  assessedAt: string;
  compositeStressIndex?: number;
  dominantStressor?: string;
  compositeStress?: {
    index?: number;
    dominantStressor?: string;
    waterContribution?: number;
    thermalContribution?: number;
    vigorContribution?: number;
    stageKy?: number;
  };
  yieldUtilizationPct?: number;
  yieldGapConfidence?: string;
  thermalCondition?: string;
  thermalSeverity?: string;
  heatStressHours?: number;
  frostHours?: number;
  thermalDataFidelity?: string;
  vigorIndex?: number;
  vigorCondition?: string;
  growthAnomaly?: number;
  vigorIndexUsed?: string;
  vigorDataFidelity?: string;
  dataFidelity?: string;
  wueStatus?: string;
  wueKgM3?: number;
  wueBiomassKg?: number;
  wueWaterAppliedMm?: number;
  wueTrend?: string;
  species?: string;
  cropSpecies?: string;
  cropName?: string;
  varietyName?: string;
  phenologyDeviation?: string;
  stageProgressPct?: number;
  gddAccumulated?: number;
  phenologyStage?: string;
  vhi?: { vhi?: number; vci?: number; tci?: number; asiPct?: number; tciSource?: string };
  sar?: {
    isFlooded?: boolean;
    floodStage?: string;
    surfaceMoistureIndex?: number;
    waterloggingRisk?: string;
    dataFidelity?: string;
  };
  compactionRisk?: {
    level?: string;
    score?: number;
    susceptibilityScore?: number;
    factors?: string[];
    moistureWarning?: boolean;
    vigorConcern?: boolean;
    requiresVerification?: boolean;
    advisory?: string;
  };
  soilSensors?: { ph?: number; ec?: number; moisturePct?: number; temperatureC?: number };
  kc?: number;
  management?: string;
  soilProperties?: {
    sandPct?: number;
    clayPct?: number;
    fieldCapacity: number;
    wiltingPoint: number;
    ksatMmH: number;
    scsHydrologicGroup: string;
    usdaTextureClass: string;
    source: string;
    hasData: boolean;
  };
  waterStressIndex?: number | null;
  waterStressFidelity?: 'iot_sensor' | 'parcel_weather' | 'regional_proxy' | 'unavailable' | null;
  waterStressObservedAt?: string | null;
  underPanelWaterStressIndex?: number | null;
  underPanelWaterStressFidelity?: 'iot_sensor' | 'parcel_weather' | 'regional_proxy' | 'unavailable' | null;
  underPanelWaterStressObservedAt?: string | null;
  soilWaterMm?: number;
  soilAWCmm?: number;
  soilWaterRatio?: number;
  soilWaterBalance?: {
    swMm?: number;
    awcMm?: number;
    swRatio?: number;
    stressLevel?: string;
    soilMoistureConfidence?: string;
    stressCoefficientKs?: number;
    actualETmm?: number;
    deepPercolationMm?: number;
    depletionFractionP?: number;
  };
  waterloggingRiskLevel?: string;
  waterloggingSaturationHours?: number;
  waterloggingRisk?: {
    riskLevel?: string;
    saturationHours?: number;
    excessMm?: number;
    drainageRateMmH?: number;
  };
  soilSuitability?: {
    verdict: 'suitable' | 'marginal' | 'unsuitable' | 'unknown';
    reason?: string | null;
    confidence?: 'high' | 'medium' | 'low' | null;
    source?: string | null;
    detail?: {
      ph?: Record<string, unknown> | null;
      texture?: Record<string, unknown> | null;
      drainage?: Record<string, unknown> | null;
    } | null;
  } | null;
}

export interface ZoneAssessmentData extends AssessmentData {
  zoneId: string;
  zoneUrn?: string;
  geometry?: {
    type: string;
    coordinates: number[][][] | number[][][][];
  };
  sensorNearby?: boolean;
  differsFromParcel?: boolean;
}

export interface ZonesResponse {
  zones: ZoneAssessmentData[];
  isWholeParcel: boolean;
  parcelValues: Partial<
    Pick<AssessmentData, 'cwsiValue' | 'compositeStressIndex' | 'vigorIndex' | 'overallSeverity'>
  >;
}

export type CropStatus = 'active' | 'none';
export type Freshness = 'none' | 'fresh' | 'aging' | 'stale';

export interface NextJob {
  kind: 'irrigate' | 'sow' | 'treat' | 'harvest' | 'pending_assessment' | 'none_until';
  when: 'today' | string | null;
  detail: Record<string, unknown>;
}

export interface Surprise {
  code: string;
  detail: Record<string, unknown>;
}

export interface PlannedCrop {
  species: string;
  names?: Record<string, string>;
  sowingDate?: string | null;
}

export interface ParcelSummary {
  parcelId: string;
  parcelName?: string;
  cropName?: string;
  phenologyStage?: string;
  areaHa?: number;
  overallSeverity?: string;
  cwsiValue?: number;
  vigorIndex?: number;
  assessedAt?: string;
  hasData: boolean;
  healthIndicator?: string;
  sourcesActive?: number;
  sourcesDegraded?: number;
  sourcesDown?: number;
  cropStatus: CropStatus;
  freshness: Freshness;
  stale: boolean;
  nextJob: NextJob | null;
  surprise: Surprise | null;
  plannedCrop: PlannedCrop | null;
  lastAssessment: { assessedAt: string; cropName?: string } | null;
}

export interface DiseaseRisk {
  disease: string;
  crop: string;
  risk_level: string;
  conditions: string;
  confidence: string;
  lwd_method?: string;
  source_model?: string;
  recommended_action: string;
  parcelId?: string;
}

export interface PhenologyStageProjection {
  stage: string;
  current?: boolean;
  reached?: boolean;
  gddMin?: number;
  gddMax?: number;
  projectedDate?: string;
  projectedEnd?: string;
}

export interface PhenologyStatus {
  status?: string;
  parcelId?: string;
  asOf?: string;
  currentStage?: string;
  deviation?: string;
  phenologySource?: string;
  dataFidelity?: string;
  gdd?: { accumulated?: number };
  stages?: PhenologyStageProjection[];
}
