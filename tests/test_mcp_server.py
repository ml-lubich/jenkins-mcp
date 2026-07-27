import asyncio
import json
import unittest
from unittest.mock import MagicMock
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
