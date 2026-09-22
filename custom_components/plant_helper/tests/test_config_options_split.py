"""Regression coverage for separated configuration and options flows."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_flow_classes_are_separated() -> None:
    config_source = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    options_source = (ROOT / "options.py").read_text(encoding="utf-8")
    config_classes = {n.name for n in ast.parse(config_source).body if isinstance(n, ast.ClassDef)}
    options_classes = {n.name for n in ast.parse(options_source).body if isinstance(n, ast.ClassDef)}
    assert "PlantHelperConfigFlow" in config_classes
    assert "PlantHelperOptionsFlow" not in config_classes
    assert "PlantHelperOptionsFlow" in options_classes

def test_options_factory_lazy_imports_handler() -> None:
    source = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    assert "from .options import PlantHelperOptionsFlow" in source
    assert "return PlantHelperOptionsFlow()" in source

def test_options_flow_keeps_lifecycle_steps() -> None:
    source = (ROOT / "options.py").read_text(encoding="utf-8")
    for step in ("async_step_init", "async_step_add_plant", "async_step_edit_plant", "async_step_remove_plant", "async_step_global_settings"):
        assert f"def {step}" in source
