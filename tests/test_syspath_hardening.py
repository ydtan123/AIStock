"""Test sys.path hardening: AIStock config must resolve correctly even after
FinRL's data_fetcher.py poisons sys.path."""

import os
import sys

import pytest


@pytest.fixture
def poisoned_sys_path():
    """Simulate what FinRL's data_fetcher.py does: insert its own paths at index 0."""
    finrl_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "external", "FinRL-Trading")
    )
    saved = list(sys.path)
    saved_modules = dict(sys.modules)
    # Remove config from sys.modules to simulate worst case (fresh import)
    sys.modules.pop("config", None)
    sys.path.insert(0, finrl_root)
    sys.path.insert(0, os.path.join(finrl_root, "src"))
    yield
    sys.path[:] = saved
    sys.modules.clear()
    sys.modules.update(saved_modules)


class TestSysPathHardening:
    """Verify config resolution after FinRL path poisoning."""

    def test_app_import_config_before_finrl(self, poisoned_sys_path):
        """app.py's explicit 'import config' before FinRL imports caches correctly."""
        # Simulate app.py: set AIStock path first
        aistock_src = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "src")
        )
        sys.path.insert(0, aistock_src)
        import config
        assert hasattr(config, "load_config"), (
            f"Wrong config module: {config.__file__}"
        )
        assert "AIStock" in config.__file__, (
            f"Not AIStock config: {config.__file__}"
        )

    def test_direct_yaml_bypasses_import(self, poisoned_sys_path):
        """UI pages load config.yaml directly — immune to sys.path poisoning."""
        import yaml
        config_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        )
        assert os.path.exists(config_path), f"config.yaml not found at {config_path}"
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        assert "database" in cfg, "config.yaml should have database section"

    def test_from_config_import_fails_after_poisoning(self, poisoned_sys_path):
        """Without pre-caching, from config import load_config resolves to FinRL."""
        with pytest.raises(ImportError):
            from config import load_config  # noqa: F401
