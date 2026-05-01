import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.burner import Burner, LinuxBurnStrategy, MacOSBurnStrategy, WindowsBurnStrategy


class BurnerStrategyTests(unittest.TestCase):
    def test_burner_selects_os_strategy(self):
        with mock.patch("tools.burner.platform.system", return_value="Linux"):
            self.assertIsInstance(Burner().strategy, LinuxBurnStrategy)
        with mock.patch("tools.burner.platform.system", return_value="Darwin"):
            self.assertIsInstance(Burner().strategy, MacOSBurnStrategy)
        with mock.patch("tools.burner.platform.system", return_value="Windows"):
            self.assertIsInstance(Burner().strategy, WindowsBurnStrategy)

    def test_linux_burn_uses_wodim_or_cdrecord_and_dev_sr0_default(self):
        strategy = LinuxBurnStrategy()
        with tempfile.NamedTemporaryFile(suffix=".iso") as iso, \
            mock.patch("tools.burner.shutil.which", side_effect=lambda name: "/usr/bin/wodim" if name == "wodim" else None), \
            mock.patch("tools.burner.Path.glob", return_value=[]), \
            mock.patch.object(LinuxBurnStrategy, "_stream", return_value=True) as stream:
            self.assertTrue(strategy.burn_iso(Path(iso.name)))
            stream.assert_called_once_with(["/usr/bin/wodim", "-v", "dev=/dev/sr0", "-eject", iso.name])

    def test_macos_burn_uses_drutil(self):
        strategy = MacOSBurnStrategy()
        with tempfile.NamedTemporaryFile(suffix=".iso") as iso, \
            mock.patch("tools.burner.shutil.which", return_value="/usr/bin/drutil"), \
            mock.patch.object(MacOSBurnStrategy, "_stream", return_value=True) as stream:
            self.assertTrue(strategy.burn_iso(Path(iso.name)))
            stream.assert_called_once_with(["/usr/bin/drutil", "burn", iso.name])

    def test_windows_imgburn_prefers_common_path_and_uses_required_cli_flags(self):
        strategy = WindowsBurnStrategy(preferred_drive="E:")
        imgburn_path = Path(r"C:\Program Files (x86)\ImgBurn\ImgBurn.exe")
        with tempfile.NamedTemporaryFile(suffix=".iso") as iso, \
            mock.patch("tools.burner.shutil.which", return_value=None), \
            mock.patch.object(Path, "is_file", autospec=True, side_effect=lambda self: self == imgburn_path), \
            mock.patch.object(WindowsBurnStrategy, "_stream", return_value=True) as stream:
            self.assertTrue(strategy.burn_iso(Path(iso.name)))
            stream.assert_called_once_with([
                str(imgburn_path),
                "/MODE", "WRITE",
                "/SRC", iso.name,
                "/DEST", "E:",
                "/START",
                "/CLOSESUCCESS",
            ])

    def test_windows_isoburn_fallback_warns_and_uses_quiet_command(self):
        strategy = WindowsBurnStrategy(preferred_drive="F:")
        isoburn = Path(r"C:\Windows\System32\isoburn.exe")
        env = {"WINDIR": r"C:\Windows"}
        with tempfile.NamedTemporaryFile(suffix=".iso") as iso, \
            mock.patch.dict(os.environ, env, clear=True), \
            mock.patch("tools.burner.shutil.which", return_value=None), \
            mock.patch.object(Path, "is_file", autospec=True, side_effect=lambda self: self.name.lower() == "isoburn.exe"), \
            mock.patch.object(WindowsBurnStrategy, "_stream", return_value=True) as stream, \
            self.assertLogs("tools.burner", level="WARNING") as logs:
            self.assertTrue(strategy.burn_iso(Path(iso.name)))
            cmd = stream.call_args.args[0]
            self.assertEqual(cmd[1:], ["/Q", "F:", iso.name])
            self.assertTrue(cmd[0].endswith("isoburn.exe"))
            self.assertTrue(any("background GUI" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
