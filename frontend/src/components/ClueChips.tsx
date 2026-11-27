import type { Clues } from '../api';
import { formatArea } from '../format';

const TYPE_LABEL: Record<string, string> = {
  house: 'House',
  apartment: 'Apartment',
  townhouse: 'Townhouse',
  land: 'Land',
  other: 'Other',
};

const SETTING_ICON: Record<string, string> = { urban: '🏙️', rural: '🌾' };

const SETTING_LABEL: Record<string, string> = {
  urban: 'Urban',
  rural: 'Rural',
  unknown: 'Unknown setting',
};

export function ClueChips({ clues }: { clues: Clues }) {
  const place =
    clues.region && clues.region !== clues.city ? `${clues.city}, ${clues.region}` : clues.city;
  const chips: { key: string; icon: string; text: string }[] = [
    { key: 'country', icon: clues.flag, text: clues.country },
    { key: 'place', icon: '📍', text: place },
    { key: 'setting', icon: SETTING_ICON[clues.setting] ?? '📍', text: SETTING_LABEL[clues.setting] ?? clues.setting },
    { key: 'type', icon: '🏠', text: TYPE_LABEL[clues.property_type] ?? clues.property_type },
  ];
  if (clues.area_m2) chips.push({ key: 'area', icon: '📐', text: formatArea(clues.area_m2) });
  if (clues.bedrooms != null)
    chips.push({ key: 'beds', icon: '🛏️', text: `${clues.bedrooms} bed${clues.bedrooms === 1 ? '' : 's'}` });
  if (clues.bathrooms != null)
    chips.push({ key: 'baths', icon: '🛁', text: `${clues.bathrooms} bath${clues.bathrooms === 1 ? '' : 's'}` });
  if (clues.year_built) chips.push({ key: 'built', icon: '🧱', text: `Built ${clues.year_built}` });
  chips.push({
    key: 'price',
    icon: '🗓️',
    text: `${clues.price_type === 'sale_record' ? 'Sold' : 'Listed'} ${clues.price_year}`,
  });

  return (
    <ul className="chips" aria-label="Clues">
      {chips.map((c) => (
        <li key={c.key} className="chip">
          <span aria-hidden="true">{c.icon}</span> {c.text}
        </li>
      ))}
    </ul>
  );
}
