from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from html_menu_preview import make_preview
from pptx_menu_converter import repair_conflicting_slide_links


class PptxMenuConverterHeuristicTests(unittest.TestCase):
    def test_repairs_conflicting_slide_link_onto_unresolved_button(self):
        model = {
            'slides': [
                {
                    'id': 'slide1',
                    'buttons': [
                        {
                            'id': 'Jello',
                            'label': 'Jello',
                            'raw_text': 'Jello',
                            'action': {'kind': 'video', 'target': 'jello.mp4', 'type': 'play_title'},
                            'link_action': {'kind': 'slide', 'target': 'slide2'},
                        },
                        {
                            'id': 'Extras',
                            'label': 'Extra features',
                            'raw_text': 'Extra features',
                            'action': {'kind': 'unresolved', 'raw': 'Extra features', 'target_label': 'Extra features'},
                            'parse_warnings': [],
                        },
                    ],
                },
                {'id': 'slide2', 'buttons': []},
            ],
            'match_warnings': [],
        }

        repair_conflicting_slide_links(model)

        extras = model['slides'][0]['buttons'][1]
        self.assertEqual(extras['action']['kind'], 'slide')
        self.assertEqual(extras['action']['target'], 'slide2')
        self.assertTrue(extras['action']['inferred_from_conflicting_link'])
        self.assertTrue(any('inferred slide target "slide2"' in w for w in extras['parse_warnings']))

    def test_html_preview_uses_model_directory_as_asset_root(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            model_dir = tmp / 'xlets' / 'grin_samples' / 'Scripts' / 'PptxMenu'
            model_dir.mkdir(parents=True)
            project_dir = tmp / 'project'
            project_dir.mkdir()
            model_path = model_dir / 'menu-model.json'
            output = project_dir / 'menu-preview.html'
            model = {
                'source': str(project_dir / 'menu.pptx'),
                'slides': [
                    {
                        'id': 'slide1',
                        'title': 'Main Menu',
                        'buttons': [
                            {
                                'id': 'Play',
                                'label': 'Play',
                                'action': {'kind': 'video', 'target': 'movie.mp4'},
                                'hitbox_px': {'x': 0, 'y': 0, 'w': 100, 'h': 50},
                            }
                        ],
                        'background': {'file': 'assets/slide1_bg.png', 'width': 1920, 'height': 1080},
                    }
                ],
                'videos': {'movie.mp4': 'movie.mp4'},
                'coordinate_spaces': {'rendered_px': {'width': 1920, 'height': 1080}},
            }
            model_path.write_text(json.dumps(model))

            make_preview(model_path, output, project_dir)
            html = output.read_text()
            self.assertIn('"assetRoot": "../xlets/grin_samples/Scripts/PptxMenu"', html)


if __name__ == '__main__':
    unittest.main()
