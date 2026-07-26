---
name: test-isolation-invariants
description: Tests must never write to real agent config files; use autouse conftest fixtures, ban import-time side effects pointing at Path.home().
metadata:
  type: feedback
---

The current Claude Code session uses the real `~/.claude/settings.json`. If a test accidentally
writes garbage to it (wrong base URL, empty API key, etc.), the session immediately breaks with
API errors and the user has to manually fix or restore from backup. This is a basic principle,
not a nice-to-have.

**Why this is a real risk in this codebase**: during V1 development, the auto-registration at module
import time (`registry.register(ClaudeCodeDriver())` at the bottom of `claude_code.py`) created a
driver pointed at the real config the moment any test imported `yzr_agent_tools`. Even though the
constructor didn't write anything, any later code that called `driver.apply()` could potentially
write. The window was small but real. The fix: remove all import-time side effects and enforce
isolation by autouse fixture.

**How to apply:**

- Make isolation an **autouse fixture** (in `tests/conftest.py`) so it applies to every test by
  default — do NOT rely on tests remembering to opt in.
- Remove import-time side effects that point at real paths (e.g. auto-registering a driver
  singleton with `Path.home() / ".claude" / "settings.json"` at module import). Defer driver
  creation to first use, or register a factory / lazy helper.
- Add an explicit assertion in conftest that the real `~/.claude/settings.json` mtime/sha256 has
  not changed during the test run (defense in depth).
- If a test genuinely needs to exercise the real path (e.g. test_paths.py testing XDG resolution),
  opt out with `@pytest.mark.no_isolation`.
- Same rule applies to ANY tool config that touches user state: shell rc files, ssh config,
  git config, agent-specific config dirs, etc.

The reference implementation is in `/root/yzr-agent-tools/tests/conftest.py`.
