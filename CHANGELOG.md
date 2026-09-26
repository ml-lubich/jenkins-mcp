# Changelog

## 0.3.1

Pin `mcp<2` — mcp 2.x renamed `FastMCP` to `MCPServer` and removed
`mcp.server.fastmcp`, so an unbounded `mcp>=1.0.0` resolved 2.x on fresh
installs and broke server startup / test collection.

## 0.3.0

Major feature overhaul: build lifecycle with exit codes, pipeline/stage
inspection, live logs, input steps, artifacts, queue management, credentials,
plugins, and multi-context support — all stdlib-only (argparse + urllib +
json), no new dependencies.

### Added

- **Global `-o/--output {text,json}`** flag on every command. JSON output is
  always a dict starting with `"schemaVersion": "1"`.
- **Build lifecycle & exit codes**: `job build NAME --watch` exits `0`
  (SUCCESS), `1` (FAILURE), `2` (UNSTABLE), `3` (ABORTED), `4` (paused on a
  pipeline input step), or `10` (jenkins-mcp-level error). `-p/--param KEY=VALUE`
  (repeatable) passes build parameters.
- **`build cancel NAME [--build B] [--wait]`**: abort a running build, with
  the same exit-code contract when waiting.
- **`pipeline info NAME [--build B]`**: stage-by-stage status/duration via the
  Pipeline `wfapi` REST API.
- **`job log NAME [--build B] [--tail N] [-f/--follow] [--poll SECS]`**: print
  or live-follow a build's console log via the progressive log API.
- **`build input NAME {proceed,abort} [--input-id ID] [-p K=V ...]`**: resolve
  a paused pipeline input step (auto-detects the pending input if `--input-id`
  is omitted).
- **`build artifacts NAME [--build B]`** and
  **`build download NAME [--pattern GLOB] [--out DIR]`**: list/download build
  artifacts, with glob filtering.
- **`queue list`** / **`queue cancel ID`**: inspect and cancel queued builds.
- **`jobs --search TERM`**: fuzzy (substring + subsequence) job name filter.
- **`doctor`**: connectivity/auth/version/crumb health checks; exits `1` if
  any check fails.
- **Multi-context profiles**: config file `contexts`/`default_context`,
  `--context NAME` (or `$JENKINS_CONTEXT`), and `context list` / `context add`
  / `context use` / `context current` (passwords are never printed).
- **Credentials management**: `credential list` / `create` / `delete` (global
  store; secrets are never printed back).
- **Plugin management**: `plugin list [--search TERM] [--updates]` and
  `plugin install NAME`.
- **Build rerun/replay**: `job rerun NAME [--build B] [--watch]` re-triggers a
  job with the same parameters as a previous build.
- New MCP tools: `jenkins_pipeline_info`, `jenkins_cancel_build`,
  `jenkins_build_log_tail`, `jenkins_pending_input`, `jenkins_list_artifacts`,
  `jenkins_queue_list`, `jenkins_doctor`, `jenkins_list_credentials`,
  `jenkins_create_credential`, `jenkins_list_plugins`,
  `jenkins_install_plugin`, `jenkins_rerun_build`.

## 0.1.0

Initial release: node/user/git-tool administration, job listing, job build +
wait, console log tail, and an MCP stdio server.
