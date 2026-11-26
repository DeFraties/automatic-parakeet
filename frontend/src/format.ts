/** Number / money formatting and parsing helpers. Pure functions, unit-tested. */

export const FT2_PER_M2 = 10.7639;

export function userLocale(): string {
  return (typeof navigator !== 'undefined' && navigator.language) || 'en-US';
}

export function formatMoney(amount: number, currency: string, locale = userLocale()): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  }).format(Math.round(amount));
}

export function formatNumber(n: number, locale = userLocale()): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(Math.round(n));
}

export function currencySymbol(currency: string, locale = userLocale()): string {
  const parts = new Intl.NumberFormat(locale, { style: 'currency', currency }).formatToParts(0);
  return parts.find((p) => p.type === 'currency')?.value ?? currency;
}

export function currencyName(currency: string, locale = userLocale(), fallback?: string): string {
  try {
    const name = new Intl.DisplayNames([locale], { type: 'currency' }).of(currency);
    if (name) return name.charAt(0).toUpperCase() + name.slice(1);
  } catch {
    /* DisplayNames unsupported */
  }
  return fallback ?? currency;
}

const SUFFIX: Record<string, number> = { k: 1e3, m: 1e6, b: 1e9 };

/**
 * Parse a guess typed by the player. Accepts grouping separators ("1,250,000", "1.250.000",
 * "1 250 000") and k/m/b shorthand ("450k", "1.2m", "1,5m"). Returns null if not a positive number.
 */
export function parseAmount(raw: string): number | null {
  const text = raw.trim().toLowerCase().replace(/[\s\u00a0\u202f']/g, '');
  if (!text) return null;
  const m = text.match(/^([\d.,]+)([kmb])?$/);
  if (!m) return null;
  let [, num, suffix] = m;
  let value: number;
  if (suffix) {
    // Decimal shorthand. A lone comma followed by 1-2 digits is a decimal comma ("1,5m").
    if (num.includes('.') && num.includes(',')) num = num.replace(/,/g, '');
    else if (/^\d+,\d{1,2}$/.test(num)) num = num.replace(',', '.');
    else num = num.replace(/,/g, '');
    if ((num.match(/\./g) ?? []).length > 1) return null;
    value = Number(num) * SUFFIX[suffix];
  } else {
    // Whole amounts only: all separators are grouping separators.
    value = Number(num.replace(/[.,]/g, ''));
  }
  if (!Number.isFinite(value) || value <= 0) return null;
  return Math.round(value);
}

/** Reformat the text field as the user types: plain digits get grouping separators. */
export function formatTyped(raw: string, locale = userLocale()): string {
  // "1." or "1.2" may be the start of shorthand like "1.2m": leave it alone for now.
  if (/^\d+[.,]\d{0,2}$/.test(raw)) return raw;
  if (/^[\d\s.,\u00a0\u202f']*$/.test(raw)) {
    const digits = raw.replace(/\D/g, '');
    if (!digits) return '';
    return formatNumber(Number(digits), locale);
  }
  return raw; // shorthand like "1.2m" is left as typed
}

/** Log-scale slider mapping: value = min × (max/min)^t, t in [0, 1]. */
export function sliderToValue(t: number, min: number, max: number): number {
  const c = Math.min(1, Math.max(0, t));
  return min * Math.pow(max / min, c);
}

export function valueToSlider(value: number, min: number, max: number): number {
  if (value <= min) return 0;
  if (value >= max) return 1;
  return Math.log(value / min) / Math.log(max / min);
}

/** Round to 3 significant figures so slider values look like human guesses. */
export function roundSignificant(value: number, digits = 3): number {
  if (value <= 0) return 0;
  const p = Math.pow(10, Math.floor(Math.log10(value)) - digits + 1);
  return Math.round(value / p) * p;
}

export function formatArea(m2: number, locale = userLocale()): string {
  return `${formatNumber(m2, locale)} m² (${formatNumber(m2 * FT2_PER_M2, locale)} ft²)`;
}

export function scoreEmoji(score: number): string {
  if (score >= 4000) return '🟩';
  if (score >= 2000) return '🟨';
  if (score >= 1) return '🟧';
  return '🟥';
}

export function hostFromUrl(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
