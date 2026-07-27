# jenkins-mcp

[![CI](https://github.com/ml-lubich/jenkins-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ml-lubich/jenkins-mcp/actions/workflows/ci.yml)

A Jenkins CLI + MCP server — build lifecycle with exit codes, pipeline/stage
inspection, live logs, input steps, artifacts, queue management, credentials,
plugins, multi-context profiles, and node/user/git-tool administration, from
the terminal or from AI agents. Pure standard library (argparse + urllib +
json) — no extra runtime dependencies beyond the `mcp` package needed for
`serve`.

```bash
jenkins-mcp status
jenkins-mcp job build my-pipeline --watch -p BRANCH=main
jenkins-mcp job log my-pipeline -f
jenkins-mcp pipeline info my-pipeline
jenkins-mcp doctor
jenkins-mcp serve
```

## Why jenkins-mcp

Compared to other Jenkins CLIs (e.g. `addozhang/jk`, the `jk` community
skill), `jenkins-mcp` is a superset: everything they do, plus Jenkins
administration and a native MCP server.

| Capability | jenkins-mcp | jk |
|---|---|---|
| Build lifecycle with `--watch` exit codes (0/1/2/3/4/10) | ✅ | ✅ |
| Live/follow console logs (`job log -f`) | ✅ | ✅ |
| Pipeline stage tree (`pipeline info`) | ✅ | ✅ |
| Pipeline input steps (`build input`) | ✅ | ✅ |
| Build artifacts list/download | ✅ | ✅ |
| Build queue list/cancel | ✅ | ✅ |
| Build rerun/replay with same parameters | ✅ | ✅ |
| `doctor` connectivity/auth/version checks | ✅ | ✅ |
| Fuzzy job name search | ✅ | ✅ |
| Multi-context / named profiles | ✅ | ✅ (URL-as-identity) |
| Machine-readable `-o json` output | ✅ | ✅ |
| **Node/agent management** (add/remove worker nodes) | ✅ | ❌ |
| **User account management** | ✅ | ❌ |
| **Credentials management** (create/list/delete) | ✅ | ❌ |
| **Plugin management** (list/install) | ✅ | ❌ |
| **Native MCP server** for AI agents (`jenkins-mcp serve`) | ✅ | ❌ |

`jk` is explicitly scoped to build/pipeline operations and does not manage
nodes, users, credentials, or plugins — `jenkins-mcp` covers both the
developer workflow and Jenkins administration, and exposes all of it as MCP
tools an AI agent can call directly.

## Features
- **Build Lifecycle**: trigger, watch, cancel, and rerun builds with
  shell-friendly exit codes; pass parameters with `-p KEY=VALUE`.
- **Pipeline Inspection**: stage-by-stage status/duration, and resolving
  paused input steps.
- **Logs**: tail or live-follow (`-f`) a build's console output.
- **Artifacts**: list and download build artifacts, with glob filtering.
- **Queue Management**: list and cancel queued builds.
- **Credentials & Plugins**: manage the global credentials store and
  installed plugins.
- **Multi-Context**: named connection profiles (`context add/use/list/current`),
  selectable with `--context` or `$JENKINS_CONTEXT`.
- **Node Management**: Add, remove, and list worker nodes/agents.
- **Account Management**: Create and configure Jenkins user accounts.
- **Job Overview**: List jobs (with fuzzy `--search`) and their status.
- **Machine-Readable Output**: every command supports `-o json` (a dict
  starting with `"schemaVersion": "1"`) for scripting.
- **CSRF Token / Crumb Handling**: Automatically acquires and attaches `Jenkins-Crumb` for Jenkins 2.x instances with security enabled.
- **Dual Mode**: Works as a standalone terminal CLI (`jenkins-mcp`) or as an MCP server for AI agents (`jenkins-mcp serve`).

## Install

`jenkins-mcp` runs on **macOS, Linux, and Windows** — it's a pure-Python package,
so pip works the same everywhere:

```bash
# macOS / Linux / Windows — pip
pip install jenkins-mcp-cli

# macOS / Linux / Windows — uv
uv tool install jenkins-mcp-cli
```

Both install a `jenkins-mcp` command on your `PATH` (in PowerShell, cmd, or a
Unix shell alike).

From a clone, on any OS:

```bash
git clone https://github.com/ml-lubich/jenkins-mcp.git
cd jenkins-mcp
uv tool install .
```

## Quickstart

```bash
export JENKINS_URL="https://jenkins.example.com"
export JENKINS_USER="admin"
export JENKINS_PASSWORD="your-api-token"

jenkins-mcp status
```

## CLI Usage

```bash
# Check status of all nodes
jenkins-mcp status

# Add a worker node
jenkins-mcp node add worker-01 --ip 192.0.2.10 --labels "linux worker"

# Remove a worker node
jenkins-mcp node remove worker-01

# Create a new user account
jenkins-mcp user create someuser 'a-strong-password' --email someuser@example.com

# List all jobs (fuzzy search by substring/subsequence)
jenkins-mcp jobs --search dep

# Run the MCP stdio server
jenkins-mcp serve
```

Credentials can also be passed explicitly, overriding env vars / config file:

```bash
jenkins-mcp --url https://jenkins.example.com --user admin --password '...' status
```

Every command supports `-o json` for machine-readable output:

```bash
jenkins-mcp -o json jobs
# {"schemaVersion": "1", "jobs": [...]}
```

### Build lifecycle

```bash
# Trigger a build and watch it; exit code mirrors the result
jenkins-mcp job build my-pipeline --watch
# exit 0=SUCCESS 1=FAILURE 2=UNSTABLE 3=ABORTED 4=paused-on-input 10=jenkins-mcp error

# With build parameters (repeatable -p)
jenkins-mcp job build my-pipeline --watch -p BRANCH=main -p DEPLOY=true

# Cancel a running build and wait for it to actually stop
jenkins-mcp build cancel my-pipeline --wait

# Re-run a job with the same parameters as its last build
jenkins-mcp job rerun my-pipeline --watch
```

### Pipeline stages & paused input steps

```bash
jenkins-mcp pipeline info my-pipeline

# Resolve a paused "input" step (auto-detects the pending one)
jenkins-mcp build input my-pipeline proceed
jenkins-mcp build input my-pipeline abort --input-id Proceed
jenkins-mcp build input my-pipeline proceed -p CONFIRM=yes
```

### Logs

```bash
# Last 100 lines
jenkins-mcp job log my-pipeline --tail 100

# Live-follow until the build finishes
jenkins-mcp job log my-pipeline -f
```

### Artifacts

```bash
jenkins-mcp build artifacts my-pipeline
jenkins-mcp build download my-pipeline --pattern "*.jar" --out ./dist
```

### Queue

```bash
jenkins-mcp queue list
jenkins-mcp queue cancel 42
```

### Doctor

```bash
jenkins-mcp doctor
# [OK] reachable: https://jenkins.example.com
# [OK] auth: authenticated as admin
# [OK] version: 2.479.1
# [OK] crumb: <crumb value>
# exits 1 if any check fails
```

### Credentials

```bash
jenkins-mcp credential list
jenkins-mcp credential create deploy-key --kind userpass --username deployer --secret 'a-strong-password'
jenkins-mcp credential create ci-token --kind secret-text --secret 'a-token-value'
jenkins-mcp credential delete deploy-key
```

### Plugins

```bash
jenkins-mcp plugin list --search git
jenkins-mcp plugin list --updates
jenkins-mcp plugin install workflow-aggregator
```

### Multi-context (named profiles)

```bash
jenkins-mcp context add prod --url https://jenkins.example.com --user admin --password 'token'
jenkins-mcp context use prod
jenkins-mcp context list
jenkins-mcp context current

# Use a context without making it the default
jenkins-mcp --context prod jobs
JENKINS_CONTEXT=prod jenkins-mcp jobs
```

## Configuration

`jenkins-mcp` never ships with credentials. It resolves connection settings in this
order, first match wins:

1. Explicit CLI flags: `--url`, `--user`, `--password`
2. Environment variables: `JENKINS_URL`, `JENKINS_USER`, `JENKINS_PASSWORD`
3. A JSON config file at `~/.config/jenkins-mcp/config.json`

If no username/password is found by any of the above, the command exits with
a clear error instead of connecting anonymously.

### Environment variables

```bash
export JENKINS_URL="https://jenkins.example.com"
export JENKINS_USER="your-jenkins-username"
export JENKINS_PASSWORD="your-jenkins-api-token"
```

### Config file

Create `~/.config/jenkins-mcp/config.json`:

```json
{
  "url": "https://jenkins.example.com",
  "username": "your-jenkins-username",
  "password": "your-jenkins-api-token"
}
```

Or define multiple named contexts (managed via `jenkins-mcp context add/use`):

```json
{
  "default_context": "prod",
  "contexts": {
    "prod": {
      "url": "https://jenkins.example.com",
      "username": "your-jenkins-username",
      "password": "your-jenkins-api-token"
    },
    "staging": {
      "url": "https://jenkins-staging.example.com",
      "username": "your-jenkins-username",
      "password": "a-different-token"
    }
  }
}
```

## Running as an MCP Server for AI Agents

`jenkins-mcp` ships a `serve` subcommand that runs the MCP stdio server:

```bash
jenkins-mcp serve
```

Register it with Claude Code:

```bash
claude mcp add jenkins -- jenkins-mcp serve
```

Exposed MCP Tools:
- `jenkins_get_status()`
- `jenkins_add_node(name, ip, labels, remote_fs)`
- `jenkins_remove_node(name)`
- `jenkins_create_user(username, password, email)`
- `jenkins_list_jobs()`
- `jenkins_use_jgit()`
- `jenkins_build_job(job, wait)`
- `jenkins_pipeline_info(job, build)`
- `jenkins_cancel_build(job, build)`
- `jenkins_build_log_tail(job, build, lines)`
- `jenkins_pending_input(job, build)`
- `jenkins_list_artifacts(job, build)`
- `jenkins_queue_list()`
- `jenkins_doctor()`
- `jenkins_list_credentials()`
- `jenkins_create_credential(id, kind, username, secret, description)`
- `jenkins_list_plugins(search)`
- `jenkins_install_plugin(name)`
- `jenkins_rerun_build(job, build)`

Every tool other than `jenkins_get_status`/`jenkins_add_node`/`jenkins_remove_node`/`jenkins_create_user`/`jenkins_list_jobs`/`jenkins_use_jgit`/`jenkins_build_job`
catches its own errors and returns `{"error": "..."}` instead of raising.

## Security

Requests use HTTP Basic Auth, which sends `username:password` base64-encoded
on every request — base64 is trivially reversible, not encryption. Use an
`https://` Jenkins URL, or make sure the connection stays on a trusted
network, before sending real credentials.

Prefer a Jenkins **API token** over your account password: generate one under
your Jenkins user profile ("Configure" → "API Token") and set it as
`JENKINS_PASSWORD`. `jenkins-mcp` accepts an API token anywhere it accepts a
password, and tokens can be revoked independently of your login credentials.

## Development

```bash
git clone https://github.com/ml-lubich/jenkins-mcp.git
cd jenkins-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest -q
```

## License

MIT
