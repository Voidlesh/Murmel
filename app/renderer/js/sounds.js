// Start/stop use the reference app's sound files; the error tone stays synthesized.
const startSound = new Audio('assets/sounds/dictation-start.wav');
const stopSound = new Audio('assets/sounds/dictation-stop.wav');

function play(audio) {
  audio.currentTime = 0;
  audio.play().catch(() => {});
}

let ctx = null;

function tone(freqs, { duration = 0.12, gain = 0.06, type = 'sine', gap = 0.07 } = {}) {
  ctx = ctx || new AudioContext();
  const now = ctx.currentTime;
  freqs.forEach((freq, i) => {
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    const start = now + i * gap;
    osc.type = type;
    osc.frequency.setValueAtTime(freq, start);
    amp.gain.setValueAtTime(0, start);
    amp.gain.linearRampToValueAtTime(gain, start + 0.012);
    amp.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(amp).connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.02);
  });
}

export const playStart = () => play(startSound);
export const playStop = () => play(stopSound);
export const playError = () => tone([220, 196], { type: 'triangle', duration: 0.18 });
