import assert from 'node:assert/strict'

import { test } from 'vitest'

import { dashboardFallbackArgs, serveBackendArgs, sourceDeclaresServe } from './backend-command'

test('serveBackendArgs builds a dashboard --no-open invocation that serves the SPA', () => {
  // The desktop renderer discovers its session token by parsing
  // `window.__HERMES_SESSION_TOKEN__` out of the served `index.html`
  // (see `dashboard-token.ts:adoptServedDashboardToken`). The backend the
  // desktop spawns MUST serve the SPA. `hermes serve` is intentionally
  // headless (sets HERMES_SERVE_HEADLESS=1 and returns 404 on every non-API
  // path) and would break boot. `dashboard --no-open` serves the SPA without
  // popping a browser window.
  assert.deepEqual(serveBackendArgs(), ['dashboard', '--no-open', '--host', '127.0.0.1', '--port', '0'])
})

test('serveBackendArgs pins a profile when provided', () => {
  assert.deepEqual(serveBackendArgs('worker'), [
    '--profile',
    'worker',
    'dashboard',
    '--no-open',
    '--host',
    '127.0.0.1',
    '--port',
    '0'
  ])
})

test('serveBackendArgs never routes to headless `serve` (regression: v0.20.4 boot failure)', () => {
  // Invariant, not a snapshot: the desktop must never spawn `hermes serve`,
  // because `serve` does not serve the SPA. If a future change reintroduces
  // it, this test fails loudly at the unit level — the symptom in production
  // is a desktop window that opens and immediately fails WebSocket auth.
  for (const profile of [undefined, 'worker']) {
    assert.ok(
      !serveBackendArgs(profile).includes('serve'),
      `serveBackendArgs(${JSON.stringify(profile)}) must not contain 'serve': ${JSON.stringify(serveBackendArgs(profile))}`
    )
  }
})

test('dashboardFallbackArgs rewrites serve -> dashboard --no-open, keeping the -m prefix', () => {
  const serve = ['-m', 'hermes_cli.main', 'serve', '--host', '127.0.0.1', '--port', '0']
  assert.deepEqual(dashboardFallbackArgs(serve), [
    '-m',
    'hermes_cli.main',
    'dashboard',
    '--no-open',
    '--host',
    '127.0.0.1',
    '--port',
    '0'
  ])
})

test('dashboardFallbackArgs preserves a --profile flag ahead of serve', () => {
  const serve = ['-m', 'hermes_cli.main', '--profile', 'worker', 'serve', '--host', '127.0.0.1', '--port', '0']
  assert.deepEqual(dashboardFallbackArgs(serve), [
    '-m',
    'hermes_cli.main',
    '--profile',
    'worker',
    'dashboard',
    '--no-open',
    '--host',
    '127.0.0.1',
    '--port',
    '0'
  ])
})

test('dashboardFallbackArgs is a no-op (copy) when there is no serve token', () => {
  const args = ['-m', 'hermes_cli.main', 'dashboard', '--no-open']
  const out = dashboardFallbackArgs(args)
  assert.deepEqual(out, args)
  assert.notEqual(out, args, 'should return a copy, not the same reference')
})

test('sourceDeclaresServe detects the serve subparser registration', () => {
  assert.equal(sourceDeclaresServe('subparsers.add_parser("serve", help="...")'), true)
  assert.equal(sourceDeclaresServe("subparsers.add_parser('serve')"), true)
  assert.equal(sourceDeclaresServe('subparsers.add_parser(\n        "serve",\n)'), true)
})

test('sourceDeclaresServe does not false-positive on the substring "server"', () => {
  const oldSource = `
    dashboard_parser = subparsers.add_parser("dashboard", help="Start the web UI dashboard")
    from hermes_cli.web_server import start_server  # web server
  `

  assert.equal(sourceDeclaresServe(oldSource), false)
})
