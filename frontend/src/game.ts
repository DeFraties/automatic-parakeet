import type { Difficulty, Meta, Mode, SummaryPayload, WhereScope } from './api';
import { formatNumber, hostFromUrl, scoreEmoji } from './format';
import { readStorage, writeStorage } from './storage';

export const MODE_LABEL: Record<Mode, string> = {
  classic: 'Classic',
  urban: 'Urban',
  suburban: 'Suburban',
};

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

export function modeBadge(mode: Mode, w: Where, difficulty: Difficulty, meta: Meta | null): string {
  return [MODE_LABEL[mode], whereLabel(w, meta), difficulty === 'hard' ? '🔥 Hard' : 'Normal'].join(
    ' · ',
  );
}

export function buildShareText(summary: SummaryPayload, meta: Meta | null): string {
  const title = `Ballpark ${MODE_LABEL[summary.mode]}`;
  const hard = summary.difficulty === 'hard' ? ' 🔥 HARD' : '';
  const where =
    summary.where_scope === 'world'
      ? ''
      : ` (${whereLabel({ scope: summary.where_scope, value: summary.where_value }, meta)})`;
  const line1 = `${title}${where} — ${formatNumber(summary.total_score, 'en-US')} / ${formatNumber(summary.max_score, 'en-US')}${hard}`;
  const squares = summary.rounds.map((r) => scoreEmoji(r.score ?? 0)).join('');
  const host = hostFromUrl(meta?.public_base_url ?? 'https://ballpark.example.com');
  return `${line1}\n${squares}\n${host}`;
}

const DIFFICULTY_KEY = 'ballpark_difficulty';

/** Last chosen difficulty; Normal on first visit or when storage is unavailable. */
export function loadDifficulty(): Difficulty {
  return readStorage(DIFFICULTY_KEY) === 'hard' ? 'hard' : 'normal';
}

export function saveDifficulty(d: Difficulty): void {
  writeStorage(DIFFICULTY_KEY, d);
}
