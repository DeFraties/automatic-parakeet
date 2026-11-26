import { useEffect, useRef, useState } from 'react';
import type { Difficulty, RevealPayload } from '../api';
import { FT2_PER_M2, formatMoney, formatNumber } from '../format';

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

function useCountUp(target: number, ms = 900): number {
  const [value, setValue] = useState(() =>
    prefersReducedMotion() || typeof requestAnimationFrame !== 'function' ? target : 0,
  );
  const raf = useRef(0);
  useEffect(() => {
    if (prefersReducedMotion() || typeof requestAnimationFrame !== 'function') {
      setValue(target);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      setValue(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, ms]);
  return value;
}

const TONE: Record<string, string> = {
  'Bullseye!': 'tone-great',
  'In the ballpark': 'tone-good',
  'Close-ish': 'tone-ok',
  'Way off': 'tone-bad',
  'Different planet': 'tone-worst',
};

interface Props {
  reveal: RevealPayload;
  difficulty: Difficulty;
  roundNo: number;
  roundsTotal: number;
  place: string;
  onNext: () => void;
}

export function Reveal({ reveal: r, difficulty, roundNo, roundsTotal, place, onNext }: Props) {
  const shown = useCountUp(r.score);
  const hard = difficulty === 'hard';
  const isUsd = r.currency === 'USD';
  const guessText = hard
    ? formatMoney(r.guess_local, r.currency)
    : formatMoney(r.guess_usd, 'USD');
  const last = roundNo >= roundsTotal;
  const date = new Date(r.price_date + 'T00:00:00Z').toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });

  return (
    <main className="reveal" id="main">
      <p className="reveal-place">{place}</p>
      <section className="card reveal-card" aria-live="polite">
        <p className={`reveal-label ${TONE[r.label] ?? ''}`}>{r.label}</p>
        <div className="reveal-prices">
          <div>
            <span className="kicker">{r.price_type === 'sale_record' ? 'Sold for' : 'Listed at'}</span>
            <span className="price-big">{formatMoney(r.price_local, r.currency)}</span>
            {!isUsd && <span className="price-sub">≈ {formatMoney(r.price_usd, 'USD')}</span>}
          </div>
          <div>
            <span className="kicker">Your guess</span>
            <span className="price-big price-guess">{guessText}</span>
            <span className="price-sub">{formatNumber(r.pct_off)}% off</span>
          </div>
        </div>
        {r.fx_hint && <p className={hard ? 'fx-hint fx-hint-strong' : 'fx-hint'}>{r.fx_hint}</p>}
        <div className="score-meter" aria-hidden="true">
          <div className="score-fill" style={{ width: `${(shown / 5000) * 100}%` }} />
        </div>
        <p className="reveal-score" aria-label={`${r.score} points`}>
          +{formatNumber(shown)} <span>pts</span>
        </p>
      </section>

      <dl className="facts card">
        {r.price_per_m2_local != null && (
          <>
            <dt>Price per m²</dt>
            <dd>{formatMoney(r.price_per_m2_local, r.currency)}</dd>
            <dt>Price per ft²</dt>
            <dd>{formatMoney(r.price_per_m2_local / FT2_PER_M2, r.currency)}</dd>
          </>
        )}
        <dt>{r.price_type === 'sale_record' ? 'Sale date' : 'Listing date'}</dt>
        <dd>{date}</dd>
        <dt>Source</dt>
        <dd>{r.source_name}</dd>
      </dl>

      <div className="actions">
        {r.listing_url && (
          <a className="btn btn-ghost" href={r.listing_url} target="_blank" rel="noopener noreferrer">
            See original listing ↗
          </a>
        )}
        <button type="button" className="btn btn-primary" onClick={onNext} autoFocus>
          {last ? 'See results' : 'Next round'}
        </button>
      </div>
    </main>
  );
}
