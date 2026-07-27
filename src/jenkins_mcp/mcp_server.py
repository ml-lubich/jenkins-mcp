import json
from mcp.server.fastmcp import FastMCP
from jenkins_mcp.client import JenkinsClient

def create_mcp_server(client: JenkinsClient = None) -> FastMCP:
    mcp = FastMCP("jenkins-mcp")

    if client is None:
        client = JenkinsClient.from_env()

    @mcp.tool()
    def jenkins_get_status() -> str:
        """Get status of all Jenkins nodes and executors."""
        res = client.get_status()
        return str(res["nodes"])

    @mcp.tool()
    def jenkins_add_node(name: str, ip: str = "", labels: str = "dev-test worker", remote_fs: str = "/home/jenkins") -> str:
        """Add/register a worker node on Jenkins."""
        res = client.add_node(node_name=name, ip=ip, labels=labels, remote_fs=remote_fs)
        return f"Add node result: {res['output'].strip()}"

    @mcp.tool()
    def jenkins_remove_node(name: str) -> str:
        """Remove a worker node from Jenkins."""
        res = client.remove_node(node_name=name)
        return f"Remove node result: {res['output'].strip()}"

    @mcp.tool()
    def jenkins_create_user(username: str, password: str, email: str = "") -> str:
        """Create a new user account in Jenkins."""
        res = client.create_user(username=username, password=password, email=email)
        return f"Create user result: {res['output'].strip()}"

    @mcp.tool()
    def jenkins_list_jobs() -> str:
        """List all jobs in Jenkins."""
        jobs = client.list_jobs()
        return str(jobs)

    @mcp.tool()
    def jenkins_use_jgit() -> str:
        """Set the default Jenkins git tool to JGit (pure-Java git, no OS git binary needed)."""
        res = client.set_default_git_tool_jgit()
        return json.dumps(res)

    @mcp.tool()
    def jenkins_build_job(job: str, wait: bool = True) -> str:
        """Trigger a Jenkins job build, optionally waiting for the result."""
        res = client.wait_job(job) if wait else client.build_job(job)
        return json.dumps(res)

    @mcp.tool()
    def jenkins_pipeline_info(job: str, build: str = "lastBuild") -> str:
        """Get the pipeline stage tree (name/status/duration) for a build."""
        try:
            return json.dumps(client.get_pipeline_info(job, build=build))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_cancel_build(job: str, build: str = "lastBuild") -> str:
        """Cancel/abort a running build."""
        try:
            return json.dumps(client.cancel_build(job, build=build))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_build_log_tail(job: str, build: str = "lastBuild", lines: int = 40) -> str:
        """Get the last N lines of a build's console log."""
        try:
            return json.dumps({"job": job, "build": build, "log": client.get_build_log_tail(job, lines=lines)})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_pending_input(job: str, build: str = "lastBuild") -> str:
        """Check whether a pipeline build is paused waiting on an input step."""
        try:
            return json.dumps(client.get_pending_input(job, build=build))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_list_artifacts(job: str, build: str = "lastBuild") -> str:
        """List artifacts produced by a build."""
        try:
            return json.dumps(client.list_artifacts(job, build=build))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_queue_list() -> str:
        """List items currently in the Jenkins build queue."""
        try:
            return json.dumps(client.queue_list())
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_doctor() -> str:
        """Run connectivity/auth/version/crumb health checks against Jenkins."""
        try:
            return json.dumps(client.doctor())
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_list_credentials() -> str:
        """List global credentials (never returns secret values)."""
        try:
            return json.dumps(client.list_credentials())
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_create_credential(id: str, kind: str, username: str = "", secret: str = "", description: str = "") -> str:
        """Create a global credential (kind: userpass or secret_text)."""
        try:
            return json.dumps(client.create_credential(id, kind, username=username, secret=secret, description=description))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_list_plugins(search: str = "") -> str:
        """List installed plugins, optionally filtered by a substring."""
        try:
            return json.dumps(client.list_plugins(search=search))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_install_plugin(name: str) -> str:
        """Request installation of a plugin by short name."""
        try:
            return json.dumps(client.install_plugin(name))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def jenkins_rerun_build(job: str, build: str = "lastBuild") -> str:
        """Re-trigger a job with the same parameters as a previous build."""
        try:
            return json.dumps(client.rerun_build(job, build=build))
        except Exception as e:
            return json.dumps({"error": str(e)})

    return mcp

def run_server(client: JenkinsClient = None):
    mcp = create_mcp_server(client)
    mcp.run()
