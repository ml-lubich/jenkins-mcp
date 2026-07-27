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

# Exit codes for build results (shared by CLI build/watch/cancel commands).
EXIT_CODE_BY_RESULT = {
    "SUCCESS": 0,
    "FAILURE": 1,
    "UNSTABLE": 2,
    "ABORTED": 3,
}
EXIT_PENDING_INPUT = 4
EXIT_ERROR = 10


def _config_file_path() -> Path:
    return Path.home() / ".config" / "jenkins-mcp" / "config.json"


def _load_config_file() -> Dict[str, Any]:
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
    context: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Resolve Jenkins connection settings.

    Priority: explicit args > env vars > named context (--context / $JENKINS_CONTEXT,
    falling back to the config file's "default_context") > top-level config file
    values > built-in default URL.
    """
    file_cfg = _load_config_file()
    contexts = file_cfg.get("contexts") or {}
    context = context or os.environ.get("JENKINS_CONTEXT") or file_cfg.get("default_context")
    ctx_cfg: Dict[str, str] = {}
    if context:
        found = contexts.get(context)
        if found is None:
            raise ValueError(
                f"Unknown Jenkins context '{context}'. Known contexts: "
                f"{', '.join(sorted(contexts)) or '(none configured)'}"
            )
        ctx_cfg = found

    url = url or os.environ.get("JENKINS_URL") or ctx_cfg.get("url") or file_cfg.get("url") or DEFAULT_URL
    username = username or os.environ.get("JENKINS_USER") or ctx_cfg.get("username") or file_cfg.get("username")
    password = password or os.environ.get("JENKINS_PASSWORD") or ctx_cfg.get("password") or file_cfg.get("password")
    if not username or not password:
        raise ValueError(
            "Jenkins credentials not found. Set JENKINS_USER and JENKINS_PASSWORD "
            "environment variables, pass --user/--password, or create "
            f"{_config_file_path()} with {{\"username\": ..., \"password\": ...}}."
        )
    return url, username, password


def list_contexts() -> List[Dict[str, Any]]:
    """List named Jenkins contexts/profiles from the config file (never passwords)."""
    file_cfg = _load_config_file()
    contexts = file_cfg.get("contexts") or {}
    default_context = file_cfg.get("default_context")
    return [
        {"name": name, "url": (cfg or {}).get("url", ""), "default": name == default_context}
        for name, cfg in contexts.items()
    ]


def _save_config_file(cfg: Dict[str, Any]) -> None:
    path = _config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)


def add_context(name: str, url: str, username: str, password: str) -> Dict[str, Any]:
    """Add/overwrite a named context in the config file. Never returns the password."""
    cfg = _load_config_file()
    contexts = cfg.get("contexts") or {}
    contexts[name] = {"url": url, "username": username, "password": password}
    cfg["contexts"] = contexts
    _save_config_file(cfg)
    return {"name": name, "url": url}


def use_context(name: str) -> Dict[str, Any]:
    """Set the config file's default_context to a known context name."""
    cfg = _load_config_file()
    contexts = cfg.get("contexts") or {}
    if name not in contexts:
        raise ValueError(
            f"Unknown Jenkins context '{name}'. Known contexts: "
            f"{', '.join(sorted(contexts)) or '(none configured)'}"
        )
    cfg["default_context"] = name
    _save_config_file(cfg)
    return {"default_context": name}


def current_context() -> Dict[str, Any]:
    """Report the active context name/url (never the password)."""
    cfg = _load_config_file()
    contexts = cfg.get("contexts") or {}
    name = os.environ.get("JENKINS_CONTEXT") or cfg.get("default_context")
    if name and name in contexts:
        return {"name": name, "url": contexts[name].get("url", "")}
    if name:
        return {"name": name, "url": "(unknown context, not found in config)"}
    return {"name": None, "url": cfg.get("url", "")}


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
        context: Optional[str] = None,
    ) -> "JenkinsClient":
        url, username, password = resolve_jenkins_config(url, username, password, context=context)
        return cls(url=url, username=username, password=password)

    def _get_auth_header(self) -> str:
        auth_str = f"{self.username}:{self.password}"
        b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
        return f"Basic {b64_auth}"

    def _crumb_headers(self) -> Dict[str, str]:
        crumb, cookie = self.get_crumb()
        headers = {}
        if crumb:
            headers["Jenkins-Crumb"] = crumb
        if cookie:
            headers["Cookie"] = cookie
        return headers

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

    def build_job(self, job_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        job_name_esc = _groovy_escape(job_name)
        if params:
            values = ",\n".join(
                f"    new hudson.model.StringParameterValue('{_groovy_escape(k)}', '{_groovy_escape(v)}')"
                for k, v in params.items()
            )
            script = f"""
def j=Jenkins.instance.getItemByFullName('{job_name_esc}')
def paramsAction = new hudson.model.ParametersAction([
{values}
])
def q=j.scheduleBuild2(0, paramsAction); println "QUEUED=" + (q!=null)
"""
        else:
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

    def watch_job(
        self,
        job_name: str,
        timeout: int = 300,
        poll: int = 6,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Queue a build and watch it, stopping early if it pauses on an input step.

        Unlike wait_job, the returned dict includes a "pending_input" entry
        (populated when a pipeline stage is paused waiting for `build input`).
        """
        start = self.get_job_result(job_name)
        start_number = start.get("number")
        self.build_job(job_name, params=params)

        result = start
        elapsed = 0
        timed_out = True
        pending_input: Optional[Dict[str, Any]] = None
        while elapsed <= timeout:
            result = self.get_job_result(job_name)
            number = result.get("number")
            if number is not None and number != start_number:
                if not result.get("building"):
                    timed_out = False
                    break
                pending_input = self.get_pending_input(job_name, build=number)
                if pending_input:
                    timed_out = False
                    break
            time.sleep(poll)
            elapsed += poll

        return {
            "job": job_name,
            "number": result.get("number"),
            "result": result.get("result"),
            "pending_input": pending_input,
            "waited": elapsed,
            "timed_out": timed_out,
        }

    def cancel_build(
        self,
        job_name: str,
        build: str = "lastBuild",
        wait: bool = False,
        timeout: int = 120,
        poll: int = 3,
    ) -> Dict[str, Any]:
        quoted = urllib.parse.quote(job_name)
        headers = self._crumb_headers()
        req = urllib.request.Request(f"{self.url}/job/{quoted}/{build}/stop", data=b"", method='POST')
        req.add_header("Authorization", self._get_auth_header())
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

        result: Dict[str, Any] = {"job": job_name, "build": build, "stopped": True}
        if wait:
            elapsed = 0
            status = self.get_job_result(job_name)
            while elapsed <= timeout and status.get("building"):
                time.sleep(poll)
                elapsed += poll
                status = self.get_job_result(job_name)
            result["number"] = status.get("number")
            result["result"] = status.get("result")
            result["timed_out"] = bool(status.get("building"))
        return result

    def get_pipeline_info(self, job_name: str, build: str = "lastBuild") -> Dict[str, Any]:
        quoted = urllib.parse.quote(job_name)
        req = urllib.request.Request(f"{self.url}/job/{quoted}/{build}/wfapi/describe")
        req.add_header("Authorization", self._get_auth_header())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(
                    f"No pipeline/stage data for job '{job_name}' build '{build}' "
                    "(not a Pipeline job, or the Pipeline: REST API plugin is missing)."
                ) from e
            raise

        stages = [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                "durationMillis": s.get("durationMillis"),
            }
            for s in data.get("stages", [])
        ]
        return {
            "name": data.get("name"),
            "status": data.get("status"),
            "stages": stages,
            "pendingInput": any(s.get("status") == "PAUSED_PENDING_INPUT" for s in stages),
        }

    def get_build_log(self, job_name: str, build: str = "lastBuild", start: int = 0) -> Tuple[str, int, bool]:
        """Fetch one chunk of a build's console log via the progressiveText API.

        Returns (text, next_start, more) where `next_start` is the offset to pass
        as `start` on the next call, and `more` is True while the build is still
        producing output.
        """
        quoted = urllib.parse.quote(job_name)
        req = urllib.request.Request(f"{self.url}/job/{quoted}/{build}/logText/progressiveText?start={start}")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode('utf-8')
            info = resp.info()
            next_start = int(info.get("X-Text-Size", start))
            more = (info.get("X-More-Data") or "false").lower() == "true"
        return text, next_start, more

    def get_build_log_tail(self, job_name: str, lines: int = 40) -> str:
        quoted = urllib.parse.quote(job_name)
        req = urllib.request.Request(f"{self.url}/job/{quoted}/lastBuild/consoleText")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode('utf-8')
        return "\n".join(text.splitlines()[-lines:])

    def get_pending_input(self, job_name: str, build: str = "lastBuild") -> Optional[Dict[str, Any]]:
        quoted = urllib.parse.quote(job_name)
        req = urllib.request.Request(f"{self.url}/job/{quoted}/{build}/wfapi/pendingInputActions")
        req.add_header("Authorization", self._get_auth_header())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        if not data:
            return None
        action = data[0]
        return {
            "id": action.get("id"),
            "message": action.get("message"),
            "ok": action.get("proceedText", "Proceed"),
            "parameters": action.get("inputs", []),
        }

    def submit_input(
        self,
        job_name: str,
        build: str,
        input_id: str,
        action: str = "proceed",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        quoted = urllib.parse.quote(job_name)
        input_id_q = urllib.parse.quote(input_id)
        headers = self._crumb_headers()

        if action == "abort":
            url = f"{self.url}/job/{quoted}/{build}/input/{input_id_q}/abort"
            data = b""
        elif params:
            url = f"{self.url}/job/{quoted}/{build}/input/{input_id_q}/submit"
            payload = json.dumps({"parameter": [{"name": k, "value": v} for k, v in params.items()]})
            data = urllib.parse.urlencode({"json": payload}).encode('utf-8')
        else:
            url = f"{self.url}/job/{quoted}/{build}/input/{input_id_q}/proceedEmpty"
            data = b""

        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header("Authorization", self._get_auth_header())
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return {"job": job_name, "build": build, "input_id": input_id, "action": action, "ok": True}

    def list_artifacts(self, job_name: str, build: str = "lastBuild") -> List[Dict[str, Any]]:
        quoted = urllib.parse.quote(job_name)
        req = urllib.request.Request(f"{self.url}/job/{quoted}/{build}/api/json?tree=artifacts[fileName,relativePath]")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return [
            {"fileName": a.get("fileName"), "relativePath": a.get("relativePath")}
            for a in data.get("artifacts", [])
        ]

    def download_artifact(self, job_name: str, build: str, relative_path: str, out_dir: str) -> str:
        quoted = urllib.parse.quote(job_name)
        path_q = urllib.parse.quote(relative_path)
        req = urllib.request.Request(f"{self.url}/job/{quoted}/{build}/artifact/{path_q}")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        out_path = Path(out_dir) / Path(relative_path).name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(content)
        return str(out_path)

    def queue_list(self) -> List[Dict[str, Any]]:
        req = urllib.request.Request(f"{self.url}/queue/api/json")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return [
            {
                "id": item.get("id"),
                "task": (item.get("task") or {}).get("name"),
                "why": item.get("why"),
                "stuck": item.get("stuck"),
            }
            for item in data.get("items", [])
        ]

    def queue_cancel(self, item_id: int) -> Dict[str, Any]:
        headers = self._crumb_headers()
        req = urllib.request.Request(f"{self.url}/queue/cancelItem?id={item_id}", data=b"", method='POST')
        req.add_header("Authorization", self._get_auth_header())
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return {"id": item_id, "cancelled": True}

    def doctor(self) -> Dict[str, Dict[str, Any]]:
        """Run connectivity/auth/version/crumb checks. Never raises."""
        checks: Dict[str, Dict[str, Any]] = {}
        req = urllib.request.Request(f"{self.url}/api/json")
        req.add_header("Authorization", self._get_auth_header())
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
                version = resp.info().get("X-Jenkins")
            checks["reachable"] = {"ok": True, "detail": self.url}
            checks["auth"] = {"ok": True, "detail": f"authenticated as {self.username}"}
            checks["version"] = {"ok": bool(version), "detail": version or "unknown"}
        except urllib.error.HTTPError as e:
            checks["reachable"] = {"ok": True, "detail": f"HTTP {e.code}"}
            checks["auth"] = {"ok": e.code not in (401, 403), "detail": f"HTTP {e.code}"}
            checks["version"] = {"ok": False, "detail": "unavailable"}
        except Exception as e:
            checks["reachable"] = {"ok": False, "detail": str(e)}
            checks["auth"] = {"ok": False, "detail": "unreachable"}
            checks["version"] = {"ok": False, "detail": "unreachable"}

        try:
            crumb, _ = self.get_crumb()
            checks["crumb"] = {"ok": True, "detail": crumb or "not required (CSRF protection disabled)"}
        except Exception as e:
            checks["crumb"] = {"ok": False, "detail": str(e)}

        return checks

    def list_credentials(self) -> List[Dict[str, Any]]:
        """List global credentials. Never returns secret values."""
        script = """
import com.cloudbees.plugins.credentials.CredentialsProvider
import com.cloudbees.plugins.credentials.common.StandardCredentials

def creds = CredentialsProvider.lookupCredentials(StandardCredentials.class, Jenkins.instance, null, null)
creds.each { c ->
    def user = c.metaClass.respondsTo(c, 'getUsername') ? c.username : '-'
    println "CRED|" + c.id + "|" + user + "|" + c.class.simpleName
}
"""
        output = self.execute_groovy(script)
        result = []
        for line in output.splitlines():
            if line.startswith("CRED|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    result.append({"id": parts[1], "username_or_secret": parts[2], "type": parts[3]})
        return result

    def create_credential(
        self,
        cred_id: str,
        kind: str,
        username: Optional[str] = None,
        secret: Optional[str] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        cred_id_esc = _groovy_escape(cred_id)
        desc_esc = _groovy_escape(description)
        secret_esc = _groovy_escape(secret or "")
        if kind == "userpass":
            username_esc = _groovy_escape(username or "")
            script = f"""
import com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl
import com.cloudbees.plugins.credentials.CredentialsScope
import com.cloudbees.plugins.credentials.SystemCredentialsProvider
import com.cloudbees.plugins.credentials.domains.Domain

def store = SystemCredentialsProvider.getInstance().getStore()
def cred = new UsernamePasswordCredentialsImpl(CredentialsScope.GLOBAL, '{cred_id_esc}', '{desc_esc}', '{username_esc}', '{secret_esc}')
store.addCredentials(Domain.global(), cred)
println 'CREATED'
"""
        elif kind in ("secret_text", "string"):
            script = f"""
import org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl
import com.cloudbees.plugins.credentials.CredentialsScope
import com.cloudbees.plugins.credentials.SystemCredentialsProvider
import com.cloudbees.plugins.credentials.domains.Domain
import hudson.util.Secret

def store = SystemCredentialsProvider.getInstance().getStore()
def cred = new StringCredentialsImpl(CredentialsScope.GLOBAL, '{cred_id_esc}', '{desc_esc}', Secret.fromString('{secret_esc}'))
store.addCredentials(Domain.global(), cred)
println 'CREATED'
"""
        else:
            raise ValueError(f"Unknown credential kind '{kind}'. Expected 'userpass' or 'secret_text'.")
        output = self.execute_groovy(script)
        return {"id": cred_id, "created": "CREATED" in output}

    def delete_credential(self, cred_id: str) -> Dict[str, Any]:
        cred_id_esc = _groovy_escape(cred_id)
        script = f"""
import com.cloudbees.plugins.credentials.SystemCredentialsProvider
import com.cloudbees.plugins.credentials.CredentialsProvider
import com.cloudbees.plugins.credentials.Credentials
import com.cloudbees.plugins.credentials.domains.Domain

def store = SystemCredentialsProvider.getInstance().getStore()
def target = CredentialsProvider.lookupCredentials(Credentials.class, Jenkins.instance, null, null).find {{ it.id == '{cred_id_esc}' }}
if (target != null) {{
    store.removeCredentials(Domain.global(), target)
    println 'DELETED'
}} else {{
    println 'NOT_FOUND'
}}
"""
        output = self.execute_groovy(script)
        return {"id": cred_id, "deleted": "DELETED" in output}

    def list_plugins(self, search: str = "") -> List[Dict[str, Any]]:
        req = urllib.request.Request(f"{self.url}/pluginManager/api/json?depth=1")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        plugins = [
            {
                "shortName": p.get("shortName"),
                "version": p.get("version"),
                "enabled": p.get("enabled"),
                "hasUpdate": p.get("hasUpdate"),
            }
            for p in data.get("plugins", [])
        ]
        if search:
            term = search.lower()
            plugins = [p for p in plugins if term in (p.get("shortName") or "").lower()]
        return plugins

    def install_plugin(self, short_name: str) -> Dict[str, Any]:
        body = f'<jenkins><install plugin="{short_name}@current"/></jenkins>'.encode('utf-8')
        headers = self._crumb_headers()
        req = urllib.request.Request(f"{self.url}/pluginManager/installNecessaryPlugins", data=body, method='POST')
        req.add_header("Authorization", self._get_auth_header())
        req.add_header("Content-Type", "text/xml")
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return {"plugin": short_name, "requested": True}

    def rerun_build(self, job_name: str, build: str = "lastBuild") -> Dict[str, Any]:
        """Re-trigger a job using the same build parameters as a previous build."""
        quoted = urllib.parse.quote(job_name)
        req = urllib.request.Request(f"{self.url}/job/{quoted}/{build}/api/json?tree=actions[parameters[name,value]]")
        req.add_header("Authorization", self._get_auth_header())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        params: Dict[str, Any] = {}
        for action in data.get("actions", []):
            for p in (action.get("parameters") or []):
                name = p.get("name")
                if name is not None:
                    params[name] = p.get("value")
        res = self.build_job(job_name, params=params or None)
        return {"job": job_name, "rerun_of": build, "queued": res.get("queued", False)}

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
