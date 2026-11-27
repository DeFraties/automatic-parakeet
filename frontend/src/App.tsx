import { useCallback, useEffect, useState } from 'react';
import {
  api,
  ApiError,
  type CreateGameResponse,
  type DailyStatus,
  type Difficulty,
  type GameHeader,
  type Meta,
  type RevealPayload,
  type RoundPayload,
  type Setting,
  type SummaryPayload,
} from './api';
import {
  buildShareText,
  isSelectable,
  loadDifficulty,
  loadSettings,
  modeBadge,
  saveDifficulty,
  saveSettings,
  type Where,
} from './game';
import { About } from './screens/About';
import { Home } from './screens/Home';
import { Leaderboards } from './screens/Leaderboards';
import { Reveal } from './screens/Reveal';
import { Round } from './screens/Round';
import { Summary } from './screens/Summary';

interface GameState {
  header: GameHeader;
  score: number;
  round: RoundPayload | null;
  reveal: RevealPayload | null;
  nextRound: RoundPayload | null;
  summary: SummaryPayload | null;
  phase: 'round' | 'reveal' | 'summary';
}

type Route = 'home' | 'leaderboards' | 'about';

function routeFromHash(): Route {
  const h = typeof window !== 'undefined' ? window.location.hash : '';
  if (h.startsWith('#/leaderboards')) return 'leaderboards';
  if (h.startsWith('#/about')) return 'about';
  return 'home';
}

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return 'Something went wrong. Check your connection and try again.';
}

function fromCreate(g: CreateGameResponse): GameState {
  return { header: g, score: 0, round: g.round, reveal: null, nextRound: null, summary: null, phase: 'round' };
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [daily, setDaily] = useState<DailyStatus | null>(null);
  const [where, setWhere] = useState<Where>({ scope: 'world', value: null });
  const [difficulty, setDifficulty] = useState<Difficulty>(loadDifficulty);
  const [settings, setSettings] = useState<Setting[]>(loadSettings);
  const [game, setGame] = useState<GameState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshMeta = useCallback(() => {
    api.meta().then(setMeta, (e) => setMetaError(errorMessage(e)));
    api.daily().then(setDaily, () => setDaily(null));
  }, []);

  useEffect(refreshMeta, [refreshMeta]);

  useEffect(() => {
    const onHash = () => {
      setRoute(routeFromHash());
      setGame(null);
      setError(null);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    window.scrollTo?.(0, 0);
  }, [route, game?.phase, game?.round?.round_no]);

  const goHome = () => {
    setGame(null);
    setError(null);
    if (window.location.hash && window.location.hash !== '#/') window.location.hash = '#/';
    refreshMeta();
  };

  const changeDifficulty = (d: Difficulty) => {
    setDifficulty(d);
    saveDifficulty(d);
  };

  const changeSettings = (s: Setting[]) => {
    setSettings(s);
    saveSettings(s);
    // Drop a region/country choice that has too few homes for the new mix.
    if (meta && where.scope !== 'world') {
      const opt =
        where.scope === 'region'
          ? meta.regions.find((r) => r.key === where.value)
          : meta.countries.find((c) => c.code === where.value);
      if (!opt || !isSelectable(opt.eligible, s, meta)) setWhere({ scope: 'world', value: null });
    }
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const startClassic = () =>
    run(async () => {
      const g = await api.createGame({
        mode: 'classic',
        where_scope: where.scope,
        where_value: where.value,
        difficulty,
        settings,
      });
      setGame(fromCreate(g));
    });

  const openDaily = () =>
    run(async () => {
      if (daily?.completed) {
        window.location.hash = '#/leaderboards';
        return;
      }
      if (daily?.played && daily.game_id) {
        const g = await api.getGame(daily.game_id);
        setGame({
          header: g,
          score: g.score ?? 0,
          round: g.round ?? null,
          reveal: null,
          nextRound: null,
          summary: g.summary ?? null,
          phase: g.summary ? 'summary' : 'round',
        });
        return;
      }
      const g = await api.startDaily(difficulty);
      setGame(fromCreate(g));
      api.daily().then(setDaily, () => undefined);
    });

  const guess = (amount: number) =>
    run(async () => {
      if (!game?.round) return;
      const res = await api.guess(
        game.header.game_id,
        game.round.round_no,
        amount,
        game.round.guess_currency,
      );
      setGame({
        ...game,
        score: game.score + res.reveal.score,
        reveal: res.reveal,
        nextRound: res.next_round ?? null,
        summary: res.summary ?? null,
        phase: 'reveal',
      });
    });

  const next = () => {
    if (!game) return;
    if (game.nextRound) {
      setGame({ ...game, round: game.nextRound, nextRound: null, reveal: null, phase: 'round' });
    } else {
      setGame({ ...game, phase: 'summary' });
      if (game.header.mode === 'daily') api.daily().then(setDaily, () => undefined);
    }
  };

  let screen;
  if (game) {
    const h = game.header;
    const badge = modeBadge(
      h.mode,
      { scope: h.where_scope, value: h.where_value },
      h.settings,
      h.difficulty,
      meta,
    );
    if (game.phase === 'round' && game.round) {
      const roundNo = game.round.round_no;
      screen = (
        <Round
          round={game.round}
          score={game.score}
          badge={badge}
          submitting={busy}
          error={error}
          onGuess={guess}
          onImageError={() =>
            game.round?.image_source &&
            api.reportImageError(h.game_id, roundNo, game.round.image_source)
          }
          tileUrl={meta?.tile_url}
          tileAttribution={meta?.tile_attribution}
        />
      );
    } else if (game.phase === 'reveal' && game.reveal && game.round) {
      screen = (
        <Reveal
          reveal={game.reveal}
          difficulty={h.difficulty}
          roundNo={game.round.round_no}
          roundsTotal={h.rounds_total}
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
          onPlayAgain={h.mode === 'classic' ? startClassic : undefined}
          onHome={goHome}
          onSubmitScore={(nick) => api.submitScore(h.game_id, nick)}
        />
      );
    }
  } else if (route === 'leaderboards') {
    screen = <Leaderboards meta={meta} initialDifficulty={difficulty} />;
  } else if (route === 'about') {
    screen = <About meta={meta} />;
  } else {
    screen = (
      <Home
        meta={meta}
        where={where}
        difficulty={difficulty}
        settings={settings}
        daily={daily}
        onWhereChange={setWhere}
        onDifficultyChange={changeDifficulty}
        onSettingsChange={changeSettings}
        onStart={startClassic}
        onDaily={openDaily}
        starting={busy}
        error={error ?? metaError}
      />
    );
  }

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {(game || route !== 'home') && (
        <nav className="nav">
          <button type="button" className="nav-home" onClick={goHome}>
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
          Photos: listing sources, Mapillary (CC BY-SA) or Google · Maps © OpenStreetMap
          contributors ·{' '}
          <a href="#/about">About &amp; data</a> · <a href="#/about">Request removal</a>
        </p>
      </footer>
    </div>
  );
}
