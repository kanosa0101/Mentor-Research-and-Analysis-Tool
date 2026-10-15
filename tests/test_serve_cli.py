import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


class ServeCliTests(unittest.TestCase):
    def command(self, folder, port):
        return [sys.executable, '-u', str(ROOT / 'scripts/serve.py'),
                '--port', str(port), '--site', str(folder / 'site'),
                '--outreach', str(folder / 'outreach.yaml'),
                '--workflow', str(folder / 'workflow.yaml')]

    def test_cold_start_lists_current_entries_and_keeps_private_files_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            site = folder / 'site'
            site.mkdir()
            for name in ('discovery', 'desk', 'applications'):
                (site / (name + '.html')).write_text(name, encoding='utf-8')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            process = subprocess.Popen(self.command(folder, port), stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                       env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=.2) as response:
                            self.assertEqual(json.load(response), {'ok': True})
                        break
                    except OSError:
                        if process.poll() is not None:
                            self.fail('冷启动提前退出')
                        time.sleep(.05)
                else:
                    self.fail('冷启动超时')
                for name in ('discovery', 'desk', 'applications'):
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/{name}.html') as response:
                        self.assertEqual(response.read().decode(), name)
                self.assertFalse((folder / 'outreach.yaml').exists())
                self.assertFalse((folder / 'workflow.yaml').exists())
            finally:
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
            for name in ('discovery', 'desk', 'applications'):
                self.assertIn(f'http://127.0.0.1:{port}/{name}.html', stdout)
            self.assertNotIn('/board.html', stdout)
            self.assertNotIn('Traceback', stderr)

    def test_occupied_port_is_actionable_and_does_not_write_private_data(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket() as occupied:
            folder = Path(tmp)
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            result = subprocess.run(self.command(folder, port), capture_output=True, text=True,
                                    encoding='utf-8', timeout=15,
                                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            self.assertEqual(result.returncode, 1)
            self.assertIn('已被占用', result.stderr)
            self.assertIn('--port', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(list(folder.iterdir()), [])
