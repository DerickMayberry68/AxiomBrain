"""
AxiomBrain — Web Dashboard Route
Serves a lightweight browser UI for memory browsing and operational controls.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from axiom_brain.config import get_settings

router = APIRouter()


_DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AxiomBrain Dashboard</title>
  <style>
    :root {
      --bg-a: #0b1321;
      --bg-b: #13263a;
      --panel: rgba(11, 21, 34, 0.82);
      --line: rgba(129, 170, 196, 0.35);
      --text: #eff7ff;
      --muted: #9bb7cc;
      --accent: #21c7a8;
      --accent-warm: #f8a553;
      --danger: #ff6f6f;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(circle at 15% -10%, #1f5a7f 0%, transparent 42%),
        radial-gradient(circle at 90% 5%, #6c4d2f 0%, transparent 36%),
        linear-gradient(150deg, var(--bg-a), var(--bg-b));
      font-family: "Space Grotesk", "Trebuchet MS", "Segoe UI", sans-serif;
      min-height: 100vh;
    }

    .wrap {
      width: 100%;
      margin: 0;
      padding: 28px 24px 40px;
      display: grid;
      gap: 16px;
    }

    .panel {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 14px;
      padding: 14px;
      animation: panel-in 360ms ease forwards;
      opacity: 0;
      transform: translateY(8px);
      backdrop-filter: blur(8px);
    }

    .panel:nth-child(2) { animation-delay: 70ms; }
    .panel:nth-child(3) { animation-delay: 140ms; }
    .panel:nth-child(4) { animation-delay: 210ms; }
    .panel:nth-child(5) { animation-delay: 280ms; }
    .panel:nth-child(6) { animation-delay: 350ms; }

    @keyframes panel-in {
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    h1, h2, h3 {
      margin: 0 0 8px;
      line-height: 1.2;
      letter-spacing: 0.03em;
    }

    h1 {
      font-size: clamp(1.4rem, 2.2vw, 2rem);
    }

    h2 {
      font-size: 1rem;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    p {
      margin: 0;
      color: var(--muted);
      font-size: 0.95rem;
    }

    .hero {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .status {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .status strong {
      color: var(--text);
    }

    .grid-2 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }

    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-top: 8px;
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }

    .stat {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: rgba(28, 42, 56, 0.55);
    }

    .stat .name {
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .stat .count {
      margin-top: 4px;
      font-size: 1.35rem;
      font-weight: 700;
    }

    input, select, button {
      border-radius: 8px;
      border: 1px solid var(--line);
      padding: 8px 10px;
      background: rgba(16, 30, 44, 0.9);
      color: var(--text);
      font: inherit;
    }

    input, select {
      width: min(320px, 100%);
    }

    button {
      cursor: pointer;
      background: linear-gradient(135deg, var(--accent), #1ca6dd);
      color: #02262a;
      border: 0;
      font-weight: 700;
    }

    button.secondary {
      background: linear-gradient(135deg, #30495f, #20384c);
      color: var(--text);
      border: 1px solid var(--line);
    }

    button.warm {
      background: linear-gradient(135deg, var(--accent-warm), #f2c35d);
      color: #2b1f10;
    }

    .list {
      margin-top: 10px;
      display: grid;
      gap: 8px;
      max-height: 340px;
      overflow: auto;
      padding-right: 3px;
    }

    .item {
      border: 1px solid var(--line);
      border-radius: 9px;
      padding: 10px;
      background: rgba(16, 30, 44, 0.75);
    }

    .meta {
      color: var(--muted);
      font-size: 0.82rem;
      margin-top: 6px;
    }

    .graph-shell {
      border: 1px solid var(--line);
      border-radius: 10px;
      margin-top: 10px;
      background: rgba(10, 20, 33, 0.75);
      overflow: hidden;
    }

    #graph-svg {
      width: 100%;
      min-height: 340px;
      display: block;
    }

    .edge-list {
      margin-top: 10px;
      max-height: 220px;
      overflow: auto;
      display: grid;
      gap: 6px;
    }

    .pill {
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      margin-right: 4px;
      font-size: 0.75rem;
      color: var(--muted);
    }

    .error {
      color: var(--danger);
      white-space: pre-wrap;
      margin-top: 8px;
      font-size: 0.9rem;
    }

    .ok {
      color: var(--accent);
      margin-top: 8px;
      font-size: 0.9rem;
    }
  </style>
</head>
<body>
  <main class="wrap">
    <section class="panel hero">
      <div>
        <h1>AxiomBrain Dashboard</h1>
        <p>Browse memory, inspect graph links, trigger summaries, and view table stats.</p>
      </div>
      <div class="status" id="status-line">API status: <strong>idle</strong></div>
    </section>

    <section class="panel">
      <h2>Auth</h2>
      <p>Enter your existing API key once. It stays in local browser storage.</p>
      <div class="controls">
        <input id="api-key" type="password" placeholder="X-API-Key value" autocomplete="off" />
        <button id="save-key">Save Key</button>
        <button id="test-key" class="secondary">Test /stats</button>
      </div>
      <div id="auth-message"></div>
    </section>

    <div class="grid-2">
      <section class="panel">
        <h2>Stats</h2>
        <p>Row counts and last-update times for core memory tables.</p>
        <div class="controls">
          <button id="refresh-stats">Refresh Stats</button>
        </div>
        <div class="stats-grid" id="stats-grid"></div>
      </section>

      <section class="panel">
        <h2>Summarization</h2>
        <p>Run the full summarization pipeline manually.</p>
        <div class="controls">
          <label for="hours-back">Hours back</label>
          <input id="hours-back" type="number" min="1" max="168" value="24" />
          <label for="min-thoughts">Min thoughts</label>
          <input id="min-thoughts" type="number" min="1" value="3" />
          <button id="run-summary" class="warm">Run Summaries</button>
        </div>
        <div id="summary-result"></div>
      </section>
    </div>

    <div class="grid-2">
      <section class="panel">
        <h2>Browse Thoughts</h2>
        <div class="controls">
          <label for="thought-limit">Limit</label>
          <input id="thought-limit" type="number" min="1" max="100" value="20" />
          <label for="thought-offset">Offset</label>
          <input id="thought-offset" type="number" min="0" value="0" />
          <input id="thought-source" type="text" placeholder="Optional source filter" />
          <button id="load-thoughts">Load Thoughts</button>
        </div>
        <div class="list" id="thoughts-list"></div>
      </section>

      <section class="panel">
        <h2>Browse Summaries</h2>
        <div class="controls">
          <label for="summary-type">Type</label>
          <select id="summary-type">
            <option value="">All</option>
            <option value="daily_thoughts">daily_thoughts</option>
            <option value="project_rollup">project_rollup</option>
            <option value="person_profile">person_profile</option>
            <option value="all_tables">all_tables</option>
          </select>
          <label for="summary-limit">Limit</label>
          <input id="summary-limit" type="number" min="1" max="100" value="20" />
          <label for="summary-offset">Offset</label>
          <input id="summary-offset" type="number" min="0" value="0" />
          <button id="load-summaries">Load Summaries</button>
        </div>
        <div class="list" id="summaries-list"></div>
      </section>
    </div>

    <section class="panel">
      <h2>Semantic Search</h2>
      <div class="controls">
        <input id="search-query" type="text" placeholder="Search memories (required)" />
        <label for="search-limit">Limit</label>
        <input id="search-limit" type="number" min="1" max="50" value="10" />
        <input id="search-topic" type="text" placeholder="Optional topic filter" />
        <input id="search-person" type="text" placeholder="Optional person filter" />
        <button id="run-search">Search</button>
      </div>
      <div class="list" id="search-results"></div>
    </section>

    <section class="panel">
      <h2>Relationship Graph</h2>
      <p>Load relationships for a node and render a quick graph + edge list.</p>
      <div class="controls">
        <label for="graph-table">Table</label>
        <select id="graph-table">
          <option value="thoughts">thoughts</option>
          <option value="people">people</option>
          <option value="projects">projects</option>
          <option value="ideas">ideas</option>
          <option value="admin">admin</option>
        </select>
        <input id="graph-node-id" type="text" placeholder="Node UUID" />
        <select id="graph-direction">
          <option value="both">both</option>
          <option value="from">from</option>
          <option value="to">to</option>
        </select>
        <input id="graph-rel-type" type="text" placeholder="Optional rel_type filter" />
        <button id="load-graph">Load Graph</button>
      </div>
      <div class="graph-shell">
        <svg id="graph-svg" viewBox="0 0 960 360" aria-label="Relationship graph"></svg>
      </div>
      <div class="edge-list" id="edge-list"></div>
    </section>
  </main>

  <script>
    const KEY_STORAGE = "axiom_dashboard_api_key";
    const SERVER_DEFAULT_API_KEY = __SERVER_DEFAULT_API_KEY__;
    const node = (id) => document.getElementById(id);

    const statusLine = node("status-line");
    const authMessage = node("auth-message");

    function setStatus(text, tone = "normal") {
      statusLine.innerHTML = "API status: <strong>" + text + "</strong>";
      statusLine.style.color = tone === "error" ? "var(--danger)" : "var(--muted)";
    }

    function showMessage(target, text, ok = true) {
      target.className = ok ? "ok" : "error";
      target.textContent = text;
    }

    function formatDate(value) {
      if (!value) return "n/a";
      const dt = new Date(value);
      if (Number.isNaN(dt.getTime())) return String(value);
      return dt.toLocaleString();
    }

    function getApiKey() {
      return node("api-key").value.trim();
    }

    async function apiFetch(path, options = {}) {
      const key = getApiKey();
      if (!key) {
        throw new Error("Set API key first.");
      }
      const headers = new Headers(options.headers || {});
      headers.set("X-API-Key", key);
      if (options.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }

      const response = await fetch(path, { ...options, headers });
      if (!response.ok) {
        let detail = response.status + " " + response.statusText;
        try {
          const data = await response.json();
          if (data && data.detail) detail += " - " + data.detail;
        } catch (_) {}
        throw new Error(detail);
      }
      if (response.status === 204) return null;
      const ctype = response.headers.get("content-type") || "";
      return ctype.includes("application/json") ? response.json() : response.text();
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    function renderStats(data) {
      const root = node("stats-grid");
      if (!data || !data.tables || !data.tables.length) {
        root.innerHTML = "<p class='meta'>No stats found.</p>";
        return;
      }

      root.innerHTML = data.tables.map((t) => (
        "<article class='stat'>" +
          "<div class='name'>" + escapeHtml(t.table) + "</div>" +
          "<div class='count'>" + Number(t.row_count).toLocaleString() + "</div>" +
          "<div class='meta'>Updated: " + escapeHtml(formatDate(t.last_update)) + "</div>" +
        "</article>"
      )).join("");
    }

    function renderThoughts(data) {
      const root = node("thoughts-list");
      if (!data || !data.items || !data.items.length) {
        root.innerHTML = "<p class='meta'>No thoughts found.</p>";
        return;
      }
      root.innerHTML = data.items.map((item) => {
        const tags = (item.topics || []).map((t) => "<span class='pill'>" + escapeHtml(t) + "</span>").join("");
        return (
          "<article class='item'>" +
            "<div>" + escapeHtml(item.content || "") + "</div>" +
            "<div class='meta'>" +
              "id: " + escapeHtml(item.id) + "<br/>" +
              "source: " + escapeHtml(item.source || "n/a") + " | " +
              "routed_to: " + escapeHtml(item.routed_to || "n/a") + " | " +
              "created_at: " + escapeHtml(formatDate(item.created_at)) +
            "</div>" +
            "<div style='margin-top:6px;'>" + tags + "</div>" +
          "</article>"
        );
      }).join("");
    }

    function renderSummaries(data) {
      const root = node("summaries-list");
      if (!data || !data.items || !data.items.length) {
        root.innerHTML = "<p class='meta'>No summaries found.</p>";
        return;
      }
      root.innerHTML = data.items.map((item) => {
        const preview = (item.content || "").slice(0, 400);
        const tags = (item.topics || []).map((t) => "<span class='pill'>" + escapeHtml(t) + "</span>").join("");
        return (
          "<article class='item'>" +
            "<div><strong>" + escapeHtml(item.summary_type) + "</strong> " +
            (item.subject_name ? " - " + escapeHtml(item.subject_name) : "") +
            "</div>" +
            "<div style='margin-top:6px;'>" + escapeHtml(preview) + "</div>" +
            "<div class='meta'>" +
              "id: " + escapeHtml(item.id) + "<br/>" +
              "sources: " + escapeHtml(String(item.source_count)) + " | " +
              "created_at: " + escapeHtml(formatDate(item.created_at)) +
            "</div>" +
            "<div style='margin-top:6px;'>" + tags + "</div>" +
          "</article>"
        );
      }).join("");
    }

    function renderSearch(data) {
      const root = node("search-results");
      if (!data || !data.results || !data.results.length) {
        root.innerHTML = "<p class='meta'>No matching memories.</p>";
        return;
      }
      root.innerHTML = data.results.map((item) => {
        const tags = (item.topics || []).map((t) => "<span class='pill'>" + escapeHtml(t) + "</span>").join("");
        return (
          "<article class='item'>" +
            "<div><strong>" + escapeHtml(item.source_table) + "</strong> " +
            "(score " + Number(item.similarity).toFixed(4) + ")</div>" +
            "<div style='margin-top:6px;'>" + escapeHtml(item.primary_text || "") + "</div>" +
            "<div class='meta'>id: " + escapeHtml(item.id) + " | created_at: " +
            escapeHtml(formatDate(item.created_at)) + "</div>" +
            "<div style='margin-top:6px;'>" + tags + "</div>" +
          "</article>"
        );
      }).join("");
    }

    function drawGraph(table, nodeId, edges) {
      const svg = node("graph-svg");
      const edgeList = node("edge-list");
      svg.innerHTML = "";

      if (!edges || !edges.length) {
        edgeList.innerHTML = "<p class='meta'>No edges found.</p>";
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", "20");
        text.setAttribute("y", "40");
        text.setAttribute("fill", "#9bb7cc");
        text.textContent = "No relationships for this node.";
        svg.appendChild(text);
        return;
      }

      const center = { x: 480, y: 180, label: table + ":" + nodeId.slice(0, 8) };
      const linked = edges.map((edge) => {
        const isFrom = edge.from_table === table && edge.from_id === nodeId;
        return {
          id: isFrom ? edge.to_id : edge.from_id,
          table: isFrom ? edge.to_table : edge.from_table,
          relType: edge.rel_type,
          strength: edge.strength
        };
      });

      const unique = [];
      const seen = new Set();
      linked.forEach((item) => {
        const key = item.table + ":" + item.id;
        if (!seen.has(key)) {
          seen.add(key);
          unique.push(item);
        }
      });

      const radius = Math.max(120, Math.min(150, 30 + unique.length * 16));
      unique.forEach((item, idx) => {
        const angle = (Math.PI * 2 * idx) / unique.length;
        item.x = center.x + Math.cos(angle) * radius;
        item.y = center.y + Math.sin(angle) * radius;
      });

      edges.forEach((edge) => {
        const isFrom = edge.from_table === table && edge.from_id === nodeId;
        const targetKey = (isFrom ? edge.to_table : edge.from_table) + ":" + (isFrom ? edge.to_id : edge.from_id);
        const target = unique.find((u) => (u.table + ":" + u.id) === targetKey);
        if (!target) return;

        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", String(center.x));
        line.setAttribute("y1", String(center.y));
        line.setAttribute("x2", String(target.x));
        line.setAttribute("y2", String(target.y));
        line.setAttribute("stroke", "#4b6d84");
        line.setAttribute("stroke-width", String(1 + (Number(edge.strength) || 0)));
        svg.appendChild(line);

        const mx = (center.x + target.x) / 2;
        const my = (center.y + target.y) / 2;
        const lbl = document.createElementNS("http://www.w3.org/2000/svg", "text");
        lbl.setAttribute("x", String(mx));
        lbl.setAttribute("y", String(my));
        lbl.setAttribute("fill", "#f8a553");
        lbl.setAttribute("font-size", "11");
        lbl.textContent = edge.rel_type;
        svg.appendChild(lbl);
      });

      const centerNode = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      centerNode.setAttribute("cx", String(center.x));
      centerNode.setAttribute("cy", String(center.y));
      centerNode.setAttribute("r", "20");
      centerNode.setAttribute("fill", "#21c7a8");
      svg.appendChild(centerNode);

      const centerText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      centerText.setAttribute("x", String(center.x + 24));
      centerText.setAttribute("y", String(center.y + 3));
      centerText.setAttribute("fill", "#eff7ff");
      centerText.setAttribute("font-size", "12");
      centerText.textContent = center.label;
      svg.appendChild(centerText);

      unique.forEach((item) => {
        const n = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        n.setAttribute("cx", String(item.x));
        n.setAttribute("cy", String(item.y));
        n.setAttribute("r", "12");
        n.setAttribute("fill", "#f8a553");
        svg.appendChild(n);

        const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
        t.setAttribute("x", String(item.x + 15));
        t.setAttribute("y", String(item.y + 3));
        t.setAttribute("fill", "#eff7ff");
        t.setAttribute("font-size", "11");
        t.textContent = item.table + ":" + item.id.slice(0, 8);
        svg.appendChild(t);
      });

      edgeList.innerHTML = edges.map((edge) => (
        "<article class='item'>" +
          "<div><strong>" + escapeHtml(edge.rel_type) + "</strong> " +
          "(strength " + Number(edge.strength).toFixed(2) + ")</div>" +
          "<div class='meta'>" +
            escapeHtml(edge.from_table + ":" + edge.from_id) + " -> " +
            escapeHtml(edge.to_table + ":" + edge.to_id) + "<br/>" +
            "source: " + escapeHtml(edge.source || "n/a") + " | created_at: " +
            escapeHtml(formatDate(edge.created_at)) +
          "</div>" +
        "</article>"
      )).join("");
    }

    async function refreshStats() {
      setStatus("loading /stats");
      const data = await apiFetch("/stats");
      renderStats(data);
      setStatus("stats loaded");
    }

    async function loadThoughts() {
      const limit = Number(node("thought-limit").value || "20");
      const offset = Number(node("thought-offset").value || "0");
      const source = node("thought-source").value.trim();
      const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (source) qs.set("source", source);

      setStatus("loading /thoughts");
      const data = await apiFetch("/thoughts?" + qs.toString());
      renderThoughts(data);
      setStatus("thoughts loaded");
    }

    async function loadSummaries() {
      const limit = Number(node("summary-limit").value || "20");
      const offset = Number(node("summary-offset").value || "0");
      const summaryType = node("summary-type").value;
      const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (summaryType) qs.set("summary_type", summaryType);

      setStatus("loading /summaries");
      const data = await apiFetch("/summaries?" + qs.toString());
      renderSummaries(data);
      setStatus("summaries loaded");
    }

    async function runSearch() {
      const query = node("search-query").value.trim();
      if (!query) {
        throw new Error("Search query is required.");
      }
      const body = {
        query,
        limit: Number(node("search-limit").value || "10")
      };
      const topic = node("search-topic").value.trim();
      const person = node("search-person").value.trim();
      if (topic) body.topic_filter = topic;
      if (person) body.person_filter = person;

      setStatus("running /search");
      const data = await apiFetch("/search", {
        method: "POST",
        body: JSON.stringify(body)
      });
      renderSearch(data);
      setStatus("search complete");
    }

    async function runSummarization() {
      const hoursBack = Number(node("hours-back").value || "24");
      const minThoughtCount = Number(node("min-thoughts").value || "3");
      const resultNode = node("summary-result");
      setStatus("running /summarize");
      const data = await apiFetch("/summarize", {
        method: "POST",
        body: JSON.stringify({
          hours_back: hoursBack,
          min_thought_count: minThoughtCount
        })
      });
      showMessage(
        resultNode,
        "Created daily: " + data.daily_created +
        " | project summaries: " + data.projects_summarized +
        " | people summaries: " + data.people_summarized +
        " | IDs: " + (data.summary_ids || []).join(", "),
        true
      );
      setStatus("summaries complete");
    }

    async function loadGraph() {
      const table = node("graph-table").value;
      const nodeId = node("graph-node-id").value.trim();
      const direction = node("graph-direction").value;
      const relType = node("graph-rel-type").value.trim();

      if (!nodeId) {
        throw new Error("Node UUID is required.");
      }

      const qs = new URLSearchParams({ direction });
      if (relType) qs.set("rel_type", relType);

      setStatus("loading /relationships");
      const data = await apiFetch(
        "/relationships/" + encodeURIComponent(table) + "/" +
        encodeURIComponent(nodeId) + "?" + qs.toString()
      );
      drawGraph(table, nodeId, data.relationships || []);
      setStatus("graph loaded");
    }

    async function withErrorHandling(work) {
      try {
        authMessage.textContent = "";
        await work();
      } catch (err) {
        setStatus("request failed", "error");
        showMessage(authMessage, String(err && err.message ? err.message : err), false);
      }
    }

    function wireEvents() {
      node("save-key").addEventListener("click", () => {
        const key = getApiKey();
        if (!key) {
          showMessage(authMessage, "Enter an API key first.", false);
          return;
        }
        localStorage.setItem(KEY_STORAGE, key);
        showMessage(authMessage, "API key saved for this browser.", true);
      });

      node("test-key").addEventListener("click", () => withErrorHandling(async () => {
        await refreshStats();
        showMessage(authMessage, "API key verified against /stats.", true);
      }));

      node("refresh-stats").addEventListener("click", () => withErrorHandling(refreshStats));
      node("load-thoughts").addEventListener("click", () => withErrorHandling(loadThoughts));
      node("load-summaries").addEventListener("click", () => withErrorHandling(loadSummaries));
      node("run-search").addEventListener("click", () => withErrorHandling(runSearch));
      node("run-summary").addEventListener("click", () => withErrorHandling(runSummarization));
      node("load-graph").addEventListener("click", () => withErrorHandling(loadGraph));
    }

    function restoreApiKey() {
      const existing = localStorage.getItem(KEY_STORAGE);
      if (existing) {
        node("api-key").value = existing;
        return;
      }
      if (SERVER_DEFAULT_API_KEY) {
        node("api-key").value = SERVER_DEFAULT_API_KEY;
      }
    }

    async function init() {
      restoreApiKey();
      wireEvents();
      setStatus("ready");
      if (getApiKey()) {
        await withErrorHandling(async () => {
          await refreshStats();
          await loadThoughts();
          await loadSummaries();
        });
      }
    }

    init();
  </script>
</body>
</html>
"""


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def dashboard() -> HTMLResponse:
    """Serve the built-in web dashboard."""
    settings = get_settings()
    html = _DASHBOARD_HTML.replace(
        "__SERVER_DEFAULT_API_KEY__",
        json.dumps(settings.axiom_api_key),
    )
    return HTMLResponse(content=html)
