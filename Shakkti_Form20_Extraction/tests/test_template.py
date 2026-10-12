import unittest
from types import SimpleNamespace

from form20.pipeline import choose_template


def page(offset, left=0, right=1000, columns=(0.0, 0.2, 0.4, 0.6, 1.0)):
    width = right - left
    return SimpleNamespace(left=left, right=right, col_candidates=[left + (u + offset) * width for u in columns])


class ChooseTemplateTests(unittest.TestCase):
    PAGES = [page(-0.006), page(0.0), page(0.006)]      # the scanner shifts the table a little on every page

    def test_default_vote_is_kept_when_no_expectation_is_given(self):
        template, vote = choose_template(self.PAGES)
        self.assertIsNone(vote)
        self.assertLess(len(template) - 1, 4)           # the strict vote splits the drifting lines and loses columns

    def test_looser_vote_is_tried_until_the_expected_column_count_appears(self):
        template, vote = choose_template(self.PAGES, expected_cols={4})
        self.assertEqual(len(template) - 1, 4)
        self.assertEqual(vote, (0.008, 0.6))

    def test_default_is_kept_when_it_already_matches(self):
        clean = [page(0.0), page(0.0), page(0.0)]
        template, vote = choose_template(clean, expected_cols={4})
        self.assertEqual((len(template) - 1, vote), (4, None))

    def test_default_is_kept_when_no_setting_reaches_an_expected_count(self):
        template, vote = choose_template(self.PAGES, expected_cols={9})
        self.assertIsNone(vote)


if __name__ == "__main__":
    unittest.main()
