#!/usr/bin/env python3
"""Prepare an XcodeGen project from the bundled Element X release source."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from settings import apple_identifier, bundle_id, host

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "vendor" / "element-x-ios-975651a.tar.gz"
UPSTREAM_SHA256 = "7cb130fe278607431b90973874877bbaf40a0f78ef8fa1bb52582350b4099f07"
PATCH = ROOT / "patches" / "sovereign-ios.patch"


def replace_once(path, before, after):
    source = path.read_text(encoding="utf-8")
    if source.count(before) != 1:
        raise ValueError(f"Unexpected source in {path.name}.")
    path.write_text(source.replace(before, after, 1), encoding="utf-8")


def apply_settings(project, args):
    app = project / "app.yml"
    replace_once(app, "  BASE_BUNDLE_IDENTIFIER: net.example.sovereignchat", f"  BASE_BUNDLE_IDENTIFIER: {args.bundle_id}")
    replace_once(app, "  APP_GROUP_IDENTIFIER: group.net.example.sovereignchat", f"  APP_GROUP_IDENTIFIER: group.{args.bundle_id}")
    replace_once(app, '  DEVELOPMENT_TEAM: ""', f'  DEVELOPMENT_TEAM: "{args.team_id}"')
    if args.push:
        replace_once(
            project / "ElementX/SupportingFiles/target.yml",
            "        # Sovereign Chat push entitlement",
            "        aps-environment: $(SOVEREIGN_APS_ENVIRONMENT)\n"
            "        com.apple.developer.usernotifications.communication: true",
        )
    if args.lock_screen_calls:
        replace_once(
            project / "NSE/SupportingFiles/target.yml",
            "        # Sovereign Chat notification filtering entitlement",
            "        com.apple.developer.usernotifications.filtering: true",
        )

    source = project / "ElementX/Sources/Application/Settings/SovereignConfiguration.swift"
    source.write_text(
        "// SPDX-License-Identifier: AGPL-3.0-only\n"
        "\n"
        "import Foundation\n"
        "\n"
        "nonisolated enum SovereignConfiguration {\n"
        f"    static let serverName = {json.dumps(args.matrix_host)}\n"
        f"    static let homeserverURL: URL = {json.dumps('https://' + args.matrix_host)}\n"
        '    static let pushGatewayURL: URL = "http://push:5000"\n'
        f"    static let pushEnabled = {str(args.push).lower()}\n"
        f"    static let lockScreenCallsEnabled = {str(args.lock_screen_calls).lower()}\n"
        "}\n",
        encoding="utf-8",
    )
    shutil.copyfile(ROOT / "brand" / "AppIcon.png", project / "ElementX/Resources/AppIcon.icon/Assets/AppIcon.png")
    shutil.copyfile(
        ROOT / "brand" / "app-logo.pdf",
        project / "ElementX/Resources/Assets.xcassets/images/app-logo.imageset/app-logo.pdf",
    )


def prepare(args):
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"{output} already exists. Pick a new project directory.")
    with UPSTREAM.open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != UPSTREAM_SHA256:
            raise ValueError("The bundled upstream source failed its integrity check.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sovereign-ios-", dir=output.parent) as workspace:
        folder = Path(workspace)
        with tarfile.open(UPSTREAM, "r:gz") as archive:
            archive.extractall(folder, filter="data")
        [project] = folder.iterdir()
        subprocess.run(["git", "init", "--quiet", str(project)], check=True)
        subprocess.run(["git", "apply", str(PATCH)], cwd=project, check=True)
        apply_settings(project, args)
        project.rename(output)
    print(f"Prepared {output}\nRun xcodegen in this directory and open ElementX.xcodeproj in Xcode.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-host", type=host, required=True)
    parser.add_argument("--bundle-id", type=bundle_id, required=True)
    parser.add_argument("--team-id", type=apple_identifier, required=True)
    parser.add_argument("--push", action="store_true", help="Include the Apple Push Notifications capability.")
    parser.add_argument("--lock-screen-calls", action="store_true", help="Enable the approved notification filtering entitlement.")
    parser.add_argument("--output", type=Path, default=Path("ios-project"))
    args = parser.parse_args()
    if args.lock_screen_calls and not args.push:
        parser.error("--lock-screen-calls requires --push.")
    try:
        prepare(args)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
