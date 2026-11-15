import unittest

from crawler.email_util import normalize_email


class EmailBoundaries(unittest.TestCase):
    def test_separate_phone_and_education_date(self):
        self.assertEqual(normalize_email('ljcai@hnu.edu.cn 0731-88821513'), 'ljcai@hnu.edu.cn')
        self.assertEqual(normalize_email('luxh@jlu.edu.cn 2000.09-2003.06'), 'luxh@jlu.edu.cn')

    def test_do_not_guess_glued_domain(self):
        for value in ('wangw@whu.edu.cn2', 'x@hnu.edu.cn13800000000', 'x@jlu.edu.cnWechat'):
            self.assertIsNone(normalize_email(value))

    def test_explicit_obfuscation_and_split_address(self):
        self.assertEqual(normalize_email('jxuan@whu_.dot._edu_.dot._cn'), 'jxuan@whu.edu.cn')
        self.assertEqual(normalize_email('alice AT example DOT edu'), 'alice@example.edu')
        self.assertEqual(normalize_email('alice @ example.edu'), 'alice@example.edu')


if __name__ == '__main__':
    unittest.main()
