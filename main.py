"""
ChirpDrop - Air-Gapped Acoustic Data and File Transfer
-----------------------------------------------------
Main application entry point.

Provides the CLI interface for acoustic transmission (sender) and reception (receiver)
demonstrations, as well as configuration and environment validation flags.
"""

import argparse
import importlib.util
import logging
import sys
import time
from typing import Dict, List, Optional

import config
from config import TransmissionMode
from app.core import Opcode, Packet
from app.audio import AudioDeviceManager, AudioEngine
from app.communication import AcousticTransport, encode_packet_to_text

# Configure top-level logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(config.APPLICATION_NAME)


def check_runtime_environment() -> Dict[str, bool]:
    """
    Inspect the Python runtime environment and probe for expected dependencies.

    Returns:
        Dict mapping dependency name to boolean availability flag.
    """
    target_dependencies: List[str] = [
        "PySide6",
        "sounddevice",
        "numpy",
        "ggwave",
        "pytest",
    ]
    status: Dict[str, bool] = {}
    for dep in target_dependencies:
        spec = importlib.util.find_spec(dep)
        status[dep] = spec is not None
    return status


def verify_directories() -> None:
    """Ensure all required project directories exist on the filesystem."""
    required_paths = [
        config.RECEIVED_FILES_DIR,
        config.LOGS_DIR,
        config.DOCS_DIR,
        config.TESTS_DIR,
    ]
    for p in required_paths:
        p.mkdir(parents=True, exist_ok=True)


def print_banner() -> None:
    """Display the application startup banner."""
    banner = f"""
======================================================================
  {config.APPLICATION_NAME} v{config.APPLICATION_VERSION}
  Air-Gapped Acoustic Data & File Transfer System
  Target OS: Windows 10 / 11 | Python: 3.11+
======================================================================
"""
    print(banner.strip())


def print_configuration_summary() -> None:
    """Print the active system configuration parameters."""
    print("\n--- System Configuration ---")
    print(f"Sample Rate:               {config.SAMPLE_RATE} Hz")
    print(f"Audio Channels:            {config.CHANNELS} (Mono)")
    print(f"Audio Data Type:           {config.AUDIO_DTYPE}")
    print(f"Header Size:               {config.HEADER_SIZE} bytes")
    print(f"Preamble:                  {config.MAGIC_PREAMBLE!r}")
    print(f"Max Payload Size:          {config.MAX_PAYLOAD_SIZE} bytes")
    print(f"Max Packet Size:           {config.MAX_PACKET_SIZE} bytes")
    print(f"Transfer Window Size:      {config.TRANSFER_WINDOW_SIZE} packets")
    print(f"Inter-Chirp Delay:         {config.INTER_CHIRP_DELAY_MS} ms")
    print(f"Post-Tx Guard Delay:       {config.POST_TRANSMISSION_GUARD_MS} ms")
    print(f"Base Directory:            {config.BASE_DIR}")
    print(f"Received Files Directory:  {config.RECEIVED_FILES_DIR}")

    print("\n--- Acoustic Profiles ---")
    for mode, profile in config.AUDIO_PROFILES.items():
        print(f"  • {profile.name} [{mode.value}]:")
        print(f"      Description:     {profile.description}")
        print(f"      Freq Range:      {profile.frequency_range_hz[0]} Hz - {profile.frequency_range_hz[1]} Hz")
        print(f"      Protocol ID:     {profile.ggwave_protocol_id}")
        print(f"      Default Volume:  {profile.default_volume * 100:.0f}%")


def validate_demo_text_payload(text: str) -> bytes:
    """
    Validate that text payload adheres to the single-chirp demo limit of 97 bytes.

    Args:
        text: Input string to transmit.

    Returns:
        UTF-8 encoded bytes.

    Raises:
        ValueError: If message is empty or exceeds 97 bytes.
    """
    payload_bytes = text.encode("utf-8")
    if not payload_bytes:
        raise ValueError("Message cannot be empty.")
    if len(payload_bytes) > 97:
        raise ValueError(
            f"Message length ({len(payload_bytes)} bytes) exceeds the single-chirp demo limit of 97 bytes.\n"
            f"GGWave's single-chirp capacity is 140 Base64 characters (105 raw bytes including 8B header).\n"
            f"Please shorten the message for this initial direct-chirp demo."
        )
    return payload_bytes


# ---------------------------------------------------------------------------
# Sender CLI Handler
# ---------------------------------------------------------------------------
def run_sender(args: argparse.Namespace) -> int:
    """
    Execute acoustic packet transmission for a single text message.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success).
    """
    try:
        payload_bytes = validate_demo_text_payload(args.text)
    except ValueError as err:
        print(f"\n[ERROR] {err}")
        return 1

    mode = TransmissionMode.ULTRASONIC if args.mode == "ultrasonic" else TransmissionMode.AUDIBLE
    default_vol = 100 if mode == TransmissionMode.ULTRASONIC else 80
    volume = args.volume if args.volume is not None else default_vol

    print("\nCHIRPDROP SENDER", flush=True)
    print("------------------------------", flush=True)
    print(f"Message: {args.text}", flush=True)
    print(f"Mode:    {mode.value.capitalize()}", flush=True)
    print("Status: Encoding...", flush=True)

    try:
        # Build binary DATA packet with sequence ID 1
        packet = Packet(opcode=Opcode.DATA, sequence_id=1, payload=payload_bytes)

        # Initialize audio engine and acoustic transport
        engine = AudioEngine(
            output_device_index=args.device,
            transmission_mode=mode,
        )
        transport = AcousticTransport(audio_engine=engine)

        print("Status: Transmitting...", flush=True)
        transport.send_packet(packet, blocking=True, volume=volume)
        print("Status: Transmission completed.\n", flush=True)
        return 0
    except Exception as err:
        print(f"\n[ERROR] Acoustic transmission failed: {err}", flush=True)
        return 1


# ---------------------------------------------------------------------------
# Receiver CLI Handler
# ---------------------------------------------------------------------------
def run_receiver(args: argparse.Namespace) -> int:
    """
    Execute continuous acoustic packet reception loop.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success).
    """
    mode = TransmissionMode.ULTRASONIC if args.mode == "ultrasonic" else TransmissionMode.AUDIBLE

    # Resolve input device name for display
    device_manager = AudioDeviceManager()
    input_name = "Default Microphone"
    try:
        if args.device is not None:
            dev_info = device_manager.get_device_by_index(args.device)
            input_name = dev_info.name
        else:
            default_in = device_manager.get_default_input_device()
            if default_in:
                input_name = default_in.name
    except Exception:
        if args.device is not None:
            input_name = f"Device #{args.device}"

    print("\nCHIRPDROP RECEIVER", flush=True)
    print("------------------------------", flush=True)
    print("Status: Listening...", flush=True)
    print(f"Audio Input: {input_name}", flush=True)
    print(f"Protocol: {mode.value.capitalize()}", flush=True)
    print("Waiting for incoming messages...\n", flush=True)

    def on_packet_received(packet: Packet) -> None:
        """Invoked when a valid packet is demodulated and checksum-verified."""
        if packet.opcode == Opcode.DATA:
            try:
                decoded_text = packet.payload.decode("utf-8")
            except UnicodeDecodeError:
                decoded_text = repr(packet.payload)

            print("\nMESSAGE RECEIVED", flush=True)
            print("------------------------------", flush=True)
            print("From: Acoustic Channel", flush=True)
            print(f"Message: {decoded_text}", flush=True)
            print("Status: Packet validated successfully", flush=True)
            print(
                f"Details: Seq #{packet.sequence_id} | "
                f"CRC: 0x{packet.calculate_checksum():04X} | "
                f"Size: {len(packet.payload)} bytes\n",
                flush=True,
            )
        else:
            print(
                f"\n[INFO] Control packet received: Opcode={packet.opcode.name}, "
                f"Seq={packet.sequence_id}\n",
                flush=True,
            )

    try:
        engine = AudioEngine(
            input_device_index=args.device,
            transmission_mode=mode,
        )
        transport = AcousticTransport(audio_engine=engine)
        transport.register_packet_callback(on_packet_received)
        transport.start()

        # Keep main thread alive while background audio worker demodulates
        while True:
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nStopping receiver...")
    except Exception as err:
        print(f"\n[ERROR] Receiver failure: {err}")
        return 1
    finally:
        if "transport" in locals():
            transport.stop()
        print("Receiver stopped.\n")

    return 0


# ---------------------------------------------------------------------------
# Argument Parser Configuration
# ---------------------------------------------------------------------------
def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments and subcommands."""
    parser = argparse.ArgumentParser(
        prog=config.APPLICATION_NAME,
        description=f"{config.APPLICATION_NAME}: Air-Gapped Acoustic Data & File Transfer",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{config.APPLICATION_NAME} {config.APPLICATION_VERSION}",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate directories and output centralized configuration values.",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Inspect runtime Python version and dependency installation status.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Operational commands")

    # Receiver sub-command
    recv_parser = subparsers.add_parser(
        "receive",
        aliases=["recv"],
        help="Start listening for acoustic text messages through the microphone",
    )
    recv_parser.add_argument(
        "--mode",
        choices=["audible", "ultrasonic"],
        default="audible",
        help="Acoustic modulation band (default: audible)",
    )
    recv_parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio input device index (default: OS default microphone)",
    )

    # Sender sub-command
    send_parser = subparsers.add_parser(
        "send",
        help="Transmit a text message through the speakers using sound waves",
    )
    send_parser.add_argument(
        "--text",
        "-t",
        required=True,
        help="Text message to transmit (max 97 bytes UTF-8)",
    )
    send_parser.add_argument(
        "--mode",
        choices=["audible", "ultrasonic"],
        default="audible",
        help="Acoustic modulation band (default: audible)",
    )
    send_parser.add_argument(
        "--volume",
        "-v",
        type=int,
        default=None,
        help="Playback volume percentage 1-100 (default: 80 for audible, 100 for ultrasonic)",
    )
    send_parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio output device index (default: OS default speaker)",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    """
    Application bootstrap entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 for success).
    """
    args = parse_arguments(argv)

    # Command-line demo operations
    if args.command in ("receive", "recv"):
        print_banner()
        verify_directories()
        return run_receiver(args)

    if args.command == "send":
        print_banner()
        verify_directories()
        return run_sender(args)

    # Diagnostic inspection flags
    print_banner()
    verify_directories()

    if args.check_config:
        print_configuration_summary()
        return 0

    if args.check_env:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        print(f"\nPython Runtime: {py_ver} on {sys.platform}")
        print("\nDependency Check Status:")
        dep_status = check_runtime_environment()
        for dep, available in dep_status.items():
            status_str = "[INSTALLED]" if available else "[NOT INSTALLED]"
            print(f"  - {dep:<15} {status_str}")
        return 0

    # Default overview when no command is specified
    print("\n[CHIRPDROP ACOUSTIC DEMO]")
    print("To listen for incoming acoustic messages on this machine:")
    print("  python main.py receive\n")
    print("To transmit a text message through the speakers:")
    print('  python main.py send --text "Hello from ChirpDrop!"\n')
    print("Run 'python main.py --help' for full CLI options.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
