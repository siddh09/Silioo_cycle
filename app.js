// ── Constants ──────────────────────────────────────────────────────────────
const ARC = Math.PI * 95;
const VAULT_KEY = "sillicocycle_vault";
let lastResult = null;
let bomChart = null, radarChart = null, compChart = null;

// ── Theme ──────────────────────────────────────────────────────────────────
const themeBtn = document.getElementById("theme-btn");
themeBtn.addEventListener("click", () => {
  document.documentElement.classList.toggle("dark");
  themeBtn.textContent = document.documentElement.classList.contains("dark") ? "☀ Light" : "☾ Dark";
  localStorage.setItem("theme", document.documentElement.classList.contains("dark") ? "dark" : "light");
});
if (localStorage.getItem("theme") === "dark") {
  document.documentElement.classList.add("dark");
  themeBtn.textContent = "☀ Light";
}

// ── Upload & Drop-zone ─────────────────────────────────────────────────────
const dz = document.getElementById("drop-zone");
const fi = document.getElementById("file-input");
const fn = document.getElementById("file-name");
const abtn = document.getElementById("analyze-btn");
let selectedFile = null;

dz.addEventListener("click", () => fi.click());
dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("drag-over"); });
dz.addEventListener("dragleave", () => dz.classList.remove("drag-over"));
dz.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("drag-over"); setFile(e.dataTransfer.files[0]); });
fi.addEventListener("change", () => setFile(fi.files[0]));

function setFile(f) {
  if (!f) return;
  selectedFile = f;
  fn.textContent = "📄 " + f.name + " (" + (f.size / 1024).toFixed(1) + " KB)";
  abtn.disabled = false;
}

// ── Sample download ────────────────────────────────────────────────────────
document.getElementById("sample-btn").addEventListener("click", async () => {
  const blob = await (await fetch("/sample_netlist")).blob();
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "demo_adder.json" });
  a.click(); URL.revokeObjectURL(a.href);
});

// ── Analyze ────────────────────────────────────────────────────────────────
abtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  showError(""); setLoading(true);
  const fd = new FormData();
  fd.append("netlist", selectedFile);
  fd.append("packaging_type", document.getElementById("pkg-select").value);
  try {
    const res = await fetch("/analyze", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok || data.error) { showError(data.error || "Unknown error"); return; }
    lastResult = data;
    renderResults(data);
    vaultAdd(data, selectedFile.name);
  } catch (e) { showError("Network error: " + e.message); }
  finally { setLoading(false); }
});

// ── Render Results ─────────────────────────────────────────────────────────
function renderResults(d) {
  document.getElementById("results").style.display = "block";
  document.getElementById("results").scrollIntoView({ behavior: "smooth" });

  // Gauge
  const arc = document.getElementById("gauge-arc");
  arc.style.strokeDashoffset = ARC * (1 - d.ces / 100);
  arc.style.stroke = scoreColor(d.ces);
  document.getElementById("gauge-val").textContent = d.ces;
  document.getElementById("mci-val").textContent = d.mci;
  document.getElementById("pkg-badge").textContent = d.packaging_type;

  // Sub-score bars
  setBar("tox", d.toxicity_score);
  setBar("recov", d.recoverability_score);
  setBar("dis", d.disassembly_score);

  // Stats
  const e = d.eda_metrics || {};
  document.getElementById("s-cells").textContent = d.total_cells.toLocaleString();
  document.getElementById("s-seq").textContent = (e.flip_flop_percentage || 0).toFixed(1) + "%";
  document.getElementById("s-cong").textContent = ((e.interconnect_congestion || 0) * 100).toFixed(1) + "%";
  document.getElementById("s-depth").textContent = e.logic_depth_estimate || "--";
  document.getElementById("s-ds").textContent = (e.avg_drive_strength || 0).toFixed(2) + "x";
  document.getElementById("s-xor").textContent = (e.xor_percentage || 0).toFixed(1) + "%";

  // EDA breakdown bars
  const tot = d.total_cells || 1;
  setEdaBar("eda-arith", e.arithmetic_cells, tot);
  setEdaBar("eda-clock", e.clock_tree_cells, tot);
  setEdaBar("eda-route", e.routing_critical_cells, tot);
  setEdaBar("eda-seq",   e.sequential_cells, tot);

  // BOM Table
  const tb = document.getElementById("bom-body");
  tb.innerHTML = "";
  d.bom.forEach(m => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${m.material_name}</strong></td><td style="color:var(--muted)">${m.vlsi_use}</td>
      <td>${rohsBadge(m.rohs_status)}</td><td style="text-align:center">${m.eol_recycle_percentage}</td>
      <td style="text-align:center">${toxBadge(m.toxicity_score)}</td>
      <td style="text-align:right;font-family:monospace">${m.mass_g.toExponential(3)}</td>`;
    tb.appendChild(tr);
  });

  // Recommendations
  document.getElementById("rec-list").innerHTML = "";
  buildRecs(d).forEach(r => {
    const div = document.createElement("div");
    div.className = "rec-item";
    div.innerHTML = `<div class="rec-icon" style="background:${r.bg}">${r.icon}</div><div class="rec-text">${r.text}</div>`;
    document.getElementById("rec-list").appendChild(div);
  });

  // Charts
  renderBomChart(d.mass_breakdown);
  renderRadarChart(d);
}

// ── Charts ─────────────────────────────────────────────────────────────────
function renderBomChart(mb) {
  const ctx = document.getElementById("bom-chart").getContext("2d");
  if (bomChart) bomChart.destroy();
  bomChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: Object.keys(mb),
      datasets: [{ data: Object.values(mb), backgroundColor: ["#1A56DB","#00C896","#F59E0B","#3B9EE8"], borderWidth: 0, hoverOffset: 8 }]
    },
    options: { cutout: "70%", plugins: { legend: { position: "bottom", labels: { color: getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || "#111" } } } }
  });
}

function renderRadarChart(d) {
  const ctx = document.getElementById("radar-chart").getContext("2d");
  if (radarChart) radarChart.destroy();
  const e = d.eda_metrics || {};
  radarChart = new Chart(ctx, {
    type: "radar",
    data: {
      labels: ["Toxicity", "Recoverability", "Disassembly", "Gate Density", "Circularity (MCI×100)"],
      datasets: [{
        label: "Design Score",
        data: [d.toxicity_score, d.recoverability_score, d.disassembly_score,
               Math.min(100, (e.gate_density_factor || 1) * 33), d.mci * 100],
        backgroundColor: "rgba(26,86,219,0.15)",
        borderColor: "#1A56DB",
        pointBackgroundColor: "#1A56DB",
        borderWidth: 2
      }]
    },
    options: { scales: { r: { min: 0, max: 100, ticks: { display: false }, grid: { color: "#DDE3EE" }, pointLabels: { color: "#5A6A8A", font: { size: 11 } } } }, plugins: { legend: { display: false } } }
  });
}

// ── Design Vault ───────────────────────────────────────────────────────────
function vaultGet() { try { return JSON.parse(localStorage.getItem(VAULT_KEY) || "[]"); } catch { return []; } }
function vaultSave(v) { localStorage.setItem(VAULT_KEY, JSON.stringify(v)); }

function vaultAdd(data, filename) {
  const vault = vaultGet();
  vault.unshift({ filename, ces: data.ces, toxicity_score: data.toxicity_score, recoverability_score: data.recoverability_score, disassembly_score: data.disassembly_score, mci: data.mci, total_cells: data.total_cells, packaging_type: data.packaging_type, ts: new Date().toLocaleString() });
  if (vault.length > 10) vault.pop();
  vaultSave(vault);
  renderVault();
}

function renderVault() {
  const vault = vaultGet();
  const el = document.getElementById("vault-list");
  const empty = document.getElementById("vault-empty");
  const compBtn = document.getElementById("compare-btn");
  if (!vault.length) { el.innerHTML = ""; empty.style.display = "block"; compBtn.style.display = "none"; return; }
  empty.style.display = "none";
  compBtn.style.display = vault.length >= 2 ? "inline-block" : "none";
  el.innerHTML = vault.map((v, i) => `
    <div class="vault-item" data-i="${i}">
      <div class="vault-chip"><span class="vault-name">${v.filename}</span><span class="vault-time">${v.ts}</span></div>
      <div class="vault-scores">
        <span class="vault-score" style="color:${scoreColor(v.ces)}">CES ${v.ces}</span>
        <span class="vault-score">MCI ${v.mci}</span>
        <span class="vault-score">${v.total_cells.toLocaleString()} cells</span>
        <span class="vault-score">${v.packaging_type}</span>
      </div>
    </div>`).join("");
}

document.getElementById("vault-clear").addEventListener("click", () => {
  vaultSave([]); renderVault();
  document.getElementById("compare-section").style.display = "none";
});

document.getElementById("compare-btn").addEventListener("click", () => {
  const vault = vaultGet();
  const ctx = document.getElementById("comp-chart").getContext("2d");
  if (compChart) compChart.destroy();
  document.getElementById("compare-section").style.display = "block";
  document.getElementById("compare-section").scrollIntoView({ behavior: "smooth" });
  compChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: vault.map(v => v.filename.replace(".json", "")),
      datasets: [
        { label: "Toxicity",        data: vault.map(v => v.toxicity_score),       backgroundColor: "#00C896" },
        { label: "Recoverability",  data: vault.map(v => v.recoverability_score), backgroundColor: "#3B9EE8" },
        { label: "Disassembly",     data: vault.map(v => v.disassembly_score),    backgroundColor: "#F59E0B" },
        { label: "CES (Total)",     data: vault.map(v => v.ces),                  backgroundColor: "#1A56DB" },
      ]
    },
    options: {
      responsive: true, scales: { y: { min: 0, max: 100 } },
      plugins: { legend: { position: "top" } }
    }
  });
});

// ── Helpers ────────────────────────────────────────────────────────────────
function setBar(id, val) {
  const c = scoreColor(val);
  document.getElementById(id + "-val").textContent = val;
  document.getElementById(id + "-val").style.color = c;
  document.getElementById(id + "-bar").style.cssText = `width:${val}%;background:${c}`;
}

function setEdaBar(id, val, total) {
  const pct = total ? (val / total * 100) : 0;
  const el = document.getElementById(id);
  if (el) { el.style.width = pct + "%"; el.nextElementSibling && (el.nextElementSibling.textContent = val.toLocaleString()); }
}

function scoreColor(s) {
  if (s >= 80) return "#00C896";
  if (s >= 60) return "#1A56DB";
  if (s >= 30) return "#F59E0B";
  return "#EF4444";
}

function rohsBadge(s) {
  const u = s.toUpperCase();
  if (u.includes("RESTRICT")) return `<span class="badge badge-red">${s}</span>`;
  if (u.includes("SVHC") || u.includes("CHECK")) return `<span class="badge badge-amber">${s}</span>`;
  return `<span class="badge badge-green">${s}</span>`;
}

function toxBadge(n) {
  return `<span class="badge ${n >= 7 ? "badge-red" : n >= 4 ? "badge-amber" : "badge-green"}">${n}</span>`;
}

function buildRecs(d) {
  const recs = [];
  const pkg = (d.packaging_type || "").toUpperCase().replace(" ", "-");
  if (pkg === "FC-BGA") recs.push({ icon: "📦", bg: "#fef3c7", text: "<strong>Switch packaging:</strong> FC-BGA carries a −25 pt disassembly penalty. Migrate to BGA (+15 pts) or QFP (+25 pts)." });
  else if (pkg === "BGA") recs.push({ icon: "📦", bg: "#fef3c7", text: "<strong>Consider QFP:</strong> BGA has a −10 pt disassembly penalty. QFP packaging would recover 10 points." });
  const restricted = (d.bom || []).filter(m => m.rohs_status.toUpperCase().includes("RESTRICT"));
  if (restricted.length) recs.push({ icon: "⚠️", bg: "#fee2e2", text: `<strong>RESTRICTED material(s):</strong> ${restricted.map(m => m.material_name).join(", ")}. Immediate RoHS review required.` });
  if (d.recoverability_score < 40) recs.push({ icon: "♻️", bg: "#dcfce7", text: "<strong>Improve recoverability:</strong> Average EOL rate below 40%. Prefer materials with established recycling streams." });
  if (d.toxicity_score < 50) recs.push({ icon: "🧪", bg: "#ede9fe", text: "<strong>High toxicity detected:</strong> Review high-scoring materials and explore compliant substitutes." });
  const e = d.eda_metrics || {};
  if ((e.interconnect_congestion || 0) > 0.6) recs.push({ icon: "🔀", bg: "#e0f2fe", text: `<strong>High routing congestion (${((e.interconnect_congestion) * 100).toFixed(0)}%):</strong> Consider replacing MUX/XOR-heavy blocks with arithmetic optimised cells.` });
  if (!recs.length) recs.push({ icon: "✅", bg: "#dcfce7", text: "<strong>No critical issues found.</strong> Design scores well across all sustainability criteria." });
  return recs;
}

function setLoading(on) {
  document.getElementById("loading").style.display = on ? "block" : "none";
  abtn.disabled = on;
  if (on) document.getElementById("results").style.display = "none";
}
function showError(msg) {
  const b = document.getElementById("error-box");
  b.style.display = msg ? "block" : "none";
  b.textContent = msg ? "⚠ " + msg : "";
}

// ── PDF ────────────────────────────────────────────────────────────────────
document.getElementById("pdf-btn").addEventListener("click", async () => {
  if (!lastResult) return;
  const btn = document.getElementById("pdf-btn");
  btn.textContent = "⏳ Generating…"; btn.disabled = true;
  try {
    const res = await fetch("/download_pdf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(lastResult) });
    if (!res.ok) { showError("PDF generation failed."); return; }
    const blob = await res.blob();
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "SilicoCycle_Report.pdf" });
    a.click(); URL.revokeObjectURL(a.href);
  } catch (e) { showError("PDF error: " + e.message); }
  btn.textContent = "⬇ Download PDF Report"; btn.disabled = false;
});

// ── Reset ──────────────────────────────────────────────────────────────────
document.getElementById("reset-btn").addEventListener("click", () => {
  document.getElementById("results").style.display = "none";
  document.getElementById("compare-section").style.display = "none";
  selectedFile = null; fi.value = ""; fn.textContent = ""; abtn.disabled = true; lastResult = null;
  window.scrollTo({ top: 0, behavior: "smooth" });
});

// ── Init ───────────────────────────────────────────────────────────────────
renderVault();
