const deptSelect = document.getElementById("department-select");
const levelSelect = document.getElementById("level-select");
const courseSection = document.getElementById("course-section");
const courseList = document.getElementById("course-list");
const continueBtn = document.getElementById("continue-btn");
const portalStatus = document.getElementById("portal-status");

let availableCourses = [];

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function showStatus(message, type = "info") {
  portalStatus.textContent = message;
  portalStatus.className = `status show ${type}`;
}

function hideStatus() {
  portalStatus.className = "status";
}

function getSelectedCourseIds() {
  return [...courseList.querySelectorAll('input[type="checkbox"]:checked')].map(
    (el) => el.value
  );
}

function updateContinueButton() {
  continueBtn.disabled = getSelectedCourseIds().length === 0;
}

async function loadDepartments() {
  try {
    const res = await fetch("/departments");
    if (!res.ok) throw new Error("Failed to load departments");
    const departments = await res.json();

    deptSelect.innerHTML = '<option value="">— Select department —</option>';
    departments.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.department_id;
      opt.textContent = d.code ? `${d.name} (${d.code})` : d.name;
      deptSelect.appendChild(opt);
    });

    if (departments.length === 0) {
      showStatus("No departments yet. Ask an admin to create departments first.", "info");
    }
  } catch (err) {
    showStatus(err.message, "error");
  }
}

async function loadLevels(departmentId) {
  levelSelect.innerHTML = '<option value="">— Select level —</option>';
  levelSelect.disabled = true;
  courseSection.classList.add("hidden");
  courseList.innerHTML = "";
  availableCourses = [];

  if (!departmentId) return;

  try {
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
    if (levels.length === 0) {
      showStatus("No levels found for this department. Contact an admin.", "info");
    } else {
      hideStatus();
    }
  } catch (err) {
    showStatus(err.message, "error");
  }
}

async function loadCourses(departmentId, levelId) {
  courseList.innerHTML = "";
  availableCourses = [];
  courseSection.classList.add("hidden");

  if (!departmentId || !levelId) return;

  try {
    const res = await fetch(`/courses?department_id=${departmentId}&level_id=${levelId}`);
    if (!res.ok) throw new Error("Failed to load courses");
    availableCourses = await res.json();

    if (availableCourses.length === 0) {
      courseSection.classList.remove("hidden");
      courseList.innerHTML =
        '<p class="empty">No courses available for this department and level yet.</p>';
      continueBtn.disabled = true;
      return;
    }

    courseList.innerHTML = availableCourses
      .map(
        (c) => `
      <label class="course-check">
        <input type="checkbox" value="${c.course_id}" />
        <span>
          <strong>${escapeHtml(c.code)} — ${escapeHtml(c.name)}</strong>
          <small>${c.lecturer ? escapeHtml(c.lecturer) : "No lecturer listed"}</small>
        </span>
      </label>`
      )
      .join("");

    courseSection.classList.remove("hidden");
    courseList.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.addEventListener("change", updateContinueButton);
    });
    updateContinueButton();
    hideStatus();
  } catch (err) {
    showStatus(err.message, "error");
  }
}

deptSelect.addEventListener("change", () => {
  loadLevels(deptSelect.value);
});

levelSelect.addEventListener("change", () => {
  loadCourses(deptSelect.value, levelSelect.value);
});

continueBtn.addEventListener("click", () => {
  const courseIds = getSelectedCourseIds();
  if (courseIds.length === 0) return;

  const params = new URLSearchParams({
    department_id: deptSelect.value,
    level_id: levelSelect.value,
    course_ids: courseIds.join(","),
  });

  const deptName = deptSelect.options[deptSelect.selectedIndex].textContent;
  const levelName = levelSelect.options[levelSelect.selectedIndex].textContent;
  params.set("dept_name", deptName);
  params.set("level_name", levelName);

  window.location.href = `/static/register.html?${params.toString()}`;
});

loadDepartments();
