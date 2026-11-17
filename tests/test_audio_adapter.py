"""
ChirpDrop - Unit Tests for GGWave Adapter
-----------------------------------------
Validates initialization, text encoding, payload validation, demodulation,
protocol toggling, and native resource cleanup.
"""

import pytest

from app.audio.ggwave_adapter import (
    GgWaveAdapter,
    GgWaveDecodeError,
    GgWaveEncodeError,
    GgWaveInitError,
    PROTOCOL_AUDIBLE_FAST,
    PROTOCOL_AUDIBLE_NORMAL,
    PROTOCOL_ULTRASONIC_NORMAL,
)


def test_adapter_initialization_and_cleanup() -> None:
    """Test explicit lifecycle initialization and cleanup of native GGWave handle."""
    adapter = GgWaveAdapter(sample_rate=48000)
    assert not adapter.is_initialized
    assert adapter.instance_id is None

    handle = adapter.initialize()
    assert adapter.is_initialized
    assert adapter.instance_id == handle
    assert isinstance(handle, int)

    # Subsequent initialize call returns the same handle
    assert adapter.initialize() == handle

    # Close and verify handle is freed
    adapter.close()
    assert not adapter.is_initialized
    assert adapter.instance_id is None

    # Idempotent close
    adapter.close()
    assert not adapter.is_initialized


def test_adapter_context_manager() -> None:
    """Test initialization and cleanup via Python context manager."""
    adapter = GgWaveAdapter(sample_rate=48000)
    with adapter as a:
        assert a.is_initialized
        assert a.instance_id is not None
    assert not adapter.is_initialized


def test_text_encoding_success() -> None:
    """Test encoding plain text into a valid float32 acoustic waveform."""
    adapter = GgWaveAdapter(sample_rate=48000)
    with adapter:
        # Audible normal
        wf_audible = adapter.encode("ChirpDrop Audio Test", protocol_id=PROTOCOL_AUDIBLE_NORMAL, volume=20)
        assert isinstance(wf_audible, bytes)
        assert len(wf_audible) > 0
        assert len(wf_audible) % 4 == 0  # Multiple of float32 sample size

        # Ultrasonic normal
        wf_ultrasonic = adapter.encode("ChirpDrop Ultrasonic", protocol_id=PROTOCOL_ULTRASONIC_NORMAL, volume=30)
        assert isinstance(wf_ultrasonic, bytes)
        assert len(wf_ultrasonic) > 0
        assert len(wf_ultrasonic) % 4 == 0


def test_invalid_payload_handling() -> None:
    """Test that invalid payloads trigger GgWaveEncodeError."""
    adapter = GgWaveAdapter(sample_rate=48000)
    with adapter:
        # Empty string
        with pytest.raises(GgWaveEncodeError, match="empty payload"):
            adapter.encode("")

        # None or invalid type
        with pytest.raises(GgWaveEncodeError, match="must be str or bytes"):
            adapter.encode(12345)  # type: ignore[arg-type]

        # Non-UTF8 raw binary bytes (invalid surrogate/continuation)
        with pytest.raises(GgWaveEncodeError, match="UTF-8"):
            adapter.encode(b"\xff\xfe\x80\x81")


def test_decode_previously_encoded_waveform() -> None:
    """Test full encode-decode cycle on generated waveform."""
    adapter = GgWaveAdapter(sample_rate=48000)
    with adapter:
        message = "Test-Acoustic-123"
        waveform = adapter.encode(message, protocol_id=PROTOCOL_AUDIBLE_FAST, volume=20)
        assert len(waveform) > 0

        # Decode entire buffer
        decoded = adapter.decode(waveform)
        assert decoded is not None
        assert decoded.decode("utf-8") == message


def test_decode_uninitialized_error() -> None:
    """Test that calling decode on an uninitialized adapter raises GgWaveDecodeError."""
    adapter = GgWaveAdapter(sample_rate=48000)
    with pytest.raises(GgWaveDecodeError, match="not initialized"):
        adapter.decode(b"\x00" * 4096)


def test_protocol_toggling() -> None:
    """Test rx and tx protocol toggling methods."""
    adapter = GgWaveAdapter(sample_rate=48000)
    with adapter:
        adapter.rx_toggle_protocol(PROTOCOL_AUDIBLE_NORMAL, True)
        adapter.rx_toggle_protocol(PROTOCOL_AUDIBLE_NORMAL, False)
        adapter.tx_toggle_protocol(PROTOCOL_AUDIBLE_NORMAL, True)
        adapter.tx_toggle_protocol(PROTOCOL_AUDIBLE_NORMAL, False)
