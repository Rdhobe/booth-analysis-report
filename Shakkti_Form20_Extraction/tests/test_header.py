import unittest
from types import SimpleNamespace

import numpy as np

from form20.header import title_text


class TitleTextTests(unittest.TestCase):
    def test_table_at_the_very_top_of_the_page_gives_empty_title_instead_of_crashing(self):
        page = np.full((200, 300), 255, np.uint8)
        for header_top in (0, 3, 11):          # 11 - 4 = 7 rows: still too little to hold a title
            self.assertEqual(title_text(page, SimpleNamespace(header_top=header_top)), "")


if __name__ == "__main__":
    unittest.main()
