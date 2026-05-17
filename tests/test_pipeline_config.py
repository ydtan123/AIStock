"""ConfigLoader tests: YAML load, dotted-path overrides, type parsing."""
import textwrap

import pytest

from pipeline.config import ConfigLoader


def write_config(tmp_path, content):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_load_plain_yaml(tmp_path):
    cfg_path = write_config(tmp_path, """
        database:
          url: "mysql://x"
        data_update:
          source: alpha_vantage
    """)
    loader = ConfigLoader(cfg_path)
    cfg = loader.load()
    assert cfg["database"]["url"] == "mysql://x"
    assert cfg["data_update"]["source"] == "alpha_vantage"


def test_dotted_path_override_simple(tmp_path):
    cfg_path = write_config(tmp_path, """
        fast_evaluation:
          top_n: 10
    """)
    loader = ConfigLoader(cfg_path, overrides=["fast_evaluation.top_n=5"])
    cfg = loader.load()
    assert cfg["fast_evaluation"]["top_n"] == 5


def test_dotted_path_override_creates_missing_parents(tmp_path):
    cfg_path = write_config(tmp_path, "database: {url: 'm'}")
    loader = ConfigLoader(cfg_path, overrides=["deep_evaluation.trading_agents.quick=true"])
    cfg = loader.load()
    assert cfg["deep_evaluation"]["trading_agents"]["quick"] is True


def test_dotted_path_override_yaml_value_parsing(tmp_path):
    cfg_path = write_config(tmp_path, "x: {}")
    loader = ConfigLoader(
        cfg_path,
        overrides=[
            "x.an_int=42",
            "x.a_bool=false",
            "x.a_list=[a,b,c]",
            "x.a_str=hello",
        ],
    )
    cfg = loader.load()
    assert cfg["x"]["an_int"] == 42
    assert cfg["x"]["a_bool"] is False
    assert cfg["x"]["a_list"] == ["a", "b", "c"]
    assert cfg["x"]["a_str"] == "hello"


def test_invalid_override_format_raises(tmp_path):
    cfg_path = write_config(tmp_path, "{}")
    with pytest.raises(ValueError, match="must be KEY=VALUE"):
        ConfigLoader(cfg_path, overrides=["no_equals_sign"]).load()


def test_write_effective_config(tmp_path):
    cfg_path = write_config(tmp_path, "x: 1")
    out_path = tmp_path / "effective.yaml"
    loader = ConfigLoader(cfg_path, overrides=["x=2"])
    cfg = loader.load()
    loader.write_effective(out_path)
    assert out_path.exists()
    content = out_path.read_text()
    assert "x: 2" in content
