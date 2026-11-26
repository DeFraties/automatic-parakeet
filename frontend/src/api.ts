import { getDeviceId } from './deviceId';

export type Difficulty = 'normal' | 'hard';
export type Mode = 'classic' | 'urban' | 'suburban';
export type WhereScope = 'world' | 'region' | 'country';

export interface Eligible {
  urban: number;
  suburban: number;
  total: number;
}

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
  quota: { games_available: boolean };
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
  streetview_url: string | null;
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

export interface SummaryPayload {
  game_id: string;
  mode: Mode;
  where_scope: WhereScope;
  where_value: string | null;
  difficulty: Difficulty;
  total_score: number;
  max_score: number;
  rounds: SummaryRow[];
}

export interface CreateGameResponse {
  game_id: string;
  rounds_total: number;
  mode: Mode;
  where_scope: WhereScope;
  where_value: string | null;
  difficulty: Difficulty;
  round: RoundPayload;
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
  return (await res.json()) as T;
}

export const api = {
  meta: () => request<Meta>('/meta'),
  createGame: (body: {
    mode: Mode;
    where_scope: WhereScope;
    where_value: string | null;
    difficulty: Difficulty;
  }) => request<CreateGameResponse>('/games', { method: 'POST', body: JSON.stringify(body) }),
  guess: (gameId: string, roundNo: number, amount: number, currency: string) =>
    request<GuessResponse>(`/games/${encodeURIComponent(gameId)}/rounds/${roundNo}/guess`, {
      method: 'POST',
      body: JSON.stringify({ amount, currency }),
    }),
};
