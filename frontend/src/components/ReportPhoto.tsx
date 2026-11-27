import { useState } from 'react';
import type { ReportReason } from '../api';

const REASONS: [ReportReason, string][] = [
  ['price_visible', 'The price is visible in this photo'],
  ['broken', 'Broken image'],
  ['person', 'Shows a person'],
  ['other', 'Something else'],
];

export function ReportPhoto({ onReport }: { onReport: (reason: ReportReason) => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ReportReason>('price_visible');
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');

  if (state === 'sent') {
    return (
      <p className="report-done" role="status">
        Thanks — reported. We'll take a look.
      </p>
    );
  }
  if (!open) {
    return (
      <button type="button" className="link-button report-link" onClick={() => setOpen(true)}>
        Report photo
      </button>
    );
  }
  return (
    <form
      className="report-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setState('sending');
        try {
          await onReport(reason);
          setState('sent');
        } catch {
          setState('error');
        }
      }}
    >
      <fieldset>
        <legend>What's wrong with this photo?</legend>
        {REASONS.map(([value, label]) => (
          <label key={value}>
            <input
              type="radio"
              name="report-reason"
              value={value}
              checked={reason === value}
              onChange={() => setReason(value)}
            />{' '}
            {label}
          </label>
        ))}
      </fieldset>
      <div className="report-actions">
        <button type="button" className="link-button" onClick={() => setOpen(false)}>
          Cancel
        </button>
        <button type="submit" className="btn btn-ghost" disabled={state === 'sending'}>
          Send report
        </button>
      </div>
      {state === 'error' && (
        <p className="guess-error" role="alert">
          Couldn't send the report. Try again.
        </p>
      )}
    </form>
  );
}
