from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from button_action_parser import parse_button_action, parse_timestamp, split_display_action


def videos():
    return {
        'main feature.mp4': 'Main Feature.mp4',
        'main feature': 'Main Feature.mp4',
        'main feature final export.mp4': 'Main Feature.mp4',
        'main feature final export': 'Main Feature.mp4',
        'just friends 2005 720p mp4': 'Just.Friends.2005.720p.mp4',
        'just friends 2005 720p': 'Just.Friends.2005.720p.mp4',
        'trailer final export.mov': 'Trailer Final Export.mov',
        'trailer final export': 'Trailer Final Export.mov',
    }


class PptxActionParserGrammarV1Tests(unittest.TestCase):
    def parse_raw(self, raw: str, video_map=None):
        display_text, action_text, split_warnings = split_display_action(raw)
        action, parse_warnings = parse_button_action(action_text, video_map or videos())
        return display_text, action_text, action, split_warnings + parse_warnings

    def test_simple_filename_match(self):
        display, action_text, action, warnings = self.parse_raw('Main Feature')
        self.assertEqual(display, 'Main Feature')
        self.assertEqual(action_text, 'Main Feature')
        self.assertEqual(action['kind'], 'video')
        self.assertEqual(action['target'], 'Main Feature.mp4')
        self.assertEqual(action['video_file'], 'Main Feature.mp4')
        self.assertEqual(warnings, [])

    def test_fuzzy_filename_match_still_works(self):
        display, _, action, warnings = self.parse_raw('Just Friends')
        self.assertEqual(display, 'Just Friends')
        self.assertEqual(action['target'], 'Just.Friends.2005.720p.mp4')
        self.assertTrue(any('partial label match' in w for w in warnings))

    def test_display_override_with_video(self):
        display, action_text, action, warnings = self.parse_raw('Play Movie | Main Feature')
        self.assertEqual(display, 'Play Movie')
        self.assertEqual(action_text, 'Main Feature')
        self.assertEqual(action['target'], 'Main Feature.mp4')
        self.assertEqual(warnings, [])

    def test_timestamp_formats(self):
        cases = {'1:00:30': 3630, '01:00:30': 3630, '12:15': 735, '75s': 75, '1h00m30s': 3630}
        for raw, seconds in cases.items():
            with self.subTest(raw=raw):
                parsed_seconds, timecode = parse_timestamp(raw)
                self.assertEqual(parsed_seconds, seconds)
                self.assertRegex(timecode, r'^\d{2}:\d{2}:\d{2}$')

    def test_timestamp_action_infers_display(self):
        display, _, action, _ = self.parse_raw('Main Feature@1:00:30')
        self.assertEqual(display, 'Main Feature')
        self.assertEqual(action['start_time_seconds'], 3630)
        self.assertEqual(action['start_time'], '01:00:30')

    def test_display_override_with_timestamp(self):
        display, _, action, _ = self.parse_raw('Start at Big Reveal | Main Feature@1:00:30')
        self.assertEqual(display, 'Start at Big Reveal')
        self.assertEqual(action['target'], 'Main Feature.mp4')
        self.assertEqual(action['start_time'], '01:00:30')

    def test_chapter_name(self):
        display, _, action, _ = self.parse_raw('Finale | Main Feature#Finale')
        self.assertEqual(display, 'Finale')
        self.assertEqual(action['target'], 'Main Feature.mp4')
        self.assertEqual(action['chapter'], 'Finale')

    def test_chapter_number(self):
        display, _, action, _ = self.parse_raw('Chapter 4 | Main Feature#4')
        self.assertEqual(display, 'Chapter 4')
        self.assertEqual(action['target'], 'Main Feature.mp4')
        self.assertEqual(action['chapter'], 4)

    def test_goto_alias(self):
        display, _, action, _ = self.parse_raw('Bonus Features | goto:Extras')
        self.assertEqual(display, 'Bonus Features')
        self.assertEqual(action['kind'], 'slide')
        self.assertEqual(action['target'], 'Extras')

    def test_menu_alias(self):
        _, _, action, _ = self.parse_raw('Bonus Features | menu:Extras')
        self.assertEqual(action['kind'], 'slide')
        self.assertEqual(action['target'], 'Extras')

    def test_slide_alias(self):
        _, _, action, _ = self.parse_raw('Bonus Features | slide:Extras')
        self.assertEqual(action['kind'], 'slide')
        self.assertEqual(action['target'], 'Extras')

    def test_builtin_actions(self):
        for raw, name in [('Return Home | main', 'main'), ('Go Back | back', 'back'), ('Top | top menu', 'top_menu'), ('Watch Everything | play all', 'play_all')]:
            with self.subTest(raw=raw):
                display, _, action, warnings = self.parse_raw(raw)
                self.assertTrue(display)
                self.assertEqual(action['kind'], 'builtin')
                self.assertEqual(action['name'], name)
                self.assertEqual(warnings, [])

    def test_disabled_and_none(self):
        for raw, display in [('disabled', 'Disabled'), ('none', 'None'), ('Coming Soon | disabled', 'Coming Soon')]:
            with self.subTest(raw=raw):
                parsed_display, _, action, warnings = self.parse_raw(raw)
                self.assertEqual(parsed_display, display)
                self.assertEqual(action['kind'], 'builtin')
                self.assertIn(action['name'], ('disabled', 'none'))
                self.assertEqual(warnings, [])

    def test_exact_file_target(self):
        display, _, action, warnings = self.parse_raw('Trailer | file:Trailer Final Export.mov')
        self.assertEqual(display, 'Trailer')
        self.assertEqual(action['kind'], 'video')
        self.assertEqual(action['target'], 'Trailer Final Export.mov')
        self.assertTrue(action['exact_file'])
        self.assertEqual(warnings, [])

    def test_malformed_pipe_empty_action(self):
        display, action_text, action, warnings = self.parse_raw('Play Movie | ')
        self.assertEqual(display, 'Play Movie')
        self.assertEqual(action_text, 'none')
        self.assertEqual(action['kind'], 'builtin')
        self.assertEqual(action['name'], 'none')
        self.assertTrue(any('empty action after pipe' in w for w in warnings))

    def test_empty_display_side_infers_display(self):
        display, action_text, action, warnings = self.parse_raw(' | Main Feature')
        self.assertEqual(display, 'Main Feature')
        self.assertEqual(action_text, 'Main Feature')
        self.assertEqual(action['target'], 'Main Feature.mp4')
        self.assertTrue(any('empty display text' in w for w in warnings))

    def test_ambiguous_video_matches_produce_parse_warnings(self):
        ambiguous = {
            'main feature theatrical.mp4': 'Main Feature Theatrical.mp4',
            'main feature theatrical': 'Main Feature Theatrical.mp4',
            'main feature extended.mp4': 'Main Feature Extended.mp4',
            'main feature extended': 'Main Feature Extended.mp4',
        }
        _, _, action, warnings = self.parse_raw('Main Feature', ambiguous)
        self.assertEqual(action['kind'], 'unresolved')
        self.assertTrue(any('ambiguous video target' in w for w in warnings))

    def test_old_button_text_matching_remains_backward_compatible(self):
        display, action_text, action, warnings = self.parse_raw('Main Feature Final Export')
        self.assertEqual(display, 'Main Feature Final Export')
        self.assertEqual(action_text, 'Main Feature Final Export')
        self.assertEqual(action['target'], 'Main Feature.mp4')
        self.assertEqual(warnings, [])


if __name__ == '__main__':
    unittest.main()
