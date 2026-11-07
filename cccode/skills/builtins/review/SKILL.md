---
name: review
description: Code review with severity-graded findings
mode: fork
context: none
allowedTools:
  - Bash
  - ReadFile
  - Grep
  - Glob
---

# Code Review Skill

Perform a thorough code review. Analyze the following five dimensions:

1. **Logic**: Correctness, edge cases, error handling
2. **Security**: Input validation, injection risks, secret leakage
3. **Performance**: Algorithmic complexity, unnecessary work, memory leaks
4. **Style**: Naming, formatting, consistency with codebase conventions
5. **Maintainability**: Coupling, cohesion, documentation, testability

For each finding, assign a severity level:
- **Critical**: Must fix before merge (security holes, data loss, crashes)
- **Warning**: Should fix soon (performance regressions, fragile code)
- **Info**: Nice to have (style nits, minor improvements)

Output format:
```
## Review Summary
- Files reviewed: <count>
- Critical: <n> | Warning: <n> | Info: <n>

### Critical
- [C1] <file>:<line> — <description>

### Warning
- [W1] <file>:<line> — <description>

### Info
- [I1] <file>:<line> — <description>
```

If the user provided $ARGUMENTS, focus the review on those specific concerns.