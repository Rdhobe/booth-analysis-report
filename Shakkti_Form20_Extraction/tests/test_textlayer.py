import tempfile
import unittest
from pathlib import Path

import fitz

from form20.grid import apply_template, build_col_template
from form20.textlayer import open_text_doc

COLS = [300 + 50 * j for j in range(8)]             # x (points) of the eight numeric columns
ROWS_PER_PAGE, PAGES = 25, 2


def make_pdf(path, blank_after=None, wrap_every=0, scan_like=False):
    """A typed Form 20-like PDF: serial | name (text, some ending in a digit) | eight numeric columns."""
    doc = fitz.open()
    expected = []
    for p in range(PAGES):
        page = doc.new_page(width=792, height=612)
        y = 60.0
        for i in range(ROWS_PER_PAGE):
            serial = p * ROWS_PER_PAGE + i + 1
            vals = [(serial * (j + 3)) % 997 + j for j in range(8)]
            expected.append((serial, vals))
            if scan_like:
                y += 14
                continue
            page.insert_text((30, y), str(serial), fontsize=8)
            page.insert_text((60, y), "School" if i % 3 else f"School room {i % 4}", fontsize=8)   # digits in names
            for j, (x, v) in enumerate(zip(COLS, vals)):
                if blank_after is not None and j >= blank_after:
                    x += 50                                  # one column's width left empty
                page.insert_text((x + (j % 2) * 2, y + (j % 3) * 0.5), str(v), fontsize=8)   # a little baseline jitter
            y += 14 + (6 if wrap_every and i % wrap_every == wrap_every - 1 else 0)
    doc.save(path)
    doc.close()
    return expected


class TextLayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "t.pdf")

    def tearDown(self):
        self.tmp.cleanup()

    def test_columns_rows_and_cells_are_read_exactly(self):
        expected = make_pdf(self.path)
        td = open_text_doc(self.path)
        self.assertIsNotNone(td)
        self.assertEqual(len(td.centres), 9)                    # serial + eight numeric columns; name digits are no column
        pl = td.page_lines(0)
        self.assertEqual(len(pl.data_edges) - 1, ROWS_PER_PAGE)
        grid = apply_template(pl, build_col_template([pl, td.page_lines(1)]))
        table = td.reader(0)(None, grid, grid.data_edges)
        self.assertEqual(len(table), ROWS_PER_PAGE)
        for row, (serial, vals) in zip(table, expected):
            self.assertEqual(row[0].text, str(serial))          # the digit in the name does not reach the serial cell
            self.assertEqual([c.text for c in row[1:]], [str(v) for v in vals])

    def test_digits_ending_every_station_name_are_not_a_column(self):
        doc = fitz.open()
        for p in range(2):
            page = doc.new_page(width=792, height=612)
            for i in range(25):
                y = 60.0 + 14 * i
                page.insert_text((30, y), str(p * 25 + i + 1), fontsize=8)
                page.insert_text((60, y), "PRIMARY SCHOOL NO.", fontsize=8)
                end = 60 + fitz.get_text_length("PRIMARY SCHOOL NO. ", fontsize=8)
                page.insert_text((end, y), str(1 + i % 3), fontsize=8)                         # the name's own digit, every row
                for j, x in enumerate(COLS):
                    page.insert_text((x, y), str((i * (j + 3)) % 97 + j), fontsize=8)
        doc.save(self.path)
        doc.close()
        td = open_text_doc(self.path)
        self.assertEqual(len(td.centres), 9)                    # serial + eight numeric columns, no ninth from the names

    def test_taller_rows_do_not_break_the_table(self):
        make_pdf(self.path, wrap_every=4)
        td = open_text_doc(self.path)
        self.assertEqual(len(td.page_lines(0).data_edges) - 1, ROWS_PER_PAGE)

    def test_a_column_with_no_numbers_is_inserted_where_a_gap_shows_it(self):
        make_pdf(self.path, blank_after=4)
        self.assertEqual(len(open_text_doc(self.path).centres), 10)        # serial + eight numeric + one empty

    def test_partial_text_layer_is_refused_when_the_official_count_needs_more_columns(self):
        make_pdf(self.path)
        self.assertIsNone(open_text_doc(self.path, {20, 21, 22}))           # nine columns found, about twenty needed
        self.assertIsNotNone(open_text_doc(self.path, {10, 11, 12}))

    def test_a_page_without_numbers_is_not_a_table_page(self):
        make_pdf(self.path, scan_like=True)
        self.assertIsNone(open_text_doc(self.path))

    def test_grid_with_another_column_count_is_refused(self):
        make_pdf(self.path)
        td = open_text_doc(self.path)
        pl = td.page_lines(0)
        grid = apply_template(pl, build_col_template([pl]))
        grid.col_edges = grid.col_edges[:-2]
        with self.assertRaises(ValueError):
            td.reader(0)(None, grid, grid.data_edges)


if __name__ == "__main__":
    unittest.main()
