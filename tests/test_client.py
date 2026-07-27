import unittest
from unittest.mock import patch, MagicMock
import json
import os
import urllib.error
from jenkins_mcp.client import JenkinsClient, resolve_jenkins_config, _groovy_escape

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


if __name__ == "__main__":
    unittest.main()
