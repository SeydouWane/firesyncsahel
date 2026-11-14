// Animated FireSync logo: hexagonal grid cell, flame, rising embers and an
// orbiting satellite (MODIS/VIIRS). Animations live in CSS and stop under
// prefers-reduced-motion.
let uid = 0;
export function logoSVG({ size = 36, animated = true, title = "FireSync Sahel" } = {}) {
  const id = `fsl${++uid}`;
  return `
<svg class="fs-logo${animated ? "" : " static"}" width="${size}" height="${size}" viewBox="0 0 100 104" role="img" aria-label="${title}">
  <defs>
    <linearGradient id="${id}h" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#8f2b13"/><stop offset="1" stop-color="#4a150b"/>
    </linearGradient>
    <linearGradient id="${id}f" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0" stop-color="#c23a1e"/><stop offset=".55" stop-color="#f28a33"/><stop offset="1" stop-color="#ffd27a"/>
    </linearGradient>
    <linearGradient id="${id}i" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0" stop-color="#ffb347"/><stop offset="1" stop-color="#fff3c4"/>
    </linearGradient>
    <radialGradient id="${id}g" cx="50%" cy="62%" r="50%">
      <stop offset="0" stop-color="#ff9a3c" stop-opacity=".55"/><stop offset="1" stop-color="#ff9a3c" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="${id}c"><path d="M50 6 89 28.5v45L50 96 11 73.5v-45z"/></clipPath>
  </defs>
  <path d="M50 6 89 28.5v45L50 96 11 73.5v-45z" fill="url(#${id}h)"/>
  <g clip-path="url(#${id}c)" fill="none" stroke="#ffb27a" stroke-width="1">
    <path class="hexcell" d="M24 22l8-4.6 8 4.6v9.2l-8 4.6-8-4.6z"/>
    <path class="hexcell c2" d="M60 22l8-4.6 8 4.6v9.2l-8 4.6-8-4.6z"/>
    <path class="hexcell c3" d="M16 50l8-4.6 8 4.6v9.2l-8 4.6-8-4.6z"/>
    <path class="hexcell c4" d="M68 50l8-4.6 8 4.6v9.2l-8 4.6-8-4.6z"/>
  </g>
  <circle cx="50" cy="62" r="30" fill="url(#${id}g)"/>
  <g class="flame-outer">
    <path d="M50 24c5 11 20 17 20 36a20 20 0 0 1-40 0c0-10 6-15 9-23 2 6 5 9 8 10-2-9 0-16 3-23z" fill="url(#${id}f)"/>
  </g>
  <g class="flame-inner">
    <path d="M50 50c3 6 10 9 10 17a10 10 0 0 1-20 0c0-5 3-8 5-12 1 3 2 4 4 5-1-4 0-7 1-10z" fill="url(#${id}i)"/>
  </g>
  <circle class="ember" cx="44" cy="36" r="1.6" fill="#ffd27a" style="--dx:-4px"/>
  <circle class="ember e2" cx="56" cy="34" r="1.3" fill="#ffe7a6" style="--dx:3px"/>
  <circle class="ember e3" cx="50" cy="30" r="1.1" fill="#fff3c4" style="--dx:1px"/>
  <ellipse class="ring" cx="50" cy="52" rx="44" ry="15" fill="none" stroke="#ffd27a" stroke-opacity=".5" stroke-width="1.2"
    transform="rotate(-18 50 52)"/>
  <g transform="rotate(-18 50 52)">
    <g transform="translate(${(animated && moving) ? 0 : 94} ${(animated && moving) ? 0 : 52})">
      <rect x="-3" y="-2.5" width="6" height="5" rx="1" fill="#fff"/>
      <rect x="-9" y="-1.2" width="5" height="2.4" fill="#9ec5f4"/><rect x="4" y="-1.2" width="5" height="2.4" fill="#9ec5f4"/>
      ${(animated && moving) ? `<animateMotion dur="7s" repeatCount="indefinite" path="M94,52 a44,15 0 1,1 -88,0 a44,15 0 1,1 88,0"/>` : ""}
    </g>
  </g>
</svg>`;
}
const reduced = () => { try { return matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; } };
let moving = !reduced();
