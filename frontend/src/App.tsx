import { useCallback, useEffect, useState } from 'react';
import {
  api,
  ApiError,
  type CreateGameResponse,
  type Difficulty,
  type Meta,
  type Mode,
  type RevealPayload,
  type RoundPayload,
  type SummaryPayload,
} from './api';
import { buildShareText, loadDifficulty, modeBadge, saveDifficulty, type Where } from './game';
import { Home } from './screens/Home';
import { Reveal } from './screens/Reveal';
import { Round } from './screens/Round';
import { Summary } from './screens/Summary';

interface GameState {
  id: string;
  mode: Mode;
  where: Where;
  difficulty: Difficulty;
  roundsTotal: number;
  score: number;
  round: RoundPayload;
  reveal: RevealPayload | null;
  nextRound: RoundPayload | null;
  summary: SummaryPayload | null;
  phase: 'round' | 'reveal' | 'summary';
}

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return 'Something went wrong. Check your connection and try again.';
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [where, setWhere] = useState<Where>({ scope: 'world', value: null });
  const [difficulty, setDifficulty] = useState<Difficulty>(loadDifficulty);
  const [game, setGame] = useState<GameState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.meta().then(setMeta, (e) => setMetaError(errorMessage(e)));
  }, []);

  useEffect(() => {
    window.scrollTo?.(0, 0);
  }, [game?.phase, game?.round.round_no]);

  const changeDifficulty = (d: Difficulty) => {
    setDifficulty(d);
    saveDifficulty(d);
  };

  const start = useCallback(
    async (mode: Mode) => {
      setBusy(true);
      setError(null);
      try {
        const g: CreateGameResponse = await api.createGame({
          mode,
          where_scope: where.scope,
          where_value: where.value,
          difficulty,
        });
        setGame({
          id: g.game_id,
          mode: g.mode,
          where: { scope: g.where_scope, value: g.where_value },
          difficulty: g.difficulty,
          roundsTotal: g.rounds_total,
          score: 0,
          round: g.round,
          reveal: null,
          nextRound: null,
          summary: null,
          phase: 'round',
        });
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setBusy(false);
      }
    },
    [where, difficulty],
  );

  const guess = async (amount: number) => {
    if (!game) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.guess(game.id, game.round.round_no, amount, game.round.guess_currency);
      setGame({
        ...game,
        score: game.score + res.reveal.score,
        reveal: res.reveal,
        nextRound: res.next_round ?? null,
        summary: res.summary ?? null,
        phase: 'reveal',
      });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const next = () => {
    if (!game) return;
    if (game.nextRound) {
      setGame({ ...game, round: game.nextRound, nextRound: null, reveal: null, phase: 'round' });
    } else {
      setGame({ ...game, phase: 'summary' });
    }
  };

  let screen;
  if (!game) {
    screen = (
      <Home
        meta={meta}
        where={where}
        difficulty={difficulty}
        onWhereChange={setWhere}
        onDifficultyChange={changeDifficulty}
        onStart={start}
        starting={busy}
        error={error ?? metaError}
      />
    );
  } else {
    const badge = modeBadge(game.mode, game.where, game.difficulty, meta);
    if (game.phase === 'round') {
      screen = (
        <Round
          round={game.round}
          score={game.score}
          badge={badge}
          submitting={busy}
          error={error}
          onGuess={guess}
        />
      );
    } else if (game.phase === 'reveal' && game.reveal) {
      screen = (
        <Reveal
          reveal={game.reveal}
          difficulty={game.difficulty}
          roundNo={game.round.round_no}
          roundsTotal={game.roundsTotal}
          place={`${game.round.clues.flag} ${game.round.clues.city}, ${game.round.clues.country}`}
          onNext={next}
        />
      );
    } else if (game.summary) {
      screen = (
        <Summary
          summary={game.summary}
          badge={badge}
          shareText={buildShareText(game.summary, meta)}
          onPlayAgain={() => start(game.mode)}
          onHome={() => {
            setGame(null);
            setError(null);
          }}
        />
      );
    }
  }

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {game && (
        <nav className="nav">
          <button type="button" className="nav-home" onClick={() => setGame(null)}>
            Ballpark<span aria-hidden="true">.</span>
          </button>
        </nav>
      )}
      {screen}
      <footer className="footer">
        <p>
          Data:{' '}
          {meta?.sources.length
            ? meta.sources.map((s) => s.display_name).join(' · ')
            : 'loading sources…'}
          . Prices may be asking prices or recorded sale prices.
        </p>
        <p>
          Street imagery © Google where shown. Want a property removed?{' '}
          <a
            href={`mailto:${meta?.contact_email ?? ''}?subject=${encodeURIComponent('Ballpark removal request')}`}
          >
            Request removal
          </a>
        </p>
      </footer>
    </div>
  );
}
