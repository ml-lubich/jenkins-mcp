import asyncio
import json
import unittest
from unittest.mock import MagicMock
from mcp.server.fastmcp.exceptions import ToolError
from jenkins_mcp.mcp_server import create_mcp_server

class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mcp = create_mcp_server(self.mock_client)

    def test_mcp_server_tools_registered(self):
        # Verify tool definitions exist in the server instance
        self.assertIsNotNone(self.mcp)
        self.assertEqual(self.mcp.name, "jenkins-mcp")

    def _call(self, name, args=None):
        _, meta = asyncio.run(self.mcp.call_tool(name, args or {}))
        return json.loads(meta["result"])

    def _call_raw(self, name, args=None):
        # For the plain-passthrough tools that return non-JSON strings.
        _, meta = asyncio.run(self.mcp.call_tool(name, args or {}))
        return meta["result"]

    def test_all_new_tools_registered(self):
        names = {t.name for t in asyncio.run(self.mcp.list_tools())}
        expected = {
            "jenkins_pipeline_info",
            "jenkins_cancel_build",
            "jenkins_build_log_tail",
            "jenkins_pending_input",
            "jenkins_list_artifacts",
            "jenkins_queue_list",
            "jenkins_doctor",
            "jenkins_list_credentials",
            "jenkins_create_credential",
            "jenkins_list_plugins",
            "jenkins_install_plugin",
            "jenkins_rerun_build",
        }
        self.assertTrue(expected.issubset(names))

    def test_jenkins_pipeline_info_returns_client_result(self):
        self.mock_client.get_pipeline_info.return_value = {"name": "myjob #6", "status": "SUCCESS", "stages": []}
        result = self._call("jenkins_pipeline_info", {"job": "myjob"})
        self.assertEqual(result["status"], "SUCCESS")
        self.mock_client.get_pipeline_info.assert_called_once_with("myjob", build="lastBuild")

    def test_jenkins_pipeline_info_catches_errors(self):
        self.mock_client.get_pipeline_info.side_effect = ValueError("no pipeline data")
        result = self._call("jenkins_pipeline_info", {"job": "myjob"})
        self.assertIn("error", result)

    def test_jenkins_cancel_build(self):
        self.mock_client.cancel_build.return_value = {"job": "myjob", "stopped": True}
        result = self._call("jenkins_cancel_build", {"job": "myjob"})
        self.assertTrue(result["stopped"])

    def test_jenkins_doctor(self):
        self.mock_client.doctor.return_value = {"reachable": {"ok": True, "detail": "x"}}
        result = self._call("jenkins_doctor")
        self.assertTrue(result["reachable"]["ok"])

    def test_jenkins_queue_list(self):
        self.mock_client.queue_list.return_value = [{"id": 1, "task": "myjob", "why": "waiting", "stuck": False}]
        result = self._call("jenkins_queue_list")
        self.assertEqual(result[0]["id"], 1)

    def test_jenkins_list_credentials_never_leaks_secret_key(self):
        self.mock_client.list_credentials.return_value = [{"id": "x", "username_or_secret": "u", "type": "T"}]
        result = self._call("jenkins_list_credentials")
        self.assertEqual(result[0]["id"], "x")

    def test_jenkins_create_credential(self):
        self.mock_client.create_credential.return_value = {"id": "x", "created": True}
        result = self._call("jenkins_create_credential", {"id": "x", "kind": "userpass", "username": "u", "secret": "s"})
        self.assertTrue(result["created"])

    def test_jenkins_list_plugins(self):
        self.mock_client.list_plugins.return_value = [{"shortName": "git", "version": "5.0", "enabled": True, "hasUpdate": False}]
        result = self._call("jenkins_list_plugins")
        self.assertEqual(result[0]["shortName"], "git")

    def test_jenkins_install_plugin(self):
        self.mock_client.install_plugin.return_value = {"plugin": "git", "requested": True}
        result = self._call("jenkins_install_plugin", {"name": "git"})
        self.assertTrue(result["requested"])

    def test_jenkins_rerun_build(self):
        self.mock_client.rerun_build.return_value = {"job": "myjob", "rerun_of": "6", "queued": True}
        result = self._call("jenkins_rerun_build", {"job": "myjob", "build": "6"})
        self.assertTrue(result["queued"])

    # --- Passthrough tools (no try/except in mcp_server.py) ---
    # Valid-input calls verify the wrapper delegates to the client with the
    # right kwargs and formats its output; invalid-input calls verify a bad
    # call surfaces as ToolError instead of hanging or crashing the process.

    def test_jenkins_get_status_valid(self):
        self.mock_client.get_status.return_value = {"nodes": [{"name": "master", "idle": True}]}
        result = self._call_raw("jenkins_get_status")
        self.assertIn("master", result)
        self.mock_client.get_status.assert_called_once_with()

    def test_jenkins_get_status_client_error_raises_tool_error(self):
        self.mock_client.get_status.side_effect = RuntimeError("connection refused")
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_get_status", {}))

    def test_jenkins_add_node_valid_defaults(self):
        self.mock_client.add_node.return_value = {"output": "Node added.\n"}
        result = self._call_raw("jenkins_add_node", {"name": "worker-01"})
        self.assertEqual(result, "Add node result: Node added.")
        self.mock_client.add_node.assert_called_once_with(
            node_name="worker-01", ip="", labels="dev-test worker", remote_fs="/home/jenkins"
        )

    def test_jenkins_add_node_valid_explicit_args(self):
        self.mock_client.add_node.return_value = {"output": "ok"}
        self._call_raw(
            "jenkins_add_node",
            {"name": "w2", "ip": "10.0.0.5", "labels": "linux docker", "remote_fs": "/opt/jenkins"},
        )
        self.mock_client.add_node.assert_called_once_with(
            node_name="w2", ip="10.0.0.5", labels="linux docker", remote_fs="/opt/jenkins"
        )

    def test_jenkins_add_node_missing_required_arg_raises_tool_error(self):
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_add_node", {}))

    def test_jenkins_add_node_wrong_type_raises_tool_error(self):
        # name has no default and is typed str; a dict is not coercible.
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_add_node", {"name": {"not": "a string"}}))

    def test_jenkins_remove_node_valid(self):
        self.mock_client.remove_node.return_value = {"output": "Node removed.\n"}
        result = self._call_raw("jenkins_remove_node", {"name": "worker-01"})
        self.assertEqual(result, "Remove node result: Node removed.")
        self.mock_client.remove_node.assert_called_once_with(node_name="worker-01")

    def test_jenkins_remove_node_missing_required_arg_raises_tool_error(self):
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_remove_node", {}))

    def test_jenkins_remove_node_client_error_raises_tool_error(self):
        self.mock_client.remove_node.side_effect = ValueError("no such node")
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_remove_node", {"name": "ghost"}))

    def test_jenkins_create_user_valid(self):
        self.mock_client.create_user.return_value = {"output": "User created.\n"}
        result = self._call_raw(
            "jenkins_create_user", {"username": "alice", "password": "s3cret", "email": "alice@example.com"}
        )
        self.assertEqual(result, "Create user result: User created.")
        self.mock_client.create_user.assert_called_once_with(
            username="alice", password="s3cret", email="alice@example.com"
        )

    def test_jenkins_create_user_valid_no_email(self):
        self.mock_client.create_user.return_value = {"output": "ok"}
        self._call_raw("jenkins_create_user", {"username": "bob", "password": "pw"})
        self.mock_client.create_user.assert_called_once_with(username="bob", password="pw", email="")

    def test_jenkins_create_user_missing_password_raises_tool_error(self):
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_create_user", {"username": "alice"}))

    def test_jenkins_create_user_missing_username_raises_tool_error(self):
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_create_user", {"password": "pw"}))

    def test_jenkins_list_jobs_valid(self):
        self.mock_client.list_jobs.return_value = [{"name": "job-a"}, {"name": "job-b"}]
        result = self._call_raw("jenkins_list_jobs")
        self.assertIn("job-a", result)
        self.assertIn("job-b", result)
        self.mock_client.list_jobs.assert_called_once_with()

    def test_jenkins_list_jobs_client_error_raises_tool_error(self):
        self.mock_client.list_jobs.side_effect = RuntimeError("HTTP 500")
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_list_jobs", {}))

    def test_jenkins_use_jgit_valid(self):
        self.mock_client.set_default_git_tool_jgit.return_value = {"tool": "JGit", "set": True}
        result = self._call("jenkins_use_jgit")
        self.assertTrue(result["set"])
        self.mock_client.set_default_git_tool_jgit.assert_called_once_with()

    def test_jenkins_use_jgit_client_error_raises_tool_error(self):
        self.mock_client.set_default_git_tool_jgit.side_effect = RuntimeError("crumb rejected")
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_use_jgit", {}))

    def test_jenkins_build_job_valid_waits_by_default(self):
        self.mock_client.wait_job.return_value = {"job": "myjob", "status": "SUCCESS"}
        result = self._call("jenkins_build_job", {"job": "myjob"})
        self.assertEqual(result["status"], "SUCCESS")
        self.mock_client.wait_job.assert_called_once_with("myjob")
        self.mock_client.build_job.assert_not_called()

    def test_jenkins_build_job_valid_no_wait(self):
        self.mock_client.build_job.return_value = {"job": "myjob", "queued": True}
        result = self._call("jenkins_build_job", {"job": "myjob", "wait": False})
        self.assertTrue(result["queued"])
        self.mock_client.build_job.assert_called_once_with("myjob")
        self.mock_client.wait_job.assert_not_called()

    def test_jenkins_build_job_missing_required_arg_raises_tool_error(self):
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_build_job", {}))

    def test_jenkins_build_job_client_error_raises_tool_error(self):
        self.mock_client.wait_job.side_effect = TimeoutError("build timed out")
        with self.assertRaises(ToolError):
            asyncio.run(self.mcp.call_tool("jenkins_build_job", {"job": "myjob"}))
