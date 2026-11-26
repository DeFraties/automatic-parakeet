import type { SummaryPayload } from '../api';
import { ShareButton } from '../components/ShareButton';
import { formatMoney, formatNumber, scoreEmoji } from '../format';

interface Props {
  summary: SummaryPayload;
  shareText: string;
  badge: string;
  onPlayAgain: () => void;
  onHome: () => void;
}

export function Summary({ summary, shareText, badge, onPlayAgain, onHome }: Props) {
  const hard = summary.difficulty === 'hard';
  const guessText = (r: SummaryPayload['rounds'][number]) =>
    r.guess_local == null
      ? '—'
      : hard
        ? formatMoney(r.guess_local, r.currency)
        : formatMoney(r.guess_usd ?? 0, 'USD');
  return (
    <main className="summary" id="main">
      <p className="badge">{badge}</p>
      <h1 className="summary-total">
        {formatNumber(summary.total_score)}
        <span> / {formatNumber(summary.max_score)}</span>
      </h1>
      <p className="summary-squares" aria-hidden="true">
        {summary.rounds.map((r) => scoreEmoji(r.score ?? 0)).join('')}
      </p>
      <div className="card table-wrap">
        <table className="summary-table">
          <caption className="sr-only">Round results</caption>
          <thead>
            <tr>
              <th scope="col" className="col-no">#</th>
              <th scope="col">City</th>
              <th scope="col">Actual</th>
              <th scope="col" className="col-guess">Guess</th>
              <th scope="col">Points</th>
            </tr>
          </thead>
          <tbody>
            {summary.rounds.map((r) => (
              <tr key={r.round_no}>
                <td className="col-no">{r.round_no}</td>
                <td>
                  <span aria-hidden="true">{r.flag}</span> {r.city}
                </td>
                <td className="num">
                  {hard ? formatMoney(r.price_local, r.currency) : formatMoney(r.price_usd, 'USD')}
                  <span className="guess-inline" aria-hidden="true">
                    guess {guessText(r)}
                  </span>
                </td>
                <td className="num col-guess">{guessText(r)}</td>
                <td className="num">{formatNumber(r.score ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ShareButton text={shareText} />
      <div className="actions">
        <button type="button" className="btn btn-ghost" onClick={onHome}>
          Home
        </button>
        <button type="button" className="btn btn-primary" onClick={onPlayAgain}>
          Play again
        </button>
      </div>
    </main>
  );
}
