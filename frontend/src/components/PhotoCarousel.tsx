import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { Photo } from '../api';

interface Props {
  photos: Photo[];
  credit: string;
  /** Called (debounced, once per batch) with listing positions that failed to load. */
  onFailed?: (positions: number[]) => void;
  /** Lets the Report link know which photo is on screen. */
  onCurrentChange?: (position: number | null) => void;
}

const REPORT_DELAY_MS = 1500;

/**
 * Listing photos, loaded straight from the listing site (hotlinked, Section 12.1). Shown exactly
 * as published: `object-fit: contain`, no filters, nothing drawn over the photo. Broken photos
 * are skipped; if all fail, a placeholder card is shown.
 */
export function PhotoCarousel({ photos, credit, onFailed, onCurrentChange }: Props) {
  const [failed, setFailed] = useState<Set<number>>(() => new Set());
  const [index, setIndex] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const track = useRef<HTMLDivElement>(null);
  const pending = useRef<number[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const visible = photos.filter((p) => !failed.has(p.position));
  const current = visible.length ? visible[Math.min(index, visible.length - 1)] : null;

  useEffect(() => {
    onCurrentChange?.(current ? current.position : null);
  }, [current, onCurrentChange]);

  useEffect(
    () => () => {
      // Flush any unreported failures when the round ends.
      if (timer.current) clearTimeout(timer.current);
      if (pending.current.length) onFailed?.(pending.current);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const markFailed = useCallback(
    (position: number) => {
      setFailed((prev) => new Set(prev).add(position));
      pending.current.push(position);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        const batch = pending.current;
        pending.current = [];
        if (batch.length) onFailed?.(batch);
      }, REPORT_DELAY_MS);
    },
    [onFailed],
  );

  const go = useCallback(
    (i: number) => {
      if (!visible.length) return;
      const next = (i + visible.length) % visible.length;
      setIndex(next);
      const el = track.current?.children[next] as HTMLElement | undefined;
      el?.scrollIntoView?.({ behavior: 'smooth', inline: 'start', block: 'nearest' });
    },
    [visible.length],
  );

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      go(index + 1);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      go(index - 1);
    } else if (e.key === 'Escape') {
      setFullscreen(false);
    }
  };

  const onScroll = () => {
    const el = track.current;
    if (!el || !el.clientWidth) return;
    const i = Math.round(el.scrollLeft / el.clientWidth);
    if (i !== index) setIndex(i);
  };

  if (!visible.length) {
    return (
      <figure className="carousel carousel-empty" role="img" aria-label="Photos unavailable">
        <div className="carousel-empty-inner">
          <span aria-hidden="true">🖼️</span>
          <span>Photos unavailable</span>
        </div>
        <figcaption className="photo-credit">{credit}</figcaption>
      </figure>
    );
  }

  const n = visible.length;
  const pos = Math.min(index, n - 1);

  return (
    <figure className="carousel" aria-roledescription="carousel" aria-label="Listing photos">
      <div
        className="carousel-frame"
        tabIndex={0}
        onKeyDown={onKey}
        aria-label={`Photo ${pos + 1} of ${n}. Use the left and right arrow keys to browse.`}
      >
        <div className="carousel-track" ref={track} onScroll={onScroll}>
          {visible.map((p, i) => (
            <div
              className="carousel-slide"
              key={p.position}
              aria-hidden={i !== pos}
              data-active={i === pos}
            >
              <img
                src={p.url}
                alt={p.alt}
                width={p.width ?? undefined}
                height={p.height ?? undefined}
                loading={i === 0 ? 'eager' : 'lazy'}
                decoding="async"
                draggable={false}
                onClick={() => setFullscreen(true)}
                onError={() => markFailed(p.position)}
              />
            </div>
          ))}
        </div>
      </div>
      {/* Controls live below the photo so nothing ever covers part of it (Section 4.2). */}
      <div className="carousel-controls">
        {n > 1 && (
          <button type="button" className="carousel-btn" onClick={() => go(pos - 1)}
                  aria-label="Previous photo">‹</button>
        )}
        {n > 1 && (
          <div className="carousel-dots" role="group" aria-label="Choose photo">
            {visible.map((p, i) => (
              <button
                key={p.position}
                type="button"
                className={i === pos ? 'is-active' : ''}
                aria-label={`Show photo ${i + 1} of ${n}`}
                aria-current={i === pos}
                onClick={() => go(i)}
              />
            ))}
          </div>
        )}
        {n > 1 && (
          <button type="button" className="carousel-btn" onClick={() => go(pos + 1)}
                  aria-label="Next photo">›</button>
        )}
        <button type="button" className="carousel-btn carousel-zoom" onClick={() => setFullscreen(true)}
                aria-label="View photo full screen">⤢</button>
      </div>
      <figcaption className="photo-credit">{credit}</figcaption>

      {fullscreen && current && (
        <div
          className="lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="Full-screen photo"
          tabIndex={-1}
          onKeyDown={onKey}
          ref={(el) => el?.focus()}
          onClick={(e) => e.target === e.currentTarget && setFullscreen(false)}
        >
          <button type="button" className="lightbox-close" onClick={() => setFullscreen(false)}
                  aria-label="Close full screen">✕</button>
          <img src={current.url} alt={current.alt} />
          <div className="lightbox-bar">
            {n > 1 && (
              <button type="button" className="carousel-btn" onClick={() => go(pos - 1)}
                      aria-label="Previous photo">‹</button>
            )}
            <p className="lightbox-credit">
              {pos + 1} / {n} · {credit}
            </p>
            {n > 1 && (
              <button type="button" className="carousel-btn" onClick={() => go(pos + 1)}
                      aria-label="Next photo">›</button>
            )}
          </div>
        </div>
      )}
    </figure>
  );
}
