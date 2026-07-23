# Runbook: Mobile export

## Mobile browser

A hosted WebGPU/WebGL export can run on compatible phones and tablets without a
native SDK. Responsive layout, touch input, browser support, and performance
must be verified by each consuming game on real devices.

See [public hosting](public-hosting.md) for export and HTTP requirements.

## Native Android

Requires the Android SDK, JDK 17, and Godot Android editor configuration.
`just doctor` reports readiness.

1. Install JDK 17.
2. Install Android Studio or command-line SDK components required by the pinned
   Godot release.
3. Configure Godot's Android SDK, ADB, jarsigner, and debug keystore paths.
4. Install the matching official Godot export templates.
5. Export a mechanics-neutral baseline:

   ```sh
   just export-android GAME=templates/godot-game
   ```

A consuming game should override identifiers, icons, signing, permissions, and
store metadata in its own repository.

Evidence requires installing the artifact and reaching the first interactive
scene on a real device or emulator.

## Native iOS

Requires macOS, Xcode, Apple signing, and the matching export templates. Run:

```sh
just export-ios GAME=templates/godot-game
```

Each consuming game owns its bundle identifier, entitlements, signing team,
privacy declarations, and store configuration. Claim iOS readiness only after a
real-device run.
