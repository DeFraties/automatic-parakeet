import type { RoundPayload } from '../api';
import { ClueChips } from '../components/ClueChips';
import { GuessInput } from '../components/GuessInput';
import { MiniMap } from '../components/MiniMap';
import { StreetViewImage } from '../components/StreetViewImage';
import { currencyName, currencySymbol, formatNumber } from '../format';

interface Props {
  round: RoundPayload;
  score: number;
  badge: string;
  submitting: boolean;
  error: string | null;
  onGuess: (amount: number) => void;
  onImageError?: () => void;
  tileUrl?: string;
  tileAttribution?: string;
}

export function Round({
  round,
  score,
  badge,
  submitting,
  error,
  onGuess,
  onImageError,
  tileUrl,
  tileAttribution,
}: Props) {
  const { clues } = round;
  const hard = round.difficulty === 'hard';
  const cur = round.guess_currency;
  const helper = hard ? `${currencyName(cur)} (${currencySymbol(cur)})` : undefined;
  return (
    <main className="round" id="main">
      <div className="topbar">
        <span className="topbar-round">
          Round {round.round_no}/{round.rounds_total}
        </span>
        <span className="badge">{badge}</span>
        <span className="topbar-score" aria-label={`Score ${score}`}>
          {formatNumber(score)} pts
        </span>
      </div>
      <div className="round-layout">
        <StreetViewImage
          url={round.streetview_url}
          attribution={round.attribution}
          alt={`Street View of a property in ${clues.city}, ${clues.country}`}
          onError={onImageError}
        />
        <div className="round-side">
          <ClueChips clues={clues} />
          <div className="card">
            <GuessInput
              key={round.round_no}
              currency={cur}
              min={round.slider.min}
              max={round.slider.max}
              helper={helper}
              disabled={submitting}
              onSubmit={onGuess}
            />
            {error && (
              <p className="banner banner-error" role="alert">
                {error}
              </p>
            )}
          </div>
          {tileUrl && (
            <MiniMap
              lat={round.map.lat_approx}
              lng={round.map.lng_approx}
              tileUrl={tileUrl}
              attribution={tileAttribution ?? ''}
              label={`Map showing the area around ${clues.city}, ${clues.country}`}
            />
          )}
        </div>
      </div>
    </main>
  );
}
