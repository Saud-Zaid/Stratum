#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""vault_diagram.py — Lightweight, Zero-Dependency Architecture Diagram & SVG Generator.

AD13 M03 Component:
- Standard library only (M32 compliance: no Node, no Go binaries, no heavy Python packages).
- Reads semantic palette and 5 global dark contrast themes from AI-Agent/schema/themes.json.
- Renders crisp, self-contained SVG diagrams with dark theme contrast.
- Generates themed Mermaid diagrams with classDef styling for native browser/Dagre rendering.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

THEMES_PATH = Path(__file__).resolve().parent.parent / "schema" / "themes.json"


def load_theme_matrix(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the themes matrix configuration from JSON."""
    p = path or THEMES_PATH
    if not p.exists():
        raise FileNotFoundError(f"Themes configuration not found at: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def get_theme(theme_id: Optional[str] = None, matrix: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Retrieve theme by ID or return the default theme."""
    data = matrix or load_theme_matrix()
    themes = data.get("themes", {})
    default_id = data.get("default_theme", "catppuccin_macchiato")
    target_id = theme_id or default_id
    if target_id not in themes:
        available = ", ".join(themes.keys())
        raise KeyError(f"Unknown theme '{target_id}'. Available themes: {available}")
    return themes[target_id]


def get_semantic_palette(matrix: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Retrieve the core semantic palette definitions."""
    data = matrix or load_theme_matrix()
    return data.get("semantic_palette", {})


def generate_mermaid_theme_styles(theme_id: Optional[str] = None) -> str:
    """Generate Mermaid classDef CSS statements matching the selected theme."""
    matrix = load_theme_matrix()
    theme = get_theme(theme_id, matrix)
    roles = theme.get("roles", {})
    
    lines = [
        f"%% Mermaid Theme Classes: {theme.get('name', theme_id)} %%",
    ]
    for role_name, style in roles.items():
        bg = style.get("bg", "#1e2030")
        stroke = style.get("border", "#cad3f5")
        color = style.get("text", "#cad3f5")
        lines.append(f"classDef {role_name} fill:{bg},stroke:{stroke},stroke-width:2px,color:{color};")
    
    return "\n".join(lines)


def wrap_mermaid(mermaid_code: str, theme_id: Optional[str] = None) -> str:
    """Append themed classDef definitions to raw mermaid code."""
    styles = generate_mermaid_theme_styles(theme_id)
    return f"{mermaid_code.strip()}\n\n{styles}\n"


def generate_palette_svg(theme_id: Optional[str] = None) -> str:
    """Generate an SVG showcase of the semantic palette and active theme."""
    matrix = load_theme_matrix()
    theme = get_theme(theme_id, matrix)
    semantic = get_semantic_palette(matrix)
    
    width = 960
    height = 540
    canvas_bg = theme.get("canvas_bg", "#24273a")
    card_bg = theme.get("card_bg", "#1e2030")
    text_primary = theme.get("text_primary", "#cad3f5")
    text_muted = theme.get("text_muted", "#a5adcb")
    border_color = theme.get("border", "#5b6078")
    accent = theme.get("accent", "#c6a0f6")
    theme_name = theme.get("name", theme_id or "Default")
    
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" style="background-color: {canvas_bg}; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif;">',
        f'  <defs>',
        f'    <filter id="shadow" x="-5%" y="-5%" width="110%" height="110%">',
        f'      <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000000" flood-opacity="0.35"/>',
        f'    </filter>',
        f'  </defs>',
        f'  <!-- Header Banner -->',
        f'  <rect x="30" y="24" width="{width - 60}" height="70" rx="10" fill="{card_bg}" stroke="{border_color}" stroke-width="1.5" filter="url(#shadow)"/>',
        f'  <text x="50" y="58" fill="{accent}" font-size="22" font-weight="bold">AD13 Visual Identity — Semantic Palette &amp; Contrast Matrix</text>',
        f'  <text x="50" y="78" fill="{text_muted}" font-size="13">Active Theme: <tspan fill="{text_primary}" font-weight="600">{html.escape(theme_name)}</tspan> · Zero-Dependency Headless Engine</text>',
    ]
    
    # 6 Semantic Cards in a 3x2 grid
    roles = list(semantic.keys())
    theme_roles = theme.get("roles", {})
    card_w = 275
    card_h = 175
    spacing_x = 25
    spacing_y = 25
    start_x = 35
    start_y = 120
    
    for idx, role_key in enumerate(roles):
        row = idx // 3
        col = idx % 3
        x = start_x + col * (card_w + spacing_x)
        y = start_y + row * (card_h + spacing_y)
        
        info = semantic[role_key]
        theme_style = theme_roles.get(role_key, {})
        box_bg = theme_style.get("bg", info.get("container_bg", "#1e2030"))
        box_border = theme_style.get("border", info.get("border", "#a78bfa"))
        box_text = theme_style.get("text", info.get("text", "#ffffff"))
        primary = info.get("primary", "#ffffff")
        name_ar = info.get("name_ar", "")
        name_en = info.get("name_en", role_key)
        desc = info.get("description", "")
        
        svg.append(f'  <!-- Card {idx + 1}: {role_key} -->')
        svg.append(f'  <g transform="translate({x}, {y})" filter="url(#shadow)">')
        svg.append(f'    <rect width="{card_w}" height="{card_h}" rx="8" fill="{box_bg}" stroke="{box_border}" stroke-width="2"/>')
        svg.append(f'    <!-- Primary Pill Indicator -->')
        svg.append(f'    <circle cx="24" cy="28" r="8" fill="{primary}" stroke="{box_border}" stroke-width="1.5"/>')
        svg.append(f'    <text x="40" y="33" fill="{primary}" font-size="14" font-weight="bold">{html.escape(name_en)}</text>')
        svg.append(f'    <text x="{card_w - 18}" y="33" text-anchor="end" fill="{box_text}" font-size="13" font-weight="500">{html.escape(name_ar)}</text>')
        svg.append(f'    <line x1="15" y1="50" x2="{card_w - 15}" y2="50" stroke="{box_border}" stroke-width="1" stroke-opacity="0.4"/>')
        svg.append(f'    <text x="18" y="75" fill="{text_muted}" font-size="11" font-weight="600">ROLE ID: <tspan fill="{text_primary}">{role_key}</tspan></text>')
        svg.append(f'    <text x="18" y="96" fill="{text_muted}" font-size="11" font-weight="600">PRIMARY: <tspan fill="{primary}">{primary}</tspan></text>')
        svg.append(f'    <text x="18" y="117" fill="{text_muted}" font-size="11" font-weight="600">BG / TEXT: <tspan fill="{box_text}">{box_bg}</tspan></text>')
        svg.append(f'    <!-- Description -->')
        svg.append(f'    <rect x="15" y="132" width="{card_w - 30}" height="30" rx="4" fill="{card_bg}" fill-opacity="0.6"/>')
        svg.append(f'    <text x="22" y="151" fill="{text_muted}" font-size="10.5">{html.escape(desc[:36])}</text>')
        svg.append(f'  </g>')
    
    # Footer
    svg.append(f'  <!-- Footer -->')
    svg.append(f'  <text x="{width // 2}" y="{height - 20}" text-anchor="middle" fill="{text_muted}" font-size="11.5">Vault Architecture Intelligence · Compliant with M32 Standard Library &amp; Dark High-Contrast Guidelines</text>')
    svg.append(f'</svg>')
    
    return "\n".join(svg)


def generate_architecture_svg(
    title: str,
    nodes: List[Dict[str, Any]],
    connections: Optional[List[Tuple[str, str, str]]] = None,
    theme_id: Optional[str] = None,
    width: int = 1000,
    height: int = 600,
) -> str:
    """Generate a clean, structured architecture SVG diagram with themed nodes and arrows."""
    matrix = load_theme_matrix()
    theme = get_theme(theme_id, matrix)
    theme_roles = theme.get("roles", {})
    
    canvas_bg = theme.get("canvas_bg", "#24273a")
    card_bg = theme.get("card_bg", "#1e2030")
    text_primary = theme.get("text_primary", "#cad3f5")
    text_muted = theme.get("text_muted", "#a5adcb")
    border_color = theme.get("border", "#5b6078")
    accent = theme.get("accent", "#c6a0f6")
    
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" style="background-color: {canvas_bg}; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif;">',
        f'  <defs>',
        f'    <filter id="nodeShadow" x="-10%" y="-10%" width="120%" height="120%">',
        f'      <feDropShadow dx="0" dy="4" stdDeviation="5" flood-color="#000000" flood-opacity="0.4"/>',
        f'    </filter>',
        f'    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        f'      <path d="M 0 1 L 10 5 L 0 9 z" fill="{accent}"/>',
        f'    </marker>',
        f'  </defs>',
        f'  <!-- Header -->',
        f'  <rect x="25" y="20" width="{width - 50}" height="55" rx="8" fill="{card_bg}" stroke="{border_color}" stroke-width="1.5"/>',
        f'  <text x="45" y="48" fill="{accent}" font-size="18" font-weight="bold">{html.escape(title)}</text>',
        f'  <text x="{width - 45}" y="48" text-anchor="end" fill="{text_muted}" font-size="12">Theme: {theme.get("name", theme_id)}</text>',
    ]
    
    node_coords: Dict[str, Tuple[float, float, float, float]] = {}
    
    # Draw Nodes
    for n in nodes:
        nid = n["id"]
        role = n.get("role", "neutral")
        label = n.get("label", nid)
        subtext = n.get("subtext", "")
        x = float(n.get("x", 50))
        y = float(n.get("y", 100))
        w = float(n.get("w", 180))
        h = float(n.get("h", 80))
        
        node_coords[nid] = (x, y, w, h)
        style = theme_roles.get(role, theme_roles.get("neutral", {}))
        bg = style.get("bg", "#1e2030")
        border = style.get("border", border_color)
        fg = style.get("text", text_primary)
        
        svg.append(f'  <!-- Node: {nid} -->')
        svg.append(f'  <g id="node-{nid}" filter="url(#nodeShadow)">')
        svg.append(f'    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{bg}" stroke="{border}" stroke-width="2"/>')
        svg.append(f'    <text x="{x + w / 2}" y="{y + (28 if subtext else h / 2 + 5)}" text-anchor="middle" fill="{fg}" font-size="13.5" font-weight="bold">{html.escape(label)}</text>')
        if subtext:
            svg.append(f'    <text x="{x + w / 2}" y="{y + 52}" text-anchor="middle" fill="{text_muted}" font-size="11">{html.escape(subtext)}</text>')
        svg.append(f'  </g>')
    
    # Draw Connections
    if connections:
        for src_id, dst_id, conn_label in connections:
            if src_id in node_coords and dst_id in node_coords:
                sx, sy, sw, sh = node_coords[src_id]
                dx, dy, dw, dh = node_coords[dst_id]
                
                # Simple orthogonal or direct center routing
                x1 = sx + sw / 2
                y1 = sy + sh / 2
                x2 = dx + dw / 2
                y2 = dy + dh / 2
                
                # Adjust end point to border
                if y2 > y1:  # going down
                    y1_adj = sy + sh
                    y2_adj = dy
                    x1_adj = x1
                    x2_adj = x2
                elif y2 < y1:  # going up
                    y1_adj = sy
                    y2_adj = dy + dh
                    x1_adj = x1
                    x2_adj = x2
                elif x2 > x1:  # going right
                    x1_adj = sx + sw
                    x2_adj = dx
                    y1_adj = y1
                    y2_adj = y2
                else:  # going left
                    x1_adj = sx
                    x2_adj = dx + dw
                    y1_adj = y1
                    y2_adj = y2
                
                svg.append(f'  <!-- Edge: {src_id} -> {dst_id} -->')
                svg.append(f'  <line x1="{x1_adj}" y1="{y1_adj}" x2="{x2_adj}" y2="{y2_adj}" stroke="{accent}" stroke-width="2" marker-end="url(#arrow)"/>')
                if conn_label:
                    mid_x = (x1_adj + x2_adj) / 2
                    mid_y = (y1_adj + y2_adj) / 2 - 6
                    svg.append(f'  <text x="{mid_x}" y="{mid_y}" text-anchor="middle" fill="{text_muted}" font-size="10.5" font-weight="500">{html.escape(conn_label)}</text>')
    
    svg.append(f'</svg>')
    return "\n".join(svg)


def get_demo_system_diagram(theme_id: Optional[str] = None) -> str:
    """Generate a sample AD13 System Context SVG diagram demonstrating the semantic palette."""
    nodes = [
        {"id": "governance", "role": "governance", "label": "Governance Gate", "subtext": "audit.py (ratchet)", "x": 50, "y": 120, "w": 200, "h": 75},
        {"id": "agent", "role": "execution", "label": "Autonomous Agent", "subtext": "agent_loop.py", "x": 380, "y": 120, "w": 220, "h": 75},
        {"id": "storage", "role": "knowledge", "label": "Vault Storage", "subtext": "Markdown & SQLite", "x": 730, "y": 120, "w": 200, "h": 75},
        {"id": "decision", "role": "decision", "label": "Decision Fork", "subtext": "jev_client / Ledger", "x": 380, "y": 320, "w": 220, "h": 75},
        {"id": "alerts", "role": "alert", "label": "Circuit Breaker", "subtext": "Anti-Thrashing / Tax", "x": 50, "y": 320, "w": 200, "h": 75},
        {"id": "ui", "role": "neutral", "label": "the owner UI Cockpit", "subtext": "Headless CLI / Web", "x": 730, "y": 320, "w": 200, "h": 75},
    ]
    connections = [
        ("governance", "agent", "enforces contract"),
        ("agent", "storage", "reads / writes"),
        ("agent", "decision", "submits option"),
        ("decision", "alerts", "trips threshold"),
        ("agent", "ui", "renders telemetry"),
    ]
    return generate_architecture_svg(
        title="AD13 Architecture System Overview — Visual Identity",
        nodes=nodes,
        connections=connections,
        theme_id=theme_id,
        width=980,
        height=480,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="vault_diagram.py — Zero-dependency architecture diagram generator")
    parser.add_argument("--theme", choices=["catppuccin_macchiato", "tokyo_night", "dracula", "gruvbox_dark", "solarized_dark"], default="catppuccin_macchiato", help="Color theme")
    parser.add_argument("--mode", choices=["palette", "demo", "mermaid-styles"], default="palette", help="Generation mode")
    parser.add_argument("--output", "-o", type=str, help="Output file path (default prints to stdout)")
    
    args = parser.parse_args()
    
    if args.mode == "palette":
        content = generate_palette_svg(args.theme)
    elif args.mode == "demo":
        content = get_demo_system_diagram(args.theme)
    elif args.mode == "mermaid-styles":
        content = generate_mermaid_theme_styles(args.theme)
    else:
        content = ""
    
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        print(f"DIAGRAM generated: {out_path} ({len(content)} bytes)")
    else:
        sys.stdout.write(content)


if __name__ == "__main__":
    main()
