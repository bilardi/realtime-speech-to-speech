"""CLI audio client: captures audio from a system device and sends PCM to the server."""

import argparse
import asyncio

import numpy as np
import sounddevice as sd
import websockets


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: argument list, None means sys.argv[1:].

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(description="Audio client for speech-to-speech")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument(
        "--server", type=str, default="ws://localhost:8000", help="Server WebSocket URL"
    )
    parser.add_argument("--ws-path", type=str, default="/ws/speak", help="WebSocket endpoint path")
    parser.add_argument("--room", type=str, default="1", help="Room id (default '1')")
    parser.add_argument(
        "--lang", type=str, default="it-IT", help="Language code (e.g. it-IT, en-US)"
    )
    parser.add_argument("--device", type=int, default=None, help="Audio device index")
    return parser.parse_args(argv)


def to_pcm16(audio: np.ndarray) -> bytes:
    """Convert float32 audio samples to PCM 16-bit little-endian bytes.

    Args:
        audio: numpy array of float32 samples in [-1.0, 1.0].

    Returns:
        Raw PCM bytes.
    """
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    return pcm.tobytes()


def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample audio using linear interpolation.

    Args:
        audio: input samples as float32.
        src_rate: source sample rate.
        dst_rate: destination sample rate.

    Returns:
        Resampled float32 array.
    """
    if src_rate == dst_rate:
        return audio
    duration = len(audio) / src_rate
    dst_len = int(duration * dst_rate)
    indices = np.linspace(0, len(audio) - 1, dst_len)
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


async def stream_audio(
    server: str,
    ws_path: str,
    room: str,
    lang: str,
    device: int | None,
) -> None:
    """Capture audio from device and stream to server.

    Args:
        server: WebSocket server base URL.
        ws_path: WebSocket endpoint path (e.g. /ws/speak).
        room: Room id.
        lang: BCP-47 language code.
        device: audio device index, or None for default.
    """
    url = f"{server.rstrip('/')}{ws_path}?room={room}&lang={lang}"
    target_rate = 16000
    chunk_duration = 0.1
    device_info = sd.query_devices(device, "input")  # type: ignore[reportUnknownMemberType]
    src_rate = int(device_info["default_samplerate"])
    block_size = int(src_rate * chunk_duration)

    print(f"Connecting to {url}", flush=True)  # noqa: T201
    print(f"Device: {device_info['name']} ({src_rate} Hz)", flush=True)  # noqa: T201
    print(f"Room: {room} | Language: {lang}", flush=True)  # noqa: T201
    print("Press Ctrl+C to stop", flush=True)  # noqa: T201

    async with websockets.connect(url) as ws:
        loop = asyncio.get_event_loop()
        audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        def audio_callback(
            indata: np.ndarray,
            frames: int,  # noqa: ARG001
            time_info: object,  # noqa: ARG001
            status: sd.CallbackFlags,  # noqa: ARG001
        ) -> None:
            mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
            resampled = resample(mono, src_rate, target_rate)
            pcm = to_pcm16(resampled)
            loop.call_soon_threadsafe(audio_queue.put_nowait, pcm)

        stream = sd.InputStream(
            device=device,
            channels=1,
            samplerate=src_rate,
            blocksize=block_size,
            dtype="float32",
            callback=audio_callback,
        )

        with stream:
            try:
                while True:
                    chunk = await audio_queue.get()
                    if chunk is None:
                        break
                    await ws.send(chunk)
            except KeyboardInterrupt:
                print("\nStopped", flush=True)  # noqa: T201


def main() -> None:
    """Entry point."""
    args = parse_args()

    if args.list_devices:
        print(sd.query_devices())  # type: ignore[reportUnknownMemberType]  # noqa: T201
        return

    asyncio.run(stream_audio(args.server, args.ws_path, args.room, args.lang, args.device))
