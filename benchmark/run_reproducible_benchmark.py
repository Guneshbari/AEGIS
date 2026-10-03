"""Reproducible benchmark runner for AEGIS adaptive caching against LRU, LFU, and GDS.

Executes deterministic workload scenarios (steady, popularity-shift, cost-sensitive)
with warm-up separation, identical request sequences, and unified metrics collection.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.cost.profiles import get_profile as get_cost_profile
from backend.workload.generator import (
    ScenarioGenerator,
)
from backend.workload.scenario import (
    PRODUCT_CATALOG_PROFILE,
    ScenarioConfig,
    ScenarioEvent,
)
from benchmark.cache_simulator import CacheSimulator
from benchmark.policies import get_policy_adapter
from benchmark.results import calculate_percentile


def run_benchmark(
    seed: int = 42,
    warmup_requests: int = 1000,
    measured_requests: int = 4000,
    output_dir: str = "benchmark/results",
    cost_profile_name: str = "default",
) -> dict[str, Any]:
    """Execute complete reproducible benchmark suite across all workloads and policies."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    cost_profile = get_cost_profile(cost_profile_name)

    workload_configs = [
        {
            "name": "steady",
            "capacity_bytes": 40960,  # ~20 objects
            "adaptive_window_seconds": 2.0,
            "generator": lambda s, n_warm, n_meas: _generate_steady_events(s, n_warm, n_meas),
            "description": "Stable request stream with 80/20 popularity distribution",
        },
        {
            "name": "popularity_shift",
            "capacity_bytes": 40960,  # ~20 objects
            "adaptive_window_seconds": 3.0,
            "generator": lambda s, n_warm, n_meas: _generate_shift_events(s, n_warm, n_meas),
            "description": "Progressive shift in hot set from initial to disjoint final objects",
        },
        {
            "name": "cost_sensitive",
            "capacity_bytes": 61440,  # ~60 KB for multi-size archetypes
            "adaptive_window_seconds": 3.0,
            "generator": lambda s, n_warm, n_meas: _generate_cost_sensitive_events(s, n_warm, n_meas),
            "description": "Varied object sizes (1KB-16KB) and retrieval costs (10ms-250ms)",
        },
    ]

    policies = ["LRU", "LFU", "GDS", "AEGIS"]
    all_results: list[dict[str, Any]] = []
    warmup_results: list[dict[str, Any]] = []

    for w_cfg in workload_configs:
        w_name = w_cfg["name"]
        cap_bytes = w_cfg["capacity_bytes"]
        win_s = w_cfg["adaptive_window_seconds"]

        warmup_events, measured_events = w_cfg["generator"](
            seed, warmup_requests, measured_requests
        )

        span = 0.0
        if len(measured_events) >= 2:
            span = (measured_events[-1].timestamp - measured_events[0].timestamp).total_seconds()

        for policy_name in policies:
            adapter = get_policy_adapter(policy_name, window_seconds=win_s)
            sim = CacheSimulator(
                capacity_bytes=cap_bytes,
                policy=adapter,
                hit_latency_ms=1.0,
            )

            # --- WARM-UP PHASE ---
            warmup_start_wall = time.perf_counter()
            for ev in warmup_events:
                sim.process_event(ev)
            warmup_elapsed_wall = time.perf_counter() - warmup_start_wall

            warmup_m = sim.get_metrics(duration_seconds=warmup_requests / 100.0, cost_profile=cost_profile)
            warmup_results.append({
                "workload": w_name,
                "policy": policy_name,
                "warmup_requests": warmup_m.total_requests,
                "warmup_hits": warmup_m.cache_hits,
                "warmup_hit_ratio": warmup_m.hit_ratio,
                "warmup_evictions": warmup_m.eviction_count,
                "warmup_elapsed_seconds": round(warmup_elapsed_wall, 4),
            })


            # Separate warmup measurements: clear metrics while retaining cached objects and policy state
            sim.reset_metrics()

            # --- MEASURED PHASE ---
            measured_start_wall = time.perf_counter()
            for ev in measured_events:
                sim.process_event(ev)
            measured_elapsed_wall = time.perf_counter() - measured_start_wall

            m = sim.get_metrics(duration_seconds=span, cost_profile=cost_profile)
            p50 = calculate_percentile(sim._latencies, 50.0) if sim._latencies else 0.0
            p95 = calculate_percentile(sim._latencies, 95.0) if sim._latencies else 0.0
            p99 = calculate_percentile(sim._latencies, 99.0) if sim._latencies else 0.0
            wall_throughput = (
                round(len(measured_events) / measured_elapsed_wall, 1)
                if measured_elapsed_wall > 0
                else 0.0
            )

            res_dict = {
                "workload": w_name,
                "policy": policy_name,
                "requests": m.total_requests,
                "hits": m.cache_hits,
                "misses": m.cache_misses,
                "hit_ratio": round(m.hit_ratio, 4),
                "backend_calls": m.backend_requests,
                "backend_calls_prevented": m.backend_requests_prevented,
                "avg_latency": round(m.average_latency_ms, 2),
                "p50_latency": round(p50, 2),
                "p95_latency": round(p95, 2),
                "p99_latency": round(p99, 2),
                "evictions": m.eviction_count,
                "memory_usage": sim.current_usage_bytes,
                "peak_memory_usage": m.peak_cache_usage_bytes,
                "cache_capacity_bytes": cap_bytes,
                "estimated_cost": round(m.estimated_cost, 4),
                "throughput": round(m.throughput_rps, 2),
                "wall_throughput_rps": wall_throughput,
            }
            all_results.append(res_dict)

    # Compute improvements of AEGIS relative to LRU, LFU, and GDS
    improvements = _compute_improvements(all_results)

    # Output structured data
    benchmark_payload = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "seed": seed,
            "warmup_requests": warmup_requests,
            "measured_requests": measured_requests,
            "cost_profile": cost_profile.name,
            "policies": policies,
            "workloads": [w["name"] for w in workload_configs],
        },
        "raw_results": all_results,
        "warmup_results": warmup_results,
        "improvements": improvements,
    }

    # Write JSON
    json_path = out_path / "reproducible_benchmark_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_payload, f, indent=2)

    # Write CSV
    csv_path = out_path / "reproducible_benchmark_results.csv"
    _write_csv(csv_path, all_results)

    # Write Report Markdown
    report_path = out_path / "benchmark_report.md"
    report_md = _generate_report_markdown(benchmark_payload)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    return benchmark_payload


def _generate_steady_events(seed: int, n_warm: int, n_meas: int) -> tuple[list[ScenarioEvent], list[ScenarioEvent]]:
    total = n_warm + n_meas
    cfg = ScenarioConfig(
        name="steady",
        scenario_type="steady",
        seed=seed,
        object_count=100,
        request_count=total,
        request_rate=100.0,
        hot_set_size=15,
        profile=PRODUCT_CATALOG_PROFILE,
    )
    events = ScenarioGenerator(cfg).generate()
    return events[:n_warm], events[n_warm:]


def _generate_shift_events(seed: int, n_warm: int, n_meas: int) -> tuple[list[ScenarioEvent], list[ScenarioEvent]]:
    # Warmup with initial steady state
    warmup_cfg = ScenarioConfig(
        name="popularity_shift_warmup",
        scenario_type="steady",
        seed=seed + 100,
        object_count=100,
        request_count=n_warm,
        request_rate=100.0,
        hot_set_size=15,
        profile=PRODUCT_CATALOG_PROFILE,
    )
    warmup = ScenarioGenerator(warmup_cfg).generate()

    # Measured sequence executes popularity shift
    shift_cfg = ScenarioConfig(
        name="popularity_shift",
        scenario_type="popularity_shift",
        seed=seed,
        object_count=100,
        request_count=n_meas,
        request_rate=100.0,
        hot_set_size=15,
        profile=PRODUCT_CATALOG_PROFILE,
    )
    measured = ScenarioGenerator(shift_cfg).generate()
    return warmup, measured


def _generate_cost_sensitive_events(seed: int, n_warm: int, n_meas: int) -> tuple[list[ScenarioEvent], list[ScenarioEvent]]:
    total = n_warm + n_meas
    cfg = ScenarioConfig(
        name="cost_sensitive",
        scenario_type="cost_sensitive",
        seed=seed,
        object_count=100,
        request_count=total,
        request_rate=100.0,
        hot_set_size=15,
    )
    events = ScenarioGenerator(cfg).generate()
    return events[:n_warm], events[n_warm:]


def _compute_improvements(results: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    """Compute percentage improvements for AEGIS versus each baseline for each workload."""
    by_workload: dict[str, dict[str, dict[str, Any]]] = {}
    for r in results:
        w = r["workload"]
        p = r["policy"]
        by_workload.setdefault(w, {})[p] = r

    improvements: dict[str, dict[str, dict[str, float]]] = {}
    for w, policies in by_workload.items():
        if "AEGIS" not in policies:
            continue
        aegis = policies["AEGIS"]
        improvements[w] = {}

        for base_p in ["LRU", "LFU", "GDS"]:
            if base_p not in policies:
                continue
            base = policies[base_p]

            # Backend call reduction: (baseline - AEGIS) / baseline * 100
            b_calls_base = base["backend_calls"]
            b_calls_aegis = aegis["backend_calls"]
            backend_reduction = (
                ((b_calls_base - b_calls_aegis) / b_calls_base * 100)
                if b_calls_base > 0
                else 0.0
            )

            # Latency improvements
            lat_p50_red = (
                ((base["p50_latency"] - aegis["p50_latency"]) / base["p50_latency"] * 100)
                if base["p50_latency"] > 0
                else 0.0
            )
            lat_p95_red = (
                ((base["p95_latency"] - aegis["p95_latency"]) / base["p95_latency"] * 100)
                if base["p95_latency"] > 0
                else 0.0
            )
            lat_p99_red = (
                ((base["p99_latency"] - aegis["p99_latency"]) / base["p99_latency"] * 100)
                if base["p99_latency"] > 0
                else 0.0
            )
            lat_avg_red = (
                ((base["avg_latency"] - aegis["avg_latency"]) / base["avg_latency"] * 100)
                if base["avg_latency"] > 0
                else 0.0
            )

            # Eviction reduction
            evict_base = base["evictions"]
            evict_aegis = aegis["evictions"]
            evict_red = (
                ((evict_base - evict_aegis) / evict_base * 100)
                if evict_base > 0
                else 0.0
            )

            # Hit ratio improvement (relative & absolute percentage points)
            hit_rel = (
                ((aegis["hit_ratio"] - base["hit_ratio"]) / base["hit_ratio"] * 100)
                if base["hit_ratio"] > 0
                else 0.0
            )
            hit_pts = (aegis["hit_ratio"] - base["hit_ratio"]) * 100

            # Cost reduction
            cost_base = base["estimated_cost"]
            cost_aegis = aegis["estimated_cost"]
            cost_red = (
                ((cost_base - cost_aegis) / cost_base * 100)
                if cost_base > 0
                else 0.0
            )

            improvements[w][base_p] = {
                "hit_ratio_relative_improvement_pct": round(hit_rel, 2),
                "hit_ratio_point_improvement": round(hit_pts, 2),
                "backend_call_reduction_pct": round(backend_reduction, 2),
                "p50_latency_reduction_pct": round(lat_p50_red, 2),
                "p95_latency_reduction_pct": round(lat_p95_red, 2),
                "p99_latency_reduction_pct": round(lat_p99_red, 2),
                "avg_latency_reduction_pct": round(lat_avg_red, 2),
                "eviction_reduction_pct": round(evict_red, 2),
                "estimated_cost_reduction_pct": round(cost_red, 2),
            }

    return improvements


def _write_csv(csv_path: Path, results: list[dict[str, Any]]) -> None:
    headers = [
        "workload",
        "policy",
        "requests",
        "hits",
        "misses",
        "hit_ratio",
        "backend_calls",
        "p50_latency",
        "p95_latency",
        "p99_latency",
        "evictions",
        "memory_usage",
        "estimated_cost",
        "throughput",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)


def _generate_report_markdown(payload: dict[str, Any]) -> str:
    meta = payload["metadata"]
    results = payload["raw_results"]
    improvements = payload["improvements"]

    lines = [
        "# AEGIS Adaptive Caching Benchmark Report",
        "",
        f"**Date:** {meta['timestamp']}",
        f"**Random Seed:** {meta['seed']}",
        f"**Warmup Requests:** {meta['warmup_requests']:,}",
        f"**Measured Requests:** {meta['measured_requests']:,}",
        f"**Cost Profile:** `{meta['cost_profile']}` (modeled platform economics)",
        "",
        "## 1. Executive Summary",
        "",
        "This benchmark deterministically measures the performance of **AEGIS** (Adaptive Engine for Intelligent Caching & Scaling)",
        "against three foundational caching baselines: **LRU** (Least Recently Used), **LFU** (Least Frequently Used), and",
        "**GDS** (Greedy-Dual-Size). All policies were subjected to identical request sequences, object sizes, backend retrieval costs,",
        "and cache capacities, with separate warm-up phases to eliminate cold-start bias.",
        "",
        "## 2. Comparison Table (Measured Results)",
        "",
        "| Workload | Policy | Requests | Hits | Misses | Hit Ratio | Backend Calls | P50 (ms) | P95 (ms) | P99 (ms) | Evictions | Memory (B) | Estimated Cost | Throughput (req/s) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for r in results:
        lines.append(
            f"| {r['workload']} | **{r['policy']}** | {r['requests']:,} | {r['hits']:,} | {r['misses']:,} | "
            f"**{r['hit_ratio']:.2%}** | {r['backend_calls']:,} | {r['p50_latency']:.2f} | {r['p95_latency']:.2f} | "
            f"{r['p99_latency']:.2f} | {r['evictions']:,} | {r['memory_usage']:,} | {r['estimated_cost']:.2f} | {r['throughput']:.1f} |"
        )

    lines.extend([
        "",
        "## 3. AEGIS Relative Improvements vs Baselines",
        "",
        "> [!NOTE]",
        "> Percentage improvements are computed as `(Baseline - AEGIS) / Baseline * 100` for metrics where lower is better (calls, latency, evictions, cost),",
        "> and `(AEGIS - Baseline) / Baseline * 100` for hit ratio (where higher is better).",
        "",
    ])

    for w, baselines in improvements.items():
        lines.extend([
            f"### Workload: `{w}`",
            "",
            "| Baseline | Hit Ratio Relative | Hit Ratio Points | Backend Call Red. | P50 Latency Red. | P95 Latency Red. | Avg Latency Red. | Eviction Red. | Est. Cost Red. |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for b_name, imp in baselines.items():
            lines.append(
                f"| vs **{b_name}** | **+{imp['hit_ratio_relative_improvement_pct']:.1f}%** | "
                f"+{imp['hit_ratio_point_improvement']:.2f}% | "
                f"**{imp['backend_call_reduction_pct']:.1f}%** | "
                f"{imp['p50_latency_reduction_pct']:.1f}% | "
                f"{imp['p95_latency_reduction_pct']:.1f}% | "
                f"{imp['avg_latency_reduction_pct']:.1f}% | "
                f"**{imp['eviction_reduction_pct']:.1f}%** | "
                f"{imp['estimated_cost_reduction_pct']:.1f}% |"
            )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run reproducible AEGIS benchmark suite")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic RNG seed")
    parser.add_argument("--warmup-requests", type=int, default=1000, help="Number of warmup requests")
    parser.add_argument("--measured-requests", type=int, default=4000, help="Number of measured requests")
    parser.add_argument("--output-dir", type=str, default="benchmark/results", help="Directory for output files")
    parser.add_argument("--cost-profile", type=str, default="default", help="Cost profile name")

    args = parser.parse_args()
    payload = run_benchmark(
        seed=args.seed,
        warmup_requests=args.warmup_requests,
        measured_requests=args.measured_requests,
        output_dir=args.output_dir,
        cost_profile_name=args.cost_profile,
    )
    print("Benchmark complete. Results saved to:", args.output_dir)
