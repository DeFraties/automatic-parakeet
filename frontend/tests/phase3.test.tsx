import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { SettingToggles } from '../src/components/SettingToggles';
import { buildShareText, isSelectable, loadSettings } from '../src/game';
import { About } from '../src/screens/About';
import { Leaderboards } from '../src/screens/Leaderboards';
import { makeMeta, makeReveal, makeRound, makeSummary } from './fixtures';

type Handler = (url: string, body: any) => unknown;

function stubFetch(routes: Handler) {
  const calls: { url: string; body: any }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(init.body as string) : undefined;
      calls.push({ url, body });
      const out = routes(url, body);
      if (out instanceof Response) return out;
      if (out === undefined) return new Response('{}', { status: 404 });
      return new Response(JSON.stringify(out), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = '';
});

const notPlayed = { date: '2026-11-27', number: 7, played: false, completed: false, game_id: null, score: null, difficulty: null };

describe('setting toggles', () => {
  it('keeps at least one setting on', async () => {
    const onChange = vi.fn();
    render(<SettingToggles value={['urban']} onChange={onChange} />);
    expect(screen.getByRole('button', { name: /Urban/ })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: /Rural/ }));
    expect(onChange).toHaveBeenCalledWith(['urban', 'rural']);
  });

  it('defaults to urban + rural and remembers the choice', () => {
    expect(loadSettings()).toEqual(['urban', 'rural']);
    window.localStorage.setItem('ballpark_settings', 'suburban');
    expect(loadSettings()).toEqual(['suburban']);
    window.localStorage.setItem('ballpark_settings', 'garbage');
    expect(loadSettings()).toEqual(['urban', 'rural']);
  });

  it('selectability depends on the chosen settings', () => {
    const meta = makeMeta(['FR']);
    const fr = meta.countries.find((c) => c.code === 'FR')!; // urban 40, suburban 10, rural 40
    expect(isSelectable(fr.eligible, ['urban', 'rural'], meta)).toBe(true);
    expect(isSelectable(fr.eligible, ['suburban'], meta)).toBe(false);
    expect(isSelectable(fr.eligible, ['urban', 'suburban'], meta)).toBe(true);
  });
});

describe('share text', () => {
  it('daily format with number and hard tag', () => {
    const meta = { ...makeMeta(), daily_number: 142 };
    const s = makeSummary([5000, 4000, 2500, 1000, 0], true, 'daily');
    expect(buildShareText(s, meta)).toBe(
      'Ballpark Daily #142 — 12,500 / 25,000 🔥 HARD\n🟩🟩🟨🟧🟥\nballpark.example.com',
    );
  });
});

describe('App: Daily Challenge', () => {
  it('starts the daily, plays it, and submits to the leaderboard', async () => {
    const scores = [5000, 4000, 2500, 1000, 0];
    const calls = stubFetch((url, body) => {
      if (url === '/api/meta') return { ...makeMeta(), daily_number: 7 };
      if (url === '/api/daily') return notPlayed;
      if (url === '/api/daily/start')
        return { game_id: 'd1', rounds_total: 5, mode: 'daily', where_scope: 'world', where_value: null,
                 settings: ['urban', 'rural'], difficulty: body.difficulty, round: makeRound(1) };
      const m = url.match(/\/api\/games\/d1\/rounds\/(\d)\/guess/);
      if (m) {
        const n = Number(m[1]);
        return { reveal: makeReveal(n, scores[n - 1]),
                 ...(n < 5 ? { next_round: makeRound(n + 1) } : { summary: makeSummary(scores, false, 'daily') }) };
      }
      if (url === '/api/leaderboards') return { rank: 3, nickname: body.nickname, score: 12500 };
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: /Daily Challenge/ }));
    expect(calls.find((c) => c.url === '/api/daily/start')!.body).toEqual({ difficulty: 'normal' });
    for (let n = 1; n <= 5; n++) {
      expect(await screen.findByText(`Round ${n}/5`)).toBeInTheDocument();
      expect(screen.getByText('Daily #7 · Normal')).toBeInTheDocument();
      await user.type(screen.getByLabelText('Your guess'), '400k{Enter}');
      await screen.findByLabelText(/points$/);
      await user.click(screen.getByRole('button', { name: n < 5 ? 'Next round' : 'See results' }));
    }
    expect(screen.queryByRole('button', { name: 'Play again' })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Submit to leaderboard'), 'Alice');
    await user.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText(/you're #3 on this board/)).toBeInTheDocument();
    expect(calls.find((c) => c.url === '/api/leaderboards')!.body).toEqual({ game_id: 'd1', nickname: 'Alice' });
  });

  it('shows done state and resumes an unfinished daily', async () => {
    stubFetch((url) => {
      if (url === '/api/meta') return makeMeta();
      if (url === '/api/daily') return { ...notPlayed, played: true, game_id: 'd9' };
      if (url === '/api/games/d9')
        return { game_id: 'd9', rounds_total: 5, mode: 'daily', where_scope: 'world', where_value: null,
                 settings: ['urban', 'rural'], difficulty: 'hard', score: 4000, round: makeRound(2, true) };
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: /Resume/ }));
    expect(await screen.findByText('Round 2/5')).toBeInTheDocument();
    expect(screen.getByLabelText('Score 4000')).toBeInTheDocument();
  });

  it('shows the completed daily score on Home', async () => {
    stubFetch((url) => {
      if (url === '/api/meta') return makeMeta();
      if (url === '/api/daily') return { ...notPlayed, played: true, completed: true, game_id: 'x', score: 18420 };
    });
    render(<App />);
    expect(await screen.findByText(/✓ Done today · 18,420 pts/)).toBeInTheDocument();
  });

  it('quota limit disables Classic but not the Daily', async () => {
    stubFetch((url) => {
      if (url === '/api/meta') return { ...makeMeta(), quota: { games_available: false, daily_available: true } };
      if (url === '/api/daily') return notPlayed;
    });
    render(<App />);
    expect(await screen.findByText(/hit today's limit/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Classic/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Daily Challenge/ })).toBeEnabled();
  });
});

describe('App: Classic with settings', () => {
  it('sends the chosen settings and reports image errors', async () => {
    const calls = stubFetch((url, body) => {
      if (url === '/api/meta') return makeMeta();
      if (url === '/api/daily') return notPlayed;
      if (url === '/api/games')
        return { game_id: 'g1', rounds_total: 5, mode: 'classic', where_scope: 'world', where_value: null,
                 settings: body.settings, difficulty: 'normal',
                 round: { ...makeRound(1), image_url: 'https://cdn.mly.test/1.jpg', image_source: 'mapillary', attribution: '© Mapillary contributors · CC BY-SA 4.0' } };
      if (url === '/api/telemetry/image-error') return new Response(null, { status: 204 });
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Suburban', pressed: false }));
    await user.click(screen.getByRole('button', { name: 'Rural', pressed: true }));
    expect(screen.getByText('Urban + Suburban · 5 rounds')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Classic/ }));
    expect(calls.find((c) => c.url === '/api/games')!.body.settings).toEqual(['urban', 'suburban']);
    expect(await screen.findByText('Classic · World · Urban + Suburban · Normal')).toBeInTheDocument();
    expect(screen.getByText('© Mapillary contributors · CC BY-SA 4.0')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Map showing the area around City1/ })).toBeInTheDocument();
    fireEvent.error(screen.getByRole('img', { name: /Photo of a property in City1/ }));
    expect(await screen.findByText('No photo for this one. Use the clues!')).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.find((c) => c.url === '/api/telemetry/image-error')!.body).toEqual({ game_id: 'g1', round_no: 1, source: 'mapillary' }),
    );
  });
});

describe('Leaderboards screen', () => {
  it('queries with exact filters and renders rows', async () => {
    const calls = stubFetch((url) => {
      if (url.startsWith('/api/leaderboards/'))
        return { mode: 'classic', difficulty: 'normal',
                 entries: [{ rank: 1, nickname: 'Alice', score: 21000, flag: '🇫🇷', date: '2026-11-27' }] };
    });
    const user = userEvent.setup();
    render(<Leaderboards meta={makeMeta()} initialDifficulty="normal" />);
    await waitFor(() => expect(calls[0].url).toMatch(/^\/api\/leaderboards\/daily\?difficulty=normal&date=\d{4}-\d\d-\d\d$/));
    await user.click(screen.getByRole('tab', { name: 'Classic' }));
    await user.click(screen.getByRole('radio', { name: /Hard/ }));
    await user.selectOptions(screen.getByLabelText('Where'), 'country:FR');
    await user.click(screen.getByRole('button', { name: /Suburban/ }));
    await waitFor(() => {
      const url = calls[calls.length - 1].url;
      expect(url).toContain('/api/leaderboards/classic?');
      const q = new URLSearchParams(url.split('?')[1]);
      expect(Object.fromEntries(q)).toEqual({ difficulty: 'hard', where_scope: 'country', where_value: 'FR',
                                              settings: 'rural,suburban,urban', period: 'all' });
    });
    const row = await screen.findByRole('row', { name: /Alice/ });
    expect(within(row).getByText('21,000')).toBeInTheDocument();
  });
});

describe('About page', () => {
  it('lists sources and sends a removal request', async () => {
    const calls = stubFetch((url) => (url === '/api/removals' ? { id: 1, status: 'pending' } : undefined));
    const meta = makeMeta();
    meta.sources = [{ key: 'uk', display_name: 'HM Land Registry Price Paid Data', homepage: 'https://gov.uk',
                      license_note: 'Contains HM Land Registry data © Crown copyright' }];
    const user = userEvent.setup();
    render(<About meta={meta} />);
    expect(screen.getByRole('link', { name: 'HM Land Registry Price Paid Data' })).toBeInTheDocument();
    expect(screen.getByText(/Crown copyright/)).toBeInTheDocument();
    expect(screen.getByText(/GHS-SMOD/, { selector: 'small' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Your email'), 'me@example.com');
    await user.type(screen.getByLabelText('Listing link or property ID'), 'https://example.com/x');
    await user.click(screen.getByRole('button', { name: 'Send removal request' }));
    expect(await screen.findByText(/within 72 hours/)).toBeInTheDocument();
    expect(calls[0].body).toEqual({ email: 'me@example.com', reference: 'https://example.com/x', message: '' });
  });
});

describe('PropertyImage', () => {
  it('shows a listing photo with its credit', async () => {
    const { PropertyImage } = await import('../src/components/PropertyImage');
    render(<PropertyImage url="https://photos.example/1.jpg" alt="Photo of a property in Leeds, United Kingdom"
             attribution="Photo: Example Homes" setting="suburban" propertyType="house" />);
    expect(screen.getByRole('img', { name: /Photo of a property in Leeds/ })).toHaveAttribute('src', 'https://photos.example/1.jpg');
    expect(screen.getByText('Photo: Example Homes')).toBeInTheDocument();
  });

  it('illustrated card is themed by setting and type', async () => {
    const { PropertyImage } = await import('../src/components/PropertyImage');
    const { container } = render(<PropertyImage url={null} alt="x" attribution={null} setting="rural" propertyType="house" />);
    expect(screen.getByRole('img', { name: 'Illustration of a rural house (no photo available)' })).toBeInTheDocument();
    expect(container.querySelector('.scene-rural')).not.toBeNull();
  });
});

describe('photo source hint', () => {
  it('tells the owner how to enable photos when none is configured', async () => {
    stubFetch((url) => {
      if (url === '/api/meta') return { ...makeMeta(), photo_sources: { mapillary: false, google: false } };
      if (url === '/api/daily') return notPlayed;
    });
    render(<App />);
    expect(await screen.findByText(/No photo source is set up/)).toBeInTheDocument();
  });

  it('stays quiet when Mapillary is configured', async () => {
    stubFetch((url) => {
      if (url === '/api/meta') return makeMeta();
      if (url === '/api/daily') return notPlayed;
    });
    render(<App />);
    await screen.findByRole('button', { name: /Daily Challenge/ });
    expect(screen.queryByText(/No photo source is set up/)).not.toBeInTheDocument();
  });
});
