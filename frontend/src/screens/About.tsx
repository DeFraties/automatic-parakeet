import { useState } from 'react';
import { api, ApiError, type Meta } from '../api';

function RemovalForm() {
  const [email, setEmail] = useState('');
  const [reference, setReference] = useState('');
  const [message, setMessage] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | 'sent'>('idle');
  const [error, setError] = useState<string | null>(null);

  if (state === 'sent') {
    return (
      <p className="card" role="status">
        Thanks — we've received your request and aim to act on it within 72 hours.
      </p>
    );
  }
  return (
    <form
      className="card removal-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setState('sending');
        setError(null);
        try {
          await api.requestRemoval({ email, reference, message });
          setState('sent');
        } catch (err) {
          setError(err instanceof ApiError && err.status !== 422 ? err.message
            : 'Please check the email address and the listing link or ID.');
          setState('idle');
        }
      }}
    >
      <label>
        Your email
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
      </label>
      <label>
        Listing link or property ID
        <input required minLength={3} maxLength={1000} value={reference} onChange={(e) => setReference(e.target.value)} />
      </label>
      <label>
        Message (optional)
        <textarea maxLength={2000} rows={3} value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>
      {error && (
        <p className="guess-error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="btn btn-primary" disabled={state === 'sending'}>
        Send removal request
      </button>
    </form>
  );
}

export function About({ meta }: { meta: Meta | null }) {
  return (
    <main className="about" id="main">
      <h1>How it works</h1>
      <div className="card prose">
        <p>
          Each round shows a real home, a few clues and roughly where it is. Guess the price. Scoring
          is proportional: being 2× too high costs the same as being 2× too low, so a $60k cabin is as
          hard as a $5M mansion. Within 3× of the real price you score points, up to 5,000 for a
          perfect guess.
        </p>
        <p>
          <strong>Hard mode</strong> asks for the guess in the local currency (yen, złoty, rand…) with
          no exchange-rate hint. <strong>Daily Challenge</strong> gives everyone the same five homes
          each day (UTC).
        </p>
      </div>

      <h2>Where the data comes from</h2>
      <div className="card prose">
        <p>
          Prices are either <strong>recorded sale prices</strong> from official open data or{' '}
          <strong>asking prices</strong> from public listings. The reveal screen says which. We keep
          facts only (price, size, rooms, rough location) and always link back to the source. We
          never store listing photos, descriptions or anyone's contact details.
        </p>
        <ul className="sources">
          {meta?.sources.map((s) => (
            <li key={s.key}>
              {s.homepage ? <a href={s.homepage} target="_blank" rel="noopener noreferrer">{s.display_name}</a> : s.display_name}
              {s.license_note && <small>{s.license_note}</small>}
            </li>
          ))}
          <li>
            Urban / suburban / rural classification: GHSL GHS-SMOD settlement model, European
            Commission, Joint Research Centre (JRC).
            <small>
              Schiavina M., Melchiorri M., Pesaresi M. (2023): GHS-SMOD R2023A — GHS settlement
              layers, application of the Degree of Urbanisation methodology. European Commission,
              JRC. Licensed under CC BY 4.0.
            </small>
          </li>
          <li>
            Street-level imagery: Google Street View, loaded directly from Google (© Google).
          </li>
          <li>
            Maps: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors.
            Locations without coordinates are geocoded with Nominatim and postcodes.io.
          </li>
        </ul>
      </div>

      <h2 id="removal">Request removal</h2>
      <p>
        If a home shown here is yours, or you represent a listing source, tell us and we'll remove it
        and make sure it never comes back.
      </p>
      <RemovalForm />
      <a href="#/" className="btn btn-ghost back-link">
        ← Home
      </a>
    </main>
  );
}
