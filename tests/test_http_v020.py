import unittest

from lughus.infra.http import same_origin_url, sse_events


class Response:
    def __init__(self, chunks):
        self.chunks = chunks

    def raise_for_status(self):
        pass

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk


class HttpTests(unittest.IsolatedAsyncioTestCase):
    def test_origin_pinning(self) -> None:
        self.assertEqual(same_origin_url("https://a.example/sse", "/rpc"), "https://a.example/rpc")
        for target in (
            "//b.example/rpc",
            "http://a.example/rpc",
            "https://a.example:444/rpc",
            "https://u:p@a.example/rpc",
        ):
            with self.assertRaises(ValueError):
                same_origin_url("https://a.example/sse", target)

    async def test_multiline_sse(self) -> None:
        response = Response([b"event: message\r\ndata: one\r\n", b"data: two\r\n\r\n"])
        self.assertEqual([x async for x in sse_events(response, 100)], [("message", "one\ntwo")])

    async def test_bounded_unterminated_sse(self) -> None:
        with self.assertRaises(ValueError):
            _ = [x async for x in sse_events(Response([b"a" * 1000]), 10)]
