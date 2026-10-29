"""Per-process LLM usage and configurable cost accounting."""
import json
import os
from collections import defaultdict


class LLMUsageTracker:
    def __init__(self):
        self._by_model = defaultdict(lambda: {"requests": 0, "input_tokens": 0,
                                               "cached_input_tokens": 0, "output_tokens": 0,
                                               "total_tokens": 0, "cost_cny": 0.0,
                                               "cost_usd": 0.0,
                                               "pricing_complete": True})
        try:
            self._pricing = json.loads(os.getenv("LLM_MODEL_PRICING_JSON", "{}"))
        except json.JSONDecodeError:
            self._pricing = {}
        # Known gateway price, in CNY per million tokens. Environment entries
        # take precedence so a later pricing change needs no code update.
        self._pricing.setdefault("gpt-5.6-luna", {
            "input_per_million_cny": 1.26,
            "output_per_million_cny": 7.56,
        })
        self._pricing.setdefault("gpt-5-nano", {
            "input_per_million_cny": 0.32,
            "output_per_million_cny": 2.52,
        })
        # OpenRouter list price, in USD per million tokens.
        self._pricing.setdefault("qwen/qwen3-coder-30b-a3b-instruct", {
            "input_per_million_usd": 0.07,
            "output_per_million_usd": 0.28,
        })

    @staticmethod
    def _qwen_flash_rates(input_tokens):
        if input_tokens <= 32_000:
            return 0.2, 0.8, 0.04
        if input_tokens <= 256_000:
            return 0.6, 2.4, 0.12
        if input_tokens <= 1_000_000:
            return 1.2, 4.8, 0.24
        return None

    def _request_cost(self, model, input_tokens, output_tokens, cached_tokens):
        if model == "qwen3.7-flash":
            rates = self._qwen_flash_rates(input_tokens)
            if rates is None:
                return None
            input_rate, output_rate, cached_rate = rates
            uncached = max(0, input_tokens - cached_tokens)
            return {"cny": (uncached * input_rate + cached_tokens * cached_rate
                            + output_tokens * output_rate) / 1_000_000}
        price = self._pricing.get(model)
        if not isinstance(price, dict):
            return None
        costs = {}
        for currency in ("cny", "usd"):
            input_rate = price.get(f"input_per_million_{currency}")
            output_rate = price.get(f"output_per_million_{currency}")
            if input_rate is not None and output_rate is not None:
                costs[currency] = (input_tokens * float(input_rate)
                                   + output_tokens * float(output_rate)) / 1_000_000
        return costs or None

    def reset(self):
        self._by_model.clear()

    def record(self, model, response):
        usage = getattr(response, "usage", None)
        row = self._by_model[str(model)]
        row["requests"] += 1
        if usage is None:
            return
        prompt = getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0))
        completion = getattr(usage, "completion_tokens", getattr(usage, "output_tokens", 0))
        total = getattr(usage, "total_tokens", None)
        prompt, completion = int(prompt or 0), int(completion or 0)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details is not None else 0
        row["input_tokens"] += prompt
        row["cached_input_tokens"] += int(cached or 0)
        row["output_tokens"] += completion
        row["total_tokens"] += int(total if total is not None else (prompt or 0) + (completion or 0))
        costs = self._request_cost(str(model), prompt, completion, int(cached or 0))
        if costs is None:
            row["pricing_complete"] = False
        else:
            for currency, cost in costs.items():
                row[f"cost_{currency}"] += cost

    def summary(self):
        models, total_cny, total_usd, cost_complete = {}, 0.0, 0.0, True
        for model, values in sorted(self._by_model.items()):
            row = dict(values)
            row["estimated_cost_cny"] = round(row.pop("cost_cny"), 8)
            row["estimated_cost_usd"] = round(row.pop("cost_usd"), 8)
            model_complete = row.pop("pricing_complete")
            row["cost_pricing_complete"] = model_complete
            cost_complete = cost_complete and model_complete
            total_cny += row["estimated_cost_cny"]
            total_usd += row["estimated_cost_usd"]
            models[model] = row
        return {"models": models,
                "estimated_cost_cny": round(total_cny, 8),
                "estimated_cost_usd": round(total_usd, 8),
                "cost_pricing_complete": cost_complete}


usage_tracker = LLMUsageTracker()
