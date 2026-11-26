import { roundSignificant, sliderToValue, valueToSlider } from '../format';

const STEPS = 1000;

interface Props {
  min: number;
  max: number;
  value: number | null;
  onChange: (value: number) => void;
  label: string;
  valueText?: string;
}

/** Log-scale range input: position t in [0,1] maps to min × (max/min)^t. */
export function LogSlider({ min, max, value, onChange, label, valueText }: Props) {
  const pos = value == null ? STEPS / 2 : Math.round(valueToSlider(value, min, max) * STEPS);
  return (
    <input
      type="range"
      className="log-slider"
      min={0}
      max={STEPS}
      step={1}
      value={pos}
      aria-label={label}
      aria-valuetext={valueText}
      onChange={(e) => {
        const t = Number(e.target.value) / STEPS;
        onChange(Math.min(max, Math.max(min, roundSignificant(sliderToValue(t, min, max)))));
      }}
    />
  );
}
