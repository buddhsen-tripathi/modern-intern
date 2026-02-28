/**
 * AudioWorklet processor for mic capture.
 * Downsamples from native rate to 16kHz, outputs 480-sample Int16 chunks (30ms).
 */
class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = [];
    this.ratio = sampleRate / 16000;
    this.accumulator = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const samples = input[0]; // mono channel

    // Downsample by picking every Nth sample
    for (let i = 0; i < samples.length; i++) {
      this.accumulator++;
      if (this.accumulator >= this.ratio) {
        this.accumulator -= this.ratio;
        // Clamp and convert float32 -> int16
        const s = Math.max(-1, Math.min(1, samples[i]));
        this.buffer.push(s * 32767);
      }
    }

    // Send 480-sample chunks (30ms at 16kHz, matching VAD expectation)
    while (this.buffer.length >= 480) {
      const chunk = new Int16Array(480);
      for (let i = 0; i < 480; i++) {
        chunk[i] = this.buffer[i];
      }
      this.buffer.splice(0, 480);
      this.port.postMessage(chunk.buffer, [chunk.buffer]);
    }

    return true;
  }
}

registerProcessor("mic-processor", MicProcessor);
