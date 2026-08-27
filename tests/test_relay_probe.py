import unittest
from unittest.mock import Mock, patch

from server.TESTAR_RELAY_LOCAL import RelayConnector


class RelayConnectorTests(unittest.TestCase):
    @patch("server.TESTAR_RELAY_LOCAL.socket.create_connection")
    def test_plain_lab_connection_remains_supported(self, create_connection):
        raw = Mock()
        create_connection.return_value = raw

        connector = RelayConnector("127.0.0.1", 45443)

        self.assertIs(connector.connect(), raw)
        create_connection.assert_called_once_with(("127.0.0.1", 45443), timeout=5)

    @patch("server.TESTAR_RELAY_LOCAL.ssl.create_default_context")
    @patch("server.TESTAR_RELAY_LOCAL.socket.create_connection")
    def test_tls_wraps_socket_with_expected_server_name(
        self, create_connection, create_default_context
    ):
        raw = Mock()
        wrapped = Mock()
        context = Mock()
        create_connection.return_value = raw
        create_default_context.return_value = context
        context.wrap_socket.return_value = wrapped

        connector = RelayConnector(
            "203.0.113.10",
            443,
            use_tls=True,
            server_name="relay.example.com",
            ca_file="relay-ca.crt",
        )

        self.assertIs(connector.connect(), wrapped)
        create_default_context.assert_called_once_with(cafile="relay-ca.crt")
        context.wrap_socket.assert_called_once_with(
            raw, server_hostname="relay.example.com"
        )


if __name__ == "__main__":
    unittest.main()
