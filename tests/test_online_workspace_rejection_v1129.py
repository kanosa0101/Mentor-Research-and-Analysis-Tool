import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from crawler.online_workspace import Workspace
from scripts.serve_public import Handler


@pytest.mark.parametrize('path', ['/api/workflow/scan', '/api/workflow/materials'])
@pytest.mark.parametrize('state', ['small', 'already_read', 'oversized'])
def test_disabled_workspace_route_buffers_rejection_and_only_drains_unread_small_body(tmp_path, path, state):
    body = b'{"path":"disabled"}'
    content_length = 16385 if state == 'oversized' else len(body)
    unread = b'next request' if state == 'already_read' else body
    transport = SimpleNamespace(
        site=tmp_path / 'site', path=path, headers={'Content-Length': str(content_length)},
        rfile=io.BytesIO(unread), connection=Mock(), server=None, reply=Mock(),
        close_connection=False, _online_body_read=state == 'already_read',
    )
    transport.drain_small_body = lambda: Handler.drain_small_body(transport)
    workspace = Workspace(transport, tmp_path / 'workspace')

    workspace.handle('POST')

    assert workspace.response_code == 400
    assert transport.close_connection is True
    transport.reply.assert_not_called()
    if state == 'small':
        assert transport.rfile.tell() == len(body)
        transport.connection.settimeout.assert_called_once_with(1)
    else:
        assert transport.rfile.tell() == 0
        transport.connection.settimeout.assert_not_called()
    workspace.flush()
    code, payload, content_type, headers = transport.reply.call_args.args
    assert code == 400 and content_type == 'application/json; charset=utf-8'
    assert headers['Connection'] == 'close'
    assert json.loads(payload) == {'error': '请上传材料文件；在线服务不读取电脑或服务器目录'}
