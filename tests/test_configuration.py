"""Check the source overlay and the generated server configuration."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS_ARGS = ["--matrix-host", "chat.example.net", "--bundle-id", "net.example.sovereignchat", "--team-id", "ABCD123456"]
SERVER_ARGS = ["--matrix-host", "chat.example.net", "--rtc-host", "rtc.example.net", "--media-ip", "192.0.2.20"]


def run(script, *args):
    return subprocess.run([sys.executable, str(ROOT / script), *args], capture_output=True, text=True)


def json_file(path):
    return json.loads(path.read_text())


class ConfigurationTests(unittest.TestCase):
    def test_build_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            for push, lock_screen in ((False, False), (True, False), (True, True)):
                project = Path(directory) / f"project-{push}-{lock_screen}"
                flags = (["--push"] if push else []) + (["--lock-screen-calls"] if lock_screen else [])
                result = run("prepare_ios.py", *IOS_ARGS, *flags, "--output", str(project))
                self.assertEqual(result.returncode, 0, result.stderr)
                configuration = (project / "ElementX/Sources/Application/Settings/SovereignConfiguration.swift").read_text()
                self.assertIn('static let homeserverURL: URL = "https://chat.example.net"', configuration)
                self.assertIn(f"static let pushEnabled = {str(push).lower()}", configuration)
                app = (project / "app.yml").read_text()
                self.assertIn("APP_GROUP_IDENTIFIER: group.net.example.sovereignchat", app)
                target = (project / "ElementX/SupportingFiles/target.yml").read_text()
                self.assertEqual("aps-environment: $(SOVEREIGN_APS_ENVIRONMENT)" in target, push)
                self.assertNotIn("applinks:element.io", target)
                nse = (project / "NSE/SupportingFiles/target.yml").read_text()
                self.assertEqual("com.apple.developer.usernotifications.filtering: true" in nse, lock_screen)
                driver = (project / "ElementX/Sources/Services/ElementCall/ElementCallWidgetDriver.swift").read_text()
                self.assertIn("return .failure(.encryptionRequired)", driver)
                self.assertIn("encryption: .perParticipantKeys", driver)
                self.assertNotIn(".unencrypted", driver)
                self.assertNotIn("https://", (project / "Components/Secrets/Secrets.swift").read_text())

    def test_lock_screen_option_requires_push(self):
        result = run("prepare_ios.py", *IOS_ARGS, "--lock-screen-calls")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --push", result.stderr)

    def test_server_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            result = run("prepare_server.py", *SERVER_ARGS, "--output", str(state))
            self.assertEqual(result.returncode, 0, result.stderr)
            synapse = json_file(state / "synapse/homeserver.json")
            livekit = json_file(state / "livekit/livekit.json")
            self.assertFalse(synapse["enable_registration"])
            self.assertFalse(synapse["report_stats"])
            self.assertFalse(synapse["push"]["enabled"])
            self.assertEqual(synapse["federation_domain_whitelist"], [])
            self.assertEqual(synapse["matrix_rtc"]["transports"], [{"type": "livekit", "url": "wss://rtc.example.net"}])
            self.assertEqual(livekit["rtc"]["stun_servers"], ["rtc.example.net:3478"])
            self.assertFalse(livekit["room"]["auto_create"])
            self.assertEqual(json_file(state / "rtc-auth/registration.json"), json_file(state / "synapse/rtc-appservice.json"))
            self.assertFalse((state / "synapse/homeserver.json").stat().st_mode & 0o077)
            caddy = (state / "caddy/Caddyfile").read_text()
            self.assertIn("remote_ip 172.30.196.11", caddy)
            self.assertNotIn("@TLS_DIRECTIVE@", caddy)
            self.assertFalse((state / "push/sygnal.json").exists())

    def test_push_generation_separates_testflight_and_development(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            fixture = path / "fixture.p8"
            fixture.write_bytes(b"-----BEGIN PRIVATE KEY-----\nfixture-only")
            state = path / "state"
            result = run(
                "prepare_server.py", *SERVER_ARGS, "--output", str(state),
                "--bundle-id", "net.example.sovereignchat", "--team-id", "ABCD123456",
                "--apns-key-id", "ABCD123457", "--apns-key-file", str(fixture),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            synapse = json_file(state / "synapse/homeserver.json")
            self.assertEqual(synapse["push"], {"enabled": True, "include_content": False})
            self.assertEqual(synapse["ip_range_whitelist"], ["172.30.196.12/32"])
            apps = json_file(state / "push/sygnal.json")["apps"]
            self.assertEqual(apps["net.example.sovereignchat.ios.dev"]["platform"], "sandbox")
            self.assertEqual(apps["net.example.sovereignchat.ios.prod"]["platform"], "production")
            self.assertFalse((state / "push/AuthKey.p8").stat().st_mode & 0o077)


if __name__ == "__main__":
    unittest.main()
