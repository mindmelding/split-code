const state = {
  window: "90",
  sort: "momentum",
  body: "",
  vehicle: "",
  failure: "",
  mode: "exploded",
  key: "",
  part: "",
  scrub: null,
};

let facets = null;
let payload = null;
let clusters = [];
let shown = { type: null, powertrain: null };
let sequence = 0;
let loadToken = 0;
let searchTimer = 0;

const $ = (selector) => document.querySelector(selector);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const BODY_ORDER = ["sedan", "crossover", "suv", "pickup", "minivan", "fastback"];

function dateLabel(value) {
  if (!value || value.length !== 8) return value || "";
  return `${Number(value.slice(6))} ${MONTHS[Number(value.slice(4, 6)) - 1]} ${value.slice(0, 4)}`;
}

function title(value) {
  return String(value)
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\bEv\b/g, "EV")
    .replace(/\bGmc\b/g, "GMC")
    .replace(/\bBmw\b/g, "BMW");
}

function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function keyOf(cluster) {
  return `${cluster.year}|${cluster.make}|${cluster.model}|${cluster.failure}`;
}

function signed(value) {
  return value > 0 ? `↑${value}` : value < 0 ? `↓${Math.abs(value)}` : "±0";
}

// Data

async function load() {
  const token = ++loadToken;
  document.body.classList.add("loading");
  const query = new URLSearchParams({ window: state.window, sort: state.sort });
  if (state.body) query.set("body", state.body);
  if (state.vehicle) query.set("vehicle", state.vehicle);
  if (state.part) query.set("failures", Cutaway.failuresForPart(state.part).join(","));
  else if (state.failure) query.set("failure", state.failure);
  if (facets) query.set("include_facets", "0");
  try {
    const response = await fetch(`/api/query?${query}`);
    if (!response.ok) throw new Error(`Query failed (${response.status})`);
    const data = await response.json();
    if (token !== loadToken) return;
    payload = data;
  } catch (error) {
    if (token !== loadToken) return;
    $("#signals").innerHTML = `<li class="empty">${escapeHtml(error.message)}</li>`;
    document.body.classList.remove("loading");
    return;
  }
  if (payload.facets) {
    facets = payload.facets;
    renderFacets();
  }
  clusters = payload.clusters;
  if (!clusters.some((cluster) => keyOf(cluster) === state.key)) {
    state.key = clusters[0] ? keyOf(clusters[0]) : "";
  }
  renderRail();
  renderColophon();
  select(state.key);
  document.body.classList.remove("loading");
}

// Filters

function renderFacets() {
  const counts = new Map(facets.bodies.map((row) => [row.id, row]));
  const chip = (id, label, count) => {
    const icon = id
      ? `<svg viewBox="40 120 930 290" aria-hidden="true"><path d="${Cutaway.outline(id)}"/></svg>`
      : "";
    return `<button type="button" class="chip${state.body === id ? " on" : ""}" data-body="${id}">
      ${icon}${label}${count ? ` <small>${count.toLocaleString()}</small>` : ""}</button>`;
  };
  $("#bodies").innerHTML =
    chip("", "All vehicles") +
    BODY_ORDER.filter((id) => counts.has(id))
      .map((id) => chip(id, counts.get(id).label, counts.get(id).count))
      .join("");

  const failures = facets.failures.filter((row) => row.id !== "other");
  $("#failure").innerHTML =
    `<option value="">Any failure</option>` +
    failures.map((row) => `<option value="${row.id}">${escapeHtml(row.label)}</option>`).join("");
  $("#failure").value = state.failure;

  $("#vehicles").innerHTML = facets.vehicles.map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
}

function syncChips() {
  document.querySelectorAll("#bodies .chip").forEach((chip) => chip.classList.toggle("on", chip.dataset.body === state.body));
}

function renderActivePart() {
  $("#activePart").innerHTML = state.part
    ? `<button type="button" class="chip on part-chip" id="clearPart" title="Clear part filter">Part · ${escapeHtml(Cutaway.LABELS[state.part])} <span aria-hidden="true">✕</span></button>`
    : "";
}

function sparkline(weekly) {
  const recent = (weekly || []).slice(-12);
  const max = Math.max(1, ...recent.map((week) => week.n));
  const width = 5;
  return `<svg class="spark" viewBox="0 0 ${recent.length * width} 18" aria-hidden="true">${recent
    .map((week, i) => {
      const h = Math.max(1, (week.n / max) * 18);
      return `<rect x="${i * width}" y="${18 - h}" width="${width - 1.4}" height="${h}" class="${i >= recent.length - 4 ? "hot" : ""}"/>`;
    })
    .join("")}</svg>`;
}

// Rail

function renderRail() {
  const list = $("#signals");
  const suffix = state.part ? ` · ${Cutaway.LABELS[state.part]}` : "";
  $("#railCount").textContent = `${clusters.length} signal${clusters.length === 1 ? "" : "s"}${suffix}`;
  if (!clusters.length) {
    list.innerHTML = `<li class="empty">No signal in this cut yet. The descriptions have not agreed on anything. Widen the window or clear a filter.</li>`;
    return;
  }
  list.innerHTML = clusters
    .map((cluster, index) => {
      const key = keyOf(cluster);
      return `<li><button type="button" class="signal${key === state.key ? " on" : ""}" data-key="${escapeHtml(key)}">
        <span class="rank">${String(index + 1).padStart(2, "0")}</span>
        <span class="who">${escapeHtml(title(cluster.vehicle))}</span>
        <span class="trend">${sparkline(cluster.weekly)}</span>
        <span class="num">${cluster.count}</span>
        <span class="what">${escapeHtml(cluster.headline)}</span>
        <span class="delta">${signed(cluster.momentum)} 30d</span>
      </button></li>`;
    })
    .join("");
}

function markRail() {
  document.querySelectorAll(".signal").forEach((button) => {
    const on = button.dataset.key === state.key;
    button.classList.toggle("on", on);
    if (on) button.scrollIntoView({ block: "nearest" });
  });
}

// Selection

function select(key, options = {}) {
  state.key = key;
  state.scrub = null;
  const cluster = clusters.find((item) => keyOf(item) === key) || null;
  markRail();
  renderHead(cluster);
  renderReadout(cluster);
  renderTimeline(cluster);
  showDrawing(cluster, options.replay);
}

function currentCluster() {
  return clusters.find((item) => keyOf(item) === state.key) || null;
}

// Timeline

function weekEnd(start) {
  const date = new Date(Number(start.slice(0, 4)), Number(start.slice(4, 6)) - 1, Number(start.slice(6)) + 6);
  return `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, "0")}${String(date.getDate()).padStart(2, "0")}`;
}

function renderTimeline(cluster) {
  const chart = $("#timeline");
  const weekly = cluster?.weekly || [];
  if (!weekly.length) {
    chart.innerHTML = "";
    $("#scrubLabel").textContent = "Weekly complaints";
    $("#scrubNow").hidden = true;
    return;
  }
  const count = weekly.length;
  const slot = 1000 / count;
  const max = Math.max(1, ...weekly.map((week) => week.n));
  const index = state.scrub ?? count - 1;
  let months = "";
  let lastMonth = "";
  weekly.forEach((week, i) => {
    const month = week.start.slice(4, 6);
    if (month !== lastMonth) {
      months += `<text x="${i * slot + 2}" y="68">${MONTHS[Number(month) - 1]}</text>`;
      lastMonth = month;
    }
  });
  const bars = weekly
    .map((week, i) => {
      const h = week.n ? Math.max(2, (week.n / max) * 44) : 0;
      return `<rect class="bar${i > index ? " future" : ""}" x="${i * slot + 2}" y="${52 - h}" width="${slot - 4}" height="${h}"><title>Week of ${dateLabel(week.start)} · ${week.n}</title></rect>`;
    })
    .join("");
  const handleX = (index + 1) * slot - 1;
  chart.innerHTML = `<svg viewBox="0 0 1000 72">
      <rect class="recent" x="${(count - 4.3) * slot}" y="0" width="${4.3 * slot}" height="54"/>
      <text class="recent-label" x="${1000 - 4}" y="10" text-anchor="end">Latest 30 days</text>
      ${bars}
      <line class="baseline" x1="0" y1="52.5" x2="1000" y2="52.5"/>
      ${months}
      <line class="handle" x1="${handleX}" y1="0" x2="${handleX}" y2="56"/>
      <rect class="knob" x="${handleX - 5}" y="52" width="10" height="8" rx="2"/>
    </svg>`;

  const total = weekly.reduce((sum, week) => sum + week.n, 0);
  const upTo = weekly.slice(0, index + 1).reduce((sum, week) => sum + week.n, 0);
  $("#scrubLabel").textContent =
    state.scrub === null
      ? `Weekly complaints · last 26 weeks · ${total} total — drag to go back`
      : `Through ${dateLabel(weekEnd(weekly[index].start))} · ${upTo} of ${total} complaints`;
  $("#scrubNow").hidden = state.scrub === null;
  chart.setAttribute("aria-valuemin", "0");
  chart.setAttribute("aria-valuemax", String(count - 1));
  chart.setAttribute("aria-valuenow", String(index));
}

function calloutCluster(cluster) {
  if (state.scrub === null || !cluster.weekly) return cluster;
  const counts = new Map();
  cluster.weekly.slice(0, state.scrub + 1).forEach((week) => {
    for (const [name, count] of Object.entries(week.filed)) counts.set(name, (counts.get(name) || 0) + count);
  });
  const filed = [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  return { ...cluster, filed_components: filed };
}

function scrubTo(index) {
  const cluster = currentCluster();
  if (!cluster?.weekly?.length) return;
  const last = cluster.weekly.length - 1;
  const clamped = Math.max(0, Math.min(last, index));
  const next = clamped === last ? null : clamped;
  if (next === state.scrub) return;
  state.scrub = next;
  renderTimeline(cluster);
  const svg = $("#drawing svg");
  if (!svg) return;
  const total = cluster.weekly.reduce((sum, week) => sum + week.n, 0);
  const upTo = cluster.weekly.slice(0, clamped + 1).reduce((sum, week) => sum + week.n, 0);
  svg.style.setProperty("--share", next === null || !total ? 1 : upTo / total);
  if (svg.classList.contains("exploded") && svg.querySelector(".callouts").childElementCount) {
    drawCallouts(svg, calloutCluster(cluster));
  }
}

function renderHead(cluster) {
  const bodyLabel = (id) => (facets?.bodies.find((row) => row.id === id)?.label || id || "Vehicle");
  if (!cluster) {
    $("#fig").textContent = `Fig. 00 — ${bodyLabel(state.body || "crossover")} · side elevation`;
    $("#vehicleName").textContent = "No signal";
    $("#failureName").textContent = "Nothing in this cut has agreed yet.";
    return;
  }
  const index = clusters.indexOf(cluster) + 1;
  const drive = cluster.powertrain === "ev" ? "electric" : "combustion";
  $("#fig").textContent = `Fig. ${String(index).padStart(2, "0")} — ${bodyLabel(cluster.body)} · ${drive} · section A–A`;
  $("#vehicleName").textContent = title(cluster.vehicle);
  const parts = Cutaway.describedParts(cluster.failure, cluster.powertrain).map((key) => Cutaway.LABELS[key]);
  $("#failureName").textContent = parts.length ? `${cluster.headline} — ${parts.join(", ").toLowerCase()}` : cluster.headline;
}

function renderReadout(cluster) {
  const readout = $("#readout");
  if (!cluster) {
    readout.innerHTML = `<p class="label">Readout</p><p class="note">Pick a body type or search a vehicle. A signal appears once several complaints describe the same failure while their filed codes disagree.</p>`;
    return;
  }
  const described = Cutaway.describedParts(cluster.failure, cluster.powertrain);
  const filed = Cutaway.filedParts(cluster.filed_components, cluster.powertrain);
  const filedKey = (code) => {
    const hit = filed.parts.find((part) => part.codes.includes(code));
    if (!hit) return `<span class="key" style="border:1px solid transparent"></span>`;
    return described.includes(hit.key) ? `<span class="key solid"></span>` : `<span class="key dashed"></span>`;
  };
  const quotes = (cluster.examples || [])
    .map(
      (example) => `<figure class="quote">
        <p>${escapeHtml(example.desc)}</p>
        <cite>${dateLabel(example.ldate)} · ODI ${example.odi}${example.crash ? " · crash" : ""}${example.fire ? " · fire" : ""}</cite>
      </figure>`
    )
    .join("");

  readout.innerHTML = `
    <p class="label">Complaints in this signal</p>
    <p class="big">${cluster.count}</p>
    <p class="big-sub">${cluster.current_count} in the latest 30 days, ${signed(cluster.momentum)} on the prior 30 · ${dateLabel(cluster.first)} – ${dateLabel(cluster.last)}</p>
    <div class="block">
      <p class="label">Described in the complaints</p>
      <ul class="rows">${
        described.length
          ? described.map((key) => `<li><span class="key solid"></span>${Cutaway.LABELS[key]}</li>`).join("")
          : `<li class="muted">No single component</li>`
      }</ul>
    </div>
    <div class="block">
      <p class="label">Filed by owners as</p>
      <ul class="rows">${cluster.filed_components
        .map(
          (code) => `<li class="${filed.unmapped.includes(code) ? "muted" : ""}">${filedKey(code)}${escapeHtml(title(code.name))}<span class="count">${code.count}</span></li>`
        )
        .join("")}</ul>
    </div>
    <div class="block meters">
      <div><strong>${cluster.mean_severity.toFixed(2)}</strong><span>Severity / 3</span></div>
      <div><strong>${Math.round(cluster.mean_confidence * 100)}%</strong><span>Jev confidence</span></div>
      <div><strong>${cluster.crashes}</strong><span>Crashes${cluster.fires ? ` · ${cluster.fires} fires` : ""}</span></div>
    </div>
    <div class="block">
      <p class="label">From the complaints</p>
      ${quotes}
    </div>
    <p class="note">A reporting lead, not proof of a common cause. The drawing is a generic ${escapeHtml(cluster.body)} body, and the highlighted parts come from Jev's failure class, not a teardown.</p>`;

  readout.querySelectorAll(".quote").forEach((quote) => {
    quote.addEventListener("click", () => quote.classList.toggle("open"));
  });
}

function renderColophon() {
  const meta = payload.meta;
  $("#colophon").innerHTML = `
    <span>${meta.scored.toLocaleString()} complaints scored with ${meta.model} · complete through ${dateLabel(meta.coverage_complete_through)} · ${meta.matched.toLocaleString()} in this cut · ${meta.elapsed_ms} ms</span>
    <span>Source: NHTSA vehicle owner complaints</span>`;
}

// Drawing

async function showDrawing(cluster, replay = false) {
  const mine = ++sequence;
  const drawing = $("#drawing");
  const type = cluster ? cluster.body : state.body || "crossover";
  const powertrain = cluster ? cluster.powertrain : "ice";
  let svg = drawing.querySelector("svg");
  const fresh = !svg || replay || shown.type !== type || shown.powertrain !== powertrain;

  if (fresh) {
    if (svg) {
      drawing.classList.add("swap");
      await wait(240);
      if (mine !== sequence) return;
    }
    drawing.innerHTML = Cutaway.markup(type, powertrain);
    svg = drawing.querySelector("svg");
    svg.classList.add("enter");
    shown = { type, powertrain };
    drawing.classList.remove("swap");
    applyRoles(svg, cluster);
    if (!cluster) return;
    await wait(1500);
    if (mine !== sequence) return;
  } else {
    svg.querySelector(".callouts").innerHTML = "";
    svg.querySelector(".axes").innerHTML = "";
    if (svg.classList.contains("exploded")) {
      svg.classList.remove("exploded");
      await wait(700);
      if (mine !== sequence) return;
    }
    applyRoles(svg, cluster);
    await wait(80);
    if (mine !== sequence) return;
  }
  if (cluster && state.mode === "exploded") explode(svg, cluster, mine);
}

function applyRoles(svg, cluster) {
  const described = cluster ? Cutaway.describedParts(cluster.failure, cluster.powertrain) : [];
  const filed = cluster ? Cutaway.filedParts(cluster.filed_components, cluster.powertrain).parts.map((part) => part.key) : [];
  svg.style.setProperty("--share", 1);
  svg.querySelectorAll(".part").forEach((group) => {
    const key = group.dataset.key;
    group.classList.toggle("target", described.includes(key));
    group.classList.toggle("filed", filed.includes(key) && !described.includes(key));
  });
}

function offsetOf(group) {
  const style = group.style;
  return [parseFloat(style.getPropertyValue("--dx")) || 0, parseFloat(style.getPropertyValue("--dy")) || 0];
}

function explode(svg, cluster, mine) {
  svg.classList.remove("enter");
  const layer = svg.querySelector(".parts");
  svg.querySelectorAll(".part").forEach((group) => group.classList.remove("zoom"));
  svg.querySelectorAll(".part.target").forEach((group) => {
    layer.appendChild(group);
    const box = group.getBBox();
    group.classList.toggle("zoom", box.width < 220 && box.height < 120);
  });

  const axes = svg.querySelector(".axes");
  axes.innerHTML = [...svg.querySelectorAll(".part.filed")]
    .map((group) => {
      const box = group.getBBox();
      const [dx, dy] = offsetOf(group);
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      return `<line x1="${x}" y1="${y}" x2="${x + dx}" y2="${y + dy}"/>`;
    })
    .join("");

  svg.classList.add("exploded");
  setTimeout(() => {
    if (mine === sequence && state.mode === "exploded") drawCallouts(svg, calloutCluster(cluster));
  }, 1050);
}

function spread(items, gap = 10) {
  items.sort((a, b) => a.x - b.x);
  let edge = 12;
  for (const item of items) {
    item.lx = Math.max(item.x, edge + item.w / 2);
    edge = item.lx + item.w / 2 + gap;
  }
  const overflow = edge - gap - (Cutaway.W - 12);
  if (overflow > 0) items.forEach((item) => (item.lx -= overflow));
  return items;
}

function chipWidth(text) {
  return text.length * 7.3 + 24;
}

function drawCallouts(svg, cluster) {
  const layer = svg.querySelector(".callouts");
  const filedInfo = Cutaway.filedParts(cluster.filed_components, cluster.powertrain).parts;
  const matched = new Map(filedInfo.map((part) => [part.key, part.count]));
  const described = [...svg.querySelectorAll(".part.target")].map((group) => {
    const whole = group.getBBox();
    const primary = group.querySelector(".sf, .ht, .caliper, .harness");
    const raw = primary ? primary.getBBox() : whole;
    const scale = group.classList.contains("zoom") ? 1.35 : 1;
    const cx = whole.x + whole.width / 2;
    const cy = whole.y + whole.height / 2;
    const box = {
      x: cx + (raw.x - cx) * scale,
      y: cy + (raw.y - cy) * scale,
      width: raw.width * scale,
      height: raw.height * scale,
    };
    const key = group.dataset.key;
    const text = matched.has(key) ? `${Cutaway.LABELS[key]} · filed ${matched.get(key)}` : Cutaway.LABELS[key];
    return { box, text, x: box.x + box.width / 2, w: chipWidth(text) };
  });
  const filed = filedInfo
    .map((part) => ({ part, group: svg.querySelector(`.part.filed[data-key="${part.key}"]`) }))
    .filter((item) => item.group)
    .slice(0, 3)
    .map(({ part, group }) => {
      const primary = group.querySelector(".sf, .ht, .caliper, .harness");
      const box = (primary || group).getBBox();
      const [dx, dy] = offsetOf(group);
      const text = `Filed · ${Cutaway.LABELS[part.key]} ${part.count}`;
      return { box, dx, dy, text, x: box.x + box.width / 2 + dx, w: chipWidth(text) };
    });

  const bottomY = 440;
  const topY = 34;
  let out = "";
  for (const item of spread(described)) {
    const { box } = item;
    const from = Math.min(box.y + box.height + 6, 412);
    const ping =
      box.width < 260
        ? `<rect class="ping" x="${box.x - 8}" y="${box.y - 8}" width="${box.width + 16}" height="${box.height + 16}" rx="10"/>`
        : "";
    out += `<g>${ping}
      <circle class="anchor" cx="${item.x}" cy="${from}" r="2.5"/>
      <path class="leader" d="M${item.x},${from} V${bottomY - 26} L${item.lx},${bottomY - 11}"/>
      <rect class="chip-bg" x="${item.lx - item.w / 2}" y="${bottomY - 11}" width="${item.w}" height="22" rx="11"/>
      <text x="${item.lx}" y="${bottomY}" text-anchor="middle">${escapeHtml(item.text)}</text>
    </g>`;
  }
  for (const item of spread(filed)) {
    const top = item.box.y + item.dy - 4;
    out += `<g>
      <path class="leader filed" d="M${item.x},${top} L${item.lx},${topY + 11}"/>
      <rect class="chip-bg filed" x="${item.lx - item.w / 2}" y="${topY - 11}" width="${item.w}" height="22" rx="11"/>
      <text class="filed" x="${item.lx}" y="${topY}" text-anchor="middle">${escapeHtml(item.text)}</text>
    </g>`;
  }
  layer.innerHTML = out;
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll("#mode button").forEach((button) => button.classList.toggle("on", button.dataset.value === mode));
  const svg = $("#drawing svg");
  const cluster = clusters.find((item) => keyOf(item) === state.key);
  if (!svg || !cluster) return;
  if (mode === "exploded") {
    explode(svg, cluster, ++sequence);
  } else {
    sequence++;
    svg.querySelector(".callouts").innerHTML = "";
    svg.querySelector(".axes").innerHTML = "";
    svg.classList.remove("exploded");
  }
}

// Events

function bindSegmented(id, onChange) {
  document.querySelectorAll(`#${id} button`).forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(`#${id} button`).forEach((other) => other.classList.toggle("on", other === button));
      onChange(button.dataset.value);
    });
  });
}

bindSegmented("window", (value) => {
  state.window = value;
  load();
});
bindSegmented("sort", (value) => {
  state.sort = value;
  load();
});
document.querySelectorAll("#mode button").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.value));
});

$("#bodies").addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  state.body = chip.dataset.body;
  syncChips();
  load();
});

$("#failure").addEventListener("change", (event) => {
  state.failure = event.target.value;
  state.part = "";
  renderActivePart();
  load();
});

$("#activePart").addEventListener("click", (event) => {
  if (!event.target.closest("#clearPart")) return;
  state.part = "";
  renderActivePart();
  load();
});

function partUnder(event) {
  const group = event.target instanceof Element ? event.target.closest(".part") : null;
  if (!group) return null;
  const key = group.dataset.key;
  return Cutaway.failuresForPart(key).length ? key : null;
}

$("#drawing").addEventListener("click", (event) => {
  const key = partUnder(event);
  if (!key) return;
  state.part = key;
  state.failure = "";
  $("#failure").value = "";
  renderActivePart();
  load();
});

const hoverTag = document.createElement("div");
hoverTag.className = "hovertag";
hoverTag.hidden = true;
document.body.appendChild(hoverTag);

$("#drawing").addEventListener("mousemove", (event) => {
  const key = partUnder(event);
  document.querySelectorAll(".part.hover").forEach((group) => {
    if (group.dataset.key !== key) group.classList.remove("hover");
  });
  if (!key) {
    hoverTag.hidden = true;
    return;
  }
  document.querySelector(`.part[data-key="${key}"]`)?.classList.add("hover");
  hoverTag.innerHTML = `<strong>${escapeHtml(Cutaway.LABELS[key])}</strong><span>Click to see every vehicle with this problem</span>`;
  hoverTag.style.left = `${event.clientX + 14}px`;
  hoverTag.style.top = `${event.clientY + 14}px`;
  hoverTag.hidden = false;
});

$("#drawing").addEventListener("mouseleave", () => {
  hoverTag.hidden = true;
  document.querySelectorAll(".part.hover").forEach((group) => group.classList.remove("hover"));
});

const timelineEl = $("#timeline");
function scrubFromPointer(event) {
  const cluster = currentCluster();
  if (!cluster?.weekly?.length) return;
  const rect = timelineEl.getBoundingClientRect();
  const ratio = (event.clientX - rect.left) / rect.width;
  scrubTo(Math.floor(ratio * cluster.weekly.length));
}
timelineEl.addEventListener("pointerdown", (event) => {
  timelineEl.setPointerCapture(event.pointerId);
  timelineEl.classList.add("dragging");
  scrubFromPointer(event);
});
timelineEl.addEventListener("pointermove", (event) => {
  if (timelineEl.hasPointerCapture(event.pointerId)) scrubFromPointer(event);
});
timelineEl.addEventListener("pointerup", () => timelineEl.classList.remove("dragging"));
$("#scrubNow").addEventListener("click", () => scrubTo(Number.MAX_SAFE_INTEGER));

$("#vehicle").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.vehicle = event.target.value.trim();
    if (state.vehicle && state.body) {
      state.body = "";
      syncChips();
    }
    load();
  }, 280);
});

$("#signals").addEventListener("click", (event) => {
  const button = event.target.closest(".signal");
  if (button) select(button.dataset.key);
});

$("#replay").addEventListener("click", () => select(state.key, { replay: true }));

document.addEventListener("keydown", (event) => {
  if (event.target instanceof Element && event.target.closest("input, select, textarea")) return;
  const index = clusters.findIndex((item) => keyOf(item) === state.key);
  if (event.key === "ArrowDown" || event.key === "j") {
    event.preventDefault();
    if (index < clusters.length - 1) select(keyOf(clusters[index + 1]));
  } else if (event.key === "ArrowUp" || event.key === "k") {
    event.preventDefault();
    if (index > 0) select(keyOf(clusters[index - 1]));
  } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    const cluster = currentCluster();
    if (!cluster?.weekly?.length) return;
    const now = state.scrub ?? cluster.weekly.length - 1;
    scrubTo(now + (event.key === "ArrowLeft" ? -1 : 1));
  } else if (event.key === " ") {
    event.preventDefault();
    setMode(state.mode === "exploded" ? "assembled" : "exploded");
  } else if (event.key === "r") {
    select(state.key, { replay: true });
  }
});

load();
