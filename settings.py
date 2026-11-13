"""Validation shared by the iOS and server configuration commands."""

import argparse
import re

LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
BUNDLE_PART = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


def host(value):
    parts = value.split(".")
    if len(value) > 253 or len(parts) < 2 or not all(LABEL.fullmatch(part) for part in parts):
        raise argparse.ArgumentTypeError("Use a lowercase hostname, such as chat.example.com.")
    if parts[-1].isdigit():
        raise argparse.ArgumentTypeError("Use a DNS hostname with a trusted HTTPS certificate.")
    return value


def bundle_id(value):
    parts = value.split(".")
    if len(parts) < 3 or len(value) > 96 or not all(BUNDLE_PART.fullmatch(part) for part in parts):
        raise argparse.ArgumentTypeError("Use a reverse-DNS identifier, such as com.example.sovereignchat.")
    return value


def apple_identifier(value):
    if not re.fullmatch(r"[A-Z0-9]{10}", value):
        raise argparse.ArgumentTypeError("Use the ten-character identifier from your Apple Developer account.")
    return value
