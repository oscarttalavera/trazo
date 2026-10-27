/* Trazo — interfaz web local */
"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const S = {
  meta: null, file: null, settings: null, plan: null, calibration: false,
  view: null, req: 0, timer: null, drag: null, hover: null, orig: null, anim: null,
};
const STORE_KEY = "trazo.settings.v1";
const SEC_KEY = "trazo.sections.v1";
const MODE_HINT = {
  trace: "Vectoriza las zonas oscuras como rellenos. Con «colores a separar» > 1 crea un grupo por color.",
  grays: "Separa la imagen en niveles de gris; cada nivel es un grupo con densidad automática: todo con una sola pluma.",
  hatch: "Rayado por capas de tono (líneas en varias direcciones), estilo grabado.",
  centerline: "Sigue el eje de líneas dibujadas (bocetos, firmas, caligrafía).",
  edges: "Dibuja los contornos detectados en la imagen.",
};

// ---------- utilidades ----------
const getK = (o, path) => path.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
function setK(o, path, v) {
  const ks = path.split("."); const last = ks.pop();
  const t = ks.reduce((a, k) => (a[k] ??= {}), o); t[last] = v;
}
function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function prof(kind, name) {
  const list = S.meta.profiles[kind];
  return list.find((p) => p.name === name) || list[0];
}
function busy(on) { $("#busy").hidden = !on; }
let toastTimer = null;
function toast(msg, err = true) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 6000);
}
function isNeutral(hex) {
  const h = (hex || "#000").replace("#", "");
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) || 0);
  return Math.max(...c) - Math.min(...c) <= 18;
}

async function api(url, body, raw = false) {
  const r = await fetch(url, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* sin JSON */ }
    throw new Error(msg);
  }
  return raw ? r : r.json();
}

function saveLocal() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(S.settings)); } catch (_) { /* almacenamiento no disponible */ }
}
function loadLocal(key = STORE_KEY) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (_) { return null; }
}
function merge(base, extra) {
  if (!extra || typeof extra !== "object") return base;
  for (const [k, v] of Object.entries(extra)) {
    if (v && typeof v === "object" && !Array.isArray(v) && base[k] && typeof base[k] === "object") merge(base[k], v);
    else base[k] = v;
  }
  return base;
}

// ---------- inicio ----------
async function loadMeta() {
  S.meta = await api("/api/meta");
  $("#ver").textContent = "v" + S.meta.version;
  $("#profPath").textContent = "Perfiles propios: " + S.meta.profiles_path;
  for (const sel of $$("select.prof")) {
    const kind = sel.dataset.kind;
    sel.innerHTML = S.meta.profiles[kind].map((p) => `<option>${esc(p.name)}</option>`).join("");
  }
  $("#calPen").innerHTML = S.meta.profiles.pens.map((p) => `<option>${esc(p.name)}</option>`).join("");
}

async function init() {
  await loadMeta();
  $("#fontSel").innerHTML = S.meta.fonts.map((f) => `<option>${f}</option>`).join("");
  const d = structuredClone(S.meta.defaults);
  delete d.patterns;
  d.machine = S.meta.profiles.machines[0].name;
  d.material = S.meta.profiles.materials[0].name;
  d.default_pen = (S.meta.profiles.pens.find((p) => p.name === "Fineliner 0.5") || S.meta.profiles.pens[0]).name;
  d.pen_map = {}; d.density_map = {}; d.group_order = [];
  S.settings = merge(d, loadLocal());
  for (const k of ["machine", "material", "default_pen"]) {
    const kind = { machine: "machines", material: "materials", default_pen: "pens" }[k];
    if (!S.meta.profiles[kind].some((p) => p.name === S.settings[k])) S.settings[k] = S.meta.profiles[kind][0].name;
  }
  bindControls();
  setupSections();
  setupCanvas();
  setupFile();
  setupDialogs();
  setupGroupsBulk();
  refreshUI();
  fitView(); draw();
}

function setupSections() {
  const st = loadLocal(SEC_KEY) || {};
  for (const d of $$("details[data-sec]")) {
    if (d.dataset.sec in st) d.open = st[d.dataset.sec];
    d.addEventListener("toggle", () => {
      st[d.dataset.sec] = d.open;
      try { localStorage.setItem(SEC_KEY, JSON.stringify(st)); } catch (_) { /* sin almacenamiento */ }
    });
  }
}

// ---------- controles ----------
function readControl(el) {
  if (el.type === "checkbox") return el.checked;
  if (el.dataset.nullWhen && $(el.dataset.nullWhen).checked) return null;
  if (el.type === "number" || el.type === "range") return el.value === "" ? null : parseFloat(el.value);
  return el.value;
}
function writeControl(el, v) {
  if (el.type === "checkbox") el.checked = !!v;
  else if (el.dataset.nullWhen) { $(el.dataset.nullWhen).checked = v == null; if (v != null) el.value = v; el.disabled = v == null; }
  else el.value = v == null ? "" : v;
  const out = $(`output[data-out="${el.dataset.k}"]`);
  if (out) out.textContent = v == null ? "" : (+v).toFixed(2);
}
function writeAll() { for (const el of $$("[data-k]")) writeControl(el, getK(S.settings, el.dataset.k)); }
function bindControls() {
  writeAll();
  for (const el of $$("[data-k]")) {
    el.addEventListener(el.type === "range" ? "input" : "change", () => {
      setK(S.settings, el.dataset.k, readControl(el));
      writeControl(el, getK(S.settings, el.dataset.k));
      refreshUI(); schedule();
    });
  }
  $("#thrAuto").addEventListener("change", () => {
    const r = $('[data-k="import.threshold"]');
    r.disabled = $("#thrAuto").checked;
    if (!r.value) r.value = 0.5;
    setK(S.settings, "import.threshold", readControl(r));
    schedule();
  });
  for (const b of $$("[data-rot]")) {
    b.addEventListener("click", () => {
      const r = (((S.settings.layout.rotate || 0) + +b.dataset.rot) % 360 + 360) % 360;
      S.settings.layout.rotate = r; writeAll(); refreshUI(); schedule();
    });
  }
  $("#resetOffset").addEventListener("click", () => {
    S.settings.layout.offset_x = 0; S.settings.layout.offset_y = 0; writeAll(); refreshUI(); schedule();
  });
}
function refreshUI() {
  const st = S.settings;
  $("#rasterBox").hidden = !(S.file && S.file.raster);
  const mode = st.import.raster_mode;
  $("#modeHint").textContent = MODE_HINT[mode] || "";
  for (const r of $$("[data-show]")) r.hidden = !r.dataset.show.split(" ").includes(mode);
  for (const r of $$("[data-scale]")) r.hidden = !r.dataset.scale.split(" ").includes(st.layout.scale_mode);
  const m = prof("machines", st.machine), mat = prof("materials", st.material);
  const zc = m.contact_mode === "fixed" ? m.contact_z_fixed + mat.thickness : mat.thickness + m.nozzle_clearance;
  $("#contactHint").innerHTML = m.contact_mode === "insert"
    ? `Modo <b>insertar</b>: haga home <b>sin pluma</b>; la máquina baja a Z ${zc.toFixed(2)} sobre el primer punto y pausa para insertar la pluma tocando la superficie.`
    : `Modo <b>fijo</b>: la punta toca a Z ${zc.toFixed(2)}. ¡Cuidado con el home de Z con la pluma montada!`;
  $("#btnGen").disabled = !S.file;
  $("#origBox").hidden = !(S.file && S.file.viewable);
  saveLocal();
}
function schedule() {
  clearTimeout(S.timer);
  S.timer = setTimeout(replan, 250);
}

// ---------- plan ----------
async function replan() {
  if (!S.file) { if (S.calibration) calPreview(); return; }
  S.calibration = false;
  const id = ++S.req;
  busy(true);
  try {
    const res = await api("/api/plan", { file_id: S.file.file_id, settings: S.settings });
    if (id !== S.req) return;
    const first = !S.plan;
    S.plan = res;
    renderGroups(); renderStats();
    if (first) fitView();
    draw();
  } catch (e) {
    if (id === S.req) toast(e.message);
  } finally { if (id === S.req) busy(false); }
}

// ---------- grupos: pluma + densidad ----------
const DENS_OPTS = [1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1];
function groupSpec(g) {
  const v = S.settings.density_map[g.key];
  if (v === undefined || v === null || v === "") return isNeutral(g.color) ? "auto" : 1;
  return v;
}
function renderGroups() {
  const box = $("#groups");
  const groups = S.plan ? S.plan.groups : [];
  if (!groups.length) { box.innerHTML = '<p class="muted">Sin elementos</p>'; return; }
  const pens = S.meta.profiles.pens;
  box.innerHTML = groups.map((g, i) => {
    const pen = g.key in S.settings.pen_map ? S.settings.pen_map[g.key] : S.settings.default_pen;
    const penObj = pens.find((p) => p.name === pen);
    const popts = pens.map((p) => `<option ${p.name === pen ? "selected" : ""}>${esc(p.name)}</option>`).join("")
      + `<option value="" ${pen === "" ? "selected" : ""}>— omitir —</option>`;
    const spec = groupSpec(g);
    const custom = spec !== "auto" && !DENS_OPTS.some((v) => Math.abs(v - spec) < 1e-6);
    const dopts = `<option value="auto" ${spec === "auto" ? "selected" : ""}>Auto · ${Math.round(g.tone * 100)} %</option>`
      + DENS_OPTS.map((v) => `<option value="${v}" ${!custom && Math.abs(v - spec) < 1e-6 ? "selected" : ""}>${v === 1 ? "Sólido 100 %" : Math.round(v * 100) + " %"}</option>`).join("")
      + (custom ? `<option value="${spec}" selected>${Math.round(spec * 100)} %</option>` : "");
    const kinds = [g.kinds.stroke ? `${g.kinds.stroke} trazo${g.kinds.stroke > 1 ? "s" : ""}` : "",
      g.kinds.fill ? `${g.kinds.fill} relleno${g.kinds.fill > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ");
    const ink = penObj ? penObj.color : "#000";
    const op = pen === "" ? 0 : g.density;
    return `<div class="grp${pen === "" ? " off" : ""}" data-key="${esc(g.key)}">
      <div class="grp-head">
        <span class="sw" title="Color en el archivo" style="background:${esc(g.color)}"></span>
        <span class="arrow">→</span>
        <span class="sw ink" title="Resultado aproximado con la pluma"><i style="background:${esc(ink)};opacity:${op}"></i></span>
        <span class="key" title="${esc(g.key)}">${esc(g.key)}<small>${kinds}</small></span>
        <button class="ico" data-mv="-1" ${i === 0 ? "disabled" : ""} title="Dibujar antes">▲</button>
        <button class="ico" data-mv="1" ${i === groups.length - 1 ? "disabled" : ""} title="Dibujar después">▼</button>
      </div>
      <div class="grp-ctl">
        <select data-pen="${esc(g.key)}" title="Pluma">${popts}</select>
        <select data-dens="${esc(g.key)}" title="Densidad de tinta" ${pen === "" ? "disabled" : ""}>${dopts}</select>
      </div></div>`;
  }).join("");
  for (const sel of box.querySelectorAll("[data-pen]")) {
    sel.addEventListener("change", () => { S.settings.pen_map[sel.dataset.pen] = sel.value; saveLocal(); schedule(); });
  }
  for (const sel of box.querySelectorAll("[data-dens]")) {
    sel.addEventListener("change", () => {
      S.settings.density_map[sel.dataset.dens] = sel.value === "auto" ? "auto" : parseFloat(sel.value);
      saveLocal(); schedule();
    });
  }
  for (const b of box.querySelectorAll("[data-mv]")) {
    b.addEventListener("click", () => {
      const keys = groups.map((g) => g.key);
      const k = b.closest(".grp").dataset.key, i = keys.indexOf(k), j = i + +b.dataset.mv;
      [keys[i], keys[j]] = [keys[j], keys[i]];
      S.settings.group_order = keys; saveLocal(); schedule();
    });
  }
}
function setupGroupsBulk() {
  const keys = () => (S.plan ? S.plan.groups.map((g) => g.key) : []);
  $("#allOnePen").addEventListener("click", () => {
    for (const k of keys()) S.settings.pen_map[k] = S.settings.default_pen;
    saveLocal(); schedule();
  });
  $("#allAuto").addEventListener("click", () => {
    for (const k of keys()) S.settings.density_map[k] = "auto";
    saveLocal(); schedule();
  });
  $("#allSolid").addEventListener("click", () => {
    for (const k of keys()) S.settings.density_map[k] = 1;
    saveLocal(); schedule();
  });
}

function fmtM(mm) { return mm >= 1000 ? (mm / 1000).toFixed(2) + " m" : mm.toFixed(0) + " mm"; }
function fmtS(s) { return s < 90 ? Math.round(s) + " s" : Math.round(s / 60) + " min"; }
function renderStats() {
  const p = S.plan;
  if (!p) { $("#stats").innerHTML = ""; $("#legend").innerHTML = ""; showWarnings([]); return; }
  const st = p.stats;
  const changes = S.settings.per_pen ? 0 : Math.max(0, p.jobs.length - 1);
  const items = [["Tiempo estimado", st.time], ["Dibujo", fmtM(st.draw_mm)], ["Viajes", fmtM(st.travel_mm)],
    ["Levantadas", st.lifts], ["Plumas", p.jobs.length + (changes ? ` (${changes} cambio${changes > 1 ? "s" : ""})` : "")],
    ["Archivos", p.files.length]];
  if (p.scale && Math.abs(p.scale - 1) > 1e-6) items.push(["Escala", (p.scale * 100).toFixed(1) + " %"]);
  if (p.design_bounds) {
    const b = p.design_bounds;
    items.push(["Tamaño", `${(b[2] - b[0]).toFixed(1)} × ${(b[3] - b[1]).toFixed(1)} mm`]);
  }
  $("#stats").innerHTML = items.map(([k, v]) => `<span>${k}<b>${v}</b></span>`).join("");
  $("#legend").innerHTML = p.jobs.map((j, i) => {
    const e = st.per_pen[i];
    return `<div><i style="background:${esc(j.color)}"></i>${i + 1}. ${esc(j.pen)} · ${j.paths.length} trazos · ${e ? fmtS(e.seconds) : ""}</div>`;
  }).join("");
  showWarnings(p.warnings);
}
function showWarnings(list) {
  $("#warnings").innerHTML = list.map((w) => `<li>${esc(w)}</li>`).join("");
}

// ---------- archivo ----------
async function openFile(f) {
  const fd = new FormData(); fd.append("file", f);
  busy(true);
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    S.file = await r.json();
    S.file.viewable = /\.(svg|png|jpe?g|gif|webp|bmp)$/i.test(S.file.name);
    S.plan = null; S.calibration = false; S.orig = null;
    S.settings.layout.offset_x = 0; S.settings.layout.offset_y = 0; writeAll();
    $("#fname").textContent = S.file.name;
    $("#drop").classList.add("hidden");
    refreshUI();
    await replan();
  } catch (e) { toast(e.message); } finally { busy(false); }
}
function setupFile() {
  $("#file").addEventListener("change", (e) => e.target.files[0] && openFile(e.target.files[0]));
  const view = $(".view"), drop = $("#drop");
  view.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.remove("hidden"); drop.classList.add("over"); });
  view.addEventListener("dragleave", () => { drop.classList.remove("over"); if (S.file) drop.classList.add("hidden"); });
  view.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files[0]) openFile(e.dataTransfer.files[0]);
  });
  $("#btnGen").addEventListener("click", async () => {
    busy(true);
    try {
      const r = await api("/api/gcode", { file_id: S.file.file_id, settings: S.settings }, true);
      await saveBlob(r);
      toast("G-code descargado. Cópielo a la tarjeta SD.", false);
    } catch (e) { toast(e.message); } finally { busy(false); }
  });
}
async function saveBlob(r) {
  const cd = r.headers.get("Content-Disposition") || "";
  const name = (cd.match(/filename="([^"]+)"/) || [])[1] || "trazo.gcode";
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ---------- lienzo ----------
const cv = () => $("#cv");
function machineBox() {
  const m = prof("machines", S.settings.machine);
  return {
    m, bed: [m.x_min, m.y_min, m.x_max, m.y_max],
    reach: [m.x_min + m.pen_offset_x, m.y_min + m.pen_offset_y, m.x_max + m.pen_offset_x, m.y_max + m.pen_offset_y],
  };
}
function fitView() {
  const c = cv(), { bed, reach } = machineBox();
  const x0 = Math.min(bed[0], reach[0]), y0 = Math.min(bed[1], reach[1]);
  const x1 = Math.max(bed[2], reach[2]), y1 = Math.max(bed[3], reach[3]);
  const W = c.clientWidth, H = c.clientHeight, pad = 30, top = 76;
  const k = Math.min((W - 2 * pad) / (x1 - x0), (H - pad - top) / (y1 - y0));
  S.view = { k, ox: (W - (x1 - x0) * k) / 2 - x0 * k, oy: top + (H - pad - top + (y1 - y0) * k) / 2 + y0 * k };
}
function toWorld(e) {
  const r = cv().getBoundingClientRect(), v = S.view;
  return [(e.clientX - r.left - v.ox) / v.k, (v.oy - (e.clientY - r.top)) / v.k];
}
function inDesign(x, y) {
  const b = S.plan && !S.calibration ? S.plan.design_bounds : null;
  return b && x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];
}
function setupCanvas() {
  const c = cv();
  new ResizeObserver(() => { if (!S.view) fitView(); draw(); }).observe(c);
  c.addEventListener("wheel", (e) => {
    e.preventDefault();
    const f = Math.exp(-e.deltaY * 0.0015), r = c.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top, v = S.view;
    v.ox = mx - (mx - v.ox) * f; v.oy = my - (my - v.oy) * f; v.k *= f; draw();
  }, { passive: false });
  c.addEventListener("pointerdown", (e) => {
    const [x, y] = toWorld(e);
    const move = inDesign(x, y) && e.button === 0 && !e.shiftKey;
    S.drag = { move, sx: e.clientX, sy: e.clientY, x: e.clientX, y: e.clientY, dx: 0, dy: 0 };
    c.setPointerCapture(e.pointerId);
    c.style.cursor = move ? "move" : "grabbing";
  });
  c.addEventListener("pointermove", (e) => {
    const [x, y] = toWorld(e);
    const m = prof("machines", S.settings.machine);
    $("#coords").textContent = `pluma X ${x.toFixed(1)}  Y ${y.toFixed(1)} · boquilla X ${(x - m.pen_offset_x).toFixed(1)} Y ${(y - m.pen_offset_y).toFixed(1)}`;
    const d = S.drag;
    if (!d) {
      const h = inDesign(x, y);
      c.style.cursor = h ? "move" : "grab";
      if (h !== S.hover) { S.hover = h; draw(); }
      return;
    }
    if (d.move) {
      d.dx = (e.clientX - d.sx) / S.view.k; d.dy = -(e.clientY - d.sy) / S.view.k;
    } else {
      S.view.ox += e.clientX - d.x; S.view.oy += e.clientY - d.y;
    }
    d.x = e.clientX; d.y = e.clientY; draw();
  });
  c.addEventListener("pointerup", () => {
    const d = S.drag; S.drag = null; c.style.cursor = "grab";
    if (d && d.move && (Math.abs(d.dx) > 0.05 || Math.abs(d.dy) > 0.05)) {
      const L = S.settings.layout;
      L.offset_x = +((L.offset_x || 0) + d.dx).toFixed(1);
      L.offset_y = +((L.offset_y || 0) + d.dy).toFixed(1);
      // vista provisional desplazada hasta que llegue el nuevo plan
      shiftPlan(d.dx, d.dy);
      writeAll(); saveLocal(); schedule();
    }
    draw();
  });
  c.addEventListener("pointerleave", () => { $("#coords").textContent = ""; });
  $("#fitView").addEventListener("click", () => { fitView(); draw(); });
  for (const id of ["#realWidth", "#showTravel", "#progress"]) $(id).addEventListener("input", draw);
  $("#showOrig").addEventListener("change", draw);
  $("#play").addEventListener("click", togglePlay);
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, select, textarea, dialog")) return;
    if (e.key === "f" || e.key === "F") { fitView(); draw(); }
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
  });
}
function shiftPlan(dx, dy) {
  const p = S.plan; if (!p) return;
  for (const j of p.jobs) for (const q of j.paths) for (let i = 0; i < q.length; i += 2) { q[i] += dx; q[i + 1] += dy; }
  if (p.design_bounds) p.design_bounds = [p.design_bounds[0] + dx, p.design_bounds[1] + dy, p.design_bounds[2] + dx, p.design_bounds[3] + dy];
  if (p.matrix) { p.matrix[0][2] += dx; p.matrix[1][2] += dy; }
}
function togglePlay() {
  const r = $("#progress");
  if (S.anim) { cancelAnimationFrame(S.anim); S.anim = null; $("#play").textContent = "▶"; return; }
  if (+r.value >= 1000) r.value = 0;
  $("#play").textContent = "❚❚";
  let last = performance.now();
  const step = (t) => {
    r.value = Math.min(1000, +r.value + (t - last) / 8); last = t; draw();
    if (+r.value >= 1000) { S.anim = null; $("#play").textContent = "▶"; return; }
    S.anim = requestAnimationFrame(step);
  };
  S.anim = requestAnimationFrame(step);
}
function origImage() {
  if (!S.file || !S.file.viewable) return null;
  if (!S.orig || S.orig.fid !== S.file.file_id) {
    const img = new Image();
    img.onload = draw;
    img.src = `/api/source/${S.file.file_id}`;
    S.orig = { fid: S.file.file_id, img };
  }
  return S.orig.img.complete && S.orig.img.naturalWidth ? S.orig.img : null;
}
function draw() {
  const c = cv(); if (!S.view || !S.meta) return;
  const dpr = window.devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight;
  if (c.width !== W * dpr || c.height !== H * dpr) { c.width = W * dpr; c.height = H * dpr; }
  const g = c.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const css = getComputedStyle(document.documentElement);
  g.fillStyle = css.getPropertyValue("--canvas"); g.fillRect(0, 0, W, H);
  const { k, ox, oy } = S.view;
  const X = (x) => ox + x * k, Y = (y) => oy - y * k;
  const rect = (b) => [X(b[0]), Y(b[3]), (b[2] - b[0]) * k, (b[3] - b[1]) * k];
  const { m, bed, reach } = machineBox();
  const mat = prof("materials", S.settings.material);

  // cama + cuadrícula
  g.fillStyle = css.getPropertyValue("--bed"); g.fillRect(...rect(bed));
  g.strokeStyle = "rgba(0,0,0,.07)"; g.lineWidth = 1; g.beginPath();
  for (let x = Math.ceil(bed[0] / 10) * 10; x <= bed[2]; x += 10) { g.moveTo(X(x), Y(bed[1])); g.lineTo(X(x), Y(bed[3])); }
  for (let y = Math.ceil(bed[1] / 10) * 10; y <= bed[3]; y += 10) { g.moveTo(X(bed[0]), Y(y)); g.lineTo(X(bed[2]), Y(y)); }
  g.stroke();
  g.setLineDash([6, 4]); g.strokeStyle = "rgba(0,0,0,.35)"; g.strokeRect(...rect(reach)); g.setLineDash([]);
  const mb = [mat.origin_x, mat.origin_y, mat.origin_x + mat.width, mat.origin_y + mat.height];
  g.save(); g.shadowColor = "rgba(0,0,0,.25)"; g.shadowBlur = 8;
  g.fillStyle = css.getPropertyValue("--sheet"); g.fillRect(...rect(mb)); g.restore();
  const area = S.plan ? S.plan.drawable : null;
  if (area) { g.setLineDash([4, 3]); g.strokeStyle = "#4a90d9"; g.strokeRect(...rect(area)); g.setLineDash([]); }
  g.fillStyle = "#e5484d"; g.beginPath(); g.arc(X(0), Y(0), 3, 0, 7); g.fill();
  g.fillStyle = "rgba(0,0,0,.55)"; g.font = "11px system-ui";
  g.fillText(`${m.name} · ${bed[2] - bed[0]}×${bed[3] - bed[1]} mm · ${mat.name}`, X(bed[0]), Y(bed[3]) - 6);

  if (!S.plan) return;
  const d = S.drag && S.drag.move ? S.drag : { dx: 0, dy: 0 };
  const DX = (x) => X(x + d.dx), DY = (y) => Y(y + d.dy);

  // original superpuesto
  const img = $("#showOrig").checked && S.plan.extent && S.plan.matrix ? origImage() : null;
  if (img) {
    const [[a, b, tx], [cc, dd, ty]] = S.plan.matrix, e = S.plan.extent;
    const sx = (e[2] - e[0]) / img.naturalWidth, sy = (e[3] - e[1]) / img.naturalHeight;
    const A = k * a * sx, C = -k * b * sy, E = ox + k * (a * e[0] + b * e[3] + tx + d.dx);
    const B = -k * cc * sx, D = k * dd * sy, F = oy - k * (cc * e[0] + dd * e[3] + ty + d.dy);
    g.save(); g.globalAlpha = 0.35;
    g.setTransform(dpr * A, dpr * B, dpr * C, dpr * D, dpr * E, dpr * F);
    g.drawImage(img, 0, 0);
    g.restore(); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  const real = $("#realWidth").checked, travel = $("#showTravel").checked;
  const total = S.plan.jobs.reduce((a, j) => a + j.paths.length, 0);
  let left = Math.round(total * $("#progress").value / 1000);
  let px = m.park_x + m.pen_offset_x, py = m.park_y + m.pen_offset_y;
  g.lineCap = "round"; g.lineJoin = "round";
  for (const j of S.plan.jobs) {
    if (left <= 0) break;
    const n = Math.min(left, j.paths.length); left -= n;
    g.strokeStyle = j.color;
    g.lineWidth = real ? Math.max(j.tip * k, 0.6) : 1;
    g.beginPath();
    for (let i = 0; i < n; i++) {
      const p = j.paths[i];
      g.moveTo(DX(p[0]), DY(p[1]));
      if (p.length === 2) g.lineTo(DX(p[0]) + 0.01, DY(p[1]));
      for (let q = 2; q < p.length; q += 2) g.lineTo(DX(p[q]), DY(p[q + 1]));
    }
    g.stroke();
    if (travel) {
      g.beginPath(); g.strokeStyle = "rgba(229,72,77,.6)"; g.lineWidth = 1; g.setLineDash([3, 3]);
      for (let i = 0; i < n; i++) {
        const p = j.paths[i];
        g.moveTo(DX(px), DY(py)); g.lineTo(DX(p[0]), DY(p[1]));
        px = p[p.length - 2]; py = p[p.length - 1];
      }
      g.stroke(); g.setLineDash([]);
    } else {
      const p = j.paths[n - 1]; px = p[p.length - 2]; py = p[p.length - 1];
    }
  }
  // posición actual de la pluma durante la animación
  if (+$("#progress").value < 1000 && total) {
    g.fillStyle = "#e5484d"; g.beginPath(); g.arc(DX(px), DY(py), 4, 0, 7); g.fill();
  }

  // caja del diseño con medidas (al pasar el ratón o arrastrar)
  const db = S.plan.design_bounds;
  if (db && !S.calibration && (S.hover || (S.drag && S.drag.move))) {
    const bb = [db[0] + d.dx, db[1] + d.dy, db[2] + d.dx, db[3] + d.dy];
    g.setLineDash([5, 4]); g.strokeStyle = "#1f6feb"; g.lineWidth = 1; g.strokeRect(...rect(bb)); g.setLineDash([]);
    g.fillStyle = "#1f6feb"; g.font = "12px system-ui";
    g.fillText(`${(bb[2] - bb[0]).toFixed(1)} × ${(bb[3] - bb[1]).toFixed(1)} mm`, X(bb[0]), Y(bb[3]) - 6);
    g.fillText(`X ${bb[0].toFixed(1)}  Y ${bb[1].toFixed(1)}`, X(bb[0]), Y(bb[1]) + 14);
  }
}

// ---------- perfiles ----------
let dlgKind = null;
const KIND_TITLE = { machines: "Máquinas", pens: "Plumas", materials: "Materiales" };
function setupDialogs() {
  for (const b of $$("[data-edit]")) b.addEventListener("click", () => openProfiles(b.dataset.edit));
  $("#dlgSel").addEventListener("change", () => renderProfileForm(prof(dlgKind, $("#dlgSel").value)));
  $("#dlgSave").addEventListener("click", () => saveProfile(collectProfile()));
  $("#dlgDup").addEventListener("click", () => {
    const p = collectProfile(); p.name = p.name + " (copia)"; saveProfile(p);
  });
  $("#dlgDelete").addEventListener("click", async () => {
    const name = $("#dlgSel").value;
    if (!confirm(`¿Eliminar el perfil propio «${name}»? (los integrados vuelven a su valor original)`)) return;
    await fetch(`/api/profiles/${dlgKind}/${encodeURIComponent(name)}`, { method: "DELETE" });
    await afterProfileChange(null);
  });
  $("#btnCal").addEventListener("click", () => { $("#calPen").value = S.settings.default_pen; $("#calDlg").showModal(); });
  $("#calPreview").addEventListener("click", () => { $("#calDlg").close(); S.calibration = true; calPreview(); });
  $("#calDownload").addEventListener("click", async () => {
    try {
      const r = await api("/api/calibration", { ...calBody(), download: true }, true);
      await saveBlob(r); $("#calDlg").close();
    } catch (e) { toast(e.message); }
  });
}
function calBody() { return { machine: S.settings.machine, material: S.settings.material, pen: $("#calPen").value }; }
async function calPreview() {
  try {
    S.plan = await api("/api/calibration", calBody());
    S.plan.groups = []; renderStats(); draw();
    $("#drop").classList.add("hidden");
  } catch (e) { toast(e.message); }
}
function openProfiles(kind) {
  dlgKind = kind;
  $("#dlgTitle").textContent = KIND_TITLE[kind];
  const cur = { machines: S.settings.machine, pens: S.settings.default_pen, materials: S.settings.material }[kind];
  $("#dlgSel").innerHTML = S.meta.profiles[kind].map((p) => `<option ${p.name === cur ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  renderProfileForm(prof(kind, cur));
  $("#dlg").showModal();
}
function renderProfileForm(p) {
  const fields = S.meta.fields[dlgKind];
  $("#dlgNote").textContent = p._builtin ? "Perfil integrado: al guardar se crea su versión propia." : "Perfil propio";
  $("#dlgBody").innerHTML = Object.entries(fields).map(([k, info]) => {
    const [label, help, choices] = info, v = p[k];
    let input;
    if (choices) input = `<select data-f="${k}">${choices.map((c) => `<option ${c === v ? "selected" : ""}>${c}</option>`).join("")}</select>`;
    else if (typeof v === "boolean") input = `<input type="checkbox" data-f="${k}" ${v ? "checked" : ""}>`;
    else if (k.endsWith("_gcode")) input = `<textarea data-f="${k}">${esc(v || "")}</textarea>`;
    else if (k === "color") input = `<input type="color" data-f="${k}" value="${esc(v)}">`;
    else if (typeof v === "number" || v === null) input = `<input type="number" step="any" data-f="${k}" data-num="1" value="${v ?? ""}">`;
    else input = `<input type="text" data-f="${k}" value="${esc(v)}">`;
    return `<div class="row"><label>${esc(label)}</label>${input}${help ? `<div class="help">${esc(help)}</div>` : ""}</div>`;
  }).join("");
}
function collectProfile() {
  const out = {};
  for (const el of $("#dlgBody").querySelectorAll("[data-f]")) {
    const k = el.dataset.f;
    if (el.type === "checkbox") out[k] = el.checked;
    else if (el.dataset.num) out[k] = el.value === "" ? null : parseFloat(el.value);
    else out[k] = el.value;
  }
  return out;
}
async function saveProfile(p) {
  try {
    const r = await fetch(`/api/profiles/${dlgKind}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) });
    if (!r.ok) throw new Error((await r.json()).detail);
    await afterProfileChange(p.name);
    toast(`Perfil «${p.name}» guardado.`, false);
  } catch (e) { toast(e.message); }
}
async function afterProfileChange(name) {
  await loadMeta();
  const key = { machines: "machine", pens: "default_pen", materials: "material" }[dlgKind];
  const list = S.meta.profiles[dlgKind];
  if (name && list.some((p) => p.name === name)) S.settings[key] = name;
  if (!list.some((p) => p.name === S.settings[key])) S.settings[key] = list[0].name;
  writeAll();
  $("#dlgSel").innerHTML = list.map((p) => `<option ${p.name === (name || S.settings[key]) ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  renderProfileForm(prof(dlgKind, $("#dlgSel").value));
  refreshUI(); fitView(); schedule(); draw();
}

init().catch((e) => toast("Error al iniciar: " + e.message));
