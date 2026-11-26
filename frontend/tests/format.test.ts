import { describe, expect, it } from 'vitest';
import {
  formatArea,
  formatMoney,
  formatTyped,
  parseAmount,
  roundSignificant,
  scoreEmoji,
  sliderToValue,
  valueToSlider,
} from '../src/format';
import { buildShareText } from '../src/game';
import { makeMeta, makeSummary } from './fixtures';

describe('parseAmount', () => {
  it.each([
    ['425000', 425_000],
    ['425,000', 425_000],
    ['1.250.000', 1_250_000],
    ['1 250 000', 1_250_000],
    ['450k', 450_000],
    ['450K', 450_000],
    ['1.2m', 1_200_000],
    ['1,5m', 1_500_000],
    ['2b', 2_000_000_000],
    ['1,200k', 1_200_000],
  ])('%s -> %d', (input, expected) => {
    expect(parseAmount(input)).toBe(expected);
  });

  it.each(['', 'abc', '0', '-5', '1.2.3m', '12x', '3億'])('rejects %s', (input) => {
    expect(parseAmount(input)).toBeNull();
  });
});

describe('formatting', () => {
  it('formats currencies without minor units', () => {
    expect(formatMoney(38_000_000, 'JPY', 'en-US')).toBe('¥38,000,000');
    expect(formatMoney(1_234_567.89, 'USD', 'en-US')).toBe('$1,234,568');
    expect(formatMoney(12_000_000_000, 'TWD', 'en-US')).toBe('NT$12,000,000,000');
  });

  it('adds thousands separators as you type', () => {
    expect(formatTyped('1234567', 'en-US')).toBe('1,234,567');
    expect(formatTyped('1,2345', 'en-US')).toBe('12,345');
    expect(formatTyped('450k', 'en-US')).toBe('450k');
    expect(formatTyped('1.', 'en-US')).toBe('1.');
    expect(formatTyped('1.2', 'en-US')).toBe('1.2');
    expect(formatTyped('', 'en-US')).toBe('');
  });

  it('formats area in m² and ft²', () => {
    expect(formatArea(120, 'en-US')).toBe('120 m² (1,292 ft²)');
  });

  it('rounds to significant figures', () => {
    expect(roundSignificant(123_456)).toBe(123_000);
    expect(roundSignificant(9_876_543)).toBe(9_880_000);
  });
});

describe('log slider mapping', () => {
  const min = 5_000;
  const max = 50_000_000;
  it('maps the ends and the geometric midpoint', () => {
    expect(sliderToValue(0, min, max)).toBeCloseTo(min);
    expect(sliderToValue(1, min, max)).toBeCloseTo(max);
    expect(sliderToValue(0.5, min, max)).toBeCloseTo(500_000);
  });
  it('round-trips', () => {
    for (const t of [0, 0.1, 0.33, 0.5, 0.77, 1]) {
      expect(valueToSlider(sliderToValue(t, min, max), min, max)).toBeCloseTo(t, 10);
    }
    for (const v of [5_000, 77_777, 425_000, 12_000_000]) {
      expect(sliderToValue(valueToSlider(v, min, max), min, max)).toBeCloseTo(v, 4);
    }
  });
  it('clamps out-of-range values', () => {
    expect(valueToSlider(1, min, max)).toBe(0);
    expect(valueToSlider(1e12, min, max)).toBe(1);
  });
});

describe('share text', () => {
  it('uses emoji thresholds and the domain', () => {
    const s = makeSummary([4000, 3999, 2000, 1, 0]);
    expect(buildShareText(s, makeMeta())).toBe(
      'Ballpark Classic — 10,000 / 25,000\n🟩🟨🟨🟧🟥\nballpark.example.com',
    );
  });
  it('tags hard games', () => {
    expect(buildShareText(makeSummary([5000, 5000, 5000, 5000, 5000], true), makeMeta())).toContain(
      '🔥 HARD',
    );
  });
  it('emoji helper', () => {
    expect([4000, 2000, 1999, 1, 0].map(scoreEmoji).join('')).toBe('🟩🟨🟧🟧🟥');
  });
});
