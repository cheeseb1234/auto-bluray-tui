import tempfile
import unittest
from pathlib import Path
from unittest import mock

import start


class StartLauncherTests(unittest.TestCase):
    def test_run_tui_in_process_passes_project_and_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            fake_monitor = mock.Mock()
            fake_monitor.main.return_value = 7
            with mock.patch.object(start, "_import_tui_monitor", return_value=fake_monitor):
                rc = start.run_tui(project, ["--once"])
            self.assertEqual(rc, 7)
            fake_monitor.main.assert_called_once_with([str(project), "--once"])

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


if __name__ == "__main__":
    unittest.main()
