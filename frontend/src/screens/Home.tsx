import type { Difficulty, Meta, Mode } from '../api';
import { decodeWhere, encodeWhere, type Where } from '../game';

interface Props {
  meta: Meta | null;
  where: Where;
  difficulty: Difficulty;
  onWhereChange: (w: Where) => void;
  onDifficultyChange: (d: Difficulty) => void;
  onStart: (mode: Mode) => void;
  starting: boolean;
  error: string | null;
}

export function Home({
  meta,
  where,
  difficulty,
  onWhereChange,
  onDifficultyChange,
  onStart,
  starting,
  error,
}: Props) {
  const worldOk = meta?.world.selectable ?? false;
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
            {meta?.regions.map((r) => (
              <optgroup key={r.key} label={r.name}>
                <option value={`region:${r.key}`} disabled={!r.selectable}>
                  All of {r.name}
                  {r.selectable ? '' : ' — Coming soon'}
                </option>
                {meta.countries
                  .filter((c) => c.region === r.key)
                  .map((c) => (
                    <option key={c.code} value={`country:${c.code}`} disabled={!c.selectable}>
                      {c.flag} {c.name}
                      {c.selectable ? '' : ' — Coming soon'}
                    </option>
                  ))}
              </optgroup>
            ))}
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
          onClick={() => onStart('classic')}
          disabled={starting || !worldOk}
        >
          <span className="mode-title">Classic</span>
          <span className="mode-sub">Urban + Suburban · 5 rounds</span>
          <span className="mode-cta">{starting ? 'Loading…' : 'Play'}</span>
        </button>
      </section>

      {meta && !worldOk && (
        <p className="banner">No playable properties yet. Run <code>make seed</code> to load demo data.</p>
      )}
    </main>
  );
}
