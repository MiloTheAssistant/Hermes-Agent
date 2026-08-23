// Backend subcommand routing for the desktop-managed Hermes process.
//
// The desktop app spawns a backend to host its SPA. The renderer fetches the
// session token from the served `index.html` (window.__HERMES_SESSION_TOKEN__),
// so the backend MUST serve the SPA. We use `hermes dashboard --no-open` for
// that: the `--no-open` flag prevents the browser window from popping up while
// the SPA is still served. The legacy `hermes serve` subcommand explicitly
// disables the SPA (sets HERMES_SERVE_HEADLESS=1 → mount_spa returns 404 on
// every non-API path) and is therefore incompatible with this renderer's
// token-discovery strategy. The fallback chain below exists only as defense
// in depth: if `dashboard` were ever removed, we would need to teach the
// renderer to fetch the token through an authenticated API endpoint first.
//
// These helpers are pure so they can be unit-tested without Electron.

/**
 * Build the canonical desktop backend argv. Always `dashboard --no-open` so
 * the SPA is served; the `--no-open` flag suppresses the browser window.
 * @param {string} [profile] optional Hermes profile to pin via `--profile`.
 */
export function serveBackendArgs(profile?: string) {
  const head = profile ? ['--profile', profile] : []

  return [...head, 'dashboard', '--no-open', '--host', '127.0.0.1', '--port', '0']
}

/**
 * Rewrite a resolved backend argv from `serve` to the legacy
 * `dashboard --no-open` form, preserving every other argument (incl. a leading
 * `-m hermes_cli.main` and any `--profile <name>`). Returns a copy; if there is
 * no `serve` token the argv is returned unchanged.
 */
export function dashboardFallbackArgs(args: string[]) {
  const i = args.indexOf('serve')

  if (i === -1) {
    return args.slice()
  }

  return [...args.slice(0, i), 'dashboard', '--no-open', ...args.slice(i + 1)]
}

/**
 * True when a runtime's `hermes_cli/subcommands/dashboard.py` source registers
 * the `serve` subcommand. Matches `add_parser("serve"` / `add_parser('serve'`
 * specifically so the substring "server" (e.g. "start_server", "web server")
 * never produces a false positive.
 */
export function sourceDeclaresServe(dashboardPySource: string) {
  return /add_parser\(\s*["']serve["']/.test(String(dashboardPySource || ''))
}
