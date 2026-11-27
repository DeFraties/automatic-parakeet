import { useEffect, useState } from 'react';
import { api, type Difficulty, type LeaderboardEntry, type Meta, type Mode, type Setting } from '../api';
import { SettingToggles } from '../components/SettingToggles';
import { formatNumber } from '../format';
import { DEFAULT_SETTINGS, decodeWhere, encodeSettings, encodeWhere, type Where } from '../game';

type Period = 'day' | 'week' | 'all';

function lastDays(n: number): string[] {
  const out: string[] = [];
  const now = new Date();
  for (let i = 0; i < n; i++) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - i));
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

export function Leaderboards({ meta, initialDifficulty }: { meta: Meta | null; initialDifficulty: Difficulty }) {
  const [mode, setMode] = useState<Mode>('daily');
  const [difficulty, setDifficulty] = useState<Difficulty>(initialDifficulty);
  const [where, setWhere] = useState<Where>({ scope: 'world', value: null });
  const [settings, setSettings] = useState<Setting[]>(DEFAULT_SETTINGS);
  const [period, setPeriod] = useState<Period>('all');
  const [day, setDay] = useState(lastDays(1)[0]);
  const [entries, setEntries] = useState<LeaderboardEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setEntries(null);
    setError(null);
    const q =
      mode === 'daily'
        ? { difficulty, date: day }
        : {
            difficulty,
            where_scope: where.scope,
            where_value: where.value,
            settings: encodeSettings(settings),
            period,
          };
    api.leaderboard(mode, q).then(
      (r) => alive && setEntries(r.entries),
      () => alive && setError('Could not load the leaderboard.'),
    );
    return () => {
      alive = false;
    };
  }, [mode, difficulty, where, settings, period, day]);

  return (
    <main className="boards" id="main">
      <h1>Leaderboards</h1>
      <div className="tabs" role="tablist" aria-label="Mode">
        {(['daily', 'classic'] as const).map((m) => (
          <button
            key={m}
            role="tab"
            type="button"
            aria-selected={mode === m}
            className={mode === m ? 'is-active' : ''}
            onClick={() => setMode(m)}
          >
            {m === 'daily' ? 'Daily' : 'Classic'}
          </button>
        ))}
      </div>

      <div className="card board-filters">
        <div className="segmented" role="radiogroup" aria-label="Difficulty">
          {(['normal', 'hard'] as const).map((d) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={difficulty === d}
              className={difficulty === d ? 'is-active' : ''}
              onClick={() => setDifficulty(d)}
            >
              {d === 'hard' ? '🔥 Hard' : 'Normal'}
            </button>
          ))}
        </div>
        {mode === 'daily' ? (
          <label className="inline-field">
            Day
            <select value={day} onChange={(e) => setDay(e.target.value)}>
              {lastDays(7).map((d, i) => (
                <option key={d} value={d}>
                  {i === 0 ? `Today (${d})` : d}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <>
            <label className="inline-field">
              Where
              <select
                value={encodeWhere(where)}
                onChange={(e) => setWhere(decodeWhere(e.target.value))}
              >
                <option value="world">🌍 World</option>
                {meta?.regions.map((r) => (
                  <optgroup key={r.key} label={r.name}>
                    <option value={`region:${r.key}`}>All of {r.name}</option>
                    {meta.countries
                      .filter((c) => c.region === r.key)
                      .map((c) => (
                        <option key={c.code} value={`country:${c.code}`}>
                          {c.flag} {c.name}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="inline-field">
              Period
              <select value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
                <option value="day">Today</option>
                <option value="week">7 days</option>
                <option value="all">All time</option>
              </select>
            </label>
            <div className="setting-wide">
              <span className="setting-label" id="settings-label">
                Neighbourhoods
              </span>
              <SettingToggles value={settings} onChange={setSettings} />
            </div>
          </>
        )}
      </div>

      <div className="card table-wrap">
        {error && <p role="alert">{error}</p>}
        {!error && entries === null && <p>Loading…</p>}
        {entries && entries.length === 0 && <p>No scores yet. Be the first!</p>}
        {entries && entries.length > 0 && (
          <table className="summary-table board-table">
            <caption className="sr-only">Top scores</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Player</th>
                <th scope="col">Score</th>
                <th scope="col">Date</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={`${e.rank}-${e.nickname}`}>
                  <td>{e.rank}</td>
                  <td>
                    <span aria-hidden="true">{e.flag}</span> {e.nickname}
                  </td>
                  <td className="num">{formatNumber(e.score)}</td>
                  <td className="num">{e.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <a href="#/" className="btn btn-ghost back-link">
        ← Home
      </a>
    </main>
  );
}
