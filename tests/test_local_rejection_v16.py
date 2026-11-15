"""Early local API rejection sends a response without draining unbounded input."""
import unittest
from unittest.mock import Mock
from scripts.serve import Handler


class LocalRejectionTests(unittest.TestCase):
    def handler(self, length):
        handler = Handler.__new__(Handler)
        handler.headers = {'Content-Length': length}
        handler.connection = Mock()
        handler.rfile = Mock()
        handler._json = Mock()
        return handler

    def test_small_body_is_drained_before_forbidden_response(self):
        handler = self.handler('2')
        handler._reject_local(403, 'forbidden')
        handler.connection.settimeout.assert_called_once_with(1)
        handler.rfile.read.assert_called_once_with(2)
        handler._json.assert_called_once_with(403, {'error': 'forbidden'})
        self.assertTrue(handler.close_connection)

    def test_large_or_invalid_body_is_not_read(self):
        for length in ('16385', '-1', 'invalid'):
            handler = self.handler(length)
            handler._reject_local(415, 'json required')
            handler.rfile.read.assert_not_called()
            handler._json.assert_called_once_with(415, {'error': 'json required'})
            self.assertTrue(handler.close_connection)

    def test_stalled_small_body_still_rejects(self):
        handler = self.handler('2')
        handler.rfile.read.side_effect = TimeoutError()
        handler._reject_local(403, 'forbidden')
        handler._json.assert_called_once_with(403, {'error': 'forbidden'})
        self.assertTrue(handler.close_connection)
