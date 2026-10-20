import time
import unittest

from corpus import actual_ratio, build_growth, build_pair, build_text, estimate_tokens


class CorpusTests(unittest.TestCase):
    def test_deterministic_and_suffix_prefix(self):
        a = build_text(1000, tag="alpha")
        self.assertEqual(a, build_text(1000, tag="alpha"))
        cold, warm = build_pair(1000, "alpha", 1)
        self.assertTrue(warm.startswith(cold))
        self.assertEqual(warm[:-5], cold)
        self.assertNotEqual(warm, cold)
        self.assertLess(abs(len(warm) - len(cold)), 32)

    def test_growth_prefixes(self):
        values = build_growth([100, 200, 500], "g")
        self.assertEqual(len(values), 3)
        for first, later in zip(values, values[1:]):
            self.assertTrue(later.startswith(first))
            self.assertGreater(len(later), len(first))

    def test_sizes_ascii_and_speed(self):
        for tokens in (1000, 4000, 16000, 32000):
            text = build_text(tokens, tag="scale")
            size = len(text.encode("utf-8"))
            expected = tokens * 4.6
            self.assertLessEqual(abs(size - expected), expected * .05)
            self.assertTrue(text.isascii())
        start = time.monotonic()
        build_text(32000, tag="speed")
        self.assertLess(time.monotonic() - start, 2)

    def test_helpers(self):
        self.assertEqual(estimate_tokens("abcd", 4), 1)
        self.assertEqual(actual_ratio(20, 4), 5)


if __name__ == "__main__":
    unittest.main()
