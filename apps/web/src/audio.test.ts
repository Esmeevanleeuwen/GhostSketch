import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { encodeWav, resamplePCM, startRecording, type RecordingState } from './audio';

describe('independent PCM WAV fragments', () => {
  it('writes a standard mono 16kHz PCM16 header, clips samples and keeps silence finite', async () => {
    const wav = encodeWav(new Float32Array([-2, -1, 0, 1, 2, Number.NaN]), 16_000);
    const bytes = await wav.arrayBuffer();
    const view = new DataView(bytes);
    const text = (offset: number, length: number) => String.fromCharCode(...new Uint8Array(bytes, offset, length));
    expect(wav.type).toBe('audio/wav');
    expect(text(0, 4)).toBe('RIFF');
    expect(text(8, 4)).toBe('WAVE');
    expect(text(12, 4)).toBe('fmt ');
    expect(text(36, 4)).toBe('data');
    expect(view.getUint32(4, true)).toBe(bytes.byteLength - 8);
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint32(28, true)).toBe(32_000);
    expect(view.getUint16(32, true)).toBe(2);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(12);
    expect(Array.from({ length: 6 }, (_, i) => view.getInt16(44 + i * 2, true))).toEqual([-32768, -32768, 0, 32767, 32767, 0]);
  });

  it('preserves a 1kHz tone and duration when converting a typical 48kHz device', async () => {
    const samples = Float32Array.from({ length: 48_000 }, (_, i) => Math.sin(i * 2 * Math.PI * 1_000 / 48_000));
    const resampled = resamplePCM(samples, 48_000);
    expect(resampled.length).toBe(16_000);
    for (let i = 0; i < 160; i += 1) expect(resampled[i]).toBeCloseTo(Math.sin(i * 2 * Math.PI * 1_000 / 16_000), 5);
    const wav = await encodeWav(samples, 48_000).arrayBuffer();
    expect(new DataView(wav).getUint32(40, true)).toBe(32_000);
  });

  it('interpolates fractional sample positions and rejects invalid sample rates', () => {
    expect(Array.from(resamplePCM(new Float32Array([0, 1, 0, -1]), 4, 8))).toEqual([0, .5, 1, .5, 0, -.5, -1, -1]);
    expect(() => resamplePCM(new Float32Array(), 0)).toThrow('audiofrequentie');
    expect(() => resamplePCM(new Float32Array(), Number.NaN)).toThrow('audiofrequentie');
    expect(resamplePCM(new Float32Array(), 48_000)).toHaveLength(0);
  });
});

// Lifecycle tests use deterministic Web Audio doubles. They do not claim that a
// real microphone, speech model or hardware performance was tested.
class AudioNodeDouble {
  connect = vi.fn();
  disconnect = vi.fn();
}
class AudioContextDouble {
  static current: AudioContextDouble;
  sampleRate = 16_000;
  state = 'suspended';
  onstatechange: (() => void) | null = null;
  destination = {};
  audioWorklet = { addModule: vi.fn(async () => undefined) };
  source = new AudioNodeDouble();
  gain = { ...new AudioNodeDouble(), gain: { value: 1 } };
  createMediaStreamSource = vi.fn(() => this.source);
  createGain = vi.fn(() => this.gain);
  resume = vi.fn(async () => { this.state = 'running'; });
  close = vi.fn(async () => { this.state = 'closed'; this.onstatechange?.(); });
  constructor() { AudioContextDouble.current = this; }
}
class WorkletDouble extends AudioNodeDouble {
  static current: WorkletDouble;
  onprocessorerror: (() => void) | null = null;
  port = {
    onmessage: null as ((event: { data: unknown }) => void) | null,
    postMessage: vi.fn((message: { type: string }) => {
      if (message.type === 'flush') queueMicrotask(() => this.port.onmessage?.({ data: { type: 'flushed' } }));
    }),
    close: vi.fn(),
  };
  constructor() { super(); WorkletDouble.current = this; }
  emit(samples: Float32Array) {
    this.port.onmessage?.({ data: { type: 'samples', id: 1, buffer: samples.buffer } });
  }
}
function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}
function feedSamples(count: number) {
  for (let left = count; left > 0; left -= Math.min(left, 4096)) {
    WorkletDouble.current.emit(new Float32Array(Math.min(left, 4096)).fill(.1));
  }
}

describe('capture lifecycle and bounded processing', () => {
  let track: { stop: ReturnType<typeof vi.fn>; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> };
  let media: { getTracks: () => typeof track[] };
  let getUserMedia: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    track = { stop: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() };
    media = { getTracks: () => [track] };
    getUserMedia = vi.fn(async () => media);
    vi.stubGlobal('window', { AudioContext: AudioContextDouble, location: { origin: 'http://localhost:8000' } });
    vi.stubGlobal('AudioWorkletNode', WorkletDouble);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('requests a device only on explicit start and releases it before pending transcription finishes', async () => {
    expect(getUserMedia).not.toHaveBeenCalled();
    const firstUpload = deferred<void>();
    const onChunk = vi.fn().mockImplementationOnce(() => firstUpload.promise).mockResolvedValue(undefined);
    const states: RecordingState[] = [];
    const recorder = await startRecording({ deviceId: 'chosen-device', startMs: 12_500, onChunk, onState: (s) => states.push(s) });
    expect(getUserMedia).toHaveBeenCalledWith(expect.objectContaining({ audio: expect.objectContaining({ deviceId: { exact: 'chosen-device' } }), video: false }));
    feedSamples(16_000 * 8);
    feedSamples(4_000);
    const stopping = recorder.stop();
    expect(track.stop).toHaveBeenCalled();
    expect(states.at(-1)).toEqual({ capturing: false, pending: 1 });
    await vi.waitFor(() => expect(AudioContextDouble.current.state).toBe('closed'));
    expect(onChunk).toHaveBeenCalledTimes(1);
    firstUpload.resolve();
    await stopping;
    expect(onChunk).toHaveBeenCalledTimes(2);
    expect(onChunk.mock.calls[0][1]).toBe(12_500);
    expect(onChunk.mock.calls[1][1]).toBe(20_500);
    expect((onChunk.mock.calls[0][0] as Blob).size).toBe(256_044);
    expect((onChunk.mock.calls[1][0] as Blob).size).toBe(8_044);
    expect(states.at(-1)).toEqual({ capturing: false, pending: 0 });
    expect(WorkletDouble.current.port.close).toHaveBeenCalled();
  });

  it('stops capture when two fragments are pending and processes those fragments sequentially', async () => {
    const firstUpload = deferred<void>();
    const onChunk = vi.fn().mockImplementationOnce(() => firstUpload.promise).mockResolvedValue(undefined);
    const onError = vi.fn();
    const states: RecordingState[] = [];
    const recorder = await startRecording({ onChunk, onError, onState: (s) => states.push(s) });
    feedSamples(16_000 * 16);
    expect(track.stop).toHaveBeenCalled();
    expect(Math.max(...states.map((s) => s.pending))).toBe(2);
    expect(states.at(-1)?.capturing).toBe(false);
    expect(onError.mock.calls[0][0].message).toContain('loopt achter');
    await Promise.resolve();
    expect(onChunk).toHaveBeenCalledTimes(1);
    firstUpload.resolve();
    await recorder.stop();
    expect(onChunk).toHaveBeenCalledTimes(2);
    expect(states.at(-1)).toEqual({ capturing: false, pending: 0 });
  });

  it('cleans up when device permission is rejected and explains the next step', async () => {
    getUserMedia.mockRejectedValue(new DOMException('Denied', 'NotAllowedError'));
    await expect(startRecording({ onChunk: vi.fn() })).rejects.toThrow('Controleer de browsertoestemming');
    expect(AudioContextDouble.current.close).toHaveBeenCalled();
  });

  it('releases a stream that arrives after the start operation was cancelled', async () => {
    const permission = deferred<typeof media>();
    getUserMedia.mockReturnValue(permission.promise);
    const controller = new AbortController();
    const start = startRecording({ signal: controller.signal, onChunk: vi.fn() });
    controller.abort();
    permission.resolve(media);
    await expect(start).rejects.toThrow('geannuleerd');
    expect(track.stop).toHaveBeenCalled();
    expect(AudioContextDouble.current.state).toBe('closed');
  });

  it('releases capture and reports an upload failure without a fabricated transcript', async () => {
    const onError = vi.fn();
    const recorder = await startRecording({ onChunk: vi.fn().mockRejectedValue(new Error('Lokaal model niet beschikbaar.')), onError });
    feedSamples(16_000 * 8);
    await vi.waitFor(() => expect(track.stop).toHaveBeenCalled());
    await recorder.stop();
    expect(onError.mock.calls[0][0].message).toContain('audio wordt niet bewaard');
    expect(onError.mock.calls[0][0].message).toContain('Lokaal model niet beschikbaar');
  });

  it('shares cleanup when a UI state callback stops the same recorder again', async () => {
    let recorder: Awaited<ReturnType<typeof startRecording>> | undefined;
    let reentrantStop: Promise<void> | undefined;
    recorder = await startRecording({
      onChunk: vi.fn().mockResolvedValue(undefined),
      onState: (state) => { if (recorder && !state.capturing) reentrantStop = recorder.stop(); },
    });
    const stopping = recorder.stop();
    expect(reentrantStop).toBe(stopping);
    await stopping;
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(AudioContextDouble.current.close).toHaveBeenCalledTimes(1);
  });
});
