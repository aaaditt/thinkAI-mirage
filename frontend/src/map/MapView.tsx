import type { FeatureCollection } from "geojson";
import {
  type ExpressionSpecification,
  type LineLayerSpecification,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";

import { fetchRoads, type Meta } from "../api";
import { COLORS, loadBaseStyle } from "./style";

setWorkerUrl(workerUrl);

const ROADS = "roads";
const RISK: ExpressionSpecification = ["coalesce", ["feature-state", "risk"], 0];

interface Props {
  meta: Meta;
  /** One digit per road segment: 0 clear, 1 caution, 2 impassable. */
  risk: string;
}

function addRoadLayer(map: MapLibreMap, roads: FeatureCollection): void {
  map.addSource(ROADS, {
    type: "geojson",
    data: roads,
    attribution: "Roads © OpenStreetMap contributors",
  });
  const layer: LineLayerSpecification = {
    id: ROADS,
    type: "line",
    source: ROADS,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": ["match", RISK, 1, COLORS.amber, 2, COLORS.impassable, COLORS.clearRoad],
      // Width also encodes risk, so colour is not the only signal.
      "line-width": [
        "interpolate", ["linear"], ["zoom"],
        9, ["match", RISK, 1, 1.2, 2, 2.0, 0.4],
        14, ["match", RISK, 1, 4.0, 2, 7.0, 1.4],
      ],
      "line-opacity": ["match", RISK, 0, 0.55, 1],
    },
  };
  map.addLayer(layer);
}

export function MapView({ meta, risk }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const applied = useRef("");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let map: MapLibreMap | undefined;
    Promise.all([loadBaseStyle(), fetchRoads()])
      .then(([base, roads]) => {
        if (cancelled || !container.current) return;
        const [west, south, east, north] = meta.bbox;
        map = new MapLibreMap({
          container: container.current,
          style: base.style,
          bounds: [west, south, east, north],
          fitBoundsOptions: { padding: 24 },
          attributionControl: { compact: true },
        });
        map.addControl(new NavigationControl({ showCompass: false }), "top-left");
        map.on("load", () => {
          if (cancelled || !map) return;
          addRoadLayer(map, roads);
          mapRef.current = map;
          setReady(true);
        });
      })
      .catch((reason: unknown) => setError(String(reason)));
    return () => {
      cancelled = true;
      mapRef.current = null;
      applied.current = ""; // a new map starts with no feature state
      setReady(false);
      map?.remove();
    };
  }, [meta]);

  // Restyle only the segments whose class changed since the last frame.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !risk) return;
    const previous = applied.current;
    for (let id = 0; id < risk.length; id += 1) {
      if (risk[id] !== previous[id]) {
        map.setFeatureState({ source: ROADS, id }, { risk: Number(risk[id]) });
      }
    }
    applied.current = risk;
  }, [ready, risk]);

  return (
    <>
      <div ref={container} className="map" data-ready={ready} />
      {error && <div className="map-error">Map failed to load: {error}</div>}
    </>
  );
}
