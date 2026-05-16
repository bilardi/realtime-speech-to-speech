(() => {
  const params = new URL(window.location.href).searchParams;
  const room = params.get("room") || "1";
  const lang = params.get("lang") || "en-US";
  const token = params.get("token");
  let wsUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/listen?room=${encodeURIComponent(room)}&lang=${encodeURIComponent(lang)}`;
  if (token) {
    wsUrl += `&token=${encodeURIComponent(token)}`;
  }

  const statusEl = document.getElementById("status");
  const transcriptEl = document.getElementById("transcript");
  const enableServiceBtn = document.getElementById("enable-service");
  const muteToggleBtn = document.getElementById("mute-toggle");
  const themeDarkBtn = document.getElementById("theme-dark");
  const themeLightBtn = document.getElementById("theme-light");
  const themeWarmBtn = document.getElementById("theme-warm");
  const zoomInBtn = document.getElementById("zoom-in");
  const zoomOutBtn = document.getElementById("zoom-out");
  const resetBtn = document.getElementById("reset");
  const saveBtn = document.getElementById("save");

  // List of all theme classes; helpers below add/remove via this list so
  // adding a fourth theme means just appending to this array and adding the
  // corresponding button.
  const THEME_CLASSES = ["theme-solarized-dark", "theme-solarized-light", "theme-warm"];

  // Key used to persist the user's UI preferences (theme, zoom, muted) across
  // page reloads. "save" writes here, "reset" clears it, and page load
  // restores from it before opening the WebSocket.
  const PREFS_KEY = "s2s-prefs";

  let audioCtx = null;
  let nextStartTime = 0;
  let muted = true;
  const SAMPLE_RATE = 16000;
  // Transcript font zoom: 1.0 = CSS defaults (1.5rem normal, 2rem latest line).
  // Bounds chosen empirically; outside this range the layout breaks down (text
  // either disappears or overflows past the controls).
  const ZOOM_STEP = 0.1;
  const ZOOM_MIN = 0.5;
  const ZOOM_MAX = 3.0;
  let zoom = 1.0;

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
    // Drop incoming chunks while suspended or while the user has muted output,
    // otherwise they would queue up and replay all at once when the user toggles
    // unmute or the context resumes.
    if (ctx.state === "suspended" || muted) {
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

  function enableService() {
    const ctx = ensureAudioCtx();
    enableServiceBtn.style.display = "none";
    if (ctx.state === "suspended") {
      ctx.resume().then(() => {
        nextStartTime = ctx.currentTime;
      });
    }
  }
  enableServiceBtn.addEventListener("click", enableService);

  function toggleMute() {
    muted = !muted;
    muteToggleBtn.textContent = muted ? "unmute" : "mute";
    // When transitioning from muted to unmuted, reset the audio scheduling
    // anchor so the next chunk does not try to play at a stale past time
    // accumulated while output was suppressed.
    if (!muted && audioCtx !== null) {
      nextStartTime = audioCtx.currentTime;
    }
  }
  muteToggleBtn.addEventListener("click", toggleMute);

  // Theme switching toggles body classes; the CSS variables defined per class
  // cascade to bg, fg, button colors and enable-service inverted accent.
  function setTheme(themeClass) {
    document.body.classList.remove(...THEME_CLASSES);
    if (themeClass !== null) {
      document.body.classList.add(themeClass);
    }
  }
  themeDarkBtn.addEventListener("click", () => setTheme("theme-solarized-dark"));
  themeLightBtn.addEventListener("click", () => setTheme("theme-solarized-light"));
  themeWarmBtn.addEventListener("click", () => setTheme("theme-warm"));

  // Zoom updates the --zoom CSS variable that the transcript font-size rules
  // multiply by. Latest-line emphasis (2rem * --zoom) scales proportionally.
  function applyZoom() {
    document.body.style.setProperty("--zoom", zoom.toString());
  }
  zoomInBtn.addEventListener("click", () => {
    zoom = Math.min(zoom + ZOOM_STEP, ZOOM_MAX);
    applyZoom();
  });
  zoomOutBtn.addEventListener("click", () => {
    zoom = Math.max(zoom - ZOOM_STEP, ZOOM_MIN);
    applyZoom();
  });

  // Reset all UI preferences back to defaults without reloading: theme = none
  // (initial black/white), zoom = 1.0, mute = true. Also clears the saved
  // preferences so the defaults survive a reload. Does not touch the
  // transcript history or the WebSocket connection.
  resetBtn.addEventListener("click", () => {
    setTheme(null);
    zoom = 1.0;
    applyZoom();
    if (!muted) {
      muted = true;
      muteToggleBtn.textContent = "unmute";
    }
    try {
      localStorage.removeItem(PREFS_KEY);
    } catch {
      // localStorage unavailable (private mode quotas, etc.): ignore
    }
  });

  // Save current UI preferences to localStorage; they will be restored at the
  // top of the next page load (see the block just before connect() below).
  // Map between body class name and the short label used in localStorage, so
  // saved prefs stay compact and stable even if a class is renamed.
  const THEME_TO_LABEL = {
    "theme-solarized-dark": "dark",
    "theme-solarized-light": "light",
    "theme-warm": "warm",
  };
  const LABEL_TO_THEME = Object.fromEntries(
    Object.entries(THEME_TO_LABEL).map(([cls, label]) => [label, cls]),
  );

  saveBtn.addEventListener("click", () => {
    const activeClass = THEME_CLASSES.find((cls) => document.body.classList.contains(cls));
    const theme = activeClass ? THEME_TO_LABEL[activeClass] : null;
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({ theme, zoom, muted }));
    } catch {
      // localStorage unavailable: ignore (the click is a no-op in that case)
    }
  });

  function setStatus(s) {
    statusEl.textContent = `room ${room} · ${lang} · ${s}`;
  }

  // Threshold (px) to treat the user as "at the bottom" of the transcript scroll.
  // Larger than 0 to tolerate sub-pixel scroll positions and small fast-scroll
  // overshoots.
  const SCROLL_STICKY_THRESHOLD = 50;

  function isAtBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_STICKY_THRESHOLD;
  }

  function appendText(text, isError) {
    // Drop the initial "waiting for speaker" placeholder on the first real line,
    // so the transcript log starts clean with the actual phrases.
    const placeholder = transcriptEl.querySelector(".transcript-line.placeholder");
    if (placeholder) {
      placeholder.remove();
    }
    const wasAtBottom = isAtBottom(transcriptEl);
    const line = document.createElement("div");
    line.className = isError ? "transcript-line error" : "transcript-line";
    line.textContent = text;
    transcriptEl.appendChild(line);
    // Auto-follow only when the user was already at the bottom; if they scrolled
    // up to read an older phrase, do not yank the view back down.
    if (wasAtBottom) {
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
    }
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
          appendText(msg.text || "", Boolean(msg.error));
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

  // Restore saved UI preferences (if any) before opening the WebSocket, so the
  // page renders with the user's chosen theme and zoom immediately.
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "null");
    if (saved) {
      if (saved.theme && LABEL_TO_THEME[saved.theme]) {
        setTheme(LABEL_TO_THEME[saved.theme]);
      }
      if (typeof saved.zoom === "number") {
        zoom = saved.zoom;
        applyZoom();
      }
      if (typeof saved.muted === "boolean") {
        muted = saved.muted;
        muteToggleBtn.textContent = muted ? "unmute" : "mute";
      }
    }
  } catch {
    // localStorage unavailable or corrupted JSON: stick with defaults
  }

  if (!window.AudioContext && !window.webkitAudioContext) {
    appendText("this browser does not support audio playback", true);
  } else {
    connect();
  }
})();
