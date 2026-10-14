import unittest

from threads_post_screenshot import check_url


class UrlTest(unittest.TestCase):
    def test_only_post_urls(self):
        for url in (
            "https://www.threads.com/share/ExampleShare/",
            "https://www.threads.com/@example/post/ExamplePost",
        ):
            check_url(url)
        for url in (
            "https://www.threads.com/",
            "https://www.threads.com/@example",
            "https://example.com/@example/post/ExamplePost",
        ):
            with self.assertRaises(ValueError):
                check_url(url)


if __name__ == "__main__":
    unittest.main()
