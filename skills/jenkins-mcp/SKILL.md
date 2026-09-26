---
name: jenkins-mcp
description: Jenkins CLI and MCP server for build lifecycle, pipeline/stage inspection, live logs, artifacts, queue, credentials, plugins, and node/user/git-tool administration. Use when the user asks to check Jenkins build status, trigger/watch/cancel/rerun a build, tail Jenkins console logs, inspect pipeline stages, resolve a paused pipeline input step, list/download build artifacts, manage the build queue, manage Jenkins credentials/plugins/nodes/users, or run Jenkins connectivity diagnostics ("jenkins doctor"). Also use to wire up the `jenkins-mcp serve` MCP server for an agent that needs these Jenkins tools directly.
---

# jenkins-mcp

Jenkins CLI + MCP server. Pure standard library (argparse + urllib + json) —
no extra runtime dependency beyond the `mcp` package, which is only needed
for `serve`.

## Install

```bash
# editable, from a local clone
uv tool install -e ~/dev/jenkins-mcp

# fresh from GitHub
git clone https://github.com/ml-lubich/jenkins-mcp && uv tool install -e ./jenkins-mcp
```

This installs one CLI: `jenkins-mcp`.

## Credentials (required before any real command)

No macOS permissions are needed — this is a plain HTTP client, no Keychain,
Contacts, Calendar, or Automation access. It needs Jenkins credentials,
resolved in this order: CLI flags > env vars > named context file.

```bash
export JENKINS_URL=http://localhost:8080
export JENKINS_USER=admin
export JENKINS_PASSWORD=...        # or a Jenkins API token
```

Or store one or more named profiles in `~/.config/jenkins-mcp/config.json`
(plaintext on disk — treat it like any other local credentials file):

```bash
jenkins-mcp context add prod --url https://jenkins.example.com --user admin --password '...'
jenkins-mcp context use prod
jenkins-mcp context list      # never prints passwords
```

## Key CLI commands (real flags, from `--help`)

```
jenkins-mcp [--url URL] [--user USER] [--password PASSWORD] [--context CONTEXT] [-o {text,json}] <command>

status                Get status of all nodes
node                  Node management (add/remove agents)
user                  User management
jobs                  List Jenkins jobs
git                   Git tool management (e.g. force JGit)
job                   Job management: build/watch/log/rerun (-p KEY=VALUE for params, -f to follow logs)
build                 Build operations: cancel, input, artifacts, download
pipeline              Pipeline/stage inspection (pipeline info <job>)
queue                 Build queue management (list/cancel)
credential            Credentials management (create/list/delete)
plugin                Plugin management (list/install)
context               Manage named Jenkins contexts/profiles (list/current/add/use)
doctor                Connectivity/auth/version/crumb checks — read-only, safe to run anytime
serve                 Run the MCP stdio server
```

`-o json` on any command emits a `{"schemaVersion": "1", ...}` envelope
instead of text — use it when scripting or when an agent parses output.

## MCP server

Launch:

```bash
jenkins-mcp serve
```

Register with Claude Code:

```bash
claude mcp add jenkins-mcp -- jenkins-mcp serve
```

Set `JENKINS_URL` / `JENKINS_USER` / `JENKINS_PASSWORD` (or `JENKINS_CONTEXT`)
in the environment `claude mcp add` runs under, since the MCP server takes no
CLI flags of its own.

Exposes 19 tools, all prefixed `jenkins_`: `jenkins_get_status`,
`jenkins_add_node`, `jenkins_remove_node`, `jenkins_create_user`,
`jenkins_list_jobs`, `jenkins_use_jgit`, `jenkins_build_job`,
`jenkins_pipeline_info`, `jenkins_cancel_build`, `jenkins_build_log_tail`,
`jenkins_pending_input`, `jenkins_list_artifacts`, `jenkins_queue_list`,
`jenkins_doctor`, `jenkins_list_credentials`, `jenkins_create_credential`,
`jenkins_list_plugins`, `jenkins_install_plugin`, `jenkins_rerun_build`.

## Safety rules

- Read-only by default: prefer `status`, `jobs`, `doctor`, `pipeline info`,
  `queue list`, `list_credentials`, `list_plugins`, `list_artifacts` unless
  the user explicitly asks for a mutating action.
- Mutating operations (`job build`, `build cancel`, `node add/remove`,
  `user create`, `credential create`, `plugin install`, `queue cancel`,
  `build rerun`) touch a real Jenkins instance — never run one without the
  user's explicit ask, and confirm the target `--context`/`JENKINS_URL`
  first if more than one profile is configured.
- Credentials in `~/.config/jenkins-mcp/config.json` are stored in plaintext;
  never print or commit that file's contents.
