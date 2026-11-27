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
    expect(screen.queryByRole('button', { name: /Suburban/ })).not.toBeInTheDocument();
  });

  it('defaults to urban + rural and remembers the choice', () => {
    expect(loadSettings()).toEqual(['urban', 'rural']);
    window.localStorage.setItem('ballpark_settings', 'rural');
    expect(loadSettings()).toEqual(['rural']);
    window.localStorage.setItem('ballpark_settings', 'suburban'); // old v1 value
    expect(loadSettings()).toEqual(['urban', 'rural']);
  });

  it('selectability depends on the chosen settings', () => {
    const meta = makeMeta(['FR']);
    const fr = meta.countries.find((c) => c.code === 'FR')!; // urban 40, rural 15
    expect(isSelectable(fr.eligible, ['urban', 'rural'], meta)).toBe(true);
    expect(isSelectable(fr.eligible, ['rural'], meta)).toBe(false);
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

});

describe('App: Classic with settings', () => {
  it('sends the chosen settings, shows listing photos and reports broken ones', async () => {
    const calls = stubFetch((url, body) => {
      if (url === '/api/meta') return makeMeta();
      if (url === '/api/daily') return notPlayed;
      if (url === '/api/games')
        return { game_id: 'g1', rounds_total: 5, mode: 'classic', where_scope: 'world', where_value: null,
                 settings: body.settings, difficulty: 'normal', round: makeRound(1) };
      if (url === '/api/telemetry/image-error') return new Response(null, { status: 204 });
      if (url === '/api/reports') return { id: 1, status: 'open' };
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Rural', pressed: true }));
    expect(screen.getByText('Urban · 5 rounds')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Classic/ }));
    expect(calls.find((c) => c.url === '/api/games')!.body.settings).toEqual(['urban']);
    expect(await screen.findByText('Classic · World · Urban · Normal')).toBeInTheDocument();
    expect(screen.getByText('Photos: Example Listings')).toBeInTheDocument();
    const first = screen.getByRole('img', { name: 'Listing photo 1 of 3, property in City1, Japan' });
    expect(first).toHaveAttribute('src', 'https://img.test/r1/0.jpg');
    expect(first).not.toHaveAttribute('referrerpolicy');

    // Report the photo on screen
    await user.click(screen.getByRole('button', { name: 'Report photo' }));
    await user.click(screen.getByRole('button', { name: 'Send report' }));
    expect(await screen.findByText(/Thanks — reported/)).toBeInTheDocument();
    expect(calls.find((c) => c.url === '/api/reports')!.body).toEqual(
      { game_id: 'g1', round_no: 1, position: 0, reason: 'price_visible' });

    // Every photo fails -> placeholder + one batched telemetry report
    for (const img of document.querySelectorAll('.carousel-slide img')) fireEvent.error(img);
    expect(await screen.findByText('Photos unavailable')).toBeInTheDocument();
    expect(screen.getByText('Photos: Example Listings')).toBeInTheDocument(); // credit stays
    await waitFor(
      () => expect(calls.find((c) => c.url === '/api/telemetry/image-error')!.body)
        .toEqual({ game_id: 'g1', round_no: 1, positions: [0, 1, 2] }),
      { timeout: 3000 },
    );
  });

  it('hides the mini map when the listing has no coordinates', async () => {
    stubFetch((url, body) => {
      if (url === '/api/meta') return makeMeta();
      if (url === '/api/daily') return notPlayed;
      if (url === '/api/games')
        return { game_id: 'g1', rounds_total: 5, mode: 'classic', where_scope: 'world', where_value: null,
                 settings: body.settings, difficulty: 'normal', round: { ...makeRound(1), map: null } };
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: /Classic/ }));
    await screen.findByText('Round 1/5');
    expect(screen.queryByRole('img', { name: /Map showing/ })).not.toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: 'Rural', pressed: true }));
    await waitFor(() => {
      const url = calls[calls.length - 1].url;
      expect(url).toContain('/api/leaderboards/classic?');
      const q = new URLSearchParams(url.split('?')[1]);
      expect(Object.fromEntries(q)).toEqual({ difficulty: 'hard', where_scope: 'country', where_value: 'FR',
                                              settings: 'urban', period: 'all' });
    });
    const row = await screen.findByRole('row', { name: /Alice/ });
    expect(within(row).getByText('21,000')).toBeInTheDocument();
  });
});

describe('About page', () => {
  it('lists sources and sends a removal request', async () => {
    const calls = stubFetch((url) => (url === '/api/removals' ? { id: 1, status: 'pending' } : undefined));
    const meta = makeMeta();
    meta.sources = [{ key: 'ex', display_name: 'Example Listings', homepage: 'https://listings.test',
                      license_note: 'Listing data and photos © Example Listings', image_hosts: [] }];
    const user = userEvent.setup();
    render(<About meta={meta} />);
    expect(screen.getByRole('link', { name: 'Example Listings' })).toBeInTheDocument();
    expect(screen.getByText(/© Example Listings/)).toBeInTheDocument();
    expect(screen.getByText(/never copied to our servers/)).toBeInTheDocument();
    expect(screen.getByText(/GHS-SMOD/, { selector: 'small' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Your email'), 'me@example.com');
    await user.type(screen.getByLabelText('Listing link or property ID'), 'https://example.com/x');
    await user.click(screen.getByRole('button', { name: 'Send removal request' }));
    expect(await screen.findByRole('status')).toHaveTextContent(/within 72 hours/);
    expect(calls[0].body).toEqual({ email: 'me@example.com', reference: 'https://example.com/x', message: '' });
  });
});

describe('PhotoCarousel', () => {
  const photos = [0, 1, 2, 3].map((i) => ({
    position: i, url: `https://img.test/${i}.jpg`, width: 1600, height: 1067,
    kind: (i === 3 ? 'floorplan' : 'photo') as 'photo' | 'floorplan',
    alt: `${i === 3 ? 'Floor plan' : 'Listing photo'} ${i + 1} of 4, property in Lyon, France`,
  }));

  async function load() {
    const { PhotoCarousel } = await import('../src/components/PhotoCarousel');
    return PhotoCarousel;
  }

  it('shows photos in order, lazy after the first, with the credit always visible', async () => {
    const PhotoCarousel = await load();
    render(<PhotoCarousel photos={photos} credit="Photos: Example Listings" />);
    const imgs = document.querySelectorAll('.carousel-slide img');
    expect([...imgs].map((i) => i.getAttribute('src'))).toEqual(photos.map((p) => p.url));
    expect(imgs[0]).toHaveAttribute('loading', 'eager');
    expect(imgs[1]).toHaveAttribute('loading', 'lazy');
    expect(screen.getByText('Photos: Example Listings')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Show photo/ })).toHaveLength(4);
  });

  it('keyboard and arrow navigation', async () => {
    const PhotoCarousel = await load();
    const onCurrent = vi.fn();
    render(<PhotoCarousel photos={photos} credit="c" onCurrentChange={onCurrent} />);
    const frame = screen.getByLabelText(/Photo 1 of 4/);
    fireEvent.keyDown(frame, { key: 'ArrowRight' });
    expect(screen.getByLabelText(/Photo 2 of 4/)).toBeInTheDocument();
    fireEvent.keyDown(frame, { key: 'ArrowLeft' });
    fireEvent.keyDown(frame, { key: 'ArrowLeft' });
    expect(screen.getByLabelText(/Photo 4 of 4/)).toBeInTheDocument(); // wraps
    await userEvent.click(screen.getByRole('button', { name: 'Next photo' }));
    expect(screen.getByLabelText(/Photo 1 of 4/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Show photo 3 of 4' }));
    expect(onCurrent).toHaveBeenLastCalledWith(2);
  });

  it('skips broken photos silently', async () => {
    const PhotoCarousel = await load();
    render(<PhotoCarousel photos={photos} credit="c" />);
    fireEvent.error(document.querySelectorAll('.carousel-slide img')[1]);
    expect(document.querySelectorAll('.carousel-slide img')).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: /Show photo/ })).toHaveLength(3);
    expect(screen.queryByText('Photos unavailable')).not.toBeInTheDocument();
  });

  it('opens full screen and closes with Escape', async () => {
    const PhotoCarousel = await load();
    render(<PhotoCarousel photos={photos} credit="Photos: X" />);
    await userEvent.click(screen.getByRole('button', { name: 'View photo full screen' }));
    const dialog = screen.getByRole('dialog', { name: 'Full-screen photo' });
    expect(within(dialog).getByRole('img')).toHaveAttribute('src', 'https://img.test/0.jpg');
    expect(within(dialog).getByText('1 / 4 · Photos: X')).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
