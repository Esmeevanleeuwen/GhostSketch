/** Local microphone capture. No device access occurs until startRecording is called. */
export interface RecordingState {
  capturing: boolean;
  /** Complete WAV fragments awaiting or currently undergoing processing. */
  pending: number;
}

export interface RecordingOptions {
  deviceId?: string;
  startMs?: number;
  signal?: AbortSignal;
  onChunk: (wav: Blob, startMs: number) => Promise<void>;
  onState?: (state: RecordingState) => void;
  onLevel?: (level: number) => void;
  onError?: (error: Error) => void;
}

export interface RecordingHandle {
  /** Releases the microphone immediately, then drains already captured fragments. */
  stop: () => Promise<void>;
}

const OUTPUT_RATE = 16_000;
const CHUNK_SECONDS = 8;
const MAX_PENDING = 2;

/** Resample mono PCM, preserving sample duration and using linear interpolation. */
export function resamplePCM(samples: Float32Array, inputRate: number, outputRate = OUTPUT_RATE): Float32Array {
  if (!Number.isFinite(inputRate) || inputRate <= 0 || !Number.isFinite(outputRate) || outputRate <= 0) {
    throw new Error('De audiofrequentie is ongeldig.');
  }
  if (inputRate === outputRate) return samples.slice();
  const output = new Float32Array(Math.round(samples.length * outputRate / inputRate));
  const ratio = inputRate / outputRate;
  for (let i = 0; i < output.length; i += 1) {
    const position = i * ratio;
    const left = Math.min(Math.floor(position), samples.length - 1);
    const right = Math.min(left + 1, samples.length - 1);
    const fraction = position - left;
    output[i] = (samples[left] ?? 0) * (1 - fraction) + (samples[right] ?? 0) * fraction;
  }
  return output;
}

/** An independent, standard mono PCM16 WAV, never a partial MediaRecorder container. */
export function encodeWav(samples: Float32Array, inputRate: number): Blob {
  const pcm = resamplePCM(samples, inputRate);
  const bytes = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(bytes);
  const write = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
  };
  write(0, 'RIFF');
  view.setUint32(4, bytes.byteLength - 8, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, OUTPUT_RATE, true);
  view.setUint32(28, OUTPUT_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, 'data');
  view.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i += 1) {
    const sample = Number.isFinite(pcm[i]) ? Math.max(-1, Math.min(1, pcm[i])) : 0;
    view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 0x8000 : 0x7fff)), true);
  }
  return new Blob([bytes], { type: 'audio/wav' });
}

function friendlyStartError(error: unknown): Error {
  if (error instanceof DOMException) {
    if (error.name === 'AbortError') return new Error('Het starten van de opname is geannuleerd.');
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return new Error('De microfoon is niet toegestaan. Controleer de browsertoestemming of importeer een opname.');
    }
    if (error.name === 'NotFoundError' || error.name === 'OverconstrainedError') {
      return new Error('De gekozen microfoon is niet beschikbaar. Kies een ander apparaat.');
    }
    if (error.name === 'NotReadableError') {
      return new Error('De microfoon kan niet worden geopend. Controleer of een ander programma hem gebruikt.');
    }
  }
  return error instanceof Error ? error : new Error('De opname kon niet worden gestart.');
}

export async function startRecording(options: RecordingOptions): Promise<RecordingHandle> {
  if (typeof window === 'undefined' || typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
    throw new Error('Deze browser kan hier geen microfoon openen. Gebruik localhost of HTTPS, of importeer een opname.');
  }
  if (options.signal?.aborted) throw new Error('Het starten van de opname is geannuleerd.');
  const audioWindow = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
  const Context = audioWindow.AudioContext ?? audioWindow.webkitAudioContext;
  if (!Context || typeof AudioWorkletNode === 'undefined') {
    throw new Error('Deze browser ondersteunt geen lokale audio-opname. Gebruik een recente browser of importeer een opname.');
  }
  const context = new Context({ latencyHint: 'interactive' });
  // Resume during the initiating gesture; some mobile browsers require this
  // before asynchronous device permission or worklet loading completes.
  void context.resume().catch(() => undefined);
  let stream: MediaStream | undefined;
  let source: MediaStreamAudioSourceNode | undefined;
  let processor: AudioWorkletNode | undefined;
  let mute: GainNode | undefined;
  let capturing = false;
  let stopping = false;
  let finished = false;
  let failed = false;
  let stopPromise: Promise<void> | undefined;
  let flushAcknowledge: (() => void) | undefined;
  let processing: Promise<void> | undefined;
  let inFlight = false;
  let pieces: Float32Array[] = [];
  let buffered = 0;
  let positionMs = Number.isFinite(options.startMs) ? Math.max(0, options.startMs ?? 0) : 0;
  const maxSamples = Math.round(context.sampleRate * CHUNK_SECONDS);
  const queue: Array<{ blob: Blob; startMs: number }> = [];

  const pending = () => queue.length + (inFlight ? 1 : 0);
  const notify = () => {
    try { options.onState?.({ capturing, pending: pending() }); } catch { /* UI errors must not retain a microphone. */ }
  };
  const report = (error: Error) => {
    try { options.onError?.(error); } catch { /* Cleanup continues even if a UI callback throws. */ }
  };
  const level = (value: number) => {
    try { options.onLevel?.(value); } catch { /* Metering is optional. */ }
  };
  const endListener = () => {
    if (!stopping) {
      report(new Error('De microfoon is losgekoppeld of gestopt. Ontvangen audio wordt nog verwerkt.'));
      void stop();
    }
  };
  const abortListener = () => { void stop(); };

  function takeBuffer(): Float32Array {
    const result = new Float32Array(buffered);
    let offset = 0;
    for (const piece of pieces) {
      result.set(piece, offset);
      offset += piece.length;
    }
    pieces = [];
    buffered = 0;
    return result;
  }

  function pump(): void {
    if (processing || failed) return;
    // Set the promise before invoking consumer code, including callbacks that
    // synchronously throw or stop this recorder themselves.
    processing = Promise.resolve().then(async () => {
      while (queue.length && !failed) {
        const item = queue.shift()!;
        inFlight = true;
        notify();
        try {
          await options.onChunk(item.blob, item.startMs);
        } catch (error) {
          failed = true;
          queue.length = 0;
          const detail = error instanceof Error ? ` ${error.message}` : '';
          report(new Error(`Een audiofragment kon niet worden verwerkt. De opname is gestopt; audio wordt niet bewaard.${detail}`));
          void stop();
        } finally {
          inFlight = false;
          notify();
        }
      }
    }).finally(() => {
      processing = undefined;
      notify();
    });
  }

  function enqueue(samples: Float32Array): void {
    if (!samples.length || failed) return;
    queue.push({ blob: encodeWav(samples, context.sampleRate), startMs: Math.round(positionMs) });
    positionMs += samples.length * 1000 / context.sampleRate;
    pump();
    notify();
    // Stop capture as soon as the bounded processing queue is full. Already
    // received samples are kept only until these local requests finish.
    if (pending() >= MAX_PENDING && !stopping) {
      report(new Error('De verwerking loopt achter. De opname is gestopt; ontvangen audio wordt nog verwerkt.'));
      void stop();
    }
  }

  function receive(samples: Float32Array): void {
    if (finished || failed) return;
    let sum = 0;
    for (const value of samples) sum += value * value;
    if (capturing) level(Math.min(1, Math.sqrt(sum / Math.max(1, samples.length)) * 3));
    let offset = 0;
    while (offset < samples.length) {
      const size = Math.min(maxSamples - buffered, samples.length - offset);
      pieces.push(samples.slice(offset, offset + size));
      buffered += size;
      offset += size;
      if (buffered === maxSamples) enqueue(takeBuffer());
    }
  }

  async function drain(): Promise<void> {
    while (processing) await processing;
  }

  /** This function releases input synchronously before it returns a promise. */
  function stop(): Promise<void> {
    if (stopPromise) return stopPromise;
    stopping = true;
    capturing = false;
    // Assign before notifying consumers so reentrant calls share one cleanup.
    stopPromise = Promise.resolve().then(finishStop);
    for (const track of stream?.getTracks() ?? []) {
      track.removeEventListener('ended', endListener);
      track.stop();
    }
    source?.disconnect();
    level(0);
    notify();
    return stopPromise;
  }

  async function finishStop(): Promise<void> {
    // Leave the silent worklet connected briefly to collect its final partial
    // packet. It cannot access new input after the tracks/source stop above.
    if (processor) {
      await new Promise<void>((resolve) => {
        const timeout = setTimeout(() => {
          flushAcknowledge = undefined;
          report(new Error('Het laatste kleine audiofragment kon niet volledig worden opgehaald.'));
          resolve();
        }, 500);
        flushAcknowledge = () => { clearTimeout(timeout); resolve(); };
        try {
          processor!.port.postMessage({ type: 'flush' });
        } catch {
          clearTimeout(timeout);
          flushAcknowledge = undefined;
          resolve();
        }
      });
      processor.port.onmessage = null;
      processor.onprocessorerror = null;
      processor.disconnect();
      processor.port.close();
    }
    mute?.disconnect();
    context.onstatechange = null;
    try { if (context.state !== 'closed') await context.close(); } catch { /* Input tracks are already released. */ }
    options.signal?.removeEventListener('abort', abortListener);
    await drain();
    if (!failed && buffered) {
      enqueue(takeBuffer());
      await drain();
    }
    pieces = [];
    buffered = 0;
    finished = true;
    notify();
  }

  notify();
  options.signal?.addEventListener('abort', abortListener, { once: true });
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        ...(options.deviceId ? { deviceId: { exact: options.deviceId } } : {}),
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
      video: false,
    });
    if (stopping || options.signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
    for (const track of stream.getTracks()) track.addEventListener('ended', endListener);
    capturing = true;
    notify();
    if (!context.audioWorklet) throw new Error('Deze browser ondersteunt geen AudioWorklet. Importeer een opname.');
    await context.audioWorklet.addModule(new URL('/pcm-worklet.js', window.location.origin).href);
    if (stopping) throw new DOMException('Cancelled', 'AbortError');
    processor = new AudioWorkletNode(context, 'ghostsketch-pcm', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    processor.port.onmessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; id?: number; buffer?: ArrayBuffer } | undefined;
      if (data?.type === 'samples' && data.buffer instanceof ArrayBuffer && data.buffer.byteLength <= 16_384 && data.buffer.byteLength % 4 === 0) {
        processor?.port.postMessage({ type: 'ack', id: data.id });
        receive(new Float32Array(data.buffer));
      } else if (data?.type === 'flushed') {
        flushAcknowledge?.();
        flushAcknowledge = undefined;
      } else if (data?.type === 'overflow' && !stopping) {
        report(new Error('De audioverwerking is onderbroken. De opname is gestopt; ontvangen audio wordt nog verwerkt.'));
        void stop();
      }
    };
    processor.onprocessorerror = () => {
      if (!stopping) {
        report(new Error('De lokale audioverwerking is gestopt. Start opnieuw of importeer een opname.'));
        void stop();
      }
    };
    source = context.createMediaStreamSource(stream);
    mute = context.createGain();
    mute.gain.value = 0;
    source.connect(processor);
    processor.connect(mute);
    mute.connect(context.destination);
    await context.resume();
    if (stopping) throw new DOMException('Cancelled', 'AbortError');
    context.onstatechange = () => {
      if (capturing && context.state !== 'running') {
        report(new Error('De browser heeft de audioverwerking onderbroken. Ontvangen audio wordt nog verwerkt.'));
        void stop();
      }
    };
    return { stop };
  } catch (error) {
    // A permission prompt can resolve after cancellation. Stop those late tracks
    // even if an earlier stop promise has already completed.
    for (const track of stream?.getTracks() ?? []) track.stop();
    await stop();
    if (options.signal?.aborted) throw friendlyStartError(new DOMException('Cancelled', 'AbortError'));
    throw friendlyStartError(error);
  }
}
