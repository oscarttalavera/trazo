/* Trazo — interfaz web local (sistema visual Tritic) */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const S = {
  meta: null, file: null, settings: null, plan: null, calibration: false,
  view: null, req: 0, timer: null, drag: null, hover: false, orig: null, anim: null, cursor: null,
};
const STORE_KEY = "trazo.settings.v1";
const UI_KEY = "trazo.ui.v2";
const PX_PER_MM = 96 / 25.4;
const RULER = 20;
const MODE_HINT = {
  trace: "Vectoriza las zonas oscuras como rellenos. Con «colores a separar» mayor a 1 crea un grupo por color.",
  grays: "Separa la imagen en niveles de gris; cada nivel es un grupo con densidad automática: todo con una sola pluma.",
  hatch: "Rayado por capas de tono en varias direcciones, estilo grabado.",
  centerline: "Sigue el eje de las líneas dibujadas: bocetos, firmas, caligrafía.",
  edges: "Dibuja los contornos detectados en la imagen.",
};
const PATTERN_NAME = { zigzag: "Zigzag", lines: "Líneas", cross: "Cruzado", concentric: "Concéntrico", none: "Contorno" };
const SCALE_NAME = { real: "Real", fit: "Ajustar", width: "Ancho", height: "Alto", factor: "Factor" };

// ---------- utilidades ----------
const getK = (o, path) => path.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
function setK(o, path, v) {
  const ks = path.split("."); const last = ks.pop();
  const t = ks.reduce((a, k) => (a[k] ??= {}), o); t[last] = v;
}
function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function prof(kind, name) { const l = S.meta.profiles[kind]; return l.find((p) => p.name === name) || l[0]; }
const fmt = (v, d = 1) => (v == null || isNaN(v) ? "—" : (+v).toFixed(d));
function fmtM(mm) { return mm >= 1000 ? (mm / 1000).toFixed(2) + " m" : mm.toFixed(0) + " mm"; }
function fmtS(s) { if (s < 60) return Math.round(s) + " s"; const m = Math.round(s / 60); return m < 60 ? m + " min" : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`; }
function isNeutral(hex) {
  const h = (hex || "#000").replace("#", "");
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) || 0);
  return Math.max(...c) - Math.min(...c) <= 18;
}
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function loadJSON(key) { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (_) { return null; } }
function saveJSON(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch (_) { /* sin almacenamiento */ } }
function saveLocal() { saveJSON(STORE_KEY, S.settings); }
const UI = Object.assign({ closed: {}, insp: true, width: true, travel: false, orig: false }, loadJSON(UI_KEY) || {});
const saveUI = () => saveJSON(UI_KEY, UI);
function merge(base, extra) {
  if (!extra || typeof extra !== "object") return base;
  for (const [k, v] of Object.entries(extra)) {
    if (v && typeof v === "object" && !Array.isArray(v) && base[k] && typeof base[k] === "object") merge(base[k], v);
    else base[k] = v;
  }
  return base;
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
function busy(on, label = "Calculando…") {
  $("#loadbar").hidden = !on;
  const st = $("#state"); st.textContent = on ? label : "Listo"; st.classList.toggle("busy", on);
}
let toastTimer = null;
function toast(msg, kind = "err") {
  const t = $("#toast");
  t.className = "callout toast " + kind;
  t.dataset.tab = { err: "ERROR", ok: "LISTO", warn: "PRECAUCIÓN" }[kind] || "NOTA";
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, kind === "err" ? 8000 : 4000);
}

// ---------- inicio ----------
async function loadMeta() {
  S.meta = await api("/api/meta");
  for (const sel of $$("select.prof")) {
    sel.innerHTML = S.meta.profiles[sel.dataset.kind].map((p) => `<option>${esc(p.name)}</option>`).join("");
  }
  $("#calPen").innerHTML = S.meta.profiles.pens.map((p) => `<option>${esc(p.name)}</option>`).join("");
  $("#verInfo").textContent = `Trazo ${S.meta.version}`;
  $("#aboutVer").textContent = `Versión ${S.meta.version}`;
  $("#aboutPath").textContent = S.meta.profiles_path;
}

async function init() {
  hydrateIcons();
  await loadMeta();
  $("#fontSel").innerHTML = S.meta.fonts.map((f) => `<option>${f}</option>`).join("");
  const d = structuredClone(S.meta.defaults);
  delete d.patterns;
  d.machine = S.meta.profiles.machines[0].name;
  d.material = S.meta.profiles.materials[0].name;
  d.default_pen = (S.meta.profiles.pens.find((p) => p.name === "Fineliner 0.5") || S.meta.profiles.pens[0]).name;
  d.pen_map = {}; d.density_map = {}; d.group_order = [];
  S.settings = merge(d, loadJSON(STORE_KEY));
  for (const [k, kind] of [["machine", "machines"], ["material", "materials"], ["default_pen", "pens"]]) {
    if (!S.meta.profiles[kind].some((p) => p.name === S.settings[k])) S.settings[k] = S.meta.profiles[kind][0].name;
  }
  bindControls(); setupSections(); setupCanvas(); setupFile(); setupDialogs(); setupGroupsBulk(); setupKeys();
  $("#tWidth").classList.toggle("on", UI.width);
  $("#tTravel").classList.toggle("on", UI.travel);
  $("#tOrig").classList.toggle("on", UI.orig);
  setInspector(inspOn());
  refreshUI(); renderFile(); renderInspector();
  fitView(); draw();
}

function setupSections() {
  for (const sec of $$(".sec")) {
    const key = sec.dataset.sec;
    sec.classList.toggle("closed", !!UI.closed[key]);
    $(".sec-h", sec).addEventListener("click", () => {
      sec.classList.toggle("closed"); UI.closed[key] = sec.classList.contains("closed"); saveUI();
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
  if (out) out.textContent = v == null ? "auto" : (+v).toFixed(2);
}
function writeAll() {
  for (const el of $$("[data-k]")) writeControl(el, getK(S.settings, el.dataset.k));
  for (const seg of $$("[data-seg]")) {
    const v = String(getK(S.settings, seg.dataset.seg));
    for (const b of $$("button", seg)) b.classList.toggle("on", b.dataset.v === v);
  }
  for (const b of $$("[data-tog]")) b.classList.toggle("on", !!getK(S.settings, b.dataset.tog));
}
function changed() { writeAll(); refreshUI(); schedule(); }
function bindControls() {
  writeAll();
  for (const el of $$("[data-k]")) {
    el.addEventListener(el.type === "range" ? "input" : "change", () => {
      setK(S.settings, el.dataset.k, readControl(el)); changed();
    });
  }
  for (const seg of $$("[data-seg]")) {
    for (const b of $$("button", seg)) {
      b.addEventListener("click", () => {
        const raw = b.dataset.v;
        setK(S.settings, seg.dataset.seg, raw === "true" ? true : raw === "false" ? false : raw); changed();
      });
    }
  }
  for (const b of $$("[data-tog]")) {
    b.addEventListener("click", () => { setK(S.settings, b.dataset.tog, !getK(S.settings, b.dataset.tog)); changed(); });
  }
  $("#thrAuto").addEventListener("change", () => {
    const r = $('[data-k="import.threshold"]');
    if (!r.value) r.value = 0.5;
    r.disabled = $("#thrAuto").checked;
    setK(S.settings, "import.threshold", readControl(r)); changed();
  });
  for (const b of $$("[data-rot]")) {
    b.addEventListener("click", () => {
      S.settings.layout.rotate = ((((S.settings.layout.rotate || 0) + +b.dataset.rot) % 360) + 360) % 360; changed();
    });
  }
  $("#resetOffset").addEventListener("click", () => { S.settings.layout.offset_x = 0; S.settings.layout.offset_y = 0; changed(); });
}

function refreshUI() {
  const st = S.settings;
  $("#rasterBox").hidden = !(S.file && S.file.raster);
  const mode = st.import.raster_mode;
  $("#modeHint").textContent = MODE_HINT[mode] || "";
  for (const r of $$("[data-show]")) r.hidden = !r.dataset.show.split(" ").includes(mode);
  for (const r of $$("[data-scale]")) r.hidden = !r.dataset.scale.split(" ").includes(st.layout.scale_mode);
  for (const r of $$("[data-stroke]")) r.hidden = st.stroke.mode !== r.dataset.stroke;
  const m = prof("machines", st.machine), mat = prof("materials", st.material);
  const zc = m.contact_mode === "fixed" ? m.contact_z_fixed + mat.thickness : mat.thickness + m.nozzle_clearance;
  const note = $("#contactNote");
  if (m.contact_mode === "insert") {
    note.dataset.tab = "EN PLANTA";
    note.innerHTML = `Haga home <b>sin pluma</b>. La máquina baja a <span class="mono">Z ${zc.toFixed(2)} mm</span> sobre el primer punto y pausa para insertar la pluma hasta tocar la superficie.`;
  } else {
    note.dataset.tab = "PRECAUCIÓN";
    note.innerHTML = `Modo fijo: la punta toca a <span class="mono">Z ${zc.toFixed(2)} mm</span>. Cuidado con el home de Z con la pluma montada.`;
  }
  $("#btnGen").disabled = !S.file;
  $("#tOrig").hidden = !(S.file && S.file.viewable);
  $("#playbar").hidden = !S.plan || !S.plan.jobs.length;
  $("#machInfo").textContent = `${m.name} · ${mat.name} ${mat.thickness} mm`;
  renderSummaries();
  saveLocal();
}
function renderSummaries() {
  const st = S.settings, p = S.plan;
  const set = (k, v) => { $(`[data-sum="${k}"]`).textContent = v; };
  set("archivo", S.file ? S.file.name : "—");
  const pens = p ? p.jobs.length : 0, groups = p && p.groups ? p.groups.length : 0;
  set("plumas", p ? `${pens} pluma${pens === 1 ? "" : "s"} · ${groups} grupo${groups === 1 ? "" : "s"}` : st.default_pen);
  set("maquina", `${st.machine} · ${st.material}`);
  set("disposicion", `${SCALE_NAME[st.layout.scale_mode]} · ${st.layout.rotate || 0}°`);
  set("relleno", `${PATTERN_NAME[st.fill.pattern]} ${st.fill.angle}°`);
  set("salida", st.per_pen ? "uno por pluma" : "un archivo");
}
function schedule() { clearTimeout(S.timer); S.timer = setTimeout(replan, 250); }

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
    renderGroups(); renderInspector(); renderFile(); refreshUI();
    if (first) fitView();
    draw();
  } catch (e) {
    if (id === S.req) toast(e.message);
  } finally { if (id === S.req) busy(false); }
}

// ---------- 01 archivo ----------
function renderFile() {
  const card = $("#filecard"), dn = $("#docname");
  if (!S.file) {
    card.innerHTML = '<p class="muted">Ningún archivo abierto.</p><button class="btn" data-action="open"><i data-icon="folder"></i>Abrir archivo…</button>';
    dn.innerHTML = '<span class="muted-d">Sin archivo</span>';
  } else {
    const ext = S.file.name.split(".").pop().toUpperCase();
    const b = S.plan && S.plan.design_bounds;
    const size = b ? `${fmt(b[2] - b[0])} × ${fmt(b[3] - b[1])} mm` : "—";
    const n = S.plan && S.plan.groups ? S.plan.groups.reduce((a, g) => a + g.items, 0) : "—";
    card.innerHTML = `<p class="fc-n">${esc(S.file.name)}</p>
      <dl class="kv"><dt>Formato</dt><dd>${ext}${S.file.raster ? " · imagen" : " · vector"}</dd>
      <dt>Tamaño final</dt><dd>${size}</dd><dt>Elementos</dt><dd>${n}</dd></dl>
      <button class="btn sm" data-action="open"><i data-icon="folder"></i>Abrir otro…</button>`;
    dn.innerHTML = `<span class="n">${esc(S.file.name)}</span><span class="t">${ext}</span>${b ? `<span class="d">${size}</span>` : ""}`;
  }
  hydrateIcons(card);
}

// ---------- 02 grupos: pluma + densidad ----------
const DENS_OPTS = [1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1];
function groupSpec(g) {
  const v = S.settings.density_map[g.key];
  if (v === undefined || v === null || v === "") return isNeutral(g.color) ? "auto" : 1;
  return v;
}
function renderGroups() {
  const box = $("#groups");
  const groups = S.plan ? S.plan.groups : [];
  if (!groups.length) { box.innerHTML = '<p class="muted">Sin elementos.</p>'; return; }
  const pens = S.meta.profiles.pens;
  box.innerHTML = groups.map((g, i) => {
    const pen = g.key in S.settings.pen_map ? S.settings.pen_map[g.key] : S.settings.default_pen;
    const penObj = pens.find((p) => p.name === pen);
    const popts = pens.map((p) => `<option ${p.name === pen ? "selected" : ""}>${esc(p.name)}</option>`).join("")
      + `<option value="" ${pen === "" ? "selected" : ""}>— Omitir —</option>`;
    const spec = groupSpec(g);
    const custom = spec !== "auto" && !DENS_OPTS.some((v) => Math.abs(v - spec) < 1e-6);
    const dopts = `<option value="auto" ${spec === "auto" ? "selected" : ""}>Auto · ${Math.round(g.tone * 100)} %</option>`
      + DENS_OPTS.map((v) => `<option value="${v}" ${!custom && Math.abs(v - spec) < 1e-6 ? "selected" : ""}>${v === 1 ? "Sólido · 100 %" : Math.round(v * 100) + " %"}</option>`).join("")
      + (custom ? `<option value="${spec}" selected>${Math.round(spec * 100)} %</option>` : "");
    const kinds = [g.kinds.stroke ? `${g.kinds.stroke} trazo${g.kinds.stroke > 1 ? "s" : ""}` : "",
      g.kinds.fill ? `${g.kinds.fill} relleno${g.kinds.fill > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ");
    return `<div class="grp${pen === "" ? " off" : ""}" data-key="${esc(g.key)}">
      <div class="grp-h">
        <span class="sw" title="Color en el archivo" style="background:${esc(g.color)}"></span>
        <span class="to">→</span>
        <span class="sw ink" title="Resultado aproximado con la pluma"><i style="background:${esc(penObj ? penObj.color : "#000")};opacity:${pen === "" ? 0 : g.density}"></i></span>
        <span class="k"><b title="${esc(g.key)}">${esc(g.key)}</b><small>${kinds}</small></span>
        <button class="ib" data-mv="-1" ${i === 0 ? "disabled" : ""} title="Dibujar antes"><i data-icon="up" data-size="16"></i></button>
        <button class="ib" data-mv="1" ${i === groups.length - 1 ? "disabled" : ""} title="Dibujar después"><i data-icon="down" data-size="16"></i></button>
      </div>
      <div class="grp-c">
        <select data-pen="${esc(g.key)}" title="Pluma">${popts}</select>
        <select data-dens="${esc(g.key)}" title="Densidad de tinta" ${pen === "" ? "disabled" : ""}>${dopts}</select>
      </div></div>`;
  }).join("");
  hydrateIcons(box);
  for (const sel of $$("[data-pen]", box)) sel.addEventListener("change", () => { S.settings.pen_map[sel.dataset.pen] = sel.value; saveLocal(); schedule(); });
  for (const sel of $$("[data-dens]", box)) {
    sel.addEventListener("change", () => {
      S.settings.density_map[sel.dataset.dens] = sel.value === "auto" ? "auto" : parseFloat(sel.value); saveLocal(); schedule();
    });
  }
  for (const b of $$("[data-mv]", box)) {
    b.addEventListener("click", () => {
      const keys = groups.map((g) => g.key);
      const i = keys.indexOf(b.closest(".grp").dataset.key), j = i + +b.dataset.mv;
      [keys[i], keys[j]] = [keys[j], keys[i]];
      S.settings.group_order = keys; saveLocal(); schedule();
    });
  }
}
function setupGroupsBulk() {
  const keys = () => (S.plan && S.plan.groups ? S.plan.groups.map((g) => g.key) : []);
  $("#allOnePen").addEventListener("click", () => { for (const k of keys()) S.settings.pen_map[k] = S.settings.default_pen; saveLocal(); schedule(); });
  $("#allAuto").addEventListener("click", () => { for (const k of keys()) S.settings.density_map[k] = "auto"; saveLocal(); schedule(); });
  $("#allSolid").addEventListener("click", () => { for (const k of keys()) S.settings.density_map[k] = 1; saveLocal(); schedule(); });
}

// ---------- inspector ----------
// el inspector recuerda su estado por separado en pantallas amplias y angostas (ahí inicia oculto)
const isNarrow = () => window.matchMedia("(max-width: 1180px)").matches;
const inspOn = () => (isNarrow() ? !!UI.inspNarrow : UI.insp);
function setInspector(on) {
  const narrow = isNarrow();
  if (narrow) UI.inspNarrow = on; else UI.insp = on;
  saveUI();
  $("#layout").classList.toggle("no-insp", !on && !narrow);
  $("#layout").classList.toggle("show-insp", on && narrow);
  $("#tInspector").classList.toggle("on", on);
  requestAnimationFrame(draw);
}
function renderInspector() {
  const p = S.plan;
  const cell = (k, v, full = false) => `<div class="${full ? "full" : ""}"><span class="k">${k}</span><span class="v${v === "—" ? " empty-v" : ""}">${v}</span></div>`;
  if (!p) {
    $("#cajetin").innerHTML = cell("Tiempo estimado", "—", true) + cell("Dibujo", "—") + cell("Viajes", "—")
      + cell("Levantadas", "—") + cell("Cambios", "—") + cell("Tamaño", "—") + cell("Escala", "—");
    $("#seq").innerHTML = '<li class="muted">—</li>';
    $("#warnings").innerHTML = '<p class="muted">Sin avisos.</p>';
    return;
  }
  const st = p.stats;
  const changes = S.settings.per_pen ? 0 : Math.max(0, p.jobs.length - 1);
  const b = p.design_bounds;
  const lines = p.files ? p.files.reduce((a, f) => a + f.lines, 0) : 0;
  $("#cajetin").innerHTML = cell("Tiempo estimado", st.time, true)
    + cell("Dibujo", fmtM(st.draw_mm)) + cell("Viajes", fmtM(st.travel_mm))
    + cell("Levantadas", st.lifts) + cell("Cambios de pluma", S.settings.per_pen ? `${p.files.length} archivos` : changes)
    + cell("Tamaño (mm)", b ? `${fmt(b[2] - b[0])} × ${fmt(b[3] - b[1])}` : "—")
    + cell("Escala", p.scale ? `${(p.scale * 100).toFixed(1)} %` : "—")
    + cell("Líneas G-code", lines ? lines.toLocaleString("es-MX") : "—")
    + cell("Archivo(s)", p.files ? p.files.length : "—");
  $("#seq").innerHTML = p.jobs.length ? p.jobs.map((j, i) => {
    const e = st.per_pen[i];
    const w = Math.max(1, Math.min(6, j.tip * 3));
    return `${i > 0 && !S.settings.per_pen ? '<li><span></span><span class="chg">pausa · cambio de pluma</span></li>' : ""}
      <li><span class="chip sm">${i + 1}</span>
      <span class="pn"><b>${esc(j.pen)}</b><small><span class="smp"><i style="height:${w}px;background:${esc(j.color)}"></i></span>${j.tip} mm · ${j.paths.length} trazos</small></span>
      <span class="t">${e ? fmtS(e.seconds) : ""}</span></li>`;
  }).join("") : '<li class="muted">Ninguna pluma asignada.</li>';
  const w = p.warnings || [];
  $("#warnings").innerHTML = w.length
    ? w.map((x) => `<div class="callout warn" data-tab="PRECAUCIÓN">${esc(x)}</div>`).join("")
    : `<div class="callout ok" data-tab="LISTO">${S.calibration ? "Patrón de calibración listo para descargar." : "Sin avisos. El G-code está listo para generarse."}</div>`;
}

// ---------- archivo ----------
async function openFile(f) {
  const fd = new FormData(); fd.append("file", f);
  busy(true, "Leyendo archivo…");
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    S.file = await r.json();
    S.file.viewable = /\.(svg|png|jpe?g|gif|webp|bmp)$/i.test(S.file.name);
    S.plan = null; S.calibration = false; S.orig = null;
    S.settings.layout.offset_x = 0; S.settings.layout.offset_y = 0; writeAll();
    $("#empty").hidden = true;
    refreshUI(); renderFile();
    await replan();
  } catch (e) { toast(e.message); } finally { busy(false); }
}
function openDialog() { $("#file").value = ""; $("#file").click(); }
async function generate() {
  if (!S.file) return;
  busy(true, "Generando G-code…");
  try {
    const r = await api("/api/gcode", { file_id: S.file.file_id, settings: S.settings }, true);
    const name = await saveBlob(r);
    toast(`${name} descargado. Cópielo a la tarjeta SD.`, "ok");
  } catch (e) { toast(e.message); } finally { busy(false); }
}
function setupFile() {
  $("#file").addEventListener("change", (e) => e.target.files[0] && openFile(e.target.files[0]));
  document.addEventListener("click", (e) => { if (e.target.closest("[data-action=open]")) openDialog(); });
  $("#btnOpen").addEventListener("click", openDialog);
  const view = $("#view"), drop = $("#drop");
  let depth = 0;
  view.addEventListener("dragenter", (e) => { e.preventDefault(); depth++; drop.hidden = false; });
  view.addEventListener("dragover", (e) => e.preventDefault());
  view.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; drop.hidden = true; } });
  view.addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; drop.hidden = true;
    if (e.dataTransfer.files[0]) openFile(e.dataTransfer.files[0]);
  });
  $("#btnGen").addEventListener("click", generate);
}
async function saveBlob(r) {
  const cd = r.headers.get("Content-Disposition") || "";
  const name = (cd.match(/filename="([^"]+)"/) || [])[1] || "trazo.gcode";
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return name;
}
function setupKeys() {
  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest("input, select, textarea");
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") { e.preventDefault(); openDialog(); return; }
    if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "g" || e.key.toLowerCase() === "s")) { e.preventDefault(); generate(); return; }
    if (typing || $("dialog[open]")) return;
    if (e.key === "f" || e.key === "F") { fitView(); draw(); }
    else if (e.key === "1") zoomTo(PX_PER_MM);
    else if (e.key === "+" || e.key === "=") zoomBy(1.25);
    else if (e.key === "-") zoomBy(0.8);
    else if (e.key === " ") { e.preventDefault(); togglePlay(); }
  });
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
  const W = c.clientWidth, H = c.clientHeight;
  const L = RULER + 30, R = 30, T = RULER + 56, B = 62;
  const k = Math.max(0.2, Math.min((W - L - R) / (x1 - x0), (H - T - B) / (y1 - y0)));
  S.view = { k, ox: L + (W - L - R - (x1 - x0) * k) / 2 - x0 * k, oy: T + (H - T - B + (y1 - y0) * k) / 2 + y0 * k };
  updateZoom();
}
function zoomBy(f, cx, cy) {
  const c = cv(), v = S.view;
  cx ??= c.clientWidth / 2; cy ??= c.clientHeight / 2;
  v.ox = cx - (cx - v.ox) * f; v.oy = cy - (cy - v.oy) * f; v.k *= f;
  updateZoom(); draw();
}
function zoomTo(k) { zoomBy(k / S.view.k); }
function updateZoom() { $("#zoom100").textContent = `${Math.round((S.view.k / PX_PER_MM) * 100)} %`; }
function toWorld(e) {
  const r = cv().getBoundingClientRect(), v = S.view;
  return [(e.clientX - r.left - v.ox) / v.k, (v.oy - (e.clientY - r.top)) / v.k];
}
function inDesign(x, y) {
  const b = S.plan && !S.calibration ? S.plan.design_bounds : null;
  return !!b && x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];
}
function setupCanvas() {
  const c = cv();
  new ResizeObserver(() => { if (!S.view) fitView(); draw(); }).observe(c);
  c.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = c.getBoundingClientRect();
    zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
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
    S.cursor = [x, y];
    const m = prof("machines", S.settings.machine);
    $("#coords").textContent = `X ${fmt(x)}  Y ${fmt(y)} mm`;
    $("#nozzle").textContent = `boquilla X ${fmt(x - m.pen_offset_x)}  Y ${fmt(y - m.pen_offset_y)}`;
    const d = S.drag;
    if (!d) {
      const h = inDesign(x, y);
      c.style.cursor = h ? "move" : "grab";
      if (h !== S.hover) S.hover = h;
      draw(); return;
    }
    if (d.move) { d.dx = (e.clientX - d.sx) / S.view.k; d.dy = -(e.clientY - d.sy) / S.view.k; }
    else { S.view.ox += e.clientX - d.x; S.view.oy += e.clientY - d.y; }
    d.x = e.clientX; d.y = e.clientY; draw();
  });
  c.addEventListener("pointerup", () => {
    const d = S.drag; S.drag = null; c.style.cursor = "grab";
    if (d && d.move && (Math.abs(d.dx) > 0.05 || Math.abs(d.dy) > 0.05)) {
      const L = S.settings.layout;
      L.offset_x = +((L.offset_x || 0) + d.dx).toFixed(1);
      L.offset_y = +((L.offset_y || 0) + d.dy).toFixed(1);
      shiftPlan(d.dx, d.dy);
      changed();
    }
    draw();
  });
  c.addEventListener("pointerleave", () => { S.cursor = null; S.hover = false; $("#coords").textContent = "X —  Y —"; $("#nozzle").textContent = ""; draw(); });
  $("#fitView").addEventListener("click", () => { fitView(); draw(); });
  $("#zoomIn").addEventListener("click", () => zoomBy(1.25));
  $("#zoomOut").addEventListener("click", () => zoomBy(0.8));
  $("#zoom100").addEventListener("click", () => zoomTo(PX_PER_MM));
  const tog = (id, key) => $(id).addEventListener("click", () => { UI[key] = !UI[key]; $(id).classList.toggle("on", UI[key]); saveUI(); draw(); });
  tog("#tWidth", "width"); tog("#tTravel", "travel"); tog("#tOrig", "orig");
  $("#tInspector").addEventListener("click", () => setInspector(!inspOn()));
  $("#progress").addEventListener("input", draw);
  $("#play").addEventListener("click", togglePlay);
}
function shiftPlan(dx, dy) {
  const p = S.plan; if (!p) return;
  for (const j of p.jobs) for (const q of j.paths) for (let i = 0; i < q.length; i += 2) { q[i] += dx; q[i + 1] += dy; }
  if (p.design_bounds) p.design_bounds = [p.design_bounds[0] + dx, p.design_bounds[1] + dy, p.design_bounds[2] + dx, p.design_bounds[3] + dy];
  if (p.matrix) { p.matrix[0][2] += dx; p.matrix[1][2] += dy; }
}
function togglePlay() {
  if (!S.plan || !S.plan.jobs.length) return;
  const r = $("#progress"), btn = $("#play");
  const setIcon = (n) => { btn.innerHTML = `<i data-icon="${n}"></i>`; hydrateIcons(btn); };
  if (S.anim) { cancelAnimationFrame(S.anim); S.anim = null; setIcon("play"); return; }
  if (+r.value >= 1000) r.value = 0;
  setIcon("pause");
  let last = performance.now();
  const step = (t) => {
    r.value = Math.min(1000, +r.value + (t - last) / 8); last = t; draw();
    if (+r.value >= 1000) { S.anim = null; setIcon("play"); return; }
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
function niceStep(k, minPx) {
  for (const s of [1, 2, 5, 10, 20, 25, 50, 100, 200, 500]) if (s * k >= minPx) return s;
  return 1000;
}

function draw() {
  const c = cv(); if (!S.view || !S.meta) return;
  const dpr = window.devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight;
  if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
  const g = c.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const col = {
    fondo: css("--cv-fondo"), cama: css("--cv-cama"), reja: css("--cv-reja"), reja2: css("--cv-reja2"), borde: css("--cv-borde"),
    hoja: css("--cv-hoja"), texto: css("--cv-texto"), cota: css("--cv-cota"), viaje: css("--cv-viaje"), panel: css("--fondo"),
    linea: css("--linea"), tinta: css("--tinta-2"), azul: "#00476A",
  };
  g.fillStyle = col.fondo; g.fillRect(0, 0, W, H);
  const { k, ox, oy } = S.view;
  const X = (x) => ox + x * k, Y = (y) => oy - y * k;
  const rect = (b) => [X(b[0]), Y(b[3]), (b[2] - b[0]) * k, (b[3] - b[1]) * k];
  const crisp = (v) => Math.round(v) + 0.5;
  const { m, bed, reach } = machineBox();
  const mat = prof("materials", S.settings.material);
  const mono = (px) => `${px}px "IBM Plex Mono", Consolas, monospace`;

  // cama con cuadrícula de 10 mm (50 mm marcada)
  g.fillStyle = col.cama; g.fillRect(...rect(bed));
  g.lineWidth = 1;
  for (const [step, color] of [[10, col.reja], [50, col.reja2]]) {
    if (step * k < 6) continue;
    g.strokeStyle = color; g.beginPath();
    for (let x = Math.ceil(bed[0] / step) * step; x <= bed[2]; x += step) { g.moveTo(crisp(X(x)), Y(bed[1])); g.lineTo(crisp(X(x)), Y(bed[3])); }
    for (let y = Math.ceil(bed[1] / step) * step; y <= bed[3]; y += step) { g.moveTo(X(bed[0]), crisp(Y(y))); g.lineTo(X(bed[2]), crisp(Y(y))); }
    g.stroke();
  }
  g.strokeStyle = col.borde; g.strokeRect(...rect(bed).map((v, i) => (i < 2 ? crisp(v) : Math.round(v))));
  g.setLineDash([5, 4]); g.strokeStyle = col.borde; g.globalAlpha = 0.6; g.strokeRect(...rect(reach)); g.globalAlpha = 1; g.setLineDash([]);
  // material: hoja blanca con filete (sin sombra)
  const mb = [mat.origin_x, mat.origin_y, mat.origin_x + mat.width, mat.origin_y + mat.height];
  g.fillStyle = col.hoja; g.fillRect(...rect(mb));
  g.strokeStyle = col.borde; g.strokeRect(...rect(mb).map((v, i) => (i < 2 ? crisp(v) : Math.round(v))));
  const area = S.plan ? S.plan.drawable : null;
  if (area) { g.setLineDash([4, 3]); g.strokeStyle = col.cota; g.strokeRect(...rect(area)); g.setLineDash([]); }
  g.font = mono(10); g.fillStyle = col.texto; g.textBaseline = "alphabetic";
  g.fillText(`${m.name.toUpperCase()} · ${bed[2] - bed[0]} × ${bed[3] - bed[1]} mm`, X(bed[0]), Y(bed[3]) - 6);
  if (Y(mb[3]) - 6 > Y(bed[3]) + 14) g.fillText(`${mat.name} · ${mat.width} × ${mat.height} mm`, X(mb[0]), Y(mb[3]) - 6);
  // origen
  g.strokeStyle = col.cota; g.beginPath();
  g.moveTo(X(0) - 6, Y(0)); g.lineTo(X(0) + 6, Y(0)); g.moveTo(X(0), Y(0) - 6); g.lineTo(X(0), Y(0) + 6); g.stroke();

  if (S.plan) {
    const d = S.drag && S.drag.move ? S.drag : { dx: 0, dy: 0 };
    const DX = (x) => X(x + d.dx), DY = (y) => Y(y + d.dy);
    // original superpuesto
    const img = UI.orig && S.plan.extent && S.plan.matrix ? origImage() : null;
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
    // trayectorias
    const total = S.plan.jobs.reduce((a, j) => a + j.paths.length, 0);
    let left = Math.round(total * $("#progress").value / 1000);
    const shown = left;
    let px = m.park_x + m.pen_offset_x, py = m.park_y + m.pen_offset_y, curPen = "";
    g.lineCap = "round"; g.lineJoin = "round";
    for (const j of S.plan.jobs) {
      if (left <= 0) break;
      const n = Math.min(left, j.paths.length); left -= n; curPen = j.pen;
      g.strokeStyle = j.color;
      g.lineWidth = UI.width ? Math.max(j.tip * k, 0.6) : 1;
      g.beginPath();
      for (let i = 0; i < n; i++) {
        const p = j.paths[i];
        g.moveTo(DX(p[0]), DY(p[1]));
        if (p.length === 2) g.lineTo(DX(p[0]) + 0.01, DY(p[1]));
        for (let q = 2; q < p.length; q += 2) g.lineTo(DX(p[q]), DY(p[q + 1]));
      }
      g.stroke();
      if (UI.travel) {
        g.beginPath(); g.strokeStyle = col.viaje; g.lineWidth = 1; g.setLineDash([3, 3]);
        for (let i = 0; i < n; i++) {
          const p = j.paths[i];
          g.moveTo(DX(px), DY(py)); g.lineTo(DX(p[0]), DY(p[1]));
          px = p[p.length - 2]; py = p[p.length - 1];
        }
        g.stroke(); g.setLineDash([]);
      } else { const p = j.paths[n - 1]; px = p[p.length - 2]; py = p[p.length - 1]; }
    }
    $("#progLabel").textContent = total ? `${shown.toLocaleString("es-MX")} / ${total.toLocaleString("es-MX")} trazos${curPen ? " · " + curPen : ""}` : "";
    if (+$("#progress").value < 1000 && total) {   // posición de la pluma
      const x = DX(px), y = DY(py);
      g.strokeStyle = col.azul; g.lineWidth = 1.5; g.beginPath();
      g.moveTo(x - 9, y); g.lineTo(x - 3, y); g.moveTo(x + 3, y); g.lineTo(x + 9, y);
      g.moveTo(x, y - 9); g.lineTo(x, y - 3); g.moveTo(x, y + 3); g.lineTo(x, y + 9); g.stroke();
      g.strokeRect(x - 3, y - 3, 6, 6);
    }
    // caja del diseño con cotas
    const db = S.plan.design_bounds;
    if (db && !S.calibration && (S.hover || (S.drag && S.drag.move))) {
      const bb = [db[0] + d.dx, db[1] + d.dy, db[2] + d.dx, db[3] + d.dy];
      const [rx, ry, rw, rh] = rect(bb);
      g.strokeStyle = col.cota; g.lineWidth = 1.5; g.strokeRect(rx, ry, rw, rh);
      g.lineWidth = 1; g.font = mono(11);
      const label = (txt, x, y, rot = 0) => {
        g.save(); g.translate(x, y); g.rotate(rot);
        const w = g.measureText(txt).width + 8;
        g.fillStyle = col.panel; g.fillRect(-w / 2, -8, w, 16);
        g.fillStyle = col.cota; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(txt, 0, 0.5);
        g.restore();
      };
      const yT = ry - 16, xL = rx - 16;
      g.beginPath();
      g.moveTo(rx, yT); g.lineTo(rx + rw, yT); g.moveTo(rx, yT - 5); g.lineTo(rx, ry - 3); g.moveTo(rx + rw, yT - 5); g.lineTo(rx + rw, ry - 3);
      g.moveTo(xL, ry); g.lineTo(xL, ry + rh); g.moveTo(xL - 5, ry); g.lineTo(rx - 3, ry); g.moveTo(xL - 5, ry + rh); g.lineTo(rx - 3, ry + rh);
      g.stroke();
      label(`${fmt(bb[2] - bb[0])} mm`, rx + rw / 2, yT);
      label(`${fmt(bb[3] - bb[1])} mm`, xL, ry + rh / 2, -Math.PI / 2);
      g.font = mono(10.5); g.fillStyle = col.cota; g.textAlign = "left"; g.textBaseline = "top";
      g.fillText(`X ${fmt(bb[0])}  Y ${fmt(bb[1])}`, rx, ry + rh + 6);
      g.textBaseline = "alphabetic";
    }
  }
  drawRulers(g, W, H, X, Y, col, mono);
}

function drawRulers(g, W, H, X, Y, col, mono) {
  const { k } = S.view;
  const minor = niceStep(k, 7), major = niceStep(k, 56);
  g.fillStyle = col.panel; g.fillRect(0, 0, W, RULER); g.fillRect(0, 0, RULER, H);
  g.strokeStyle = col.linea; g.lineWidth = 1; g.beginPath();
  g.moveTo(0, RULER - 0.5); g.lineTo(W, RULER - 0.5); g.moveTo(RULER - 0.5, 0); g.lineTo(RULER - 0.5, H); g.stroke();
  g.strokeStyle = col.texto; g.fillStyle = col.texto; g.font = mono(9.5); g.beginPath();
  const x0 = Math.floor(((RULER - S.view.ox) / k) / minor) * minor, x1 = (W - S.view.ox) / k;
  for (let x = x0; x <= x1; x += minor) {
    const sx = Math.round(X(x)) + 0.5; if (sx < RULER) continue;
    const isMaj = Math.abs(x / major - Math.round(x / major)) < 1e-6;
    g.moveTo(sx, RULER); g.lineTo(sx, RULER - (isMaj ? 9 : 4));
    if (isMaj) { g.textAlign = "left"; g.fillText(String(Math.round(x)), sx + 3, 10); }
  }
  const y0 = Math.floor(((S.view.oy - H) / k) / minor) * minor, y1 = (S.view.oy - RULER) / k;
  for (let y = y0; y <= y1; y += minor) {
    const sy = Math.round(Y(y)) + 0.5; if (sy < RULER) continue;
    const isMaj = Math.abs(y / major - Math.round(y / major)) < 1e-6;
    g.moveTo(RULER, sy); g.lineTo(RULER - (isMaj ? 9 : 4), sy);
    if (isMaj) { g.save(); g.translate(10, sy - 3); g.rotate(-Math.PI / 2); g.textAlign = "left"; g.fillText(String(Math.round(y)), 0, 0); g.restore(); }
  }
  g.stroke();
  if (S.cursor) {   // posición del cursor en las reglas
    g.strokeStyle = col.cota; g.lineWidth = 1.5; g.beginPath();
    const cx = X(S.cursor[0]), cy = Y(S.cursor[1]);
    if (cx > RULER) { g.moveTo(cx, 0); g.lineTo(cx, RULER); }
    if (cy > RULER) { g.moveTo(0, cy); g.lineTo(RULER, cy); }
    g.stroke();
  }
  g.fillStyle = col.panel; g.fillRect(0, 0, RULER, RULER);
  g.fillStyle = col.texto; g.font = mono(8.5); g.textAlign = "center"; g.fillText("mm", RULER / 2, 13);
  g.textAlign = "left";
}

// ---------- perfiles (ficha técnica) ----------
const FORM = {
  machines: [
    ["Identificación", ["name", "flavor"]],
    ["Recorrido de la boquilla", ["x_min", "x_max", "y_min", "y_max", "z_max"]],
    ["Pluma y contacto", ["pen_offset_x", "pen_offset_y", "contact_mode", "nozzle_clearance", "contact_z_fixed", "pen_lift", "pen_press", "safe_z_lift"]],
    ["Movimiento", ["travel_feed", "z_feed", "acceleration", "home", "park_x", "park_y"]],
    ["Firmware", ["pause_cmd", "message_cmd", "max_message_len", "disable_heaters", "decimals"]],
    ["G-code personalizado", ["start_gcode", "end_gcode"]],
  ],
  pens: [["Pluma", ["name", "color", "tip", "draw_feed", "overlap", "dwell_ms", "press"]]],
  materials: [["Material", ["name", "width", "height", "thickness"]], ["Posición en la cama", ["origin_x", "origin_y", "margin"]], ["Velocidad", ["speed_factor"]]],
};
const UNITS = {
  x_min: "mm", x_max: "mm", y_min: "mm", y_max: "mm", z_max: "mm", pen_offset_x: "mm", pen_offset_y: "mm", nozzle_clearance: "mm",
  contact_z_fixed: "mm", pen_lift: "mm", pen_press: "mm", safe_z_lift: "mm", travel_feed: "mm/min", z_feed: "mm/min",
  acceleration: "mm/s²", park_x: "mm", park_y: "mm", max_message_len: "car.", tip: "mm", draw_feed: "mm/min", overlap: "0–0.9",
  dwell_ms: "ms", press: "mm", width: "mm", height: "mm", thickness: "mm", origin_x: "mm", origin_y: "mm", margin: "mm", speed_factor: "×",
};
const KIND = { machines: ["MÁQUINA", "Perfiles de máquina", "machine"], pens: ["PLUMA", "Plumas", "default_pen"], materials: ["MATERIAL", "Materiales", "material"] };
let dlgKind = null, dlgName = null;
function setupDialogs() {
  for (const b of $$("[data-edit]")) b.addEventListener("click", () => openProfiles(b.dataset.edit));
  $("#dlgClose").addEventListener("click", () => $("#dlg").close());
  $("#dlgSave").addEventListener("click", () => saveProfile(collectProfile()));
  $("#dlgDup").addEventListener("click", () => { const p = collectProfile(); p.name += " (copia)"; saveProfile(p); });
  $("#dlgDelete").addEventListener("click", async () => {
    const p = prof(dlgKind, dlgName);
    const msg = p._builtin ? `¿Restablecer «${dlgName}» a sus valores integrados?` : `¿Eliminar el perfil «${dlgName}»?`;
    if (!confirm(msg)) return;
    await fetch(`/api/profiles/${dlgKind}/${encodeURIComponent(dlgName)}`, { method: "DELETE" });
    await afterProfileChange(null);
  });
  for (const b of $$("dialog [data-close]")) b.addEventListener("click", () => b.closest("dialog").close());
  for (const d of $$("dialog")) d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
  $("#btnCal").addEventListener("click", () => { $("#calPen").value = S.settings.default_pen; $("#calDlg").showModal(); });
  $("#btnAbout").addEventListener("click", () => $("#aboutDlg").showModal());
  $("#calPreview").addEventListener("click", () => { $("#calDlg").close(); S.calibration = true; calPreview(); });
  $("#calDownload").addEventListener("click", async () => {
    try {
      const r = await api("/api/calibration", { ...calBody(), download: true }, true);
      const name = await saveBlob(r); $("#calDlg").close(); toast(`${name} descargado.`, "ok");
    } catch (e) { toast(e.message); }
  });
}
function calBody() { return { machine: S.settings.machine, material: S.settings.material, pen: $("#calPen").value }; }
async function calPreview() {
  try {
    busy(true);
    S.plan = await api("/api/calibration", calBody());
    S.plan.groups = []; S.plan.design_bounds = null;
    $("#empty").hidden = true;
    renderInspector(); refreshUI(); draw();
  } catch (e) { toast(e.message); } finally { busy(false); }
}
function openProfiles(kind) {
  dlgKind = kind;
  dlgName = S.settings[KIND[kind][2]];
  $("#dlgKind").textContent = "PERFIL · " + KIND[kind][0];
  $("#dlgTitle").textContent = KIND[kind][1];
  renderProfileList(); renderProfileForm(prof(kind, dlgName));
  $("#dlg").showModal();
}
function renderProfileList() {
  const list = S.meta.profiles[dlgKind];
  $("#plist").innerHTML = list.map((p) => `<button data-name="${esc(p.name)}" class="${p.name === dlgName ? "on" : ""}">
    ${dlgKind === "pens" ? `<span class="sw" style="background:${esc(p.color)}"></span>` : ""}
    <span>${esc(p.name)}</span><span class="tag">${p._builtin ? "INTEGRADO" : "PROPIO"}</span></button>`).join("");
  for (const b of $$("#plist button")) {
    b.addEventListener("click", () => { dlgName = b.dataset.name; renderProfileList(); renderProfileForm(prof(dlgKind, dlgName)); });
  }
}
function renderProfileForm(p) {
  const fields = S.meta.fields[dlgKind];
  $("#dlgNote").textContent = p._builtin ? "Perfil integrado: al guardar se crea su versión propia." : "Perfil propio.";
  $("#dlgDelete").innerHTML = `<i data-icon="${p._builtin ? "reset" : "trash"}"></i>${p._builtin ? "Restablecer" : "Eliminar"}`;
  hydrateIcons($("#dlgDelete"));
  const field = (k) => {
    const info = fields[k]; if (!info) return "";
    const [label, help, choices] = info, v = p[k];
    let input;
    if (choices) input = `<select data-f="${k}">${choices.map((c) => `<option ${c === v ? "selected" : ""}>${c}</option>`).join("")}</select>`;
    else if (typeof v === "boolean") input = `<label class="ck"><input type="checkbox" data-f="${k}" ${v ? "checked" : ""}>activado</label>`;
    else if (k.endsWith("_gcode")) input = `<textarea data-f="${k}" spellcheck="false">${esc(v || "")}</textarea>`;
    else if (k === "color") input = `<input type="color" data-f="${k}" value="${esc(v)}">`;
    else if (typeof v === "number" || v === null) input = `<div class="num"><input type="number" step="any" data-f="${k}" data-num="1" value="${v ?? ""}" placeholder="—"><span class="u">${UNITS[k] || ""}</span></div>`;
    else input = `<input type="text" data-f="${k}" value="${esc(v)}" ${k.endsWith("_cmd") ? 'class="mono"' : ""}>`;
    return `<div class="f"><label>${esc(label)}</label>${input}${help ? `<p class="help">${esc(help)}</p>` : ""}</div>`;
  };
  $("#dlgBody").innerHTML = FORM[dlgKind].map(([title, keys]) => `<h4>${title}</h4>${keys.map(field).join("")}`).join("");
}
function collectProfile() {
  const out = {};
  for (const el of $$("[data-f]", $("#dlgBody"))) {
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
    toast(`Perfil «${p.name}» guardado.`, "ok");
  } catch (e) { toast(e.message); }
}
async function afterProfileChange(name) {
  await loadMeta();
  const key = KIND[dlgKind][2], list = S.meta.profiles[dlgKind];
  if (name && list.some((p) => p.name === name)) S.settings[key] = name;
  if (!list.some((p) => p.name === S.settings[key])) S.settings[key] = list[0].name;
  dlgName = name && list.some((p) => p.name === name) ? name : S.settings[key];
  writeAll(); renderProfileList(); renderProfileForm(prof(dlgKind, dlgName));
  refreshUI(); fitView(); schedule(); draw();
}

window.addEventListener("resize", () => setInspector(inspOn()));
init().catch((e) => toast("Error al iniciar: " + e.message));
