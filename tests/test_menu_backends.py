from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from menu_backends import HdmvMenuBackend, MenuBackendError, analyze_menu_compatibility, select_backend, write_compatibility_report


def safe_model():
    return {
        'schema_version': 'auto-bluray-menu-model-v1',
        'slides': [
            {
                'id': 'slide1',
                'background': {'file': 'assets/slide1_bg.png', 'kind': 'static_image'},
                'buttons': [
                    {
                        'id': 'Play',
                        'label': 'Play',
                        'hitbox_px': {'x': 100, 'y': 100, 'w': 200, 'h': 60},
                        'action': {
                            'kind': 'video',
                            'type': 'play_title',
                            'target': 'Movie.mkv',
                            'video_file': 'Movie.mkv',
                            'playlist_id': '00001',
                            'playlist': '00001',
                            'title_number': 1,
                        },
                    }
                ],
                'focus_order': ['Play'],
            }
        ],
        'playlists': [{'playlist_id': '00001', 'video_file': 'Movie.mkv', 'kind': 'title'}],
    }


def bdj_only_model():
    model = safe_model()
    model['slides'][0]['loop_videos'] = [{'id': 'Preview', 'video_file': 'Preview.mkv'}]
    return model


class MenuBackendCompatibilityTests(unittest.TestCase):
    def test_hdmv_safe_menu_is_accepted_by_selector(self):
        report = analyze_menu_compatibility(safe_model())
        self.assertTrue(report['hdmv_safe'])
        self.assertEqual(select_backend('auto', report), 'hdmv')
        self.assertEqual(select_backend('bdj', report), 'bdj')

    def test_bdj_only_feature_forces_auto_to_bdj(self):
        report = analyze_menu_compatibility(bdj_only_model())
        self.assertFalse(report['hdmv_safe'])
        self.assertEqual(select_backend('auto', report), 'bdj')
        self.assertTrue(any(row['feature'] == 'motion_or_windowed_menu_video' for row in report['bdj_required_features']))

    def test_compatibility_report_files_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            report = write_compatibility_report(menu_dir, bdj_only_model(), requested_backend='auto', selected_backend='bdj')
            self.assertFalse(report['hdmv_safe'])
            self.assertIn('motion_or_windowed_menu_video', (menu_dir / 'menu-compatibility.md').read_text())
            self.assertTrue((menu_dir / 'menu-compatibility.json').exists())

    def test_hdmv_backend_fails_clearly_for_safe_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            with self.assertRaises(MenuBackendError) as caught:
                HdmvMenuBackend().install(
                    root=Path(tmp),
                    project=Path(tmp),
                    menu_dir=menu_dir,
                    disc_root=Path(tmp) / 'disc-root',
                    output_root=Path(tmp) / 'out',
                    model=safe_model(),
                )
            self.assertIn('actual HDMV compilation is not implemented yet', str(caught.exception))
            self.assertTrue((menu_dir / 'menu-compatibility.md').exists())

    def test_hdmv_backend_reports_bdj_only_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            with self.assertRaises(MenuBackendError) as caught:
                HdmvMenuBackend().install(
                    root=Path(tmp),
                    project=Path(tmp),
                    menu_dir=menu_dir,
                    disc_root=Path(tmp) / 'disc-root',
                    output_root=Path(tmp) / 'out',
                    model=bdj_only_model(),
                )
            message = str(caught.exception)
            self.assertIn('not HDMV-safe', message)
            self.assertIn('Looping/menu-window video', message)


if __name__ == '__main__':
    unittest.main()
