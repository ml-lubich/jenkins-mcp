import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json
import tempfile
from io import StringIO
from jenkins_mcp.cli import main

CREDS = ["--user", "testuser", "--password", "testpass"]

class TestCLI(unittest.TestCase):
    @patch("jenkins_mcp.client.JenkinsClient.get_status")
    def test_cli_status(self, mock_status):
        mock_status.return_value = {
            "nodes": [
                {"name": "Built-In Node", "offline": False, "labels": ["built-in"]}
            ]
        }
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "status"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("Built-In Node", output)

    @patch("jenkins_mcp.client.JenkinsClient.get_status")
    def test_cli_status_handles_missing_name_and_labels(self, mock_status):
        mock_status.return_value = {
            "nodes": [
                {"name": None, "offline": False, "labels": None}
            ]
        }
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "status"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("Node: ?", output)

    @patch("jenkins_mcp.client.JenkinsClient.add_node")
    def test_cli_node_add(self, mock_add):
        mock_add.return_value = {"output": "SUCCESS"}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "node", "add", "worker-01", "--ip", "192.0.2.1"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("Add Node 'worker-01'", output)
                mock_add.assert_called_once()

    @patch("jenkins_mcp.client.JenkinsClient.create_user")
    def test_cli_user_create(self, mock_create):
        mock_create.return_value = {"output": "USER_CREATED"}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "user", "create", "newuser", "secretpass"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("Create User 'newuser'", output)
                mock_create.assert_called_once()

    @patch("jenkins_mcp.client.JenkinsClient.set_default_git_tool_jgit")
    def test_cli_git_use_jgit_success(self, mock_jgit):
        mock_jgit.return_value = {"ok": True, "output": "GITTOOL_AFTER=[JGitTool:Default]\n"}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "git", "use-jgit"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("default git tool is now JGit", output)

    @patch("jenkins_mcp.client.JenkinsClient.set_default_git_tool_jgit")
    def test_cli_git_use_jgit_failure_exits_1(self, mock_jgit):
        mock_jgit.return_value = {"ok": False, "output": "unexpected\n"}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "git", "use-jgit"]):
            with patch("sys.stdout", new=StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)

    @patch("jenkins_mcp.client.JenkinsClient.build_job")
    def test_cli_job_build_no_wait(self, mock_build):
        mock_build.return_value = {"job": "myjob", "queued": True, "output": "QUEUED=true\n"}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "build", "myjob"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("queued: myjob", output)
                mock_build.assert_called_once()

    @patch("jenkins_mcp.client.JenkinsClient.get_build_log_tail")
    @patch("jenkins_mcp.client.JenkinsClient.wait_job")
    def test_cli_job_build_wait_success_exit_0(self, mock_wait, mock_tail):
        mock_wait.return_value = {"job": "myjob", "number": 6, "result": "SUCCESS", "waited": 6, "timed_out": False}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "build", "myjob", "--wait"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
                self.assertIn("myjob #6: SUCCESS", output)
                mock_tail.assert_not_called()

    @patch("jenkins_mcp.client.JenkinsClient.get_build_log_tail")
    @patch("jenkins_mcp.client.JenkinsClient.wait_job")
    def test_cli_job_build_wait_failure_exit_1_prints_tail(self, mock_wait, mock_tail):
        mock_wait.return_value = {"job": "myjob", "number": 6, "result": "FAILURE", "waited": 6, "timed_out": False}
        mock_tail.return_value = "console log tail here"
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "build", "myjob", "--wait"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                with self.assertRaises(SystemExit) as cm:
                    main()
                output = fake_out.getvalue()
                self.assertEqual(cm.exception.code, 1)
                self.assertIn("myjob #6: FAILURE", output)
                self.assertIn("console log tail here", output)

    def test_cli_missing_credentials_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            with patch.dict(os.environ, {"HOME": tmp_home}, clear=True):
                with patch.object(sys, "argv", ["jenkins-mcp", "status"]):
                    with patch("sys.stderr", new=StringIO()) as fake_err:
                        with self.assertRaises(SystemExit) as cm:
                            main()
                        self.assertEqual(cm.exception.code, 2)
                        self.assertIn("JENKINS_USER", fake_err.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.get_status")
    def test_cli_status_json_output_has_schema_version(self, mock_status):
        mock_status.return_value = {"nodes": []}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "-o", "json", "status"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                payload = json.loads(fake_out.getvalue())
        self.assertEqual(payload["schemaVersion"], "1")

    @patch("jenkins_mcp.client.JenkinsClient.list_jobs")
    def test_cli_jobs_search_fuzzy_filter(self, mock_list_jobs):
        mock_list_jobs.return_value = [
            {"name": "development", "url": "u1", "color": "blue"},
            {"name": "test-sbm", "url": "u2", "color": "red"},
        ]
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "jobs", "--search", "dev"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()
        self.assertIn("development", output)
        self.assertNotIn("test-sbm", output)

    @patch("jenkins_mcp.client.JenkinsClient.build_job")
    def test_cli_job_build_param_parsing(self, mock_build):
        mock_build.return_value = {"job": "myjob", "queued": True, "output": "QUEUED=true\n"}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "build", "myjob", "-p", "BRANCH=main", "-p", "FLAG=1"]):
            with patch("sys.stdout", new=StringIO()):
                main()
        mock_build.assert_called_once_with("myjob", params={"BRANCH": "main", "FLAG": "1"})

    def test_cli_job_build_invalid_param_exits_2(self):
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "build", "myjob", "-p", "BADPARAM"]):
            with patch("sys.stderr", new=StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 2)

    def _watch_case(self, result_dict, expected_exit):
        with patch("jenkins_mcp.client.JenkinsClient.watch_job", return_value=result_dict):
            with patch("jenkins_mcp.client.JenkinsClient.get_build_log_tail", return_value="tail"):
                with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "build", "myjob", "--watch"]):
                    with patch("sys.stdout", new=StringIO()):
                        with self.assertRaises(SystemExit) as cm:
                            main()
                        self.assertEqual(cm.exception.code, expected_exit)

    def test_cli_job_build_watch_success_exit_0(self):
        self._watch_case({"job": "myjob", "number": 6, "result": "SUCCESS", "pending_input": None, "waited": 6, "timed_out": False}, 0)

    def test_cli_job_build_watch_failure_exit_1(self):
        self._watch_case({"job": "myjob", "number": 6, "result": "FAILURE", "pending_input": None, "waited": 6, "timed_out": False}, 1)

    def test_cli_job_build_watch_unstable_exit_2(self):
        self._watch_case({"job": "myjob", "number": 6, "result": "UNSTABLE", "pending_input": None, "waited": 6, "timed_out": False}, 2)

    def test_cli_job_build_watch_aborted_exit_3(self):
        self._watch_case({"job": "myjob", "number": 6, "result": "ABORTED", "pending_input": None, "waited": 6, "timed_out": False}, 3)

    def test_cli_job_build_watch_pending_input_exit_4(self):
        self._watch_case({"job": "myjob", "number": 6, "result": None, "pending_input": {"id": "in1"}, "waited": 6, "timed_out": False}, 4)

    def test_cli_job_build_watch_error_exit_10(self):
        with patch("jenkins_mcp.client.JenkinsClient.watch_job", side_effect=RuntimeError("boom")):
            with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "build", "myjob", "--watch"]):
                with patch("sys.stderr", new=StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        main()
                    self.assertEqual(cm.exception.code, 10)

    @patch("jenkins_mcp.client.JenkinsClient.get_build_log_tail")
    def test_cli_job_log_default_tail(self, mock_tail):
        mock_tail.return_value = "line a\nline b"
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "log", "myjob"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("line a", fake_out.getvalue())

    @patch("time.sleep", return_value=None)
    @patch("jenkins_mcp.client.JenkinsClient.get_job_result")
    @patch("jenkins_mcp.client.JenkinsClient.get_build_log")
    def test_cli_job_log_follow_until_complete(self, mock_log, mock_result, mock_sleep):
        mock_log.side_effect = [
            ("partial output ", 14, True),
            ("more output", 25, False),
        ]
        mock_result.return_value = {"job": "myjob", "number": 6, "building": False, "result": "SUCCESS"}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "log", "myjob", "-f"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        output = fake_out.getvalue()
        self.assertIn("partial output", output)
        self.assertIn("more output", output)

    @patch("jenkins_mcp.client.JenkinsClient.cancel_build")
    def test_cli_build_cancel(self, mock_cancel):
        mock_cancel.return_value = {"job": "myjob", "build": "lastBuild", "stopped": True}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "build", "cancel", "myjob"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("stopped=True", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.cancel_build")
    def test_cli_build_cancel_wait_aborted_exit_3(self, mock_cancel):
        mock_cancel.return_value = {"job": "myjob", "build": "lastBuild", "stopped": True, "result": "ABORTED", "number": 6, "timed_out": False}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "build", "cancel", "myjob", "--wait"]):
            with patch("sys.stdout", new=StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 3)

    @patch("jenkins_mcp.client.JenkinsClient.submit_input")
    @patch("jenkins_mcp.client.JenkinsClient.get_pending_input")
    def test_cli_build_input_auto_detects_id(self, mock_pending, mock_submit):
        mock_pending.return_value = {"id": "in1", "message": "Deploy?", "ok": "Proceed", "parameters": []}
        mock_submit.return_value = {"job": "myjob", "build": "lastBuild", "input_id": "in1", "action": "proceed", "ok": True}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "build", "input", "myjob", "proceed"]):
            with patch("sys.stdout", new=StringIO()):
                main()
        mock_submit.assert_called_once_with("myjob", "lastBuild", "in1", action="proceed", params=None)

    @patch("jenkins_mcp.client.JenkinsClient.get_pending_input", return_value=None)
    def test_cli_build_input_no_pending_exits_2(self, mock_pending):
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "build", "input", "myjob", "proceed"]):
            with patch("sys.stderr", new=StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 2)

    @patch("jenkins_mcp.client.JenkinsClient.list_artifacts")
    def test_cli_build_artifacts(self, mock_list):
        mock_list.return_value = [{"fileName": "app.jar", "relativePath": "build/app.jar"}]
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "build", "artifacts", "myjob"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("build/app.jar", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.download_artifact")
    @patch("jenkins_mcp.client.JenkinsClient.list_artifacts")
    def test_cli_build_download_filters_by_pattern(self, mock_list, mock_download):
        mock_list.return_value = [
            {"fileName": "app.jar", "relativePath": "build/app.jar"},
            {"fileName": "notes.txt", "relativePath": "build/notes.txt"},
        ]
        mock_download.return_value = "/tmp/out/app.jar"
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "build", "download", "myjob", "--pattern", "*.jar"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        mock_download.assert_called_once_with("myjob", "lastBuild", "build/app.jar", ".")
        self.assertIn("/tmp/out/app.jar", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.get_pipeline_info")
    def test_cli_pipeline_info(self, mock_info):
        mock_info.return_value = {
            "name": "myjob #6",
            "status": "SUCCESS",
            "stages": [{"id": "1", "name": "Build", "status": "SUCCESS", "durationMillis": 1000}],
            "pendingInput": False,
        }
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "pipeline", "info", "myjob"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("Build", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.get_pipeline_info", side_effect=ValueError("no pipeline data"))
    def test_cli_pipeline_info_error_exits_1(self, mock_info):
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "pipeline", "info", "myjob"]):
            with patch("sys.stderr", new=StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)

    @patch("jenkins_mcp.client.JenkinsClient.queue_list")
    def test_cli_queue_list(self, mock_list):
        mock_list.return_value = [{"id": 42, "task": "myjob", "why": "waiting", "stuck": False}]
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "queue", "list"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("#42", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.queue_cancel")
    def test_cli_queue_cancel(self, mock_cancel):
        mock_cancel.return_value = {"id": 42, "cancelled": True}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "queue", "cancel", "42"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        mock_cancel.assert_called_once_with(42)
        self.assertIn("42", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.doctor")
    def test_cli_doctor_all_ok_exit_0(self, mock_doctor):
        mock_doctor.return_value = {"reachable": {"ok": True, "detail": "x"}}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "doctor"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("OK", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.doctor")
    def test_cli_doctor_failure_exits_1(self, mock_doctor):
        mock_doctor.return_value = {"reachable": {"ok": False, "detail": "unreachable"}}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "doctor"]):
            with patch("sys.stdout", new=StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)

    @patch("jenkins_mcp.client.JenkinsClient.list_credentials")
    def test_cli_credential_list_never_shows_secret(self, mock_list):
        mock_list.return_value = [{"id": "deploy-key", "username_or_secret": "deployer", "type": "UsernamePasswordCredentialsImpl"}]
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "credential", "list"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("deploy-key", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.create_credential")
    def test_cli_credential_create_userpass(self, mock_create):
        mock_create.return_value = {"id": "deploy-key", "created": True}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "credential", "create", "deploy-key", "--kind", "userpass", "--username", "d", "--secret", "s"]):
            with patch("sys.stdout", new=StringIO()):
                main()
        mock_create.assert_called_once_with("deploy-key", "userpass", username="d", secret="s", description="")

    @patch("jenkins_mcp.client.JenkinsClient.delete_credential")
    def test_cli_credential_delete(self, mock_delete):
        mock_delete.return_value = {"id": "deploy-key", "deleted": True}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "credential", "delete", "deploy-key"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("deleted=True", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.list_plugins")
    def test_cli_plugin_list_updates_filter(self, mock_list):
        mock_list.return_value = [
            {"shortName": "git", "version": "5.0", "enabled": True, "hasUpdate": False},
            {"shortName": "workflow-job", "version": "1.0", "enabled": True, "hasUpdate": True},
        ]
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "plugin", "list", "--updates"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        output = fake_out.getvalue()
        self.assertIn("workflow-job", output)
        self.assertNotIn("git 5.0", output)

    @patch("jenkins_mcp.client.JenkinsClient.install_plugin")
    def test_cli_plugin_install(self, mock_install):
        mock_install.return_value = {"plugin": "git", "requested": True}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "plugin", "install", "git"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        self.assertIn("git", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.rerun_build")
    def test_cli_job_rerun(self, mock_rerun):
        mock_rerun.return_value = {"job": "myjob", "rerun_of": "6", "queued": True}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "rerun", "myjob", "--build", "6"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
        mock_rerun.assert_called_once_with("myjob", build="6")
        self.assertIn("rerun queued", fake_out.getvalue())

    @patch("jenkins_mcp.client.JenkinsClient.watch_job")
    @patch("jenkins_mcp.client.JenkinsClient.rerun_build")
    def test_cli_job_rerun_watch_success_exit_0(self, mock_rerun, mock_watch):
        mock_rerun.return_value = {"job": "myjob", "rerun_of": "6", "queued": True}
        mock_watch.return_value = {"job": "myjob", "number": 7, "result": "SUCCESS", "pending_input": None, "waited": 6, "timed_out": False}
        with patch.object(sys, "argv", ["jenkins-mcp", *CREDS, "job", "rerun", "myjob", "--watch"]):
            with patch("sys.stdout", new=StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)


class TestContextCLI(unittest.TestCase):
    def _tmp_home(self, config_dict=None):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            with tempfile.TemporaryDirectory() as tmp:
                if config_dict is not None:
                    from pathlib import Path
                    config_dir = Path(tmp) / ".config" / "jenkins-mcp"
                    config_dir.mkdir(parents=True)
                    (config_dir / "config.json").write_text(json.dumps(config_dict))
                yield tmp

        return _ctx()

    def test_context_list_never_shows_password(self):
        config = {
            "default_context": "prod",
            "contexts": {"prod": {"url": "http://prod:8080", "username": "p", "password": "topsecret"}},
        }
        with self._tmp_home(config) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                with patch.object(sys, "argv", ["jenkins-mcp", "context", "list"]):
                    with patch("sys.stdout", new=StringIO()) as fake_out:
                        main()
        output = fake_out.getvalue()
        self.assertIn("prod", output)
        self.assertNotIn("topsecret", output)

    def test_context_add_then_use_then_current(self):
        with self._tmp_home({}) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                with patch.object(sys, "argv", ["jenkins-mcp", "context", "add", "prod", "--url", "http://prod:8080", "--user", "p", "--password", "secretpw"]):
                    with patch("sys.stdout", new=StringIO()):
                        main()
                with patch.object(sys, "argv", ["jenkins-mcp", "context", "use", "prod"]):
                    with patch("sys.stdout", new=StringIO()):
                        main()
                with patch.object(sys, "argv", ["jenkins-mcp", "context", "current"]):
                    with patch("sys.stdout", new=StringIO()) as fake_out:
                        main()
        self.assertIn("prod", fake_out.getvalue())
        self.assertNotIn("secretpw", fake_out.getvalue())

    def test_context_use_unknown_exits_2(self):
        with self._tmp_home({}) as home:
            with patch.dict(os.environ, {"HOME": home}, clear=True):
                with patch.object(sys, "argv", ["jenkins-mcp", "context", "use", "nope"]):
                    with patch("sys.stderr", new=StringIO()):
                        with self.assertRaises(SystemExit) as cm:
                            main()
                        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
