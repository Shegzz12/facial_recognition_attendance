const deptSelect = document.getElementById("department-select");
const levelSelect = document.getElementById("level-select");
const courseSelect = document.getElementById("course-select");
const startBtn = document.getElementById("start-btn");
const setupStatus = document.getElementById("setup-status");
const sessionPreview = document.getElementById("session-preview");
const previewEnrolled = document.getElementById("preview-enrolled");
const previewFaces = document.getElementById("preview-faces");
const previewMarked = document.getElementById("preview-marked");
const dlibStatus = document.getElementById("dlib-status");

const piCamStartBtn = document.getElementById("pi-cam-start-btn");
const piCamStopBtn = document.getElementById("pi-cam-stop-btn");
const piCamStatus = document.getElementById("pi-cam-status");
const piCamPreviewWrap = document.getElementById("pi-cam-preview-wrap");
const piCamPreviewImg = document.getElementById("pi-cam-preview");

const rfidStartBtn = document.getElementById("rfid-start-btn");
const rfidStopBtn = document.getElementById("rfid-stop-btn");
const rfidStatus = document.getElementById("rfid-status");

console.log("RFID start button found:", rfidStartBtn);
console.log("RFID stop button found:", rfidStopBtn);
console.log("RFID status element found:", rfidStatus);

let piCamPollTimer = null;
let rfidPollTimer = null;

function showStatus(message, type = "info") {
  setupStatus.textContent = message;
  setupStatus.className = `status show ${type}`;
}

function showPiCamStatus(message, type = "info") {
  piCamStatus.classList.remove("hidden");
  piCamStatus.textContent = message;
  piCamStatus.className = `status show ${type}`;
}

function showRfidStatus(message, type = "info") {
  rfidStatus.classList.remove("hidden");
  rfidStatus.textContent = message;
  rfidStatus.className = `status show ${type}`;
}

function showPiCamPreview() {
  piCamPreviewWrap.classList.remove("hidden");
  // cache-bust so the browser opens a fresh MJPEG connection each time
  piCamPreviewImg.src = `/attendance/pi-scan/stream?t=${Date.now()}`;
}

function hidePiCamPreview() {
  piCamPreviewWrap.classList.add("hidden");
  piCamPreviewImg.src = "";
}

piCamPreviewImg.addEventListener("error", () => {
  // Stream ended (scanning stopped, network hiccup, etc.) — hide rather than
  // show a broken-image icon.
  hidePiCamPreview();
});

async function loadDepartments() {
  const res = await fetch("/departments");
  if (!res.ok) throw new Error("Failed to load departments");
  const departments = await res.json();

  departments.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.id;  // FIXED: Use 'id' instead of 'department_id'
    opt.textContent = d.code ? `${d.name} (${d.code})` : d.name;
    deptSelect.appendChild(opt);
  });
}

async function loadLevels(departmentId) {
  levelSelect.innerHTML = '<option value="">— Select level —</option>';
  courseSelect.innerHTML = '<option value="">— Select course —</option>';
  levelSelect.disabled = true;
  courseSelect.disabled = true;
  sessionPreview.classList.add("hidden");
  startBtn.disabled = true;
  piCamStartBtn.disabled = true;
  rfidStartBtn.disabled = true;

  if (!departmentId) return;

  const res = await fetch(`/levels?department_id=${departmentId}`);
  if (!res.ok) throw new Error("Failed to load levels");
  const levels = await res.json();

  levels.forEach((l) => {
    const opt = document.createElement("option");
    opt.value = l.id;  // FIXED: Use 'id' instead of 'level_id'
    opt.textContent = l.name;
    levelSelect.appendChild(opt);
  });
  levelSelect.disabled = levels.length === 0;
}

async function loadCourses(departmentId, levelId) {
  courseSelect.innerHTML = '<option value="">— Select course —</option>';
  courseSelect.disabled = true;
  sessionPreview.classList.add("hidden");
  startBtn.disabled = true;
  piCamStartBtn.disabled = true;
  rfidStartBtn.disabled = true;

  if (!departmentId || !levelId) return;

  const res = await fetch(`/courses?department_id=${departmentId}&level_id=${levelId}`);
  if (!res.ok) throw new Error("Failed to load courses");
  const courses = await res.json();

  courses.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.id;  // FIXED: Use 'id' instead of 'course_id'
    opt.textContent = `${c.code} — ${c.name}`;
    opt.dataset.code = c.code;
    opt.dataset.name = c.name;
    courseSelect.appendChild(opt);
  });
  courseSelect.disabled = courses.length === 0;
}

async function loadSessionPreview(courseId) {
  if (!courseId) {
    sessionPreview.classList.add("hidden");
    startBtn.disabled = true;
    piCamStartBtn.disabled = true;
    rfidStartBtn.disabled = true;
    return;
  }

  const res = await fetch(`/attendance/session/${courseId}`);
  if (!res.ok) throw new Error("Failed to load session info");
  const session = await res.json();

  previewEnrolled.textContent = session.enrolled_students;
  previewFaces.textContent = session.students_with_faces;
  previewMarked.textContent = session.marked_today;
  sessionPreview.classList.remove("hidden");

  if (!session.dlib_ready) {
    dlibStatus.textContent =
      "Warning: dlib is not installed on the server. Run pip install face-recognition before scanning.";
    dlibStatus.style.color = "var(--warning)";
    startBtn.disabled = true;
    piCamStartBtn.disabled = true;
    showStatus("Install face-recognition on the server to enable face scanning.", "error");
  } else {
    dlibStatus.textContent = `Session date: ${session.session_date} · Recognition engine: dlib`;
    dlibStatus.style.color = "var(--muted)";

    if (session.students_with_faces === 0) {
      showStatus("No enrolled students have face data yet. Students must register first.", "error");
      startBtn.disabled = true;
      piCamStartBtn.disabled = true;
    } else {
      startBtn.disabled = false;
      piCamStartBtn.disabled = false;
      showStatus("Ready to start the attendance scanning session.", "success");
    }
  }

  // RFID button is enabled when a course is selected (doesn't require face data)
  console.log("Enrolled students:", session.enrolled_students);
  rfidStartBtn.disabled = false;
  console.log("RFID button disabled state:", rfidStartBtn.disabled);
}

deptSelect.addEventListener("change", () => loadLevels(deptSelect.value));
levelSelect.addEventListener("change", () => loadCourses(deptSelect.value, levelSelect.value));
courseSelect.addEventListener("change", () => loadSessionPreview(courseSelect.value));

startBtn.addEventListener("click", () => {
  const courseId = courseSelect.value;
  if (!courseId) return;

  const opt = courseSelect.selectedOptions[0];
  const params = new URLSearchParams({
    course_id: courseId,
    code: opt.dataset.code || "",
    name: opt.dataset.name || "",
  });
  window.location.href = `/static/attendance.html?${params.toString()}`;
});

// ---- Pi Camera scanning controls ----

async function refreshPiCamStatus() {
  try {
    const res = await fetch("/attendance/pi-scan/status");
    if (!res.ok) return;
    const data = await res.json();

    if (data.running) {
      piCamStartBtn.classList.add("hidden");
      piCamStopBtn.classList.remove("hidden");
      const msg = data.last_message || `Scanning with Pi camera for ${data.course_code}…`;
      showPiCamStatus(`${msg} (Marked this session: ${data.marks_this_session})`, "info");
      if (piCamPreviewWrap.classList.contains("hidden")) {
        showPiCamPreview();
      }
      if (!piCamPollTimer) {
        piCamPollTimer = setInterval(refreshPiCamStatus, 1500);
      }
    } else {
      piCamStartBtn.classList.remove("hidden");
      piCamStopBtn.classList.add("hidden");
      hidePiCamPreview();
      if (data.error) {
        showPiCamStatus(`Pi camera scanning stopped: ${data.error}`, "error");
      }
      if (piCamPollTimer) {
        clearInterval(piCamPollTimer);
        piCamPollTimer = null;
      }
    }
  } catch (err) {
    // ignore transient poll errors
  }
}

piCamStartBtn.addEventListener("click", async () => {
  const courseId = courseSelect.value;
  if (!courseId) return;

  piCamStartBtn.disabled = true;
  try {
    const res = await fetch("/attendance/pi-scan/start", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ course_id: courseId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to start Pi camera scanning");

    showPiCamStatus(`Pi camera scanning started for ${data.course_code}.`, "success");
    piCamStartBtn.classList.add("hidden");
    piCamStopBtn.classList.remove("hidden");
    showPiCamPreview();
    if (!piCamPollTimer) {
      piCamPollTimer = setInterval(refreshPiCamStatus, 1500);
    }
  } catch (err) {
    showPiCamStatus(err.message, "error");
    piCamStartBtn.disabled = false;
  }
});

piCamStopBtn.addEventListener("click", async () => {
  piCamStopBtn.disabled = true;
  try {
    await fetch("/attendance/pi-scan/stop", { method: "POST" });
    showPiCamStatus("Pi camera scanning stopped.", "info");
    piCamStopBtn.classList.add("hidden");
    piCamStartBtn.classList.remove("hidden");
    hidePiCamPreview();
    piCamStartBtn.disabled = !courseSelect.value;
    if (piCamPollTimer) {
      clearInterval(piCamPollTimer);
      piCamPollTimer = null;
    }
  } catch (err) {
    showPiCamStatus(err.message, "error");
  } finally {
    piCamStopBtn.disabled = false;
  }
});

// ---- RFID scanning controls ----

async function refreshRfidStatus() {
  try {
    const res = await fetch("/attendance/rfid-scan/status");
    if (!res.ok) return;
    const data = await res.json();

    if (data.running) {
      rfidStartBtn.classList.add("hidden");
      rfidStopBtn.classList.remove("hidden");
      const msg = data.last_message || `Scanning with RFID for ${data.course_code}…`;
      showRfidStatus(`${msg} (Marked this session: ${data.marks_this_session})`, "info");
      if (!rfidPollTimer) {
        rfidPollTimer = setInterval(refreshRfidStatus, 1500);
      }
    } else {
      rfidStartBtn.classList.remove("hidden");
      rfidStopBtn.classList.add("hidden");
      if (data.error) {
        showRfidStatus(`RFID scanning stopped: ${data.error}`, "error");
      }
      if (rfidPollTimer) {
        clearInterval(rfidPollTimer);
        rfidPollTimer = null;
      }
    }
  } catch (err) {
    // ignore transient poll errors
  }
}

rfidStartBtn.addEventListener("click", async () => {
  const courseId = courseSelect.value;
  if (!courseId) return;

  rfidStartBtn.disabled = true;
  try {
    const formData = new FormData();
    formData.append("course_id", courseId);
    
    const res = await fetch("/attendance/rfid-scan/start", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to start RFID scanning");

    showRfidStatus(`RFID scanning started for ${data.course_code}.`, "success");
    rfidStartBtn.classList.add("hidden");
    rfidStopBtn.classList.remove("hidden");
    if (!rfidPollTimer) {
      rfidPollTimer = setInterval(refreshRfidStatus, 1500);
    }
  } catch (err) {
    showRfidStatus(err.message, "error");
    rfidStartBtn.disabled = false;
  }
});

rfidStopBtn.addEventListener("click", async () => {
  rfidStopBtn.disabled = true;
  try {
    await fetch("/attendance/rfid-scan/stop", { method: "POST" });
    showRfidStatus("RFID scanning stopped.", "info");
    rfidStopBtn.classList.add("hidden");
    rfidStartBtn.classList.remove("hidden");
    rfidStartBtn.disabled = !courseSelect.value;
    if (rfidPollTimer) {
      clearInterval(rfidPollTimer);
      rfidPollTimer = null;
    }
  } catch (err) {
    showRfidStatus(err.message, "error");
  } finally {
    rfidStopBtn.disabled = false;
  }
});

loadDepartments().catch((err) => showStatus(err.message, "error"));
refreshPiCamStatus();
refreshRfidStatus();