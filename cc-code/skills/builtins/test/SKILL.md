---
name: test
description: Run project tests with auto-detected test framework
mode: inline
allowedTools:
  - Bash
  - ReadFile
  - Grep
  - Glob
---

# Test Skill

Auto-detect the project's test framework and run tests.

1. Detect project type by checking for config files:
   - `pyproject.toml` or `setup.cfg` → Python (pytest)
   - `go.mod` → Go (`go test ./...`)
   - `package.json` → Node.js (check scripts.test, default `npm test`)
   - `Cargo.toml` → Rust (`cargo test`)
   - `Makefile` with test target → `make test`

2. Run the appropriate test command

3. Analyze the output:
   - If all tests pass, report success with count
   - If tests fail, distinguish between:
     - **Code bug**: The source code under test has a defect
     - **Test bug**: The test itself is wrong or outdated
   - Provide actionable suggestions for fixing failures

4. If the user provided $ARGUMENTS, use them to filter which tests to run
   (e.g., specific file, test name pattern, or test marker)