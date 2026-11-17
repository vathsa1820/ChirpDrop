# ChirpDrop - Environment Setup & Dependency Verification

This document records the installation, configuration, and verification of the Python 3.11 development environment and core dependencies for ChirpDrop on Windows 11 64-bit.

---

## 1. System & Runtime Specifications

| Attribute | Specification / Value |
| :--- | :--- |
| **Operating System** | Windows 11 (`10.0.26300-SP0`, 64-bit) |
| **System Default Python** | Python 3.13.14 (Microsoft Store App, unmodified) |
| **Environment Toolchain** | `uv` version 0.11.12 (`C:\Users\sriva\.local\bin\uv.exe`) |
| **Project Python Runtime** | **CPython 3.11.15 (64-bit AMD64, MSC v.1944)** |
| **Virtual Environment Location** | `C:\Users\sriva\.gemini\antigravity\scratch\ChirpDrop\.venv` |
| **Virtual Environment Python** | `C:\Users\sriva\.gemini\antigravity\scratch\ChirpDrop\.venv\Scripts\python.exe` |
| **Package Installer** | `pip 26.3` (operating inside `.venv`) |

---

## 2. Installed Dependencies & Versions

All dependencies are installed exclusively inside `ChirpDrop/.venv` without global pollution:

| Package | Version | Purpose |
| :--- | :--- | :--- |
| **PySide6** | `6.8.3` | Qt 6 GUI framework for Windows desktop interface. |
| **PySide6-Essentials** | `6.8.3` | Core Qt binaries, plugins, and widgets. |
| **PySide6-Addons** | `6.8.3` | Extended Qt modules. |
| **shiboken6** | `6.8.3` | CPython/C++ binding generator runtime for PySide6. |
| **sounddevice** | `0.5.6` | PortAudio wrapper for low-latency audio capture and playback. |
| **numpy** | `1.26.4` | Numerical array buffers for audio samples (pinned to `<2.0.0`). |
| **ggwave-wheels** | `0.4.2.5` | Precompiled Windows x64 binary wheel providing the `ggwave` module. |
| **cffi** | `2.1.1` | Foreign function interface (dependency of sounddevice). |
| **pycparser** | `3.12` | C parser in Python (dependency of cffi). |
| **pytest** | `9.2.0` | Unit and integration testing framework. |
| **colorama** | `0.4.6` | ANSI terminal text coloring for Windows console. |
| **iniconfig** | `2.3.1` | Brain-dead simple config-parsing for pytest. |
| **pluggy** | `1.7.0` | Plugin management framework for pytest. |
| **pygments** | `2.21.0` | Syntax highlighter used by pytest tracebacks. |
| **packaging** | `26.3` | Core utilities for Python packages. |
| **setuptools** | `84.2.1` | Python package development utilities. |
| **wheel** | `0.48.0` | Built-package format support. |

---

## 3. GGWave Distribution & Verification

Because the official PyPI `ggwave` package only publishes source tarballs (`.tar.gz`) requiring Microsoft Visual C++ Build Tools, `ggwave-wheels==0.4.2.5` was retrieved using pip's binary-only download filter (`--only-binary=:all:`).

### Wheel Integrity Check

- **Package**: `ggwave-wheels==0.4.2.5`
- **Wheel Filename**: `ggwave_wheels-0.4.2.5-cp311-cp311-win_amd64.whl`
- **Compatibility Tag**: `cp311-cp311-win_amd64`
- **Expected SHA-256**:
  `43e41992fc5804f58b603ca41be7ccf0ae03f24539e5495f564ca4696753baa5`
- **Calculated SHA-256**:
  `43e41992fc5804f58b603ca41be7ccf0ae03f24539e5495f564ca4696753baa5`
- **Integrity Status**: **VERIFIED / EXACT MATCH**

### Module Inspection & API Verification

The wheel installs a single top-level C-extension module: `ggwave.cp311-win_amd64.pyd`.

Exposed module attributes:
```python
['decode', 'disableLog', 'enableLog', 'encode', 'free', 'getDefaultParameters', 'init', 'rxToggleProtocol', 'txToggleProtocol']
```

- **Encoding Test**:
  ```python
  payload = "ChirpDrop-Test-01"
  waveform = ggwave.encode(payload, protocolId=1, volume=20)
  ```
  *Result*: Successfully produced 352,256 bytes of raw 16-bit PCM waveform samples.
- **Decoding Loopback Test**:
  ```python
  instance = ggwave.init()
  decoded = ggwave.decode(instance, waveform)
  ggwave.free(instance)
  ```
  *Result*: `b'ChirpDrop-Test-01'` was decoded and matched the original payload byte-for-byte.

---

## 4. Audio Hardware Verification

Queried via `sounddevice 0.5.6` with PortAudio host APIs (MME, DirectSound, WASAPI, WDM-KS):

- **Default Input Device**: `Microphone Array (AMD Audio Device)` (Index 1)
- **Default Output Device**: `Speaker (Realtek(R) Audio)` (Index 3)
- **Total Input Endpoints**: 11
- **Total Output Endpoints**: 9
- **48 kHz Mono (float32) Input Support**: **SUPPORTED** (`sd.check_input_settings` passed)
- **48 kHz Mono (float32) Output Support**: **SUPPORTED** (`sd.check_output_settings` passed)

---

## 5. Qt 6 (PySide6) Initialization Test

- **PySide6 Version**: `6.8.3`
- **QtCore Version**: `6.8.3`
- **Test Procedure**: Initialized `QtWidgets.QApplication(['test', '-platform', 'offscreen'])` in a clean sub-process.
- **Thread Affinity**: Validated main thread association.
- **Exit Code**: Clean shutdown via `app.quit()` with zero exceptions.

---

## 6. Compatibility & Operational Warnings

1. **NumPy Version Lock**:
   `numpy` must remain on `1.26.4`. Upgrading to NumPy 2.x will break binary ABI compatibility with `ggwave.cp311-win_amd64.pyd` and `sounddevice`.
2. **Audio Permissions**:
   Windows 10/11 privacy controls must allow desktop applications access to the microphone. If disabled, PortAudio will return host errors during stream open calls.
3. **Loopback Reverberation & Speaker Decay**:
   While `ggwave` loopback decoding directly on byte arrays succeeds instantaneously, physical acoustic transmission between speakers and microphones requires adhering to the 150 ms inter-chirp delay and 250 ms guard delay specified in `config.py`.
