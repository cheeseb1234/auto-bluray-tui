import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import start


class StartLauncherTests(unittest.TestCase):
    def test_embedded_helper_resolution_stays_inside_project_root(self):
        helper = start._resolve_embedded_helper('tools/opensubtitles_fetch.py')
        self.assertIsNotNone(helper)
        self.assertEqual(helper.parts[-2:], ('tools', 'opensubtitles_fetch.py'))
        outside = (start.project_root().parent / 'outside.py').resolve()
        self.assertIsNone(start._resolve_embedded_helper(str(outside)))

    def test_run_tui_in_process_passes_project_and_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            fake_monitor = mock.Mock()
            fake_monitor.main.return_value = 7
            with mock.patch.object(start, "_import_tui_monitor", return_value=fake_monitor):
                rc = start.run_tui(project, ["--once"])
            self.assertEqual(rc, 7)
            fake_monitor.main.assert_called_once_with([str(project), "--once"])
            self.assertEqual(start.os.environ.get("AUTO_BLURAY_PYTHON"), start.sys.executable)

    def test_main_calls_tui_in_process_after_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_monitor = mock.Mock()
            fake_monitor.main.return_value = 0
            with mock.patch.object(start, "preflight") as preflight, \
                 mock.patch.object(start, "_import_tui_monitor", return_value=fake_monitor):
                rc = start.main(["--skip-dependency-check", "--quiet", tmp, "--", "--once"])
            self.assertEqual(rc, 0)
            preflight.assert_called_once()
            fake_monitor.main.assert_called_once_with([str(Path(tmp).resolve()), "--once"])

    def test_find_java_executable_reports_macos_stub_as_missing_java(self):
        stub = Path('/usr/bin/java')

        def fake_capture(cmd, timeout=10):
            if cmd[0] == str(stub):
                return subprocess.CompletedProcess(cmd, 1, stdout='The operation couldn\'t be completed. Unable to locate a Java Runtime.\n')
            raise AssertionError(f'unexpected command: {cmd}')

        with mock.patch.object(start.platform, 'system', return_value='Darwin'), \
             mock.patch.object(start, '_java_candidates', return_value=[stub]), \
             mock.patch.object(start, 'capture_command', side_effect=fake_capture), \
             self.assertRaises(start.LauncherError) as caught:
            start.find_java_executable()
        self.assertIn('Java is not installed', str(caught.exception))
        self.assertIn('temurin@17', str(caught.exception))

    def test_main_doctor_does_not_require_project_dir(self):
        with mock.patch.object(start, 'print_doctor', return_value=0) as doctor:
            rc = start.main(['--doctor'])
        self.assertEqual(rc, 0)
        doctor.assert_called_once()

    def test_main_dispatches_embedded_helper_before_normal_argparse(self):
        helper = start.project_root() / 'tools' / 'opensubtitles_fetch.py'
        with mock.patch.object(start, 'run_embedded_helper', return_value=0) as run_helper:
            rc = start.main(['tools/opensubtitles_fetch.py', '/tmp/project'])
        self.assertEqual(rc, 0)
        run_helper.assert_called_once_with(helper, ['/tmp/project'])

    def test_doctor_mentions_requests_and_tsmuxer_alias_help(self):
        out = StringIO()

        def fake_check_tool(name):
            return Path(f'/tmp/{name}'), f'{name} ok'

        def fake_check_optional(name):
            if name == 'tsMuxer':
                return None, 'not found — install with: Install tsMuxer and ensure tsMuxer, tsMuxeR, or tsmuxer is on PATH'
            return Path(f'/tmp/{name}'), f'{name} ok'

        with mock.patch.object(start, 'check_tool', side_effect=fake_check_tool), \
             mock.patch.object(start, 'check_optional_tool', side_effect=fake_check_optional), \
             mock.patch.object(start.importlib.util, 'find_spec', return_value=None), \
             mock.patch('sys.stdout', out):
            rc = start.print_doctor()
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn('requests importable: no', text)
        self.assertIn('tsMuxeR', text)


if __name__ == "__main__":
    unittest.main()
