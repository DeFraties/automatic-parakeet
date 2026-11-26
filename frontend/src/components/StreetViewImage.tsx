import { useState } from 'react';

interface Props {
  url: string | null;
  alt: string;
  attribution: string | null;
  onError?: () => void;
}

/** Street View image loaded live from Google (never proxied), or a placeholder card. */
export function StreetViewImage({ url, alt, attribution, onError }: Props) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return (
      <figure className="sv sv-placeholder" role="img" aria-label={`${alt} (no image available)`}>
        <div className="sv-placeholder-inner">
          <span className="sv-placeholder-icon" aria-hidden="true">
            🏘️
          </span>
          <span>No street image available</span>
          {!url && <small>Demo mode — Street View images arrive with real data.</small>}
        </div>
      </figure>
    );
  }
  return (
    <figure className="sv">
      <img
        src={url}
        alt={alt}
        width={640}
        height={640}
        referrerPolicy="strict-origin-when-cross-origin"
        onError={() => {
          setFailed(true);
          onError?.();
        }}
      />
      {attribution && <figcaption className="sv-attribution">{attribution}</figcaption>}
    </figure>
  );
}
