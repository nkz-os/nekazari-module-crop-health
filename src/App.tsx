import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import ParcelList from './components/ParcelList';
import CropStatusSnapshot from './components/CropStatusSnapshot';
import CropHealthDetail from './components/CropHealthDetail';

const App: React.FC = () => {
  const { t } = useTranslation('crop-health');
  const [selectedParcelId, setSelectedParcelId] = useState<string | null>(null);

  const handleSelectParcel = (parcelId: string) => {
    setSelectedParcelId(parcelId);
  };

  const handleViewInViewer = (parcelId: string) => {
    const sdk = (window as any).__NKZ_SDK__;
    if (sdk?.navigate) {
      sdk.navigate(`/entities?parcel=${encodeURIComponent(parcelId)}`);
    }
  };

  return (
    <div className="flex h-full" style={{ minHeight: 'calc(100vh - 120px)' }}>
      {/* Left sidebar — Parcel List */}
      <div
        className="flex-shrink-0 border-r border-nkz-border bg-nkz-surface overflow-hidden"
        style={{ width: 320 }}
      >
        <div className="p-2 border-b border-nkz-border">
          <h2 className="text-nkz-text-primary font-bold text-sm">🌱 {t('title')}</h2>
        </div>
        <ParcelList onSelectParcel={handleSelectParcel} selectedParcelId={selectedParcelId} />
      </div>

      {/* Right panel — Detail */}
      <div className="flex-1 overflow-y-auto p-4">
        {!selectedParcelId ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-sm">
              <span className="text-4xl">🌱</span>
              <h3 className="text-nkz-text-primary font-semibold text-lg mt-3">
                {t('app.selectPrompt')}
              </h3>
              <p className="text-nkz-text-muted text-sm mt-1">
                {t('app.selectPromptHint')}
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-nkz-text-primary font-bold text-lg">
                {selectedParcelId}
              </h2>
              <button
                onClick={() => handleViewInViewer(selectedParcelId)}
                className="text-nkz-accent-base text-sm hover:underline"
              >
                🗺️ {t('app.viewInViewer')}
              </button>
            </div>
            <CropStatusSnapshot parcelId={selectedParcelId} />
            <CropHealthDetail parcelId={selectedParcelId} />
          </>
        )}
      </div>
    </div>
  );
};

export default App;
