import type { FeatureCollection } from "geojson";
import {
  AttributionControl,
  type CircleLayerSpecification,
  type ExpressionSpecification,
  type GeoJSONSource,
  type ImageSource,
  type LineLayerSpecification,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";

import { type Action, fetchRoads, type Meta, type PayoutEvent, type SensorReading } from "../api";
import { COLORS, loadBaseStyle } from "./style";

setWorkerUrl(workerUrl);

const ROADS = "roads";
const RAIN = "rain";
const SENSORS = "sensors";
const RISK: ExpressionSpecification = ["coalesce", ["feature-state", "risk"], 0];
const SENSOR_RISK: ExpressionSpecification = ["get", "risk"];
/** Rain at or above this (mm in the hour) is drawn at full strength. */
export const RAIN_FULL_MM = 20;
const RAIN_RGB = [60, 207, 224]; // the palette cyan
/** Same breakpoint as the small-screen block in styles.css. */
const SMALL_SCREEN = "(max-width: 1500px), (max-height: 860px)";

/** Keeps the fitted city clear of the side panels, the top bar and the timeline. */
function viewPadding(): { top: number; bottom: number; left: number; right: number } {
  return window.matchMedia(SMALL_SCREEN).matches
    ? { top: 64, bottom: 112, left: 288, right: 360 }
    : { top: 76, bottom: 132, left: 316, right: 392 };
}

interface Props {
  meta: Meta;
  /** One digit per road segment: 0 clear, 1 caution, 2 impassable. */
  risk: string;
  /** Rain (mm) per block, meta.rain_rows x meta.rain_cols, row 0 = south. */
  rain: number[];
  sensors: SensorReading[];
  actions: Action[];
  payouts: PayoutEvent[];
  hour: number;
}

/** Approved closures and pumps that are in force at `hour`. Proposals are never drawn. */
function activeOnMap(actions: Action[], hour: number): Action[] {
  return actions.filter(
    (action) =>
      action.status === "approved" &&
      (action.type === "close_underpass" || action.type === "stage_pump") &&
      action.start_hour <= hour &&
      (action.end_hour === null || hour < action.end_hour),
  );
}

function markerElement(action: Action): HTMLElement {
  const element = document.createElement("div");
  const closure = action.type === "close_underpass";
  element.className = closure ? "marker closure" : "marker pump";
  element.title = `${closure ? "Closed" : "Pump staged"}: ${action.label}`;
  if (closure) {
    element.textContent = "CLOSED";
  } else {
    // The diamond is drawn in CSS; a text label keeps it readable without colour.
    element.innerHTML = '<span class="diamond"></span><span class="marker-text">PUMP</span>';
  }
  return element;
}

function payoutPin(business: string, amountAed: number): HTMLElement {
  const element = document.createElement("div");
  // MapLibre positions this root element itself, so the pin is drawn by a child.
  element.className = "marker";
  element.title = `Payout: ${business}, AED ${amountAed.toLocaleString("en-US")}`;
  const pin = document.createElement("span");
  pin.className = "payout-pin";
  pin.textContent = "AED";
  element.append(pin);
  return element;
}

/** One pixel per rain block: cyan, more opaque where more rain fell. */
function rainImage(rain: number[], rows: number, cols: number): string {
  const canvas = document.createElement("canvas");
  canvas.width = cols;
  canvas.height = rows;
  const context = canvas.getContext("2d");
  if (!context) return canvas.toDataURL();
  const image = context.createImageData(cols, rows);
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const mm = rain[row * cols + col] ?? 0;
      const at = ((rows - 1 - row) * cols + col) * 4; // grid row 0 is south, canvas row 0 is north
      image.data.set(RAIN_RGB, at);
      image.data[at + 3] = Math.round(255 * Math.min(1, mm / RAIN_FULL_MM));
    }
  }
  context.putImageData(image, 0, 0);
  return canvas.toDataURL();
}

function sensorPoints(sensors: SensorReading[], meta: Meta): FeatureCollection {
  const { caution_cm, impassable_cm } = meta.thresholds;
  return {
    type: "FeatureCollection",
    features: sensors.map((sensor) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [sensor.lon, sensor.lat] },
      properties: {
        id: sensor.id,
        depth_cm: sensor.depth_cm,
        risk: Number(sensor.depth_cm >= caution_cm) + Number(sensor.depth_cm > impassable_cm),
      },
    })),
  };
}

function addRainLayer(map: MapLibreMap, meta: Meta): void {
  const [west, south, east, north] = meta.bbox;
  map.addSource(RAIN, {
    type: "image",
    url: rainImage([], meta.rain_rows, meta.rain_cols),
    coordinates: [[west, north], [east, north], [east, south], [west, south]],
  });
  // Linear resampling blurs the blocks into a soft field.
  map.addLayer({
    id: RAIN,
    type: "raster",
    source: RAIN,
    paint: { "raster-opacity": 0.4, "raster-resampling": "linear", "raster-fade-duration": 0 },
  });
}

function addRoadLayer(map: MapLibreMap, roads: FeatureCollection): void {
  map.addSource(ROADS, {
    type: "geojson",
    data: roads,
    attribution: "Roads © OpenStreetMap contributors · Weather data by Open-Meteo.com",
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

/** Simulated sensors: a ring that fills and grows with the measured depth class. */
function addSensorLayer(map: MapLibreMap): void {
  map.addSource(SENSORS, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  const layer: CircleLayerSpecification = {
    id: SENSORS,
    type: "circle",
    source: SENSORS,
    paint: {
      "circle-radius": ["match", SENSOR_RISK, 1, 5, 2, 7, 3],
      "circle-color": [
        "match", SENSOR_RISK, 1, COLORS.amber, 2, COLORS.impassable, COLORS.background,
      ],
      "circle-stroke-color": COLORS.sand,
      "circle-stroke-width": 1.5,
    },
  };
  map.addLayer(layer);

  const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 10 });
  map.on("mousemove", SENSORS, (event) => {
    const feature = event.features?.[0];
    if (!feature || feature.geometry.type !== "Point") return;
    const { id, depth_cm } = feature.properties as { id: string; depth_cm: number };
    map.getCanvas().style.cursor = "help";
    popup
      .setLngLat(feature.geometry.coordinates as [number, number])
      .setText(`Simulated sensor ${id}: ${Math.round(depth_cm)} cm`)
      .addTo(map);
  });
  map.on("mouseleave", SENSORS, () => {
    map.getCanvas().style.cursor = "";
    popup.remove();
  });
}

export function MapView({ meta, risk, rain, sensors, actions, payouts, hour }: Props) {
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
          fitBoundsOptions: { padding: viewPadding() },
          attributionControl: false,
        });
        map.addControl(new NavigationControl({ showCompass: false }), "top-left");
        map.addControl(new AttributionControl({ compact: true }), "bottom-left");
        // Refit when the window changes size, e.g. going full screen on the projector.
        map.on("resize", () => {
          map?.fitBounds([west, south, east, north], { padding: viewPadding(), duration: 0 });
        });
        map.on("load", () => {
          if (cancelled || !map) return;
          addRainLayer(map, meta);
          addRoadLayer(map, roads);
          addSensorLayer(map);
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

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.getSource<ImageSource>(RAIN)?.updateImage({
      url: rainImage(rain, meta.rain_rows, meta.rain_cols),
    });
  }, [ready, rain, meta]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.getSource<GeoJSONSource>(SENSORS)?.setData(sensorPoints(sensors, meta));
  }, [ready, sensors, meta]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const markers = activeOnMap(actions, hour).map((action) =>
      new Marker({
        element: markerElement(action),
        // Offset so a pump and a closure at the same underpass do not overlap.
        offset: action.type === "stage_pump" ? [0, 16] : [0, -12],
      })
        .setLngLat([action.lon, action.lat])
        .addTo(map),
    );
    return () => markers.forEach((marker) => marker.remove());
  }, [ready, actions, hour]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const policies = new Map(meta.policies.map((policy) => [policy.id, policy]));
    const pins = payouts.flatMap((event) => {
      const policy = policies.get(event.policy_id);
      if (!policy) return [];
      return [
        new Marker({ element: payoutPin(policy.business, event.amount_aed), anchor: "bottom" })
          .setLngLat([policy.lon, policy.lat])
          .addTo(map),
      ];
    });
    return () => pins.forEach((pin) => pin.remove());
  }, [ready, payouts, meta]);

  return (
    <>
      <div ref={container} className="map" data-ready={ready} />
      {error && <div className="map-error">Map failed to load: {error}</div>}
    </>
  );
}
