# AEGIS Adaptive Caching Benchmark Report

**Date:** 2026-10-03T18:14:16.089438+00:00
**Random Seed:** 42
**Warmup Requests:** 1,000
**Measured Requests:** 4,000
**Cost Profile:** `default` (modeled platform economics)

## 1. Executive Summary

This benchmark deterministically measures the performance of **AEGIS** (Adaptive Engine for Intelligent Caching & Scaling)
against three foundational caching baselines: **LRU** (Least Recently Used), **LFU** (Least Frequently Used), and
**GDS** (Greedy-Dual-Size). All policies were subjected to identical request sequences, object sizes, backend retrieval costs,
and cache capacities, with separate warm-up phases to eliminate cold-start bias.

## 2. Comparison Table (Measured Results)

| Workload | Policy | Requests | Hits | Misses | Hit Ratio | Backend Calls | P50 (ms) | P95 (ms) | P99 (ms) | Evictions | Memory (B) | Estimated Cost | Throughput (req/s) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| steady | **LRU** | 4,000 | 2,863 | 1,137 | **71.57%** | 1,137 | 1.00 | 6.00 | 6.00 | 1,137 | 40,960 | 5685.00 | 100.0 |
| steady | **LFU** | 4,000 | 3,279 | 721 | **81.97%** | 721 | 1.00 | 6.00 | 6.00 | 721 | 40,960 | 3605.00 | 100.0 |
| steady | **GDS** | 4,000 | 591 | 3,409 | **14.77%** | 3,409 | 6.00 | 6.00 | 6.00 | 3,409 | 40,960 | 17045.00 | 100.0 |
| steady | **AEGIS** | 4,000 | 3,054 | 946 | **76.35%** | 946 | 1.00 | 6.00 | 6.00 | 946 | 40,960 | 4730.00 | 100.0 |
| popularity_shift | **LRU** | 4,000 | 2,425 | 1,575 | **60.62%** | 1,575 | 1.00 | 6.00 | 6.00 | 1,575 | 40,960 | 7875.00 | 100.0 |
| popularity_shift | **LFU** | 4,000 | 2,108 | 1,892 | **52.70%** | 1,892 | 1.00 | 6.00 | 6.00 | 1,892 | 40,960 | 9460.00 | 100.0 |
| popularity_shift | **GDS** | 4,000 | 1,930 | 2,070 | **48.25%** | 2,070 | 6.00 | 6.00 | 6.00 | 2,070 | 40,960 | 10350.00 | 100.0 |
| popularity_shift | **AEGIS** | 4,000 | 2,764 | 1,236 | **69.10%** | 1,236 | 1.00 | 6.00 | 6.00 | 1,236 | 40,960 | 6180.00 | 100.0 |
| cost_sensitive | **LRU** | 4,000 | 1,494 | 2,506 | **37.35%** | 2,506 | 11.03 | 263.97 | 272.76 | 2,504 | 57,101 | 271871.03 | 100.0 |
| cost_sensitive | **LFU** | 4,000 | 2,537 | 1,463 | **63.42%** | 1,463 | 1.00 | 272.46 | 272.76 | 1,464 | 43,869 | 170615.53 | 100.0 |
| cost_sensitive | **GDS** | 4,000 | 1,778 | 2,222 | **44.45%** | 2,222 | 10.71 | 262.88 | 271.82 | 2,221 | 46,482 | 154869.71 | 100.0 |
| cost_sensitive | **AEGIS** | 4,000 | 2,477 | 1,523 | **61.92%** | 1,523 | 1.00 | 262.88 | 272.76 | 1,529 | 53,403 | 131366.47 | 100.0 |

## 3. AEGIS Relative Improvements vs Baselines

> [!NOTE]
> Percentage improvements are computed as `(Baseline - AEGIS) / Baseline * 100` for metrics where lower is better (calls, latency, evictions, cost),
> and `(AEGIS - Baseline) / Baseline * 100` for hit ratio (where higher is better).

### Workload: `steady`

| Baseline | Hit Ratio Relative | Hit Ratio Points | Backend Call Red. | P50 Latency Red. | P95 Latency Red. | Avg Latency Red. | Eviction Red. | Est. Cost Red. |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| vs **LRU** | **+6.7%** | +4.78% | **16.8%** | 0.0% | 0.0% | 9.9% | **16.8%** | 16.8% |
| vs **LFU** | **+-6.9%** | +-5.62% | **-31.2%** | 0.0% | 0.0% | -14.7% | **-31.2%** | -31.2% |
| vs **GDS** | **+416.9%** | +61.58% | **72.2%** | 83.3% | 0.0% | 58.6% | **72.2%** | 72.2% |

### Workload: `popularity_shift`

| Baseline | Hit Ratio Relative | Hit Ratio Points | Backend Call Red. | P50 Latency Red. | P95 Latency Red. | Avg Latency Red. | Eviction Red. | Est. Cost Red. |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| vs **LRU** | **+14.0%** | +8.48% | **21.5%** | 0.0% | 0.0% | 14.5% | **21.5%** | 21.5% |
| vs **LFU** | **+31.1%** | +16.40% | **34.7%** | 0.0% | 0.0% | 24.6% | **34.7%** | 34.7% |
| vs **GDS** | **+43.2%** | +20.85% | **40.3%** | 83.3% | 0.0% | 29.2% | **40.3%** | 40.3% |

### Workload: `cost_sensitive`

| Baseline | Hit Ratio Relative | Hit Ratio Points | Backend Call Red. | P50 Latency Red. | P95 Latency Red. | Avg Latency Red. | Eviction Red. | Est. Cost Red. |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| vs **LRU** | **+65.8%** | +24.57% | **39.2%** | 90.9% | 0.4% | 50.9% | **38.9%** | 51.7% |
| vs **LFU** | **+-2.4%** | +-1.50% | **-4.1%** | 0.0% | 3.5% | 22.5% | **-4.4%** | 23.0% |
| vs **GDS** | **+39.3%** | +17.47% | **31.5%** | 90.7% | 0.0% | 14.8% | **31.2%** | 15.2% |
