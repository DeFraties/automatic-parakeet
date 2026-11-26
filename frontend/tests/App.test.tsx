import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { makeMeta, makeReveal, makeRound, makeSummary } from './fixtures';

type Call = { url: string; body: unknown };

function mockApi(hard = false) {
  const calls: Call[] = [];
  const scores = [5000, 4000, 2500, 1000, 0];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ url, body });
    const json = (data: unknown, status = 200) =>
      new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
    if (url === '/api/meta') return json(makeMeta());
    if (url === '/api/games') {
      return json(
        {
          game_id: 'g1',
          rounds_total: 5,
          mode: 'classic',
          where_scope: 'world',
          where_value: null,
          difficulty: body.difficulty,
          round: makeRound(1, hard),
        },
        201,
      );
    }
    const m = url.match(/\/api\/games\/g1\/rounds\/(\d)\/guess/);
    if (m) {
      const n = Number(m[1]);
      return json({
        reveal: makeReveal(n, scores[n - 1]),
        ...(n < 5 ? { next_round: makeRound(n + 1, hard) } : { summary: makeSummary(scores, hard) }),
      });
    }
    return json({ detail: { code: 'nope', message: 'not found' } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

describe('App game flow', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('plays a full Normal game with a mocked API', async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: /Classic/ }));
    expect(calls.find((c) => c.url === '/api/games')!.body).toEqual({
      mode: 'classic',
      where_scope: 'world',
      where_value: null,
      difficulty: 'normal',
    });

    for (let n = 1; n <= 5; n++) {
      expect(await screen.findByText(`Round ${n}/5`)).toBeInTheDocument();
      expect(screen.getByText('Classic · World · Normal')).toBeInTheDocument();
      await user.type(screen.getByLabelText('Your guess'), '400k{Enter}');
      expect(await screen.findByLabelText(/points$/)).toBeInTheDocument();
      if (n === 1) {
        expect(screen.getByRole('link', { name: /See original listing/ })).toHaveAttribute(
          'href',
          'https://example.com/demo/1',
        );
      }
      await user.click(screen.getByRole('button', { name: n < 5 ? 'Next round' : 'See results' }));
    }
    const guesses = calls.filter((c) => c.url.includes('/guess'));
    expect(guesses).toHaveLength(5);
    expect(guesses[0].body).toEqual({ amount: 400_000, currency: 'USD' });

    expect(await screen.findByText('12,500')).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(6); // header + 5 rounds
    await user.click(screen.getByRole('button', { name: 'Share result' }));
    expect(await screen.findByText('Copied to clipboard!')).toBeInTheDocument();
    await waitFor(async () =>
      expect(await navigator.clipboard.readText()).toBe(
        'Ballpark Classic — 12,500 / 25,000\n🟩🟩🟨🟧🟥\nballpark.example.com',
      ),
    );
  });

  it('Hard mode sends local-currency guesses and remembers the choice', async () => {
    const calls = mockApi(true);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('radio', { name: /Hard/ }));
    expect(window.localStorage.getItem('ballpark_difficulty')).toBe('hard');
    await user.click(screen.getByRole('button', { name: /Classic/ }));
    expect(await screen.findByText(/^Japanese yen \(¥\)$/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Your guess'), '60m{Enter}');
    await screen.findByLabelText(/points$/);
    expect(calls.find((c) => c.url.includes('/guess'))!.body).toEqual({
      amount: 60_000_000,
      currency: 'JPY',
    });
    expect(screen.getByText('1 USD ≈ 149 JPY')).toHaveClass('fx-hint-strong');
  });
});
