#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""vault_diagram-tests.py — Comprehensive Unit & Integration Tests for vault_diagram.py."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import vault_diagram

R = []


def ok(name: str, condition: bool, details: str = "") -> None:
    R.append((name, condition, details))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name} {details}".strip())


def test_theme_matrix_structure():
    matrix = vault_diagram.load_theme_matrix()
    ok("T01-matrix-loaded", isinstance(matrix, dict) and "themes" in matrix, f"keys={list(matrix.keys())}")
    
    # Check default theme
    default_theme = matrix.get("default_theme")
    ok("T02-default-theme", default_theme == "catppuccin_macchiato", f"default={default_theme}")
    
    # Check all 5 required dark themes
    required_themes = [
        "catppuccin_macchiato",
        "tokyo_night",
        "dracula",
        "gruvbox_dark",
        "solarized_dark",
    ]
    themes = matrix.get("themes", {})
    all_exist = all(t in themes for t in required_themes)
    ok("T03-all-5-themes-present", all_exist, f"found={list(themes.keys())}")
    
    # Check all 6 semantic roles
    required_roles = ["governance", "execution", "knowledge", "decision", "alert", "neutral"]
    palette = vault_diagram.get_semantic_palette(matrix)
    roles_exist = all(r in palette for r in required_roles)
    ok("T04-all-6-roles-present", roles_exist, f"roles={list(palette.keys())}")


def test_theme_role_definitions():
    matrix = vault_diagram.load_theme_matrix()
    themes = matrix.get("themes", {})
    required_roles = ["governance", "execution", "knowledge", "decision", "alert", "neutral"]
    
    valid_all = True
    for tid, tdata in themes.items():
        roles = tdata.get("roles", {})
        for r in required_roles:
            if r not in roles or "bg" not in roles[r] or "border" not in roles[r]:
                valid_all = False
                break
    ok("T05-theme-roles-complete", valid_all, "All 5 themes configure 6 roles with bg/border")


def test_palette_svg_generation():
    for theme_id in ["catppuccin_macchiato", "tokyo_night", "dracula", "gruvbox_dark", "solarized_dark"]:
        svg_content = vault_diagram.generate_palette_svg(theme_id)
        # Parse XML to verify well-formed SVG
        try:
            root = ET.fromstring(svg_content)
            is_valid_svg = root.tag.endswith("svg")
        except ET.ParseError as e:
            is_valid_svg = False
        ok(f"T06-valid-palette-svg-{theme_id}", is_valid_svg, f"size={len(svg_content)}")


def test_architecture_svg_generation():
    svg_content = vault_diagram.get_demo_system_diagram("catppuccin_macchiato")
    try:
        root = ET.fromstring(svg_content)
        has_nodes = len(root.findall(".//{http://www.w3.org/2000/svg}g")) >= 6
    except ET.ParseError:
        has_nodes = False
    ok("T07-valid-architecture-svg", has_nodes, f"size={len(svg_content)}")


def test_mermaid_classdef_generation():
    styles = vault_diagram.generate_mermaid_theme_styles("catppuccin_macchiato")
    has_classes = all(f"classDef {r}" in styles for r in ["governance", "execution", "knowledge", "decision", "alert", "neutral"])
    ok("T08-mermaid-classdef", has_classes, "Mermaid classDef lines present for all 6 roles")
    
    wrapped = vault_diagram.wrap_mermaid("graph TD\nA-->B", "tokyo_night")
    ok("T09-mermaid-wrap", "graph TD" in wrapped and "classDef governance" in wrapped, "Wrapped mermaid includes code and styles")


def test_cli_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = Path(tmpdir) / "demo.svg"
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "vault_diagram.py"),
            "--theme", "tokyo_night",
            "--mode", "demo",
            "--output", str(out_file),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        ok("T10-cli-exit-0", res.returncode == 0, f"code={res.returncode}")
        ok("T11-cli-output-created", out_file.exists() and out_file.stat().st_size > 500, f"size={out_file.stat().st_size if out_file.exists() else 0}")


def main():
    test_theme_matrix_structure()
    test_theme_role_definitions()
    test_palette_svg_generation()
    test_architecture_svg_generation()
    test_mermaid_classdef_generation()
    test_cli_execution()
    
    passed = sum(1 for _, c, _ in R if c)
    total = len(R)
    print(f"\nVAULT-DIAGRAM-TESTS: {passed}/{total} passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
