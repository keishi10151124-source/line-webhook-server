// Live camera registration with a liveness check (MediaPipe Face Landmarker, Apache 2.0).
// The server re-checks the captured frames on its own; this only guides the person.
import { FaceLandmarker, FilesetResolver } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs";

const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const WASM_URL = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";
const CSRF = document.querySelector('meta[name="csrf-token"]').content;

const video = document.getElementById("cam");
const promptEl = document.getElementById("prompt");
const stepsEl = document.getElementById("steps");
const startBtn = document.getElementById("start");
const retryBtn = document.getElementById("retry");
const resultEl = document.getElementById("result");

const LABEL = { center: "正面を見る", turn_a: "顔を左に向ける", turn_b: "顔を右に向ける", blink: "まばたきする" };
const HOLD_FRAMES = 6;      // a pose must hold for this many frames
const CENTER_MAX = 0.08;
const TURN_MIN = 0.22;
const STEP_TIMEOUT_MS = 15000;

let landmarker = null;
let stream = null;
let running = false;

function say(text) { promptEl.textContent = text; }

function drawSteps(steps, current) {
  stepsEl.innerHTML = "";
  steps.forEach((s, i) => {
    const li = document.createElement("li");
    li.textContent = LABEL[s];
    if (i < current) li.className = "done";
    else if (i === current) { li.className = "now"; li.setAttribute("aria-current", "step"); }
    stepsEl.appendChild(li);
  });
}

// yaw from nose tip relative to the two cheek edges, about -0.5..0.5
function yawOf(lm) {
  const nose = lm[1], left = lm[234], right = lm[454];
  const mid = (left.x + right.x) / 2;
  const width = Math.abs(right.x - left.x) || 1;
  return (nose.x - mid) / width;
}

function blinkScore(result) {
  const cats = result.faceBlendshapes && result.faceBlendshapes[0] ? result.faceBlendshapes[0].categories : [];
  const get = (n) => (cats.find((c) => c.categoryName === n) || { score: 0 }).score;
  return Math.min(get("eyeBlinkLeft"), get("eyeBlinkRight"));
}

function capture() {
  const c = document.createElement("canvas");
  c.width = video.videoWidth; c.height = video.videoHeight;
  c.getContext("2d").drawImage(video, 0, 0); // un-mirrored, as the camera sees it
  return c.toDataURL("image/jpeg", 0.9);
}

async function setup() {
  if (!landmarker) {
    say("顔の確認の準備をしています…");
    const files = await FilesetResolver.forVisionTasks(WASM_URL);
    landmarker = await FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
      runningMode: "VIDEO", numFaces: 2, outputFaceBlendshapes: true,
    });
  }
  if (!stream) {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: 720, height: 960 }, audio: false });
    video.srcObject = stream;
    await new Promise((r) => (video.onloadedmetadata = r));
  }
}

function waitFor(step, state) {
  return new Promise((resolve, reject) => {
    let hold = 0, closed = false, sawOpenAfterClose = false;
    const started = performance.now();
    const tick = () => {
      if (!running) return reject(new Error("中止しました"));
      if (performance.now() - started > STEP_TIMEOUT_MS) return reject(new Error("時間内に確認できませんでした"));
      const res = landmarker.detectForVideo(video, performance.now());
      const faces = res.faceLandmarks || [];
      if (faces.length === 0) { say("顔が見えません。カメラの正面に来てください"); hold = 0; return requestAnimationFrame(tick); }
      if (faces.length > 1) { say("1人だけで撮影してください"); hold = 0; return requestAnimationFrame(tick); }
      const yaw = yawOf(faces[0]);
      say(LABEL[step]);
      let ok = false;
      if (step === "center") ok = Math.abs(yaw) < CENTER_MAX;
      else if (step === "turn_a" || step === "turn_b") {
        const other = step === "turn_a" ? state.turn_b : state.turn_a;
        ok = Math.abs(yaw) > TURN_MIN && (other === undefined || Math.sign(yaw) !== Math.sign(other));
      } else if (step === "blink") {
        const b = blinkScore(res);
        if (b > 0.55) closed = true;
        if (closed && b < 0.2) sawOpenAfterClose = true;
        ok = sawOpenAfterClose;
      }
      hold = ok ? hold + 1 : 0;
      if ((step === "blink" && ok) || hold >= HOLD_FRAMES) {
        if (step === "turn_a" || step === "turn_b") state[step] = yaw;
        return resolve(step === "blink" ? null : capture());
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

async function run() {
  resultEl.textContent = "";
  startBtn.disabled = true; retryBtn.hidden = true;
  try {
    await setup();
    const r = await fetch("/api/face/challenge", { method: "POST", headers: { "X-CSRF-Token": CSRF } });
    const ch = await r.json();
    if (!r.ok) throw new Error(ch.error || "開始できませんでした");
    running = true;
    const frames = {}, state = {};
    for (let i = 0; i < ch.steps.length; i++) {
      drawSteps(ch.steps, i);
      const img = await waitFor(ch.steps[i], state);
      if (img) frames[ch.steps[i]] = img;
    }
    drawSteps(ch.steps, ch.steps.length);
    running = false;
    say("確認しています…");
    const sent = await fetch("/api/face", {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF },
      body: JSON.stringify({ challenge_id: ch.challenge_id, frames, client_ok: true }),
    });
    const out = await sent.json();
    if (!sent.ok) throw new Error(out.error || "登録できませんでした");
    say("登録できました");
    if (stream) stream.getTracks().forEach((t) => t.stop());
    window.location.reload();
  } catch (e) {
    running = false;
    say("もう一度ためしてください");
    resultEl.textContent = e.message || String(e);
    resultEl.className = "flash error";
    retryBtn.hidden = false;
  } finally {
    startBtn.disabled = false;
  }
}

startBtn.addEventListener("click", run);
retryBtn.addEventListener("click", run);
