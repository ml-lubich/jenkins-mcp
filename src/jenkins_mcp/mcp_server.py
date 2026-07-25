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

    return mcp

def run_server(client: JenkinsClient = None):
    mcp = create_mcp_server(client)
    mcp.run()
