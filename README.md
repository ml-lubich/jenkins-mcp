# ijenk

[![CI](https://github.com/ml-lubich/ijenk/actions/workflows/ci.yml/badge.svg)](https://github.com/ml-lubich/ijenk/actions/workflows/ci.yml)

A Jenkins CLI + MCP server — manage nodes, users, and jobs from the terminal or from AI agents.

## Features
- **Node Management**: Add, remove, and list worker nodes/agents.
- **Account Management**: Create and configure Jenkins user accounts.
- **Job Overview**: List jobs and their status.
- **CSRF Token / Crumb Handling**: Automatically acquires and attaches `Jenkins-Crumb` for Jenkins 2.x instances with security enabled.
- **Dual Mode**: Works as a standalone terminal CLI (`ijenk`) or as an MCP server for AI agents (`ijenk-mcp`).

## Install

```bash
pip install ijenk
```

or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install ijenk
```

## Quickstart

```bash
export JENKINS_URL="https://jenkins.example.com"
export JENKINS_USER="admin"
export JENKINS_PASSWORD="your-api-token"

ijenk status
```

## CLI Usage

```bash
# Check status of all nodes
ijenk status

# Add a worker node
ijenk node add worker-01 --ip 192.0.2.10 --labels "linux worker"

# Remove a worker node
ijenk node remove worker-01

# Create a new user account
ijenk user create someuser 'a-strong-password' --email someuser@example.com

# List all jobs
ijenk jobs

# Run the MCP stdio server
ijenk serve
```

Credentials can also be passed explicitly, overriding env vars / config file:

```bash
ijenk --url https://jenkins.example.com --user admin --password '...' status
```

## Configuration

`ijenk` never ships with credentials. It resolves connection settings in this
order, first match wins:

1. Explicit CLI flags: `--url`, `--user`, `--password`
2. Environment variables: `JENKINS_URL`, `JENKINS_USER`, `JENKINS_PASSWORD`
3. A JSON config file at `~/.config/ijenk/config.json`

If no username/password is found by any of the above, the command exits with
a clear error instead of connecting anonymously.

### Environment variables

```bash
export JENKINS_URL="https://jenkins.example.com"
export JENKINS_USER="your-jenkins-username"
export JENKINS_PASSWORD="your-jenkins-api-token"
```

### Config file

Create `~/.config/ijenk/config.json`:

```json
{
  "url": "https://jenkins.example.com",
  "username": "your-jenkins-username",
  "password": "your-jenkins-api-token"
}
```

## Running as an MCP Server for AI Agents

`ijenk` ships a dedicated entry point for the MCP server:

```bash
ijenk-mcp
```

(equivalent to `ijenk serve`)

Register it with Claude Code:

```bash
claude mcp add jenkins -- ijenk-mcp
```

Exposed MCP Tools:
- `jenkins_get_status()`
- `jenkins_add_node(name, ip, labels, remote_fs)`
- `jenkins_remove_node(name)`
- `jenkins_create_user(username, password, email)`
- `jenkins_list_jobs()`

## Security

Requests use HTTP Basic Auth, which sends `username:password` base64-encoded
on every request — base64 is trivially reversible, not encryption. Use an
`https://` Jenkins URL, or make sure the connection stays on a trusted
network, before sending real credentials.

Prefer a Jenkins **API token** over your account password: generate one under
your Jenkins user profile ("Configure" → "API Token") and set it as
`JENKINS_PASSWORD`. `ijenk` accepts an API token anywhere it accepts a
password, and tokens can be revoked independently of your login credentials.

## Development

```bash
git clone https://github.com/ml-lubich/ijenk.git
cd ijenk
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
