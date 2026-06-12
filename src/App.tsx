import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import ParcelList from './components/ParcelList';
import SourceStatusPanel from './components/SourceStatusPanel';
import CropStatusSnapshot from './components/CropStatusSnapshot';
import CropHealthDetail from './components/CropHealthDetail';

const App: React.FC = () => {
  const { t } = useTranslation('crop-health');
  const [selectedParcelId, setSelectedParcelId] = useState<string | null>(null);
  const [selectedParcelName, setSelectedParcelName] = useState<string>("");

  const handleSelectParcel = (parcelId: string, parcelName: string) => {
    setSelectedParcelId(parcelId);
    setSelectedParcelName(parcelName);
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
        className="flex-shrink-0 border-r border-nkz-border bg-white overflow-hidden flex flex-col shadow-sm"
        style={{ width: 340 }}
      >
        {/* Header */}
        <div className="p-2.5 border-b border-nkz-border bg-nkz-surface">
          <div className="flex items-center gap-2">
            <span className="text-lg">🌱</span>
            <span className="text-sm font-bold text-nkz-text-primary">
              {t('title')}
            </span>
          </div>
        </div>

        {/* Parcel list */}
        <div className="flex-1 overflow-hidden">
          <ParcelList onSelectParcel={handleSelectParcel} selectedParcelId={selectedParcelId} />
        </div>
      </div>

      {/* Right panel — Detail */}
      <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
        {!selectedParcelId ? (
          <div className="flex items-center justify-center h-full">
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-8 max-w-sm text-center">
              <div className="flex flex-col items-center gap-3">
                <span className="text-4xl">🌱</span>
                <h3 className="text-base font-semibold text-nkz-text-primary">
                  {t('app.selectPrompt')}
                </h3>
                <p className="text-sm text-nkz-text-muted">
                  {t('app.selectPromptHint')}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto">
            {/* Parcel header */}
            <div className="bg-white border border-gray-200 rounded-lg p-3 mb-3 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-bold text-nkz-text-primary">
                    {selectedParcelName || selectedParcelId}
                  </h2>
                  {selectedParcelName && (
                    <p className="text-xs text-nkz-text-muted mt-0.5">
                      ID: {selectedParcelId}
                    </p>
                  )}
                </div>
                <button
                  onClick={() => handleViewInViewer(selectedParcelId)}
                  className="text-xs font-medium text-nkz-accent-base hover:underline cursor-pointer bg-transparent border-none"
                >
                  🗺️ {t('app.viewInViewer')}
                </button>
              </div>
            </div>

            {/* Content sections */}
            <SourceStatusPanel parcelId={selectedParcelId} parcelName={selectedParcelName} />
            <CropStatusSnapshot parcelId={selectedParcelId} parcelName={selectedParcelName} />
            <CropHealthDetail parcelId={selectedParcelId} />
          </div>
        )}
      </div>
    </div>
  );
};

export default App;
