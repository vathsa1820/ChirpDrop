"""
ChirpDrop - Unit Tests for Audio Engine
---------------------------------------
Validates audio engine lifecycle, real-time audio callback queuing,
echo suppression, post-transmission guard delay, and background worker shutdown.
"""

import queue
import time
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from app.audio.audio_engine import AudioEngine, AudioEngineError
from app.audio.device_manager import AudioDeviceInfo
from config import AUDIBLE_CONFIG, TransmissionMode


MOCK_IN_DEV = AudioDeviceInfo(
    index=1,
    name="Mock Microphone",
    host_api_index=0,
    host_api_name="MME",
    max_input_channels=1,
    max_output_channels=0,
    default_sample_rate=48000.0,
    is_default_input=True,
)

MOCK_OUT_DEV = AudioDeviceInfo(
    index=2,
    name="Mock Speaker",
    host_api_index=0,
    host_api_name="MME",
    max_input_channels=0,
    max_output_channels=2,
    default_sample_rate=48000.0,
    is_default_output=True,
)


@pytest.fixture
def mock_audio_env():
    """Mock sounddevice and hardware device manager interactions."""
    with patch("app.audio.audio_engine.AudioDeviceManager") as mock_dm_cls, \
         patch("sounddevice.InputStream") as mock_stream_cls, \
         patch("sounddevice.play") as mock_play, \
         patch("sounddevice.wait") as mock_wait:

        mock_dm = mock_dm_cls.return_value
        mock_dm.get_default_input_device.return_value = MOCK_IN_DEV
        mock_dm.get_default_output_device.return_value = MOCK_OUT_DEV
        mock_dm.validate_input_device.return_value = MOCK_IN_DEV
        mock_dm.validate_output_device.return_value = MOCK_OUT_DEV

        mock_stream = MagicMock()
        mock_stream_cls.return_value = mock_stream

        yield {
            "dm": mock_dm,
            "stream": mock_stream,
            "play": mock_play,
            "wait": mock_wait,
        }


def test_audio_engine_start_and_stop(mock_audio_env) -> None:
    """Verify audio capture startup and clean thread/stream shutdown."""
    engine = AudioEngine(input_device_index=1, output_device_index=2)

    assert not engine.is_running
    engine.start_capture()
    assert engine.is_running

    # Stream should be opened and started
    mock_audio_env["stream"].start.assert_called_once()

    # Stop capture
    engine.stop_capture()
    assert not engine.is_running
    mock_audio_env["stream"].stop.assert_called_once()
    mock_audio_env["stream"].close.assert_called_once()


def test_transmission_state_and_echo_suppression(mock_audio_env) -> None:
    """Verify that is_suppressed() is active during transmission and during the post-tx guard delay."""
    # Use 100 ms guard delay for snappy test execution
    engine = AudioEngine(guard_delay_ms=100)
    assert not engine.is_suppressed()

    status = engine.get_suppression_status()
    assert not status["is_suppressed"]
    assert not status["is_transmitting"]

    # Generate a dummy float32 waveform
    dummy_waveform = np.zeros(1024, dtype=np.float32).tobytes()

    # Play waveform
    engine.play_waveform(dummy_waveform, blocking=True)

    # Immediately after playback, guard delay should be active
    assert engine.is_suppressed()
    status_guard = engine.get_suppression_status()
    assert status_guard["in_guard_period"]
    assert status_guard["is_suppressed"]

    # Wait for the guard delay (100 ms) to expire
    time.sleep(0.15)
    assert not engine.is_suppressed()
    assert not engine.get_suppression_status()["in_guard_period"]


def test_audio_callback_suppression(mock_audio_env) -> None:
    """Verify that the real-time audio callback discards buffers when suppressed."""
    engine = AudioEngine(guard_delay_ms=250)
    engine._running = True

    # 1. Not suppressed: buffer should be enqueued
    test_block = np.ones((1024, 1), dtype=np.float32)
    engine._audio_callback(test_block, 1024, {}, 0)
    assert not engine._audio_queue.empty()
    queued_item = engine._audio_queue.get_nowait()
    assert queued_item == test_block.tobytes()

    # 2. Suppressed: buffer should be discarded
    with engine._tx_lock:
        engine._is_transmitting = True

    assert engine.is_suppressed()
    engine._audio_callback(test_block, 1024, {}, 0)
    assert engine._audio_queue.empty()  # Discarded, nothing in queue


def test_queue_overflow_handling(mock_audio_env) -> None:
    """Verify that when the audio queue is full, blocks are dropped gracefully without crashing."""
    engine = AudioEngine()
    engine._running = True
    # Fill the internal audio queue to capacity
    while not engine._audio_queue.full():
        engine._audio_queue.put_nowait(b"\x00" * 4096)

    assert engine.dropped_blocks_count == 0

    # Incoming audio block when queue is full
    test_block = np.zeros((1024, 1), dtype=np.float32)
    engine._audio_callback(test_block, 1024, {}, 0)

    # Dropped blocks counter should increment without throwing exception
    assert engine.dropped_blocks_count == 1


def test_payload_dispatch_and_callbacks(mock_audio_env) -> None:
    """Verify that demodulated payloads are dispatched to callbacks and the received queue."""
    engine = AudioEngine()
    received_via_callback = []

    def sample_callback(data: bytes):
        received_via_callback.append(data)

    engine.register_callback(sample_callback)

    test_payload = b"ChirpDrop Acoustic Message"
    engine._dispatch_payload(test_payload)

    # Check callback
    assert len(received_via_callback) == 1
    assert received_via_callback[0] == test_payload

    # Check received queue
    assert not engine.received_queue.empty()
    assert engine.received_queue.get_nowait() == test_payload

    # Unregister callback
    engine.unregister_callback(sample_callback)
    engine._dispatch_payload(b"Second Message")
    assert len(received_via_callback) == 1  # Not called again


def test_transmission_mode_toggle(mock_audio_env) -> None:
    """Verify switching transmission profile between Audible and Ultrasonic."""
    engine = AudioEngine(transmission_mode=TransmissionMode.AUDIBLE)
    assert engine.transmission_mode == TransmissionMode.AUDIBLE
    assert engine._get_active_protocol_id() == AUDIBLE_CONFIG.ggwave_protocol_id

    engine.set_transmission_mode(TransmissionMode.ULTRASONIC)
    assert engine.transmission_mode == TransmissionMode.ULTRASONIC
    assert engine._get_active_protocol_id() == 3
