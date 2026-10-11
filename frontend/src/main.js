import "./styles.css";
("use strict");
// Same-origin backend only. No bundled dataset, client-side models, or credentials.
const $ = (id) => document.getElementById(id);
const state = {
  config: null,
  nodes: new Map(),
  children: new Map(),
  childCursors: new Map(),
  expanded: new Set(),
  scope: null,
  groups: [],
  selectedGroups: new Set(),
  points: [],
  cursor: null,
  total: 0,
  query: "",
  list: false,
  listLimit: 100,
  selected: null,
  selectedSource: null,
  zoom: 1,
  camera: { x: 0, y: 0 },
  bounds: { x: 0, y: 0, w: 1, h: 1 },
  busy: false,
  chatEpoch: 0,
  mapEpoch: 0,
  sourceEpoch: 0,
  issuesEpoch: 0,
  controller: null,
  mapController: null,
  history: [],
  issues: [],
  hitGrid: new Map(),
};
const palette = [
  "#163f3b",
  "#4059a8",
  "#977040",
  "#775087",
  "#367974",
  "#a45d52",
  "#586995",
  "#767a3c",
];
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const btn = (text, callback, className) => {
  const node = el("button", className, text);
  node.type = "button";
  node.addEventListener("click", callback);
  return node;
};
function status(text = "") {
  $("app-status").textContent = text;
}
function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
async function json(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail, trace;
    try {
      const data = await response.json();
      detail = typeof data.error === "string" && data.error;
      trace = data.trace;
    } catch {}
    const error = new Error(detail || `Request failed (${response.status}).`);
    error.trace = trace;
    throw error;
  }
  return response.json();
}
function accent(value, fallback) {
  if (!/^#[0-9a-f]{6}$/i.test(value || "")) return fallback;
  let rgb = value
    .slice(1)
    .match(/../g)
    .map((v) => parseInt(v, 16));
  const luminance = () =>
    rgb
      .map((v) => v / 255)
      .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
      .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
  while (1.05 / (luminance() + 0.05) < 4.8)
    rgb = rgb.map((v) => Math.floor(v * 0.88));
  return "#" + rgb.map((v) => v.toString(16).padStart(2, "0")).join("");
}
function applyTheme(config) {
  palette[0] = accent(config.theme?.primary, "#163f3b");
  palette[1] = accent(config.theme?.secondary, "#4059a8");
  document.documentElement.style.setProperty("--primary", palette[0]);
  document.documentElement.style.setProperty("--secondary", palette[1]);
}
const searchMode = () =>
  document.querySelector('input[name="mode"]:checked').value;
function requestBody(query) {
  return {
    query,
    scope_node_id: state.scope,
    group_ids: [...state.selectedGroups],
    mode: searchMode(),
    history: state.history.slice(-8),
  };
}
function setBusy(busy) {
  state.busy = busy;
  $("send").disabled =
    busy ||
    !state.config ||
    state.config.total_chunks === 0 ||
    !$("question").value.trim();
  $("send").hidden = busy;
  $("stop").hidden = !busy;
}
function scopeLabel() {
  const parts = [state.nodes.get(state.scope)?.title || "All sources"];
  if (state.selectedGroups.size)
    parts.push(
      `${state.selectedGroups.size} group${state.selectedGroups.size === 1 ? "" : "s"}`,
    );
  return parts.join(" · ");
}
function syncScope() {
  $("scope-button").textContent = scopeLabel();
  $("clear-scope").hidden = !state.scope && !state.selectedGroups.size;
  renderHierarchy();
  renderGroups();
}
function changeScope(id, clearGroups = false) {
  state.scope = id;
  if (clearGroups) state.selectedGroups.clear();
  state.history = [];
  state.chatEpoch++;
  state.controller?.abort();
  setBusy(false);
  syncScope();
  status();
  loadMap();
}
function traceView(trace) {
  if (!trace || !Array.isArray(trace.steps)) return null;
  const details = el("details", "search-trace");
  details.append(el("summary", "", "Search trace"));
  const body = el("div", "trace-body");
  body.append(el("p", "trace-query", `Query: ${trace.query}`));
  body.append(
    el(
      "p",
      "",
      `${trace.mode} · branch: ${trace.scope_node_id || "all"} · groups: ${(trace.group_ids || []).join(", ") || "all"}`,
    ),
  );
  body.append(
    el(
      "p",
      "",
      trace.expansions?.length
        ? `Expanded terms: ${trace.expansions.join(", ")}`
        : "Original query only; no expansion.",
    ),
  );
  const list = el("ol");
  trace.steps.forEach((step) => {
    const row = el("li", `trace-step ${step.status}`);
    row.append(el("strong", "", `${step.name} · ${step.status}`));
    row.append(
      el(
        "span",
        "trace-meta",
        `${Number(step.duration_ms || 0).toFixed(2)} ms${Number.isInteger(step.result_count) ? ` · ${step.result_count} results` : ""}`,
      ),
    );
    row.append(el("p", "", step.detail));
    if (step.result_ids?.length) {
      const ids = el("details", "trace-ids");
      ids.append(
        el("summary", "", "Ranked passage IDs"),
        el("p", "", step.result_ids.join(" → ")),
      );
      row.append(ids);
    }
    list.append(row);
  });
  body.append(list);
  details.append(body);
  return details;
}
function message(role, text, citations, note, trace) {
  const article = el("article", `message ${role}`);
  article.append(el("p", "", text));
  if (note) article.append(el("small", "scope-note", note));
  if (citations?.length) {
    const links = el("div", "citations");
    citations.forEach((chunk, i) =>
      links.append(
        btn(`[${i + 1}] ${chunk.title || "Source"}`, () => openSource(chunk)),
      ),
    );
    article.append(links);
  }
  const inspection = traceView(trace);
  if (inspection) article.append(inspection);
  $("messages").append(article);
  $("messages").scrollTop = $("messages").scrollHeight;
}
async function ask(searchOnly = $("sources-only").checked) {
  const query = $("question").value.trim();
  if (!query || state.busy || !state.config || state.config.total_chunks === 0)
    return;
  const epoch = ++state.chatEpoch,
    body = requestBody(query),
    label = scopeLabel();
  state.controller = new AbortController();
  setBusy(true);
  status(searchOnly ? "Finding sources…" : "Finding evidence…");
  message("user", query, [], label);
  $("question").value = "";
  resizeQuestion();
  try {
    const data = await json(searchOnly ? "/api/search" : "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: state.controller.signal,
    });
    if (epoch !== state.chatEpoch) return;
    if (searchOnly) {
      const results = Array.isArray(data.results) ? data.results : [];
      message(
        "assistant",
        results.length
          ? `${results.length} source${results.length === 1 ? "" : "s"} found.`
          : "No matching sources found.",
        results,
        data.coverage_note,
        data.trace,
      );
    } else {
      if (typeof data.answer !== "string")
        throw new Error("No answer was returned.");
      message(
        "assistant",
        data.answer,
        data.citations || [],
        data.coverage_note,
        data.trace,
      );
      state.history.push(
        { role: "user", content: query },
        { role: "assistant", content: data.answer },
      );
    }
    status();
    await refreshIssues();
  } catch (error) {
    if (epoch === state.chatEpoch && error.name !== "AbortError") {
      status(error.message);
      if (error.trace)
        message("assistant", error.message, [], null, error.trace);
    }
  } finally {
    if (epoch === state.chatEpoch) setBusy(false);
  }
}
function storeNodes(nodes) {
  if (!Array.isArray(nodes)) throw new Error("Invalid hierarchy response.");
  nodes.forEach((node) => {
    if (typeof node.id !== "string" || typeof node.title !== "string")
      throw new Error("A source node is missing its ID or title.");
    state.nodes.set(node.id, node);
    const parent = node.parent_id || null;
    if (!state.children.has(parent)) state.children.set(parent, []);
    if (!state.children.get(parent).includes(node.id))
      state.children.get(parent).push(node.id);
  });
}
async function loadChildren(parent = null, more = false) {
  const params = new URLSearchParams({ limit: "100" });
  if (parent) params.set("parent_id", parent);
  if (more && state.childCursors.get(parent))
    params.set("cursor", state.childCursors.get(parent));
  const data = await json(`/api/nodes?${params}`);
  storeNodes(data.nodes);
  state.childCursors.set(parent, data.next_cursor || null);
  renderHierarchy();
}
function renderHierarchy() {
  const root = $("hierarchy");
  root.replaceChildren();
  const visited = new Set();
  function branch(parent, container) {
    (state.children.get(parent) || []).forEach((id) => {
      if (visited.has(id)) return;
      visited.add(id);
      const node = state.nodes.get(id),
        row = el("div", "tree-row");
      const expandable = Number(node.child_count) > 0;
      const expand = btn(
        state.expanded.has(id) ? "−" : "+",
        async () => {
          try {
            if (state.expanded.has(id)) state.expanded.delete(id);
            else {
              if (!state.children.has(id)) await loadChildren(id);
              state.expanded.add(id);
            }
            renderHierarchy();
          } catch (error) {
            status(error.message);
          }
        },
        "expand",
      );
      expand.disabled = !expandable;
      expand.setAttribute("aria-label", `Expand ${node.title}`);
      if (expandable)
        expand.setAttribute("aria-expanded", String(state.expanded.has(id)));
      const title = btn(
        node.title,
        () => {
          changeScope(id);
          $("filters-dialog").close();
        },
        "tree-title",
      );
      title.title = node.description || node.title;
      if (state.scope === id) title.setAttribute("aria-current", "true");
      if (node.status && node.status !== "ready")
        title.append(el("small", "", node.status));
      row.append(
        expand,
        title,
        btn("↗", () => openNode(node), "expand"),
      );
      row.lastChild.setAttribute("aria-label", `Preview ${node.title}`);
      container.append(row);
      if (state.expanded.has(id)) {
        const children = el("div", "tree-children");
        branch(id, children);
        container.append(children);
      }
    });
    if (state.childCursors.get(parent))
      container.append(
        btn("Load more sources", async () => {
          try {
            await loadChildren(parent, true);
          } catch (error) {
            status(error.message);
          }
        }),
      );
  }
  branch(null, root);
}
function renderGroups() {
  $("group-filters").replaceChildren();
  state.groups.forEach((group) => {
    const control = btn(group.title, () => {
      if (state.selectedGroups.has(group.id))
        state.selectedGroups.delete(group.id);
      else state.selectedGroups.add(group.id);
      changeScope(state.scope);
    });
    control.setAttribute(
      "aria-pressed",
      String(state.selectedGroups.has(group.id)),
    );
    $("group-filters").append(control);
  });
}
function openDialog(id) {
  const dialog = $(id);
  for (const other of document.querySelectorAll("dialog[open]"))
    if (other !== dialog) other.close();
  if (!dialog.open) {
    if (document.body.classList.contains("map-view") && id !== "issues-dialog")
      dialog.show();
    else dialog.showModal();
  }
  draw();
}
function sourceLoading(title) {
  $("source-title").textContent = title || "Source";
  $("source-path").textContent = "";
  $("source-description").textContent = "";
  $("source-text").textContent = "Loading…";
  $("source-link").hidden = $("source-warning").hidden = true;
  $("source-scope").disabled = true;
  state.selectedSource = null;
  openDialog("source-dialog");
  return ++state.sourceEpoch;
}
function showSource(chunk, node = {}) {
  state.selectedSource = chunk;
  $("source-title").textContent = chunk.title || node.title || "Source";
  $("source-path").textContent = Array.isArray(chunk.path || node.path)
    ? (chunk.path || node.path).join(" › ")
    : chunk.locator || "";
  $("source-description").textContent =
    node.description || chunk.description || "";
  $("source-text").textContent =
    chunk.text || "No extracted text is available for this source.";
  $("source-warning").hidden = !chunk.coverage_note && !node.coverage_note;
  $("source-warning").textContent =
    chunk.coverage_note || node.coverage_note || "";
  const url = safeUrl(chunk.source_url || node.source_url);
  $("source-link").hidden = !url;
  if (url) $("source-link").href = url;
  else $("source-link").removeAttribute("href");
  $("source-scope").disabled = !chunk.node_id;
}
async function openSource(chunk) {
  const epoch = sourceLoading(chunk.title);
  try {
    const full =
      typeof chunk.text === "string"
        ? chunk
        : await json(`/api/chunks/${encodeURIComponent(chunk.id)}`);
    if (epoch === state.sourceEpoch)
      showSource(full, state.nodes.get(full.node_id));
  } catch (error) {
    if (epoch === state.sourceEpoch)
      $("source-text").textContent = error.message;
  }
}
async function openNode(node) {
  const epoch = sourceLoading(node.title);
  try {
    const data = await json(
      `/api/nodes/${encodeURIComponent(node.id)}/chunks?limit=1`,
    );
    if (epoch === state.sourceEpoch)
      showSource(
        {
          ...data.chunks?.[0],
          node_id: node.id,
          title: node.title || data.chunks?.[0]?.title,
          path: node.path || data.chunks?.[0]?.path,
        },
        node,
      );
  } catch (error) {
    if (epoch === state.sourceEpoch)
      $("source-text").textContent = error.message;
  }
}
async function refreshIssues() {
  const epoch = ++state.issuesEpoch;
  try {
    const data = await json("/api/issues");
    if (epoch !== state.issuesEpoch) return;
    state.issues = (data.issues || []).filter(
      (issue) => issue.status !== "resolved",
    );
    $("issues-button").hidden = !state.issues.length;
    $("issues-button").textContent =
      `${state.issues.length} data issue${state.issues.length === 1 ? "" : "s"}`;
    const list = $("issues-list");
    list.replaceChildren();
    state.issues.forEach((issue) => {
      const card = el("article", "issue");
      card.append(
        el("strong", "", issue.title),
        el("p", "", issue.message),
        el("small", "", issue.locator || ""),
      );
      if (Number.isFinite(issue.affected_count))
        card.append(
          el(
            "small",
            "",
            `${issue.affected_count.toLocaleString()} affected ${issue.affected_unit || "records"}`,
          ),
        );
      if (issue.question) card.append(el("p", "", issue.question));
      if (issue.node_id)
        card.append(
          btn("View source", () =>
            openNode(
              state.nodes.get(issue.node_id) || {
                id: issue.node_id,
                title: issue.source_title,
                path: issue.path,
                coverage_note: issue.message,
              },
            ),
          ),
        );
      list.append(card);
    });
    if (!state.issues.length)
      list.append(el("p", "", "No unresolved data issues reported."));
  } catch (error) {
    $("issues-button").hidden = false;
    $("issues-button").textContent = "Data status unavailable";
    $("issues-list").replaceChildren(
      el("p", "", `Could not check ingestion issues. ${error.message}`),
    );
  }
}
function mapMetrics() {
  const r = $("map").getBoundingClientRect();
  const inset =
    document.body.classList.contains("map-view") &&
    $("filters-dialog").open &&
    r.width > 720
      ? Math.min(510, r.width * 0.4)
      : 0;
  return {
    w: r.width,
    h: r.height,
    inset,
    centerX: inset + (r.width - inset) / 2,
    scale:
      Math.min((r.width - inset) / state.bounds.w, r.height / state.bounds.h) *
      0.85 *
      state.zoom,
  };
}
function screenPoint(point, m) {
  return {
    x: (point.x - state.camera.x) * m.scale + m.centerX,
    y: (point.y - state.camera.y) * m.scale + m.h / 2,
  };
}
function fit() {
  if (state.points.length) {
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    state.points.forEach((p) => {
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x);
      maxY = Math.max(maxY, p.y);
    });
    state.bounds = {
      x: (minX + maxX) / 2,
      y: (minY + maxY) / 2,
      w: Math.max(maxX - minX, 0.1),
      h: Math.max(maxY - minY, 0.1),
    };
  } else state.bounds = { x: 0, y: 0, w: 1, h: 1 };
  state.camera = { x: state.bounds.x, y: state.bounds.y };
  state.zoom = 1;
  draw();
}
let drawQueued = false;
function draw() {
  if (drawQueued) return;
  drawQueued = true;
  requestAnimationFrame(() => {
    drawQueued = false;
    paint();
  });
}
function paint() {
  const canvas = $("map"),
    m = mapMetrics();
  if (!m.w || !m.h) return;
  const dpr = devicePixelRatio || 1,
    ctx = canvas.getContext("2d");
  canvas.width = Math.round(m.w * dpr);
  canvas.height = Math.round(m.h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, m.w, m.h);
  state.hitGrid.clear();
  if (!state.points.length) return;
  const center = screenPoint(state.bounds, m);
  ctx.strokeStyle = "rgba(20,49,95,.12)";
  ctx.lineWidth = 1;
  ctx.setLineDash([5, 8]);
  ctx.beginPath();
  ctx.moveTo(center.x, 0);
  ctx.lineTo(center.x, m.h);
  ctx.moveTo(0, center.y);
  ctx.lineTo(m.w, center.y);
  ctx.stroke();
  ctx.setLineDash([]);
  const colors = new Map(
    state.groups.map((g, i) => [g.id, palette[i % palette.length]]),
  );
  const radius = Math.min(7, Math.max(2.8, 3.7 * Math.sqrt(state.zoom)));
  state.points.forEach((point) => {
    const p = screenPoint(point, m);
    if (p.x < -15 || p.y < -15 || p.x > m.w + 15 || p.y > m.h + 15) return;
    const selected = state.selected === point.id;
    ctx.beginPath();
    ctx.arc(p.x, p.y, selected ? radius * 1.75 : radius, 0, 2 * Math.PI);
    ctx.fillStyle = colors.get(point.group_id) || palette[0];
    ctx.globalAlpha = selected ? 1 : 0.82;
    ctx.fill();
    ctx.strokeStyle = selected ? "#fffdf7" : "rgba(22,33,61,.85)";
    ctx.lineWidth = selected ? 2 : 1;
    ctx.stroke();
    const key = `${Math.floor(p.x / 24)},${Math.floor(p.y / 24)}`;
    if (!state.hitGrid.has(key)) state.hitGrid.set(key, []);
    state.hitGrid.get(key).push({ ...p, point });
  });
  ctx.globalAlpha = 1;
}
function hit(x, y) {
  let closest = null,
    distance = 12 ** 2;
  const cellX = Math.floor(x / 24),
    cellY = Math.floor(y / 24);
  for (let dx = -1; dx <= 1; dx++)
    for (let dy = -1; dy <= 1; dy++) {
      (state.hitGrid.get(`${cellX + dx},${cellY + dy}`) || []).forEach((p) => {
        const d = (p.x - x) ** 2 + (p.y - y) ** 2;
        if (d <= distance) {
          distance = d;
          closest = p.point;
        }
      });
    }
  return closest;
}
function zoom(factor, x, y) {
  const m = mapMetrics();
  if (!m.scale) return;
  x ??= m.centerX;
  y ??= m.h / 2;
  const world = {
    x: state.camera.x + (x - m.centerX) / m.scale,
    y: state.camera.y + (y - m.h / 2) / m.scale,
  };
  state.zoom = Math.min(30, Math.max(0.2, state.zoom * factor));
  const next = mapMetrics();
  state.camera = {
    x: world.x - (x - m.centerX) / next.scale,
    y: world.y - (y - m.h / 2) / next.scale,
  };
  draw();
}
function renderPointList() {
  const list = $("point-list");
  list.replaceChildren();
  state.points.slice(0, state.listLimit).forEach((point) => {
    const control = btn(point.title, () => selectPoint(point));
    if (point.path) control.append(el("small", "", point.path.join(" › ")));
    list.append(control);
  });
  if (state.points.length > state.listLimit)
    list.append(
      btn("Show more", () => {
        state.listLimit += 100;
        renderPointList();
      }),
    );
  if (!state.points.length)
    list.append(
      el(
        "p",
        "",
        state.config
          ? "No mapped passages in this scope."
          : "No database connected.",
      ),
    );
}
function selectPoint(point) {
  state.selected = point.id;
  draw();
  openSource({ id: point.chunk_id, title: point.title });
}
async function loadMap(more = false) {
  if (!state.config) return;
  if (more && !state.cursor) return;
  const epoch = ++state.mapEpoch;
  state.mapController?.abort();
  state.mapController = new AbortController();
  const params = new URLSearchParams({ limit: "5000", mode: searchMode() });
  if (state.scope) params.set("scope_node_id", state.scope);
  if (state.query) params.set("query", state.query);
  state.selectedGroups.forEach((id) => params.append("group_ids", id));
  if (more) params.set("cursor", state.cursor);
  $("more-points").disabled = true;
  $("map-count").textContent = "Loading…";
  $("map-trace").hidden = true;
  $("map-trace").replaceChildren();
  try {
    const data = await json(`/api/map?${params}`, {
      signal: state.mapController.signal,
    });
    if (epoch !== state.mapEpoch) return;
    const inspection = traceView(data.trace);
    if (inspection) {
      $("map-trace").replaceChildren(inspection);
      $("map-trace").hidden = false;
    }
    if (
      !Array.isArray(data.points) ||
      data.points.some(
        (p) =>
          !Number.isFinite(p.x) ||
          !Number.isFinite(p.y) ||
          typeof p.id !== "string" ||
          typeof p.chunk_id !== "string",
      )
    )
      throw new Error("Invalid map coordinates or source IDs.");
    const points = new Map((more ? state.points : []).map((p) => [p.id, p]));
    data.points.forEach((p) => points.set(p.id, p));
    state.points = [...points.values()];
    state.groups = data.groups || [];
    state.cursor = data.next_cursor || null;
    state.total = data.total_points;
    state.listLimit = 100;
    $("map-count").textContent =
      `${state.points.length.toLocaleString()}${Number.isFinite(state.total) && state.total > state.points.length ? ` of ${state.total.toLocaleString()}` : ""} passages${data.coverage_note ? ` · ${data.coverage_note}` : ""}`;
    $("map-empty").hidden = !!state.points.length;
    $("map-empty").textContent =
      data.coverage_note || "No mapped passages in this scope.";
    $("more-points").hidden = !state.cursor;
    if (!more) fit();
    else draw();
    renderPointList();
    renderGroups();
  } catch (error) {
    if (epoch !== state.mapEpoch || error.name === "AbortError") return;
    if (!more) {
      state.points = [];
      state.selected = null;
      draw();
      renderPointList();
    }
    $("map-count").textContent = error.message;
    const inspection = traceView(error.trace);
    if (inspection) {
      $("map-trace").replaceChildren(inspection);
      $("map-trace").hidden = false;
    }
    $("map-empty").hidden = !!state.points.length;
    $("map-empty").textContent = "Map unavailable.";
  } finally {
    if (epoch === state.mapEpoch) $("more-points").disabled = false;
  }
}
function page() {
  const map = ["#map", "#explore"].includes(location.hash);
  document.body.classList.toggle("map-view", map);
  document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
  $("chat-page").hidden = map;
  $("map-page").hidden = !map;
  ["chat", "map"].forEach((name) => {
    if ((name === "map") === map)
      $(`nav-${name}`).setAttribute("aria-current", "page");
    else $(`nav-${name}`).removeAttribute("aria-current");
  });
  if (map) draw();
}
const pointers = new Map();
let gesture = null;
$("map").addEventListener("pointerdown", (event) => {
  $("map").setPointerCapture(event.pointerId);
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  gesture = {
    startX: event.clientX,
    startY: event.clientY,
    x: event.clientX,
    y: event.clientY,
    moved: pointers.size > 1,
    distance: null,
  };
  $("map").classList.add("dragging");
  $("map-tooltip").hidden = true;
});
$("map").addEventListener("pointermove", (event) => {
  const r = $("map").getBoundingClientRect(),
    x = event.clientX - r.left,
    y = event.clientY - r.top;
  if (pointers.has(event.pointerId)) {
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size > 1) {
      const [a, b] = [...pointers.values()],
        distance = Math.hypot(a.x - b.x, a.y - b.y);
      if (gesture.distance)
        zoom(
          distance / gesture.distance,
          (a.x + b.x) / 2 - r.left,
          (a.y + b.y) / 2 - r.top,
        );
      gesture.distance = distance;
      gesture.moved = true;
    } else {
      const scale = mapMetrics().scale;
      if (scale) {
        state.camera.x -= (event.clientX - gesture.x) / scale;
        state.camera.y -= (event.clientY - gesture.y) / scale;
      }
      gesture.x = event.clientX;
      gesture.y = event.clientY;
      if (
        Math.hypot(
          event.clientX - gesture.startX,
          event.clientY - gesture.startY,
        ) > 4
      )
        gesture.moved = true;
      draw();
    }
    return;
  }
  const point = hit(x, y);
  $("map-tooltip").hidden = !point;
  if (point) {
    $("map-tooltip").textContent = point.title;
    $("map-tooltip").style.left =
      `${Math.max(10, Math.min(x + 16, r.width - 310))}px`;
    $("map-tooltip").style.top = `${Math.min(y + 16, r.height - 80)}px`;
  }
});
function endPointer(event) {
  if (!pointers.has(event.pointerId)) return;
  const moved = gesture?.moved;
  pointers.delete(event.pointerId);
  if (!pointers.size) {
    $("map").classList.remove("dragging");
    gesture = null;
    if (!moved && event.type === "pointerup") {
      const r = $("map").getBoundingClientRect(),
        point = hit(event.clientX - r.left, event.clientY - r.top);
      if (point) selectPoint(point);
    }
  } else {
    const p = [...pointers.values()][0];
    gesture = { ...gesture, x: p.x, y: p.y, distance: null, moved: true };
  }
}
["pointerup", "pointercancel"].forEach((type) =>
  $("map").addEventListener(type, endPointer),
);
$("map").addEventListener("pointerleave", () => {
  $("map-tooltip").hidden = true;
});
$("map").addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    const r = $("map").getBoundingClientRect();
    zoom(
      Math.exp(-event.deltaY * 0.0015),
      event.clientX - r.left,
      event.clientY - r.top,
    );
  },
  { passive: false },
);
new ResizeObserver(draw).observe($("map"));
window.addEventListener("hashchange", page);
$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  ask();
});
$("question").addEventListener("keydown", (event) => {
  if (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.isComposing &&
    event.keyCode !== 229
  ) {
    event.preventDefault();
    ask();
  }
});
function resizeQuestion() {
  $("question").style.height = "auto";
  $("question").style.height = `${Math.min($("question").scrollHeight, 180)}px`;
}
$("question").addEventListener("input", () => {
  resizeQuestion();
  setBusy(state.busy);
});
$("sources-only").addEventListener("change", () => {
  const action = $("sources-only").checked ? "search" : "ask";
  $("send-label").textContent = action === "ask" ? "Ask" : "Search";
  $("composer-hint").textContent = $("sources-only").checked
    ? "Matching passages only, no AI answer · Enter to search"
    : "Enter to ask · Shift+Enter for a new line";
});
$("stop").addEventListener("click", () => {
  state.chatEpoch++;
  state.controller?.abort();
  setBusy(false);
  status("Stopped.");
});
["scope-button", "filters"].forEach((id) =>
  $(id).addEventListener("click", () => openDialog("filters-dialog")),
);
$("all-sources").addEventListener("click", () => {
  changeScope(null, true);
  $("filters-dialog").close();
});
$("clear-scope").addEventListener("click", () => changeScope(null, true));
$("issues-button").addEventListener("click", () => {
  refreshIssues();
  openDialog("issues-dialog");
});
$("source-scope").addEventListener("click", () => {
  if (state.selectedSource?.node_id) {
    changeScope(state.selectedSource.node_id);
    $("source-dialog").close();
  }
});
$("source-dialog").addEventListener("close", () => {
  state.sourceEpoch++;
  draw();
});
$("filters-dialog").addEventListener("close", draw);
$("map-search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.query = $("map-search").value.trim();
  loadMap();
});
$("map-search").addEventListener("search", () => {
  if (!$("map-search").value) {
    state.query = "";
    loadMap();
  }
});
$("modes").addEventListener("change", () => {
  if (state.query) loadMap();
});
$("zoom-in").addEventListener("click", () => zoom(1.6));
$("zoom-out").addEventListener("click", () => zoom(1 / 1.6));
$("fit").addEventListener("click", fit);
$("more-points").addEventListener("click", () => loadMap(true));
$("toggle-list").addEventListener("click", () => {
  state.list = !state.list;
  $("point-list").hidden = !state.list;
  $("toggle-list").setAttribute("aria-pressed", String(state.list));
  renderPointList();
});
document
  .querySelectorAll("[data-close]")
  .forEach((control) =>
    control.addEventListener("click", () => $(control.dataset.close).close()),
  );
async function connect() {
  $("retry").disabled = true;
  $("connection-text").textContent = "Connecting…";
  try {
    const config = await json("/api/config");
    state.config = config;
    applyTheme(config);
    document.body.classList.remove("disconnected");
    $("connection").hidden = true;
    $("scope-button").disabled = $("filters").disabled = false;
    setBusy(false);
    state.nodes.clear();
    state.children.clear();
    state.childCursors.clear();
    state.expanded.clear();
    await loadChildren();
    syncScope();
    status(config.total_chunks === 0 ? "No data indexed yet." : "");
    await Promise.all([loadMap(), refreshIssues()]);
  } catch (error) {
    state.config = null;
    setBusy(false);
    state.points = [];
    draw();
    document.body.classList.add("disconnected");
    $("connection").hidden = false;
    $("connection-text").textContent = "No database connected.";
    $("retry").title = error.message;
    $("scope-button").disabled = $("filters").disabled = true;
    $("map-count").textContent = "";
    $("map-empty").hidden = false;
    $("map-empty").textContent = "No database connected.";
  } finally {
    $("retry").disabled = false;
  }
}
$("retry").addEventListener("click", connect);
setInterval(() => {
  if (state.config && !document.hidden) refreshIssues();
}, 15000);
page();
connect();
