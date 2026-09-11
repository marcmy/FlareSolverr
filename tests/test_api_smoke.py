import unittest

from webtest import TestApp

import flaresolverr


class TestLocalApiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = TestApp(flaresolverr.app)

    def test_health_endpoint(self):
        response = self.app.get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.json["status"])

    def test_unknown_endpoint_returns_json_404(self):
        response = self.app.get("/not-a-real-endpoint", status=404)

        self.assertEqual(404, response.status_code)
        self.assertEqual(404, response.json["status_code"])

    def test_v1_requires_command(self):
        response = self.app.post_json("/v1", {}, status=500)

        self.assertEqual("error", response.json["status"])
        self.assertEqual("Error: Request parameter 'cmd' is mandatory.", response.json["message"])

    def test_v1_rejects_unknown_command(self):
        response = self.app.post_json(
            "/v1",
            {"cmd": "request.bad"},
            status=500,
        )

        self.assertEqual("error", response.json["status"])
        self.assertEqual("Error: Request parameter 'cmd' = 'request.bad' is invalid.", response.json["message"])

    def test_request_get_requires_url(self):
        response = self.app.post_json(
            "/v1",
            {"cmd": "request.get"},
            status=500,
        )

        self.assertEqual("error", response.json["status"])
        self.assertEqual(
            "Error: Request parameter 'url' is mandatory in 'request.get' command.",
            response.json["message"],
        )

    def test_request_post_requires_post_data(self):
        response = self.app.post_json(
            "/v1",
            {"cmd": "request.post", "url": "https://example.invalid/"},
            status=500,
        )

        self.assertEqual("error", response.json["status"])
        self.assertEqual(
            "Error: Request parameter 'postData' is mandatory in 'request.post' command.",
            response.json["message"],
        )


if __name__ == "__main__":
    unittest.main()
