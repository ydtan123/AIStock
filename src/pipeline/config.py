"""ConfigLoader: YAML + dotted-path overrides + legacy back-compat."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads config.yaml, applies CLI overrides, maps legacy keys."""

    LEGACY_MAP = {
        # legacy_top_level_key -> (new_step_namespace, new_subkey_or_none, backend_name_or_none)
        "finrl_pipeline": ("stock_selection", "finrl", "finrl"),
        "ai_hedge_fund": ("fast_evaluation", "ai_hedge_fund", "ai_hedge_fund"),
    }

    def __init__(self, path: str | Path, overrides: list[str] | None = None):
        self.path = Path(path)
        self.overrides = overrides or []
        self._cfg: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        with self.path.open() as f:
            cfg = yaml.safe_load(f) or {}
        cfg = self._apply_backcompat(cfg)
        for override in self.overrides:
            self._apply_override(cfg, override)
        self._cfg = cfg
        return cfg

    def write_effective(self, out_path: str | Path) -> None:
        if self._cfg is None:
            raise RuntimeError("call load() before write_effective()")
        Path(out_path).write_text(yaml.safe_dump(self._cfg, sort_keys=False))

    def _apply_backcompat(self, cfg: dict[str, Any]) -> dict[str, Any]:
        # source + alpha_vantage at top level -> data_update
        if "source" in cfg or "alpha_vantage" in cfg:
            du = cfg.setdefault("data_update", {})
            if "source" in cfg and "source" not in du:
                du["source"] = cfg["source"]
                logger.warning(
                    "config.yaml: top-level 'source' is deprecated; "
                    "use 'data_update.source' instead"
                )
            if "alpha_vantage" in cfg and "alpha_vantage" not in du:
                du["alpha_vantage"] = cfg["alpha_vantage"]
                logger.warning(
                    "config.yaml: top-level 'alpha_vantage' is deprecated; "
                    "use 'data_update.alpha_vantage' instead"
                )

        # finrl_pipeline / ai_hedge_fund -> stock_selection / fast_evaluation
        for legacy_key, (new_ns, sub_key, backend) in self.LEGACY_MAP.items():
            if legacy_key not in cfg:
                continue
            new_ns_dict = cfg.setdefault(new_ns, {})
            # Only set backend if not already specified
            new_ns_dict.setdefault("backend", backend)
            existing_sub = new_ns_dict.get(sub_key, {})
            # New keys take precedence; legacy fills gaps only.
            merged = dict(cfg[legacy_key])
            merged.update(existing_sub)
            new_ns_dict[sub_key] = merged
            logger.warning(
                "config.yaml: top-level '%s' is deprecated; "
                "use '%s.%s' instead",
                legacy_key,
                new_ns,
                sub_key,
            )

        return cfg

    @staticmethod
    def _apply_override(cfg: dict[str, Any], override: str) -> None:
        if "=" not in override:
            raise ValueError(
                f"override must be KEY=VALUE, got: {override!r}"
            )
        key_path, raw_value = override.split("=", 1)
        keys = key_path.split(".")
        try:
            value = yaml.safe_load(raw_value)
        except yaml.YAMLError:
            value = raw_value
        node = cfg
        for k in keys[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value
