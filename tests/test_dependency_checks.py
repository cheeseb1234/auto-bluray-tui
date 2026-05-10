from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import dependency_checks


class DependencyChecksTests(unittest.TestCase):
    def test_find_java_executable_reports_macos_stub_as_missing_java(self):
        stub = Path('/usr/bin/java')

        def fake_capture(cmd, timeout=10):
            if cmd[0] == str(stub):
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="The operation couldn't be completed. Unable to locate a Java Runtime.\n",
                )
            raise AssertionError(f'unexpected command: {cmd}')

        with mock.patch.object(dependency_checks.platform, 'system', return_value='Darwin'), \
             mock.patch.object(dependency_checks, '_java_candidates', return_value=[stub]), \
             mock.patch.object(dependency_checks, 'capture_command', side_effect=fake_capture), \
             self.assertRaises(dependency_checks.DependencyError) as caught:
            dependency_checks.find_java_executable()

        self.assertIn('Java is not installed', str(caught.exception))
        self.assertIn('temurin@17', str(caught.exception))

    def test_check_optional_tool_accepts_tsmuxer_aliases(self):
        with mock.patch.object(dependency_checks.shutil, 'which', side_effect=lambda name: '/tmp/tsMuxeR' if name == 'tsMuxeR' else None), \
             mock.patch.object(
                 dependency_checks,
                 'capture_command',
                 return_value=subprocess.CompletedProcess(['/tmp/tsMuxeR'], 0, stdout='tsMuxeR. Version 2.6.16\nusage: ...\n'),
             ):
            exe, detail = dependency_checks.check_optional_tool('tsMuxer')

        self.assertEqual(exe, Path('/tmp/tsMuxeR'))
        self.assertEqual(detail, 'tsMuxeR. Version 2.6.16')

    def test_which_tool_prefers_local_bundle_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / 'tools' / 'bin' / 'tsMuxer'
            local.parent.mkdir(parents=True)
            local.write_text('fake')
            with mock.patch.object(dependency_checks.shutil, 'which', return_value='/usr/bin/tsMuxer'):
                found = dependency_checks.which_tool('tsMuxer', root=root, prefer_local=True)

        self.assertEqual(found, local)

    def test_missing_optional_tool_includes_remediation(self):
        with mock.patch.object(dependency_checks.shutil, 'which', return_value=None), \
             mock.patch.object(dependency_checks.platform, 'system', return_value='Darwin'):
            exe, detail = dependency_checks.check_optional_tool('xorriso')

        self.assertIsNone(exe)
        self.assertIn('brew install xorriso', detail)

    def test_requests_available_reflects_importlib_spec(self):
        with mock.patch.object(dependency_checks.importlib.util, 'find_spec', return_value=object()):
            self.assertTrue(dependency_checks.requests_available())
        with mock.patch.object(dependency_checks.importlib.util, 'find_spec', return_value=None):
            self.assertFalse(dependency_checks.requests_available())


if __name__ == '__main__':
    unittest.main()
