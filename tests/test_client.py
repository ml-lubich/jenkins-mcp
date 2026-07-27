import unittest
from unittest.mock import patch, MagicMock
import json
import os
import urllib.error
from jenkins_mcp.client import (
    JenkinsClient,
    resolve_jenkins_config,
    _groovy_escape,
    list_contexts,
    add_context,
    use_context,
    current_context,
)

class TestJenkinsClient(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    def test_auth_header(self):
        header = self.client._get_auth_header()
        self.assertTrue(header.startswith("Basic "))

    def test_missing_credentials_raises(self):
        with self.assertRaises(ValueError):
            JenkinsClient(url="http://jenkins.test:8080")
        with self.assertRaises(ValueError):
            JenkinsClient(url="http://jenkins.test:8080", username="testuser")
        with self.assertRaises(ValueError):
            JenkinsClient(url="http://jenkins.test:8080", password="testpass")

    @patch("urllib.request.urlopen")
    def test_get_crumb(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"crumb": "test-crumb"}).encode('utf-8')
        mock_resp.info.return_value.get.return_value = "JSESSIONID=123"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        crumb, cookie = self.client.get_crumb()
        self.assertEqual(crumb, "test-crumb")
        self.assertEqual(cookie, "JSESSIONID=123")

    @patch("urllib.request.urlopen")
    def test_get_crumb_404_returns_none(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://jenkins.test:8080/crumbIssuer/api/json", 404, "Not Found", {}, None
        )
        crumb, cookie = self.client.get_crumb()
        self.assertIsNone(crumb)
        self.assertIsNone(cookie)

    @patch("urllib.request.urlopen")
    def test_get_crumb_other_error_propagates(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://jenkins.test:8080/crumbIssuer/api/json", 500, "Server Error", {}, None
        )
        with self.assertRaises(urllib.error.HTTPError):
            self.client.get_crumb()

    @patch("urllib.request.urlopen")
    def test_get_status(self, mock_urlopen):
        mock_resp = MagicMock()
        data = {
            "computer": [
                {
                    "displayName": "Built-In Node",
                    "offline": False,
                    "assignedLabels": [{"name": "built-in"}],
                    "numExecutors": 2
                },
                {
                    "displayName": "worker-01",
                    "offline": True,
                    "assignedLabels": [{"name": "worker"}],
                    "numExecutors": 2
                }
            ]
        }
        mock_resp.read.return_value = json.dumps(data).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.client.get_status()
        self.assertEqual(len(res["nodes"]), 2)
        self.assertEqual(res["nodes"][0]["name"], "Built-In Node")
        self.assertFalse(res["nodes"][0]["offline"])

    @patch.object(JenkinsClient, "execute_groovy")
    def test_add_node(self, mock_groovy):
        mock_groovy.return_value = "SUCCESS"
        res = self.client.add_node("worker-01", ip="192.0.2.1")
        self.assertTrue(res["success"])
        self.assertEqual(res["node_name"], "worker-01")
        mock_groovy.assert_called_once()

    @patch.object(JenkinsClient, "execute_groovy")
    def test_add_node_escapes_single_quote(self, mock_groovy):
        mock_groovy.return_value = "SUCCESS"
        self.client.add_node("o'brien-node")
        script = mock_groovy.call_args[0][0]
        self.assertIn("o\\'brien-node", script)
        self.assertNotIn("'o'brien-node'", script)

    @patch.object(JenkinsClient, "execute_groovy")
    def test_remove_node(self, mock_groovy):
        mock_groovy.return_value = "REMOVED"
        res = self.client.remove_node("worker-01")
        self.assertTrue(res["success"])
        self.assertEqual(res["node_name"], "worker-01")

    @patch.object(JenkinsClient, "execute_groovy")
    def test_create_user(self, mock_groovy):
        mock_groovy.return_value = "USER_CREATED"
        res = self.client.create_user("testuser2", "pass123")
        self.assertTrue(res["success"])
        self.assertEqual(res["username"], "testuser2")

    @patch.object(JenkinsClient, "execute_groovy")
    def test_set_default_git_tool_jgit_ok(self, mock_groovy):
        mock_groovy.return_value = (
            "GITTOOL_BEFORE=[Default]\n"
            "GITTOOL_ARRAYTYPE=[Lhudson.plugins.git.GitTool;\n"
            "GITTOOL_DEFAULT=JGitTool:jgit\n"
            "GITTOOL_AFTER=[JGitTool:jgit]\n"
        )
        res = self.client.set_default_git_tool_jgit()
        self.assertTrue(res["ok"])
        self.assertIn("JGitTool", res["output"])

    @patch.object(JenkinsClient, "execute_groovy")
    def test_set_default_git_tool_jgit_not_ok(self, mock_groovy):
        mock_groovy.return_value = "some unexpected error\n"
        res = self.client.set_default_git_tool_jgit()
        self.assertFalse(res["ok"])

    @patch.object(JenkinsClient, "execute_groovy")
    def test_build_job_queued(self, mock_groovy):
        mock_groovy.return_value = "QUEUED=true\n"
        res = self.client.build_job("myjob")
        self.assertEqual(res["job"], "myjob")
        self.assertTrue(res["queued"])

    @patch.object(JenkinsClient, "execute_groovy")
    def test_build_job_not_queued(self, mock_groovy):
        mock_groovy.return_value = "QUEUED=false\n"
        res = self.client.build_job("myjob")
        self.assertFalse(res["queued"])

    @patch.object(JenkinsClient, "execute_groovy")
    def test_get_job_result_parses_fields(self, mock_groovy):
        mock_groovy.return_value = "NUM=6\nBUILDING=false\nRESULT=SUCCESS\n"
        res = self.client.get_job_result("myjob")
        self.assertEqual(res["number"], 6)
        self.assertFalse(res["building"])
        self.assertEqual(res["result"], "SUCCESS")

    @patch.object(JenkinsClient, "execute_groovy")
    def test_get_job_result_building(self, mock_groovy):
        mock_groovy.return_value = "NUM=6\nBUILDING=true\nRESULT=null\n"
        res = self.client.get_job_result("myjob")
        self.assertEqual(res["number"], 6)
        self.assertTrue(res["building"])
        self.assertIsNone(res["result"])

    @patch.object(JenkinsClient, "execute_groovy")
    def test_get_job_result_nobuild(self, mock_groovy):
        mock_groovy.return_value = "NOBUILD\n"
        res = self.client.get_job_result("myjob")
        self.assertIsNone(res["number"])
        self.assertFalse(res["building"])
        self.assertIsNone(res["result"])

    @patch("time.sleep", return_value=None)
    @patch.object(JenkinsClient, "build_job")
    @patch.object(JenkinsClient, "get_job_result")
    def test_wait_job_detects_new_build_then_success(self, mock_result, mock_build, mock_sleep):
        mock_result.side_effect = [
            {"job": "myjob", "number": 5, "building": False, "result": "SUCCESS"},
            {"job": "myjob", "number": 6, "building": True, "result": None},
            {"job": "myjob", "number": 6, "building": False, "result": "SUCCESS"},
        ]
        res = self.client.wait_job("myjob", timeout=300, poll=6)
        self.assertEqual(res["job"], "myjob")
        self.assertEqual(res["number"], 6)
        self.assertEqual(res["result"], "SUCCESS")
        self.assertFalse(res["timed_out"])
        mock_build.assert_called_once_with("myjob")

    @patch("urllib.request.urlopen")
    def test_get_build_log_tail(self, mock_urlopen):
        mock_resp = MagicMock()
        text = "\n".join(f"line{i}" for i in range(1, 51))
        mock_resp.read.return_value = text.encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        tail = self.client.get_build_log_tail("myjob", lines=5)
        self.assertEqual(tail, "\n".join(f"line{i}" for i in range(46, 51)))

    @patch("urllib.request.urlopen")
    def test_list_jobs(self, mock_urlopen):
        mock_resp = MagicMock()
        data = {
            "jobs": [
                {"name": "development", "url": "http://jenkins.test:8080/job/development/", "color": "blue"},
                {"name": "test-sbm", "url": "http://jenkins.test:8080/job/test-sbm/", "color": "red"}
            ]
        }
        mock_resp.read.return_value = json.dumps(data).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        jobs = self.client.list_jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["name"], "development")


class TestGroovyEscape(unittest.TestCase):
    def test_escapes_single_quote(self):
        self.assertEqual(_groovy_escape("o'brien"), "o\\'brien")

    def test_escapes_backslash(self):
        self.assertEqual(_groovy_escape("a\\b"), "a\\\\b")


class TestConfigResolution(unittest.TestCase):
    def test_explicit_args_win(self):
        url, user, pw = resolve_jenkins_config(
            url="http://explicit:8080", username="explicituser", password="explicitpass"
        )
        self.assertEqual(url, "http://explicit:8080")
        self.assertEqual(user, "explicituser")
        self.assertEqual(pw, "explicitpass")

    def test_env_used_when_no_args(self, ):
        env = {
            "JENKINS_URL": "http://env.test:8080",
            "JENKINS_USER": "envuser",
            "JENKINS_PASSWORD": "envpass",
        }
        with patch.dict(os.environ, env, clear=True):
            url, user, pw = resolve_jenkins_config()
        self.assertEqual(url, "http://env.test:8080")
        self.assertEqual(user, "envuser")
        self.assertEqual(pw, "envpass")

    def test_env_overrides_config_file(self):
        with self._tmp_config_home({"url": "http://file.test:8080", "username": "fileuser", "password": "filepass"}) as home:
            env = {"HOME": home, "JENKINS_USER": "envuser", "JENKINS_PASSWORD": "envpass"}
            with patch.dict(os.environ, env, clear=True):
                url, user, pw = resolve_jenkins_config()
        self.assertEqual(user, "envuser")
        self.assertEqual(pw, "envpass")

    def test_config_file_used_when_no_env(self):
        with self._tmp_config_home({"url": "http://file.test:8080", "username": "fileuser", "password": "filepass"}) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                url, user, pw = resolve_jenkins_config()
        self.assertEqual(url, "http://file.test:8080")
        self.assertEqual(user, "fileuser")
        self.assertEqual(pw, "filepass")

    def test_missing_credentials_raises_helpful_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                with self.assertRaises(ValueError) as cm:
                    resolve_jenkins_config()
        self.assertIn("JENKINS_USER", str(cm.exception))

    def test_non_dict_config_file_is_ignored(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as home:
            config_dir = Path(home) / ".config" / "jenkins-mcp"
            config_dir.mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps(["not", "a", "dict"]))
            env = {"HOME": home, "JENKINS_USER": "envuser", "JENKINS_PASSWORD": "envpass"}
            with patch.dict(os.environ, env, clear=True):
                url, user, pw = resolve_jenkins_config()
        self.assertEqual(user, "envuser")
        self.assertEqual(pw, "envpass")

    def _tmp_config_home(self, config_dict):
        import tempfile
        import contextlib
        from pathlib import Path

        @contextlib.contextmanager
        def _ctx():
            with tempfile.TemporaryDirectory() as tmp:
                config_dir = Path(tmp) / ".config" / "jenkins-mcp"
                config_dir.mkdir(parents=True)
                (config_dir / "config.json").write_text(json.dumps(config_dict))
                yield tmp

        return _ctx()


class TestBuildLifecycle(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch.object(JenkinsClient, "execute_groovy")
    def test_build_job_with_params_generates_parameters_action(self, mock_groovy):
        mock_groovy.return_value = "QUEUED=true\n"
        res = self.client.build_job("myjob", params={"BRANCH": "main", "FLAG": "true"})
        self.assertTrue(res["queued"])
        script = mock_groovy.call_args[0][0]
        self.assertIn("ParametersAction", script)
        self.assertIn("StringParameterValue('BRANCH', 'main')", script)
        self.assertIn("StringParameterValue('FLAG', 'true')", script)

    @patch.object(JenkinsClient, "execute_groovy")
    def test_build_job_without_params_omits_parameters_action(self, mock_groovy):
        mock_groovy.return_value = "QUEUED=true\n"
        self.client.build_job("myjob")
        script = mock_groovy.call_args[0][0]
        self.assertNotIn("ParametersAction", script)

    @patch("time.sleep", return_value=None)
    @patch.object(JenkinsClient, "get_pending_input")
    @patch.object(JenkinsClient, "build_job")
    @patch.object(JenkinsClient, "get_job_result")
    def test_watch_job_success(self, mock_result, mock_build, mock_pending, mock_sleep):
        mock_result.side_effect = [
            {"job": "myjob", "number": 5, "building": False, "result": "SUCCESS"},
            {"job": "myjob", "number": 6, "building": False, "result": "SUCCESS"},
        ]
        res = self.client.watch_job("myjob", timeout=300, poll=6)
        self.assertEqual(res["number"], 6)
        self.assertEqual(res["result"], "SUCCESS")
        self.assertIsNone(res["pending_input"])
        self.assertFalse(res["timed_out"])
        mock_pending.assert_not_called()

    @patch("time.sleep", return_value=None)
    @patch.object(JenkinsClient, "get_pending_input")
    @patch.object(JenkinsClient, "build_job")
    @patch.object(JenkinsClient, "get_job_result")
    def test_watch_job_detects_pending_input(self, mock_result, mock_build, mock_pending, mock_sleep):
        mock_result.side_effect = [
            {"job": "myjob", "number": 5, "building": False, "result": "SUCCESS"},
            {"job": "myjob", "number": 6, "building": True, "result": None},
        ]
        mock_pending.return_value = {"id": "in1", "message": "Deploy?", "ok": "Proceed", "parameters": []}
        res = self.client.watch_job("myjob", timeout=300, poll=6)
        self.assertEqual(res["pending_input"]["id"], "in1")
        self.assertFalse(res["timed_out"])

    @patch("urllib.request.urlopen")
    @patch.object(JenkinsClient, "get_crumb", return_value=(None, None))
    def test_cancel_build_posts_stop(self, mock_crumb, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.client.cancel_build("myjob", build="6")
        self.assertTrue(res["stopped"])
        req = mock_urlopen.call_args[0][0]
        self.assertIn("/job/myjob/6/stop", req.full_url)
        self.assertEqual(req.get_method(), "POST")

    @patch("time.sleep", return_value=None)
    @patch.object(JenkinsClient, "get_job_result")
    @patch("urllib.request.urlopen")
    @patch.object(JenkinsClient, "get_crumb", return_value=(None, None))
    def test_cancel_build_wait_polls_until_terminal(self, mock_crumb, mock_urlopen, mock_result, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp
        mock_result.side_effect = [
            {"job": "myjob", "number": 6, "building": True, "result": None},
            {"job": "myjob", "number": 6, "building": False, "result": "ABORTED"},
        ]
        res = self.client.cancel_build("myjob", wait=True, poll=1)
        self.assertEqual(res["result"], "ABORTED")
        self.assertFalse(res["timed_out"])


class TestPipelineInfo(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch("urllib.request.urlopen")
    def test_get_pipeline_info_parses_stages(self, mock_urlopen):
        data = {
            "name": "myjob #6",
            "status": "IN_PROGRESS",
            "stages": [
                {"id": "1", "name": "Build", "status": "SUCCESS", "durationMillis": 1200},
                {"id": "2", "name": "Deploy", "status": "PAUSED_PENDING_INPUT", "durationMillis": 0},
            ],
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        info = self.client.get_pipeline_info("myjob", build="6")
        self.assertEqual(len(info["stages"]), 2)
        self.assertTrue(info["pendingInput"])
        self.assertEqual(info["stages"][0]["name"], "Build")

    @patch("urllib.request.urlopen")
    def test_get_pipeline_info_404_raises_value_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://jenkins.test:8080/job/myjob/lastBuild/wfapi/describe", 404, "Not Found", {}, None
        )
        with self.assertRaises(ValueError):
            self.client.get_pipeline_info("myjob")


class TestBuildLog(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch("urllib.request.urlopen")
    def test_get_build_log_parses_headers(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"hello world"
        mock_resp.info.return_value = {"X-Text-Size": "128", "X-More-Data": "true"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        text, next_start, more = self.client.get_build_log("myjob", start=0)
        self.assertEqual(text, "hello world")
        self.assertEqual(next_start, 128)
        self.assertTrue(more)

    @patch("urllib.request.urlopen")
    def test_get_build_log_no_more_data(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"done"
        mock_resp.info.return_value = {"X-Text-Size": "200"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        _, _, more = self.client.get_build_log("myjob", start=196)
        self.assertFalse(more)


class TestPendingInput(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch("urllib.request.urlopen")
    def test_get_pending_input_returns_first_action(self, mock_urlopen):
        data = [{"id": "in1", "message": "Deploy to prod?", "proceedText": "Proceed", "inputs": [{"name": "TARGET"}]}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        pending = self.client.get_pending_input("myjob")
        self.assertEqual(pending["id"], "in1")
        self.assertEqual(pending["message"], "Deploy to prod?")

    @patch("urllib.request.urlopen")
    def test_get_pending_input_empty_returns_none(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"[]"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        self.assertIsNone(self.client.get_pending_input("myjob"))

    @patch("urllib.request.urlopen")
    def test_get_pending_input_404_returns_none(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://jenkins.test:8080/job/myjob/lastBuild/wfapi/pendingInputActions", 404, "Not Found", {}, None
        )
        self.assertIsNone(self.client.get_pending_input("myjob"))

    @patch("urllib.request.urlopen")
    @patch.object(JenkinsClient, "get_crumb", return_value=(None, None))
    def test_submit_input_proceed(self, mock_crumb, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.client.submit_input("myjob", "6", "in1", action="proceed")
        self.assertTrue(res["ok"])
        req = mock_urlopen.call_args[0][0]
        self.assertIn("/input/in1/proceedEmpty", req.full_url)

    @patch("urllib.request.urlopen")
    @patch.object(JenkinsClient, "get_crumb", return_value=(None, None))
    def test_submit_input_abort(self, mock_crumb, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        self.client.submit_input("myjob", "6", "in1", action="abort")
        req = mock_urlopen.call_args[0][0]
        self.assertIn("/input/in1/abort", req.full_url)

    @patch("urllib.request.urlopen")
    @patch.object(JenkinsClient, "get_crumb", return_value=(None, None))
    def test_submit_input_with_params_uses_submit_endpoint(self, mock_crumb, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        self.client.submit_input("myjob", "6", "in1", action="proceed", params={"TARGET": "prod"})
        req = mock_urlopen.call_args[0][0]
        self.assertIn("/input/in1/submit", req.full_url)


class TestArtifacts(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch("urllib.request.urlopen")
    def test_list_artifacts(self, mock_urlopen):
        data = {"artifacts": [{"fileName": "app.jar", "relativePath": "build/app.jar"}]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        artifacts = self.client.list_artifacts("myjob")
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["relativePath"], "build/app.jar")

    @patch("urllib.request.urlopen")
    def test_download_artifact_writes_file(self, mock_urlopen):
        import tempfile
        from pathlib import Path

        mock_resp = MagicMock()
        mock_resp.read.return_value = b"binary-content"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        with tempfile.TemporaryDirectory() as out_dir:
            path = self.client.download_artifact("myjob", "6", "build/app.jar", out_dir)
            self.assertEqual(Path(path).read_bytes(), b"binary-content")
            self.assertEqual(Path(path).name, "app.jar")


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch("urllib.request.urlopen")
    def test_queue_list(self, mock_urlopen):
        data = {"items": [{"id": 42, "task": {"name": "myjob"}, "why": "waiting", "stuck": False}]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        items = self.client.queue_list()
        self.assertEqual(items[0]["id"], 42)
        self.assertEqual(items[0]["task"], "myjob")

    @patch("urllib.request.urlopen")
    @patch.object(JenkinsClient, "get_crumb", return_value=(None, None))
    def test_queue_cancel(self, mock_crumb, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.client.queue_cancel(42)
        self.assertTrue(res["cancelled"])
        req = mock_urlopen.call_args[0][0]
        self.assertIn("cancelItem?id=42", req.full_url)


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch.object(JenkinsClient, "get_crumb", return_value=("crumb123", None))
    @patch("urllib.request.urlopen")
    def test_doctor_all_ok(self, mock_urlopen, mock_crumb):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_resp.info.return_value = {"X-Jenkins": "2.400"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        checks = self.client.doctor()
        self.assertTrue(checks["reachable"]["ok"])
        self.assertTrue(checks["auth"]["ok"])
        self.assertTrue(checks["version"]["ok"])
        self.assertTrue(checks["crumb"]["ok"])

    @patch("urllib.request.urlopen")
    def test_doctor_auth_failure_never_raises(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://jenkins.test:8080/api/json", 401, "Unauthorized", {}, None
        )
        checks = self.client.doctor()
        self.assertTrue(checks["reachable"]["ok"])
        self.assertFalse(checks["auth"]["ok"])

    @patch("urllib.request.urlopen")
    def test_doctor_unreachable_never_raises(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("connection refused")
        checks = self.client.doctor()
        self.assertFalse(checks["reachable"]["ok"])
        self.assertFalse(checks["auth"]["ok"])


class TestCredentials(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch.object(JenkinsClient, "execute_groovy")
    def test_list_credentials_parses_lines(self, mock_groovy):
        mock_groovy.return_value = "CRED|deploy-key|deployer|UsernamePasswordCredentialsImpl\nCRED|token1|-|StringCredentialsImpl\n"
        creds = self.client.list_credentials()
        self.assertEqual(len(creds), 2)
        self.assertEqual(creds[0]["id"], "deploy-key")
        self.assertEqual(creds[0]["username_or_secret"], "deployer")
        self.assertEqual(creds[1]["username_or_secret"], "-")

    @patch.object(JenkinsClient, "execute_groovy")
    def test_create_credential_userpass(self, mock_groovy):
        mock_groovy.return_value = "CREATED"
        res = self.client.create_credential("deploy-key", "userpass", username="deployer", secret="s3cret")
        self.assertTrue(res["created"])
        script = mock_groovy.call_args[0][0]
        self.assertIn("UsernamePasswordCredentialsImpl", script)
        self.assertIn("'deployer'", script)

    @patch.object(JenkinsClient, "execute_groovy")
    def test_create_credential_secret_text(self, mock_groovy):
        mock_groovy.return_value = "CREATED"
        res = self.client.create_credential("token1", "secret_text", secret="s3cret")
        self.assertTrue(res["created"])
        script = mock_groovy.call_args[0][0]
        self.assertIn("StringCredentialsImpl", script)

    def test_create_credential_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            self.client.create_credential("x", "bogus")

    @patch.object(JenkinsClient, "execute_groovy")
    def test_delete_credential(self, mock_groovy):
        mock_groovy.return_value = "DELETED"
        res = self.client.delete_credential("deploy-key")
        self.assertTrue(res["deleted"])


class TestPlugins(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch("urllib.request.urlopen")
    def test_list_plugins_filters_by_search(self, mock_urlopen):
        data = {
            "plugins": [
                {"shortName": "git", "version": "5.0", "enabled": True, "hasUpdate": False},
                {"shortName": "workflow-job", "version": "1.0", "enabled": True, "hasUpdate": True},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        plugins = self.client.list_plugins(search="workflow")
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["shortName"], "workflow-job")

    @patch("urllib.request.urlopen")
    @patch.object(JenkinsClient, "get_crumb", return_value=(None, None))
    def test_install_plugin_posts_xml(self, mock_crumb, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.client.install_plugin("git")
        self.assertTrue(res["requested"])
        req = mock_urlopen.call_args[0][0]
        self.assertIn("installNecessaryPlugins", req.full_url)
        self.assertIn(b'plugin="git@current"', req.data)


class TestRerunBuild(unittest.TestCase):
    def setUp(self):
        self.client = JenkinsClient("http://jenkins.test:8080", "testuser", "testpass")

    @patch.object(JenkinsClient, "build_job")
    @patch("urllib.request.urlopen")
    def test_rerun_build_copies_params(self, mock_urlopen, mock_build):
        data = {"actions": [{"parameters": [{"name": "BRANCH", "value": "main"}]}]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp
        mock_build.return_value = {"job": "myjob", "queued": True, "output": "QUEUED=true\n"}

        res = self.client.rerun_build("myjob", build="6")
        self.assertTrue(res["queued"])
        self.assertEqual(res["rerun_of"], "6")
        mock_build.assert_called_once_with("myjob", params={"BRANCH": "main"})


class TestMultiContext(unittest.TestCase):
    def _tmp_config_home(self, config_dict):
        import tempfile
        import contextlib
        from pathlib import Path

        @contextlib.contextmanager
        def _ctx():
            with tempfile.TemporaryDirectory() as tmp:
                config_dir = Path(tmp) / ".config" / "jenkins-mcp"
                config_dir.mkdir(parents=True)
                (config_dir / "config.json").write_text(json.dumps(config_dict))
                yield tmp

        return _ctx()

    def test_explicit_context_wins_over_default(self):
        config = {
            "default_context": "staging",
            "contexts": {
                "staging": {"url": "http://staging:8080", "username": "s", "password": "sp"},
                "prod": {"url": "http://prod:8080", "username": "p", "password": "pp"},
            },
        }
        with self._tmp_config_home(config) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                url, user, pw = resolve_jenkins_config(context="prod")
        self.assertEqual(url, "http://prod:8080")
        self.assertEqual(user, "p")

    def test_env_context_used_when_no_explicit_context(self):
        config = {"contexts": {"prod": {"url": "http://prod:8080", "username": "p", "password": "pp"}}}
        with self._tmp_config_home(config) as home:
            env = {"HOME": home, "JENKINS_CONTEXT": "prod"}
            with patch.dict(os.environ, env, clear=True):
                url, user, pw = resolve_jenkins_config()
        self.assertEqual(url, "http://prod:8080")

    def test_default_context_used_when_nothing_else_specified(self):
        config = {
            "default_context": "prod",
            "contexts": {"prod": {"url": "http://prod:8080", "username": "p", "password": "pp"}},
        }
        with self._tmp_config_home(config) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                url, user, pw = resolve_jenkins_config()
        self.assertEqual(url, "http://prod:8080")

    def test_unknown_context_raises(self):
        config = {"contexts": {"prod": {"url": "http://prod:8080", "username": "p", "password": "pp"}}}
        with self._tmp_config_home(config) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                with self.assertRaises(ValueError):
                    resolve_jenkins_config(context="staging")

    def test_list_contexts_marks_default_and_hides_passwords(self):
        config = {
            "default_context": "prod",
            "contexts": {
                "prod": {"url": "http://prod:8080", "username": "p", "password": "secret"},
                "staging": {"url": "http://staging:8080", "username": "s", "password": "secret2"},
            },
        }
        with self._tmp_config_home(config) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                contexts = list_contexts()
        by_name = {c["name"]: c for c in contexts}
        self.assertTrue(by_name["prod"]["default"])
        self.assertFalse(by_name["staging"]["default"])
        for c in contexts:
            self.assertNotIn("password", c)

    def test_add_context_then_use_then_current(self):
        with self._tmp_config_home({}) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                add_context("prod", "http://prod:8080", "p", "secretpw")
                use_context("prod")
                current = current_context()
        self.assertEqual(current["name"], "prod")
        self.assertEqual(current["url"], "http://prod:8080")

    def test_use_unknown_context_raises(self):
        with self._tmp_config_home({}) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                with self.assertRaises(ValueError):
                    use_context("nope")

    def test_current_context_with_no_default(self):
        with self._tmp_config_home({"url": "http://legacy:8080"}) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                current = current_context()
        self.assertIsNone(current["name"])
        self.assertEqual(current["url"], "http://legacy:8080")


if __name__ == "__main__":
    unittest.main()
