const params = new URLSearchParams(window.location.search);
const departmentId = params.get("department_id");
const levelId = params.get("level_id");
const preselectedIds = (params.get("course_ids") || "")
  .split(",")
  .map((v) => v.trim())
  .filter(Boolean);
const deptName = params.get("dept_name") || "";
const levelName = params.get("level_name") || "";

const departmentIdInput = document.getElementById("department_id");
const levelIdInput = document.getElementById("level_id");
const courseSelect = document.getElementById("course-select");
const courseLabel = document.getElementById("course-label");
const video = document.getElementById("webcam");
const overlay = document.getElementById("overlay");
const countdownEl = document.getElementById("countdown");
const progressWrap = document.getElementById("progress-wrap");
const progressFill = document.getElementById("progress-fill");
const captureBtn = document.getElementById("capture-btn");
const submitBtn = document.getElementById("submit-btn");
const form = document.getElementById("register-form");
const statusEl = document.getElementById("status");

const CAPTURE_SECONDS = 10;
const FRAME_INTERVAL_MS = 400;

let stream = null;
let capturedFrames = [];
let captureCanvas = null;
let captureCtx = null;

function showStatus(message, type = "info") {
  statusEl.textContent = message;
  statusEl.className = `status show ${type}`;
}

function hideStatus() {
  statusEl.className = "status";
}

function formatApiError(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return "Registration failed";
}

function getSelectedCourseIds() {
  return [...courseSelect.selectedOptions].map((opt) => opt.value);
}

async function loadCourses() {
  if (!departmentId || !levelId) {
    showStatus("Missing department or level. Go back and select them first.", "error");
    captureBtn.disabled = true;
    submitBtn.disabled = true;
    return;
  }

  departmentIdInput.value = departmentId;
  levelIdInput.value = levelId;
  courseLabel.textContent = `${deptName || "Department"} · ${levelName || "Level"}`;

  try {
    const res = await fetch(`/courses?department_id=${departmentId}&level_id=${levelId}`);
    if (!res.ok) throw new Error("Failed to load courses");
    const courses = await res.json();

    courseSelect.innerHTML = "";
    courses.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.id;  // FIXED: Use 'id' instead of 'course_id'
      opt.textContent = `${c.code} — ${c.name}`;
      if (preselectedIds.includes(String(c.id))) {
        opt.selected = true;
      }
      courseSelect.appendChild(opt);
    });

    if (courses.length === 0) {
      showStatus("No courses available for this department and level.", "error");
      captureBtn.disabled = true;
      submitBtn.disabled = true;
    } else if (getSelectedCourseIds().length === 0 && preselectedIds.length === 0) {
      showStatus("Select at least one course from the list.", "info");
    }
  } catch (err) {
    showStatus(err.message, "error");
    captureBtn.disabled = true;
    submitBtn.disabled = true;
  }
}

async function initCamera() {
  captureCanvas = document.createElement("canvas");
  captureCtx = captureCanvas.getContext("2d");

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    video.srcObject = stream;
  } catch (err) {
    showStatus(`Camera access denied or unavailable: ${err.message}`, "error");
    captureBtn.disabled = true;
  }
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
    captureCanvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.92);
  });
}

async function runCapture() {
  if (!stream || video.readyState < 2) {
    showStatus("Webcam is not ready yet. Wait a moment and try again.", "error");
    return;
  }

  capturedFrames = [];
  captureBtn.disabled = true;
  submitBtn.disabled = true;
  overlay.classList.remove("hidden");
  progressWrap.style.display = "block";
  hideStatus();

  const totalMs = CAPTURE_SECONDS * 1000;
  const start = Date.now();
  let lastFrameAt = 0;

  const interval = setInterval(async () => {
    const elapsed = Date.now() - start;
    const remaining = Math.ceil((totalMs - elapsed) / 1000);

    countdownEl.textContent = String(Math.max(remaining, 1));
    progressFill.style.width = `${Math.min((elapsed / totalMs) * 100, 100)}%`;

    if (elapsed - lastFrameAt >= FRAME_INTERVAL_MS) {
      lastFrameAt = elapsed;
      const blob = await grabFrameBlob();
      if (blob) capturedFrames.push(blob);
    }

    if (elapsed >= totalMs) {
      clearInterval(interval);
      overlay.classList.add("hidden");
      progressFill.style.width = "100%";
      captureBtn.disabled = false;

      if (capturedFrames.length === 0) {
        showStatus("No frames captured. Please try again.", "error");
        return;
      }

      submitBtn.disabled = false;
      showStatus(`Captured ${capturedFrames.length} frame(s). You can submit now.`, "success");
    }
  }, 100);
}

captureBtn.addEventListener("click", runCapture);

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const fullName = document.getElementById("full_name").value.trim();
  const matricNo = document.getElementById("matric_no").value.trim();
  const selectedCourseIds = getSelectedCourseIds();

  if (!fullName || !matricNo) {
    showStatus("Please enter your name and matric number.", "error");
    return;
  }

  if (selectedCourseIds.length === 0) {
    showStatus("Select at least one course to register for.", "error");
    return;
  }

  if (capturedFrames.length === 0) {
    showStatus("Complete face capture before submitting.", "error");
    return;
  }

  submitBtn.disabled = true;
  captureBtn.disabled = true;
  showStatus("Uploading and processing your registration…", "info");

  const body = new FormData();
  body.append("full_name", fullName);
  body.append("matric_no", matricNo);
  body.append("department_id", departmentId);
  body.append("level_id", levelId);
  selectedCourseIds.forEach((id) => body.append("course_ids", id));
  capturedFrames.forEach((blob, index) => {
    body.append("frames", blob, `frame_${index}.jpg`);
  });

  try {
    const res = await fetch("/enrollment/register", { method: "POST", body });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(formatApiError(data.detail));
    }

    showStatus(data.message, "success");
    submitBtn.textContent = "Registered ✓";
  } catch (err) {
    showStatus(err.message, "error");
    submitBtn.disabled = false;
    captureBtn.disabled = false;
  }
});

window.addEventListener("beforeunload", () => {
  if (stream) stream.getTracks().forEach((t) => t.stop());
});

loadCourses();
initCamera();
