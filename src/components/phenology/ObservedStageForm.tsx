import React, { useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button, Input, Select } from '@nekazari/ui-kit';
import { recordObservedStage } from '../../api/fieldOperationsApi';
import { BBCH_PRINCIPAL_STAGES, newClientId, parseBbch, todayIso, validateObserved } from './phenologyBbch';

const KNOWN_ERRORS = ['invalid_phenological_stage', 'missing_fields', 'invalid_parcel', 'invalid_notes', 'network_error'];

interface ObservedStageFormProps {
  parcelId: string;
  onRecorded?: () => void;
}

/** "Record observed stage": sends a scouting operation with the BBCH code to field-operations. */
const ObservedStageForm: React.FC<ObservedStageFormProps> = ({ parcelId, onRecorded }) => {
  const { t } = useTranslation('crop-health');
  const [code, setCode] = useState('');
  const [date, setDate] = useState(() => todayIso());
  const [note, setNote] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One id per form open: a retry of the same record is idempotent on the server.
  const clientId = useRef<string>(newClientId());

  const stageOptions = BBCH_PRINCIPAL_STAGES.map((d) => ({
    value: String(d),
    label: `${d}x · ${t(`phenologyTimeline.bbchStage.${d}`)}`,
  }));

  const onShortcut = (digit: string) => {
    // Fills the first digit; keeps the second one if already typed.
    setCode(code.length === 2 ? `${digit}${code[1]}` : digit);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (sending) return;
    const invalid = validateObserved(code, date, todayIso());
    if (invalid) {
      setError(t(`phenologyTimeline.form.error.${invalid}`));
      return;
    }
    setSending(true);
    setError(null);
    const result = await recordObservedStage({
      parcelId, code: parseBbch(code)!, date, note, clientId: clientId.current,
    });
    setSending(false);
    if (result.ok) {
      setCode('');
      setNote('');
      setDate(todayIso());
      clientId.current = newClientId();
      onRecorded?.();
      return;
    }
    setError(KNOWN_ERRORS.includes(result.code)
      ? t(`phenologyTimeline.form.error.${result.code}`)
      : t('phenologyTimeline.form.error.generic'));
  };

  return (
    <form className="mt-3 border-t border-nkz-border pt-2 space-y-2" onSubmit={submit}>
      <p className="text-xs font-semibold text-nkz-text-primary">{t('phenologyTimeline.form.title')}</p>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-nkz-text-secondary space-y-1 block">
          <span>{t('phenologyTimeline.form.stageShortcut')}</span>
          <Select
            size="sm"
            value={code.length ? code[0] : ''}
            onValueChange={onShortcut}
            options={stageOptions}
            placeholder={t('phenologyTimeline.form.stagePlaceholder')}
            disabled={sending}
          />
        </label>
        <label className="text-xs text-nkz-text-secondary space-y-1 block">
          <span>{t('phenologyTimeline.form.code')}</span>
          <Input
            size="sm"
            type="number"
            inputMode="numeric"
            min={0}
            max={99}
            step={1}
            value={code}
            onChange={(ev) => setCode(ev.target.value)}
            disabled={sending}
          />
        </label>
        <label className="text-xs text-nkz-text-secondary space-y-1 block">
          <span>{t('phenologyTimeline.form.date')}</span>
          <Input
            size="sm"
            type="date"
            max={todayIso()}
            value={date}
            onChange={(ev) => setDate(ev.target.value)}
            disabled={sending}
          />
        </label>
        <label className="text-xs text-nkz-text-secondary space-y-1 block">
          <span>{t('phenologyTimeline.form.note')}</span>
          <Input
            size="sm"
            type="text"
            maxLength={500}
            value={note}
            onChange={(ev) => setNote(ev.target.value)}
            disabled={sending}
          />
        </label>
      </div>
      {error && <p role="alert" className="text-xs text-nkz-danger-strong">{error}</p>}
      <Button type="submit" variant="primary" size="sm" disabled={sending}>
        {sending ? t('phenologyTimeline.form.sending') : t('phenologyTimeline.form.submit')}
      </Button>
    </form>
  );
};

export default ObservedStageForm;
