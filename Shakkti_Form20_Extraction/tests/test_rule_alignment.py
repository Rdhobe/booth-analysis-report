import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from form20.grid import align_to_rules
from tests.test_grid_ocr import synthetic_table


def grid_for(xs, ys, shift=0, stretch=1.0):
    mid = np.mean(xs)
    edges = [int(round(stretch * (x - mid) + mid + shift)) for x in xs]
    return SimpleNamespace(col_edges=edges, data_edges=ys[7:15], total_edges=[], pitch=40.0)


class AlignToRulesTests(unittest.TestCase):
    def setUp(self):
        self.img, self.xs, self.ys = synthetic_table(rows=20, cols=6, digits=True)

    def test_columns_placed_off_the_rules_move_onto_them(self):
        grid = align_to_rules(self.img, grid_for(self.xs, self.ys, shift=18))
        for got, want in zip(grid.col_edges, self.xs):
            self.assertLessEqual(abs(got - want), 3)

    def test_a_stretched_placement_is_corrected_too(self):
        grid = align_to_rules(self.img, grid_for(self.xs, self.ys, shift=-10, stretch=1.006))
        for got, want in zip(grid.col_edges, self.xs):
            self.assertLessEqual(abs(got - want), 4)

    def test_a_table_five_percent_narrower_than_the_template_is_found(self):
        grid = align_to_rules(self.img, grid_for(self.xs, self.ys, shift=0, stretch=1 / 0.945))
        for got, want in zip(grid.col_edges, self.xs):
            self.assertLessEqual(abs(got - want), 5)

    def test_a_curved_page_is_not_a_straight_shift_each_edge_finds_its_own_rule(self):
        xs = self.xs
        bent = [int(x) for x in (np.array(xs) - np.array([0, 0, 0, 4, 12, 18, 20]))]      # left edges right, right ones 20 px off
        grid = align_to_rules(self.img, grid_for(bent, self.ys))
        for got, want in zip(grid.col_edges, xs):
            self.assertLessEqual(abs(got - want), 3)

    def test_an_edge_with_no_rule_near_it_keeps_its_place(self):
        img, xs, ys = synthetic_table(rows=20, cols=6, digits=True)
        cv2.line(img, (xs[3], ys[0] - 5), (xs[3], ys[-1] + 5), 255, 7)                    # the rule of edge 3 is missing
        grid = align_to_rules(img, grid_for(xs, ys, shift=12))
        self.assertLessEqual(abs(grid.col_edges[0] - xs[0]), 3)                           # the others find theirs
        self.assertLessEqual(abs(grid.col_edges[3] - (xs[3] + 12 - 12)), 14)              # it stays near where it was placed

    def test_a_grid_already_on_the_rules_is_left_alone(self):
        before = grid_for(self.xs, self.ys).col_edges
        self.assertEqual(align_to_rules(self.img, grid_for(self.xs, self.ys)).col_edges, before)

    def test_a_page_without_vertical_rules_keeps_its_edges(self):
        img, xs, ys = synthetic_table(rows=20, cols=6, digits=True)
        img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, np.ones((1, 1), np.uint8))
        for x in xs:
            cv2.line(img, (x, ys[0] - 5), (x, ys[-1] + 5), 255, 7)           # erase the vertical rules
        before = grid_for(xs, ys, shift=18).col_edges
        self.assertEqual(align_to_rules(img, grid_for(xs, ys, shift=18)).col_edges, before)


if __name__ == "__main__":
    unittest.main()
