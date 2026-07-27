import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

DEFAULT_URL = "http://localhost:8080"


def _config_file_path() -> Path:
    return Path.home() / ".config" / "jenkins-mcp" / "config.json"


def _load_config_file() -> Dict[str, str]:
    try:
        with open(_config_file_path()) as f:
            cfg = json.load(f)
            return cfg if isinstance(cfg, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_jenkins_config(
    url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Resolve Jenkins connection settings: explicit args > env vars > config file."""
    file_cfg = _load_config_file()
    url = url or os.environ.get("JENKINS_URL") or file_cfg.get("url") or DEFAULT_URL
    username = username or os.environ.get("JENKINS_USER") or file_cfg.get("username")
    password = password or os.environ.get("JENKINS_PASSWORD") or file_cfg.get("password")
    if not username or not password:
        raise ValueError(
            "Jenkins credentials not found. Set JENKINS_USER and JENKINS_PASSWORD "
            "environment variables, pass --user/--password, or create "
            f"{_config_file_path()} with {{\"username\": ..., \"password\": ...}}."
        )
    return url, username, password


def _groovy_escape(value: Any) -> str:
    """Escape a value for safe interpolation into a Groovy single-quoted string."""
    return str(value).replace('\\', '\\\\').replace("'", "\\'")


class JenkinsClient:
    def __init__(self, url: str = DEFAULT_URL, username: Optional[str] = None, password: Optional[str] = None):
        if not username or not password:
            raise ValueError(
                "JenkinsClient requires a username and password. Pass them explicitly "
                "or use JenkinsClient.from_env()."
            )
        self.url = url.rstrip('/')
        self.username = username
        self.password = password

    @classmethod
    def from_env(
        cls,
        url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> "JenkinsClient":
        url, username, password = resolve_jenkins_config(url, username, password)
        return cls(url=url, username=username, password=password)

    def _get_auth_header(self) -> str:
        auth_str = f"{self.username}:{self.password}"
        b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
        return f"Basic {b64_auth}"

    def get_crumb(self) -> Tuple[Optional[str], Optional[str]]:
        req = urllib.request.Request(f"{self.url}/crumbIssuer/api/json")
        req.add_header("Authorization", self._get_auth_header())
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                crumb = data.get('crumb')
                cookie = resp.info().get('Set-Cookie')
                return crumb, cookie
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, None
            raise

    def execute_groovy(self, script: str) -> str:
        crumb, cookie = self.get_crumb()
        data = urllib.parse.urlencode({'script': script}).encode('utf-8')
        req = urllib.request.Request(f"{self.url}/scriptText", data=data, method='POST')
        req.add_header("Authorization", self._get_auth_header())
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if crumb:
            req.add_header("Jenkins-Crumb", crumb)
        if cookie:
            req.add_header("Cookie", cookie)

        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode('utf-8')

    def get_status(self) -> Dict[str, Any]:
        req = urllib.request.Request(f"{self.url}/computer/api/json")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            nodes = []
            for comp in data.get('computer', []):
                nodes.append({
                    "name": comp.get('displayName'),
                    "offline": comp.get('offline'),
                    "labels": [l.get('name') for l in comp.get('assignedLabels', [])],
                    "executors": comp.get('numExecutors')
                })
            return {"nodes": nodes, "raw": data}

    def add_node(
        self,
        node_name: str,
        remote_fs: str = "/home/jenkins",
        num_executors: int = 2,
        labels: str = "dev-test worker",
        description: str = "Worker node",
        ip: str = ""
    ) -> Dict[str, Any]:
        desc = f"{description} ({ip})" if ip else description
        node_name_esc = _groovy_escape(node_name)
        desc_esc = _groovy_escape(desc)
        remote_fs_esc = _groovy_escape(remote_fs)
        num_executors_esc = _groovy_escape(num_executors)
        labels_esc = _groovy_escape(labels)
        script = f"""
import hudson.model.*
import hudson.slaves.*

def existing = Jenkins.instance.getNode('{node_name_esc}')
if (existing != null) {{
    Jenkins.instance.removeNode(existing)
}}

DumbSlave agent = new DumbSlave(
    '{node_name_esc}',
    '{desc_esc}',
    '{remote_fs_esc}',
    '{num_executors_esc}',
    Node.Mode.NORMAL,
    '{labels_esc}',
    new JNLPLauncher(),
    RetentionStrategy.Always.INSTANCE,
    new ArrayList()
)
Jenkins.instance.addNode(agent)
println 'SUCCESS'
"""
        output = self.execute_groovy(script)
        success = "SUCCESS" in output
        return {"success": success, "node_name": node_name, "output": output}

    def remove_node(self, node_name: str) -> Dict[str, Any]:
        node_name_esc = _groovy_escape(node_name)
        script = f"""
def existing = Jenkins.instance.getNode('{node_name_esc}')
if (existing != null) {{
    Jenkins.instance.removeNode(existing)
    println 'REMOVED'
}} else {{
    println 'NOT_FOUND'
}}
"""
        output = self.execute_groovy(script)
        return {"success": "REMOVED" in output, "node_name": node_name, "output": output}

    def create_user(self, username: str, password: str, email: Optional[str] = None) -> Dict[str, Any]:
        user_email = email or f"{username}@example.com"
        username_esc = _groovy_escape(username)
        password_esc = _groovy_escape(password)
        user_email_esc = _groovy_escape(user_email)
        script = f"""
def user = hudson.model.User.get('{username_esc}', true)
def details = new hudson.security.HudsonPrivateSecurityRealm.Details('{password_esc}', '{user_email_esc}')
user.addProperty(details)
user.save()
println 'USER_CREATED'
"""
        output = self.execute_groovy(script)
        return {"success": "USER_CREATED" in output, "username": username, "output": output}

    def set_default_git_tool_jgit(self) -> Dict[str, Any]:
        script = """
import org.jenkinsci.plugins.gitclient.JGitTool
import hudson.plugins.git.GitTool
def d = Jenkins.instance.getDescriptorByType(GitTool.DescriptorImpl)
def before = d.installations.collect{ it.name }
// Must be an explicitly-typed GitTool[]: a bare vararg erases to
// ToolInstallation[], which makes GitTool.getDefaultInstallation() throw
// ClassCastException when the git plugin casts the array back to GitTool[].
GitTool[] tools = [ new JGitTool() ]
d.setInstallations(tools)
d.save()
def resolved = GitTool.getDefaultInstallation()
println "GITTOOL_BEFORE=" + before
println "GITTOOL_ARRAYTYPE=" + d.installations.getClass().getName()
println "GITTOOL_DEFAULT=" + (resolved ? resolved.class.simpleName + ':' + resolved.name : 'null')
println "GITTOOL_AFTER=" + Jenkins.instance.getDescriptorByType(GitTool.DescriptorImpl).installations.collect{ it.class.simpleName + ':' + it.name }
"""
        output = self.execute_groovy(script)
        ok = "JGitTool" in output and "GITTOOL_DEFAULT=JGitTool" in output
        return {"ok": ok, "output": output}

    def build_job(self, job_name: str) -> Dict[str, Any]:
        job_name_esc = _groovy_escape(job_name)
        script = f"""
def j=Jenkins.instance.getItemByFullName('{job_name_esc}'); def q=j.scheduleBuild2(0); println "QUEUED=" + (q!=null)
"""
        output = self.execute_groovy(script)
        return {"job": job_name, "queued": "QUEUED=true" in output, "output": output}

    def get_job_result(self, job_name: str) -> Dict[str, Any]:
        job_name_esc = _groovy_escape(job_name)
        script = f"""
def j=Jenkins.instance.getItemByFullName('{job_name_esc}'); def b=j?.lastBuild; if(b==null){{println "NOBUILD"}} else {{println "NUM="+b.number; println "BUILDING="+b.isBuilding(); println "RESULT="+(b.result?:"null")}}
"""
        output = self.execute_groovy(script)
        result: Dict[str, Any] = {"job": job_name, "number": None, "building": False, "result": None}
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("NUM="):
                result["number"] = int(line[len("NUM="):])
            elif line.startswith("BUILDING="):
                result["building"] = line[len("BUILDING="):].strip().lower() == "true"
            elif line.startswith("RESULT="):
                value = line[len("RESULT="):].strip()
                result["result"] = None if value == "null" else value
        return result

    def wait_job(self, job_name: str, timeout: int = 300, poll: int = 6) -> Dict[str, Any]:
        start = self.get_job_result(job_name)
        start_number = start.get("number")
        self.build_job(job_name)

        result = start
        elapsed = 0
        timed_out = True
        while elapsed <= timeout:
            result = self.get_job_result(job_name)
            if result.get("number") is not None and result.get("number") != start_number and not result.get("building"):
                timed_out = False
                break
            time.sleep(poll)
            elapsed += poll

        return {
            "job": job_name,
            "number": result.get("number"),
            "result": result.get("result"),
            "waited": elapsed,
            "timed_out": timed_out,
        }

    def get_build_log_tail(self, job_name: str, lines: int = 40) -> str:
        quoted = urllib.parse.quote(job_name)
        req = urllib.request.Request(f"{self.url}/job/{quoted}/lastBuild/consoleText")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode('utf-8')
        return "\n".join(text.splitlines()[-lines:])

    def list_jobs(self) -> List[Dict[str, Any]]:
        req = urllib.request.Request(f"{self.url}/api/json")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            jobs = []
            for job in data.get('jobs', []):
                jobs.append({
                    "name": job.get('name'),
                    "url": job.get('url'),
                    "color": job.get('color')
                })
            return jobs
