#!/usr/bin/env python3
"""
analyze.py — Solution-level analysis and profiling for FileMaker solutions.

Reads pre-indexed data (index files, xref, layout summaries, sanitized scripts)
and produces a structured solution profile. Never reads raw xml_parsed XML.

Usage:
  python3 agent/scripts/analyze.py -s "FM_Quickstart_v26_0_1"
  python3 agent/scripts/analyze.py -s "FM_Quickstart_v26_0_1" --format markdown
  python3 agent/scripts/analyze.py -s "FM_Quickstart_v26_0_1" --deep
  python3 agent/scripts/analyze.py -s "FM_Quickstart_v26_0_1" --ensure-prerequisites
  python3 agent/scripts/analyze.py --list-extensions

Options:
  -s, --solution             Solution name (as it appears in agent/context/)
  --format                   Output format: json (default) or markdown (spec document)
  --deep                     Enable full script text analysis (step frequency,
                             error handling, transaction usage, nesting depth,
                             external calls). Default mode uses index + call chains.
  --ensure-prerequisites     Build xref.index / layout summaries if missing
  --list-extensions          Show available optional dependencies and exit
  --output, -o               Output path override
"""

import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Optional dependency detection
# ---------------------------------------------------------------------------

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    import jinja2
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

EXTENSIONS = {
    "networkx": {
        "available": HAS_NETWORKX,
        "description": "graph topology, community detection, cycle detection",
    },
    "pandas": {
        "available": HAS_PANDAS,
        "description": "statistical profiling, outlier detection",
    },
    "matplotlib": {
        "available": HAS_MATPLOTLIB,
        "description": "visualizations (heatmaps, charts, graph diagrams)",
    },
    "jinja2": {
        "available": HAS_JINJA2,
        "description": "rich templated reports",
    },
}


# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # agent/scripts/ -> project root

CONTEXT_DIR = PROJECT_ROOT / "agent" / "context"
XML_PARSED_DIR = PROJECT_ROOT / "agent" / "xml_parsed"


# ---------------------------------------------------------------------------
# Regex patterns for script text analysis
# ---------------------------------------------------------------------------

RE_PERFORM_SCRIPT = re.compile(
    r'Perform Script\s*\[.*?"([^"]+)"', re.DOTALL
)
RE_LAYOUT_REF = re.compile(r'Layout:\s*"([^"]+)"')
RE_SET_ERROR_CAPTURE = re.compile(r'Set Error Capture\s*\[', re.IGNORECASE)
RE_OPEN_TRANSACTION = re.compile(r'Open Transaction', re.IGNORECASE)
RE_INSERT_FROM_URL = re.compile(r'Insert from URL', re.IGNORECASE)
RE_SEND_MAIL = re.compile(r'Send Mail', re.IGNORECASE)
RE_EXPORT_RECORDS = re.compile(r'Export Records', re.IGNORECASE)
RE_IMPORT_RECORDS = re.compile(r'Import Records', re.IGNORECASE)
RE_IF_BLOCK = re.compile(r'^If\s*\[', re.IGNORECASE)
RE_LOOP_BLOCK = re.compile(r'^Loop$', re.IGNORECASE)

# Naming convention patterns
NAMING_PATTERNS = {
    "__kpt": "primary_key",
    "_kft": "foreign_key",
    "_kf": "foreign_key",
    "zzz": "deprecated",
    "zz": "deprecated",
    "z_": "deprecated",
    "zgt": "global_temp",
    "zg": "global",
    "c_": "unstored_calc",
    "g_": "global",
    "id_": "id_field",
    "flag": "boolean_flag",
}


# ---------------------------------------------------------------------------
# Index parsers (reused from trace.py pattern)
# ---------------------------------------------------------------------------

def _parse_index(path, columns):
    """Parse a pipe-delimited index file into a list of dicts."""
    rows = []
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            row = {}
            for i, col in enumerate(columns):
                row[col] = parts[i] if i < len(parts) else ""
            rows.append(row)
    return rows


def load_fields_index(solution_dir):
    return _parse_index(
        solution_dir / "fields.index",
        ["table", "table_id", "field", "field_id", "datatype",
         "fieldtype", "auto_enter", "flags"],
    )


def load_relationships_index(solution_dir):
    return _parse_index(
        solution_dir / "relationships.index",
        ["left_to", "left_to_id", "right_to", "right_to_id",
         "join_type", "join_fields", "cascade_create", "cascade_delete"],
    )


def load_table_occurrences_index(solution_dir):
    return _parse_index(
        solution_dir / "table_occurrences.index",
        ["to_name", "to_id", "base_table", "base_table_id"],
    )


def load_scripts_index(solution_dir):
    return _parse_index(
        solution_dir / "scripts.index",
        ["name", "id", "folder"],
    )


def load_layouts_index(solution_dir):
    return _parse_index(
        solution_dir / "layouts.index",
        ["name", "id", "base_to", "base_to_id", "folder"],
    )


def load_value_lists_index(solution_dir):
    return _parse_index(
        solution_dir / "value_lists.index",
        ["name", "id", "source_type", "values"],
    )


def load_xref_index(solution_dir):
    return _parse_index(
        solution_dir / "xref.index",
        ["source_type", "source_name", "source_location",
         "ref_type", "ref_name", "ref_context"],
    )


# ---------------------------------------------------------------------------
# Data model analysis
# ---------------------------------------------------------------------------

def analyze_data_model(fields_index, to_index, relationships_index):
    """Analyze base tables, fields, TOs, and relationships."""
    # --- Base tables ---
    tables = {}
    for row in fields_index:
        tname = row["table"]
        if tname not in tables:
            tables[tname] = {
                "id": row["table_id"],
                "fields": [],
                "field_count": 0,
                "by_datatype": collections.Counter(),
                "by_fieldtype": collections.Counter(),
                "auto_enter_patterns": collections.Counter(),
                "has_primary_key": False,
                "foreign_keys": [],
                "unstored_count": 0,
                "global_count": 0,
                "summary_count": 0,
            }
        t = tables[tname]
        t["fields"].append(row)
        t["field_count"] += 1
        t["by_datatype"][row["datatype"]] += 1
        t["by_fieldtype"][row["fieldtype"]] += 1

        # Performance-relevant flags
        flags = row.get("flags", "")
        if "unstored" in flags:
            t["unstored_count"] += 1
        if "global" in flags:
            t["global_count"] += 1
        if row["fieldtype"] == "Summary":
            t["summary_count"] += 1

        ae = row["auto_enter"]
        if ae:
            # Normalize auto-enter to category
            if ae.startswith("auto:"):
                ae_type = ae[5:].split("(")[0].strip()
                t["auto_enter_patterns"][ae_type] += 1
            else:
                t["auto_enter_patterns"][ae] += 1

        fname_lower = row["field"].lower()
        if fname_lower.startswith("__kpt") or fname_lower == "primarykey":
            t["has_primary_key"] = True
        if fname_lower.startswith("_kft") or fname_lower.startswith("_kf"):
            t["foreign_keys"].append(row["field"])

    # Build table summary (without raw field lists for output)
    table_summaries = {}
    for tname, t in tables.items():
        table_summaries[tname] = {
            "id": t["id"],
            "field_count": t["field_count"],
            "by_datatype": dict(t["by_datatype"]),
            "by_fieldtype": dict(t["by_fieldtype"]),
            "auto_enter_patterns": dict(t["auto_enter_patterns"]),
            "has_primary_key": t["has_primary_key"],
            "foreign_key_count": len(t["foreign_keys"]),
            "unstored_count": t["unstored_count"],
            "global_count": t["global_count"],
            "summary_count": t["summary_count"],
        }

    # --- Table occurrences ---
    to_by_base = collections.defaultdict(list)
    for row in to_index:
        base = row["base_table"] or "(external/unknown)"
        to_by_base[base].append(row["to_name"])

    to_groups = {
        base: {"count": len(tos), "names": tos}
        for base, tos in to_by_base.items()
    }

    # --- Relationships ---
    rel_summary = {
        "total": len(relationships_index),
        "by_join_type": dict(collections.Counter(
            r["join_type"] for r in relationships_index
        )),
        "cascades": {
            "create": sum(
                1 for r in relationships_index if r["cascade_create"] == "True"
            ),
            "delete": sum(
                1 for r in relationships_index if r["cascade_delete"] == "True"
            ),
        },
        "multi_predicate": sum(
            1 for r in relationships_index if "+" in r["join_type"]
        ),
        "self_joins": 0,
    }

    # Detect self-joins (left and right TO share same base table)
    to_map = {row["to_name"]: row["base_table"] for row in to_index}
    for r in relationships_index:
        left_base = to_map.get(r["left_to"], "")
        right_base = to_map.get(r["right_to"], "")
        if left_base and left_base == right_base:
            rel_summary["self_joins"] += 1

    # --- Topology analysis ---
    topology = _analyze_topology(to_index, relationships_index, to_map)

    # --- Base-table relationship pairs for ERD ---
    seen = set()
    base_table_edges = []
    for r in relationships_index:
        left_base = to_map.get(r["left_to"], "")
        right_base = to_map.get(r["right_to"], "")
        if left_base and right_base and left_base != right_base:
            pair = tuple(sorted([left_base, right_base]))
            if pair not in seen:
                seen.add(pair)
                base_table_edges.append(list(pair))

    # --- Performance metrics (solution-wide) ---
    total_unstored = sum(t["unstored_count"] for t in tables.values())
    total_summary = sum(t["summary_count"] for t in tables.values())
    total_global = sum(t["global_count"] for t in tables.values())
    total_calculated = sum(
        t.get("by_fieldtype", {}).get("Calculated", 0)
        for t in table_summaries.values()
    )

    # Tables sorted by unstored+summary count (performance hotspots)
    perf_hotspots = sorted(
        [
            {
                "table": tname,
                "unstored": t["unstored_count"],
                "summary": t["summary_count"],
                "calculated": t.get("by_fieldtype", {}).get("Calculated", 0),
                "total_fields": t["field_count"],
            }
            for tname, t in table_summaries.items()
            if t["unstored_count"] > 0 or t["summary_count"] > 0
        ],
        key=lambda x: x["unstored"] + x["summary"],
        reverse=True,
    )

    performance = {
        "total_unstored": total_unstored,
        "total_summary": total_summary,
        "total_global": total_global,
        "total_calculated": total_calculated,
        "unstored_pct": round(
            total_unstored / max(1, len(fields_index)) * 100, 1
        ),
        "summary_pct": round(
            total_summary / max(1, len(fields_index)) * 100, 1
        ),
        "hotspot_tables": perf_hotspots[:20],
    }

    return {
        "tables": table_summaries,
        "table_count": len(table_summaries),
        "total_fields": len(fields_index),
        "table_occurrences": to_groups,
        "to_count": len(to_index),
        "relationships": rel_summary,
        "topology": topology,
        "base_table_edges": base_table_edges,
        "performance": performance,
    }


def _analyze_topology(to_index, relationships_index, to_map):
    """Analyze TO topology pattern (anchor-buoy vs spider-web)."""
    if HAS_NETWORKX:
        return _topology_networkx(to_index, relationships_index, to_map)
    return _topology_basic(to_index, relationships_index, to_map)


def _topology_basic(to_index, relationships_index, to_map):
    """Basic topology analysis without networkx."""
    # Build adjacency: count connections per TO
    degree = collections.Counter()
    for r in relationships_index:
        degree[r["left_to"]] += 1
        degree[r["right_to"]] += 1

    if not degree:
        return {"pattern": "unknown", "note": "no relationships found"}

    degrees = list(degree.values())
    avg_degree = sum(degrees) / len(degrees) if degrees else 0
    max_degree = max(degrees) if degrees else 0
    low_degree_pct = sum(1 for d in degrees if d <= 2) / len(degrees) if degrees else 0

    # Heuristic: anchor-buoy has most TOs with degree 1-2 and a few hubs
    hub_count = sum(1 for d in degrees if d >= 5)

    if low_degree_pct >= 0.7 and hub_count >= 1:
        pattern = "anchor-buoy"
    elif low_degree_pct < 0.4:
        pattern = "spider-web"
    else:
        pattern = "hybrid"

    return {
        "pattern": pattern,
        "avg_degree": round(avg_degree, 2),
        "max_degree": max_degree,
        "low_degree_pct": round(low_degree_pct, 2),
        "hub_count": hub_count,
    }


def _topology_networkx(to_index, relationships_index, to_map):
    """Advanced topology analysis with networkx."""
    G = nx.Graph()
    for row in to_index:
        G.add_node(row["to_name"], base_table=row["base_table"])
    for r in relationships_index:
        G.add_edge(r["left_to"], r["right_to"], join_type=r["join_type"])

    if G.number_of_nodes() == 0:
        return {"pattern": "unknown", "note": "no table occurrences found"}

    degrees = [d for _, d in G.degree()]
    avg_degree = sum(degrees) / len(degrees) if degrees else 0
    max_degree = max(degrees) if degrees else 0
    low_degree_pct = sum(1 for d in degrees if d <= 2) / len(degrees) if degrees else 0
    hub_count = sum(1 for d in degrees if d >= 5)

    # Connected components
    components = list(nx.connected_components(G))

    # Identify anchor tables (hubs by base table)
    hub_tos = [n for n, d in G.degree() if d >= 5]
    anchor_tables = sorted(set(to_map.get(t, t) for t in hub_tos))

    if low_degree_pct >= 0.7 and hub_count >= 1:
        pattern = "anchor-buoy"
    elif low_degree_pct < 0.4:
        pattern = "spider-web"
    else:
        pattern = "hybrid"

    # Bridge edges (whose removal disconnects the graph)
    bridges = list(nx.bridges(G))

    return {
        "pattern": pattern,
        "confidence": round(low_degree_pct if pattern == "anchor-buoy" else 1 - low_degree_pct, 2),
        "avg_degree": round(avg_degree, 2),
        "max_degree": max_degree,
        "low_degree_pct": round(low_degree_pct, 2),
        "hub_count": hub_count,
        "anchor_tables": anchor_tables,
        "connected_components": len(components),
        "isolated_components": [
            sorted(c) for c in components if len(c) <= 3
        ] if len(components) > 1 else [],
        "bridge_count": len(bridges),
        "method": "networkx",
    }


# ---------------------------------------------------------------------------
# Naming convention detection
# ---------------------------------------------------------------------------

def detect_naming_conventions(fields_index):
    """Detect dominant naming conventions from field names."""
    prefix_counts = collections.Counter()
    case_styles = collections.Counter()

    for row in fields_index:
        fname = row["field"]
        # Check known prefixes
        for prefix, label in NAMING_PATTERNS.items():
            if fname.lower().startswith(prefix):
                prefix_counts[f"{prefix} ({label})"] += 1
                break

        # Detect case style
        if "_" in fname and fname == fname.lower():
            case_styles["snake_case"] += 1
        elif fname[0].isupper() and "_" not in fname:
            case_styles["PascalCase"] += 1
        elif fname[0].islower() and "_" not in fname and any(c.isupper() for c in fname):
            case_styles["camelCase"] += 1
        else:
            case_styles["mixed"] += 1

    dominant_case = case_styles.most_common(1)[0][0] if case_styles else "unknown"

    return {
        "prefix_conventions": dict(prefix_counts.most_common()),
        "case_styles": dict(case_styles),
        "dominant_case": dominant_case,
    }


# ---------------------------------------------------------------------------
# Script analysis
# ---------------------------------------------------------------------------

def find_script_files(solution_name):
    """Find all sanitized script text files for a solution."""
    scripts_dir = XML_PARSED_DIR / "scripts_sanitized" / solution_name
    if not scripts_dir.exists():
        return []
    return sorted(scripts_dir.rglob("*.txt"))


def extract_script_id_from_filename(filename):
    """Extract script ID from filename like 'Contact - Navigate To - ID 71.txt'."""
    match = re.search(r'ID (\d+)\.txt$', filename)
    return match.group(1) if match else None


def analyze_scripts(solution_name, scripts_index, deep=False):
    """Analyze scripts: inventory, call chains, and optionally deep metrics."""
    # Build inventory from index
    scripts_by_id = {s["id"]: s for s in scripts_index}
    scripts_by_name = {s["name"]: s for s in scripts_index}

    # Organize by folder
    by_folder = collections.defaultdict(list)
    for s in scripts_index:
        folder = s["folder"] or "(root)"
        by_folder[folder].append(s["name"])

    folder_tree = {
        folder: {"scripts": names, "count": len(names)}
        for folder, names in sorted(by_folder.items())
    }

    # --- Call chain extraction from sanitized scripts ---
    call_graph = {}  # script_name -> [called_script_names]
    script_line_counts = {}
    script_files = find_script_files(solution_name)

    # Deep mode accumulators
    deep_metrics = None
    if deep:
        deep_metrics = {
            "error_handling": {"with_capture": 0, "without_capture": 0},
            "transactions": {"scripts_using": 0},
            "external_calls": collections.Counter(),
            "step_frequency": collections.Counter(),
            "nesting": {"max_depth": 0, "avg_depth": 0, "depths": []},
        }

    for script_path in script_files:
        script_id = extract_script_id_from_filename(script_path.name)
        # Find script name from index
        script_name = None
        if script_id and script_id in scripts_by_id:
            script_name = scripts_by_id[script_id]["name"]
        else:
            # Fallback: derive from filename
            script_name = script_path.stem.rsplit(" - ID ", 1)[0]

        try:
            with open(script_path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        lines = text.strip().split("\n")
        script_line_counts[script_name] = len(lines)

        # Extract Perform Script calls
        calls = RE_PERFORM_SCRIPT.findall(text)
        if calls:
            call_graph[script_name] = calls

        # Deep analysis
        if deep and deep_metrics is not None:
            has_error_capture = bool(RE_SET_ERROR_CAPTURE.search(text))
            if has_error_capture:
                deep_metrics["error_handling"]["with_capture"] += 1
            else:
                deep_metrics["error_handling"]["without_capture"] += 1

            if RE_OPEN_TRANSACTION.search(text):
                deep_metrics["transactions"]["scripts_using"] += 1

            for pattern, label in [
                (RE_INSERT_FROM_URL, "Insert from URL"),
                (RE_SEND_MAIL, "Send Mail"),
                (RE_EXPORT_RECORDS, "Export Records"),
                (RE_IMPORT_RECORDS, "Import Records"),
            ]:
                count = len(pattern.findall(text))
                if count:
                    deep_metrics["external_calls"][label] += count

            # Nesting depth
            depth = 0
            max_depth = 0
            for line in lines:
                stripped = line.strip()
                if RE_IF_BLOCK.match(stripped) or RE_LOOP_BLOCK.match(stripped):
                    depth += 1
                    max_depth = max(max_depth, depth)
                elif stripped.startswith("End If") or stripped.startswith("End Loop"):
                    depth = max(0, depth - 1)

                # Step frequency: extract step name (first word before [)
                step_match = re.match(r'^([A-Z][A-Za-z ]+?)(?:\s*\[|$)', stripped)
                if step_match:
                    deep_metrics["step_frequency"][step_match.group(1).strip()] += 1

            deep_metrics["nesting"]["depths"].append(max_depth)
            if max_depth > deep_metrics["nesting"]["max_depth"]:
                deep_metrics["nesting"]["max_depth"] = max_depth

    # --- Build call chain analysis ---
    # Identify entry points and utilities
    called_by = collections.defaultdict(list)
    for caller, callees in call_graph.items():
        for callee in callees:
            called_by[callee].append(caller)

    all_script_names = set(s["name"] for s in scripts_index)
    entry_points = sorted(
        name for name in all_script_names
        if name not in called_by and name in call_graph
    )
    utility_scripts = sorted(
        name for name in all_script_names
        if len(called_by.get(name, [])) >= 3
    )
    leaf_scripts = sorted(
        name for name in all_script_names
        if name not in call_graph and name in called_by
    )

    # --- Functional clusters ---
    clusters = _cluster_scripts(call_graph, scripts_by_name, all_script_names)

    # Finalize deep metrics
    if deep and deep_metrics is not None:
        depths = deep_metrics["nesting"]["depths"]
        deep_metrics["nesting"]["avg_depth"] = (
            round(sum(depths) / len(depths), 1) if depths else 0
        )
        del deep_metrics["nesting"]["depths"]
        deep_metrics["external_calls"] = dict(deep_metrics["external_calls"])
        deep_metrics["step_frequency"] = dict(
            deep_metrics["step_frequency"].most_common(20)
        )
        deep_metrics["error_handling"]["coverage_pct"] = round(
            deep_metrics["error_handling"]["with_capture"]
            / max(1, deep_metrics["error_handling"]["with_capture"]
                  + deep_metrics["error_handling"]["without_capture"])
            * 100, 1
        )

    result = {
        "total_scripts": len(scripts_index),
        "total_files_analyzed": len(script_files),
        "folders": folder_tree,
        "call_graph_edges": sum(len(v) for v in call_graph.values()),
        "call_graph": [
            [caller, callee]
            for caller, callees in call_graph.items()
            for callee in callees
            if callee in all_script_names
        ],
        "entry_points": entry_points,
        "utility_scripts": utility_scripts,
        "leaf_scripts": leaf_scripts[:20],  # Cap for readability
        "clusters": clusters,
        "line_counts": {
            "total": sum(script_line_counts.values()),
            "avg": round(
                sum(script_line_counts.values()) / max(1, len(script_line_counts)), 1
            ),
            "max": max(script_line_counts.values()) if script_line_counts else 0,
            "largest_scripts": sorted(
                script_line_counts.items(), key=lambda x: x[1], reverse=True
            )[:10],
        },
    }

    if deep and deep_metrics is not None:
        result["deep_metrics"] = deep_metrics

    return result


def _cluster_scripts(call_graph, scripts_by_name, all_script_names):
    """Cluster scripts into functional domains."""
    if HAS_NETWORKX:
        return _cluster_scripts_networkx(call_graph, scripts_by_name, all_script_names)
    return _cluster_scripts_basic(call_graph, scripts_by_name)


def _cluster_scripts_basic(call_graph, scripts_by_name):
    """Basic clustering by folder + call chain connectivity."""
    # Group by top-level folder
    clusters = collections.defaultdict(set)
    for script_name, info in scripts_by_name.items():
        folder = info.get("folder", "") or "(root)"
        top_folder = folder.split("/")[0]
        clusters[top_folder].add(script_name)

    # Merge clusters that are connected by call chains
    result = []
    for folder, members in sorted(clusters.items()):
        entry_pts = [
            m for m in members
            if m in call_graph and not any(
                m in callees
                for callees in call_graph.values()
                if callees
            )
        ]
        result.append({
            "name": folder,
            "script_count": len(members),
            "entry_points": sorted(entry_pts)[:5],
            "method": "folder_grouping",
        })

    return result


def _cluster_scripts_networkx(call_graph, scripts_by_name, all_script_names):
    """Advanced clustering with networkx community detection."""
    G = nx.DiGraph()
    for name in all_script_names:
        folder = scripts_by_name.get(name, {}).get("folder", "")
        G.add_node(name, folder=folder)
    for caller, callees in call_graph.items():
        for callee in callees:
            if callee in all_script_names:
                G.add_edge(caller, callee)

    # Use weakly connected components as clusters
    components = list(nx.weakly_connected_components(G))

    # Detect cycles
    cycles = list(nx.simple_cycles(G))
    cycle_scripts = set()
    for cycle in cycles[:50]:  # Cap to avoid combinatorial explosion
        cycle_scripts.update(cycle)

    result = []
    for comp in sorted(components, key=len, reverse=True):
        if len(comp) < 2:
            continue

        # Determine dominant folder
        folders = collections.Counter(
            scripts_by_name.get(s, {}).get("folder", "").split("/")[0]
            for s in comp
        )
        dominant_folder = folders.most_common(1)[0][0] if folders else "(root)"

        # Find entry points in this cluster
        sub = G.subgraph(comp)
        entry_pts = [n for n in comp if sub.in_degree(n) == 0]

        # Betweenness centrality for bottleneck detection
        if len(comp) >= 3:
            centrality = nx.betweenness_centrality(sub)
            bottleneck = max(centrality, key=centrality.get) if centrality else None
        else:
            bottleneck = None

        cluster_info = {
            "name": dominant_folder or "(unnamed)",
            "script_count": len(comp),
            "entry_points": sorted(entry_pts)[:5],
            "method": "networkx_components",
        }
        if bottleneck:
            cluster_info["bottleneck"] = bottleneck
        if cycle_scripts & comp:
            cluster_info["has_cycles"] = True

        result.append(cluster_info)

    # Add cycle info at top level if any
    if cycles:
        result.insert(0, {
            "_cycles_detected": len(cycles),
            "_cycle_scripts": sorted(cycle_scripts)[:20],
        })

    return result


# ---------------------------------------------------------------------------
# Custom function analysis
# ---------------------------------------------------------------------------

def analyze_custom_functions(solution_name):
    """Analyze custom functions: inventory and dependency chains."""
    cf_dir = XML_PARSED_DIR / "custom_functions_sanitized" / solution_name
    if not cf_dir.exists():
        return {"total": 0, "note": "no custom functions directory found"}

    cf_files = sorted(cf_dir.glob("*.txt"))
    functions = {}
    all_cf_names = set()

    # First pass: collect names
    for cf_path in cf_files:
        # Filename: "FunctionName - ID 123.txt"
        name = cf_path.stem.rsplit(" - ID ", 1)[0]
        all_cf_names.add(name)

    # Second pass: analyze dependencies
    for cf_path in cf_files:
        name = cf_path.stem.rsplit(" - ID ", 1)[0]
        cf_id = None
        id_match = re.search(r'ID (\d+)$', cf_path.stem)
        if id_match:
            cf_id = id_match.group(1)

        try:
            with open(cf_path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        # Count parameters (look for function signature pattern)
        param_match = re.match(r'^(\w+)\s*\((.*?)\)', text, re.DOTALL)
        param_count = 0
        if param_match:
            params = param_match.group(2).strip()
            if params:
                param_count = len([p.strip() for p in params.split(";") if p.strip()])

        # Find references to other custom functions
        deps = []
        for other_name in all_cf_names:
            if other_name != name and other_name in text:
                deps.append(other_name)

        line_count = len(text.strip().split("\n"))

        functions[name] = {
            "id": cf_id,
            "param_count": param_count,
            "line_count": line_count,
            "dependencies": deps,
        }

    # Classify: constants vs functional vs solution-specific
    # (Simple heuristic: 1-line with no params = constant)
    categories = {"constant": [], "functional": [], "solution_specific": []}
    for name, info in functions.items():
        if info["line_count"] <= 2 and info["param_count"] == 0:
            categories["constant"].append(name)
        elif info["dependencies"]:
            categories["solution_specific"].append(name)
        else:
            categories["functional"].append(name)

    return {
        "total": len(functions),
        "functions": functions,
        "categories": {k: len(v) for k, v in categories.items()},
        "dependency_chains": _find_cf_chains(functions),
    }


def _find_cf_chains(functions):
    """Find the longest dependency chains in custom functions."""
    if not functions:
        return []

    def _chain_depth(name, visited=None):
        if visited is None:
            visited = set()
        if name in visited or name not in functions:
            return 0
        visited.add(name)
        deps = functions[name].get("dependencies", [])
        if not deps:
            return 1
        return 1 + max(_chain_depth(d, visited.copy()) for d in deps)

    chains = [(name, _chain_depth(name)) for name in functions]
    chains.sort(key=lambda x: x[1], reverse=True)
    return [{"function": name, "depth": depth} for name, depth in chains[:5] if depth > 1]


# ---------------------------------------------------------------------------
# Layout analysis
# ---------------------------------------------------------------------------

def analyze_layouts(solution_name, solution_dir, layouts_index, scripts_index):
    """Analyze layouts: inventory, classification, portal usage."""
    # Organize by base TO
    by_base_to = collections.defaultdict(list)
    for layout in layouts_index:
        base_to = layout["base_to"] or "(none)"
        by_base_to[base_to].append(layout["name"])

    # Organize by folder
    by_folder = collections.defaultdict(list)
    for layout in layouts_index:
        folder = layout["folder"] or "(root)"
        by_folder[folder].append(layout["name"])

    # Layout classification heuristics
    classifications = collections.Counter()
    classified = {}
    for layout in layouts_index:
        name_lower = layout["name"].lower()
        if any(kw in name_lower for kw in ["list", "search", "browse"]):
            cat = "list"
        elif any(kw in name_lower for kw in ["detail", "entry", "edit", "form"]):
            cat = "detail"
        elif any(kw in name_lower for kw in ["dialog", "popup", "pop up", "modal"]):
            cat = "dialog"
        elif any(kw in name_lower for kw in ["report", "print", "pdf"]):
            cat = "report"
        elif any(kw in name_lower for kw in ["menu", "nav", "dashboard"]):
            cat = "navigation"
        else:
            cat = "other"
        classifications[cat] += 1
        classified[layout["name"]] = cat

    # Check layout summaries if available
    layout_summaries_dir = solution_dir / "layouts"
    portal_usage = []
    button_wiring = collections.Counter()
    field_coverage = collections.Counter()

    if layout_summaries_dir.exists():
        for json_path in sorted(layout_summaries_dir.glob("*.json")):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    summary = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            layout_name = summary.get("layout", json_path.stem)
            _walk_layout_objects(summary, layout_name, portal_usage,
                                button_wiring, field_coverage)

    # Detect orphaned layouts (not referenced by any script)
    script_referenced_layouts = set()
    for script_path in find_script_files(solution_name):
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                text = f.read()
            for match in RE_LAYOUT_REF.findall(text):
                script_referenced_layouts.add(match)
        except (OSError, UnicodeDecodeError):
            continue

    layout_names = set(l["name"] for l in layouts_index)
    orphaned = sorted(layout_names - script_referenced_layouts)

    return {
        "total": len(layouts_index),
        "by_base_to": {k: len(v) for k, v in sorted(by_base_to.items())},
        "by_folder": {k: len(v) for k, v in sorted(by_folder.items())},
        "classifications": dict(classifications),
        "portals": portal_usage[:20] if portal_usage else [],
        "button_wiring_count": len(button_wiring),
        "orphaned_layouts": orphaned,
        "has_layout_summaries": layout_summaries_dir.exists()
            and any(layout_summaries_dir.glob("*.json")),
    }


def _walk_layout_objects(obj, layout_name, portal_usage, button_wiring, field_coverage):
    """Recursively walk layout summary JSON for portal/button/field data."""
    if isinstance(obj, dict):
        obj_type = obj.get("type", "")
        if obj_type == "Portal":
            portal_usage.append({
                "layout": layout_name,
                "table": obj.get("table", "unknown"),
            })
        if "script" in obj:
            button_wiring[obj["script"]] += 1
        if "field" in obj:
            field_coverage[obj["field"]] += 1

        # Recurse into children
        for key in ("objects", "parts"):
            children = obj.get(key, [])
            if isinstance(children, list):
                for child in children:
                    _walk_layout_objects(child, layout_name, portal_usage,
                                        button_wiring, field_coverage)
    elif isinstance(obj, list):
        for item in obj:
            _walk_layout_objects(item, layout_name, portal_usage,
                                button_wiring, field_coverage)


# ---------------------------------------------------------------------------
# Integration points
# ---------------------------------------------------------------------------

def analyze_integrations(solution_name, value_lists_index, scripts_index):
    """Analyze external data sources, value lists, and external script calls."""
    # External data sources
    eds_dir = XML_PARSED_DIR / "external_data_sources" / solution_name
    external_sources = []
    if eds_dir.exists():
        for xml_path in sorted(eds_dir.glob("*.xml")):
            external_sources.append(xml_path.stem)

    # Value lists
    vl_by_source = collections.Counter(vl["source_type"] for vl in value_lists_index)

    # External calls from scripts (lightweight grep)
    external_call_scripts = collections.defaultdict(list)
    for script_path in find_script_files(solution_name):
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        script_name = script_path.stem.rsplit(" - ID ", 1)[0]
        for pattern, label in [
            (RE_INSERT_FROM_URL, "Insert from URL"),
            (RE_SEND_MAIL, "Send Mail"),
            (RE_EXPORT_RECORDS, "Export Records"),
            (RE_IMPORT_RECORDS, "Import Records"),
        ]:
            if pattern.search(text):
                external_call_scripts[label].append(script_name)

    return {
        "external_data_sources": external_sources,
        "value_lists": {
            "total": len(value_lists_index),
            "by_source": dict(vl_by_source),
        },
        "external_calls": {
            label: {"count": len(scripts), "scripts": scripts[:10]}
            for label, scripts in external_call_scripts.items()
        },
    }


# ---------------------------------------------------------------------------
# Multi-file solution detection
# ---------------------------------------------------------------------------

def detect_multi_file(solution_name):
    """Detect if this solution references other FM files."""
    eds_dir = XML_PARSED_DIR / "external_data_sources" / solution_name
    if not eds_dir.exists():
        return {"is_multi_file": False}

    import xml.etree.ElementTree as ET

    references = []
    for xml_path in sorted(eds_dir.glob("*.xml")):
        try:
            tree = ET.parse(str(xml_path))
            root = tree.getroot()
            # Look for file references
            for ds in root.iter("FileReference"):
                name = ds.get("name", xml_path.stem)
                references.append(name)
            if not references:
                references.append(xml_path.stem)
        except ET.ParseError:
            references.append(xml_path.stem)

    # Check if referenced files also exist in xml_parsed
    all_solutions = set()
    for domain_dir in XML_PARSED_DIR.iterdir():
        if domain_dir.is_dir() and domain_dir.name != "_":
            for sol_dir in domain_dir.iterdir():
                if sol_dir.is_dir():
                    all_solutions.add(sol_dir.name)

    correlated = [ref for ref in references if ref in all_solutions]

    return {
        "is_multi_file": len(references) > 0,
        "referenced_files": references,
        "correlated_solutions": correlated,
    }


# ---------------------------------------------------------------------------
# Health metrics
# ---------------------------------------------------------------------------

def analyze_health(solution_dir, fields_index, scripts_index, layouts_index,
                   relationships_index, to_index):
    """Compute health metrics from xref and index data."""
    xref = load_xref_index(solution_dir)

    result = {
        "xref_available": len(xref) > 0,
    }

    if not xref:
        result["note"] = (
            "xref.index not found. Run: python3 agent/scripts/trace.py build "
            f'-s "{solution_dir.name}" to enable health metrics.'
        )
        return result

    # Dead object analysis
    referenced = collections.defaultdict(set)
    for row in xref:
        referenced[row["ref_type"]].add(row["ref_name"])

    # Dead fields
    all_fields = set(f"{row['table']}::{row['field']}" for row in fields_index)
    referenced_fields = referenced.get("field", set())
    dead_fields = all_fields - referenced_fields
    # Filter out system fields
    system_prefixes = ("__kpt", "creation", "modification", "PrimaryKey")
    dead_fields_filtered = [
        f for f in dead_fields
        if not any(f.split("::")[-1].lower().startswith(p.lower())
                   for p in system_prefixes)
    ]

    # Dead scripts
    all_scripts = set(s["name"] for s in scripts_index)
    referenced_scripts = referenced.get("script", set())
    dead_scripts = all_scripts - referenced_scripts

    # Dead custom functions
    referenced_cfs = referenced.get("custom_func", set())

    # Disconnected tables (no relationships)
    tables_in_rels = set()
    to_map = {row["to_name"]: row["base_table"] for row in to_index}
    for r in relationships_index:
        tables_in_rels.add(to_map.get(r["left_to"], ""))
        tables_in_rels.add(to_map.get(r["right_to"], ""))
    all_tables = set(row["table"] for row in fields_index)
    disconnected_tables = sorted(all_tables - tables_in_rels - {""})

    # Empty scripts (0-1 lines)
    empty_scripts = []
    for script_path in find_script_files(solution_dir.name):
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                lines = [l for l in f.read().strip().split("\n") if l.strip()]
            if len(lines) == 0:
                name = script_path.stem.rsplit(" - ID ", 1)[0]
                empty_scripts.append(name)
        except (OSError, UnicodeDecodeError):
            continue

    result.update({
        "dead_fields": {
            "count": len(dead_fields_filtered),
            "sample": sorted(dead_fields_filtered)[:20],
        },
        "dead_scripts": {
            "count": len(dead_scripts),
            "sample": sorted(dead_scripts)[:20],
        },
        "disconnected_tables": disconnected_tables,
        "empty_scripts": empty_scripts[:20],
        "total_xref_entries": len(xref),
    })

    return result


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

def ensure_prerequisites(solution_name, solution_dir):
    """Build missing prerequisites (xref.index, layout summaries)."""
    built = []

    # Check xref.index
    xref_path = solution_dir / "xref.index"
    if not xref_path.exists():
        print(f"  Building xref.index...")
        trace_script = SCRIPT_DIR / "trace.py"
        result = subprocess.run(
            ["python3", str(trace_script), "build", "-s", solution_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            built.append("xref.index")
            print(f"    Done.")
        else:
            print(f"    WARNING: trace.py build failed: {result.stderr.strip()}")

    # Check layout summaries
    layouts_dir = solution_dir / "layouts"
    layout_xml_dir = XML_PARSED_DIR / "layouts" / solution_name
    if layout_xml_dir.exists() and (
        not layouts_dir.exists() or not any(layouts_dir.glob("*.json"))
    ):
        print(f"  Building layout summaries...")
        summary_script = SCRIPT_DIR / "layout_to_summary.py"
        result = subprocess.run(
            ["python3", str(summary_script), "--solution", solution_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            built.append("layout summaries")
            print(f"    Done.")
        else:
            print(f"    WARNING: layout_to_summary.py failed: {result.stderr.strip()}")

    return built


# ---------------------------------------------------------------------------
# Profile assembly
# ---------------------------------------------------------------------------

def build_profile(solution_name, deep=False):
    """Build the complete solution profile."""
    solution_dir = CONTEXT_DIR / solution_name

    if not solution_dir.exists():
        print(f"ERROR: No context directory for '{solution_name}'", file=sys.stderr)
        print(f"  Expected: {solution_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"==> Analyzing solution: {solution_name}")

    # Load all index files
    fields_index = load_fields_index(solution_dir)
    relationships_index = load_relationships_index(solution_dir)
    to_index = load_table_occurrences_index(solution_dir)
    scripts_index = load_scripts_index(solution_dir)
    layouts_index = load_layouts_index(solution_dir)
    value_lists_index = load_value_lists_index(solution_dir)

    print(f"  Loaded: {len(fields_index)} fields, {len(to_index)} TOs, "
          f"{len(scripts_index)} scripts, {len(layouts_index)} layouts, "
          f"{len(relationships_index)} relationships, {len(value_lists_index)} value lists")

    # Analyze each domain
    print("  Analyzing data model...")
    data_model = analyze_data_model(fields_index, to_index, relationships_index)

    print("  Detecting naming conventions...")
    conventions = detect_naming_conventions(fields_index)

    print("  Analyzing scripts...")
    scripts = analyze_scripts(solution_name, scripts_index, deep=deep)

    print("  Analyzing custom functions...")
    custom_functions = analyze_custom_functions(solution_name)

    print("  Analyzing layouts...")
    layouts = analyze_layouts(solution_name, solution_dir, layouts_index, scripts_index)

    print("  Analyzing integrations...")
    integrations = analyze_integrations(solution_name, value_lists_index, scripts_index)

    print("  Detecting multi-file references...")
    multi_file = detect_multi_file(solution_name)

    print("  Computing health metrics...")
    health = analyze_health(
        solution_dir, fields_index, scripts_index, layouts_index,
        relationships_index, to_index,
    )

    # Extension availability
    extensions_used = [
        name for name, info in EXTENSIONS.items() if info["available"]
    ]
    extensions_skipped = [
        name for name, info in EXTENSIONS.items() if not info["available"]
    ]

    profile = {
        "solution": solution_name,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generator": "analyze.py",
        "deep_mode": deep,
        "extensions": {
            "used": extensions_used,
            "skipped": extensions_skipped,
        },
        "summary": {
            "tables": data_model["table_count"],
            "fields": data_model["total_fields"],
            "table_occurrences": data_model["to_count"],
            "relationships": data_model["relationships"]["total"],
            "scripts": scripts["total_scripts"],
            "layouts": layouts["total"],
            "custom_functions": custom_functions["total"],
            "value_lists": integrations["value_lists"]["total"],
        },
        "data_model": data_model,
        "naming_conventions": conventions,
        "business_logic": scripts,
        "custom_functions": custom_functions,
        "ui_layer": layouts,
        "integrations": integrations,
        "multi_file": multi_file,
        "health": health,
    }

    print(f"\n==> Analysis complete.")
    return profile


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

def format_html(profile):
    """Format the profile as a self-contained HTML report."""
    # Template lives in the skill's assets folder per agentskills.io spec.
    # Try skill folder first, fall back to alongside this script.
    skill_assets = PROJECT_ROOT / ".cursor" / "skills" / "solution-analysis" / "assets"
    template_path = skill_assets / "report_template.html"
    if not template_path.exists():
        template_path = SCRIPT_DIR / "report_template.html"
    if not template_path.exists():
        print(f"ERROR: HTML template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Embed the profile JSON into the template.
    # Escape </script> and <!-- sequences that would break the HTML parser.
    profile_json = json.dumps(profile, ensure_ascii=False)
    profile_json = profile_json.replace("</", "<\\/")
    profile_json = profile_json.replace("<!--", "<\\!--")

    html = template.replace("{{PROFILE_JSON}}", profile_json)
    html = html.replace("{{SOLUTION_NAME}}", profile["solution"])
    html = html.replace("{{GENERATED_AT}}", profile["generated_at"])

    return html


def format_markdown(profile):
    """Format the profile as a markdown specification document."""
    lines = []
    sol = profile["solution"]
    summary = profile["summary"]

    lines.append(f"# Solution Analysis: {sol}")
    lines.append("")
    lines.append(f"*Generated: {profile['generated_at']}*")
    if profile["deep_mode"]:
        lines.append("*Mode: Deep analysis*")
    lines.append("")

    # --- Overview ---
    lines.append("## Overview")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    for label, key in [
        ("Base Tables", "tables"),
        ("Fields", "fields"),
        ("Table Occurrences", "table_occurrences"),
        ("Relationships", "relationships"),
        ("Scripts", "scripts"),
        ("Layouts", "layouts"),
        ("Custom Functions", "custom_functions"),
        ("Value Lists", "value_lists"),
    ]:
        lines.append(f"| {label} | {summary[key]} |")
    lines.append("")

    # Extensions note
    ext = profile.get("extensions", {})
    if ext.get("skipped"):
        lines.append(
            f"*Optional extensions not installed: {', '.join(ext['skipped'])}. "
            f"Install via `pip3 install -r .cursor/skills/solution-analysis/assets/requirements-analyze.txt` "
            f"for deeper analysis.*"
        )
        lines.append("")

    # --- Data Model ---
    dm = profile["data_model"]
    lines.append("## Data Model")
    lines.append("")

    # Tables
    lines.append("### Base Tables")
    lines.append("")
    lines.append("| Table | Fields | PK | FKs | Primary Types |")
    lines.append("|-------|--------|----|-----|---------------|")
    for tname, t in sorted(dm["tables"].items()):
        pk = "Yes" if t["has_primary_key"] else "No"
        top_types = ", ".join(
            f"{k}: {v}" for k, v in sorted(
                t["by_datatype"].items(), key=lambda x: x[1], reverse=True
            )[:3]
        )
        lines.append(
            f"| {tname} | {t['field_count']} | {pk} | {t['foreign_key_count']} | {top_types} |"
        )
    lines.append("")

    # Topology
    topo = dm.get("topology", {})
    if topo:
        lines.append("### Relationship Graph Topology")
        lines.append("")
        lines.append(f"- **Pattern:** {topo.get('pattern', 'unknown')}")
        if "confidence" in topo:
            lines.append(f"- **Confidence:** {topo['confidence']}")
        lines.append(f"- **Avg degree:** {topo.get('avg_degree', 'N/A')}")
        lines.append(f"- **Max degree:** {topo.get('max_degree', 'N/A')}")
        lines.append(f"- **Hub TOs (degree >= 5):** {topo.get('hub_count', 0)}")
        if topo.get("anchor_tables"):
            lines.append(f"- **Anchor tables:** {', '.join(topo['anchor_tables'])}")
        if topo.get("connected_components", 0) > 1:
            lines.append(f"- **Connected components:** {topo['connected_components']}")
        if topo.get("bridge_count"):
            lines.append(f"- **Bridge relationships:** {topo['bridge_count']}")
        lines.append("")

    # Relationships summary
    rels = dm["relationships"]
    lines.append("### Relationships")
    lines.append("")
    lines.append(f"- **Total:** {rels['total']}")
    lines.append(f"- **Join types:** {', '.join(f'{k}: {v}' for k, v in rels['by_join_type'].items())}")
    lines.append(f"- **Cascade create:** {rels['cascades']['create']}")
    lines.append(f"- **Cascade delete:** {rels['cascades']['delete']}")
    lines.append(f"- **Multi-predicate joins:** {rels['multi_predicate']}")
    lines.append(f"- **Self-joins:** {rels['self_joins']}")
    lines.append("")

    # ERD (Mermaid) — collapse TOs to base tables and draw edges
    lines.append("### Entity Relationship Diagram")
    lines.append("")
    lines.append("```mermaid")
    lines.append("erDiagram")
    for tname, t in dm["tables"].items():
        field_count = t["field_count"]
        lines.append(f'    {_mermaid_safe(tname)} {{')
        lines.append(f'        int fields "{field_count} fields"')
        lines.append(f'    }}')

    # Add relationship lines collapsed to base tables
    for edge in dm.get("base_table_edges", []):
        left_safe = _mermaid_safe(edge[0])
        right_safe = _mermaid_safe(edge[1])
        lines.append(f'    {left_safe} ||--o{{ {right_safe} : ""')

    lines.append("```")
    lines.append("")

    # --- Naming Conventions ---
    conv = profile["naming_conventions"]
    lines.append("## Naming Conventions")
    lines.append("")
    lines.append(f"- **Dominant case style:** {conv['dominant_case']}")
    lines.append("")
    if conv["prefix_conventions"]:
        lines.append("| Prefix | Convention | Count |")
        lines.append("|--------|-----------|-------|")
        for prefix, count in conv["prefix_conventions"].items():
            lines.append(f"| `{prefix}` | {count} |")
        lines.append("")

    # --- Business Logic ---
    bl = profile["business_logic"]
    lines.append("## Business Logic")
    lines.append("")
    lines.append(f"- **Total scripts:** {bl['total_scripts']}")
    lines.append(f"- **Scripts analyzed:** {bl['total_files_analyzed']}")
    lines.append(f"- **Call graph edges:** {bl['call_graph_edges']}")
    lines.append(f"- **Total lines:** {bl['line_counts']['total']}")
    lines.append(f"- **Avg lines/script:** {bl['line_counts']['avg']}")
    lines.append(f"- **Max lines:** {bl['line_counts']['max']}")
    lines.append("")

    # Script folders
    lines.append("### Script Folders")
    lines.append("")
    lines.append("| Folder | Scripts |")
    lines.append("|--------|---------|")
    for folder, info in sorted(bl["folders"].items()):
        lines.append(f"| {folder} | {info['count']} |")
    lines.append("")

    # Entry points
    if bl["entry_points"]:
        lines.append("### Entry Point Scripts")
        lines.append("")
        lines.append("Scripts not called by any other script (likely triggered by UI):")
        lines.append("")
        for name in bl["entry_points"][:20]:
            lines.append(f"- {name}")
        lines.append("")

    # Utility scripts
    if bl["utility_scripts"]:
        lines.append("### Utility Scripts")
        lines.append("")
        lines.append("Scripts called by 3+ other scripts:")
        lines.append("")
        for name in bl["utility_scripts"][:20]:
            lines.append(f"- {name}")
        lines.append("")

    # Clusters
    if bl["clusters"]:
        lines.append("### Functional Clusters")
        lines.append("")
        for cluster in bl["clusters"]:
            if "_cycles_detected" in cluster:
                lines.append(f"- **Cycles detected:** {cluster['_cycles_detected']}")
                continue
            lines.append(
                f"- **{cluster['name']}** — {cluster['script_count']} scripts"
            )
            if cluster.get("entry_points"):
                lines.append(
                    f"  - Entry points: {', '.join(cluster['entry_points'])}"
                )
            if cluster.get("bottleneck"):
                lines.append(f"  - Bottleneck: {cluster['bottleneck']}")
        lines.append("")

    # Largest scripts
    if bl["line_counts"]["largest_scripts"]:
        lines.append("### Largest Scripts")
        lines.append("")
        lines.append("| Script | Lines |")
        lines.append("|--------|-------|")
        for name, count in bl["line_counts"]["largest_scripts"]:
            lines.append(f"| {name} | {count} |")
        lines.append("")

    # Deep metrics
    if "deep_metrics" in bl:
        dm_deep = bl["deep_metrics"]
        lines.append("### Deep Analysis Metrics")
        lines.append("")
        eh = dm_deep["error_handling"]
        lines.append(f"- **Error handling coverage:** {eh['coverage_pct']}% "
                      f"({eh['with_capture']}/{eh['with_capture'] + eh['without_capture']})")
        lines.append(f"- **Scripts using transactions:** {dm_deep['transactions']['scripts_using']}")
        lines.append(f"- **Max nesting depth:** {dm_deep['nesting']['max_depth']}")
        lines.append(f"- **Avg nesting depth:** {dm_deep['nesting']['avg_depth']}")
        lines.append("")

        if dm_deep["external_calls"]:
            lines.append("#### External Calls")
            lines.append("")
            for call_type, count in dm_deep["external_calls"].items():
                lines.append(f"- {call_type}: {count}")
            lines.append("")

        if dm_deep["step_frequency"]:
            lines.append("#### Most Used Steps")
            lines.append("")
            lines.append("| Step | Count |")
            lines.append("|------|-------|")
            for step, count in dm_deep["step_frequency"].items():
                lines.append(f"| {step} | {count} |")
            lines.append("")

    # --- Custom Functions ---
    cf = profile["custom_functions"]
    lines.append("## Custom Functions")
    lines.append("")
    lines.append(f"- **Total:** {cf['total']}")
    if "categories" in cf:
        cats = cf["categories"]
        lines.append(f"- **Constants:** {cats.get('constant', 0)}")
        lines.append(f"- **Functional:** {cats.get('functional', 0)}")
        lines.append(f"- **Solution-specific:** {cats.get('solution_specific', 0)}")
    lines.append("")

    if cf.get("dependency_chains"):
        lines.append("### Dependency Chains")
        lines.append("")
        for chain in cf["dependency_chains"]:
            lines.append(f"- {chain['function']} (depth: {chain['depth']})")
        lines.append("")

    # --- UI Layer ---
    ui = profile["ui_layer"]
    lines.append("## UI Layer")
    lines.append("")
    lines.append(f"- **Total layouts:** {ui['total']}")
    lines.append(f"- **Orphaned layouts:** {len(ui['orphaned_layouts'])}")
    lines.append(f"- **Layout summaries available:** {'Yes' if ui['has_layout_summaries'] else 'No'}")
    lines.append("")

    if ui["classifications"]:
        lines.append("### Layout Classification")
        lines.append("")
        lines.append("| Type | Count |")
        lines.append("|------|-------|")
        for cat, count in sorted(ui["classifications"].items()):
            lines.append(f"| {cat} | {count} |")
        lines.append("")

    if ui["by_base_to"]:
        lines.append("### Layouts by Base Table")
        lines.append("")
        lines.append("| Base TO | Layouts |")
        lines.append("|---------|---------|")
        for to_name, count in sorted(ui["by_base_to"].items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {to_name} | {count} |")
        lines.append("")

    if ui["portals"]:
        lines.append("### Portal Usage")
        lines.append("")
        for portal in ui["portals"]:
            lines.append(f"- Layout **{portal['layout']}** embeds portal to **{portal['table']}**")
        lines.append("")

    if ui["orphaned_layouts"]:
        lines.append("### Orphaned Layouts")
        lines.append("")
        lines.append("Layouts not referenced by any script `Go to Layout` step:")
        lines.append("")
        for name in ui["orphaned_layouts"][:20]:
            lines.append(f"- {name}")
        lines.append("")

    # --- Integrations ---
    integ = profile["integrations"]
    lines.append("## Integration Points")
    lines.append("")

    if integ["external_data_sources"]:
        lines.append("### External Data Sources")
        lines.append("")
        for src in integ["external_data_sources"]:
            lines.append(f"- {src}")
        lines.append("")

    lines.append("### Value Lists")
    lines.append("")
    lines.append(f"- **Total:** {integ['value_lists']['total']}")
    for src_type, count in integ["value_lists"]["by_source"].items():
        lines.append(f"- **{src_type}:** {count}")
    lines.append("")

    if integ["external_calls"]:
        lines.append("### External Script Calls")
        lines.append("")
        for call_type, info in integ["external_calls"].items():
            lines.append(f"- **{call_type}:** {info['count']} occurrence(s)")
            for s in info["scripts"][:5]:
                lines.append(f"  - {s}")
        lines.append("")

    # --- Multi-file ---
    mf = profile["multi_file"]
    if mf["is_multi_file"]:
        lines.append("## Multi-File Solution")
        lines.append("")
        lines.append(f"- **Referenced files:** {', '.join(mf['referenced_files'])}")
        if mf["correlated_solutions"]:
            lines.append(f"- **Correlated (also exploded):** {', '.join(mf['correlated_solutions'])}")
        lines.append("")

    # --- Health ---
    health = profile["health"]
    lines.append("## Health Metrics")
    lines.append("")

    if not health.get("xref_available"):
        lines.append(f"*{health.get('note', 'xref.index not available')}*")
        lines.append("")
    else:
        lines.append(f"- **Total cross-references:** {health.get('total_xref_entries', 0)}")
        lines.append("")

        df = health.get("dead_fields", {})
        ds = health.get("dead_scripts", {})
        lines.append(f"- **Dead fields:** {df.get('count', 0)}")
        lines.append(f"- **Dead scripts:** {ds.get('count', 0)}")
        lines.append(f"- **Disconnected tables:** {len(health.get('disconnected_tables', []))}")
        lines.append(f"- **Empty scripts:** {len(health.get('empty_scripts', []))}")
        lines.append("")

        if health.get("disconnected_tables"):
            lines.append("### Disconnected Tables")
            lines.append("")
            for t in health["disconnected_tables"]:
                lines.append(f"- {t}")
            lines.append("")

        if health.get("empty_scripts"):
            lines.append("### Empty Scripts")
            lines.append("")
            for s in health["empty_scripts"]:
                lines.append(f"- {s}")
            lines.append("")

    lines.append("---")
    lines.append(f"*Generated by analyze.py | {profile['generated_at']}*")

    return "\n".join(lines)


def _mermaid_safe(name):
    """Make a name safe for Mermaid diagrams."""
    # Replace spaces and special chars with underscores
    return re.sub(r'[^A-Za-z0-9_]', '_', name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def list_extensions():
    """Print available extensions and exit."""
    for name, info in EXTENSIONS.items():
        try:
            mod = __import__(name)
            version = getattr(mod, "__version__", "unknown")
            status = f"installed (v{version})"
        except ImportError:
            status = "not installed"

        pad = "." * (16 - len(name))
        desc = info["description"]
        print(f"  {name} {pad} {status:30s} -> {desc}")


def main():
    parser = argparse.ArgumentParser(
        description="Solution-level analysis for FileMaker solutions."
    )
    parser.add_argument(
        "-s", "--solution",
        help="Solution name (as it appears in agent/context/)",
    )
    parser.add_argument(
        "--format", choices=["json", "markdown", "html"], default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--deep", action="store_true",
        help="Enable full script text analysis",
    )
    parser.add_argument(
        "--ensure-prerequisites", action="store_true",
        help="Build xref.index and layout summaries if missing",
    )
    parser.add_argument(
        "--list-extensions", action="store_true",
        help="Show available optional dependencies and exit",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output path override",
    )

    args = parser.parse_args()

    if args.list_extensions:
        print("Optional extensions for analyze.py:")
        print()
        list_extensions()
        return

    if not args.solution:
        # Try to auto-detect if only one solution exists
        solutions = [
            d.name for d in CONTEXT_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        if len(solutions) == 1:
            args.solution = solutions[0]
            print(f"Auto-detected solution: {args.solution}")
        else:
            parser.error(
                "Please specify a solution with -s. "
                f"Available: {', '.join(sorted(solutions))}"
            )

    solution_dir = CONTEXT_DIR / args.solution

    # Ensure prerequisites if requested
    if args.ensure_prerequisites:
        print("Checking prerequisites...")
        built = ensure_prerequisites(args.solution, solution_dir)
        if built:
            print(f"  Built: {', '.join(built)}")
        else:
            print("  All prerequisites present.")

    # Build profile
    profile = build_profile(args.solution, deep=args.deep)

    # Determine output path — deliverables go to sandbox
    sandbox_dir = PROJECT_ROOT / "agent" / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = Path(args.output)
    elif args.format == "markdown":
        output_path = sandbox_dir / f"{args.solution} - solution-profile.md"
    elif args.format == "html":
        output_path = sandbox_dir / f"{args.solution} - solution-profile.html"
    else:
        output_path = sandbox_dir / f"{args.solution} - solution-profile.json"

    # Write output
    if args.format == "markdown":
        content = format_markdown(profile)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Markdown: {output_path}")
    elif args.format == "html":
        content = format_html(profile)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  HTML: {output_path}")
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
        print(f"  JSON: {output_path}")

    # Also write JSON when markdown/html is requested (profile is always useful)
    if args.format in ("markdown", "html"):
        json_path = sandbox_dir / f"{args.solution} - solution-profile.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
        print(f"  JSON: {json_path}")


if __name__ == "__main__":
    main()
