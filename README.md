# NDK Architecture Visualizer

> Turn Nutanix Data Services for Kubernetes (NDK) YAML manifests into executive-ready, two-site DR architecture diagrams — with automatic posture analysis, risk detection, and one-page briefs for leadership.

![Status](https://img.shields.io/badge/status-alpha-orange) ![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-internal-lightgrey)

---

## What it does

**NDK Architecture Visualizer** parses Kubernetes + NDK YAML bundles and produces:

- 🏢 **Executive View** — a clean two-site DR topology diagram for VP/C-level audiences
- 🔧 **Technical View** — detailed resource & relationship graph for DevOps / Platform engineers
- 📄 **Executive Brief** — auto-generated 1-page summary (App · Sites · RPO/RTO · Posture · Capabilities)
- 🟢 **Posture detection** — Protected / Partially Protected / Unprotected
- 🛡 **Risk catalog** — 18+ NDK & Kubernetes rules (missing annotations, whole-namespace selectors, snapshot metadata size, StorageClass mismatches, FSRR misalignment, etc.)
- 📦 **PNG / SVG export** of the executive diagram for slide decks

It understands NDK semantics — not just YAML structure. Cluster-scoped CRs (`Remote`, `StorageCluster`, `StorageClass`, `JobScheduler`) are resolved correctly, cross-cluster references are drawn as replication edges, and missing-but-stated artifacts (e.g. a Protection Plan you described verbally) can be **synthesised and tagged `[inferred]`** so the executive narrative stays complete and honest.

---

## Supported NDK & Kubernetes resources

**NDK CRDs (12):** `StorageCluster`, `Application`, `ApplicationSnapshot`, `ApplicationSnapshotReplication`, `ApplicationSnapshotRestore`, `Remote`, `ReplicationTarget`, `ProtectionPlan`, `AppProtectionPlan`, `JobScheduler`, `FileServerReplicationRelationship`, `AppPlannedFailover` / `AppUnplannedFailover`

**Kubernetes core:** `Deployment`, `StatefulSet`, `DaemonSet`, `Service`, `Ingress`, `ConfigMap`, `Secret`, `PersistentVolumeClaim`, `StorageClass`, `NetworkPolicy`

**Istio:** `Gateway`, `VirtualService`

---

## Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                    YAML Bundle Upload                        │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Deterministic Foundation                                    │
│  ├─ YAML Parser            (PyYAML)                          │
│  ├─ Relationship Engine    (NetworkX) — resolves refs        │
│  │     • namespace-aware                                     │
│  │     • cluster-scoped CR awareness                         │
│  │     • ghost-node detection                                │
│  ├─ Rule Engine            (18+ NDK/K8s rules)               │
│  └─ Executive Model Builder (distils graph → exec facts)     │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Rendering Layer                                             │
│  ├─ Mermaid (executive + technical)                          │
│  ├─ JSON graph model                                         │
│  └─ Markdown brief                                           │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI Server  →  Browser UI (3 tabs + PNG export)         │
└──────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

Get from zero to a rendered DR diagram in under 2 minutes.

### 1. Prerequisites

- **Python 3.10+** — check with `python3 --version`
- **pip** — Python package manager
- A folder of NDK / Kubernetes YAML manifests (or use the bundled `samples/`)

### 2. Clone the repository

```bash
git clone https://github.com/tanmaybhandge/ndk_visualizer.git
cd ndk-visualizer
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` contents:

```text
fastapi
uvicorn
python-multipart
pyyaml
networkx
```

### 4. Run the web server

```bash
python3 server.py
```

You should see:

```text
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

### 5. Open the UI

Navigate to **[http://localhost:8000](http://localhost:8000)** in your browser.

### 6. Upload your YAMLs

Drop your bundle into the upload area — for example:

```text
application.yaml
remote.yaml
replicationtarget.yaml
storage_cluster.yaml
```

The three tabs populate instantly:

| Tab | Audience | Contents |
|---|---|---|
| **Executive View** | VPs / C-level | Two-site DR topology, posture pill, RPO/RTO headline |
| **Technical View** | DevOps / Platform | Full resource graph, edges, ghost nodes |
| **Executive Brief** | Leadership readout | 1-page markdown summary, exportable |

### 7. Export for slides

Click **Download PNG** or **Download SVG** on the Executive View to embed in your deck.

---

### CLI usage (no server)

Prefer the command line? Run the engine directly against a folder:

```bash
python3 ndk_relationship_engine.py ./samples/wordpress-bcdr/
```

Outputs in the current directory:

- `bcdr_plan.mmd` — Mermaid source (paste into [mermaid.live](https://mermaid.live) to preview)
- `bcdr_plan.json` — normalised graph model
- Console report — resources parsed, edges resolved, ghost nodes, risk findings

### Try it with the bundled sample

```bash
python3 ndk_relationship_engine.py ./samples/wordpress-bcdr/
cat bcdr_plan.mmd
```

You should see a 5-node, 4-edge graph representing the WordPress Async-1h DR pattern.

---

## Example output

For a WordPress + NDK Async-1h bundle, the **Executive View** renders:

```text
┌──────────────────────────────┐                          ┌──────────────────────────────┐
│ 🏢 PRIMARY SITE              │                          │ 🏢 DR SITE                   │
│                              │                          │                              │
│  📦 Application              │  ═══════════════════════>│  🔗 Remote Endpoint          │
│     wordpress                │  NDK Async Replication   │     10.38.84.57:2021         │
│     ns: app-volume           │  RPO 1 hour              │                              │
│        │                     │                          │  🎯 Replication Target       │
│        ▼                     │                          │     ns: app-volume-dr        │
│  🛡 Protection Plan          │                          │                              │
│     wp-protect [inferred]    │                          │  📦 Application (restored)   │
│        │                     │                          │     wordpress                │
│        ▼                     │                          │                              │
│  ⏱ Schedule                  │                          │                              │
│  💾 Storage Cluster          │                          │                              │
└──────────────────────────────┘                          └──────────────────────────────┘

Headline:  🟢 Protected · RPO 1 hour · Async · primary → workload-cluster-target
```

---

## The `[inferred]` tag

If you tell the engine an intent that isn't yet expressed in YAML (e.g. *"we run Async with 1h RPO via manual snapshots today"*), it will **synthesise** the missing `ProtectionPlan` and `JobScheduler` so the executive diagram tells the complete story — and clearly tag them `[inferred]`.

To make them real, generate matching CRs and `kubectl apply` them; the tag disappears on the next render.

---

## Project structure

```text
ndk-architecture-visualizer/
├── ndk_relationship_engine.py   # parser + graph + rules + renderers
├── server.py                    # FastAPI app + UI
├── samples/                     # example YAML bundles
│   └── wordpress-bcdr/
├── requirements.txt
└── README.md
```

---

## Roadmap

- [x] v0.1 — 4-CR BCDR bundle, Mermaid output
- [x] v0.2 — 12 NDK CRDs + 18 risk rules + cluster-scoped resolution
- [x] v0.3 — Executive view, posture detection, PNG export, inferred CRs
- [ ] v0.4 — LangGraph agent layer (Architecture Explainer, DR Posture Analyst, Q&A)
- [ ] v0.5 — React + React Flow UI (drag-to-rearrange, drill-down)
- [ ] v0.6 — Helm / Kustomize / Flux input support
- [ ] v0.7 — Git repository ingestion
- [ ] v1.0 — Multi-cluster live mode (read CRs directly via kubeconfig)

---

## Use cases

| Audience | Value |
|---|---|
| **Nutanix leadership** | One-glance DR posture across customer environments |
| **NDK product team** | Visual regression on customer bundles; capability proof points |
| **Customer DevOps** | Validate BCDR plans before failover drills |
| **Platform engineers** | Onboarding new apps to NDK; catching missing annotations early |
| **Solution architects** | As-built documentation generated automatically from cluster state |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | Dependencies not installed | `pip install -r requirements.txt` |
| Port 8000 already in use | Another process is bound | `python3 server.py --port 8080` |
| Empty diagram | YAMLs failed to parse | Check console for parse errors; validate with `kubectl apply --dry-run=client -f` |
| Ghost nodes appearing | Cross-cluster CRs referenced but not uploaded | Upload the missing `Remote` / `ReplicationTarget` / `StorageCluster` YAML |
| `[inferred]` tags everywhere | No `ProtectionPlan` / `JobScheduler` in bundle | Generate real CRs and re-upload |

---

## Contributing

This is currently an internal project. For new rules, add to `RULES` in `ndk_relationship_engine.py` with a clear `id`, `severity`, `kind` filter, and human-readable `message`.

---

## Acknowledgements

Built on the foundation of *Nutanix Data Services for Kubernetes v2.1* — see the official [NDK documentation](https://portal.nutanix.com/) for CRD references and operational guidance.
