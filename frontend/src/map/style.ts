import type { StyleSpecification } from "maplibre-gl";

export const COLORS = {
  background: "#0B1220",
  cyan: "#3CCFE0",
  amber: "#F2A93B",
  sand: "#E6ECF3",
  clearRoad: "#3A5673",
  impassable: "#FF5C6C",
};

const BASEMAP_URL = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

/** Used when the basemap cannot be reached: our own road layer on a plain background. */
const PLAIN_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": COLORS.background } }],
};

/** Add ?offline to the address to skip the basemap, e.g. on unreliable venue Wi-Fi. */
const FORCE_OFFLINE = new URLSearchParams(window.location.search).has("offline");

export async function loadBaseStyle(): Promise<{ style: StyleSpecification; online: boolean }> {
  if (FORCE_OFFLINE) return { style: PLAIN_STYLE, online: false };
  try {
    const response = await fetch(BASEMAP_URL, { signal: AbortSignal.timeout(4000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return { style: (await response.json()) as StyleSpecification, online: true };
  } catch (error) {
    console.warn("Basemap unavailable, using the plain dark background.", error);
    return { style: PLAIN_STYLE, online: false };
  }
}
