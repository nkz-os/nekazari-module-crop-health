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
  predictedYieldKgHa?: number;
  baselineYieldKgHa?: number;
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
}

export interface ZoneAssessmentData extends AssessmentData {
  zoneId: string;
  zoneUrn?: string;
  geometry?: {
    type: string;
    coordinates: number[][][] | number[][][][];
  };
  sensorNearby?: boolean;
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
  status: string;
  gddMin?: number;
  gddMax?: number;
  projectedStart?: string;
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
