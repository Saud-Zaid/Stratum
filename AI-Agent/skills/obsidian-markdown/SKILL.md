---
name: obsidian-markdown
description: "Create and edit Obsidian Flavored Markdown with wikilinks [[...]], embeds ![[...]], callouts > [!...], and block references ^id. Trigger immediately on: formatting notes, adding callouts, creating block references, embedding media, cross-linking notes with wikilinks. DO NOT trigger for: CLI operations (use obsidian-cli) or database views (use obsidian-bases)."
tags:
  - ai-agent
  - skill
  - kepano
created: 2026-09-18
args:
  input: note content / template / frontmatter to write or edit
  output: valid Obsidian Flavored Markdown file (wikilinks, embeds, callouts, block refs)
  consumer: vault-writer, owner-triggered, any note creation cycle
---

# Obsidian Flavored Markdown Skill

## Overview

This skill teaches agents how to create and edit valid Obsidian Flavored Markdown. Obsidian extends standard CommonMark and GitHub Flavored Markdown (GFM) with wikilinks, embeds, callouts, properties (frontmatter), block references, and comments.

## Note Creation Workflow

1. **Frontmatter Properties:** Always include valid YAML properties (`created`, `tags`, etc.) at the top of the file conforming to `AI-Agent/schema/frontmatter.yaml`.
2. **Body Structure:** Structure content using hierarchical headings (H1 for title, H2 for main sections, H3 for leaf topics). Maintain global heading uniqueness (Rule R1-dup).
3. **Internal Links (Wikilinks):** Use `[[Note]]` for internal vault cross-references and standard Markdown `[label](https://example.com)` for external URLs only.
4. **Embeds:** Embed images, audio, PDFs, or other notes using `![[target]]`.
5. **Callouts:** Highlight key notes, warnings, and tips using `> [!type]` callouts.
6. **Validation:** Ensure closing brackets match and no unbalanced syntax exists before saving.

## Wikilink Syntax Reference

```markdown
[[Note Name]]                          Link to note
[[Note Name|Display Text]]             Custom alias display text
[[Note Name#Heading]]                  Link to specific heading
[[Note Name#^block-id]]                Link to specific block
[[#Heading in same note]]              Internal same-note heading link
```

### Block References
Define an identifier by appending `^block-id` to the target paragraph:
```markdown
This paragraph is uniquely addressable. ^unique-block-01
```

For quotes and lists, place the block ID on a separate line following the block:
```markdown
> Quoted source material

^quote-reference-01
```

## Callouts Syntax

Obsidian provides built-in visual callouts:
```markdown
> [!NOTE]
> Explanatory background or general context.

> [!TIP]
> Optimization suggestions and best practices.

> [!IMPORTANT]
> Critical operational requirements or invariants.

> [!WARNING]
> Warnings regarding potential regressions or side effects.

> [!CAUTION]
> High-risk operations that could mutate state unexpectedly.
```

Foldable callouts can be created with `+` (open by default) or `-` (collapsed by default):
```markdown
> [!FAQ]- Collapsed Question
> Detailed answer hidden until clicked.
```

## Obsidian Comments

Hide comments from reading view while preserving line layout:
```markdown
%% This comment is completely hidden in reading view %%
```
