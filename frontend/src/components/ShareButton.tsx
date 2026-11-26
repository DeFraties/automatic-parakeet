import { useState } from 'react';

function prefersNativeShare(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof navigator.share === 'function' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(pointer: coarse)').matches
  );
}

export function ShareButton({ text }: { text: string }) {
  const [status, setStatus] = useState<'idle' | 'copied' | 'failed'>('idle');

  async function share() {
    if (prefersNativeShare()) {
      try {
        await navigator.share({ text });
        return;
      } catch {
        /* cancelled or unsupported: fall back to copying */
      }
    }
    try {
      await navigator.clipboard.writeText(text);
      setStatus('copied');
    } catch {
      setStatus('failed');
    }
  }

  return (
    <div className="share">
      <button type="button" className="btn btn-primary" onClick={share}>
        Share result
      </button>
      <span role="status" className="share-status">
        {status === 'copied' && 'Copied to clipboard!'}
        {status === 'failed' && 'Could not copy — select the text below.'}
      </span>
      {status === 'failed' && <pre className="share-text">{text}</pre>}
    </div>
  );
}
