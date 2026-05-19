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
