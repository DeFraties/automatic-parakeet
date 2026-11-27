import type { Setting } from '../api';
import { ALL_SETTINGS, SETTING_LABEL, sortSettings } from '../game';

const ICON: Record<Setting, string> = { urban: '🏙️', suburban: '🏡', rural: '🌾' };

interface Props {
  value: Setting[];
  onChange: (s: Setting[]) => void;
}

/** Urban / Suburban / Rural toggles. At least one stays on. */
export function SettingToggles({ value, onChange }: Props) {
  return (
    <div className="toggles" role="group" aria-labelledby="settings-label">
      {ALL_SETTINGS.map((s) => {
        const on = value.includes(s);
        const last = on && value.length === 1;
        return (
          <button
            key={s}
            type="button"
            className={`toggle${on ? ' is-on' : ''}`}
            aria-pressed={on}
            disabled={last}
            title={last ? 'Keep at least one setting on' : undefined}
            onClick={() => onChange(sortSettings(on ? value.filter((x) => x !== s) : [...value, s]))}
          >
            <span aria-hidden="true">{ICON[s]}</span> {SETTING_LABEL[s]}
          </button>
        );
      })}
    </div>
  );
}
