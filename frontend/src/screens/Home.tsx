import type { DailyStatus, Difficulty, Meta, Setting } from '../api';
import { SettingToggles } from '../components/SettingToggles';
import { decodeWhere, encodeWhere, isSelectable, settingsLabel, type Where } from '../game';
import { formatNumber } from '../format';

interface Props {
  meta: Meta | null;
  where: Where;
  difficulty: Difficulty;
  settings: Setting[];
  daily: DailyStatus | null;
  onWhereChange: (w: Where) => void;
  onDifficultyChange: (d: Difficulty) => void;
  onSettingsChange: (s: Setting[]) => void;
  onStart: () => void;
  onDaily: () => void;
  starting: boolean;
  error: string | null;
}

export function Home({
  meta,
  where,
  difficulty,
  settings,
  daily,
  onWhereChange,
  onDifficultyChange,
  onSettingsChange,
  onStart,
  onDaily,
  starting,
  error,
}: Props) {
  const worldOk = meta ? isSelectable(meta.world.eligible, settings, meta, true) : false;

  let dailySub = 'Same 5 homes for everyone today';
  let dailyCta = 'Play';
  if (daily?.completed) {
    dailySub = `✓ Done today · ${formatNumber(daily.score ?? 0)} pts`;
    dailyCta = 'See leaderboard';
  } else if (daily?.played) {
    dailySub = 'In progress';
    dailyCta = 'Resume';
  }

  return (
    <main className="home" id="main">
      <header className="hero">
        <h1 className="logo">
          Ballpark<span className="logo-dot" aria-hidden="true">.</span>
        </h1>
        <p className="tagline">Real homes, real prices. How close can you get?</p>
      </header>

      <section className="settings card" aria-label="Game settings">
        <div className="setting">
          <label htmlFor="where">Where</label>
          <select
            id="where"
            value={encodeWhere(where)}
            onChange={(e) => onWhereChange(decodeWhere(e.target.value))}
            disabled={!meta}
          >
            <option value="world">🌍 World</option>
            {meta?.regions.map((r) => {
              const regionOk = isSelectable(r.eligible, settings, meta);
              return (
                <optgroup key={r.key} label={r.name}>
                  <option value={`region:${r.key}`} disabled={!regionOk}>
                    All of {r.name}
                    {regionOk ? '' : ' — Coming soon'}
                  </option>
                  {meta.countries
                    .filter((c) => c.region === r.key)
                    .map((c) => {
                      const ok = isSelectable(c.eligible, settings, meta);
                      return (
                        <option key={c.code} value={`country:${c.code}`} disabled={!ok}>
                          {c.flag} {c.name}
                          {ok ? '' : ' — Coming soon'}
                        </option>
                      );
                    })}
                </optgroup>
              );
            })}
          </select>
        </div>

        <div className="setting">
          <span className="setting-label" id="difficulty-label">
            Difficulty
          </span>
          <div className="segmented" role="radiogroup" aria-labelledby="difficulty-label">
            {(
              [
                ['normal', 'Normal (USD)'],
                ['hard', 'Hard (local currency)'],
              ] as const
            ).map(([d, label]) => (
              <button
                key={d}
                type="button"
                role="radio"
                aria-checked={difficulty === d}
                className={difficulty === d ? 'is-active' : ''}
                onClick={() => onDifficultyChange(d)}
              >
                {d === 'hard' && <span aria-hidden="true">🔥 </span>}
                {label}
              </button>
            ))}
          </div>
          <p className="setting-hint">
            {difficulty === 'hard'
              ? 'Hard: guess in the local currency — yen, rand, złoty… No exchange-rate hints.'
              : 'Normal: every guess is in US dollars.'}
          </p>
        </div>

        <div className="setting setting-wide">
          <span className="setting-label" id="settings-label">
            Neighbourhoods
          </span>
          <SettingToggles value={settings} onChange={onSettingsChange} />
        </div>
      </section>

      {error && (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      )}

      <section className="modes" aria-label="Game modes">
        <button
          type="button"
          className="mode-card mode-card-primary"
          onClick={onStart}
          disabled={starting || !worldOk}
        >
          <span className="mode-title">Classic</span>
          <span className="mode-sub">{settingsLabel(settings)} · 5 rounds</span>
          <span className="mode-cta">{starting ? 'Loading…' : 'Play'}</span>
        </button>
        <button
          type="button"
          className="mode-card"
          onClick={onDaily}
          disabled={starting}
        >
          <span className="mode-title">
            Daily Challenge {meta ? <span className="mode-num">#{meta.daily_number}</span> : null}
          </span>
          <span className="mode-sub">{dailySub}</span>
          <span className="mode-cta">{dailyCta}</span>
        </button>
      </section>

      <nav className="home-links" aria-label="More">
        <a href="#/leaderboards">🏆 Leaderboards</a>
        <a href="#/about">How it works &amp; data</a>
      </nav>



      {meta && !worldOk && (
        <p className="banner">
          Not enough playable homes for these settings yet. Try turning on more neighbourhood types,
          or load demo homes with <code>make seed</code>.
        </p>
      )}
    </main>
  );
}
