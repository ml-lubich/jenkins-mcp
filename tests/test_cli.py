import unittest
from unittest.mock import patch, MagicMock
import sys
import os
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

    def test_cli_missing_credentials_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            with patch.dict(os.environ, {"HOME": tmp_home}, clear=True):
                with patch.object(sys, "argv", ["jenkins-mcp", "status"]):
                    with patch("sys.stderr", new=StringIO()) as fake_err:
                        with self.assertRaises(SystemExit) as cm:
                            main()
                        self.assertEqual(cm.exception.code, 2)
                        self.assertIn("JENKINS_USER", fake_err.getvalue())


if __name__ == "__main__":
    unittest.main()
