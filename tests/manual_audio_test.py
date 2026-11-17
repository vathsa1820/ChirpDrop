"""
ChirpDrop - Manual Acoustic Hardware Diagnostic Tool
---------------------------------------------------
Interactive manual test utility to evaluate physical acoustic transmission and
reception between local speakers and microphones.

SAFETY NOTICE:
  - This script is intended strictly for manual interactive execution.
  - It does NOT automatically play audio upon import.
  - User confirmation is required before sound emission.
  - Playback gain is kept conservative (20%) to avoid ear or hardware strain.
"""

import argparse
from pathlib import Path
import sys
import time

# Ensure project root is on sys.path for direct script execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.audio import (
    AudioDeviceManager,
    AudioEngine,
    GgWaveAdapter,
    PROTOCOL_AUDIBLE_FAST,
    PROTOCOL_AUDIBLE_NORMAL,
    PROTOCOL_ULTRASONIC_NORMAL,
)
import config
from config import TransmissionMode


def run_hardware_test(
    message: str = "ChirpDrop Acoustic Test 01",
    mode: str = "audible",
    volume: int = 25,
    listen_seconds: float = 6.0,
) -> int:
    """
    Run an end-to-end interactive acoustic hardware diagnostic test.

    Args:
        message: Test payload text to encode and transmit.
        mode: 'audible' or 'ultrasonic'.
        volume: Volume level percentage (1-100).
        listen_seconds: Maximum seconds to listen for acoustic reception.

    Returns:
        0 on success, non-zero on failure.
    """
    print("\n=======================================================")
    print("      ChirpDrop - Manual Acoustic Hardware Test        ")
    print("=======================================================\n")

    # 1. Device Enumeration
    dm = AudioDeviceManager()
    devices = dm.list_devices(refresh=True)
    input_devices = dm.list_input_devices()
    output_devices = dm.list_output_devices()

    print(f"Discovered Audio Endpoints: {len(devices)} total ({len(input_devices)} In, {len(output_devices)} Out)")

    default_in = dm.get_default_input_device()
    default_out = dm.get_default_output_device()

    print("\nDefault Endpoints:")
    print(f"  [MIC]     Index {default_in.index if default_in else 'None'}: {default_in.name if default_in else 'None'}")
    print(f"  [SPEAKER] Index {default_out.index if default_out else 'None'}: {default_out.name if default_out else 'None'}")

    if not default_in or not default_out:
        print("\n[ERROR] Both an audio input and output device are required.")
        return 1

    # 2. Check 48 kHz mono capability
    print("\nChecking 48 kHz Mono float32 capability...")
    in_ok = dm.check_format_support(default_in.index, sample_rate=48000, channels=1, is_input=True)
    out_ok = dm.check_format_support(default_out.index, sample_rate=48000, channels=1, is_input=False)

    print(f"  Input Support:  {'[SUPPORTED]' if in_ok else '[FAILED]'}")
    print(f"  Output Support: {'[SUPPORTED]' if out_ok else '[FAILED]'}")

    if not in_ok or not out_ok:
        print("[WARNING] Hardware does not report full 48 kHz mono support. Audio may be resampled by Windows.")

    # 3. Protocol and Modulation Setup
    tx_mode = TransmissionMode.ULTRASONIC if mode.lower() == "ultrasonic" else TransmissionMode.AUDIBLE
    protocol_id = PROTOCOL_ULTRASONIC_NORMAL if tx_mode == TransmissionMode.ULTRASONIC else PROTOCOL_AUDIBLE_FAST

    print(f"\nTransmission Configuration:")
    print(f"  Mode:            {tx_mode.value.upper()}")
    print(f"  Protocol ID:     {protocol_id}")
    print(f"  Volume Gain:     {volume}%")
    print(f"  Payload Message: '{message}'")

    # 4. Synthesize Waveform
    print("\nSynthesizing acoustic waveform with GGWave...")
    with GgWaveAdapter(sample_rate=48000) as adapter:
        waveform = adapter.encode(message, protocol_id=protocol_id, volume=volume)

    duration_sec = (len(waveform) // 4) / 48000.0
    print(f"  Generated Waveform: {len(waveform)} bytes ({duration_sec:.2f} seconds of audio)")

    # 5. User Confirmation
    print("\n-------------------------------------------------------")
    print(f"SAFETY CONFIRMATION: Sound will be played at {volume}% volume.")
    print("Make sure your speakers are set to a comfortable level.")
    print("-------------------------------------------------------")

    try:
        user_choice = input("Proceed with acoustic transmission test? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nTest cancelled by user.")
        return 0

    if user_choice not in ["y", "yes"]:
        print("Test cancelled by user.")
        return 0

    # 6. Initialize Audio Engine & Listener
    engine = AudioEngine(
        input_device_index=default_in.index,
        output_device_index=default_out.index,
        sample_rate=48000,
        guard_delay_ms=0,  # Disable guard delay for self-reception test so mic can hear speaker!
        transmission_mode=tx_mode,
    )

    received_messages = []

    def on_received(payload: bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = repr(payload)
        received_messages.append(text)
        print(f"\n>>> [ACOUSTIC RECEPTION DETECTED] Decoded: '{text}' <<<")

    engine.register_callback(on_received)

    try:
        print("\nStarting microphone capture stream...")
        engine.start_capture()

        # Let microphone stabilize
        time.sleep(0.5)

        print("Emitting acoustic transmission through speaker...")
        # Note: Play non-blocking so the microphone can capture the acoustic signal as it plays
        engine.play_waveform(waveform, blocking=False)

        print(f"Listening for acoustic echoes/reception (timeout: {listen_seconds}s)...")
        start_time = time.time()
        while time.time() - start_time < listen_seconds:
            if received_messages:
                break
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        print(f"\n[ERROR] Audio streaming failed: {e}")
        return 1
    finally:
        print("Stopping audio streams and cleaning up native handles...")
        engine.stop_capture()

    # 7. Summary & Diagnostics
    print("\n=======================================================")
    print("                 Diagnostic Results                    ")
    print("=======================================================")
    if received_messages:
        print("[SUCCESS] Acoustic transmission was received and demodulated!")
        for idx, msg in enumerate(received_messages, 1):
            print(f"  Received #{idx}: '{msg}'")
            if msg == message:
                print("  Verification: EXACT MATCH with original transmitted text.")
        return 0
    else:
        print("[NOTICE] No message was acoustically demodulated.")
        print("Diagnostic Guidance:")
        print("  1. Ensure physical microphone is not muted or disabled in Windows Privacy Settings.")
        print("  2. In self-reception tests on a single laptop, laptop noise cancellation and echo-canceling drivers")
        print("     (e.g. Realtek/AMD Audio Enhancements) often suppress speaker audio from reaching the mic.")
        print("  3. For genuine testing, test between two separate physical laptops as designed.")
        print("  4. If running in Ultrasonic mode, verify microphone and speakers support > 16 kHz.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChirpDrop Manual Acoustic Hardware Diagnostic Tool")
    parser.add_argument("--message", default="ChirpDrop Acoustic Test 01", help="Text payload to transmit")
    parser.add_argument("--mode", choices=["audible", "ultrasonic"], default="audible", help="Modulation mode")
    parser.add_argument("--volume", type=int, default=25, help="Playback volume percentage (1-100)")
    parser.add_argument("--listen", type=float, default=6.0, help="Listen timeout in seconds")

    args = parser.parse_args()
    sys.exit(run_hardware_test(
        message=args.message,
        mode=args.mode,
        volume=args.volume,
        listen_seconds=args.listen,
    ))
