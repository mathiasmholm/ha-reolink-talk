// Inline push-to-talk button for the "reolink_talk" live WebSocket relay.
// Designed to be dropped in as a picture-elements custom element on top of
// an existing (already-playing) camera card, so it does NOT open a second
// video connection -- it only opens the audio WebSocket while held down.
//
// Usage inside an advanced-camera-card (or any picture-elements-capable card):
//
//   elements:
//     - type: custom:reolink-talk-button
//       camera: front_door   # slugified Reolink camera name, e.g. "Front Door" -> front_door
//       style:
//         bottom: 15px
//         left: 10%   # avoids overlapping advanced-camera-card's PTZ controls
//
// The camera value must match the slug of one of your Reolink camera names
// (the same name used to build the "Reolink Talk <name>" media_player entity
// this integration creates). If unsure, connect once with any value -- the
// resulting error in Home Assistant's logs lists every valid slug.

class ReolinkTalkButton extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._camera = this._config.camera || "";
    if (!this._camera) {
      console.error("reolink-talk-button: missing required `camera:` config value");
    }
    this._recording = false;
    this._wsReady = false;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  getCardSize() {
    return 1;
  }

  _render() {
    this.innerHTML = `
      <button id="rtb-btn" style="
        width: 48px;
        height: 48px;
        border-radius: 50%;
        border: none;
        background: rgba(0,0,0,0.5);
        color: #fff;
        font-size: 22px;
        line-height: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        touch-action: none;
        -webkit-user-select: none;
        user-select: none;
        cursor: pointer;
        box-shadow: 0 2px 8px rgba(0,0,0,0.4);
        transition: background 0.1s ease, transform 0.1s ease;
      ">🎙️</button>
    `;
    this._btn = this.querySelector("#rtb-btn");
    this._cooldown = false;
    this._btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (this._cooldown) return;
      if (this._recording) {
        this._stop();
      } else {
        this._start();
      }
    });
  }

  _setVisualState(state) {
    if (!this._btn) return;
    const colors = {
      idle: "rgba(0,0,0,0.5)",
      connecting: "rgba(58,123,253,0.85)",
      live: "rgba(220,40,40,0.9)",
      error: "rgba(180,0,0,0.9)",
    };
    this._btn.style.background = colors[state] || colors.idle;
    this._btn.style.transform = state === "live" ? "scale(1.08)" : "scale(1)";
  }

  async _start() {
    if (this._recording) return;
    this._recording = true;
    this._setVisualState("connecting");

    try {
      this._mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
    } catch (err) {
      console.error("reolink-talk-button: mic error", err);
      this._setVisualState("error");
      this._recording = false;
      setTimeout(() => this._setVisualState("idle"), 1500);
      return;
    }

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this._ws = new WebSocket(
      proto + "//" + location.host + "/api/reolink_talk/live_ws?camera=" + encodeURIComponent(this._camera)
    );
    this._ws.binaryType = "arraybuffer";
    this._wsReady = false;

    this._ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.status === "ready") {
          this._wsReady = true;
          this._setVisualState("live");
        }
      } catch (e) {
        // ignore
      }
    };

    this._ws.onerror = () => {
      this._setVisualState("error");
    };

    this._ws.onclose = () => {
      this._teardownAudio();
      if (this._recording) {
        this._setVisualState("error");
        setTimeout(() => this._setVisualState("idle"), 1200);
      }
      this._recording = false;
    };

    this._ws.onopen = () => {
      this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      this._sourceNode = this._audioCtx.createMediaStreamSource(this._mediaStream);
      const bufferSize = 4096;
      this._processorNode = this._audioCtx.createScriptProcessor(bufferSize, 1, 1);

      this._processorNode.onaudioprocess = (e) => {
        if (!this._recording || !this._wsReady || this._ws.readyState !== WebSocket.OPEN) return;
        const input = e.inputBuffer.getChannelData(0);
        const pcm16 = this._downsampleBuffer(input, this._audioCtx.sampleRate, 16000);
        if (pcm16.length > 0) {
          this._ws.send(pcm16.buffer);
        }
      };

      this._sourceNode.connect(this._processorNode);
      const silentGain = this._audioCtx.createGain();
      silentGain.gain.value = 0;
      this._processorNode.connect(silentGain);
      silentGain.connect(this._audioCtx.destination);
    };
  }

  _stop() {
    if (!this._recording) return;
    this._recording = false;
    this._setVisualState("idle");
    this._teardownAudio();
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.close();
    }
    this._ws = null;
    this._cooldown = true;
    this._btn.style.opacity = "0.5";
    setTimeout(() => {
      this._cooldown = false;
      if (this._btn) this._btn.style.opacity = "1";
    }, 1200);
  }

  _teardownAudio() {
    if (this._processorNode) {
      try { this._processorNode.disconnect(); } catch (e) {}
      this._processorNode.onaudioprocess = null;
      this._processorNode = null;
    }
    if (this._sourceNode) {
      try { this._sourceNode.disconnect(); } catch (e) {}
      this._sourceNode = null;
    }
    if (this._audioCtx) {
      try { this._audioCtx.close(); } catch (e) {}
      this._audioCtx = null;
    }
    if (this._mediaStream) {
      this._mediaStream.getTracks().forEach((t) => t.stop());
      this._mediaStream = null;
    }
  }

  _downsampleBuffer(buffer, inputSampleRate, outputSampleRate) {
    if (outputSampleRate === inputSampleRate) {
      return this._floatTo16BitPCM(buffer);
    }
    const ratio = inputSampleRate / outputSampleRate;
    const newLength = Math.round(buffer.length / ratio);
    const result = new Float32Array(newLength);
    let offsetResult = 0;
    let offsetBuffer = 0;
    while (offsetResult < result.length) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
      let accum = 0, count = 0;
      for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
        accum += buffer[i];
        count++;
      }
      result[offsetResult] = count > 0 ? accum / count : 0;
      offsetResult++;
      offsetBuffer = nextOffsetBuffer;
    }
    return this._floatTo16BitPCM(result);
  }

  _floatTo16BitPCM(float32Array) {
    const out = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      let s = Math.max(-1, Math.min(1, float32Array[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  disconnectedCallback() {
    this._stop();
  }
}

if (!customElements.get("reolink-talk-button")) {
  customElements.define("reolink-talk-button", ReolinkTalkButton);
}
