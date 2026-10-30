import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { ArrowLeft, Sprout } from 'lucide-react';
import ParcelList from './components/ParcelList';
import ParcelHealthWorkbench from './components/ParcelHealthWorkbench';
import FleetOverview, { type FleetSummary } from './components/FleetOverview';
import { navigateTo, readParcelIdFromLocation } from './api/cropHealthApi';
import type { ParcelSummary } from './types/assessment';

const App: React.FC = () => {
  const { t } = useTranslation('crop-health');
  const [selectedParcelId, setSelectedParcelId] = useState<string | null>(readParcelIdFromLocation());
  const [selectedParcelName, setSelectedParcelName] = useState('');
  const [parcels, setParcels] = useState<ParcelSummary[]>([]);
  const [summary, setSummary] = useState<FleetSummary>({ surprises: 0, jobsToday: 0, noData: 0 });

  useEffect(() => {
    const fromUrl = readParcelIdFromLocation();
    if (fromUrl) setSelectedParcelId(fromUrl);
  }, []);

  const handleSelectParcel = (parcelId: string, parcelName: string) => {
    setSelectedParcelId(parcelId);
    setSelectedParcelName(parcelName);
  };

  const handleParcelsLoaded = (next: ParcelSummary[]) => {
    setParcels(next);
    if (selectedParcelId && !selectedParcelName) {
      const match = next.find((p) => p.parcelId === selectedParcelId);
      if (match?.parcelName) setSelectedParcelName(match.parcelName);
    }
  };

  const selectedSummary = useMemo(
    () => parcels.find((p) => p.parcelId === selectedParcelId),
    [parcels, selectedParcelId],
  );

  return (
    <div className="flex flex-col md:flex-row h-full min-h-[calc(100vh-120px)] bg-nkz-surface">
      <aside
        className={`${
          selectedParcelId ? 'hidden md:flex' : 'flex'
        } w-full md:w-[360px] flex-shrink-0 md:border-r border-nkz-border bg-nkz-surface-raised flex-col`}
      >
        <header className="p-3 border-b border-nkz-border">
          <div className="flex items-center gap-2">
            <Sprout className="w-5 h-5 text-nkz-accent-base" />
            <div>
              <h1 className="text-sm font-bold text-nkz-text-primary">{t('title')}</h1>
              <p className="text-xs text-nkz-text-muted">{t('app.subtitle')}</p>
            </div>
          </div>
        </header>

        <FleetOverview summary={summary} />

        <div className="flex-1 overflow-hidden">
          <ParcelList
            onSelectParcel={handleSelectParcel}
            selectedParcelId={selectedParcelId}
            onParcelsLoaded={handleParcelsLoaded}
            onSummary={setSummary}
          />
        </div>
      </aside>

      <main
        className={`${
          selectedParcelId ? 'block' : 'hidden md:block'
        } flex-1 overflow-y-auto p-4 bg-nkz-surface`}
      >
        {!selectedParcelId ? (
          <div className="flex items-center justify-center h-full">
            <div className="border border-nkz-border rounded-xl bg-nkz-surface-raised p-8 max-w-md text-center">
              <Sprout className="w-10 h-10 mx-auto text-nkz-accent-base" />
              <h2 className="text-base font-semibold text-nkz-text-primary mt-3">{t('app.selectPrompt')}</h2>
              <p className="text-sm text-nkz-text-muted mt-2">{t('app.selectPromptHint')}</p>
            </div>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto">
            <header className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 min-w-0">
                <button
                  type="button"
                  aria-label={t('app.backToParcels')}
                  onClick={() => setSelectedParcelId(null)}
                  className="md:hidden inline-flex items-center justify-center min-h-[44px] min-w-[44px] -ml-1 rounded-md text-nkz-text-secondary hover:text-nkz-text-primary bg-transparent border-none cursor-pointer"
                >
                  <ArrowLeft className="w-5 h-5" />
                </button>
                <div className="min-w-0">
                  <h2 className="text-base font-bold text-nkz-text-primary truncate">
                    {selectedParcelName || selectedSummary?.parcelName || selectedParcelId}
                  </h2>
                  <p className="text-xs text-nkz-text-muted mt-0.5 truncate">
                    {selectedSummary?.cropName && `🌾 ${selectedSummary.cropName} · `}
                    ID {selectedParcelId}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => navigateTo(`/entities?parcel=${encodeURIComponent(selectedParcelId)}`)}
                className="text-xs font-medium text-nkz-accent-base hover:underline cursor-pointer bg-transparent border-none flex-shrink-0"
              >
                🗺️ {t('app.viewInViewer')}
              </button>
            </header>

            <ParcelHealthWorkbench
              parcelId={selectedParcelId}
              parcelName={selectedParcelName || selectedSummary?.parcelName}
            />
          </div>
        )}
      </main>
    </div>
  );
};

export default App;
