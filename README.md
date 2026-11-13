# Sovereign Chat for iPhone

This source kit prepares **Sovereign Chat 0.2.0**, a SwiftUI iPhone client based on the pinned Element X iOS release 26.11.0. It uses the Matrix Rust SDK for encrypted messages and device verification. The embedded Element Call engine uses MatrixRTC and a self-hosted LiveKit relay for voice and video. The call entry point requires an encrypted room and selects per-participant media encryption keys.

The generated iOS project is configured for one homeserver. Its default analytics and crash-reporting settings are disabled. The server configuration creates private rooms, refuses plaintext message events, and disables public signup and federation. An operator creates accounts on the server console.

This repository provides source and example deployment configuration. Text messaging, voice calls, and video calls were tested between iOS and a desktop Matrix client on a self-hosted deployment of version 0.2.0.

## 1. Choose a place to run the server

The Compose setup runs Synapse, the MatrixRTC authorization service, LiveKit and a Caddy HTTPS gateway on one Linux host. The iPhone needs reachable HTTPS names for both the Matrix server and the media relay.

| Where you want to use the app | Host setup |
| --- | --- |
| Home Wi-Fi | Use a Linux host on your local network. Point two DNS names at its LAN IPv4 address and supply a trusted certificate that covers both names. Use the same Matrix hostname on both phones. |
| Wi-Fi and mobile data | Use a Linux host reachable from the internet. Point both DNS names at it and make the gateway and media ports reachable there. The iPhones connect directly without a VPN. |

For the internet setup, point both DNS names to the public IPv4. The included Caddy configuration can obtain HTTPS certificates. Allow TCP 80 and 443 for the gateway, TCP 7881 for WebRTC fallback, UDP 7882 for media, and UDP 3478 for the bundled TURN relay. The app publishes the address you pass as `--media-ip` to the calling clients. TURN over TLS for particularly restrictive networks is a separate deployment option.

For the LAN setup, pass the Linux host's LAN IPv4 address as `--media-ip` and add `--tls-chain /path/to/fullchain.pem --tls-key /path/to/privkey.pem`. The provided certificate must cover both DNS names and chain to a CA trusted by iOS and the authorization service. A publicly trusted certificate obtained by DNS validation can be used on the LAN.

## 2. Start the server

Install Docker with Compose on the Linux host. Unpack this kit there. In its root directory, replace the two example DNS names and example IPv4.

```bash
python3 prepare_server.py \
  --matrix-host chat.example.net \
  --rtc-host rtc.example.net \
  --media-ip 192.0.2.20
```

Run the following in Bash from the kit directory. Keep the generated `ios-server-state` directory private. It contains your server keys and database.

```bash
chat_compose=(docker compose --env-file ios-server-state/.env -f server/compose.yaml)
"${chat_compose[@]}" run --rm --no-deps synapse -c /state/homeserver.json --generate-keys
"${chat_compose[@]}" up -d
"${chat_compose[@]}" exec synapse register_new_matrix_user \
  -c /state/homeserver.json -u testuser1 --no-admin http://127.0.0.1:8008
"${chat_compose[@]}" exec synapse register_new_matrix_user \
  -c /state/homeserver.json -u testuser2 --no-admin http://127.0.0.1:8008
```

Each account command prompts for a password. Use two accounts when testing a conversation or call. The mobile stack uses fresh state and adds the MatrixRTC endpoints the desktop release lacks.

## 3. Build on macOS

Use a Mac or hosted macOS runner with Xcode 27, the version selected by the pinned upstream release. The deployment target is iOS 18.5. Install Python 3.12 or newer and XcodeGen on the build machine. Replace the example team ID and bundle ID with values for your Apple Developer team.

```bash
brew install xcodegen
python3 prepare_ios.py \
  --matrix-host chat.example.net \
  --bundle-id net.example.sovereignchat \
  --team-id ABCD123456
cd ios-project
xcodegen
open ElementX.xcodeproj
```

The Xcode scheme remains **ElementX**. The installed app displays **Sovereign Chat**. Set automatic signing for the app and both extensions. Use your app bundle ID, the `.nse` notification service extension, the `.shareextension` extension, and the App Group `group.<your-bundle-id>` for all three targets. The main app and extensions share the app's keychain group.

Run on two iPhones. Sign in with the two local accounts, start a private chat, and verify the other account's identity from the room. Test text, a voice call, and a video call. With push off, leave the recipient's app open and join the call from the chat room.

Use **Product → Archive** and **Distribute App → App Store Connect** in Xcode Organizer. Select the resulting build for an internal TestFlight group. Review the app's export compliance and privacy answers for your distribution. This fork includes Element X source and license notices under AGPL-3.0. Keep the corresponding source available as required by that license when distributing builds.

## 4. Enable push and locked-screen ringing

Use an APNs-enabled App ID. For a fresh push-enabled server configuration, add these options to the **same** `prepare_server.py` command in step 2.

```bash
--bundle-id net.example.sovereignchat --team-id ABCD123456 \
--apns-key-id ABCD123457 --apns-key-file /secure/path/AuthKey.p8
```

The generator enables your Sygnal gateway inside the Compose network. Keep the `.p8` file on the server. The generated configuration has separate APNs entries for development and TestFlight. Use an APNs key authorized for the environment you test.

Prepare the iOS project with `--push` to register notifications through your gateway. To enable the native locked-screen CallKit handoff, also add `--lock-screen-calls` after Apple grants `com.apple.developer.usernotifications.filtering` to your notification extension's App ID and your provisioning profile includes it. The upstream notification extension retrieves and processes the call event before handing it off to CallKit.

The push gateway uses event-ID-only Matrix pushes. Apple handles delivery and sees a device token and notification routing metadata. The notification extension fetches the encrypted event and decrypts it on the iPhone. Apple does not relay the call media. Test an incoming call on a locked physical iPhone with the actual TestFlight signing and production APNs environment.

## What the tests cover

- `python3 -m unittest discover -s tests -v` prepares three iOS signing configurations from the pinned source and checks the server generation and APNs settings.
- `python3 tests/synapse_smoke.py --synapse-python /path/to/synapse-venv/bin/python` runs Synapse 1.165.0 and checks private encrypted room creation, plaintext message refusal, and authenticated proxying to a test MatrixRTC service.

Your homeserver can see account and room membership metadata. The call relay can see connection and traffic metadata. The client changes remove the preset homeserver and push service. The kit has not been independently audited or measured for all network traffic on a physical iPhone.

## Upstream references

- [Element X iOS release 26.11.0](https://github.com/element-hq/element-x-ios/releases/tag/release/26.11.0)
- [MatrixRTC self-hosting](https://github.com/element-hq/element-call/blob/main/docs/self_hosting.md)
- [MatrixRTC authorization service configuration](https://github.com/element-hq/lk-jwt-service/tree/v0.10.0)
- [Apple's encrypted incoming call handoff](https://developer.apple.com/documentation/callkit/sending-end-to-end-encrypted-voip-calls)
- [Apple's notification filtering entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.usernotifications.filtering)
- [Apple's upload requirements](https://developer.apple.com/news/upcoming-requirements/)


## Expo EAS build (optional)

The repo includes a **generic** EAS Build profile and custom workflow. The checked-in
`app.json` uses `com.example.sovereignchat`, no Expo account owner, and no EAS project ID;
`eas.json` uses `chat.example.net`. These are placeholders, **not live service settings**.

1. Replace all placeholder hostnames, bundle IDs, and App Group IDs with your own.
2. Link to your own Expo EAS project (`eas init`), and create Apple signing credentials.
3. Review `.eas/build/testflight.yml`, then run `eas build --platform ios --profile testflight`.

Keep provisioning profiles, Apple API keys, secrets, push certificates, user data,
`.env` files and `ios-server-state/` completely outside git. Never run git from
a live server-state directory. The upstream Element X source is bundled as a pinned
archive under `vendor/`, with its original license and notices preserved.

For an example of exposing a home Matrix server via a public HTTPS gateway and
a private outbound tunnel without requiring a phone VPN, see `docs/public-gateway-example.md`.
