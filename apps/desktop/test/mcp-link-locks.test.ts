import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'

const read = (path: string) =>
  readFileSync(fileURLToPath(new URL(`../src-tauri/src/${path}`, import.meta.url)), 'utf8')

describe('the mcp link locks (#1431)', () => {
  test('watch clones the endpoint with the held lock dropped before ask_window', () => {
    // Edition 2021 keeps an `if let` scrutinee temporary alive to the end of
    // the whole `if let`. `ask_window` → `change` re-locks `held` on the same
    // thread, so a guard reaching across `ask_window` waits on itself forever
    // once the window answers (#1431): every MCP call then queues behind that
    // thread's own lock, and the agent's Orden tools stop answering.
    const link = read('mcp/link.rs')
    const watch = link.slice(link.indexOf('fn watch(&self, dir: &Path)'))
    const asking = watch.slice(
      watch.indexOf('if seen.standing == Standing::Paired && seen.window.is_none()'),
    )

    expect(asking).toContain('ask_window')
    // The scrutinee temporary must not reach across ask_window: the endpoint
    // is cloned through a scoped guard that drops before the call.
    expect(asking).not.toMatch(
      /if let Some\(endpoint\) = self\.held\(\)\.endpoint\.clone\(\) \{[\s\S]*ask_window/,
    )
    expect(asking).toMatch(
      /let endpoint = self\.held\(\)\.endpoint\.clone\(\);\s*\n\s*if let Some\(endpoint\) = endpoint \{/,
    )
  })
})
