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

function showStatus(message, type = "info") {
  setupStatus.textContent = message;
  setupStatus.className = `status show ${type}`;
}

async function loadDepartments() {
  const res = await fetch("/departments");
  if (!res.ok) throw new Error("Failed to load departments");
  const departments = await res.json();

  departments.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.department_id;
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

  if (!departmentId) return;

  const res = await fetch(`/levels?department_id=${departmentId}`);
  if (!res.ok) throw new Error("Failed to load levels");
  const levels = await res.json();

  levels.forEach((l) => {
    const opt = document.createElement("option");
    opt.value = l.level_id;
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

  if (!departmentId || !levelId) return;

  const res = await fetch(`/courses?department_id=${departmentId}&level_id=${levelId}`);
  if (!res.ok) throw new Error("Failed to load courses");
  const courses = await res.json();

  courses.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.course_id;
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
    showStatus("Install face-recognition on the server to enable scanning.", "error");
    return;
  }

  dlibStatus.textContent = `Session date: ${session.session_date} · Recognition engine: dlib`;
  dlibStatus.style.color = "var(--muted)";

  if (session.students_with_faces === 0) {
    showStatus("No enrolled students have face data yet. Students must register first.", "error");
    startBtn.disabled = true;
    return;
  }

  startBtn.disabled = false;
  showStatus("Ready to start the attendance scanning session.", "success");
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

loadDepartments().catch((err) => showStatus(err.message, "error"));
