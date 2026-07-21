# Runbook: Mobile export (Android first; iOS needs macOS)

## Mobile-web already works (no SDK needed)

The fastest "mobile" target is the **browser build on a phone/tablet** — the
WebGPU/WebGL export runs in mobile Chrome/Safari, and the slice now has touch
controls (`StudioTouchStick` on the Deep + Battle HUDs, feeding the same
`move_*` actions desktop uses, self-hiding on non-touch). Host the export
(`docs/runbooks/public-hosting.md`) and it plays on a phone from a link.

## Native Android (.apk/.aab)

Requires the Android SDK + JDK 17 + Godot editor Android config. `just doctor`
reports `android (platform) sdk: not found` until then.

1. **JDK 17.** Godot's Android build targets JDK 17 (JDK 21 is installed here;
   point Godot at a 17 install — winget `EclipseAdoptium.Temurin.17.JDK`).
2. **Android SDK.** Install Android Studio (winget `Google.AndroidStudio`) or
   the command-line SDK, then `sdkmanager "platform-tools" "platforms;android-34"
   "build-tools;34.0.0" "ndk;26.1.10909125"` (Godot 4.x needs the NDK).
3. **Godot editor settings.** Editor → Editor Settings → Export → Android: set
   `adb`, `jarsigner`, debug keystore, and the SDK path.
4. **Export templates.** The official 4.7.1 templates include Android
   (`just doctor` confirms they're installed).
5. **Export:** `just export-android GAME=games/asha_world` →
   `games/asha_world/project/exports/android/asha_world.apk`.

Evidence bar for BOOTSTRAP_REPORT.md: the .apk installs and the slice reaches
the menu on a real device or emulator (screenshot). Until the SDK is installed,
Android remains "documented, not evidenced."

## Native iOS

Requires macOS + Xcode (this machine is Windows). `just doctor` reports iOS as
`na` here. On a Mac: `just export-ios` after the same template install; the
slice's touch controls already cover the input model.
