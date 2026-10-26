import { useCallback, useEffect, useState } from 'react';
import { authHeaders, cropHealthFetch, PHENOLOGY_PARAMS_URL } from '../api/cropHealthApi';
import type {
  AssessmentData,
  CropStatus,
  CorrelationPoint,
  CorrelationStats,
  DiseaseRisk,
  Freshness,
  NextJob,
  PhenologyParams,
  PhenologyStatus,
  PlannedCrop,
  Surprise,
  TrendPoint,
  ZoneAssessmentData,
  ZonesResponse,
} from '../types/assessment';

interface ParcelHealthBundle {
  assessment: AssessmentData | null;
  zoneAssessments: ZoneAssessmentData[];
  isWholeParcel: boolean;
  parcelValues: ZonesResponse['parcelValues'];
  cropStatus: CropStatus;
  freshness: Freshness;
  stale: boolean;
  nextJob: NextJob | null;
  surprise: Surprise | null;
  plannedCrop: PlannedCrop | null;
  phenologyParams: PhenologyParams | null;
  phenologyStatus: PhenologyStatus | null;
  trend: TrendPoint[];
  correlation: CorrelationPoint[];
  correlationStats: CorrelationStats | null;
  diseases: DiseaseRisk[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useParcelHealthData(parcelId: string | null): ParcelHealthBundle {
  const [assessment, setAssessment] = useState<AssessmentData | null>(null);
  const [zoneAssessments, setZoneAssessments] = useState<ZoneAssessmentData[]>([]);
  const [isWholeParcel, setIsWholeParcel] = useState(true);
  const [parcelValues, setParcelValues] = useState<ZonesResponse['parcelValues']>({});
  const [cropStatus, setCropStatus] = useState<CropStatus>('active');
  const [freshness, setFreshness] = useState<Freshness>('none');
  const [stale, setStale] = useState(false);
  const [nextJob, setNextJob] = useState<NextJob | null>(null);
  const [surprise, setSurprise] = useState<Surprise | null>(null);
  const [plannedCrop, setPlannedCrop] = useState<PlannedCrop | null>(null);
  const [phenologyParams, setPhenologyParams] = useState<PhenologyParams | null>(null);
  const [phenologyStatus, setPhenologyStatus] = useState<PhenologyStatus | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [correlation, setCorrelation] = useState<CorrelationPoint[]>([]);
  const [correlationStats, setCorrelationStats] = useState<CorrelationStats | null>(null);
  const [diseases, setDiseases] = useState<DiseaseRisk[]>([]);
  const [loading, setLoading] = useState(Boolean(parcelId));
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!parcelId) {
      setAssessment(null);
      setZoneAssessments([]);
      setIsWholeParcel(true);
      setParcelValues({});
      setCropStatus('active');
      setFreshness('none');
      setStale(false);
      setNextJob(null);
      setSurprise(null);
      setPlannedCrop(null);
      setPhenologyParams(null);
      setPhenologyStatus(null);
      setTrend([]);
      setCorrelation([]);
      setCorrelationStats(null);
      setDiseases([]);
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const [latest, zonesRes, history, corr, phenology, diseaseRes] = await Promise.all([
        cropHealthFetch<{
          assessments: AssessmentData[];
          cropStatus?: CropStatus;
          freshness?: Freshness;
          stale?: boolean;
          nextJob?: NextJob | null;
          surprise?: Surprise | null;
          plannedCrop?: PlannedCrop | null;
        }>(`/assessments/latest?parcelId=${encodeURIComponent(parcelId)}`),
        cropHealthFetch<Partial<ZonesResponse>>(
          `/assessments/zones?parcelId=${encodeURIComponent(parcelId)}`,
        ),
        cropHealthFetch<{ points: TrendPoint[] }>(`/assessments/history?parcelId=${encodeURIComponent(parcelId)}&days=7`),
        cropHealthFetch<{ pairs: CorrelationPoint[]; stats?: CorrelationStats }>(
          `/assessments/correlation?parcelId=${encodeURIComponent(parcelId)}&days=30`,
        ),
        cropHealthFetch<PhenologyStatus>(`/parcels/${encodeURIComponent(parcelId)}/phenology-status`),
        cropHealthFetch<{ risks: DiseaseRisk[] }>(`/diseases/active?parcelId=${encodeURIComponent(parcelId)}`),
      ]);

      const nextAssessment = latest?.assessments?.[0] ?? null;
      setAssessment(nextAssessment);
      setZoneAssessments(zonesRes?.zones ?? []);
      setIsWholeParcel(zonesRes?.isWholeParcel ?? true);
      setParcelValues(zonesRes?.parcelValues ?? {});
      setCropStatus(latest?.cropStatus ?? 'active');
      setFreshness(latest?.freshness ?? 'none');
      setStale(latest?.stale ?? false);
      setNextJob(latest?.nextJob ?? null);
      setSurprise(latest?.surprise ?? null);
      setPlannedCrop(latest?.plannedCrop ?? null);
      setTrend(history?.points ?? []);
      setCorrelation(corr?.pairs ?? []);
      setCorrelationStats(corr?.stats ?? null);
      setPhenologyStatus(phenology);
      setDiseases(diseaseRes?.risks ?? []);

      const species = nextAssessment?.species ?? nextAssessment?.cropSpecies;
      if (species) {
        try {
          const pResp = await fetch(`${PHENOLOGY_PARAMS_URL}?species=${encodeURIComponent(species)}`, {
            credentials: 'include',
            headers: authHeaders(),
          });
          setPhenologyParams(pResp.ok ? await pResp.json() : null);
        } catch {
          setPhenologyParams(null);
        }
      } else {
        setPhenologyParams(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'error');
    } finally {
      setLoading(false);
    }
  }, [parcelId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    assessment,
    zoneAssessments,
    isWholeParcel,
    parcelValues,
    cropStatus,
    freshness,
    stale,
    nextJob,
    surprise,
    plannedCrop,
    phenologyParams,
    phenologyStatus,
    trend,
    correlation,
    correlationStats,
    diseases,
    loading,
    error,
    refresh,
  };
}
