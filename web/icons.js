/* Iconos de Trazo: contorno 1.5 px a 24 px, terminaciones planas, un solo color
   (estilo IBM Carbon, como pide el sistema visual Tritic). */
"use strict";
const ICONS = {
  folder: '<path d="M3 5.5h6l2 2h10v11.5H3z"/>',
  download: '<path d="M12 3.5v11"/><path d="M7 10l5 5 5-5"/><path d="M4 19.5h16"/>',
  ruler: '<path d="M2.5 8.5h19v7h-19z"/><path d="M6.5 8.5v3M10.5 8.5v4M14.5 8.5v3M18.5 8.5v4"/>',
  info: '<path d="M12 3a9 9 0 1 0 0.001 0z"/><path d="M12 10.5v6.5"/><path d="M12 7v1.8"/>',
  chevron: '<path d="M7 9.5l5 5 5-5"/>',
  sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><path d="M13 4.5v5M15 4.5v5M7 14.5v5M9 14.5v5" />',
  fit: '<path d="M3.5 9V3.5H9M15 3.5h5.5V9M20.5 15v5.5H15M9 20.5H3.5V15"/><path d="M8 8h8v8H8z"/>',
  zoomin: '<path d="M10.5 3.5a7 7 0 1 0 0.001 0z"/><path d="M15.5 15.5l5 5"/><path d="M7 10.5h7M10.5 7v7"/>',
  zoomout: '<path d="M10.5 3.5a7 7 0 1 0 0.001 0z"/><path d="M15.5 15.5l5 5"/><path d="M7 10.5h7"/>',
  weight: '<path d="M3.5 6h17" stroke-width="1"/><path d="M3.5 11.5h17" stroke-width="2"/><path d="M3.5 17.5h17" stroke-width="3.2"/>',
  route: '<path d="M4 17.5h3v3H4zM17 3.5h3v3h-3z"/><path d="M7.5 17L17 7.5" stroke-dasharray="2 2"/>',
  image: '<path d="M3 4.5h18v15H3z"/><path d="M3 16l5-5 4 4 3-3 6 6"/><path d="M15.5 7.5h2v2h-2z"/>',
  panel: '<path d="M3 4.5h18v15H3z"/><path d="M15 4.5v15"/><path d="M17 8h2M17 11h2"/>',
  play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M6.5 4.5h4v15h-4zM13.5 4.5h4v15h-4z" fill="currentColor" stroke="none"/>',
  rotl: '<path d="M4 4.5v5h5"/><path d="M4.8 9.5A8 8 0 1 1 5.5 16"/>',
  rotr: '<path d="M20 4.5v5h-5"/><path d="M19.2 9.5A8 8 0 1 0 18.5 16"/>',
  fliph: '<path d="M12 2.5v19" stroke-dasharray="2 2"/><path d="M9 6.5L3 17.5h6zM15 6.5l6 11h-6z"/>',
  flipv: '<path d="M2.5 12h19" stroke-dasharray="2 2"/><path d="M6.5 9L17.5 3v6zM6.5 15l11 6v-6z"/>',
  reset: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4 3.5v4.5h4.5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  up: '<path d="M12 19V5.5"/><path d="M6.5 11L12 5.5 17.5 11"/>',
  down: '<path d="M12 5v13.5"/><path d="M6.5 13L12 18.5 17.5 13"/>',
  trash: '<path d="M4 6.5h16M9.5 6.5V4h5v2.5"/><path d="M6 6.5l1 13.5h10l1-13.5"/>',
  copy: '<path d="M8 8h12v12H8z"/><path d="M16 8V4H4v12h4"/>',
  warn: '<path d="M12 3.5L21.5 20h-19z"/><path d="M12 9.5v5.5M12 16.8v1.5"/>',
  check: '<path d="M4.5 12.5l5 5L19.5 7"/>',
  pen: '<path d="M14.5 4.5l5 5L9 20H4v-5z"/><path d="M12.5 6.5l5 5"/>',
  "p-lines": '<path d="M3.5 3.5h17v17h-17z" stroke-width="1"/><path d="M3.5 12.5l9-9M3.5 20.5l17-17M11.5 20.5l9-9"/>',
  "p-zigzag": '<path d="M3.5 3.5h17v17h-17z" stroke-width="1"/><path d="M6 7h12L6 12h12L6 17h12"/>',
  "p-cross": '<path d="M3.5 3.5h17v17h-17z" stroke-width="1"/><path d="M3.5 12.5l9-9M3.5 20.5l17-17M11.5 20.5l9-9M3.5 11.5l9 9M3.5 3.5l17 17M11.5 3.5l9 9"/>',
  "p-concentric": '<path d="M3.5 3.5h17v17h-17zM7.5 7.5h9v9h-9zM11 11h2v2h-2z"/>',
  "p-none": '<path d="M3.5 3.5h17v17h-17z"/>',
};
function icon(name, size = 18) {
  const body = ICONS[name] || "";
  return `<svg class="icn" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="1.5" stroke-linecap="butt" stroke-linejoin="miter" aria-hidden="true">${body}</svg>`;
}
function hydrateIcons(root = document) {
  for (const el of root.querySelectorAll("i[data-icon]")) {
    if (el.dataset.done) continue;
    el.innerHTML = icon(el.dataset.icon, +(el.dataset.size || 18));
    el.dataset.done = "1";
  }
}
