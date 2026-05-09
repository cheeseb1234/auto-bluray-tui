from __future__ import annotations

import json
import os
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
    build_hdmv_validation_report,
    build_hdmv_validation_runbook,
    compile_hdmv_ig_assembly,
    compile_hdmv_ig_packet_container,
    compile_hdmv_movieobject_commands,
    compile_hdmv_movieobject_plan,
    materialize_hdmv_ig_binary_scaffold,
    materialize_hdmv_ig_packet_container,
    pack_hdmv_ig_binary_scaffold,
    run_hdmv_validation_checks,
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

    def test_hdmv_ig_assembly_validates_and_maps_neighbors(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            model = safe_model()
            write_background_assets(menu_dir, model)
            hdmv_model, errors = build_hdmv_lite_model(model, menu_dir)
            self.assertEqual(errors, [])
            for menu in hdmv_model['menus']:
                for button in menu['buttons']:
                    button['object_refs'] = {
                        'selected': f"{menu['id']}:{button['id']}:selected",
                        'activated': f"{menu['id']}:{button['id']}:activated",
                    }
            ig_plan = build_hdmv_ig_plan(hdmv_model)
            for menu in hdmv_model['menus']:
                for button in menu['buttons']:
                    for state_name in ('selected', 'activated'):
                        ig_plan['objects'].append({
                            'id': button['object_refs'][state_name],
                            'kind': 'button_state_bitmap',
                            'menu_id': menu['id'],
                            'button_id': button['id'],
                            'state': state_name,
                            'file': f"assets/{menu['id']}_{button['id']}_{state_name}.png",
                            'width': button['hitbox_px']['w'],
                            'height': button['hitbox_px']['h'],
                        })
            tables = compile_hdmv_ig_tables(ig_plan)
            assembly = compile_hdmv_ig_assembly(tables)
            self.assertEqual(assembly['schema_version'], 'auto-bluray-hdmv-ig-assembly-v1')
            self.assertTrue(assembly['validation']['ok'])
            self.assertEqual(assembly['entry_page_index'], 0)
            self.assertIn('right', assembly['pages'][0]['buttons'][0]['neighbor_button_indexes'])
            self.assertGreaterEqual(assembly['action_count'], 2)
            self.assertEqual(assembly['action_table'][0]['opcode'], 'JUMP_TITLE')
            self.assertEqual(assembly['action_table'][1]['target_page_index'], 1)

    def test_hdmv_ig_assembly_reports_invalid_refs(self):
        tables = {
            'schema_version': 'auto-bluray-hdmv-ig-tables-v1',
            'entry_menu': 'missing',
            'object_table': [],
            'page_table': [{'page_index': 0, 'page_id': 999, 'menu_id': 'slide1', 'title': 'Main', 'background_object_index': 9, 'default_selected_button_index': 0}],
            'button_table': [{'page_index': 0, 'button_index': 0, 'id': 'Play', 'bog_id': 'bog0', 'select_value': 0, 'label': 'Play', 'hitbox_px': {}, 'neighbors': {'right': 'Missing'}, 'normal_object_index': 5, 'selected_object_index': None, 'activated_object_index': None, 'action': {}}],
            'bog_table': [{'page_index': 0, 'bog_index': 0, 'id': 'bog0', 'button_indexes': [7], 'auto_action': False}],
        }
        assembly = compile_hdmv_ig_assembly(tables)
        self.assertFalse(assembly['validation']['ok'])
        error_types = {row['type'] for row in assembly['validation']['errors']}
        self.assertIn('invalid_entry_menu', error_types)
        self.assertIn('invalid_object_ref', error_types)
        self.assertIn('invalid_neighbor', error_types)
        self.assertIn('invalid_bog_button', error_types)
        self.assertIn('page_id_out_of_range', error_types)
        self.assertIn('select_value_out_of_range', error_types)

    def test_hdmv_ig_assembly_reports_button_state_dimension_mismatch(self):
        tables = {
            'schema_version': 'auto-bluray-hdmv-ig-tables-v1',
            'entry_menu': 'slide1',
            'object_table': [
                {'object_index': 0, 'id': 'slide1:bg', 'kind': 'background_bitmap', 'menu_id': 'slide1', 'button_id': None, 'state': None, 'file': 'assets/slide1_bg.png', 'width': 1920, 'height': 1080},
                {'object_index': 1, 'id': 'slide1:Play:selected', 'kind': 'button_state_bitmap', 'menu_id': 'slide1', 'button_id': 'Play', 'state': 'selected', 'file': 'assets/slide1_Play_selected.png', 'width': 199, 'height': 60},
                {'object_index': 2, 'id': 'slide1:Play:activated', 'kind': 'button_state_bitmap', 'menu_id': 'slide1', 'button_id': 'Play', 'state': 'activated', 'file': 'assets/slide1_Play_activated.png', 'width': 200, 'height': 59},
            ],
            'page_table': [{'page_index': 0, 'page_id': 1, 'menu_id': 'slide1', 'title': 'Main', 'background_object_index': 0, 'default_selected_button_index': 0}],
            'button_table': [{'page_index': 0, 'button_index': 0, 'id': 'Play', 'bog_id': 'bog0', 'select_value': 1, 'label': 'Play', 'hitbox_px': {'x': 10, 'y': 20, 'w': 200, 'h': 60}, 'neighbors': {}, 'normal_object_index': 0, 'selected_object_index': 1, 'activated_object_index': 2, 'action': {'type': 'play_title', 'title_number': 1, 'playlist_id': '00001'}}],
            'bog_table': [{'page_index': 0, 'bog_index': 0, 'id': 'bog0', 'button_indexes': [0], 'auto_action': False}],
        }
        assembly = compile_hdmv_ig_assembly(tables)
        self.assertFalse(assembly['validation']['ok'])
        mismatches = [row for row in assembly['validation']['errors'] if row['type'] == 'button_state_dimension_mismatch']
        self.assertEqual(len(mismatches), 2)
        self.assertEqual(mismatches[0]['expected_width'], 200)
        self.assertEqual(mismatches[0]['expected_height'], 60)

    def test_hdmv_ig_assembly_reports_background_and_state_identity_mismatches(self):
        tables = {
            'schema_version': 'auto-bluray-hdmv-ig-tables-v1',
            'entry_menu': 'slide1',
            'object_table': [
                {'object_index': 0, 'id': 'slide2:bg', 'kind': 'button_state_bitmap', 'menu_id': 'slide2', 'button_id': None, 'state': None, 'file': 'assets/slide2_bg.png', 'width': 1920, 'height': 1080},
                {'object_index': 1, 'id': 'slide2:Wrong:selected', 'kind': 'background_bitmap', 'menu_id': 'slide2', 'button_id': 'Wrong', 'state': 'activated', 'file': 'assets/slide2_Wrong.png', 'width': 200, 'height': 60},
                {'object_index': 2, 'id': 'slide1:Play:activated', 'kind': 'button_state_bitmap', 'menu_id': 'slide1', 'button_id': 'Play', 'state': 'activated', 'file': 'assets/slide1_Play_activated.png', 'width': 200, 'height': 60},
            ],
            'page_table': [{'page_index': 0, 'page_id': 1, 'menu_id': 'slide1', 'title': 'Main', 'background_object_index': 0, 'default_selected_button_index': 0}],
            'button_table': [{'page_index': 0, 'button_index': 0, 'id': 'Play', 'bog_id': 'bog0', 'select_value': 1, 'label': 'Play', 'hitbox_px': {'x': 10, 'y': 20, 'w': 200, 'h': 60}, 'neighbors': {}, 'normal_object_index': 0, 'selected_object_index': 1, 'activated_object_index': 2, 'action': {'type': 'play_title', 'title_number': 1, 'playlist_id': '00001'}}],
            'bog_table': [{'page_index': 0, 'bog_index': 0, 'id': 'bog0', 'button_indexes': [0], 'auto_action': False}],
        }
        assembly = compile_hdmv_ig_assembly(tables)
        self.assertFalse(assembly['validation']['ok'])
        error_types = [row['type'] for row in assembly['validation']['errors']]
        self.assertIn('invalid_background_object_kind', error_types)
        self.assertIn('background_menu_mismatch', error_types)
        self.assertIn('invalid_button_state_object_kind', error_types)
        self.assertIn('button_state_object_identity_mismatch', error_types)

    def test_hdmv_ig_binary_scaffold_packs_deterministic_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu_dir = Path(tmp)
            model = safe_model()
            write_background_assets(menu_dir, model)
            hdmv_model, errors = build_hdmv_lite_model(model, menu_dir)
            self.assertEqual(errors, [])
            for menu in hdmv_model['menus']:
                for button in menu['buttons']:
                    button['object_refs'] = {
                        'selected': f"{menu['id']}:{button['id']}:selected",
                        'activated': f"{menu['id']}:{button['id']}:activated",
                    }
            ig_plan = build_hdmv_ig_plan(hdmv_model)
            for menu in hdmv_model['menus']:
                for button in menu['buttons']:
                    for state_name in ('selected', 'activated'):
                        ig_plan['objects'].append({
                            'id': button['object_refs'][state_name],
                            'kind': 'button_state_bitmap',
                            'menu_id': menu['id'],
                            'button_id': button['id'],
                            'state': state_name,
                            'file': f"assets/{menu['id']}_{button['id']}_{state_name}.png",
                            'width': button['hitbox_px']['w'],
                            'height': button['hitbox_px']['h'],
                        })
            tables = compile_hdmv_ig_tables(ig_plan)
            assembly = compile_hdmv_ig_assembly(tables)
            binary = pack_hdmv_ig_binary_scaffold(assembly)
            self.assertEqual(binary['schema_version'], 'auto-bluray-hdmv-ig-binary-scaffold-v1')
            self.assertEqual([section['name'] for section in binary['sections']], ['header', 'pages', 'buttons', 'bogs', 'actions'])
            self.assertEqual(binary['sections'][0]['hex'][:8], '49475343')
            page_section = next(section for section in binary['sections'] if section['name'] == 'pages')
            button_section = next(section for section in binary['sections'] if section['name'] == 'buttons')
            self.assertIn('animation_frame_rate_code', page_section['record_layout'])
            self.assertIn('background_behavior_code', page_section['record_layout'])
            self.assertIn('start,u16 end,u8 repeat,u8 sound', button_section['record_layout'])
            self.assertGreater(binary['total_size'], 0)
            self.assertGreater(binary['sections'][-1]['size'], 0)

    def test_hdmv_ig_binary_page_records_use_static_page_profile_layout(self):
        assembly = {
            'schema_version': 'auto-bluray-hdmv-ig-assembly-v1',
            'entry_page_index': 0,
            'page_count': 1,
            'object_count': 1,
            'action_count': 0,
            'action_table': [],
            'pages': [
                {
                    'page_index': 0,
                    'page_id': 1,
                    'background_object_index': 0,
                    'default_selected_button_index': 0,
                    'buttons': [],
                    'bogs': [],
                }
            ],
            'validation': {'ok': True, 'errors': []},
        }
        binary = pack_hdmv_ig_binary_scaffold(assembly)
        page_section = next(section for section in binary['sections'] if section['name'] == 'pages')
        page_blob = bytes.fromhex(page_section['hex'])
        self.assertEqual(len(page_blob), 14)
        self.assertEqual(page_blob[0:2], b'\x00\x00')  # page index
        self.assertEqual(page_blob[2:4], b'\x00\x01')  # page id
        self.assertEqual(page_blob[4:5], b'\x00')       # animation frame rate code (static default)
        self.assertEqual(page_blob[5:6], b'\x01')       # background behavior code (static background)
        self.assertEqual(page_blob[6:8], b'\x00\x00')  # background object index
        self.assertEqual(page_blob[8:10], b'\x00\x00') # default selected button index
        self.assertEqual(page_blob[10:12], b'\x00\x00')# button count
        self.assertEqual(page_blob[12:14], b'\x00\x00')# bog count

    def test_hdmv_ig_binary_button_records_use_state_chain_layout(self):
        assembly = {
            'schema_version': 'auto-bluray-hdmv-ig-assembly-v1',
            'entry_page_index': 0,
            'page_count': 1,
            'object_count': 3,
            'action_count': 1,
            'action_table': [
                {'action_index': 0, 'opcode': 'JUMP_TITLE', 'title_number': 1, 'playlist_id': '00001', 'target_page_index': None},
            ],
            'pages': [
                {
                    'page_index': 0,
                    'page_id': 1,
                    'background_object_index': 0,
                    'default_selected_button_index': 0,
                    'buttons': [
                        {
                            'button_index': 0,
                            'select_value': 1,
                            'bog_id': 'bog0',
                            'action_index': 0,
                            'object_indexes': {'normal': 0, 'selected': 1, 'activated': 2},
                            'neighbor_button_indexes': {},
                            'action': {'type': 'play_title', 'title_number': 1, 'playlist_id': '00001'},
                        }
                    ],
                    'bogs': [{'bog_index': 0, 'button_indexes': [0], 'auto_action': False}],
                }
            ],
            'validation': {'ok': True, 'errors': []},
        }
        binary = pack_hdmv_ig_binary_scaffold(assembly)
        button_section = next(section for section in binary['sections'] if section['name'] == 'buttons')
        button_blob = bytes.fromhex(button_section['hex'])
        self.assertEqual(len(button_blob), 34)
        self.assertEqual(button_blob[0:2], b'\x00\x00')  # page index
        self.assertEqual(button_blob[2:4], b'\x00\x00')  # button index
        self.assertEqual(button_blob[4:6], b'\x00\x01')  # select value
        self.assertEqual(button_blob[14:16], b'\x00\x00')  # normal start
        self.assertEqual(button_blob[16:18], b'\x00\x00')  # normal end
        self.assertEqual(button_blob[18:20], b'\x00\xff')  # normal repeat=0, sound=none
        self.assertEqual(button_blob[20:22], b'\x00\x01')  # selected start
        self.assertEqual(button_blob[22:24], b'\x00\x01')  # selected end
        self.assertEqual(button_blob[24:26], b'\x00\xff')  # selected repeat=0, sound=none
        self.assertEqual(button_blob[26:28], b'\x00\x02')  # activated start
        self.assertEqual(button_blob[28:30], b'\x00\x02')  # activated end
        self.assertEqual(button_blob[30:32], b'\x00\xff')  # activated repeat=0, sound=none
        self.assertEqual(button_blob[32:34], b'\x00\x00')  # action index

    def test_hdmv_ig_binary_scaffold_materializes_to_blob(self):
        binary = {
            'schema_version': 'auto-bluray-hdmv-ig-binary-scaffold-v1',
            'total_size': 6,
            'sections': [
                {'name': 'header', 'offset': 0, 'size': 4, 'hex': '49475343'},
                {'name': 'tail', 'offset': 4, 'size': 2, 'hex': '0001'},
            ],
        }
        blob = materialize_hdmv_ig_binary_scaffold(binary)
        self.assertEqual(blob, b'IGSC\x00\x01')

    def test_hdmv_ig_binary_scaffold_materialize_rejects_offset_gaps(self):
        with self.assertRaises(MenuBackendError):
            materialize_hdmv_ig_binary_scaffold({
                'schema_version': 'auto-bluray-hdmv-ig-binary-scaffold-v1',
                'total_size': 2,
                'sections': [
                    {'name': 'bad', 'offset': 1, 'size': 2, 'hex': '0001'},
                ],
            })

    def test_hdmv_ig_packet_container_wraps_scaffold_sections(self):
        container = compile_hdmv_ig_packet_container({
            'schema_version': 'auto-bluray-hdmv-ig-binary-scaffold-v1',
            'entry_page_index': 0,
            'sections': [
                {'name': 'header', 'size': 4, 'hex': '49475343'},
                {'name': 'pages', 'size': 2, 'hex': '0001'},
            ],
        })
        self.assertEqual(container['schema_version'], 'auto-bluray-hdmv-ig-packet-container-v1')
        self.assertEqual(container['packet_count'], 2)
        self.assertEqual(container['packets'][0]['packet_type'], 1)
        self.assertEqual(container['packets'][1]['payload_offset'], 4)

    def test_hdmv_ig_packet_container_materializes_to_blob(self):
        blob = materialize_hdmv_ig_packet_container({
            'schema_version': 'auto-bluray-hdmv-ig-packet-container-v1',
            'entry_page_index': 0,
            'packet_count': 1,
            'payload_size': 4,
            'packets': [
                {'packet_index': 0, 'packet_type': 1, 'payload_offset': 0, 'payload_size': 4, 'hex': '49475343'},
            ],
        })
        self.assertEqual(blob[:4], b'IGPK')
        self.assertEqual(blob[-4:], b'IGSC')

    def test_hdmv_ig_packet_container_rejects_bad_offsets(self):
        with self.assertRaises(MenuBackendError):
            materialize_hdmv_ig_packet_container({
                'schema_version': 'auto-bluray-hdmv-ig-packet-container-v1',
                'entry_page_index': 0,
                'packet_count': 1,
                'payload_size': 2,
                'packets': [
                    {'packet_index': 0, 'packet_type': 1, 'payload_offset': 1, 'payload_size': 2, 'hex': '0001'},
                ],
            })

    def test_hdmv_ig_binary_scaffold_rejects_invalid_assembly(self):
        with self.assertRaises(MenuBackendError):
            pack_hdmv_ig_binary_scaffold({
                'schema_version': 'auto-bluray-hdmv-ig-assembly-v1',
                'entry_page_index': 0,
                'validation': {'ok': False, 'errors': [{'type': 'invalid_object_ref'}]},
                'pages': [],
            })

    def test_hdmv_ig_binary_scaffold_rejects_bog_count_overflow(self):
        with self.assertRaises(MenuBackendError):
            pack_hdmv_ig_binary_scaffold({
                'schema_version': 'auto-bluray-hdmv-ig-assembly-v1',
                'entry_page_index': 0,
                'object_count': 1,
                'page_count': 1,
                'action_count': 0,
                'action_table': [],
                'validation': {'ok': True, 'errors': []},
                'pages': [{
                    'page_index': 0,
                    'page_id': 1,
                    'background_object_index': 0,
                    'default_selected_button_index': 0,
                    'buttons': [],
                    'bogs': [{'bog_index': 0, 'button_indexes': list(range(256)), 'auto_action': False}],
                }],
            })

    def test_hdmv_movieobject_plan_emits_sample_backed_jump_title_commands(self):
        plan = compile_hdmv_movieobject_plan({
            'entry_menu': 'slide1',
            'menus': [
                {
                    'id': 'slide1',
                    'page_id': 0,
                    'title': 'Main Menu',
                    'buttons': [
                        {'id': 'Play', 'label': 'Play', 'action': {'type': 'play_title', 'title_number': 1, 'playlist_id': '00001'}},
                        {'id': 'Extras', 'label': 'Extras', 'action': {'type': 'go_to_menu', 'target_menu': 'slide2'}},
                    ],
                },
                {
                    'id': 'slide2',
                    'page_id': 1,
                    'title': 'Extras',
                    'buttons': [
                        {'id': 'Return', 'label': 'Main Menu', 'action': {'type': 'return_main_menu', 'target_menu': 'slide1'}},
                    ],
                },
            ],
            'titles': [
                {'title_number': 1, 'playlist_id': '00001', 'video_file': 'Movie1.mkv'},
                {'title_number': 2, 'playlist_id': '00002', 'video_file': 'Movie2.mkv'},
            ]
        })
        self.assertEqual(plan['schema_version'], 'auto-bluray-hdmv-movieobject-plan-v1')
        self.assertEqual(plan['command_source'], 'local-hdcookbook-sample')
        self.assertEqual(plan['compiler_status'], 'graph_planned_sample_title_fallback')
        self.assertEqual(plan['entry_menu'], 'slide1')
        self.assertEqual(plan['objects'][0]['kind'], 'first_playback')
        self.assertEqual(plan['objects'][0]['commands'][0], '21810000 00000001 00000000')
        self.assertEqual(plan['objects'][0]['intended_commands'][0]['op'], 'JumpObject')
        self.assertEqual(plan['objects'][1]['kind'], 'top_menu')
        self.assertEqual(plan['objects'][1]['commands'][0], '21810000 00000001 00000000')
        self.assertEqual(plan['objects'][2]['mobj_id'], 2)
        self.assertEqual(plan['objects'][2]['commands'][0], '21810000 00000001 00000000')
        self.assertEqual(plan['objects'][3]['mobj_id'], 3)
        self.assertEqual(plan['objects'][3]['commands'][0], '21810000 00000002 00000000')
        self.assertEqual(plan['menu_object_ids']['slide1'], 4)
        self.assertEqual(plan['menu_object_ids']['slide2'], 5)
        self.assertTrue(any(obj['kind'] == 'menu_page' and obj['menu_id'] == 'slide1' for obj in plan['objects']))
        self.assertTrue(any(route['op'] == 'SetButtonPage' and route['target_menu'] == 'slide2' for route in plan['routes']))

    def test_hdmv_movieobject_command_compiler_marks_fallbacks_without_inventing_unknown_opcodes(self):
        plan = compile_hdmv_movieobject_plan({
            'entry_menu': 'slide1',
            'menus': [
                {'id': 'slide1', 'page_id': 0, 'title': 'Main Menu', 'buttons': []},
            ],
            'titles': [
                {'title_number': 1, 'playlist_id': '00001', 'video_file': 'Movie1.mkv'},
            ],
        })
        compiled = compile_hdmv_movieobject_commands(plan)
        self.assertEqual(compiled['compiler_status'], 'compiled_with_fallbacks')
        self.assertIn('JumpObject', compiled['unsupported_ops'])
        self.assertIn('SetButtonPage', compiled['unsupported_ops'])
        self.assertEqual(compiled['opcode_registry']['JumpTitle']['mode'], 'native')
        first = compiled['objects'][0]
        self.assertEqual(first['compiled_commands'][0]['status'], 'fallback')
        self.assertEqual(first['compiled_commands'][0]['word'], '21810000 00000001 00000000')
        jump_title = next(obj for obj in compiled['objects'] if obj['kind'] == 'jump_title')
        self.assertEqual(jump_title['compiled_commands'][0]['status'], 'compiled')
        self.assertEqual(jump_title['compiled_commands'][0]['word'], '21810000 00000001 00000000')
        self.assertEqual(compiled['native_ops']['JumpTitle'], 1)

    def test_hdmv_validation_report_describes_available_oracle_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(__file__).resolve().parents[1]
            disc_root = Path(tmp) / 'disc-root'
            package_dir = Path(tmp) / 'pkg'
            (disc_root / 'BDMV' / 'PLAYLIST').mkdir(parents=True)
            (disc_root / 'BDMV' / 'CLIPINF').mkdir(parents=True)
            (disc_root / 'BDMV' / 'AUXDATA').mkdir(parents=True)
            package_dir.mkdir(parents=True)
            report = build_hdmv_validation_report(root=root, disc_root=disc_root, package_dir=package_dir)
            self.assertEqual(report['schema_version'], 'auto-bluray-hdmv-validation-report-v1')
            tools = {row['tool']: row for row in report['commands']}
            self.assertIn('mobj_dump', tools)
            self.assertIn('movieobject_jar', tools)
            expected_movieobject_jar = (root / 'DiscCreationTools' / 'movieobject' / 'dist' / 'movieobject.jar').exists()
            self.assertEqual(tools['movieobject_jar']['available'], expected_movieobject_jar)
            self.assertTrue(str(disc_root) in ' '.join(tools['index_dump']['argv']))

    def test_hdmv_validation_runbook_marks_missing_vs_available_commands(self):
        report = {
            'commands': [
                {'tool': 'index_dump', 'available': False, 'argv': ['index_dump', '/disc']},
                {'tool': 'movieobject_jar', 'available': True, 'argv': ['java', '-jar', 'movieobject.jar', 'MovieObject.xml', 'MovieObject.bdmv']},
            ]
        }
        runbook = build_hdmv_validation_runbook(report)
        self.assertIn('# MISSING: index_dump', runbook)
        self.assertIn('# index_dump /disc', runbook)
        self.assertIn('# AVAILABLE: movieobject_jar', runbook)
        self.assertIn('java -jar movieobject.jar MovieObject.xml MovieObject.bdmv', runbook)

    def test_hdmv_validation_checks_execute_available_commands_and_capture_output(self):
        report = {
            'commands': [
                {'tool': 'fake-ok', 'available': True, 'argv': ['fake-ok', '--version']},
                {'tool': 'fake-missing', 'available': False, 'argv': ['fake-missing']},
            ]
        }

        def runner(argv, capture_output, text, check):
            class Result:
                returncode = 0
                stdout = 'ok\n'
                stderr = ''
            self.assertEqual(argv, ['fake-ok', '--version'])
            self.assertTrue(capture_output)
            self.assertTrue(text)
            self.assertFalse(check)
            return Result()

        result = run_hdmv_validation_checks(report, runner=runner, include_unavailable=True)
        self.assertEqual(result['schema_version'], 'auto-bluray-hdmv-validation-run-v1')
        self.assertEqual(result['command_count'], 2)
        self.assertEqual(result['executed_count'], 1)
        self.assertEqual(result['skipped_count'], 1)
        self.assertEqual(result['passed_count'], 1)
        self.assertEqual(result['failed_count'], 0)
        self.assertTrue(result['ok'])
        self.assertEqual(result['results'][0]['tool'], 'fake-ok')
        self.assertTrue(result['results'][0]['ok'])
        self.assertTrue(result['results'][1]['skipped'])

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
            self.assertTrue((package / 'hdmv-lite-ig-assembly.json').exists())
            self.assertTrue((package / 'hdmv-lite-ig-binary-scaffold.json').exists())
            self.assertTrue((package / 'hdmv-lite-ig-scaffold.bin').exists())
            self.assertTrue((package / 'hdmv-lite-ig-packet-container.json').exists())
            self.assertTrue((package / 'hdmv-lite-ig-packet-container.bin').exists())
            self.assertTrue((package / 'validation-report.json').exists())
            self.assertTrue((package / 'validation-commands.sh').exists())
            self.assertTrue((package / 'validation-run.json').exists())
            self.assertTrue((package / 'index.xml').exists())
            self.assertTrue((package / 'MovieObject.xml').exists())
            self.assertTrue((package / 'movieobject-plan.json').exists())
            self.assertTrue((package / 'assets' / 'slide1_Play_selected.png').exists())
            self.assertTrue((package / 'assets' / 'slide1_Play_activated.png').exists())
            self.assertFalse((tmp_path / 'disc-root' / 'BDMV' / 'JAR').exists())
            self.assertFalse((tmp_path / 'disc-root' / 'BDMV' / 'BDJO').exists())
            data = json.loads((package / 'hdmv-lite-menu.json').read_text())
            ig_plan = json.loads((package / 'hdmv-lite-ig-plan.json').read_text())
            ig_tables = json.loads((package / 'hdmv-lite-ig-tables.json').read_text())
            ig_assembly = json.loads((package / 'hdmv-lite-ig-assembly.json').read_text())
            ig_binary = json.loads((package / 'hdmv-lite-ig-binary-scaffold.json').read_text())
            ig_blob = (package / 'hdmv-lite-ig-scaffold.bin').read_bytes()
            ig_container = json.loads((package / 'hdmv-lite-ig-packet-container.json').read_text())
            ig_container_blob = (package / 'hdmv-lite-ig-packet-container.bin').read_bytes()
            movieobject_plan = json.loads((package / 'movieobject-plan.json').read_text())
            validation_report = json.loads((package / 'validation-report.json').read_text())
            validation_run = json.loads((package / 'validation-run.json').read_text())
            validation_runbook = (package / 'validation-commands.sh').read_text()
            movieobject_xml = (package / 'MovieObject.xml').read_text()
            index_xml = (package / 'index.xml').read_text()
            self.assertEqual(data['schema_version'], 'auto-bluray-hdmv-lite-v1')
            self.assertEqual(ig_plan['schema_version'], 'auto-bluray-hdmv-ig-plan-v1')
            self.assertEqual(ig_tables['schema_version'], 'auto-bluray-hdmv-ig-tables-v1')
            self.assertEqual(ig_assembly['schema_version'], 'auto-bluray-hdmv-ig-assembly-v1')
            self.assertEqual(ig_binary['schema_version'], 'auto-bluray-hdmv-ig-binary-scaffold-v1')
            self.assertEqual(ig_container['schema_version'], 'auto-bluray-hdmv-ig-packet-container-v1')
            self.assertEqual(movieobject_plan['schema_version'], 'auto-bluray-hdmv-movieobject-plan-v1')
            self.assertEqual(movieobject_plan['compiler_status'], 'compiled_with_fallbacks')
            self.assertEqual(validation_report['schema_version'], 'auto-bluray-hdmv-validation-report-v1')
            self.assertEqual(validation_run['schema_version'], 'auto-bluray-hdmv-validation-run-v1')
            available_validation_commands = sum(1 for cmd in validation_report['commands'] if cmd['available'])
            self.assertEqual(validation_run['command_count'], len(validation_report['commands']))
            self.assertEqual(validation_run['executed_count'], available_validation_commands)
            self.assertEqual(validation_run['skipped_count'], len(validation_report['commands']) - available_validation_commands)
            self.assertEqual(validation_run['passed_count'] + validation_run['failed_count'], validation_run['executed_count'])
            self.assertEqual(data['titles'][0]['playlist_id'], '00001')
            self.assertEqual(data['menus'][0]['buttons'][0]['state_assets']['selected'], 'assets/slide1_Play_selected.png')
            self.assertEqual(ig_plan['pages'][0]['buttons'][0]['visual_state_refs']['selected'], 'slide1:Play:selected')
            self.assertTrue(any(obj['id'] == 'slide1:Play:selected' for obj in ig_plan['objects']))
            self.assertTrue(any(row['id'] == 'slide1:Play:selected' for row in ig_tables['object_table']))
            self.assertTrue(ig_assembly['validation']['ok'])
            self.assertEqual(ig_binary['sections'][0]['name'], 'header')
            self.assertEqual(ig_blob[:4], b'IGSC')
            self.assertEqual(ig_container['packets'][0]['section_name'], 'header')
            self.assertEqual(ig_container_blob[:4], b'IGPK')
            self.assertTrue(any(cmd['tool'] == 'movieobject_jar' for cmd in validation_report['commands']))
            self.assertIn('# Generated HDMV validation runbook', validation_runbook)
            self.assertTrue(os.access(package / 'validation-commands.sh', os.X_OK))
            self.assertIn('21810000 00000001 00000000', movieobject_xml)
            self.assertIn('fallback sample_jump_title', movieobject_xml)
            self.assertIn('<HDMVName>0x1</HDMVName>', index_xml)
            self.assertIn('<playbackType>HDMVPlayback_MOVIE</playbackType>', index_xml)
            self.assertEqual(movieobject_plan['objects'][1]['kind'], 'top_menu')
            self.assertEqual(movieobject_plan['objects'][2]['kind'], 'jump_title')
            self.assertTrue(any(obj['kind'] == 'menu_page' for obj in movieobject_plan['objects']))
            self.assertTrue(any(cmd['status'] == 'fallback' for obj in movieobject_plan['objects'] for cmd in obj.get('compiled_commands', [])))

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
