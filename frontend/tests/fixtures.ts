import type { Meta, RevealPayload, RoundPayload, SummaryPayload } from '../src/api';

const REGION_OF: Record<string, string> = {
  US: 'north_america', CA: 'north_america', MX: 'north_america', BR: 'south_america',
  PT: 'europe', ES: 'europe', GB: 'europe', FR: 'europe', IT: 'europe', PL: 'europe',
  HR: 'europe', ZA: 'africa', AU: 'oceania', NZ: 'oceania', JP: 'east_asia', TW: 'east_asia',
};

export function makeMeta(selectable: string[] = ['FR', 'JP']): Meta {
  const countries = Object.entries(REGION_OF).map(([code, region]) => ({
    code,
    name: code === 'FR' ? 'France' : code === 'JP' ? 'Japan' : `Country ${code}`,
    flag: '🏳️',
    currency: code === 'JP' ? 'JPY' : 'EUR',
    currency_name: 'X',
    region,
    locale: 'en-US',
    eligible: selectable.includes(code)
      ? { urban: 40, suburban: 40, total: 80 }
      : { urban: 1, suburban: 1, total: 2 },
    selectable: selectable.includes(code),
  }));
  const regionKeys = ['north_america', 'south_america', 'europe', 'africa', 'oceania', 'east_asia'];
  return {
    countries,
    regions: regionKeys.map((key) => ({
      key,
      name: key.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      countries: countries.filter((c) => c.region === key).map((c) => c.code),
      eligible: { urban: 0, suburban: 0, total: 0 },
      selectable: key === 'europe',
    })),
    world: { eligible: { urban: 30, suburban: 30, total: 60 }, selectable: true },
    sources: [{ key: 'demo', display_name: 'DEMO data (fictional)', homepage: null, license_note: null }],
    daily_number: 1,
    min_pool_per_option: 50,
    rounds_per_game: 5,
    public_base_url: 'https://ballpark.example.com',
    contact_email: 'owner@example.com',
    quota: { games_available: true },
  };
}

export function makeRound(n: number, hard = false): RoundPayload {
  return {
    round_no: n,
    rounds_total: 5,
    streetview_url: null,
    attribution: null,
    difficulty: hard ? 'hard' : 'normal',
    guess_currency: hard ? 'JPY' : 'USD',
    local_currency: 'JPY',
    slider: hard ? { min: 500_000, max: 10_000_000_000 } : { min: 5_000, max: 50_000_000 },
    clues: {
      country: 'Japan',
      country_code: 'JP',
      flag: '🇯🇵',
      region: 'Tokyo',
      city: `City${n}`,
      setting: 'urban',
      property_type: 'apartment',
      area_m2: 55,
      bedrooms: 2,
      bathrooms: 1,
      year_built: 2001,
      price_year: 2025,
      price_type: 'sale_record',
    },
    map: { lat_approx: 35.66, lng_approx: 139.7 },
  };
}

export function makeReveal(n: number, score = 4000): RevealPayload {
  return {
    round_no: n,
    price_local: 68_000_000,
    currency: 'JPY',
    price_usd: 455_600,
    guess_local: 60_000_000,
    guess_usd: 402_000,
    pct_off: 11.8,
    score,
    label: 'In the ballpark',
    price_per_m2_local: 1_236_364,
    area_m2: 55,
    price_date: '2025-03-01',
    price_type: 'sale_record',
    source_name: 'DEMO data (fictional)',
    listing_url: n === 1 ? 'https://example.com/demo/1' : null,
    fx_hint: '1 USD ≈ 149 JPY',
    city: `City${n}`,
    country_code: 'JP',
  };
}

export function makeSummary(scores: number[], hard = false): SummaryPayload {
  return {
    game_id: 'g1',
    mode: 'classic',
    where_scope: 'world',
    where_value: null,
    difficulty: hard ? 'hard' : 'normal',
    total_score: scores.reduce((a, b) => a + b, 0),
    max_score: 25_000,
    rounds: scores.map((s, i) => ({
      round_no: i + 1,
      city: `City${i + 1}`,
      country_code: 'JP',
      flag: '🇯🇵',
      currency: 'JPY',
      price_local: 68_000_000,
      price_usd: 455_600,
      guess_local: 60_000_000,
      guess_usd: 402_000,
      score: s,
    })),
  };
}
