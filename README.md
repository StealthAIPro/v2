# Game Connection Stabilizer

Game Connection Stabilizer is a small Windows utility that adds a controlled delay to selected UDP game traffic. Its controls use plain language so the app can be operated without networking knowledge.

## What the controls mean

- **Turn Stabilizer On** starts or stops traffic handling.
- **Normal Traffic Delay** controls the extra delay for ordinary game traffic.
- **Stabilize Shot Timing** applies a fixed 500 ms delay to detected 99-byte shot traffic.
- **High Performance Mode** gives the app more CPU scheduling priority while it is running.
- **Activity** shows traffic handled, average delay, queued traffic, and traffic sent immediately during unusually heavy load.

Use this utility only on networks and applications you are authorized to test. Adding delay can interrupt games, calls, downloads, or other UDP applications because the current capture rule handles all UDP traffic.

## Run from source

```powershell
py -m pip install -r requirements.txt
py packet_shaper.py
```

Running source does not request administrator access automatically. To test real traffic handling from source, open PowerShell as Administrator and then run the command. Without administrator access, Windows will prevent WinDivert from starting.

## Build the Windows release

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
```

The script creates an isolated `.venv`, installs the pinned application and build dependencies into it, runs the test suite, obfuscates the Python modules with PyArmor, packages them with PyInstaller, embeds an administrator manifest, and creates:

- `release\GameConnectionStabilizer.exe`
- `release\GameConnectionStabilizer.exe.sha256`
- release copies of this README and the third-party notices

PyArmor and PyInstaller make casual source recovery harder, but no client-side executable can be made impossible to inspect or reverse engineer. A determined analyst can observe code and data while the program runs. A paid PyArmor license may be required for commercial distribution and for modules beyond the trial limits. For public distribution, also sign the final executable with a trusted Windows code-signing certificate.

The packaged executable requests administrator permission through its Windows manifest. While elevated, it intentionally avoids writing persistent logs into user-controlled folders; failures are shown in the interface or a Windows error dialog.

## Included WinDivert folders

The repository's `x86` and `x64` folders are the full WinDivert 2.2.2 developer distribution. They include sample and control programs that the app does not call. The release build excludes those folders and packages only the WinDivert DLL and driver supplied by the pinned PyDivert dependency.

Traffic queues are bounded to 8,192 packets and 16 MiB per queue. If either limit is reached, new traffic is sent immediately instead of being held.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency licenses and notices.
