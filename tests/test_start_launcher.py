import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock
import subprocess

import start


class StartLauncherTests(unittest.TestCase):
    def test_resolve_tool_prefers_bundled_tsmuxer_over_incompatible_path_on_intel_macos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / 'tools' / 'bin' / 'tsMuxer'
            bundled.parent.mkdir(parents=True)
            bundled.write_text('')
            path_tsmuxer = root / 'path-tsMuxer'
            path_tsmuxer.write_text('')

            def fake_capture(cmd, timeout=10):
                target = Path(cmd[1])
                if target == bundled:
                    return subprocess.CompletedProcess(cmd, 0, stdout='Mach-O 64-bit executable x86_64\n')
                if target == path_tsmuxer:
                    return subprocess.CompletedProcess(cmd, 0, stdout='Mach-O 64-bit executable arm64\n')
                raise AssertionError(f'unexpected command: {cmd}')

            with mock.patch.object(start, 'project_root', return_value=root), \
                 mock.patch.object(start.platform, 'system', return_value='Darwin'), \
                 mock.patch.object(start.platform, 'machine', return_value='x86_64'), \
                 mock.patch.object(start, 'capture_command', side_effect=fake_capture), \
                 mock.patch.object(start.shutil, 'which', side_effect=lambda name: str(path_tsmuxer) if name == 'tsMuxer' else None):
                resolved, note = start.resolve_tool('tsMuxer')

            self.assertEqual(resolved, bundled.resolve())
            self.assertIsNone(note)

    def test_check_optional_tool_reports_incompatible_tsmuxer_on_intel_macos(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'tsMuxer'
            bad.write_text('')

            def fake_capture(cmd, timeout=10):
                self.assertEqual(cmd, ['file', str(bad)])
                return subprocess.CompletedProcess(cmd, 0, stdout='Mach-O 64-bit executable arm64\n')

            with mock.patch.object(start, 'project_root', return_value=Path('/tmp/app')), \
                 mock.patch.object(start.platform, 'system', return_value='Darwin'), \
                 mock.patch.object(start.platform, 'machine', return_value='x86_64'), \
                 mock.patch.object(start, 'capture_command', side_effect=fake_capture), \
                 mock.patch.object(start.shutil, 'which', side_effect=lambda name: str(bad) if name == 'tsMuxer' else None):
                exe, message = start.check_optional_tool('tsMuxer')

            self.assertIsNone(exe)
            self.assertIn('incompatible binary found', message)
            self.assertIn(str(bad), message)
            self.assertIn('Intel Mac', message)

    def test_embedded_helper_resolution_stays_inside_project_root(self):
        helper = start._resolve_embedded_helper('tools/opensubtitles_fetch.py')
        self.assertIsNotNone(helper)
        self.assertTrue(str(helper).endswith('tools/opensubtitles_fetch.py'))
        self.assertIsNone(start._resolve_embedded_helper('/tmp/outside.py'))

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
             mock.patch.object(start, 'capture_command', side_effect=fake_capture):
            with self.assertRaises(start.LauncherError) as caught:
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

    def test_resolve_tool_accepts_soffice_alias_for_libreoffice(self):
        soffice = Path('/tmp/soffice')
        with mock.patch.object(start.shutil, 'which', side_effect=lambda name: str(soffice) if name == 'soffice' else None):
            resolved, note = start.resolve_tool('libreoffice')
        self.assertEqual(resolved, soffice)
        self.assertIsNone(note)


if __name__ == "__main__":
    unittest.main()
