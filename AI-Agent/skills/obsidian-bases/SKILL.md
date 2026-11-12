---
name: obsidian-bases
description: "Create and edit Obsidian Bases (.base files) with views, filters, formulas, and summaries. Trigger immediately on: working with .base files, creating dynamic database tables, card views, note formula calculations. DO NOT trigger for: standard markdown tables (use obsidian-markdown)."
tags:
  - ai-agent
  - skill
  - kepano
created: 2026-09-18
args:
  input: .base file path + filters/formulas/views requirements
  output: valid YAML .base file with computed properties and views
  consumer: owner-triggered, dashboards
---

# Obsidian Bases Skill

## Overview

This skill teaches agents how to create and manage structured database views using Obsidian Bases (`.base` files). Bases provide interactive tables, cards, and lists derived from note metadata without storing monolithic static tables inside prose notes.

## Workflow

1. **File Creation:** Create a `.base` file in the vault with valid YAML.
2. **Define Scope (Filters):** Specify global or view-specific filters matching target properties or tags.
3. **Computed Formulas:** Add computed properties in the `formulas` block.
4. **Configure Views:** Add one or more views (`table`, `cards`, `list`) specifying `order` of properties to display.
5. **Validation:** Ensure valid YAML syntax, correct property naming, and valid formula references.

## Schema Structure

A `.base` file contains valid YAML:

```yaml
# Global filters applied across all views
filters:
  and:
    - 'status == "active"'
    - not:
        - 'file.hasTag("archive")'

# Computed formulas
formulas:
  days_remaining: 'round((due - date("today")) / 86400000)'

# Property display labels
properties:
  status:
    displayName: "Status"
  formula.days_remaining:
    displayName: "Days Left"

# View definitions
views:
  - type: table
    name: "Active Tasks Table"
    limit: 20
    groupBy:
      property: area
      direction: ASC
    order:
      - file.name
      - status
      - due
      - formula.days_remaining
    summaries:
      due: Earliest
```

## Filter Expressions

```yaml
# Simple equality
filters: 'status == "done"'

# Logical AND
filters:
  and:
    - 'status == "active"'
    - 'priority > 2'

# Logical OR
filters:
  or:
    - 'file.hasTag("project")'
    - 'file.hasTag("area")'

# Exclusion (NOT)
filters:
  not:
    - 'file.hasTag("template")'
```
