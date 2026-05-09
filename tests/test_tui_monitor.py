from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import bluray_tui_monitor


class TuiMonitorDiagnosticsTests(unittest.TestCase):
    def _project_with_video(self) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        project = Path(td.name)
        (project / 'Main Feature.mp4').write_bytes(b'fake video')
        return project

    def test_preflight_warns_early_for_missing_tsmuxer_and_xorriso(self):
        project = self._project_with_video()
        with mock.patch.object(bluray_tui_monitor, 'tool_status', return_value={'ffmpeg': '/tmp/ffmpeg', 'ffprobe': '/tmp/ffprobe', 'tsMuxer': None, 'xorriso': None, 'nvidia': None}), \
             mock.patch.object(bluray_tui_monitor, 'pptx_menu_converter', None):
            issues = bluray_tui_monitor.project_diagnostics(project, project, cfg={'menu_backend': 'bdj'})

        messages = [(row['message'], row.get('fix', '')) for row in issues]
        self.assertTrue(any('tsMuxer is not available yet' in msg for msg, _ in messages))
        self.assertTrue(any('xorriso is not available yet' in msg for msg, _ in messages))
        self.assertTrue(any('tsMuxeR' in fix for _, fix in messages))
        self.assertTrue(any('xorriso' in fix for _, fix in messages))

    def test_preflight_flags_missing_requests_when_opensubtitles_is_enabled(self):
        project = self._project_with_video()
        env = {'OPENSUBTITLES_API_KEY': 'test-key'}
        with mock.patch.object(bluray_tui_monitor, 'tool_status', return_value={'ffmpeg': '/tmp/ffmpeg', 'ffprobe': '/tmp/ffprobe', 'tsMuxer': '/tmp/tsMuxer', 'xorriso': '/tmp/xorriso', 'nvidia': None}), \
             mock.patch.object(bluray_tui_monitor, 'requests_available', return_value=False), \
             mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(bluray_tui_monitor, 'pptx_menu_converter', None):
            issues = bluray_tui_monitor.project_diagnostics(project, project, cfg={'menu_backend': 'bdj'})

        matching = [row for row in issues if 'requests package is not available' in row['message']]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['severity'], 'error')
        self.assertIn('python3 -m pip install --user requests', matching[0]['fix'])

    def test_main_requires_explicit_project_path(self):
        with self.assertRaises(SystemExit) as caught:
            bluray_tui_monitor.main([])

        self.assertEqual(caught.exception.code, 2)

    def test_main_accepts_explicit_project_path_for_once_mode(self):
        project = self._project_with_video()
        fake_rows = [{'name': 'Main Feature.mp4'}]
        fake_meta = {'ok': True}

        with mock.patch.object(bluray_tui_monitor, 'collect', return_value=(fake_rows, fake_meta)) as mocked_collect, \
             mock.patch('sys.stdout.write') as mocked_write:
            rc = bluray_tui_monitor.main([str(project), '--once'])

        self.assertEqual(rc, 0)
        mocked_collect.assert_called_once()
        written = ''.join(call.args[0] for call in mocked_write.call_args_list)
        payload = json.loads(written)
        self.assertEqual(payload['project'], str(project.resolve()))
        self.assertEqual(payload['meta'], fake_meta)
        self.assertEqual(payload['videos'], fake_rows)


if __name__ == '__main__':
    unittest.main()
