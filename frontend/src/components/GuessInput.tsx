import { useId, useState } from 'react';
import { currencySymbol, formatMoney, formatNumber, formatTyped, parseAmount } from '../format';
import { LogSlider } from './LogSlider';

interface Props {
  currency: string;
  min: number;
  max: number;
  onSubmit: (amount: number) => void;
  disabled?: boolean;
  helper?: string;
}

export function GuessInput({ currency, min, max, onSubmit, disabled, helper }: Props) {
  const id = useId();
  const [text, setText] = useState('');
  const [touched, setTouched] = useState(false);
  const value = parseAmount(text);
  const symbol = currencySymbol(currency);
  const invalid = touched && text !== '' && value == null;

  return (
    <form
      className="guess"
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (value != null && !disabled) onSubmit(value);
      }}
    >
      <label htmlFor={id} className="guess-label">
        Your guess
      </label>
      {helper && (
        <p className="guess-helper" id={`${id}-helper`}>
          {helper}
        </p>
      )}
      <div className={`guess-field${invalid ? ' is-invalid' : ''}`}>
        <span className="guess-symbol" aria-hidden="true">
          {symbol}
        </span>
        <input
          id={id}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          placeholder="e.g. 450k or 1.2m"
          value={text}
          aria-invalid={invalid}
          aria-describedby={helper ? `${id}-helper` : undefined}
          onChange={(e) => setText(formatTyped(e.target.value))}
          onBlur={() => {
            setTouched(true);
            if (value != null) setText(formatNumber(value));
          }}
          disabled={disabled}
        />
      </div>
      {invalid && (
        <p className="guess-error" role="alert">
          Enter a number, like 450,000 or 450k.
        </p>
      )}
      <LogSlider
        min={min}
        max={max}
        value={value}
        label={`Guess slider, ${formatMoney(min, currency)} to ${formatMoney(max, currency)}`}
        valueText={value != null ? formatMoney(value, currency) : undefined}
        onChange={(v) => setText(formatNumber(v))}
      />
      <div className="slider-scale" aria-hidden="true">
        <span>{formatMoney(min, currency)}</span>
        <span>{formatMoney(max, currency)}</span>
      </div>
      <button type="submit" className="btn btn-primary btn-block" disabled={disabled}>
        Lock in guess
      </button>
    </form>
  );
}
