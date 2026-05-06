(() => {
  const params = new URL(window.location.href).searchParams;
  const room = params.get("room") || "1";
  const lang = params.get("lang") || "en-US";
  const wsUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/listen?room=${encodeURIComponent(room)}&lang=${encodeURIComponent(lang)}`;

  const statusEl = document.getElementById("status");
  const transcriptEl = document.getElementById("transcript");
  const enableBtn = document.getElementById("enable-audio");

  let audioCtx = null;
  let nextStartTime = 0;
  const SAMPLE_RATE = 16000;

  function ensureAudioCtx() {
    if (audioCtx === null) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
      nextStartTime = audioCtx.currentTime;
    }
    return audioCtx;
  }

  function pcmInt16ToFloat32(buf) {
    const view = new DataView(buf);
    const len = buf.byteLength / 2;
    const out = new Float32Array(len);
    for (let i = 0; i < len; i++) {
      const s = view.getInt16(i * 2, true);
      out[i] = s / 32768;
    }
    return out;
  }

  function enqueueAudioChunk(buf) {
    const ctx = ensureAudioCtx();
    // Browser autoplay policy: AudioContext starts suspended until a user gesture.
    // Drop incoming chunks while suspended, otherwise they queue up and replay
    // all at once when the context resumes.
    if (ctx.state === "suspended") {
      return;
    }
    const samples = pcmInt16ToFloat32(buf);
    const audioBuffer = ctx.createBuffer(1, samples.length, SAMPLE_RATE);
    audioBuffer.getChannelData(0).set(samples);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    const when = Math.max(ctx.currentTime, nextStartTime);
    source.start(when);
    nextStartTime = when + audioBuffer.duration;
  }

  function unlockAudio() {
    const ctx = ensureAudioCtx();
    enableBtn.style.display = "none";
    if (ctx.state === "suspended") {
      ctx.resume().then(() => {
        nextStartTime = ctx.currentTime;
      });
    }
  }
  enableBtn.addEventListener("click", unlockAudio);

  function setStatus(s) {
    statusEl.textContent = `room ${room} · ${lang} · ${s}`;
  }

  function setText(text, isError) {
    transcriptEl.textContent = text;
    transcriptEl.className = isError ? "error" : "";
  }

  let backoff = 1000;
  function connect() {
    setStatus("connecting...");
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      setStatus("connected");
      backoff = 1000;
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          const msg = JSON.parse(ev.data);
          setText(msg.text || "", Boolean(msg.error));
        } catch (err) {
          console.warn("bad json", err);
        }
      } else {
        enqueueAudioChunk(ev.data);
      }
    };

    ws.onclose = () => {
      setStatus("disconnected, retrying...");
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 30000);
    };

    ws.onerror = (err) => {
      console.error("ws error", err);
    };
  }

  if (!window.AudioContext && !window.webkitAudioContext) {
    setText("this browser does not support audio playback", true);
  } else {
    connect();
  }
})();
