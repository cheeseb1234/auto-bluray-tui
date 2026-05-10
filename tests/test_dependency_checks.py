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

    def test_check_optional_tool_supports_libreoffice_pdftoppm_and_ant(self):
        cases = {
            'libreoffice': ('/usr/bin/libreoffice', 'LibreOffice 24.2.0.0\n'),
            'pdftoppm': ('/usr/bin/pdftoppm', 'pdftoppm version 24.02.0\n'),
            'ant': ('/usr/bin/ant', 'Apache Ant(TM) version 1.10.14 compiled on August 16 2023\n'),
        }

        for name, (path, output) in cases.items():
            with self.subTest(name=name):
                with mock.patch.object(dependency_checks.shutil, 'which', side_effect=lambda candidate, *, _name=name, _path=path: _path if candidate == _name else None), \
                     mock.patch.object(
                         dependency_checks,
                         'capture_command',
                         return_value=subprocess.CompletedProcess([path], 0, stdout=output),
                     ):
                    exe, detail = dependency_checks.check_optional_tool(name)

                self.assertEqual(exe, Path(path))
                self.assertEqual(detail, output.strip())

    def test_check_udf_iso_creator_accepts_each_supported_candidate(self):
        cases = {
            'mkisofs': ['/usr/bin/mkisofs'],
            'genisoimage': ['/usr/bin/genisoimage'],
            'xorrisofs': ['/usr/bin/xorrisofs'],
            'xorriso': ['/usr/bin/xorriso', '-as', 'mkisofs'],
        }

        for tool_name, expected_cmd in cases.items():
            with self.subTest(tool_name=tool_name):
                def fake_which(name, root=None, prefer_local=False, *, _tool_name=tool_name, _expected_cmd=expected_cmd):
                    if name == _tool_name:
                        return Path(_expected_cmd[0])
                    return None

                with mock.patch.object(dependency_checks, 'which_tool', side_effect=fake_which), \
                     mock.patch.object(
                         dependency_checks,
                         'capture_command',
                         return_value=subprocess.CompletedProcess(expected_cmd + ['-help'], 0, stdout='usage: tool with -udf support\n'),
                     ):
                    cmd, detail = dependency_checks.check_udf_iso_creator()

                self.assertIsNotNone(cmd)
                assert cmd is not None
                self.assertEqual(Path(cmd[0]), Path(expected_cmd[0]))
                self.assertEqual(cmd[1:], expected_cmd[1:])
                self.assertIn('supports -udf', detail)

    def test_check_udf_iso_creator_reports_missing_when_no_candidates_found(self):
        with mock.patch.object(dependency_checks, 'which_tool', return_value=None):
            cmd, detail = dependency_checks.check_udf_iso_creator()

        self.assertIsNone(cmd)
        self.assertIn('not found', detail)
        self.assertIn('UDF support', detail)

    def test_check_udf_iso_creator_reports_non_udf_candidates(self):
        with mock.patch.object(dependency_checks, 'which_tool', side_effect=lambda name, root=None, prefer_local=False: Path('/usr/bin/mkisofs') if name == 'mkisofs' else None), \
             mock.patch.object(
                 dependency_checks,
                 'capture_command',
                 return_value=subprocess.CompletedProcess(['/usr/bin/mkisofs', '-help'], 0, stdout='usage without universal-disk-format support\n'),
             ):
            cmd, detail = dependency_checks.check_udf_iso_creator()

        self.assertIsNone(cmd)
        self.assertIn('found but not UDF-capable', detail)
        self.assertIn(str(Path('/usr/bin/mkisofs')), detail)


if __name__ == '__main__':
    unittest.main()
