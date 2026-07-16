const params = new URLSearchParams(window.location.search);
const courseId = params.get("course_id");
const courseCode = params.get("code") || "";
const courseName = params.get("name") || "";

const sessionLabel = document.getElementById("session-label");
const video = document.getElementById("webcam");
const scanStatus = document.getElementById("scan-status");
const scanIndicator = document.getElementById("scan-indicator");
const statEnrolled = document.getElementById("stat-enrolled");
const statFaces = document.getElementById("stat-faces");
const statMarked = document.getElementById("stat-marked");
const recentList = document.getElementById("recent-list");

const successModal = document.getElementById("success-modal");
const modalMessage = document.getElementById("modal-message");
const modalDetail = document.getElementById("modal-detail");
const modalClose = document.getElementById("modal-close");

const infoModal = document.getElementById("info-modal");
const infoTitle = document.getElementById("info-title");
const infoMessage = document.getElementById("info-message");
const infoClose = document.getElementById("info-close");

const SCAN_INTERVAL_MS = 2000;
const SUCCESS_COOLDOWN_MS = 5000;
const INFO_COOLDOWN_MS = 3000;

let stream = null;
let captureCanvas = null;
let captureCtx = null;
let scanning = false;
let scanTimer = null;
let lastScanAt = 0;
let pauseUntil = 0;
const recentMarks = [];

function showScanStatus(message, type = "info") {
  scanStatus.textContent = message;
  scanStatus.className = `status show ${type}`;
}

function showSuccessModal(message, detail) {
  modalMessage.textContent = message;
  modalDetail.textContent = detail || "";
  successModal.classList.remove("hidden");
  pauseUntil = Date.now() + SUCCESS_COOLDOWN_MS;
}

function showInfoModal(title, message) {
  infoTitle.textContent = title;
  infoMessage.textContent = message;
  infoModal.classList.remove("hidden");
  pauseUntil = Date.now() + INFO_COOLDOWN_MS;
}

function addRecentMark(name, matric) {
  recentMarks.unshift({ name, matric, time: new Date() });
  if (recentMarks.length > 8) recentMarks.pop();

  recentList.innerHTML = recentMarks
    .map(
      (item) => `
    <li>
      <strong>${escapeHtml(item.name)}</strong>
      <span>${escapeHtml(item.matric)} · ${item.time.toLocaleTimeString()}</span>
    </li>`
    )
    .join("");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

async function loadSession() {
  if (!courseId) {
    showScanStatus("Missing course. Go back and select a course.", "error");
    return;
  }

  sessionLabel.textContent = `${courseCode} — ${courseName}`;

  const res = await fetch(`/attendance/session/${courseId}`);
  if (!res.ok) throw new Error("Failed to load session");
  const session = await res.json();

  statEnrolled.textContent = session.enrolled_students;
  statFaces.textContent = session.students_with_faces;
  statMarked.textContent = session.marked_today;

  if (!session.dlib_ready) {
    showScanStatus("dlib is not installed on the server. Cannot scan faces.", "error");
    return;
  }

  if (session.students_with_faces === 0) {
    showScanStatus("No students with face data for this course.", "error");
    return;
  }

  showScanStatus("Camera active. Scanning for registered faces…", "info");
}

async function initCamera() {
  captureCanvas = document.createElement("canvas");
  captureCtx = captureCanvas.getContext("2d");

  stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
    audio: false,
  });
  video.srcObject = stream;
  await video.play();
}

function grabFrameBlob() {
  return new Promise((resolve) => {
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (!w || !h) {
      resolve(null);
      return;
    }
    captureCanvas.width = w;
    captureCanvas.height = h;
    captureCtx.drawImage(video, 0, 0, w, h);
    captureCanvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.9);
  });
}

async function scanOnce() {
  if (!scanning || Date.now() < pauseUntil) return;
  if (Date.now() - lastScanAt < SCAN_INTERVAL_MS) return;

  const blob = await grabFrameBlob();
  if (!blob) return;

  lastScanAt = Date.now();
  scanIndicator.classList.add("active");

  const body = new FormData();
  body.append("course_id", courseId);
  body.append("frame", blob, "scan.jpg");

  try {
    const res = await fetch("/attendance/scan", { method: "POST", body });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "Scan failed");
    }

    if (data.marked) {
      statMarked.textContent = String(Number(statMarked.textContent || 0) + 1);
      addRecentMark(data.full_name, data.matric_no);
      showSuccessModal(
        "Your attendance has been marked successfully!",
        `${data.full_name} (${data.matric_no}) · ${courseCode} · ${data.session_date}`
      );
      showScanStatus(data.message, "success");
    } else if (data.already_marked) {
      showInfoModal("Already marked", data.message);
    } else if (!data.matched) {
      showScanStatus(data.message, "info");
    }
  } catch (err) {
    showScanStatus(err.message, "error");
  } finally {
    setTimeout(() => scanIndicator.classList.remove("active"), 400);
  }
}

function startScanning() {
  scanning = true;
  scanTimer = setInterval(scanOnce, 800);
}

modalClose.addEventListener("click", () => {
  successModal.classList.add("hidden");
});

infoClose.addEventListener("click", () => {
  infoModal.classList.add("hidden");
});

window.addEventListener("beforeunload", () => {
  scanning = false;
  if (scanTimer) clearInterval(scanTimer);
  if (stream) stream.getTracks().forEach((t) => t.stop());
});

async function init() {
  try {
    await loadSession();
    await initCamera();
    startScanning();
  } catch (err) {
    showScanStatus(err.message, "error");
  }
}

init();
