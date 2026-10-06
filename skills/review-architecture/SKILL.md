---
name: review-architecture
description: Review a code snippet for architectural red flags, tight coupling, and poor separation of concerns. Use when the user explicitly invokes review-architecture for an architectural code review.
disable-model-invocation: true
---

# Review Architecture

Review this code snippet for architectural red flags, tight coupling, or poor separation of concerns. Suggest how to better structure this component within a scalable system.

## Review approach

1. Identify the component's responsibilities and dependencies.
2. Flag concrete architectural concerns, ranked by impact.
3. Explain the maintenance, testing, or scaling consequence of each concern.
4. Recommend the smallest practical boundary, interface, or dependency change.
5. Distinguish must-fix design risks from optional refinements.

## Response format

Use this structure:

```markdown
## Summary
[Overall architectural assessment.]

## Findings
- [Severity] [Specific concern, evidence from the snippet, and consequence.]

## Recommended structure
[Suggested component boundaries, interfaces, and dependency direction.]

## Example refactoring
[A concise example only when it clarifies the recommendation.]
```

Do not invent surrounding system requirements. State assumptions and ask for
the relevant context when the snippet alone cannot support a conclusion.
