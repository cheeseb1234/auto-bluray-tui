import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import install


class InstallReportingTests(unittest.TestCase):
    def test_linux_check_only_uses_shared_required_probe_messages(self):
        fake_deps = mock.Mock()
        fake_deps.DependencyError = RuntimeError

        def fake_check_tool(name):
            if name == 'java':
                raise RuntimeError("Required dependency 'java' was not found in PATH. Install OpenJDK 8+ and make sure `java` is on PATH.")
            return Path(f'/tmp/{name}'), f'{name} ok'

        fake_deps.check_tool.side_effect = fake_check_tool
        fake_deps.check_optional_tool.side_effect = AssertionError('Linux check-only should not probe optional tools')

        stdout = StringIO()
        stderr = StringIO()
        with mock.patch.object(install, '_dependency_checks', return_value=fake_deps), \
             mock.patch('sys.stdout', stdout), \
             mock.patch('sys.stderr', stderr):
            install.install_linux(dry_run=False, check_only=True, use_sudo=False)

        text = stdout.getvalue()
        self.assertIn('==> System dependency probes:', text)
        self.assertIn(f"- ffmpeg: OK — {Path('/tmp/ffmpeg')} — ffmpeg ok", text)
        self.assertIn("- java: MISSING — Required dependency 'java' was not found in PATH.", text)
        self.assertIn('WARN: Missing system tools: java', stderr.getvalue())

    def test_macos_check_only_reports_optional_tsmuxer_probe_message(self):
        fake_deps = mock.Mock()
        fake_deps.DependencyError = RuntimeError
        fake_deps.check_tool.side_effect = lambda name: (Path(f'/tmp/{name}'), f'{name} ok')
        fake_deps.check_optional_tool.side_effect = lambda name: (None, 'not found — install with: Download the macOS release from https://github.com/justdan96/tsMuxer/releases and place tsMuxer/tsMuxeR on PATH')

        stdout = StringIO()
        stderr = StringIO()
        with mock.patch.object(install, '_dependency_checks', return_value=fake_deps), \
             mock.patch('sys.stdout', stdout), \
             mock.patch('sys.stderr', stderr):
            install.install_macos(dry_run=False, check_only=True)

        text = stdout.getvalue()
        self.assertIn('==> System dependency probes:', text)
        self.assertIn(f"- xorriso: OK — {Path('/tmp/xorriso')} — xorriso ok", text)
        self.assertIn('- tsMuxer: MISSING — not found — install with: Download the macOS release from https://github.com/justdan96/tsMuxer/releases and place tsMuxer/tsMuxeR on PATH', text)
        self.assertEqual('', stderr.getvalue())

    def test_macos_check_only_reports_unusable_tsmuxer_probe_message(self):
        fake_deps = mock.Mock()
        fake_deps.DependencyError = RuntimeError
        fake_deps.check_tool.side_effect = lambda name: (Path(f'/tmp/{name}'), f'{name} ok')
        fake_deps.check_optional_tool.side_effect = lambda name: (Path('/tmp/tsMuxer'), 'unusable — likely platform/architecture mismatch: Bad CPU type in executable — remediation: Download the macOS release from https://github.com/justdan96/tsMuxer/releases and place tsMuxer/tsMuxeR on PATH')

        stdout = StringIO()
        stderr = StringIO()
        with mock.patch.object(install, '_dependency_checks', return_value=fake_deps), \
             mock.patch('sys.stdout', stdout), \
             mock.patch('sys.stderr', stderr):
            install.install_macos(dry_run=False, check_only=True)

        text = stdout.getvalue()
        self.assertIn('- tsMuxer: UNUSABLE — /tmp/tsMuxer — unusable — likely platform/architecture mismatch: Bad CPU type in executable', text)
        self.assertEqual('', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
