/* Independent local PCM transport. No microphone is opened by this module. */
class GhostSketchPCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(4096);
    this.length = 0;
    this.nextId = 0;
    this.pending = new Set();
    this.accepting = true;
    this.overflowSent = false;
    this.port.onmessage = ({ data }) => {
      if (data?.type === 'ack') this.pending.delete(data.id);
      if (data?.type === 'flush') {
        this.accepting = false;
        this.publish(true);
        this.port.postMessage({ type: 'flushed' });
      }
    };
  }

  publish(force = false) {
    if (!this.length) return;
    // Bound the cross-thread queue too: a blocked UI must not accumulate PCM.
    if (!force && this.pending.size >= 8) {
      this.accepting = false;
      if (!this.overflowSent) {
        this.overflowSent = true;
        this.port.postMessage({ type: 'overflow' });
      }
      return;
    }
    const id = this.nextId++;
    const packet = this.length === this.block.length ? this.block : this.block.slice(0, this.length);
    this.pending.add(id);
    this.port.postMessage({ type: 'samples', id, buffer: packet.buffer }, [packet.buffer]);
    this.block = new Float32Array(4096);
    this.length = 0;
  }

  process(inputs, outputs) {
    // The worklet remains connected to a silent destination so flush works.
    for (const channel of outputs[0] ?? []) channel.fill(0);
    const channels = inputs[0];
    if (!this.accepting || !channels?.length || !channels[0]?.length) return true;
    for (let i = 0; i < channels[0].length && this.accepting; i += 1) {
      let sample = 0;
      for (const channel of channels) sample += channel[i] ?? 0;
      this.block[this.length++] = sample / channels.length;
      if (this.length === this.block.length) this.publish();
    }
    return true;
  }
}
registerProcessor('ghostsketch-pcm', GhostSketchPCM);
