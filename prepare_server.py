#!/usr/bin/env python3
"""Generate a dedicated Synapse, MatrixRTC and optional Apple push configuration."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile

from settings import apple_identifier, bundle_id, host

ROOT = Path(__file__).resolve().parent


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def media_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as error:
        raise argparse.ArgumentTypeError("Use an IPv4 address the phones can reach for media.") from error
    if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_link_local:
        raise argparse.ArgumentTypeError("Use a routable LAN or public IPv4 address.")
    return str(address)


def subnet(value):
    try:
        network = ipaddress.IPv4Network(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use a private IPv4 /24 subnet.") from error
    private = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
    if network.prefixlen != 24 or not any(network.subnet_of(ipaddress.IPv4Network(block)) for block in private):
        raise argparse.ArgumentTypeError("Use a private IPv4 /24 subnet.")
    return network


def homeserver(args, push_ip):
    return {
        "server_name": args.matrix_host,
        "public_baseurl": f"https://{args.matrix_host}/",
        "listeners": [{
            "type": "http", "port": 8008, "tls": False, "x_forwarded": True,
            "bind_addresses": ["0.0.0.0"],
            "resources": [{"names": ["client"], "compress": False}],
        }],
        "database": {"name": "sqlite3", "args": {"database": "/state/homeserver.db"}},
        "signing_key_path": "/state/signing.key",
        "log_config": "/state/logging.json",
        "registration_shared_secret": secrets.token_urlsafe(48),
        "macaroon_secret_key": secrets.token_urlsafe(48),
        "form_secret": secrets.token_urlsafe(48),
        "media_store_path": "/state/media",
        "enable_registration": False,
        "enable_3pid_lookup": False,
        "allow_guest_access": False,
        "allow_public_rooms_without_auth": False,
        "allow_public_rooms_over_federation": False,
        "allow_profile_lookup_over_federation": False,
        "report_stats": False,
        "url_preview_enabled": False,
        "trusted_key_servers": [],
        "federation_domain_whitelist": [],
        "federation_sender_instances": [],
        "presence": {"enabled": False},
        "push": {"enabled": bool(args.apns_key_file), "include_content": False},
        "ip_range_whitelist": [f"{push_ip}/32"] if args.apns_key_file else [],
        "encryption_enabled_by_default_for_room_type": "all",
        "app_service_config_files": ["/state/rtc-appservice.json"],
        "experimental_features": {
            "msc4075_enabled": True, "msc4143_enabled": True, "msc4502_enabled": True,
            "msc4512_enabled": True,
        },
        "matrix_rtc": {"transports": [{"type": "livekit", "url": f"wss://{args.rtc_host}"}]},
        "max_event_delay_duration": "24h",
        "rc_message": {"per_second": 0.5, "burst_count": 30},
        "rc_delayed_event_mgmt": {"per_second": 1, "burst_count": 20},
        "modules": [{
            "module": "room_policy.PrivateEncryptedRooms",
            "config": {"server_name": args.matrix_host},
        }],
    }


def livekit_config(args, key, secret):
    return {
        "port": 7880,
        "rtc": {
            "tcp_port": 7881, "udp_port": 7882, "use_external_ip": False,
            "node_ip": args.media_ip, "stun_servers": [f"{args.rtc_host}:3478"],
        },
        "keys": {key: secret},
        "room": {"auto_create": False},
        "turn": {"enabled": True, "udp_port": 3478, "tls_port": 0},
        "webhook": {"api_key": key, "urls": ["http://rtc-auth:8080/sfu_webhook"]},
        "logging": {"level": "warn"},
    }


def rtc_registration(server_name):
    return {
        "id": "sovereign-chat-rtc",
        "as_token": secrets.token_urlsafe(48),
        "hs_token": secrets.token_urlsafe(48),
        "sender_localpart": "_sovereign_chat_rtc",
        "namespaces": {"users": [{"exclusive": False, "regex": f"^@[^:]+:{re.escape(server_name)}$"}]},
        "url": None,
        "io.element.msc4502.scopes": ["urn:matrix:client:io.element.msc4502:rooms:is_joined"],
        "io.element.msc4512.proxy_prefix": "rtc/livekit",
        "io.element.msc4512.proxy_url": "http://rtc-auth:8080",
    }


def write_push(directory, args):
    key = args.apns_key_file.read_bytes()
    if len(key) > 4096 or not key.startswith(b"-----BEGIN PRIVATE KEY-----"):
        raise ValueError("Provide the APNs .p8 private key file from your Apple Developer account.")
    (directory / "AuthKey.p8").write_bytes(key)
    apps = {}
    for suffix, platform in (("dev", "sandbox"), ("prod", "production")):
        apps[f"{args.bundle_id}.ios.{suffix}"] = {
            "type": "apns",
            "keyfile": "/state/AuthKey.p8",
            "key_id": args.apns_key_id,
            "team_id": args.team_id,
            "topic": args.bundle_id,
            "platform": platform,
            "push_counts": False,
        }
    write_json(directory / "sygnal.json", {
        "http": {"bind_addresses": ["0.0.0.0"], "port": 5000},
        "apps": apps,
    })


def prepare(args):
    state = args.output.resolve()
    if state.exists():
        raise ValueError(f"{state} already exists. Choose a new state directory.")
    if ipaddress.IPv4Address(args.media_ip) in args.subnet:
        raise ValueError("The media address must be outside the internal Docker subnet.")
    if any(char in str(state) for char in ("\n", "\r", ":", "'", "$")):
        raise ValueError("Use a state path without colons, line breaks, apostrophes, or dollar signs.")
    state.parent.mkdir(parents=True, exist_ok=True)
    auth_ip, push_ip = str(args.subnet[11]), str(args.subnet[12])
    with tempfile.TemporaryDirectory(prefix=".sovereign-server-", dir=state.parent) as workspace:
        build = Path(workspace) / "state"
        build.mkdir(mode=0o700)
        for name in ("synapse", "rtc-auth", "livekit", "caddy", "push"):
            (build / name).mkdir()
        write_json(build / "synapse/homeserver.json", homeserver(args, push_ip))
        write_json(build / "synapse/logging.json", {
            "version": 1,
            "handlers": {"stderr": {"class": "logging.StreamHandler", "level": "WARNING"}},
            "loggers": {"synapse.access.http": {"level": "CRITICAL", "propagate": False}},
            "root": {"level": "WARNING", "handlers": ["stderr"]},
        })
        registration = rtc_registration(args.matrix_host)
        write_json(build / "synapse/rtc-appservice.json", registration)
        write_json(build / "rtc-auth/registration.json", registration)
        key = f"sc_{secrets.token_hex(12)}"
        secret = secrets.token_urlsafe(48)
        (build / "rtc-auth/livekit-key.yaml").write_text(f"{key}: {secret}\n", encoding="utf-8")
        write_json(build / "livekit/livekit.json", livekit_config(args, key, secret))
        caddy = (ROOT / "server/Caddyfile.template").read_text(encoding="utf-8")
        for label, value in (("MATRIX_HOST", args.matrix_host), ("RTC_HOST", args.rtc_host), ("AUTH_IP", auth_ip)):
            caddy = caddy.replace(f"@{label}@", value)
        tls = ""
        if args.tls_chain:
            shutil.copyfile(args.tls_chain, build / "caddy/tls-chain.pem")
            shutil.copyfile(args.tls_key, build / "caddy/tls-key.pem")
            tls = "    tls /etc/caddy/tls-chain.pem /etc/caddy/tls-key.pem\n"
        (build / "caddy/Caddyfile").write_text(caddy.replace("@TLS_DIRECTIVE@\n", tls), encoding="utf-8")
        if args.apns_key_file:
            write_push(build / "push", args)
        variables = {
            "SC_STATE": f"'{state}'", "SC_MATRIX_HOST": args.matrix_host, "SC_RTC_HOST": args.rtc_host,
            "SC_SUBNET": str(args.subnet), "SC_AUTH_IP": auth_ip, "SC_PUSH_IP": push_ip,
            "SC_UID": os.getuid(), "SC_GID": os.getgid(),
            "COMPOSE_PROFILES": "push" if args.apns_key_file else "",
        }
        (build / ".env").write_text("".join(f"{k}={v}\n" for k, v in variables.items()), encoding="utf-8")
        build.rename(state)
    print(f"Created {state}\nMatrix: https://{args.matrix_host}\nCalls: wss://{args.rtc_host}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-host", type=host, required=True)
    parser.add_argument("--rtc-host", type=host, required=True)
    parser.add_argument("--media-ip", type=media_ipv4, required=True)
    parser.add_argument("--subnet", type=subnet, default=ipaddress.IPv4Network("172.30.196.0/24"))
    parser.add_argument("--tls-chain", type=Path, help="Use an existing trusted PEM certificate chain for both DNS names.")
    parser.add_argument("--tls-key", type=Path, help="Private key for --tls-chain.")
    parser.add_argument("--bundle-id", type=bundle_id)
    parser.add_argument("--team-id", type=apple_identifier)
    parser.add_argument("--apns-key-id", type=apple_identifier)
    parser.add_argument("--apns-key-file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("ios-server-state"))
    args = parser.parse_args()
    if bool(args.tls_chain) != bool(args.tls_key):
        parser.error("--tls-chain and --tls-key must be provided together.")
    if args.matrix_host == args.rtc_host:
        parser.error("Use different DNS names for Matrix and the call relay.")
    push_args = [args.bundle_id, args.team_id, args.apns_key_id, args.apns_key_file]
    if any(push_args) and not all(push_args):
        parser.error("For Apple push, specify the bundle ID, team ID, APNs key ID and APNs key file.")
    os.umask(0o077)
    try:
        prepare(args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
