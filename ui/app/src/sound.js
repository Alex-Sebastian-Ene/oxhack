// Hormuz Flow sound, all synthesised in the browser with the Web Audio API: there are no recordings, so
// nothing needs a licence. The music is "Night Shift", an original chiptune loop written for this app.
// The harbour (water, machinery hum, steam, clanks, a distant horn) and the interface sounds are built
// from oscillators and filtered noise. Browsers only allow sound after a click or key press.
window.HZSound = (() => {
  let ctx = null, master, musicBus, ambBus, sfxBus, lead, echo, hum, waterG;
  let soundOn = false, musicOn = false, tension = 0.69, ambOn = false;
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };

  // ------------------------------------------------------------ set-up
  function ensure() {
    if (ctx) return true;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    master = ctx.createGain(); master.gain.value = 0.0001; master.connect(ctx.destination);
    musicBus = ctx.createGain(); musicBus.gain.value = 0.0001; musicBus.connect(master);
    ambBus = ctx.createGain(); ambBus.gain.value = 0.0001; ambBus.connect(master);
    sfxBus = ctx.createGain(); sfxBus.gain.value = 0.55; sfxBus.connect(master);
    lead = ctx.createBiquadFilter(); lead.type = "lowpass"; lead.frequency.value = 3200; lead.Q.value = 0.7; lead.connect(musicBus);
    // a short echo for the lead, for a night-time harbour sound
    echo = ctx.createDelay(1); echo.delayTime.value = 0.43;
    const fb = ctx.createGain(); fb.gain.value = 0.28; const wet = ctx.createGain(); wet.gain.value = 0.3;
    lead.connect(echo); echo.connect(fb).connect(echo); echo.connect(wet).connect(musicBus);
    return true;
  }
  const now = () => ctx.currentTime;
  const ramp = (p, v, tc = 0.25) => { p.cancelScheduledValues(now()); p.setTargetAtTime(v, now(), tc); };
  let noiseBuf = null;
  function noise() {
    if (noiseBuf) return noiseBuf;
    const len = ctx.sampleRate * 2; noiseBuf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0); for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return noiseBuf;
  }
  // a square wave with a narrow pulse, for the classic chiptune lead
  const pulses = {};
  function pulse(duty) {
    if (pulses[duty]) return pulses[duty];
    const n = 32, re = new Float32Array(n), im = new Float32Array(n);
    for (let k = 1; k < n; k++) im[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * duty);
    return (pulses[duty] = ctx.createPeriodicWave(re, im));
  }
  function tone(dest, { f, t, dur, vol, wave = "square", duty, attack = 0.005, release = 0.06, slide, detune = 0 }) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    if (duty) o.setPeriodicWave(pulse(duty)); else o.type = wave;
    o.frequency.setValueAtTime(f, t); o.detune.value = detune;
    if (slide) o.frequency.exponentialRampToValueAtTime(slide, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + attack);
    g.gain.setValueAtTime(vol, t + Math.max(attack, dur - release)); g.gain.exponentialRampToValueAtTime(0.0001, t + dur + release);
    o.connect(g).connect(dest); o.start(t); o.stop(t + dur + release + 0.02);
  }
  function hiss(dest, { t, dur, vol, type = "highpass", f = 6000, q = 0.7, sweep }) {
    const s = ctx.createBufferSource(), fl = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = noise(); fl.type = type; fl.frequency.setValueAtTime(f, t); fl.Q.value = q;
    if (sweep) fl.frequency.exponentialRampToValueAtTime(sweep, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + Math.min(0.02, dur / 4)); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(fl).connect(g).connect(dest); s.start(t, Math.random() * 1.5); s.stop(t + dur + 0.05);
  }

  // ------------------------------------------------------------ music: "Night Shift", 16 bars in A minor
  const NOTE = (n) => { const m = n.match(/^([A-G])(#?)(\d)$/), s = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[m[1]] + (m[2] ? 1 : 0); return 440 * Math.pow(2, (s + (Number(m[3]) + 1) * 12 - 69) / 12); };
  const CH = { Am: ["A3", "C4", "E4"], F: ["F3", "A3", "C4"], C: ["C4", "E4", "G4"], G: ["G3", "B3", "D4"], Em: ["E3", "G3", "B3"], E: ["E3", "G#3", "B3"], Dm: ["D3", "F3", "A3"] };
  const BARS = [
    ["Am", "A4 - C5 E5 D5 C5 A4 -"], ["F", "F4 - A4 C5 A4 F4 E4 -"], ["C", "E4 G4 C5 - E5 D5 C5 -"], ["G", "D5 - B4 G4 A4 B4 D5 -"],
    ["Am", "A4 - C5 E5 A5 G5 E5 -"], ["F", "F5 E5 C5 A4 C5 - A4 -"], ["Em", "G4 - B4 E5 D5 B4 G4 -"], ["E", "G#4 - B4 E5 D5 ~ B4 G#4"],
    ["Dm", "D5 ~ F5 E5 D5 C5 A4 -"], ["Am", "C5 ~ E5 D5 C5 B4 A4 -"], ["F", "A4 C5 F5 ~ E5 C5 A4 -"], ["C", "G4 C5 E5 ~ G5 E5 C5 -"],
    ["Dm", "F5 ~ E5 D5 A4 ~ D5 -"], ["Am", "E5 ~ D5 C5 A4 ~ C5 -"], ["E", "B4 ~ G#4 B4 E5 ~ D5 -"], ["E", "E5 ~ ~ ~ - - - -"],
  ];
  const BPM = 100, S16 = 60 / BPM / 4;
  let step = 0, nextT = 0, timer = null;
  function scheduleStep(i, t) {
    const bar = BARS[Math.floor(i / 16) % BARS.length], s = i % 16, chord = CH[bar[0]], mel = bar[1].split(" ");
    // lead: eighth notes, '~' holds the note before, '-' is a rest
    if (s % 2 === 0) {
      const k = s / 2, n = mel[k];
      if (n !== "-" && n !== "~") {
        let len = 1; while (k + len < 8 && mel[k + len] === "~") len++;
        tone(lead, { f: NOTE(n), t, dur: S16 * 2 * len - 0.03, vol: 0.075, duty: 0.25, release: 0.08 });
      }
    }
    // arpeggio: sixteenths up and down the chord, an octave up, quietly
    const arp = [0, 1, 2, 1][s % 4], an = chord[arp].replace(/\d/, (d) => String(Number(d) + 1));
    tone(musicBus, { f: NOTE(an), t, dur: S16 * 0.7, vol: 0.022, wave: "triangle", release: 0.03 });
    // bass: root on the beat, octave on the off-beat
    if (s % 2 === 0) {
      const root = chord[0].replace(/\d/, "2"), f = NOTE(root) * (s % 4 === 2 ? 2 : 1);
      tone(musicBus, { f, t, dur: S16 * 1.6, vol: 0.06, duty: 0.125, release: 0.04 });
    }
    // drums: kick on 1 and 3, a light snare on 2 and 4, closed hats on the eighths
    if (s === 0 || s === 8) tone(musicBus, { f: 130, slide: 42, t, dur: 0.16, vol: 0.13, wave: "sine", release: 0.05 });
    if (s === 4 || s === 12) { hiss(musicBus, { t, dur: 0.12, vol: 0.05, type: "bandpass", f: 1900, q: 0.9 }); tone(musicBus, { f: 190, slide: 120, t, dur: 0.07, vol: 0.03, wave: "triangle" }); }
    if (s % 2 === 0) hiss(musicBus, { t, dur: 0.03, vol: s % 4 ? 0.012 : 0.02, f: 7500 });
  }
  function tick() {
    if (!ctx) return;
    if (nextT < now()) nextT = now() + 0.08;
    while (nextT < now() + 0.3) { scheduleStep(step, nextT); step = (step + 1) % (BARS.length * 16); nextT += S16; }
  }

  // ------------------------------------------------------------ harbour ambience
  let ambTimers = [];
  function startAmbience() {
    if (ambOn) return; ambOn = true;
    // water against the jetty: brown noise, low-passed, swelling slowly
    const len = ctx.sampleRate * 4, buf = ctx.createBuffer(1, len, ctx.sampleRate), d = buf.getChannelData(0);
    let last = 0; for (let i = 0; i < len; i++) { last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02; d[i] = last * 3.2; }
    const w = ctx.createBufferSource(), lp = ctx.createBiquadFilter(), lfo = ctx.createOscillator(), lg = ctx.createGain();
    waterG = ctx.createGain(); waterG.gain.value = 0.2;
    w.buffer = buf; w.loop = true; lp.type = "lowpass"; lp.frequency.value = 520;
    lfo.frequency.value = 0.09; lg.gain.value = 0.12; lfo.connect(lg).connect(waterG.gain);
    w.connect(lp).connect(waterG).connect(ambBus); w.start(); lfo.start();
    // the plant: a low two-tone hum with a slow motor throb
    hum = ctx.createGain(); hum.gain.value = 0.03 + tension * 0.03;
    const hl = ctx.createBiquadFilter(); hl.type = "lowpass"; hl.frequency.value = 220; hl.connect(hum).connect(ambBus);
    [[50, "sawtooth"], [100.7, "sawtooth"], [75.2, "triangle"]].forEach(([f, type]) => { const o = ctx.createOscillator(); o.type = type; o.frequency.value = f; o.connect(hl); o.start(); });
    const thr = ctx.createOscillator(), tg = ctx.createGain(); thr.frequency.value = 5.5; tg.gain.value = 0.012; thr.connect(tg).connect(hum.gain); thr.start();
    // now and then: a steam release, a metal clank, a ship's horn far out
    const every = (min, max, fn) => { const go = () => { if (soundOn) fn(); ambTimers.push(setTimeout(go, (min + Math.random() * (max - min)) * 1000)); }; ambTimers.push(setTimeout(go, (min + Math.random() * (max - min)) * 1000)); };
    every(9, 22, () => hiss(ambBus, { t: now() + 0.05, dur: 0.9 + Math.random() * 0.6, vol: 0.05, f: 2600, sweep: 4200 }));
    every(6, 16, () => clank(ambBus, 0.03 + Math.random() * 0.03, 0.6 + Math.random() * 0.8));
    every(35, 70, () => horn(ambBus, 0.05, 0.85));
  }
  function clank(dest, vol = 0.12, pitch = 1) {
    const t = now() + 0.01;
    [[220, 0.5], [563, 0.35], [1187, 0.22], [1731, 0.12]].forEach(([f, a]) => tone(dest, { f: f * pitch, t, dur: 0.05, vol: vol * a, wave: "sine", release: 0.35 }));
    hiss(dest, { t, dur: 0.05, vol: vol * 0.5, type: "bandpass", f: 2500 * pitch, q: 2 });
  }
  function horn(dest = sfxBus, vol = 0.14, pitch = 1) {
    const t = now() + 0.02;
    [[87 * pitch, 0], [109.6 * pitch, 0], [87 * pitch, 1.05], [109.6 * pitch, 1.05]].forEach(([f, dt]) => {
      const o = ctx.createOscillator(), lp = ctx.createBiquadFilter(), g = ctx.createGain();
      o.type = "sawtooth"; o.frequency.value = f; lp.type = "lowpass"; lp.frequency.value = 520;
      g.gain.setValueAtTime(0.0001, t + dt); g.gain.exponentialRampToValueAtTime(vol, t + dt + 0.08);
      g.gain.setValueAtTime(vol, t + dt + 0.75); g.gain.exponentialRampToValueAtTime(0.0001, t + dt + 0.95);
      o.connect(lp).connect(g).connect(dest); o.start(t + dt); o.stop(t + dt + 1);
    });
  }

  // ------------------------------------------------------------ interface sounds
  let lastTick = 0;
  const SFX = {
    blip: () => tone(sfxBus, { f: 740, slide: 620, t: now(), dur: 0.035, vol: 0.05, duty: 0.25 }),
    select: () => { tone(sfxBus, { f: 988, t: now(), dur: 0.05, vol: 0.05, duty: 0.25 }); tone(sfxBus, { f: 1319, t: now() + 0.06, dur: 0.08, vol: 0.05, duty: 0.25 }); },
    toggle: () => { tone(sfxBus, { f: 523, t: now(), dur: 0.04, vol: 0.05, duty: 0.5 }); tone(sfxBus, { f: 784, t: now() + 0.05, dur: 0.05, vol: 0.05, duty: 0.5 }); },
    clank: () => clank(sfxBus, 0.12, 1),
    paper: () => hiss(sfxBus, { t: now(), dur: 0.12, vol: 0.04, type: "bandpass", f: 3200, q: 0.8, sweep: 1800 }),
    tick: (v = 0.5) => { if (now() - lastTick < 0.05) return; lastTick = now(); tone(sfxBus, { f: 220 + v * 660, t: now(), dur: 0.02, vol: 0.035, wave: "triangle", release: 0.02 }); },
    valve: () => {
      const t = now();
      const o = ctx.createOscillator(), fm = ctx.createOscillator(), fg = ctx.createGain(), bp = ctx.createBiquadFilter(), g = ctx.createGain();
      o.type = "sawtooth"; o.frequency.value = 74; fm.frequency.value = 17; fg.gain.value = 22; fm.connect(fg).connect(o.frequency);
      bp.type = "bandpass"; bp.frequency.value = 420; bp.Q.value = 3;
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.12, t + 0.05); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.75);
      o.connect(bp).connect(g).connect(sfxBus); o.start(t); fm.start(t); o.stop(t + 0.8); fm.stop(t + 0.8);
      hiss(sfxBus, { t: t + 0.25, dur: 1.1, vol: 0.09, type: "lowpass", f: 300, sweep: 2600 });
    },
    horn: () => horn(sfxBus, 0.13, 1),
    // oil pouring: a low rush and a few glugs
    pour: () => { hiss(sfxBus, { t: now(), dur: 1.0, vol: 0.05, type: "lowpass", f: 380, q: 1.1, sweep: 900 });
      [0.12, 0.34, 0.55, 0.8].forEach((d, i) => tone(sfxBus, { f: 150 - i * 12, slide: 85, t: now() + d, dur: 0.08, vol: 0.045, duty: 0.5 })); },
  };

  // ------------------------------------------------------------ switches
  function setSound(on) {
    if (on && !ensure()) return false;
    soundOn = on; store("hz-sound", on ? "on" : "off");
    if (!ctx) return false;
    if (on) {
      ctx.resume();
      startAmbience();
      ramp(master.gain, 0.8, 0.2); ramp(ambBus.gain, 0.9, 0.6);
      if (musicOn) setMusic(true, true);
    } else {
      ramp(master.gain, 0.0001, 0.15);
      clearInterval(timer); timer = null;
    }
    return soundOn;
  }
  function setMusic(on, quiet) {
    musicOn = on; if (!quiet) store("hz-music", on ? "on" : "off");
    if (!ctx) return;
    if (on && soundOn) { ramp(musicBus.gain, 0.85, 0.4); if (!timer) { nextT = 0; tick(); timer = setInterval(tick, 100); } }
    else { ramp(musicBus.gain, 0.0001, 0.3); setTimeout(() => { if (!musicOn || !soundOn) { clearInterval(timer); timer = null; } }, 1500); }
  }
  // the lost-flow slider makes the harbour tenser: the lead darkens and the plant hums louder
  function setTension(v) {
    tension = Math.max(0, Math.min(1, v));
    if (!ctx) return;
    ramp(lead.frequency, 4200 - tension * 2500, 0.3);
    if (hum) ramp(hum.gain, 0.03 + tension * 0.03, 0.5);
  }
  return {
    get on() { return soundOn; }, get music() { return musicOn; },
    wanted: () => store("hz-sound") !== "off", musicWanted: () => store("hz-music") !== "off",
    setSound, setMusic, setTension,
    play(name, arg) { if (soundOn && ctx && SFX[name]) SFX[name](arg); },
  };
})();
