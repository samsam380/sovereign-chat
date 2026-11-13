"""Exercise generated configuration against a local Synapse 1.165.0 process."""

import argparse
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
HOST = "chat.example.net"
API = "/_matrix/client/v3"
PASSWORD = "Smoke test account password 42"
SENDER = "smoke-user-1"
RECIPIENT = "smoke-user-2"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(port, method, path, payload=None, token=None):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        client.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=headers)
        response = client.getresponse()
        return response.status, json.loads(response.read())
    finally:
        client.close()


class RTCProbe(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        response = json.dumps({
            "user": self.headers.get("X-Matrix-User-Identifier"),
            "path": self.path,
        }).encode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def register(port, username, secret):
    path = "/_synapse/admin/v1/register"
    status, data = request(port, "GET", path)
    assert status == 200, (status, data)
    nonce = data["nonce"]
    sign = "\0".join((nonce, username, PASSWORD, "notadmin"))
    mac = hmac.new(secret.encode(), sign.encode(), hashlib.sha1).hexdigest()
    status, reply = request(port, "POST", path, {
        "nonce": nonce, "username": username, "password": PASSWORD,
        "admin": False, "mac": mac,
    })
    assert status == 200, status
    return reply["access_token"]


def exercise(port, secret):
    status, _ = request(port, "POST", f"{API}/register", {"username": "visitor", "password": PASSWORD})
    assert status == 403, status
    token = register(port, SENDER, secret)
    register(port, RECIPIENT, secret)
    status, _ = request(port, "POST", f"{API}/createRoom", {"visibility": "public"}, token)
    assert status == 403, status
    status, room = request(port, "POST", f"{API}/createRoom", {
        "preset": "trusted_private_chat", "is_direct": True, "invite": [f"@{RECIPIENT}:{HOST}"],
    }, token)
    assert status == 200, (status, room)
    room_id = quote(room["room_id"], safe="")
    room_api = f"{API}/rooms/{room_id}"
    status, encryption = request(port, "GET", f"{room_api}/state/m.room.encryption", token=token)
    assert (status, encryption) == (200, {"algorithm": "m.megolm.v1.aes-sha2"}), (status, encryption)
    status, creation = request(port, "GET", f"{room_api}/state/m.room.create", token=token)
    assert status == 200 and creation["m.federate"] is False, (status, creation)
    status, _ = request(port, "PUT", f"{room_api}/send/m.room.message/probe", {
        "msgtype": "m.text", "body": "Plaintext test",
    }, token)
    assert status == 403, status

    status, transports = request(port, "GET", "/_matrix/client/v1/rtc/transports", token=token)
    assert status == 200 and transports["transports"] == [{"type": "livekit", "url": "wss://rtc.example.net"}]
    rtc_path = "/_matrix/client/unstable/io.element.msc4195/rtc/livekit/get_token"
    status, _ = request(port, "POST", rtc_path, {"room_id": room["room_id"]})
    assert status == 401, status
    status, proxied = request(port, "POST", rtc_path, {"room_id": room["room_id"]}, token)
    assert (status, proxied) == (200, {"user": f"@{SENDER}:{HOST}", "path": rtc_path}), (status, proxied)


def smoke(python, directory, rtc_probe):
    directory = Path(directory)
    state = directory / "state"
    subprocess.run([
        sys.executable, str(ROOT / "prepare_server.py"), "--matrix-host", HOST,
        "--rtc-host", "rtc.example.net", "--media-ip", "192.0.2.20", "--output", str(state),
    ], check=True, stdout=subprocess.DEVNULL)
    target = state / "synapse"
    config = target / "homeserver.json"
    config.write_text(config.read_text().replace("/state/", f"{target}/"))
    configuration = json.loads(config.read_text())
    port = free_port()
    configuration["listeners"][0].update({"port": port, "bind_addresses": ["127.0.0.1"]})
    config.write_text(json.dumps(configuration))
    registration = target / "rtc-appservice.json"
    registration.write_text(registration.read_text().replace("http://rtc-auth:8080", f"http://127.0.0.1:{rtc_probe.server_port}"))
    env = os.environ | {"PYTHONPATH": str(ROOT / "server"), "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [python, "-m", "synapse.app.homeserver", "-c", str(config)]
    subprocess.run([*cmd, "--generate-keys"], env=env, check=True, capture_output=True)
    with (directory / "synapse.log").open("w+") as log:
        process = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Synapse stopped during startup.")
                try:
                    if request(port, "GET", "/_matrix/client/versions")[0] == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Synapse did not start within ten seconds.")
            exercise(port, configuration["registration_shared_secret"])
        except BaseException:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            process.terminate()
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synapse-python", default=sys.executable)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", 0), RTCProbe) as probe:
        thread = threading.Thread(target=probe.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="sovereign-ios-smoke-") as workspace:
                smoke(args.synapse_python, workspace, probe)
        finally:
            probe.shutdown()
            thread.join()
    print("Verified private E2EE room creation, plaintext refusal and authenticated MatrixRTC proxying.")


if __name__ == "__main__":
    main()
