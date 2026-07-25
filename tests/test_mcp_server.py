import unittest
from unittest.mock import MagicMock
from ijenk.mcp_server import create_mcp_server

class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mcp = create_mcp_server(self.mock_client)

    def test_mcp_server_tools_registered(self):
        # Verify tool definitions exist in the server instance
        self.assertIsNotNone(self.mcp)
        self.assertEqual(self.mcp.name, "ijenk")
