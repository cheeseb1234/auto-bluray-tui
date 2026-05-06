from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import sys
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from menu_backends import (
    BdjMenuBackend,
    DEFAULT_MENU_BACKEND,
    HDMV_COMPILER_STATUS,
    HdmvMenuBackend,
    MenuBackendError,
    analyze_menu_compatibility,
    compile_hdmv_ig_tables,
    build_hdmv_ig_plan,
    build_hdmv_lite_model,
    select_backend,
    write_compatibility_report,
)


def safe_model():
    return {
        'schema_version': 'auto-bluray-menu-model-v1',
        'slides': [
            {
                'id': 'slide1',
                'title': 'Main Menu',
                'background': {'file': 'assets/slide1_bg.png', 'width': 1920, 'height': 1080, 'kind': 'static_image'},
                'buttons': [
                    {
                        'id': 'Play',
                        'label': 'Play',
                        'focus_index': 1,
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
                    },
                    {
                        'id': 'Extras',
                        'label': 'Extras',
                        'focus_index': 2,
                        'hitbox_px': {'x': 500, 'y': 100, 'w': 200, 'h': 60},
                        'action': {'kind': 'slide', 'target': 'slide2', 'type': 'go_to_menu'},
                    },
                ],
                'focus_order': ['Play', 'Extras'],
            },
            {
                'id': 'slide2',
                'title': 'Extras',
                'background': {'file': 'assets/slide2_bg.png', 'width': 1920, 'height': 1080, 'kind': 'static_image'},
                'buttons': [
                    {
                        'id': 'Return',
                        'label': 'Main Menu',
                        'focus_index': 1,
                        'hitbox_px': {'x': 100, 'y': 250, 'w': 240, 'h': 60},
                        'action': {'kind': 'slide', 'target': 'slide1', 'type': 'return_main_menu'},
                    }
                ],
                'focus_order': ['Return'],
            },
        ],
        'playlists': [{'playlist_id': '00001', 'video_file': 'Movie.mkv', 'title_number': 1, 'kind': 'title'}],
    }


def bdj_only_model():
    model = safe_model()
    model['slides'][0]['loop_videos'] = [{'id': 'Preview', 'video_file': 'Preview.mkv'}]
    return model


def write_background_assets(menu_dir: Path, model: dict):
    for slide in model.get('slides') or []:
        file_name = (slide.get('background') or {}).get('file')
        if file_name:
            path = menu_dir / file_name
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGBA', (1920, 1080), (32, 64, 96, 255)).save(path)


class MenuBackendCompatibilityTests(unittest.TestCase):
    def test_default_backend_is_bdj(self):
        self.assertEqual(DEFAULT_MENU_BACKEND, 'bdj')

    def test_hdmv_safe_menu_does_not_auto_select_hdmv_until_compiler_is_functional(self):
        report = analyze_menu_compatibility(safe_model())
        self.assertTrue(report['hdmv_safe'])
        self.assertEqual(report['hdmv_compiler_status'], HDMV_COMPILER_STATUS)
        self.assertFalse(report['hdmv_compiler_functional'])
        self.assertEqual(select_backend('auto', report), 'bdj')
        self.assertEqual(select_backend('bdj', report), 'bdj')
        self.assertEqual(select_backend('hdmv', report), 'hdmv')

    def test_auto_can_select_hdmv_after_compiler_status_is_functional(self):
        report = analyze_menu_compatibility(safe_model())
        report['hdmv_compiler_status'] = 'functional'
        report['hdmv_compiler_functional'] = True
        self.assertEqual(select_backend('auto', report), 'hdmv')

    def test_bdj_only_feature_forces_auto_to_bdj(self):
        report = analyze_menu_compatibility(bdj_only_model())
        self.assertFalse(report['hdmv_safe'])
        self.assertEqual(select_backend('auto', report), 'bdj')
        self.assertTrue(any(row['feature'] == 'motion_or_windowed_menu_video' for row in report['bdj_required_features']))

    def test_hdmv_report_reflects_parsed_action_types(self):
        model = safe_model()
        model['slides'][0]['buttons'].extend([
            {
                'id': 'Timed',
                'label': 'Big Reveal',
                'focus_index': 3,
                'hitbox_px': {'x': 100, 'y': 200, 'w': 200, 'h': 60},
                'action': {'kind': 'video', 'target': 'Movie.mkv', 'video_file': 'Movie.mkv', 'start_time_seconds': 60, 'start_time': '00:01:00'},
            },
            {
                'id': 'Disabled',
                'label': 'Coming Soon',
                'focus_index': 4,
                'hitbox_px': {'x': 100, 'y': 300, 'w': 200, 'h': 60},
                'action': {'kind': 'builtin', 'name': 'disabled', 'type': 'disabled'},
            },
            {
                'id': 'Resume',
                'label': 'Resume',
                'focus_index': 5,
                'hitbox_px': {'x': 100, 'y': 400, 'w': 200, 'h': 60},
                'action': {'kind': 'builtin', 'name': 'resume', 'type': 'resume'},
            },
        ])
        report = analyze_menu_compatibility(model)
        self.assertFalse(report['hdmv_safe'])
        self.assertTrue(any(row['feature'] == 'timed_or_chapter_video_actions' for row in report['bdj_required_features']))
        self.assertTrue(any(row['feature'] == 'bdj_runtime_builtin_actions' for row in report['bdj_required_features']))
        self.assertTrue(any(row['feature'] == 'safe_builtin_actions' for row in report['safe_features']))

    def test_compatibility_report_files_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            report = write_compatibility_report(menu_dir, bdj_only_model(), requested_backend='auto', selected_backend='bdj')
            self.assertFalse(report['hdmv_safe'])
            self.assertIn('motion_or_windowed_menu_video', (menu_dir / 'menu-compatibility.md').read_text())
            self.assertIn('HDMV-Lite compiler status: `ir_only_first_milestone`', (menu_dir / 'menu-compatibility.md').read_text())
            self.assertTrue((menu_dir / 'menu-compatibility.json').exists())

    def test_hdmv_lite_model_contains_hitboxes_and_simple_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            model = safe_model()
            write_background_assets(menu_dir, model)
            hdmv_model, errors = build_hdmv_lite_model(model, menu_dir)
            self.assertEqual(errors, [])
            self.assertFalse(hdmv_model['capabilities']['java'])
            actions = [button['action']['type'] for menu in hdmv_model['menus'] for button in menu['buttons']]
            self.assertIn('play_title', actions)
            self.assertIn('go_to_menu', actions)
            self.assertIn('return_main_menu', actions)
            self.assertEqual(hdmv_model['menus'][0]['buttons'][0]['hitbox_px']['w'], 200)

    def test_demo_hdmv_lite_project_model_is_safe(self):
        root = Path(__file__).resolve().parents[1]
        demo_dir = root / 'demos' / 'hdmv-lite-static-menu'
        model = json.loads((demo_dir / 'menu-model.json').read_text())
        report = analyze_menu_compatibility(model)
        self.assertTrue(report['hdmv_safe'])
        hdmv_model, errors = build_hdmv_lite_model(model, demo_dir)
        self.assertEqual(errors, [])
        self.assertEqual(hdmv_model['entry_menu'], 'slide1')

    def test_hdmv_ig_plan_exports_pages_buttons_and_background_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            model = safe_model()
            write_background_assets(menu_dir, model)
            hdmv_model, errors = build_hdmv_lite_model(model, menu_dir)
            self.assertEqual(errors, [])
            ig_plan = build_hdmv_ig_plan(hdmv_model)
            self.assertEqual(ig_plan['schema_version'], 'auto-bluray-hdmv-ig-plan-v1')
            self.assertEqual(ig_plan['entry_menu'], 'slide1')
            self.assertEqual(len(ig_plan['pages']), 2)
            self.assertTrue(any(obj['id'] == 'slide1:bg' for obj in ig_plan['objects']))
            self.assertEqual(ig_plan['pages'][0]['buttons'][0]['action']['type'], 'play_title')
            self.assertEqual(ig_plan['pages'][0]['buttons'][0]['visual_state_refs']['normal'], 'slide1:bg')
            self.assertIsNone(ig_plan['pages'][0]['buttons'][0]['visual_state_refs']['selected'])

    def test_hdmv_ig_tables_compile_stable_numeric_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            model = safe_model()
            write_background_assets(menu_dir, model)
            hdmv_model, errors = build_hdmv_lite_model(model, menu_dir)
            self.assertEqual(errors, [])
            ig_plan = build_hdmv_ig_plan(hdmv_model)
            tables = compile_hdmv_ig_tables(ig_plan)
            self.assertEqual(tables['schema_version'], 'auto-bluray-hdmv-ig-tables-v1')
            self.assertEqual(tables['page_table'][0]['background_object_index'], 0)
            self.assertEqual(tables['page_table'][0]['default_selected_button_index'], 0)
            self.assertEqual(tables['button_table'][0]['normal_object_index'], 0)
            self.assertEqual(tables['bog_table'][0]['button_indexes'], [0])

    def test_hdmv_backend_accepts_safe_menu_and_writes_java_free_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            menu_dir = tmp_path / 'menu'
            model = safe_model()
            write_background_assets(menu_dir, model)
            result = HdmvMenuBackend().install(
                root=Path(__file__).resolve().parents[1],
                project=tmp_path,
                menu_dir=menu_dir,
                disc_root=tmp_path / 'disc-root',
                output_root=tmp_path / 'out',
                model=model,
            )
            package = Path(result['hdmv_lite_package'])
            self.assertTrue((package / 'hdmv-lite-menu.json').exists())
            self.assertTrue((package / 'hdmv-lite-ig-plan.json').exists())
            self.assertTrue((package / 'hdmv-lite-ig-tables.json').exists())
            self.assertTrue((package / 'index.xml').exists())
            self.assertTrue((package / 'MovieObject.xml').exists())
            self.assertTrue((package / 'assets' / 'slide1_Play_selected.png').exists())
            self.assertTrue((package / 'assets' / 'slide1_Play_activated.png').exists())
            self.assertFalse((tmp_path / 'disc-root' / 'BDMV' / 'JAR').exists())
            self.assertFalse((tmp_path / 'disc-root' / 'BDMV' / 'BDJO').exists())
            data = json.loads((package / 'hdmv-lite-menu.json').read_text())
            ig_plan = json.loads((package / 'hdmv-lite-ig-plan.json').read_text())
            ig_tables = json.loads((package / 'hdmv-lite-ig-tables.json').read_text())
            self.assertEqual(data['schema_version'], 'auto-bluray-hdmv-lite-v1')
            self.assertEqual(ig_plan['schema_version'], 'auto-bluray-hdmv-ig-plan-v1')
            self.assertEqual(ig_tables['schema_version'], 'auto-bluray-hdmv-ig-tables-v1')
            self.assertEqual(data['titles'][0]['playlist_id'], '00001')
            self.assertEqual(data['menus'][0]['buttons'][0]['state_assets']['selected'], 'assets/slide1_Play_selected.png')
            self.assertEqual(ig_plan['pages'][0]['buttons'][0]['visual_state_refs']['selected'], 'slide1:Play:selected')
            self.assertTrue(any(obj['id'] == 'slide1:Play:selected' for obj in ig_plan['objects']))
            self.assertTrue(any(row['id'] == 'slide1:Play:selected' for row in ig_tables['object_table']))

    def test_hdmv_backend_reports_bdj_only_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp) / 'menu'
            model = bdj_only_model()
            write_background_assets(menu_dir, model)
            with self.assertRaises(MenuBackendError) as caught:
                HdmvMenuBackend().install(
                    root=Path(tmp),
                    project=Path(tmp),
                    menu_dir=menu_dir,
                    disc_root=Path(tmp) / 'disc-root',
                    output_root=Path(tmp) / 'out',
                    model=model,
                )
            message = str(caught.exception)
            self.assertIn('not HDMV-safe', message)
            self.assertIn('Looping/menu-window video', message)

    def test_bdj_backend_still_installs_same_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            menu_dir = tmp_path / 'menu'
            build_dir = menu_dir / 'build'
            assets_dir = menu_dir / 'assets'
            build_dir.mkdir(parents=True)
            assets_dir.mkdir(parents=True)
            (assets_dir / 'slide1_bg.png').write_bytes(b'asset')
            with zipfile.ZipFile(build_dir / '00000.jar', 'w') as zf:
                zf.writestr('pptx-menu.grin', 'image "assets/slide1_bg.png"')
            (build_dir / '00000.bdjo').write_bytes(b'bdjo')

            with mock.patch('menu_backends.run') as mocked_run, mock.patch('menu_backends.sign_pptx_menu_jar') as mocked_sign:
                result = BdjMenuBackend().install(
                    root=tmp_path,
                    project=tmp_path,
                    menu_dir=menu_dir,
                    disc_root=tmp_path / 'disc-root',
                    output_root=tmp_path / 'out',
                    model=safe_model(),
                )

            mocked_run.assert_called_once()
            mocked_sign.assert_called_once()
            jar = tmp_path / 'disc-root' / 'BDMV' / 'JAR' / '00000.jar'
            bdjo = tmp_path / 'disc-root' / 'BDMV' / 'BDJO' / '00000.bdjo'
            self.assertEqual(result['jar'], str(jar))
            self.assertEqual(result['bdjo'], str(bdjo))
            self.assertTrue(jar.exists())
            self.assertTrue(bdjo.exists())
            with zipfile.ZipFile(jar) as zf:
                self.assertIn('assets/slide1_bg.png', zf.namelist())


if __name__ == '__main__':
    unittest.main()
