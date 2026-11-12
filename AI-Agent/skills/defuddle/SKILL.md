---
name: defuddle
description: "Extract clean, readable Markdown from web pages with Defuddle CLI to strip boilerplate and ads. Trigger immediately on: parsing web URLs, scraping technical articles, ingesting external web content. DO NOT trigger for: local vault file navigation (use vault-navigation)."
tags:
  - ai-agent
  - skill
  - kepano
created: 2026-09-18
args:
  input: web URL (or list of URLs) to parse
  output: clean readable Markdown (piped to 00-Inbox/ scratch or a note)
  consumer: deep-research, vault ingestion, owner-triggered
---

# Defuddle Skill

## Overview

Use Defuddle to extract clean, readable content from web pages and articles. Defuddle removes navigation menus, cookie banners, tracking scripts, and advertisements, returning purified Markdown that dramatically minimizes token consumption when importing web references into the vault.

## Usage

When ingesting external URLs or research articles, invoke Defuddle with markdown formatting:

```bash
defuddle parse "<target_url>" --md
```

### Save Directly to Note
Pipe output to a scratch or inbox note:
```bash
defuddle parse "<target_url>" --md > "00-Inbox/web-article.md"
```

## Best Practices

1. **Quarantine Ingestion (IFC Protocol):** Always land external parsed web content inside `00-Inbox/` or scratch files first to review before moving to `03-Resources/`.
2. **Token Efficiency:** Prefer Defuddle over raw HTML fetches when digesting technical blogs, documentation, or news sources.
