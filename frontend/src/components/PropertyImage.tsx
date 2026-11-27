import { useEffect, useState } from 'react';

const TYPE_ICON: Record<string, string> = {
  house: '🏠',
  apartment: '🏢',
  townhouse: '🏘️',
  land: '🌳',
  other: '🏚️',
};
const SETTING_SCENE: Record<string, string> = { urban: '🏙️', suburban: '🌳', rural: '🌾' };
const TYPE_LABEL: Record<string, string> = {
  house: 'house',
  apartment: 'apartment',
  townhouse: 'townhouse',
  land: 'plot of land',
  other: 'property',
};

interface Props {
  url: string | null;
  alt: string;
  attribution: string | null;
  setting: string;
  propertyType: string;
  onError?: () => void;
}

/** The round's photo, loaded straight from its source (listing site, Google or Mapillary),
 * or an illustrated card when there's none. Photo bytes never pass through our server. */
export function PropertyImage({ url, alt, attribution, setting, propertyType, onError }: Props) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);

  if (!url || failed) {
    return (
      <figure
        className={`photo photo-card scene-${setting}`}
        role="img"
        aria-label={`Illustration of a ${setting} ${TYPE_LABEL[propertyType] ?? 'property'} (no photo available)`}
      >
        <div className="photo-card-inner" aria-hidden="true">
          <span className="photo-card-scene">{SETTING_SCENE[setting] ?? '🗺️'}</span>
          <span className="photo-card-icon">{TYPE_ICON[propertyType] ?? '🏠'}</span>
        </div>
        <figcaption className="photo-card-caption">No photo for this one. Use the clues!</figcaption>
      </figure>
    );
  }
  return (
    <figure className="photo">
      <img
        src={url}
        alt={alt}
        referrerPolicy="strict-origin-when-cross-origin"
        onError={() => {
          setFailed(true);
          onError?.();
        }}
      />
      {attribution && <figcaption className="photo-attribution">{attribution}</figcaption>}
    </figure>
  );
}
