---
name: json-canvas
description: "Create and edit JSON Canvas files (.canvas) with nodes, edges, groups, and connections. Trigger immediately on: working with .canvas files, creating mind maps, visual architectures, interactive flowcharts. DO NOT trigger for: standard markdown text notes (use obsidian-markdown)."
tags:
  - ai-agent
  - skill
  - kepano
created: 2026-09-18
args:
  input: .canvas file path + node/edge/group specs
  output: valid JSON Canvas Spec 1.0 file
  consumer: owner-triggered, architecture diagrams, mind maps
---

# JSON Canvas Skill

## Overview

This skill teaches agents how to read, create, and modify Obsidian Canvas files (`.canvas`). A canvas is a visual workspace following the open [JSON Canvas Spec 1.0](https://jsoncanvas.org/spec/1.0/).

## File Structure

A `.canvas` file is a valid JSON document containing two top-level arrays:

```json
{
  "nodes": [],
  "edges": []
}
```

## Node Specification

Nodes are visual objects on the canvas. Array ordering determines z-index (first node = bottom layer; last node = top layer).

### Common Node Attributes

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | string (16-char hex) | Unique identifier (e.g., `"4f8a1c92e73b015d"`) |
| `type` | string | `text`, `file`, `link`, or `group` |
| `x` | integer | Horizontal pixel coordinate |
| `y` | integer | Vertical pixel coordinate |
| `width` | integer | Width in pixels |
| `height` | integer | Height in pixels |
| `color` | string (optional) | Preset (`"1"` to `"6"`) or hex code (`"#ff0000"`) |

### Node Types

1. **Text Node:**
   ```json
   {
     "id": "1111222233334444",
     "type": "text",
     "text": "## Architecture Milestone\n- Key objective here",
     "x": 0,
     "y": 0,
     "width": 300,
     "height": 200
   }
   ```
2. **File Node (Links to Vault Note):**
   ```json
   {
     "id": "2222333344445555",
     "type": "file",
     "file": "01-Projects/Goal.md",
     "x": 350,
     "y": 0,
     "width": 400,
     "height": 300
   }
   ```
3. **Group Node (Container):**
   ```json
   {
     "id": "3333444455556666",
     "type": "group",
     "label": "Core Infrastructure",
     "x": -20,
     "y": -20,
     "width": 800,
     "height": 400
   }
   ```

## Edge Specification

Edges define directed or undirected connections between nodes:

```json
{
  "id": "edge112233445566",
  "fromNode": "1111222233334444",
  "fromSide": "right",
  "toNode": "2222333344445555",
  "toSide": "left",
  "label": "implements"
}
```

Anchor sides: `"top"`, `"right"`, `"bottom"`, `"left"`.
