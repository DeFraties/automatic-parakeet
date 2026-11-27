import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { DailyStatus, Setting } from '../src/api';
import { Home } from '../src/screens/Home';
import { Round } from '../src/screens/Round';
import { makeMeta, makeRound } from './fixtures';

describe('Round screen', () => {
  it('Normal mode guesses in USD', () => {
    render(<Round round={makeRound(1)} score={0} badge="Classic · World · Normal" submitting={false} error={null} onGuess={vi.fn()} />);
    expect(screen.getByText('$5,000')).toBeInTheDocument();
    expect(screen.getByText('$50,000,000')).toBeInTheDocument();
  });

  it('Hard mode uses local currency and shows no USD anywhere', () => {
    const { container } = render(
      <Round round={makeRound(1, true)} score={0} badge="Classic · World · 🔥 Hard" submitting={false} error={null} onGuess={vi.fn()} />,
    );
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/\$|USD|dollar/i);
    expect(screen.getByText('¥500,000')).toBeInTheDocument();
    expect(screen.getByText(/^Japanese yen \(¥\)$/i)).toBeInTheDocument();
    // No exchange-rate hint during the round
    expect(text).not.toMatch(/≈/);
  });

  it('shows clue chips and accessible alt text', () => {
    render(<Round round={makeRound(2)} score={4000} badge="b" submitting={false} error={null} onGuess={vi.fn()} />);
    const clues = screen.getByRole('list', { name: 'Clues' });
    expect(within(clues).getByText(/55 m² \(592 ft²\)/)).toBeInTheDocument();
    expect(within(clues).getByText(/Sold 2025/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Listing photo 1 of 3, property in City2, Japan' })).toBeInTheDocument();
    expect(screen.getByText('Round 2/5')).toBeInTheDocument();
  });
});

describe('Home screen', () => {
  function renderHome(overrides: Partial<Parameters<typeof Home>[0]> = {}) {
    const props = {
      meta: makeMeta(['FR']),
      where: { scope: 'world' as const, value: null },
      difficulty: 'normal' as const,
      settings: ['urban', 'rural'] as Setting[],
      daily: null as DailyStatus | null,
      onWhereChange: vi.fn(),
      onDifficultyChange: vi.fn(),
      onSettingsChange: vi.fn(),
      onStart: vi.fn(),
      onDaily: vi.fn(),
      starting: false,
      error: null,
      ...overrides,
    };
    render(<Home {...props} />);
    return props;
  }

  it('groups the country dropdown by region and disables small pools', () => {
    renderHome();
    const select = screen.getByLabelText('Where') as HTMLSelectElement;
    const groups = select.querySelectorAll('optgroup');
    expect([...groups].map((g) => g.label)).toEqual([
      'North America', 'South America', 'Europe', 'Africa', 'Oceania', 'East Asia',
    ]);
    const europe = [...groups].find((g) => g.label === 'Europe')!;
    expect(europe.querySelectorAll('option')).toHaveLength(8); // "All of Europe" + 7 countries
    const fr = select.querySelector('option[value="country:FR"]') as HTMLOptionElement;
    const jp = select.querySelector('option[value="country:JP"]') as HTMLOptionElement;
    expect(fr.disabled).toBe(false);
    expect(jp.disabled).toBe(true);
    expect(jp.textContent).toContain('Coming soon');
    expect((select.querySelector('option[value="region:europe"]') as HTMLOptionElement).disabled).toBe(false);
  });

  it('defaults to Normal and toggles difficulty', async () => {
    const props = renderHome();
    const normal = screen.getByRole('radio', { name: /Normal \(USD\)/ });
    expect(normal).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('radio', { name: /Hard/ }));
    expect(props.onDifficultyChange).toHaveBeenCalledWith('hard');
  });

  it('starts a Classic game', async () => {
    const props = renderHome();
    await userEvent.click(screen.getByRole('button', { name: /Classic/ }));
    expect(props.onStart).toHaveBeenCalled();
  });
});
