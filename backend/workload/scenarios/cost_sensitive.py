"""Cost-sensitive workload scenario implementation.

Generates request streams where objects vary significantly in size and
backend retrieval cost, enabling evaluation of cost-aware and size-aware
caching policies (e.g. GDS and AEGIS value density) versus recency/frequency baselines.
"""

from __future__ import annotations

import random
from datetime import timedelta

from backend.workload.scenario import ScenarioConfig, ScenarioEvent
from backend.workload.scenarios.base import BaseScenario


class CostSensitiveScenario(BaseScenario):
    """Deterministic cost-sensitive workload scenario generator.

    Varies object payload sizes and backend retrieval latencies across multiple
    archetypes (small/large size x low/high retrieval cost) to evaluate how
    policies trade off memory footprint versus backend regeneration expense.
    """

    # Default archetypes: (size_bytes, retrieval_cost_ms)
    ARCHETYPES: tuple[dict[str, float], ...] = (
        {"size": 1024, "cost": 150.0},   # Tier 1: Small payload, high retrieval cost
        {"size": 1024, "cost": 10.0},    # Tier 2: Small payload, low retrieval cost
        {"size": 8192, "cost": 250.0},   # Tier 3: Medium payload, high retrieval cost
        {"size": 16384, "cost": 10.0},   # Tier 4: Large payload, low retrieval cost
    )

    def generate(
        self, config: ScenarioConfig, rng: random.Random
    ) -> list[ScenarioEvent]:
        """Generate a synthetic request sequence with varying object sizes and costs.

        Args:
            config: Scenario configuration parameters.
            rng: Seeded random.Random instance for determinism.

        Returns:
            List of generated ScenarioEvents with diverse sizes and retrieval costs.
        """
        keys = [f"{config.key_prefix}_{i}" for i in range(config.object_count)]
        catalog = self._build_catalog(config)
        weights = self._calculate_weights(config)

        chosen_keys = rng.choices(keys, weights=weights, k=config.request_count)

        interval_seconds = (
            1.0 / config.request_rate if config.request_rate > 0.0 else 1.0
        )
        current_time = config.start_time
        events: list[ScenarioEvent] = []
        profile = config.profile

        for key in chosen_keys:
            size_bytes, cost_ms = catalog[key]
            events.append(
                ScenarioEvent(
                    timestamp=current_time,
                    key=key,
                    workload_type=profile.workload_type,
                    backend_latency_ms=cost_ms,
                    object_size_bytes=size_bytes,
                    retrieval_cost_ms=cost_ms,
                    request_rate=config.request_rate,
                    metadata={
                        "phase": "cost_sensitive",
                        "scenario": "cost_sensitive",
                    },
                )
            )
            current_time += timedelta(seconds=interval_seconds)

        return events

    def _build_catalog(
        self, config: ScenarioConfig
    ) -> dict[str, tuple[int, float]]:
        """Deterministically assign size and retrieval cost to each object key."""
        cat_rng = random.Random(config.seed + 1000)
        n = config.object_count
        catalog: dict[str, tuple[int, float]] = {}

        for i in range(n):
            key = f"{config.key_prefix}_{i}"
            archetype = self.ARCHETYPES[i % len(self.ARCHETYPES)]
            # Deterministic variation around archetype (+/- 10%)
            jitter = 0.90 + 0.20 * cat_rng.random()
            size = max(512, int(archetype["size"] * jitter))
            cost = max(1.0, round(archetype["cost"] * jitter, 2))
            catalog[key] = (size, cost)

        return catalog

    @staticmethod
    def _calculate_weights(config: ScenarioConfig) -> list[float]:
        """Compute relative selection weights for objects (80/20 or Zipfian)."""
        n = config.object_count
        k = config.hot_set_size
        extra = config.extra_params or {}

        if extra.get("distribution") == "zipf":
            s = float(extra.get("zipf_exponent", 1.0))
            return [1.0 / ((i + 1) ** s) for i in range(n)]

        if k >= n:
            return [1.0 / n] * n

        hot_ratio = float(extra.get("hot_ratio", 0.80))
        cold_ratio = 1.0 - hot_ratio

        hot_weight = hot_ratio / k
        cold_weight = cold_ratio / (n - k)

        return [hot_weight if i < k else cold_weight for i in range(n)]
