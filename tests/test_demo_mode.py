import os
import unittest
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from demo_mode import configure_demo_mode


class DemoModeTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "DEMO_MODE": "true",
            "FLASK_SECRET_KEY": "test-secret",
            "DEMO_USERNAME": "demo",
            "DEMO_PASSWORD_HASH": generate_password_hash("demo-pass"),
            "DEMO_COOKIE_SECURE": "false",
        }, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.app = Flask(__name__, template_folder="../templates")
        self.app.secret_key = os.environ["FLASK_SECRET_KEY"]
        self.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.handler_calls = 0

        @self.app.route("/")
        def menu():
            return "menu"

        @self.app.route("/tenant-overview")
        def tenant_overview():
            raise AssertionError("The production read handler must not run in demo mode.")

        @self.app.route("/create-tag", methods=["POST"])
        def create_tag():
            self.handler_calls += 1
            return "created"

        configure_demo_mode(self.app)
        self.client = self.app.test_client()

    def test_local_cookie_can_be_sent_over_http(self):
        self.assertFalse(self.app.config["SESSION_COOKIE_SECURE"])

    def login(self):
        self.client.get("/demo/login")
        with self.client.session_transaction() as demo_session:
            csrf_token = demo_session["demo_login_csrf"]
        return self.client.post("/demo/login", data={
            "username": "demo",
            "password": "demo-pass",
            "csrf_token": csrf_token,
            "return_to": "/",
        })

    def test_protected_page_requires_login(self):
        response = self.client.get("/tenant-overview")

        self.assertEqual(302, response.status_code)
        self.assertIn("/demo/login", response.headers["Location"])

    def test_valid_login_uses_demo_provider(self):
        response = self.login()
        self.assertEqual(302, response.status_code)

        overview = self.client.get("/tenant-overview")

        self.assertEqual(200, overview.status_code)
        self.assertIn(b"Finance Analytics", overview.data)
        self.assertIn(b"Demo environment", overview.data)

    def test_parallel_login_get_does_not_invalidate_form_csrf(self):
        self.client.get("/demo/login")
        with self.client.session_transaction() as demo_session:
            csrf_token = demo_session["demo_login_csrf"]
        self.client.get("/demo/login?return_to=/favicon.ico")

        response = self.client.post("/demo/login", data={
            "username": "demo",
            "password": "demo-pass",
            "csrf_token": csrf_token,
            "return_to": "/",
        })

        self.assertEqual(302, response.status_code)

    def test_write_is_blocked_before_handler(self):
        self.login()

        response = self.client.post("/create-tag", json={"displayName": "New"})

        self.assertEqual(403, response.status_code)
        self.assertEqual(0, self.handler_calls)

    def test_invalid_password_is_rejected(self):
        self.client.get("/demo/login")
        with self.client.session_transaction() as demo_session:
            csrf_token = demo_session["demo_login_csrf"]

        response = self.client.post("/demo/login", data={
            "username": "demo",
            "password": "wrong",
            "csrf_token": csrf_token,
            "return_to": "/",
        })

        self.assertEqual(401, response.status_code)


if __name__ == "__main__":
    unittest.main()