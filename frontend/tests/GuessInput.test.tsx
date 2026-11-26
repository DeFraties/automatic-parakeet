import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { GuessInput } from '../src/components/GuessInput';
import { valueToSlider } from '../src/format';

function setup(currency = 'USD', min = 5_000, max = 50_000_000) {
  const onSubmit = vi.fn();
  render(<GuessInput currency={currency} min={min} max={max} onSubmit={onSubmit} />);
  const input = screen.getByLabelText('Your guess') as HTMLInputElement;
  const slider = screen.getByRole('slider') as HTMLInputElement;
  return { onSubmit, input, slider };
}

describe('GuessInput', () => {
  it('formats with thousands separators while typing', async () => {
    const { input } = setup();
    await userEvent.type(input, '1234567');
    expect(input.value).toBe('1,234,567');
  });

  it('moves the slider when typing', async () => {
    const { input, slider } = setup();
    await userEvent.type(input, '500000');
    expect(Number(slider.value)).toBe(Math.round(valueToSlider(500_000, 5_000, 50_000_000) * 1000));
    expect(Number(slider.value)).toBe(500);
  });

  it('updates the text when the slider moves', () => {
    const { input, slider } = setup();
    fireEvent.change(slider, { target: { value: '1000' } });
    expect(input.value).toBe('50,000,000');
    fireEvent.change(slider, { target: { value: '0' } });
    expect(input.value).toBe('5,000');
  });

  it('accepts k/m shorthand and submits with Enter', async () => {
    const { input, onSubmit } = setup();
    await userEvent.type(input, '1.2m{Enter}');
    expect(onSubmit).toHaveBeenCalledWith(1_200_000);
  });

  it('shows an error and does not submit invalid input', async () => {
    const { input, onSubmit } = setup();
    await userEvent.type(input, 'lots{Enter}');
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a number');
  });

  it('shows the currency symbol and range in the guess currency', () => {
    setup('JPY', 500_000, 10_000_000_000);
    expect(screen.getAllByText('¥').length).toBeGreaterThan(0);
    expect(screen.getByText('¥500,000')).toBeInTheDocument();
    expect(screen.getByText('¥10,000,000,000')).toBeInTheDocument();
  });
});
