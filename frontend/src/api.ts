import { getDeviceId } from './deviceId';

export type Difficulty = 'normal' | 'hard';
export type Mode = 'classic' | 'daily';
export type WhereScope = 'world' | 'region' | 'country';
export type Setting = 'urban' | 'suburban' | 'rural';

export type Eligible = Record<Setting, number>;

export interface MetaCountry {
  code: string;
  name: string;
  flag: string;
  currency: string;
  currency_name: string;
  region: string;
  locale: string;
  eligible: Eligible;
  selectable: boolean;
}

export interface MetaRegion {
  key: string;
  name: string;
  emoji: string;
  countries: string[];
  eligible: Eligible;
  selectable: boolean;
}

export interface Meta {
  countries: MetaCountry[];
  regions: MetaRegion[];
  world: { eligible: Eligible; selectable: boolean };
  sources: { key: string; display_name: string; homepage: string | null; license_note: string | null }[];
  daily_number: number;
  min_pool_per_option: number;
  rounds_per_game: number;
  public_base_url: string;
  contact_email: string;
  settings: { all: Setting[]; default: Setting[] };
  tile_url: string;
  tile_attribution: string;
  streetview_enabled: boolean;
  photo_sources: { mapillary: boolean; google: boolean };
  quota: { games_available: boolean; daily_available: boolean };
}

export interface Clues {
  country: string;
  country_code: string;
  flag: string;
  region?: string | null;
  city: string;
  setting: string;
  property_type: string;
  area_m2?: number | null;
  bedrooms?: number | null;
  bathrooms?: number | null;
  year_built?: number | null;
  price_year: number;
  price_type: 'sale_record' | 'asking';
}

export interface RoundPayload {
  round_no: number;
  rounds_total: number;
  image_url: string | null;
  image_source: 'listing' | 'google' | 'mapillary' | null;
  attribution: string | null;
  difficulty: Difficulty;
  guess_currency: string;
  local_currency: string;
  slider: { min: number; max: number };
  clues: Clues;
  map: { lat_approx: number; lng_approx: number };
}

export interface RevealPayload {
  round_no: number;
  price_local: number;
  currency: string;
  price_usd: number;
  guess_local: number;
  guess_usd: number;
  pct_off: number;
  score: number;
  label: string;
  price_per_m2_local: number | null;
  area_m2: number | null;
  price_date: string;
  price_type: 'sale_record' | 'asking';
  source_name: string;
  listing_url: string | null;
  fx_hint: string | null;
  city: string;
  country_code: string;
}

export interface SummaryRow {
  round_no: number;
  city: string;
  country_code: string;
  flag: string;
  currency: string;
  price_local: number;
  price_usd: number;
  guess_local: number | null;
  guess_usd: number | null;
  score: number | null;
}

export interface GameHeader {
  game_id: string;
  rounds_total: number;
  mode: Mode;
  where_scope: WhereScope;
  where_value: string | null;
  settings: Setting[];
  difficulty: Difficulty;
}

export interface SummaryPayload {
  game_id: string;
  mode: Mode;
  where_scope: WhereScope;
  where_value: string | null;
  settings: Setting[];
  difficulty: Difficulty;
  total_score: number;
  max_score: number;
  rounds: SummaryRow[];
}

export interface CreateGameResponse extends GameHeader {
  round: RoundPayload;
}

export interface ResumeResponse extends GameHeader {
  round?: RoundPayload;
  score?: number;
  summary?: SummaryPayload;
}

export interface DailyStatus {
  date: string;
  number: number;
  played: boolean;
  completed: boolean;
  game_id: string | null;
  score: number | null;
  difficulty: Difficulty | null;
}

export interface LeaderboardEntry {
  rank: number;
  nickname: string;
  score: number;
  flag: string;
  date: string;
}

export interface LeaderboardResponse {
  mode: Mode;
  difficulty: Difficulty;
  entries: LeaderboardEntry[];
}

export interface LeaderboardQuery {
  difficulty: Difficulty;
  where_scope?: WhereScope;
  where_value?: string | null;
  settings?: string;
  period?: 'day' | 'week' | 'all';
  date?: string;
}

export interface GuessResponse {
  reveal: RevealPayload;
  next_round?: RoundPayload;
  summary?: SummaryPayload;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Device-Id': getDeviceId(),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let code = 'error';
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail?.code) {
        code = body.detail.code;
        message = body.detail.message ?? message;
      }
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return null as T;
  return (await res.json()) as T;
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>('/meta'),
  createGame: (body: {
    mode: 'classic';
    where_scope: WhereScope;
    where_value: string | null;
    difficulty: Difficulty;
    settings: Setting[];
  }) => request<CreateGameResponse>('/games', post(body)),
  getGame: (gameId: string) => request<ResumeResponse>(`/games/${encodeURIComponent(gameId)}`),
  daily: () => request<DailyStatus>('/daily'),
  startDaily: (difficulty: Difficulty) =>
    request<CreateGameResponse>('/daily/start', post({ difficulty })),
  leaderboard: (mode: Mode, q: LeaderboardQuery) => {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v != null && v !== '') params.set(k, String(v));
    return request<LeaderboardResponse>(`/leaderboards/${mode}?${params}`);
  },
  submitScore: (gameId: string, nickname: string) =>
    request<{ rank: number; nickname: string; score: number }>(
      '/leaderboards',
      post({ game_id: gameId, nickname }),
    ),
  requestRemoval: (body: { email: string; reference: string; message: string }) =>
    request<{ id: number; status: string }>('/removals', post(body)),
  reportImageError: (gameId: string, roundNo: number, source: string) =>
    request<null>(
      '/telemetry/image-error',
      post({ game_id: gameId, round_no: roundNo, source }),
    ).catch(() => null),
  guess: (gameId: string, roundNo: number, amount: number, currency: string) =>
    request<GuessResponse>(`/games/${encodeURIComponent(gameId)}/rounds/${roundNo}/guess`, {
      method: 'POST',
      body: JSON.stringify({ amount, currency }),
    }),
};
