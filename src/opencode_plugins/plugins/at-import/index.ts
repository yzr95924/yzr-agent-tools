// at-import — expand standalone-line `@path` references inside AGENTS.md
// into system instructions (OpenCode V2 does not; Claude Code does).
// Design: docs/opencode-plugins-design.md.
//
// Hard constraints for anyone editing this file:
// - Do NOT import "@opencode/plugin": the V2 server injects no alias for it,
//   so the import fails to resolve ("Cannot find package"). The plain
//   `{ id, setup }` default export is accepted by the loader as-is.
// - The hook must never throw: every failure path degrades to "inject less".
// - Targets may only resolve inside the importing file's directory subtree
//   (absolute paths / `~` / traversal rejected) — a cloned repo must not be
//   able to steer this plugin into reading arbitrary files into context.

import { existsSync, mkdirSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, join, resolve, sep } from "node:path"

const MAX_DEPTH = 5
const MAX_FILE_BYTES = 64 * 1024
const MAX_TOTAL_BYTES = 256 * 1024

function heartbeatPath(): string {
  const base = process.env.XDG_DATA_HOME || join(homedir(), ".local", "share")
  return join(base, "opencode-plugins", "at-import-heartbeat.json")
}

function writeHeartbeat(record: Record<string, unknown>): void {
  try {
    const p = heartbeatPath()
    mkdirSync(dirname(p), { recursive: true })
    const tmp = p + ".tmp"
    writeFileSync(tmp, JSON.stringify(record) + "\n")
    renameSync(tmp, p)
  } catch {
    /* the heartbeat must never break the hook */
  }
}

function agentsFiles(ctx: any): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const push = (file: string): void => {
    if (!seen.has(file) && existsSync(file)) {
      seen.add(file)
      out.push(file)
    }
  }

  const xdg = process.env.XDG_CONFIG_HOME || join(homedir(), ".config")
  push(join(xdg, "opencode", "AGENTS.md"))

  const start = ctx.location.directory as string
  const home = homedir()
  const project = (ctx.location.project && ctx.location.project.directory) || start
  const underHome = start === home || start.startsWith(home + sep)
  const stop = underHome ? home : project

  let dir = resolve(start)
  for (;;) {
    push(join(dir, "AGENTS.md"))
    if (dir === resolve(stop)) break
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return out
}

function safeTarget(baseDir: string, token: string): string | null {
  if (token.startsWith("/") || token.startsWith("~") || token.startsWith("\\")) return null
  const p = resolve(baseDir, token)
  const root = resolve(baseDir)
  if (p === root || !p.startsWith(root + sep)) return null
  return p
}

function importsOf(file: string): string[] {
  let text: string
  try {
    text = readFileSync(file, "utf8")
  } catch {
    return []
  }
  const dir = dirname(file)
  const out: string[] = []
  // Line-level fence tracking: the opening marker keeps its FULL run (```` vs
  // ```), closing requires a same-char run at least as long.
  let fence = ""
  for (const raw of text.split("\n")) {
    const line = raw.trim()
    const fenceMatch = line.match(/^(`{3,}|~{3,})/)
    if (fenceMatch) {
      if (!fence) fence = fenceMatch[0]
      else if (fenceMatch[0].startsWith(fence)) fence = ""
      continue
    }
    if (fence) continue
    const m = line.match(/^@(\S+)$/)
    if (!m) continue
    const target = safeTarget(dir, m[1])
    if (target && existsSync(target)) {
      try {
        if (statSync(target).isFile()) out.push(target)
      } catch {
        /* unreadable: leave the token as plain text in the AGENTS.md body */
      }
    }
  }
  return out
}

// `visited` is seeded with the AGENTS.md chain itself: those bodies are
// injected natively by V2, so a back-reference must not re-inject them.
function makeExpand(state: {
  visited: Set<string>
  parts: string[]
  injected: string[]
  notes: string[]
  bytes: number
}) {
  const expand = (file: string, depth: number): void => {
    if (depth >= MAX_DEPTH) return
    for (const target of importsOf(file)) {
      if (state.visited.has(target)) continue
      state.visited.add(target)
      let text: string
      try {
        const size = statSync(target).size
        if (size > MAX_FILE_BYTES) {
          state.notes.push(target + " skipped (>64KB)")
          continue
        }
        if (state.bytes + size > MAX_TOTAL_BYTES) {
          state.notes.push(target + " skipped (total cap)")
          continue
        }
        text = readFileSync(target, "utf8")
        state.bytes += size
      } catch {
        continue
      }
      state.injected.push(target)
      state.parts.push("Instructions from: " + target + "\n" + text)
      expand(target, depth + 1)
    }
  }
  return expand
}

export default {
  id: "at-import",
  async setup(ctx: any) {
    const chain = agentsFiles(ctx)
    if (chain.length === 0) return
    const appVersion = (ctx.app && ctx.app.version) || "unknown"
    const locationDir = ctx.location.directory as string
    const record = (injected: string[], error: string | null): void =>
      writeHeartbeat({
        ts: Date.now(),
        opencodeVersion: appVersion,
        location: locationDir,
        injected,
        error,
      })
    await ctx.session.hook("context", (event: any) => {
      // Never throw: a broken rebuild must not take the agent loop down.
      try {
        const state = {
          visited: new Set<string>(chain),
          parts: [] as string[],
          injected: [] as string[],
          notes: [] as string[],
          bytes: 0,
        }
        const expand = makeExpand(state)
        for (const file of chain) expand(file, 0)
        if (state.parts.length === 0 && state.notes.length === 0) {
          record([], null)
          return
        }
        let canary = "[at-import] injected: " + (state.injected.join(", ") || "(none)")
        if (state.notes.length) canary += " | skipped: " + state.notes.join(", ")
        event.system.push({ type: "text", text: canary })
        for (const part of state.parts) event.system.push({ type: "text", text: part })
        record(state.injected, null)
      } catch (e) {
        record([], String(e))
        try {
          event.system.push({ type: "text", text: "[at-import] ERROR: rebuild failed — " + String(e) })
        } catch {
          /* channel dead too; the heartbeat already recorded the error */
        }
      }
    })
  },
}
