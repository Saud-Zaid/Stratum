---
tags: []
created: 2026-09-06
---

# Dashboard

## Active projects
```dataview
TABLE area AS "Area"
FROM "01-Projects"
WHERE status = "active"
```

## Inbox (needs processing)
```dataview
LIST
FROM "00-Inbox"
```

## Latest permanent notes
```dataview
LIST
FROM "05-Zettelkasten/Permanent"
SORT created DESC
LIMIT 10
```

## Latest experiments
```dataview
LIST
FROM "05-Zettelkasten/Experiments"
SORT created DESC
LIMIT 10
```

## Content candidates awaiting processing
```dataview
LIST
FROM "05-Zettelkasten"
WHERE content_candidate = true
```
