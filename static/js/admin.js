const addDeptForm = document.getElementById("add-dept-form");
const addCourseForm = document.getElementById("add-course-form");
const deptStatus = document.getElementById("dept-status");
const courseStatus = document.getElementById("course-status");
const coursesPanel = document.getElementById("courses-panel");
const refreshBtn = document.getElementById("refresh-btn");
const courseContextHint = document.getElementById("course-context-hint");

const courseDeptSelect = document.getElementById("course_dept");
const courseLevelSelect = document.getElementById("course_level");
const courseCodeInput = document.getElementById("course_code");
const courseNameInput = document.getElementById("course_name");
const courseLecturerInput = document.getElementById("course_lecturer");
const filterDept = document.getElementById("filter-dept");
const filterLevel = document.getElementById("filter-level");

const statDepartments = document.getElementById("stat-departments");
const statLevels = document.getElementById("stat-levels");
const statCourses = document.getElementById("stat-courses");
const statEnrollments = document.getElementById("stat-enrollments");

let departmentsCache = [];

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function showStatus(el, message, type = "info") {
  el.textContent = message;
  el.className = `status show ${type}`;
}

function formatApiError(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return "Request failed";
}

function deptLabel(d) {
  return d.code ? `${d.name} (${d.code})` : d.name;
}

function updateCourseContextHint() {
  const deptText = courseDeptSelect.selectedOptions[0]?.textContent || "";
  const levelText = courseLevelSelect.selectedOptions[0]?.textContent || "";

  if (courseDeptSelect.value && courseLevelSelect.value) {
    courseContextHint.textContent = `Adding courses for: ${deptText} · ${levelText}. Department and level stay selected after each add.`;
  } else {
    courseContextHint.textContent = "Pick department and level once, then keep adding courses below.";
  }
}

function populateDeptSelects() {
  [courseDeptSelect, filterDept].forEach((sel) => {
    const isFilter = sel === filterDept;
    const previous = sel.value;
    sel.innerHTML = isFilter
      ? '<option value="">All departments</option>'
      : '<option value="">— Select department —</option>';
    departmentsCache.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.id;  // FIXED: Use 'id' instead of 'department_id'
      opt.textContent = deptLabel(d);
      sel.appendChild(opt);
    });
    if (previous && [...sel.options].some((o) => o.value === previous)) {
      sel.value = previous;
    }
  });
}

async function loadLevelsInto(select, departmentId, includeAllOption = false, preserveValue = false) {
  const previous = preserveValue ? select.value : "";
  select.innerHTML = includeAllOption
    ? '<option value="">All levels</option>'
    : '<option value="">— Select level —</option>';
  select.disabled = !departmentId && !includeAllOption;

  if (!departmentId) return [];

  const res = await fetch(`/levels?department_id=${departmentId}`);
  if (!res.ok) throw new Error("Failed to load levels");
  const levels = await res.json();

  levels.forEach((l) => {
    const opt = document.createElement("option");
    opt.value = l.id;  // FIXED: Use 'id' instead of 'level_id'
    opt.textContent = l.name;
    select.appendChild(opt);
  });

  select.disabled = levels.length === 0 && !includeAllOption;
  if (preserveValue && previous && [...select.options].some((o) => o.value === previous)) {
    select.value = previous;
  }
  return levels;
}

function clearCourseFields() {
  courseCodeInput.value = "";
  courseNameInput.value = "";
  courseLecturerInput.value = "";
  courseCodeInput.focus();
}

async function loadDepartments() {
  const res = await fetch("/departments");
  if (!res.ok) throw new Error("Failed to load departments");
  departmentsCache = await res.json();
  populateDeptSelects();
  statDepartments.textContent = departmentsCache.length;

  const levelsRes = await fetch("/levels");
  if (levelsRes.ok) {
    const levels = await levelsRes.json();
    statLevels.textContent = levels.length;
  }
}

async function loadCourses() {
  coursesPanel.innerHTML = `<p class="empty">Loading courses…</p>`;

  try {
    let url = "/admin/courses";
    const params = new URLSearchParams();
    if (filterDept.value) params.set("department_id", filterDept.value);
    if (filterLevel.value) params.set("level_id", filterLevel.value);
    if ([...params.keys()].length) url += `?${params.toString()}`;

    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load courses");
    const courses = await res.json();

    statCourses.textContent = courses.length;
    statEnrollments.textContent = courses.reduce((sum, c) => sum + c.student_count, 0);

    if (courses.length === 0) {
      coursesPanel.innerHTML = `<p class="empty">No courses found. Create a department, pick a level, and add courses above.</p>`;
      return;
    }

    coursesPanel.innerHTML = courses.map(renderCourseCard).join("");
    coursesPanel.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => toggleStudents(btn));
    });
  } catch (err) {
    coursesPanel.innerHTML = `<p class="empty" style="color: var(--danger)">${escapeHtml(err.message)}</p>`;
  }
}

function renderCourseCard(course) {
  return `
    <div class="admin-course" data-course-id="${course.id}">
      <div class="admin-course-head">
        <div>
          <strong>${escapeHtml(course.code)} — ${escapeHtml(course.name)}</strong>
          <div class="course-meta-line">
            ${escapeHtml(course.department_name)} · ${escapeHtml(course.level_name)}
            ${course.lecturer ? ` · ${escapeHtml(course.lecturer)}` : ""}
            · ${course.student_count} student(s)
            · ${course.total_attendance_marks} attendance mark(s)
          </div>
        </div>
        <button type="button" class="btn btn-secondary" data-toggle="${course.id}">
          View students
        </button>
      </div>
      <div class="student-table-wrap hidden" id="students-${course.id}">
        <p class="empty">Click "View students" to load roster.</p>
      </div>
    </div>
  `;
}

async function toggleStudents(button) {
  const courseId = button.dataset.toggle;
  const panel = document.getElementById(`students-${courseId}`);
  const isHidden = panel.classList.contains("hidden");

  if (!isHidden) {
    panel.classList.add("hidden");
    button.textContent = "View students";
    return;
  }

  panel.classList.remove("hidden");
  button.textContent = "Hide students";
  panel.innerHTML = `<p class="empty">Loading students…</p>`;

  try {
    const res = await fetch(`/admin/courses/${courseId}/students`);
    if (!res.ok) throw new Error("Failed to load students");
    const students = await res.json();

    if (students.length === 0) {
      panel.innerHTML = `<p class="empty">No students registered for this course yet.</p>`;
      return;
    }

    panel.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>Matric No.</th>
            <th>Full Name</th>
            <th>Registered</th>
            <th>Face Samples</th>
            <th>Attendance Marks</th>
          </tr>
        </thead>
        <tbody>
          ${students
            .map(
              (s) => `
            <tr>
              <td>${escapeHtml(s.matric_no)}</td>
              <td>${escapeHtml(s.full_name)}</td>
              <td>${escapeHtml(formatDate(s.registered_at))}</td>
              <td>${s.face_samples}</td>
              <td><span class="badge">${s.attendance_count}</span></td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
    `;
  } catch (err) {
    panel.innerHTML = `<p class="empty" style="color: var(--danger)">${escapeHtml(err.message)}</p>`;
  }
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value.replace(" ", "T") + "Z");
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

addDeptForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("dept_name").value.trim();
  const code = document.getElementById("dept_code").value.trim();
  const payload = { name };
  if (code) payload.code = code;

  try {
    const res = await fetch("/departments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(formatApiError(data.detail));

    addDeptForm.reset();
    showStatus(deptStatus, `Department "${data.name}" created with levels 100L–500L.`, "success");
    await loadDepartments();
    await loadCourses();
  } catch (err) {
    showStatus(deptStatus, err.message, "error");
  }
});

addCourseForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    department_id: courseDeptSelect.value,  // FIXED: Removed Number() conversion
    level_id: courseLevelSelect.value,      // FIXED: Removed Number() conversion
    code: courseCodeInput.value.trim(),
    name: courseNameInput.value.trim(),
  };
  const lecturer = courseLecturerInput.value.trim();
  if (lecturer) payload.lecturer = lecturer;

  try {
    const res = await fetch("/courses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(formatApiError(data.detail));

    clearCourseFields();
    showStatus(
      courseStatus,
      `Added ${data.code}. You can add another course for the same department and level.`,
      "success"
    );
    updateCourseContextHint();
    await loadCourses();
  } catch (err) {
    showStatus(courseStatus, err.message, "error");
  }
});

courseDeptSelect.addEventListener("change", async () => {
  await loadLevelsInto(courseLevelSelect, courseDeptSelect.value, false, false);
  updateCourseContextHint();
});

courseLevelSelect.addEventListener("change", updateCourseContextHint);

filterDept.addEventListener("change", async () => {
  filterLevel.innerHTML = '<option value="">All levels</option>';
  if (filterDept.value) {
    filterLevel.disabled = false;
    await loadLevelsInto(filterLevel, filterDept.value, true);
  } else {
    filterLevel.disabled = true;
  }
  await loadCourses();
});

filterLevel.addEventListener("change", loadCourses);
refreshBtn.addEventListener("click", loadCourses);

const rebuildBtn = document.getElementById("rebuild-embeddings-btn");
const embeddingsStatus = document.getElementById("embeddings-status");

if (rebuildBtn) {
  rebuildBtn.addEventListener("click", async () => {
    rebuildBtn.disabled = true;
    showStatus(embeddingsStatus, "Rebuilding face profiles from enrollment images…", "info");

    try {
      const res = await fetch("/attendance/rebuild-embeddings", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(formatApiError(data.detail));

      showStatus(embeddingsStatus, data.message, "success");
    } catch (err) {
      showStatus(embeddingsStatus, err.message, "error");
    } finally {
      rebuildBtn.disabled = false;
    }
  });
}

async function init() {
  try {
    await loadDepartments();
    if (courseDeptSelect.value) {
      await loadLevelsInto(courseLevelSelect, courseDeptSelect.value, false, false);
    }
    updateCourseContextHint();
    await loadCourses();
  } catch (err) {
    coursesPanel.innerHTML = `<p class="empty" style="color: var(--danger)">${escapeHtml(err.message)}</p>`;
  }
}

init();
