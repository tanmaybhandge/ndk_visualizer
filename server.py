"""
NDK Architecture Platform — FastAPI + tabbed UI (Executive / Technical / Brief)
Audience: Internal Nutanix leadership.

Run:
    pip install fastapi uvicorn python-multipart pyyaml networkx
    python server.py
Then open: http://localhost:8000
"""
from __future__ import annotations
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from ndk_relationship_engine import (
    load_resources, resolve_edges, build_graph,
    render_mermaid, to_json_model,
    build_executive_model, render_executive_mermaid, render_executive_brief,
)

app = FastAPI(title="NDK Architecture Platform")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    yaml_texts = []
    for f in files:
        content = (await f.read()).decode("utf-8", errors="replace")
        yaml_texts.append(content)

    resources = load_resources(yaml_texts)
    edges = resolve_edges(resources)
    technical_mermaid = render_mermaid(resources, edges)
    model = to_json_model(resources, edges, [])
    exec_model = build_executive_model(resources, edges)
    exec_mermaid = render_executive_mermaid(exec_model)
    brief = render_executive_brief(exec_model)

    return JSONResponse({
        "stats": {
            "resources": len(resources),
            "edges": len(edges),
            "resolved": sum(1 for e in edges if e.resolved),
            "ghosts": sum(1 for e in edges if not e.resolved),
        },
        "executive": {
            "mermaid": exec_mermaid,
            "model": exec_model,
            "brief": brief,
        },
        "technical": {
            "mermaid": technical_mermaid,
            "graph": model,
        },
    })


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>NDK Architecture Platform</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  .dropzone { border: 2px dashed #94a3b8; transition: all .2s; }
  .dropzone.dragover { border-color: #1d4ed8; background:#eff6ff; }
  .tab-btn { padding: .6rem 1.2rem; border-bottom: 3px solid transparent;
             color:#475569; font-weight:600; cursor:pointer; }
  .tab-btn.active { color:#1d4ed8; border-color:#1d4ed8; }
  .pill { display:inline-flex; align-items:center; gap:.35rem;
          padding:.2rem .6rem; border-radius:9999px; font-size:.75rem; font-weight:600; }
  .pill-green { background:#dcfce7; color:#15803d; }
  .pill-amber { background:#fef3c7; color:#b45309; }
  .pill-red   { background:#fee2e2; color:#b91c1c; }
  .pill-blue  { background:#dbeafe; color:#1d4ed8; }
  .pill-slate { background:#f1f5f9; color:#334155; }
  .dot { width:.6rem; height:.6rem; border-radius:9999px; display:inline-block; }
  .nutanix-grad { background: linear-gradient(135deg,#0b1f3a 0%,#1d4ed8 100%); }
</style>
</head>
<body class="bg-slate-50 min-h-screen">

<header class="nutanix-grad text-white">
  <div class="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between">
    <div>
      <div class="text-xs uppercase tracking-widest opacity-80">Nutanix · Data Services for Kubernetes</div>
      <h1 class="text-2xl font-bold">NDK Architecture Platform</h1>
    </div>
    <div class="text-xs opacity-90 text-right">
      <div>Internal leadership view</div>
      <div class="opacity-70">Upload YAML manifests → instant DR topology</div>
    </div>
  </div>
</header>

<main class="max-w-7xl mx-auto px-6 py-6">

  <div id="dropzone" class="dropzone rounded-lg p-8 text-center bg-white cursor-pointer mb-6">
    <p class="text-slate-700 font-semibold">Drop YAML manifests here</p>
    <p class="text-slate-500 text-sm mt-1">Application · Remote · ReplicationTarget · StorageCluster · ProtectionPlan · JobScheduler</p>
    <input id="fileInput" type="file" multiple accept=".yaml,.yml" class="hidden" />
  </div>

  <div id="status" class="hidden mb-4 p-3 rounded text-sm"></div>

  <div id="results" class="hidden">

    <!-- Headline metrics strip -->
    <div id="headline" class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6"></div>

    <!-- Tabs -->
    <div class="border-b border-slate-200 mb-4 flex gap-1">
      <div class="tab-btn active" data-tab="exec">Executive View</div>
      <div class="tab-btn" data-tab="tech">Technical View</div>
      <div class="tab-btn" data-tab="brief">Executive Brief</div>
    </div>

    <!-- Executive tab -->
    <section id="tab-exec" class="tab-panel">
      <div class="bg-white rounded-lg shadow-sm border border-slate-200">
        <div class="flex items-center justify-between px-4 py-2 border-b border-slate-200">
          <h2 class="font-semibold text-slate-800">Two-Site DR Topology</h2>
          <div class="flex gap-3 text-xs">
            <button onclick="downloadSvg('exec-diagram','ndk-executive.svg')" class="text-blue-600 hover:underline">Download SVG</button>
            <button onclick="downloadPng('exec-diagram','ndk-executive.png')" class="text-blue-600 hover:underline">Download PNG</button>
          </div>
        </div>
        <div id="exec-diagram" class="p-6"></div>
      </div>
    </section>

    <!-- Technical tab -->
    <section id="tab-tech" class="tab-panel hidden">
      <div class="bg-white rounded-lg shadow-sm border border-slate-200">
        <div class="flex items-center justify-between px-4 py-2 border-b border-slate-200">
          <h2 class="font-semibold text-slate-800">Detailed Resource Graph</h2>
          <button onclick="downloadSvg('tech-diagram','ndk-technical.svg')" class="text-xs text-blue-600 hover:underline">Download SVG</button>
        </div>
        <div id="tech-diagram" class="p-4 overflow-auto"></div>
        <div class="grid grid-cols-2 gap-6 p-4 border-t border-slate-200">
          <div>
            <h3 class="text-sm font-semibold text-slate-700 mb-2">Resources</h3>
            <div id="resourceList" class="space-y-1 text-sm"></div>
          </div>
          <div>
            <h3 class="text-sm font-semibold text-slate-700 mb-2">Relationships</h3>
            <div id="edgeList" class="space-y-1 text-sm"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- Brief tab -->
    <section id="tab-brief" class="tab-panel hidden">
      <div id="briefCard" class="bg-white rounded-lg shadow-sm border border-slate-200 p-8"></div>
    </section>

  </div>
</main>

<script>
mermaid.initialize({ startOnLoad:false, theme:"default",
  flowchart:{ useMaxWidth:true, htmlLabels:true, curve:"basis" }});

const dz = document.getElementById("dropzone");
const fi = document.getElementById("fileInput");
const statusEl = document.getElementById("status");
const results = document.getElementById("results");
let lastResponse = null;

dz.onclick = () => fi.click();
dz.ondragover = e => { e.preventDefault(); dz.classList.add("dragover"); };
dz.ondragleave = () => dz.classList.remove("dragover");
dz.ondrop = e => { e.preventDefault(); dz.classList.remove("dragover"); handleFiles(e.dataTransfer.files); };
fi.onchange = e => handleFiles(e.target.files);

document.querySelectorAll(".tab-btn").forEach(b => b.onclick = () => switchTab(b.dataset.tab));
function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab===name));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("hidden", p.id!=="tab-"+name));
}

async function handleFiles(files) {
  if (!files.length) return;
  showStatus("Processing " + files.length + " file(s)…");
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  try {
    const res = await fetch("/api/upload", { method:"POST", body:fd });
    if (!res.ok) throw new Error("HTTP "+res.status);
    const data = await res.json();
    lastResponse = data;
    await renderAll(data);
    hideStatus();
  } catch (e) { showStatus("Error: "+e.message, true); }
}

function showStatus(m, err){ statusEl.textContent=m;
  statusEl.className = "mb-4 p-3 rounded text-sm " + (err
    ? "bg-red-50 border border-red-200 text-red-800"
    : "bg-blue-50 border border-blue-200 text-blue-800"); }
function hideStatus(){ statusEl.classList.add("hidden"); }

async function renderAll(data) {
  results.classList.remove("hidden");
  renderHeadline(data.executive.brief);
  await renderMermaidInto("exec-diagram", data.executive.mermaid, "execGraph");
  await renderMermaidInto("tech-diagram", data.technical.mermaid, "techGraph");
  renderTechnicalLists(data.technical.graph);
  renderBrief(data.executive.brief);
}

function renderHeadline(brief) {
  const el = document.getElementById("headline");
  el.innerHTML = brief.headline_metrics.map(m => `
    <div class="bg-white rounded-lg border border-slate-200 p-4">
      <div class="text-xs text-slate-500 uppercase tracking-wide">${m.label}</div>
      <div class="mt-1 flex items-center gap-2">
        <span class="dot bg-${toneColor(m.tone)}-500"></span>
        <span class="text-lg font-bold text-slate-800">${m.value}</span>
      </div>
    </div>`).join("");
}
function toneColor(t){ return {green:"emerald",amber:"amber",red:"red",blue:"blue",slate:"slate"}[t]||"slate"; }

async function renderMermaidInto(containerId, src, graphId) {
  const el = document.getElementById(containerId);
  el.innerHTML = "";
  try {
    const { svg } = await mermaid.render(graphId, src);
    el.innerHTML = svg;
  } catch(e) {
    el.innerHTML = `<pre class="text-xs text-red-700 whitespace-pre-wrap">${escapeHtml(src)}</pre>`;
    console.error(e);
  }
}

function renderTechnicalLists(graph) {
  document.getElementById("resourceList").innerHTML = graph.nodes.map(n =>
    `<div class="flex items-center gap-2">
       <span class="dot ${kindBg(n.kind)}"></span>
       <span class="font-mono text-xs text-slate-500">${n.cluster||"primary"}/</span>
       <span class="font-semibold">${n.kind}</span>
       <span class="text-slate-700">/${n.name}</span>
       <span class="text-xs text-slate-400">(${n.namespace})</span>
     </div>`).join("");
  document.getElementById("edgeList").innerHTML = graph.edges.map(e => {
    const cls = e.resolved ? "text-emerald-600" : "text-amber-600";
    const m = e.resolved ? "✓" : "⚠";
    return `<div class="text-xs ${cls}">
       <span class="font-mono">${m} ${short(e.src)}</span>
       <span class="text-slate-400"> --[${e.field}]→ </span>
       <span class="font-mono">${short(e.dst)}</span>
     </div>`;
  }).join("");
}

function renderBrief(b) {
  const counts = Object.entries(b.resource_counts)
    .map(([k,v]) => `<span class="pill pill-slate">${k} <b>${v}</b></span>`).join(" ");
  const caps = b.ndk_capabilities.map(c => `<li>${c}</li>`).join("");
  const notes = b.inferred_notes.length
    ? `<div class="mt-4 p-3 rounded bg-amber-50 border border-amber-200 text-sm text-amber-900">
         <b>Notes:</b><ul class="list-disc ml-5 mt-1">${b.inferred_notes.map(n=>`<li>${n}</li>`).join("")}</ul>
       </div>` : "";
  document.getElementById("briefCard").innerHTML = `
    <div class="border-b border-slate-200 pb-4 mb-4">
      <div class="text-xs uppercase tracking-widest text-blue-700 font-semibold">${b.subtitle}</div>
      <h2 class="text-2xl font-bold text-slate-900 mt-1">${b.title}</h2>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      ${b.headline_metrics.map(m => `
        <div>
          <div class="text-xs text-slate-500 uppercase">${m.label}</div>
          <div class="text-lg font-bold">${m.value}</div>
        </div>`).join("")}
    </div>
    <p class="text-slate-700 leading-relaxed">${b.narrative}</p>
    <h3 class="text-sm font-semibold text-slate-800 mt-6 mb-2">NDK capabilities demonstrated</h3>
    <ul class="list-disc ml-5 text-sm text-slate-700 space-y-1">${caps}</ul>
    <h3 class="text-sm font-semibold text-slate-800 mt-6 mb-2">Resource inventory</h3>
    <div class="flex flex-wrap gap-2">${counts}</div>
    ${notes}
    <div class="mt-6 text-xs text-slate-400">Generated by NDK Architecture Platform · ${new Date().toLocaleString()}</div>
  `;
}

function kindBg(k) {
  const m = { Application:"bg-emerald-500", AppProtectionPlan:"bg-amber-500",
    ProtectionPlan:"bg-blue-500", JobScheduler:"bg-pink-500",
    ReplicationTarget:"bg-red-500", Remote:"bg-violet-500",
    StorageCluster:"bg-sky-500", StorageClass:"bg-sky-400",
    Deployment:"bg-lime-500", StatefulSet:"bg-lime-500",
    Service:"bg-indigo-500", Ingress:"bg-fuchsia-500",
    PersistentVolumeClaim:"bg-amber-400" };
  return m[k] || "bg-slate-400";
}
function short(uid){ const p=uid.split("/"); return p.slice(-2).join("/"); }
function escapeHtml(s){ return s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function downloadSvg(containerId, name) {
  const svg = document.querySelector("#"+containerId+" svg");
  if (!svg) return;
  const blob = new Blob([svg.outerHTML], {type:"image/svg+xml"});
  trigger(blob, name);
}
function downloadPng(containerId, name) {
  const svg = document.querySelector("#"+containerId+" svg");
  if (!svg) return;
  const xml = new XMLSerializer().serializeToString(svg);
  const img = new Image();
  img.onload = () => {
    const c = document.createElement("canvas");
    c.width = svg.viewBox.baseVal.width || svg.clientWidth || 1600;
    c.height = svg.viewBox.baseVal.height || svg.clientHeight || 900;
    const ctx = c.getContext("2d");
    ctx.fillStyle="white"; ctx.fillRect(0,0,c.width,c.height);
    ctx.drawImage(img,0,0,c.width,c.height);
    c.toBlob(b => trigger(b, name), "image/png");
  };
  img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
}
function trigger(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
}
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
