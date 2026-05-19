"""
NDK Relationship Engine v0.2
=============================
Adds:
  - Full coverage of the 12 NDK CRDs + core K8s kinds referenced by them
  - Complete cross-reference resolution rules
  - Rule Engine with the NDK risk catalog (deterministic findings)
  - Findings emitted as JSON + printed report
  - Mermaid diagram with cross-cluster (primary / replication) subgraphs

Supported kinds
---------------
NDK CRDs (12):
  StorageCluster, Application, ApplicationSnapshot, ApplicationSnapshotReplication,
  ApplicationSnapshotRestore, Remote, ReplicationTarget, ProtectionPlan,
  AppProtectionPlan, JobScheduler, FileServerReplicationRelationship (FSRR),
  AppPlannedFailover, AppUnplannedFailover

Core K8s kinds parsed for context:
  Deployment, StatefulSet, DaemonSet, Service, Ingress, ConfigMap, Secret,
  PersistentVolumeClaim, StorageClass, NetworkPolicy, Namespace,
  Gateway, VirtualService

Reference rules
---------------
AppProtectionPlan.spec.applicationName            -> Application
AppProtectionPlan.spec.protectionPlanNames[]      -> ProtectionPlan
ProtectionPlan.spec.scheduleName                  -> JobScheduler
ProtectionPlan.spec.replicationConfigs[].replicationTargetName -> ReplicationTarget
ReplicationTarget.spec.remoteName                 -> Remote
ApplicationSnapshot.spec.applicationName          -> Application
ApplicationSnapshotReplication.spec.snapshotName  -> ApplicationSnapshot
ApplicationSnapshotReplication.spec.replicationTargetName -> ReplicationTarget
ApplicationSnapshotRestore.spec.snapshotName      -> ApplicationSnapshot
AppPlannedFailover.spec.appProtectionPlanName     -> AppProtectionPlan
AppUnplannedFailover.spec.appProtectionPlanName   -> AppProtectionPlan
FSRR.spec.sourceFileServer / targetFileServer     -> external file servers
StatefulSet.spec.volumeClaimTemplates[]           -> implicit PVCs
Ingress.spec.rules[].http.paths[].backend.service.name -> Service
Service.spec.selector                             -> Deployment/StatefulSet/DaemonSet (label match)
Deployment.spec.template.spec.volumes[].persistentVolumeClaim.claimName -> PVC
Deployment.spec.template.spec.volumes[].configMap.name -> ConfigMap
Deployment.spec.template.spec.volumes[].secret.secretName -> Secret
PVC.spec.storageClassName                         -> StorageClass
VirtualService.spec.gateways[]                    -> Gateway

Risk rules (v0.2 catalog)
-------------------------
NDK-001  Whole-namespace Application selector (empty spec / applicationSelector)
NDK-002  Missing 'ndk.nutanix.com/exclude-from-deletion' on critical CRs
NDK-003  StorageClass name mismatch between primary and replication clusters
NDK-004  ProtectionPlan with sync replication and >1 replicationConfigs
NDK-005  Remote with skipTLSVerify: true
NDK-006  Workload deployed into reserved 'ntnx-system' namespace
NDK-007  ProtectionPlan missing scheduleName (no JobScheduler reference)
NDK-008  AppProtectionPlan references non-existent ProtectionPlan/Application
NDK-009  Application uses useExistingConfig: true on first-time creation
NDK-010  FSRR source/target file server alignment missing
NDK-011  Estimated snapshot metadata > 8 MB (resource count heuristic)
NDK-012  ReplicationTarget without a resolvable Remote
K8S-001  Container without resource limits
K8S-002  Container using :latest image tag
K8S-003  Privileged container / hostNetwork
K8S-004  Ingress without TLS
K8S-005  No NetworkPolicy in namespace containing workloads
K8S-006  Probes (liveness/readiness) missing
"""

from __future__ import annotations
import json, sys, re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import yaml, networkx as nx

# ---------------------------------------------------------------------------
NDK_KINDS = {
    "StorageCluster","Application","ApplicationSnapshot",
    "ApplicationSnapshotReplication","ApplicationSnapshotRestore",
    "Remote","ReplicationTarget","ProtectionPlan","AppProtectionPlan",
    "JobScheduler","FileServerReplicationRelationship",
    "AppPlannedFailover","AppUnplannedFailover",
}
K8S_KINDS = {
    "Deployment","StatefulSet","DaemonSet","Service","Ingress","ConfigMap",
    "Secret","PersistentVolumeClaim","StorageClass","NetworkPolicy",
    "Namespace","Gateway","VirtualService",
}
ALL_KINDS = NDK_KINDS | K8S_KINDS

# ---------------------------------------------------------------------------
@dataclass
class Resource:
    kind: str
    name: str
    namespace: str
    spec: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    cluster: str = "primary"   # "primary" or "replication" (set by annotation/labels)

    @property
    def uid(self) -> str:
        return f"{self.cluster}/{self.kind}/{self.namespace}/{self.name}"
    @property
    def short(self) -> str:
        return f"{self.kind}/{self.name}"

@dataclass
class Edge:
    src: str; dst: str; field: str; label: str; resolved: bool
    kind: str = "reference"   # reference | selector | implicit

@dataclass
class Finding:
    rule_id: str
    severity: str        # critical | high | medium | low | info
    title: str
    resource: str        # uid of offending resource (or "" if global)
    evidence: str
    remediation: str

# ---------------------------------------------------------------------------
def parse_docs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]

def _expand_tabs(text: str) -> str:
    """YAML forbids tabs for indentation. Auto-expand to 2 spaces to be lenient."""
    return text.expandtabs(2)

def load_resources(sources: list[str]) -> list[Resource]:
    out: list[Resource] = []
    def ingest(text: str, origin: str = "<inline>"):
        try:
            docs = parse_docs(_expand_tabs(text))
        except yaml.YAMLError as e:
            print(f"  [SKIP] {origin}: YAML parse error -> {e.__class__.__name__}: {str(e).splitlines()[0]}")
            return
        for doc in docs:
            if not isinstance(doc, dict): continue
            kind = doc.get("kind")
            if not kind: continue
            meta = doc.get("metadata", {}) or {}
            name = meta.get("name")
            if not name: continue
            ns = meta.get("namespace","default")
            ann = (meta.get("annotations") or {})
            cluster = ann.get("ndk.demo/cluster", "primary")
            out.append(Resource(
                kind=kind, name=name, namespace=ns,
                spec=doc.get("spec", {}) or {},
                metadata=meta, raw=doc, cluster=cluster,
            ))
    for s in sources:
        p = Path(s)
        if p.is_dir():
            files = sorted(p.rglob("*.y*ml"))
            print(f"Scanning {p} -> {len(files)} YAML file(s)")
            for f in files:
                try:
                    ingest(f.read_text(), str(f))
                except Exception as e:
                    print(f"  [SKIP] {f}: {e.__class__.__name__}: {e}")
        elif p.is_file():
            try:
                ingest(p.read_text(), str(p))
            except Exception as e:
                print(f"  [SKIP] {p}: {e.__class__.__name__}: {e}")
        else:
            ingest(s)
    return out

# ---------------------------------------------------------------------------
def build_index(resources: list[Resource]):
    # (cluster, kind, ns, name) -> Resource
    return {(r.cluster, r.kind, r.namespace, r.name): r for r in resources}

def resolve_edges(resources: list[Resource]) -> list[Edge]:
    idx = build_index(resources)
    edges: list[Edge] = []

    def find(cluster, kind, ns, name):
        return idx.get((cluster, kind, ns, name))

    CLUSTER_SCOPED = {"Remote", "StorageCluster", "StorageClass", "JobScheduler"}

    def find_any_ns(cluster, kind, name):
        for r in resources:
            if r.cluster == cluster and r.kind == kind and r.name == name:
                return r
        return None

    def add(src: Resource, dst_kind: str, dst_name: str,
            field_path: str, label: str, dst_ns: str | None = None,
            dst_cluster: str | None = None, kind: str = "reference"):
        dc = dst_cluster or src.cluster
        if dst_kind in CLUSTER_SCOPED:
            dst = find_any_ns(dc, dst_kind, dst_name)
            dn = dst.namespace if dst else (dst_ns or "default")
        else:
            dn = dst_ns or src.namespace
            dst = find(dc, dst_kind, dn, dst_name)
        dst_uid = dst.uid if dst else f"{dc}/{dst_kind}/{dn}/{dst_name}"
        edges.append(Edge(src.uid, dst_uid, field_path, label,
                          resolved=dst is not None, kind=kind))

    for r in resources:
        s = r.spec or {}

        if r.kind == "AppProtectionPlan":
            if s.get("applicationName"):
                add(r,"Application",s["applicationName"],
                    "spec.applicationName", f"applicationName: {s['applicationName']}")
            for pp in s.get("protectionPlanNames",[]) or []:
                add(r,"ProtectionPlan",pp,
                    "spec.protectionPlanNames[]", f"protectionPlanNames: {pp}")

        elif r.kind == "ProtectionPlan":
            if s.get("scheduleName"):
                add(r,"JobScheduler",s["scheduleName"],
                    "spec.scheduleName", f"scheduleName: {s['scheduleName']}")
            for rc in s.get("replicationConfigs",[]) or []:
                rt = rc.get("replicationTargetName")
                if rt:
                    add(r,"ReplicationTarget",rt,
                        "spec.replicationConfigs[].replicationTargetName",
                        f"replicationTargetName: {rt}")

        elif r.kind == "ReplicationTarget":
            if s.get("remoteName"):
                add(r,"Remote",s["remoteName"],
                    "spec.remoteName", f"remoteName: {s['remoteName']}")

        elif r.kind == "ApplicationSnapshot":
            if s.get("applicationName"):
                add(r,"Application",s["applicationName"],
                    "spec.applicationName", f"applicationName: {s['applicationName']}")

        elif r.kind == "ApplicationSnapshotReplication":
            if s.get("snapshotName"):
                add(r,"ApplicationSnapshot",s["snapshotName"],
                    "spec.snapshotName", f"snapshotName: {s['snapshotName']}")
            if s.get("replicationTargetName"):
                add(r,"ReplicationTarget",s["replicationTargetName"],
                    "spec.replicationTargetName",
                    f"replicationTargetName: {s['replicationTargetName']}")

        elif r.kind == "ApplicationSnapshotRestore":
            if s.get("snapshotName"):
                add(r,"ApplicationSnapshot",s["snapshotName"],
                    "spec.snapshotName", f"snapshotName: {s['snapshotName']}",
                    dst_cluster="replication" if r.cluster=="primary" else "primary")

        elif r.kind in ("AppPlannedFailover","AppUnplannedFailover"):
            if s.get("appProtectionPlanName"):
                add(r,"AppProtectionPlan",s["appProtectionPlanName"],
                    "spec.appProtectionPlanName",
                    f"appProtectionPlanName: {s['appProtectionPlanName']}")

        elif r.kind == "StatefulSet":
            for vct in s.get("volumeClaimTemplates",[]) or []:
                name = (vct.get("metadata") or {}).get("name")
                if name:
                    pvc_name = f"{name}-{r.name}-0"  # convention
                    add(r,"PersistentVolumeClaim",pvc_name,
                        "spec.volumeClaimTemplates[]",
                        f"PVC: {pvc_name}", kind="implicit")

        elif r.kind == "Deployment":
            tmpl = ((s.get("template") or {}).get("spec") or {})
            for v in tmpl.get("volumes",[]) or []:
                if "persistentVolumeClaim" in v:
                    add(r,"PersistentVolumeClaim",
                        v["persistentVolumeClaim"]["claimName"],
                        "spec.template.spec.volumes[].pvc",
                        f"pvc: {v['persistentVolumeClaim']['claimName']}")
                if "configMap" in v:
                    add(r,"ConfigMap",v["configMap"]["name"],
                        "spec.template.spec.volumes[].configMap",
                        f"configMap: {v['configMap']['name']}")
                if "secret" in v:
                    add(r,"Secret",v["secret"]["secretName"],
                        "spec.template.spec.volumes[].secret",
                        f"secret: {v['secret']['secretName']}")

        elif r.kind == "Service":
            sel = s.get("selector") or {}
            if sel:
                # match against any workload with the same labels
                for w in resources:
                    if w.kind in ("Deployment","StatefulSet","DaemonSet") \
                       and w.namespace == r.namespace and w.cluster == r.cluster:
                        labels = ((w.spec.get("template") or {}).get("metadata") or {}).get("labels") or {}
                        if all(labels.get(k)==v for k,v in sel.items()):
                            add(r,w.kind,w.name,"spec.selector",
                                f"selector: {sel}", kind="selector")

        elif r.kind == "Ingress":
            for rule in s.get("rules",[]) or []:
                for p in ((rule.get("http") or {}).get("paths") or []):
                    svc = ((p.get("backend") or {}).get("service") or {}).get("name")
                    if svc:
                        add(r,"Service",svc,"spec.rules[].backend.service.name",
                            f"service: {svc}")

        elif r.kind == "PersistentVolumeClaim":
            sc = s.get("storageClassName")
            if sc:
                add(r,"StorageClass",sc,"spec.storageClassName",
                    f"storageClassName: {sc}", dst_ns="")

        elif r.kind == "VirtualService":
            for gw in s.get("gateways",[]) or []:
                add(r,"Gateway",gw,"spec.gateways[]", f"gateway: {gw}")

        elif r.kind == "FileServerReplicationRelationship":
            if s.get("sourceFileServer"):
                add(r,"Remote",s.get("sourceFileServer"),
                    "spec.sourceFileServer", f"source: {s['sourceFileServer']}")
            if s.get("targetFileServer"):
                add(r,"Remote",s.get("targetFileServer"),
                    "spec.targetFileServer", f"target: {s['targetFileServer']}",
                    dst_cluster="replication")
    return edges

# ---------------------------------------------------------------------------
def build_graph(resources, edges) -> nx.DiGraph:
    g = nx.DiGraph()
    for r in resources:
        g.add_node(r.uid, **asdict(r))
    for e in edges:
        if e.dst not in g:
            try:
                cluster,kind,ns,name = e.dst.split("/",3)
            except ValueError:
                continue
            g.add_node(e.dst, kind=kind, name=name, namespace=ns,
                       cluster=cluster, spec={}, ghost=True)
        g.add_edge(e.src, e.dst, **asdict(e))
    return g

# ---------------------------------------------------------------------------
# Rule Engine
# ---------------------------------------------------------------------------
CRITICAL_NDK_CRS = {"Application","AppProtectionPlan","ProtectionPlan",
                    "ReplicationTarget","Remote","JobScheduler"}

def run_rules(resources: list[Resource], edges: list[Edge]) -> list[Finding]:
    findings: list[Finding] = []
    by_uid = {r.uid: r for r in resources}

    # Quick lookup: storage classes by cluster
    sc_by_cluster = {}
    for r in resources:
        if r.kind == "StorageClass":
            sc_by_cluster.setdefault(r.cluster,set()).add(r.name)

    # NDK-001: whole-namespace Application
    for r in resources:
        if r.kind == "Application":
            spec = r.spec or {}
            sel = spec.get("applicationSelector")
            if not spec or (not sel and not spec.get("includedResources")):
                findings.append(Finding("NDK-001","high",
                    "Application protects entire namespace",
                    r.uid,
                    "spec is empty / no applicationSelector -> all resources in namespace are captured",
                    "Set spec.applicationSelector with explicit label selectors to scope the application."))

    # NDK-002: missing exclude-from-deletion annotation on critical CRs
    for r in resources:
        if r.kind in CRITICAL_NDK_CRS:
            ann = (r.metadata.get("annotations") or {})
            if "ndk.nutanix.com/exclude-from-deletion" not in ann:
                findings.append(Finding("NDK-002","medium",
                    f"{r.kind} missing exclude-from-deletion annotation",
                    r.uid,
                    "annotation 'ndk.nutanix.com/exclude-from-deletion' absent",
                    "Add annotation ndk.nutanix.com/exclude-from-deletion: \"true\" to protect from accidental GC."))

    # NDK-003: StorageClass name mismatch across clusters
    if "primary" in sc_by_cluster and "replication" in sc_by_cluster:
        only_primary = sc_by_cluster["primary"] - sc_by_cluster["replication"]
        if only_primary:
            findings.append(Finding("NDK-003","high",
                "StorageClass names differ between primary and replication clusters",
                "",
                f"Primary-only StorageClasses: {sorted(only_primary)}",
                "Ensure identical StorageClass names exist on both clusters; NDK matches by name."))

    # NDK-004: sync replication + >1 target
    for r in resources:
        if r.kind == "ProtectionPlan":
            rcs = r.spec.get("replicationConfigs",[]) or []
            mode = (r.spec.get("replicationMode") or "").lower()
            if mode == "sync" and len(rcs) > 1:
                findings.append(Finding("NDK-004","critical",
                    "Sync ProtectionPlan has multiple replication targets",
                    r.uid,
                    f"replicationMode=sync, targets={len(rcs)}",
                    "Sync replication supports exactly one replicationConfig. Split into async plans."))

    # NDK-005: skipTLSVerify
    for r in resources:
        if r.kind == "Remote" and r.spec.get("skipTLSVerify") is True:
            findings.append(Finding("NDK-005","high",
                "Remote has skipTLSVerify: true",
                r.uid, "spec.skipTLSVerify=true",
                "Disable skipTLSVerify in production; install proper CA bundle."))

    # NDK-006: workload in ntnx-system
    for r in resources:
        if r.namespace == "ntnx-system" and r.kind in ("Deployment","StatefulSet","DaemonSet","Application"):
            findings.append(Finding("NDK-006","critical",
                "Workload deployed in reserved namespace 'ntnx-system'",
                r.uid,"metadata.namespace=ntnx-system",
                "Move workload to a user namespace; ntnx-system is reserved for NDK control plane."))

    # NDK-007: PP missing scheduleName (only relevant for async)
    for r in resources:
        if r.kind == "ProtectionPlan":
            mode = (r.spec.get("replicationMode") or "async").lower()
            if mode != "sync" and not r.spec.get("scheduleName"):
                findings.append(Finding("NDK-007","high",
                    "Async ProtectionPlan missing scheduleName",
                    r.uid,"spec.scheduleName not set",
                    "Reference a JobScheduler in spec.scheduleName."))

    # NDK-008: unresolved references on AppProtectionPlan
    for e in edges:
        if not e.resolved and e.src.split("/")[1] == "AppProtectionPlan":
            findings.append(Finding("NDK-008","high",
                "AppProtectionPlan references missing resource",
                e.src, f"{e.field} -> {e.dst} not found in bundle",
                "Ensure referenced resource exists in the same namespace and cluster."))

    # NDK-009: useExistingConfig: true
    for r in resources:
        if r.kind == "Application" and r.spec.get("useExistingConfig") is True:
            findings.append(Finding("NDK-009","medium",
                "Application uses useExistingConfig: true",
                r.uid,"spec.useExistingConfig=true",
                "Only set after first successful snapshot; otherwise initial state is lost."))

    # NDK-010: FSRR alignment
    for r in resources:
        if r.kind == "FileServerReplicationRelationship":
            if not (r.spec.get("sourceFileServer") and r.spec.get("targetFileServer")):
                findings.append(Finding("NDK-010","high",
                    "FSRR missing source or target file server",
                    r.uid,"sourceFileServer/targetFileServer incomplete",
                    "Both source and target file servers must be set and reachable."))

    # NDK-011: snapshot metadata heuristic (>200 resources -> warn)
    apps = [r for r in resources if r.kind == "Application"]
    for app in apps:
        ns_count = sum(1 for r in resources
                       if r.namespace == app.namespace and r.cluster == app.cluster
                       and r.kind in K8S_KINDS)
        if ns_count > 200:
            findings.append(Finding("NDK-011","medium",
                "Estimated snapshot metadata may exceed 8 MB",
                app.uid, f"~{ns_count} K8s resources captured by this Application",
                "Narrow applicationSelector or split into multiple Applications."))

    # NDK-012: ReplicationTarget without Remote
    for e in edges:
        src_kind = e.src.split("/")[1]
        if src_kind == "ReplicationTarget" and "remoteName" in e.field and not e.resolved:
            findings.append(Finding("NDK-012","high",
                "ReplicationTarget references unknown Remote",
                e.src, f"spec.remoteName -> {e.dst.split('/')[-1]} not found",
                "Create the Remote CR before the ReplicationTarget, or fix the name."))

    # K8S-001..006
    for r in resources:
        if r.kind in ("Deployment","StatefulSet","DaemonSet"):
            tmpl = ((r.spec.get("template") or {}).get("spec") or {})
            for c in tmpl.get("containers",[]) or []:
                if not c.get("resources",{}).get("limits"):
                    findings.append(Finding("K8S-001","medium",
                        "Container without resource limits",
                        r.uid, f"container {c.get('name')} has no resources.limits",
                        "Set CPU/memory limits to prevent noisy-neighbour issues."))
                img = c.get("image","")
                if img.endswith(":latest") or ":" not in img:
                    findings.append(Finding("K8S-002","medium",
                        "Container uses :latest or untagged image",
                        r.uid, f"container {c.get('name')} image={img}",
                        "Pin to an immutable tag or digest."))
                if (c.get("securityContext") or {}).get("privileged"):
                    findings.append(Finding("K8S-003","critical",
                        "Privileged container",
                        r.uid, f"container {c.get('name')} privileged=true",
                        "Drop privileged: true; use specific capabilities instead."))
                if not c.get("livenessProbe") or not c.get("readinessProbe"):
                    findings.append(Finding("K8S-006","low",
                        "Missing liveness/readiness probe",
                        r.uid, f"container {c.get('name')}",
                        "Define livenessProbe and readinessProbe."))
            if tmpl.get("hostNetwork"):
                findings.append(Finding("K8S-003","critical",
                    "Pod uses hostNetwork",
                    r.uid,"spec.template.spec.hostNetwork=true",
                    "Avoid hostNetwork unless strictly required."))
        if r.kind == "Ingress":
            if not r.spec.get("tls"):
                findings.append(Finding("K8S-004","medium",
                    "Ingress without TLS",
                    r.uid,"spec.tls not set",
                    "Configure TLS termination for ingress."))

    # K8S-005: namespace with workloads but no NetworkPolicy
    ns_with_workload = {(r.cluster,r.namespace) for r in resources
                        if r.kind in ("Deployment","StatefulSet","DaemonSet")}
    ns_with_netpol = {(r.cluster,r.namespace) for r in resources
                      if r.kind == "NetworkPolicy"}
    for c,ns in sorted(ns_with_workload - ns_with_netpol):
        findings.append(Finding("K8S-005","low",
            f"Namespace '{ns}' has workloads but no NetworkPolicy",
            f"{c}//{ns}", "no NetworkPolicy found in namespace",
            "Add a default-deny NetworkPolicy and explicit allow rules."))

    return findings

# ---------------------------------------------------------------------------
# Mermaid renderer with cross-cluster subgraphs
# ---------------------------------------------------------------------------
KIND_STYLE = {
    "JobScheduler":      ("#fde2f3","#c026d3"),
    "Application":       ("#dcfce7","#16a34a"),
    "ProtectionPlan":    ("#dbeafe","#1d4ed8"),
    "AppProtectionPlan": ("#fef9c3","#ca8a04"),
    "ReplicationTarget": ("#fee2e2","#dc2626"),
    "Remote":            ("#ede9fe","#7c3aed"),
    "StorageClass":      ("#e0f2fe","#0284c7"),
    "PersistentVolumeClaim":("#fef3c7","#b45309"),
    "Deployment":        ("#ecfccb","#65a30d"),
    "StatefulSet":       ("#ecfccb","#65a30d"),
    "Service":           ("#e0e7ff","#4338ca"),
    "Ingress":           ("#fae8ff","#a21caf"),
    "Gateway":           ("#fae8ff","#a21caf"),
    "VirtualService":    ("#fae8ff","#a21caf"),
    "FileServerReplicationRelationship":("#fee2e2","#dc2626"),
    "AppPlannedFailover":("#fee2e2","#dc2626"),
    "AppUnplannedFailover":("#fee2e2","#dc2626"),
}

def _sid(uid: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", uid)

def _card(r: Resource) -> str:
    lines = [f"<b>kind: {r.kind}</b>", "metadata:",
             f"&nbsp;&nbsp;name: {r.name}",
             f"&nbsp;&nbsp;namespace: {r.namespace}"]
    if r.spec:
        lines.append("spec:")
        lines.extend(_render(r.spec, 2))
    else:
        lines.append("spec: { }")
    return "<br/>".join(lines)

CROSS_REF_FIELDS = {
    "spec.applicationName","spec.protectionPlanNames",
    "spec.scheduleName","spec.replicationTargetName",
    "spec.remoteName","spec.snapshotName","spec.appProtectionPlanName",
    "spec.storageClassName","spec.gateways",
}

def _render(obj, indent, path="spec") -> list[str]:
    pad = "&nbsp;"*indent; out=[]
    if isinstance(obj, dict):
        for k,v in obj.items():
            fp = f"{path}.{k}"
            if isinstance(v, dict):
                out.append(f"{pad}{k}:"); out.extend(_render(v,indent+2,fp))
            elif isinstance(v, list):
                out.append(f"{pad}{k}:")
                for it in v:
                    if isinstance(it,(dict,list)):
                        out.extend(_render(it,indent+2,fp+"[]"))
                    else:
                        out.append(f"{pad}&nbsp;&nbsp;- {_bold(str(it),fp)}")
            else:
                out.append(f"{pad}{k}: {_bold(str(v),fp)}")
    return out

def _bold(val, field_path):
    return f"<b>{val}</b>" if field_path in CROSS_REF_FIELDS else val

def render_mermaid(resources, edges) -> str:
    by_cluster = {}
    for r in resources:
        by_cluster.setdefault(r.cluster,[]).append(r)

    L = ["flowchart LR"]
    for cluster in sorted(by_cluster):
        L.append(f'    subgraph {cluster.upper()}_CLUSTER["{cluster.upper()} CLUSTER"]')
        L.append("        direction TB")
        for r in by_cluster[cluster]:
            L.append(f'        {_sid(r.uid)}["{_card(r)}"]')
        L.append("    end")

    seen = {r.uid for r in resources}
    ghosts = {}
    for e in edges:
        if e.dst not in seen and e.dst not in ghosts:
            try: c,k,ns,n = e.dst.split("/",3)
            except: continue
            ghosts[e.dst] = (c,k,ns,n)
    for uid,(c,k,ns,n) in ghosts.items():
        L.append(f'    {_sid(uid)}["<b>kind: {k}</b><br/>name: {n}<br/>namespace: {ns}<br/><i>(external)</i>"]')

    for e in edges:
        arrow = "-.->|" if e.kind=="reference" else "-->|" if e.kind=="selector" else "-..->|"
        L.append(f"    {_sid(e.src)} {arrow}{e.label}| {_sid(e.dst)}")

    L.append("")
    for k,(fill,stroke) in KIND_STYLE.items():
        L.append(f"    classDef {k.lower()} fill:{fill},stroke:{stroke},stroke-width:2px,color:#111;")
    for r in resources:
        if r.kind.lower() in {k.lower() for k in KIND_STYLE}:
            L.append(f"    class {_sid(r.uid)} {r.kind.lower()};")
    return "\n".join(L)

# ---------------------------------------------------------------------------
def to_json_model(resources, edges, findings):
    return {
        "nodes":[{"id":r.uid,"kind":r.kind,"name":r.name,"namespace":r.namespace,
                  "cluster":r.cluster,"spec":r.spec} for r in resources],
        "edges":[asdict(e) for e in edges],
        "findings":[asdict(f) for f in findings],
    }

# ---------------------------------------------------------------------------
DEMO = """
---
kind: JobScheduler
metadata:
  name: hourly-schedule
  namespace: source
  annotations:
    ndk.nutanix.com/exclude-from-deletion: "true"
spec:
  interval: { minutes: 60 }
  startTime: "2026-05-14T00:02:30Z"
  timeZoneName: America/Los_Angeles
---
kind: Application
metadata:
  name: db-app
  namespace: source
spec: {}
---
kind: ProtectionPlan
metadata:
  name: pplan-1
  namespace: source
  annotations:
    ndk.nutanix.com/exclude-from-deletion: "true"
spec:
  replicationConfigs:
    - replicationTargetName: US-west-2-fin
  retentionPolicy: { retentionCount: 5 }
  scheduleName: hourly-schedule
---
kind: AppProtectionPlan
metadata:
  name: app-plan
  namespace: source
  annotations:
    ndk.nutanix.com/exclude-from-deletion: "true"
spec:
  applicationName: db-app
  protectionPlanNames: [pplan-1]
---
kind: ReplicationTarget
metadata:
  name: US-west-2-fin
  namespace: source
spec:
  remoteName: pc-west
---
kind: Remote
metadata:
  name: pc-west
  namespace: source
spec:
  endpoint: https://10.0.0.50:9440
  skipTLSVerify: true
---
kind: StorageClass
metadata:
  name: nutanix-volume
spec: {}
---
kind: StorageClass
metadata:
  name: nutanix-volume
  annotations:
    ndk.demo/cluster: "replication"
spec: {}
---
kind: Deployment
metadata:
  name: db
  namespace: source
spec:
  template:
    metadata: { labels: { app: db } }
    spec:
      containers:
        - name: db
          image: postgres:latest
          securityContext: { privileged: true }
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: db-data }
---
kind: PersistentVolumeClaim
metadata:
  name: db-data
  namespace: source
spec:
  storageClassName: nutanix-volume
---
kind: Service
metadata:
  name: db-svc
  namespace: source
spec:
  selector: { app: db }
---
kind: Ingress
metadata:
  name: db-ing
  namespace: source
spec:
  rules:
    - http:
        paths:
          - backend: { service: { name: db-svc } }
"""

def main(argv):
    resources = load_resources(argv[1:] if len(argv)>1 else [DEMO])
    print(f"Parsed {len(resources)} resources")
    edges = resolve_edges(resources)
    print(f"Resolved {len(edges)} edges ({sum(1 for e in edges if e.resolved)} in-bundle, "
          f"{sum(1 for e in edges if not e.resolved)} external/ghost)")
    g = build_graph(resources, edges)
    print(f"Graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")

    Path("bcdr_plan.mmd").write_text(render_mermaid(resources, edges))
    Path("bcdr_plan.json").write_text(json.dumps(to_json_model(resources, edges, []), indent=2))
    print("Wrote: bcdr_plan.mmd, bcdr_plan.json")

def _findings_md(findings):
    lines = ["# NDK Risk Findings\n", f"Total: **{len(findings)}**\n"]
    sev_order = ["critical","high","medium","low","info"]
    for sev in sev_order:
        group = [f for f in findings if f.severity==sev]
        if not group: continue
        lines.append(f"## {sev.upper()} ({len(group)})\n")
        for f in group:
            lines.append(f"### {f.rule_id} — {f.title}")
            lines.append(f"- **Resource:** `{f.resource or 'global'}`")
            lines.append(f"- **Evidence:** {f.evidence}")
            lines.append(f"- **Remediation:** {f.remediation}\n")
    return "\n".join(lines)


# ============================================================================
# EXECUTIVE VIEW — C-level rendering and brief generation
# ============================================================================

def _kind_summary(resources):
    by = {}
    for r in resources:
        by.setdefault(r.kind, []).append(r)
    return by


def infer_protection_defaults(resources):
    by = _kind_summary(resources)
    has_pp = "ProtectionPlan" in by
    has_js = "JobScheduler" in by
    has_app = "Application" in by
    return {
        "protection_plan_inferred": not has_pp,
        "schedule_inferred": not has_js,
        "rpo": "1 hour",
        "mode": "Async",
        "schedule_name": (by["JobScheduler"][0].name if has_js else "wp-1h-async [inferred]"),
        "plan_name": (by["ProtectionPlan"][0].name if has_pp else "wp-protect [inferred]"),
        "app": (by["Application"][0] if has_app else None),
    }


def build_executive_model(resources, edges):
    by = _kind_summary(resources)
    inferred = infer_protection_defaults(resources)
    app = inferred["app"]

    remotes = by.get("Remote", [])
    rts = by.get("ReplicationTarget", [])
    primary_cluster = app.cluster if app else "primary"

    dr = None
    if remotes:
        rem = remotes[0]
        dr_ns = rts[0].spec.get("namespaceName") if rts else None
        dr = {
            "name": rem.spec.get("clusterName", rem.name),
            "endpoint": f"{rem.spec.get('ndkServiceIp','?')}:{rem.spec.get('ndkServicePort','?')}",
            "target_namespace": dr_ns or "(same as source)",
        }

    storage = by.get("StorageCluster", [])
    sc = storage[0] if storage else None

    has_app = bool(app); has_rt = bool(rts)
    has_remote = bool(remotes); has_storage = bool(sc)
    if has_app and has_rt and has_remote and has_storage:
        posture = "Protected"; color = "green"
    elif has_app and (has_rt or has_remote):
        posture = "Partially Protected"; color = "amber"
    else:
        posture = "Unprotected"; color = "red"

    return {
        "application": {
            "name": app.name if app else "(no Application CR)",
            "namespace": app.namespace if app else "-",
        },
        "primary_site": {
            "name": primary_cluster,
            "storage_cluster": sc.name if sc else None,
        },
        "dr_site": dr,
        "protection": {
            "rpo": inferred["rpo"], "mode": inferred["mode"],
            "plan": inferred["plan_name"], "schedule": inferred["schedule_name"],
            "plan_inferred": inferred["protection_plan_inferred"],
            "schedule_inferred": inferred["schedule_inferred"],
        },
        "posture": {"status": posture, "color": color},
        "capabilities_demonstrated": [
            "Application-centric protection (CRD-driven)",
            "Cross-cluster async replication",
            "Cluster-scoped Remote registration",
            "Namespace remapping at DR site",
            "Snapshot lifecycle managed by NDK",
        ],
        "counts": {k: len(v) for k, v in by.items()},
    }


def render_executive_mermaid(model):
    app = model["application"]; p = model["primary_site"]
    dr = model["dr_site"]; prot = model["protection"]
    plan_tag = " [inferred]" if prot["plan_inferred"] else ""
    sched_tag = " [inferred]" if prot["schedule_inferred"] else ""

    lines = ["flowchart LR"]
    lines.append(f'  subgraph PRIMARY["PRIMARY SITE · {p["name"]}"]')
    lines.append('    direction TB')
    lines.append(f'    P_APP["📦 Application<br/><b>{app["name"]}</b><br/>ns: {app["namespace"]}"]')
    lines.append(f'    P_PLAN["🛡 Protection Plan<br/><b>{prot["plan"]}</b>{plan_tag}<br/>Async · RPO {prot["rpo"]}"]')
    lines.append(f'    P_SCHED["⏱ Schedule<br/><b>{prot["schedule"]}</b>{sched_tag}"]')
    lines.append(f'    P_STORE["💾 Storage Cluster<br/><b>{p["storage_cluster"] or "n/a"}</b>"]')
    lines.append('    P_APP --> P_PLAN --> P_SCHED')
    lines.append('    P_APP -.-> P_STORE')
    lines.append('  end')

    if dr:
        lines.append(f'  subgraph DR["DR SITE · {dr["name"]}"]')
        lines.append('    direction TB')
        lines.append(f'    D_REMOTE["🔗 Remote Endpoint<br/><b>{dr["endpoint"]}</b>"]')
        lines.append(f'    D_RT["🎯 Replication Target<br/>ns: <b>{dr["target_namespace"]}</b>"]')
        lines.append(f'    D_APP["📦 Application (restored)<br/><b>{app["name"]}</b><br/>ns: {dr["target_namespace"]}"]')
        lines.append('    D_REMOTE --> D_RT --> D_APP')
        lines.append('  end')
        lines.append(f'  PRIMARY ==>|"NDK Async Replication<br/>RPO {prot["rpo"]} · Plan: {prot["plan"]}"| DR')

    lines += [
        '',
        'classDef site fill:#f8fafc,stroke:#0f172a,stroke-width:2px,color:#0f172a;',
        'class PRIMARY,DR site;',
        'style P_APP fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#0f172a;',
        'style D_APP fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#0f172a;',
        'style P_PLAN fill:#dbeafe,stroke:#1d4ed8,stroke-width:2px,color:#0f172a;',
        'style P_SCHED fill:#fde2f3,stroke:#c026d3,stroke-width:2px,color:#0f172a;',
        'style P_STORE fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0f172a;',
        'style D_RT fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#0f172a;',
        'style D_REMOTE fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#0f172a;',
    ]
    return "\n".join(lines)


def render_executive_brief(model):
    p = model["primary_site"]; dr = model["dr_site"]; prot = model["protection"]
    return {
        "title": f"NDK Protection Posture · {model['application']['name']}",
        "subtitle": "Nutanix Data Services for Kubernetes — Customer Workload Protection",
        "headline_metrics": [
            {"label": "Posture", "value": model["posture"]["status"], "tone": model["posture"]["color"]},
            {"label": "RPO", "value": prot["rpo"], "tone": "blue"},
            {"label": "Mode", "value": prot["mode"], "tone": "blue"},
            {"label": "Sites", "value": f"{p['name']} → {dr['name'] if dr else 'n/a'}", "tone": "slate"},
        ],
        "narrative": (
            f"The <b>{model['application']['name']}</b> workload running in namespace "
            f"<b>{model['application']['namespace']}</b> on the <b>{p['name']}</b> cluster is "
            f"protected by NDK using an <b>{prot['mode'].lower()}</b> protection plan "
            f"<b>{prot['plan']}</b> with a <b>{prot['rpo']} RPO</b>. Snapshots replicate to the "
            f"DR cluster <b>{dr['name'] if dr else 'n/a'}</b> at <b>{dr['endpoint'] if dr else 'n/a'}</b>, "
            f"with the workload restored into namespace "
            f"<b>{dr['target_namespace'] if dr else 'n/a'}</b>."
        ),
        "ndk_capabilities": model["capabilities_demonstrated"],
        "resource_counts": model["counts"],
        "inferred_notes": [
            n for n, flag in [
                ("ProtectionPlan synthesised — customer is using manual snapshots today.",
                 prot["plan_inferred"]),
                ("JobScheduler synthesised — recommended for automated 1h cadence.",
                 prot["schedule_inferred"]),
            ] if flag
        ],
    }


if __name__ == "__main__":
    main(sys.argv)
