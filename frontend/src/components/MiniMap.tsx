import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { useEffect, useRef } from 'react';

interface Props {
  lat: number;
  lng: number;
  tileUrl: string;
  attribution: string;
  label: string;
}

/** City-level OpenStreetMap mini map (never Google tiles). The pin uses coordinates already
 * rounded server-side to ~1 km, so it doesn't pinpoint the house. */
export function MiniMap({ lat, lng, tileUrl, attribution, label }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);

  useEffect(() => {
    if (!el.current || map.current) return;
    map.current = L.map(el.current, {
      zoomControl: false,
      attributionControl: true,
      scrollWheelZoom: false,
      keyboard: false,
    }).setView([lat, lng], 10);
    L.tileLayer(tileUrl, { attribution, maxZoom: 12, minZoom: 3 }).addTo(map.current);
    L.control.zoom({ position: 'bottomright' }).addTo(map.current);
    marker.current = L.circleMarker([lat, lng], {
      radius: 9,
      color: '#fff',
      weight: 3,
      fillColor: '#c2410c',
      fillOpacity: 1,
    }).addTo(map.current);
    return () => {
      map.current?.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    map.current?.setView([lat, lng], 10);
    marker.current?.setLatLng([lat, lng]);
  }, [lat, lng]);

  return <div ref={el} className="minimap" role="img" aria-label={label} />;
}
