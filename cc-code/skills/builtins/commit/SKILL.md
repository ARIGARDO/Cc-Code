---
name: commit
description: Generate conventional commit message from staged changes
mode: inline
allowedTools:
  - Bash
  - ReadFile
  - Grep
---

# Commit Skill

You are generating a conventional commit message. Follow these steps:

1. Run `git status` to see what files changed
2. Run `git diff --cached` to see staged changes; if nothing staged, run `git diff` to see unstaged changes and `git add` the relevant files first
3. Analyze the diff and generate a **conventional commit** message:
   - Format: `<type>(<scope>): <description>`
   - Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert
   - Scope is optional but recommended for monorepos
   - Description: imperative mood, lowercase, no trailing period, ≤72 chars
4. Run `git commit -m "<message>"` with the generated message
5. If the user provided $ARGUMENTS, incorporate their intent into the commit message