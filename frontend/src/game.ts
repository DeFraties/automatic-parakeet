import type { Difficulty, Eligible, Meta, Mode, Setting, SummaryPayload, WhereScope } from './api';
import { formatNumber, hostFromUrl, scoreEmoji } from './format';
import { readStorage, writeStorage } from './storage';

export const MODE_LABEL: Record<Mode, string> = { classic: 'Classic', daily: 'Daily' };
export const SETTING_LABEL: Record<Setting, string> = {
  urban: 'Urban',
  rural: 'Rural',
};
// Owner decision: two categories. Suburbs count as urban.
export const ALL_SETTINGS: Setting[] = ['urban', 'rural'];
export const DEFAULT_SETTINGS: Setting[] = ['urban', 'rural'];
export const ROUNDS = 5;

export interface Where {
  scope: WhereScope;
  value: string | null;
}

export function encodeWhere(w: Where): string {
  return w.scope === 'world' ? 'world' : `${w.scope}:${w.value}`;
}

export function decodeWhere(s: string): Where {
  const [scope, value] = s.split(':');
  if (scope === 'region' || scope === 'country') return { scope, value: value ?? null };
  return { scope: 'world', value: null };
}

export function whereLabel(w: Where, meta: Meta | null): string {
  if (w.scope === 'region') return meta?.regions.find((r) => r.key === w.value)?.name ?? w.value ?? '';
  if (w.scope === 'country') {
    const c = meta?.countries.find((x) => x.code === w.value);
    return c ? `${c.flag} ${c.name}` : (w.value ?? '');
  }
  return 'World';
}

/** Canonical order for display and API: urban, rural. */
export function sortSettings(s: Setting[]): Setting[] {
  return ALL_SETTINGS.filter((x) => s.includes(x));
}

export function settingsLabel(s: Setting[]): string {
  return sortSettings(s)
    .map((x) => SETTING_LABEL[x])
    .join(' + ');
}

/** Backend's canonical encoding (alphabetical), used for leaderboard queries. */
export function encodeSettings(s: Setting[]): string {
  return [...new Set(s)].sort().join(',');
}

export function eligibleFor(e: Eligible, settings: Setting[]): number {
  return settings.reduce((n, s) => n + (e[s] ?? 0), 0);
}

/** Is a Where option playable with the chosen settings? World needs one game's worth. */
export function isSelectable(e: Eligible, settings: Setting[], meta: Meta, world = false): boolean {
  const need = world ? meta.rounds_per_game : Math.max(meta.min_pool_per_option, meta.rounds_per_game);
  return eligibleFor(e, settings) >= need;
}

export function modeBadge(
  mode: Mode,
  w: Where,
  settings: Setting[],
  difficulty: Difficulty,
  meta: Meta | null,
): string {
  const diff = difficulty === 'hard' ? '🔥 Hard' : 'Normal';
  if (mode === 'daily') return [`Daily #${meta?.daily_number ?? ''}`.trim(), diff].join(' · ');
  return [MODE_LABEL[mode], whereLabel(w, meta), settingsLabel(settings), diff].join(' · ');
}

export function buildShareText(summary: SummaryPayload, meta: Meta | null): string {
  const hard = summary.difficulty === 'hard' ? ' 🔥 HARD' : '';
  const score = `${formatNumber(summary.total_score, 'en-US')} / ${formatNumber(summary.max_score, 'en-US')}`;
  let title: string;
  if (summary.mode === 'daily') {
    title = `Ballpark Daily #${meta?.daily_number ?? 1}`;
  } else {
    const where =
      summary.where_scope === 'world'
        ? ''
        : ` (${whereLabel({ scope: summary.where_scope, value: summary.where_value }, meta)})`;
    title = `Ballpark ${MODE_LABEL[summary.mode]}${where}`;
  }
  const squares = summary.rounds.map((r) => scoreEmoji(r.score ?? 0)).join('');
  const host = hostFromUrl(meta?.public_base_url ?? 'https://ballpark.example.com');
  return `${title} — ${score}${hard}\n${squares}\n${host}`;
}

const DIFFICULTY_KEY = 'ballpark_difficulty';
const SETTINGS_KEY = 'ballpark_settings';

/** Last chosen difficulty; Normal on first visit or when storage is unavailable. */
export function loadDifficulty(): Difficulty {
  return readStorage(DIFFICULTY_KEY) === 'hard' ? 'hard' : 'normal';
}

export function saveDifficulty(d: Difficulty): void {
  writeStorage(DIFFICULTY_KEY, d);
}

export function loadSettings(): Setting[] {
  const raw = readStorage(SETTINGS_KEY);
  const parsed = (raw ?? '').split(',').filter((x): x is Setting => ALL_SETTINGS.includes(x as Setting));
  return parsed.length ? sortSettings(parsed) : DEFAULT_SETTINGS;
}

export function saveSettings(s: Setting[]): void {
  writeStorage(SETTINGS_KEY, sortSettings(s).join(','));
}
