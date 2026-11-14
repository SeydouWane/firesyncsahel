// MapLibre map with hexagon activity layer, admin units, selected zone,
// polygon drawing and a deck.gl detections layer (loaded on demand).
import { cssVar, fmt, fmtInt, esc, showTip, hideTip, PCT } from "./ui.js";
import { t } from "./i18n.js";

const STYLE = {
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
};
export const isDark = () => {
  const th = document.documentElement.dataset.theme;
  if (th) return th === "dark";
  return matchMedia("(prefers-color-scheme: dark)").matches;
};

let deckPromise = null;
function loadDeck() {
  if (window.deck) return Promise.resolve(window.deck);
  if (!deckPromise) {
    deckPromise = new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = "https://unpkg.com/deck.gl@9.0.38/dist.min.js";
      s.onload = () => res(window.deck);
      s.onerror = rej;
      document.head.appendChild(s);
    });
  }
  return deckPromise;
}

export function heatRamp() { return [0, 1, 2, 3, 4, 5].map((i) => cssVar(`--heat-${i}`)); }

export class FireMap {
  constructor(container, { center = [-14.4, 14.4], zoom = 5.6 } = {}) {
    this.el = container;
    this.map = new maplibregl.Map({ container, style: STYLE[isDark() ? "dark" : "light"], center, zoom,
      attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false });
    this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    this.map.touchZoomRotate.disableRotation();
    this.ready = new Promise((r) => this.map.on("load", r));
    this.layers = {};
    this.handlers = {};
    this.drawing = null;
  }

  async _src(id, data) {
    await this.ready;
    const s = this.map.getSource(id);
    if (s) s.setData(data); else this.map.addSource(id, { type: "geojson", data });
  }

  async setHex(geojson, metric) {
    await this._src("hex", geojson);
    const vals = geojson.features.map((f) => f.properties.v).filter((v) => v != null).sort((a, b) => a - b);
    const q = (p) => vals.length ? vals[Math.min(vals.length - 1, Math.floor(p * vals.length))] : 1;
    let color, stops;
    if (metric === "trend") {
      const m = Math.max(Math.abs(q(0.05)), Math.abs(q(0.95)), 1);
      stops = [-m, -m / 2, 0, m / 2, m];
      color = ["interpolate", ["linear"], ["get", "v"], stops[0], "#2a78d6", stops[1], "#86b6ef", 0, isDark() ? "#383835" : "#f0efec", stops[3], "#ec835a", stops[4], "#d03b3b"];
    } else if (metric === "anomaly") {
      stops = [0.25, 0.5, 1, 2, 4];
      color = ["interpolate", ["linear"], ["ln", ["max", ["get", "v"], 0.05]], Math.log(0.25), "#2a78d6", Math.log(0.5), "#86b6ef", 0, isDark() ? "#383835" : "#f0efec", Math.log(2), "#ec835a", Math.log(4), "#d03b3b"];
    } else {
      const r = heatRamp();
      stops = [q(0.05), q(0.25), q(0.5), q(0.75), q(0.9), q(0.99)];
      for (let i = 1; i < stops.length; i++) if (stops[i] <= stops[i - 1]) stops[i] = stops[i - 1] + 1e-6;
      color = ["interpolate", ["linear"], ["get", "v"], ...stops.flatMap((s, i) => [s, r[i]])];
    }
    if (!this.map.getLayer("hex-fill")) {
      this.map.addLayer({ id: "hex-fill", type: "fill", source: "hex", paint: { "fill-color": color, "fill-opacity": 0.72 } }, this._firstSymbol());
      this.map.addLayer({ id: "hex-line", type: "line", source: "hex", paint: { "line-color": isDark() ? "#0f0d0c" : "#ffffff", "line-width": 0.4, "line-opacity": 0.6 } }, this._firstSymbol());
      this.map.on("mousemove", "hex-fill", (e) => {
        const p = e.features[0]?.properties; if (!p) return;
        const unit = metric === "trend" ? "%/10 ans" : metric === "anomaly" ? "×" : t("ex.unit_density");
        showTip(e.originalEvent, `<b>${fmt(p.v, metric === "anomaly" ? 2 : 1)}</b> <span class="k">${esc(this._unit || unit)}</span>`);
      });
      this.map.on("mouseleave", "hex-fill", hideTip);
    } else {
      this.map.setPaintProperty("hex-fill", "fill-color", color);
    }
    this._unit = metric === "trend" ? t("ex.unit_trend") : metric === "anomaly" ? t("ex.unit_anom") : t("ex.unit_density");
    return { stops, metric };
  }

  async showHex(on) {
    await this.ready;
    for (const id of ["hex-fill", "hex-line"]) if (this.map.getLayer(id)) this.map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  }

  _firstSymbol() {
    const l = this.map.getStyle().layers.find((x) => x.type === "symbol");
    return l ? l.id : undefined;
  }

  async setAdmin(geojson, onClick) {
    await this._src("admin", geojson);
    if (!this.map.getLayer("admin-fill")) {
      this.map.addLayer({ id: "admin-fill", type: "fill", source: "admin", paint: { "fill-color": "#000", "fill-opacity": 0 } });
      this.map.addLayer({ id: "admin-line", type: "line", source: "admin", paint: { "line-color": isDark() ? "#cbc3b8" : "#57514a", "line-width": 0.7, "line-opacity": 0.55 } });
      this.map.on("click", "admin-fill", (e) => { if (!this.drawing && this.handlers.admin) this.handlers.admin(e.features[0]); });
      this.map.on("mouseenter", "admin-fill", () => { if (!this.drawing) this.map.getCanvas().style.cursor = "pointer"; });
      this.map.on("mouseleave", "admin-fill", () => { if (!this.drawing) this.map.getCanvas().style.cursor = ""; });
    }
    this.handlers.admin = onClick;
  }

  async setZone(geometry, fit = true) {
    const fc = { type: "FeatureCollection", features: geometry ? [{ type: "Feature", properties: {}, geometry }] : [] };
    await this._src("zone", fc);
    if (!this.map.getLayer("zone-fill")) {
      this.map.addLayer({ id: "zone-fill", type: "fill", source: "zone", paint: { "fill-color": cssVar("--brand"), "fill-opacity": 0.12 } });
      this.map.addLayer({ id: "zone-line", type: "line", source: "zone", paint: { "line-color": cssVar("--brand"), "line-width": 2.4 } });
    }
    if (geometry && fit) this.fit(geometry);
  }

  fit(geometry) {
    const b = new maplibregl.LngLatBounds();
    const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
    walk(geometry.coordinates);
    if (!b.isEmpty()) this.map.fitBounds(b, { padding: 40, maxZoom: 10, duration: 600 });
  }

  // -------- polygon drawing
  startDraw(onDone) {
    this.stopDraw();
    const pts = [];
    const m = this.map;
    m.doubleClickZoom.disable();
    m.getCanvas().style.cursor = "crosshair";
    const render = () => {
      const feats = [];
      if (pts.length > 1) feats.push({ type: "Feature", geometry: { type: "LineString", coordinates: pts.length > 2 ? [...pts, pts[0]] : pts } });
      pts.forEach((p) => feats.push({ type: "Feature", geometry: { type: "Point", coordinates: p } }));
      this._src("draw", { type: "FeatureCollection", features: feats }).then(() => {
        if (!m.getLayer("draw-line")) {
          m.addLayer({ id: "draw-line", type: "line", source: "draw", paint: { "line-color": cssVar("--brand"), "line-width": 2 } });
          m.addLayer({ id: "draw-pt", type: "circle", source: "draw", filter: ["==", "$type", "Point"],
            paint: { "circle-radius": 5, "circle-color": "#fff", "circle-stroke-color": cssVar("--brand"), "circle-stroke-width": 2 } });
        }
      });
    };
    const click = (e) => { pts.push([e.lngLat.lng, e.lngLat.lat]); render(); };
    const dbl = (e) => { e.preventDefault(); finish(); };
    const key = (e) => { if (e.key === "Escape") this.stopDraw(); if (e.key === "Enter") finish(); };
    const finish = () => {
      // the double click also fired one extra click: drop duplicated last vertex
      while (pts.length > 3) {
        const a = pts[pts.length - 1], b = pts[pts.length - 2];
        if (Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9) pts.pop(); else break;
      }
      if (pts.length < 3) return;
      const ring = [...pts, pts[0]];
      this.stopDraw();
      onDone({ type: "Polygon", coordinates: [ring] });
    };
    m.on("click", click); m.on("dblclick", dbl); document.addEventListener("keydown", key);
    this.drawing = { pts, finish, undo: () => { pts.pop(); render(); }, off: () => {
      m.off("click", click); m.off("dblclick", dbl); document.removeEventListener("keydown", key);
    } };
    render();
    return this.drawing;
  }
  stopDraw() {
    if (!this.drawing) return;
    this.drawing.off();
    this.drawing = null;
    this.map.getCanvas().style.cursor = "";
    setTimeout(() => this.map.doubleClickZoom.enable(), 300);
    this._src("draw", { type: "FeatureCollection", features: [] });
  }

  // -------- detections (deck.gl)
  async setPoints(pts) {
    const deck = await loadDeck();
    const colors = [[235, 104, 52], [237, 161, 0], [42, 120, 214], [27, 175, 122], [98, 80, 214]];
    const data = { length: pts.n, attributes: {} };
    const pos = new Float32Array(pts.n * 2), col = new Uint8Array(pts.n * 4);
    for (let i = 0; i < pts.n; i++) {
      pos[2 * i] = pts.lon[i]; pos[2 * i + 1] = pts.lat[i];
      const c = colors[pts.s[i]] || [137, 135, 129];
      col.set([...c, 190], 4 * i);
    }
    data.attributes.getPosition = { value: pos, size: 2 };
    data.attributes.getFillColor = { value: col, size: 4 };
    const layer = new deck.ScatterplotLayer({ id: "det", data, radiusUnits: "pixels", getRadius: 2.2, radiusMinPixels: 1.4, stroked: false });
    if (!this.overlay) { this.overlay = new deck.MapboxOverlay({ interleaved: false, layers: [layer] }); this.map.addControl(this.overlay); }
    else this.overlay.setProps({ layers: [layer] });
  }
  clearPoints() { if (this.overlay) this.overlay.setProps({ layers: [] }); }

  remove() { this.stopDraw(); hideTip(); this.map.remove(); }
}

export function hexLegend(info) {
  if (!info) return "";
  const { stops, metric } = info;
  if (metric === "trend" || metric === "anomaly") {
    const lab = metric === "trend" ? [`${fmt(stops[0], 0)}${PCT()}`, "0", `+${fmt(stops[4], 0)}${PCT()}`] : ["×0,25", "×1", "×4"];
    return `<div class="map-panel map-legend"><b class="small">${esc(metric === "trend" ? t("ex.unit_trend") : t("ex.unit_anom"))}</b>
      <div class="scale" style="background:linear-gradient(90deg,#2a78d6,#86b6ef,${isDark() ? "#383835" : "#f0efec"},#ec835a,#d03b3b)"></div>
      <div class="row small muted" style="justify-content:space-between">${lab.map((l) => `<span>${l}</span>`).join("")}</div></div>`;
  }
  const r = heatRamp();
  return `<div class="map-panel map-legend"><b class="small">${esc(t("ex.unit_density"))}</b>
    <div class="scale" style="background:linear-gradient(90deg,${r.join(",")})"></div>
    <div class="row small muted" style="justify-content:space-between"><span>${fmt(stops[0], 1)}</span><span>${fmt(stops[3], 0)}</span><span>${fmt(stops[5], 0)}+</span></div></div>`;
}
