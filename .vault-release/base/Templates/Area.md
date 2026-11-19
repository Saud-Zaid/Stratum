---
status: active
tags: []
created: <% tp.date.now("YYYY-MM-DD") %>
type: area
---

# <% tp.file.title %>

## Standard
<!-- What does it mean for this area to be "healthy" right now? -->

## Related projects
```dataview
LIST FROM "01-Projects"
WHERE area = link(this.file.link)
```

## Related resources
```dataview
LIST FROM "03-Resources"
WHERE area = link(this.file.link)
```

<!-- An Area carries no `area` field of its own (unlike a Project or a Resource), by explicit decision: every initiative of one party is represented as a single Area, not as branches (see the guide). If you need periodic tracking (weekly tasks/achievements) inside this area, use Templates/Weekly-Tracker.md as a separate pattern linked by `area` to this file, not an extra section here. -->
<!-- If rules or mechanisms specific to this area pile up (classifications, promotion criteria, recurring design decisions), create a separate sub-guide named guide-<area-name>.md and a separate changelog named changelog-<area-name>.md (from Templates/Changelog.md) — both are created only when there is a real behavioural need, not automatically for every Area. See the full guide for the rule and a worked example. -->
