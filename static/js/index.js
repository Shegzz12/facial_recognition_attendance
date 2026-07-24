const departmentSelect = document.getElementById("department-select");
const levelSelect = document.getElementById("level-select");
const courseSection = document.getElementById("course-section");
const courseList = document.getElementById("course-list");
const continueBtn = document.getElementById("continue-btn");
const portalStatus = document.getElementById("portal-status");

let selectedDepartmentId = null;
let selectedLevelId = null;
let selectedCourseIds = new Set();
let departmentsCache = [];
let levelsCache = [];

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function showStatus(message, type = "info") {
  portalStatus.textContent = message;
  portalStatus.className = `status show ${type}`;
}

async function loadDepartments() {
  try {
    const res = await fetch("/departments");
    if (!res.ok) throw new Error("Failed to load departments");
    departmentsCache = await res.json();

    departmentSelect.innerHTML = '<option value="">— Select department —</option>';
    departmentsCache.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.id;  // FIXED: Use 'id' instead of 'department_id'
      opt.textContent = d.code ? `${d.name} (${d.code})` : d.name;
      departmentSelect.appendChild(opt);
    });
  } catch (err) {
    showStatus(err.message, "error");
  }
}

async function loadLevels(departmentId) {
  try {
    levelSelect.innerHTML = '<option value="">— Select level —</option>';
    levelSelect.disabled = true;
    courseSection.classList.add("hidden");
    selectedCourseIds.clear();
    continueBtn.disabled = true;

    if (!departmentId) return;

    const res = await fetch(`/levels?department_id=${departmentId}`);
    if (!res.ok) throw new Error("Failed to load levels");
    levelsCache = await res.json();

    levelSelect.disabled = levelsCache.length === 0;
    levelsCache.forEach((l) => {
      const opt = document.createElement("option");
      opt.value = l.id;  // FIXED: Use 'id' instead of 'level_id'
      opt.textContent = l.name;
      levelSelect.appendChild(opt);
    });
  } catch (err) {
    showStatus(err.message, "error");
  }
}

async function loadCourses(departmentId, levelId) {
  try {
    courseList.innerHTML = '<p class="empty">Loading courses…</p>';
    courseSection.classList.add("hidden");
    selectedCourseIds.clear();
    continueBtn.disabled = true;

    if (!departmentId || !levelId) return;

    const res = await fetch(`/courses?department_id=${departmentId}&level_id=${levelId}`);
    if (!res.ok) throw new Error("Failed to load courses");
    const courses = await res.json();

    if (courses.length === 0) {
      courseList.innerHTML = '<p class="empty">No courses available for this department and level.</p>';
      return;
    }

    courseList.innerHTML = courses
      .map(
        (c) => `
      <label class="course-checkbox">
        <input type="checkbox" value="${c.id}" data-code="${escapeHtml(c.code)}" data-name="${escapeHtml(c.name)}">
        <span>${escapeHtml(c.code)} — ${escapeHtml(c.name)}</span>
      </label>
    `
      )
      .join("");

    courseSection.classList.remove("hidden");
    courseList.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          selectedCourseIds.add(checkbox.value);
        } else {
          selectedCourseIds.delete(checkbox.value);
        }
        continueBtn.disabled = selectedCourseIds.size === 0;
      });
    });
  } catch (err) {
    showStatus(err.message, "error");
  }
}

departmentSelect.addEventListener("change", async () => {
  selectedDepartmentId = departmentSelect.value || null;
  await loadLevels(selectedDepartmentId);
  showStatus("");
});

levelSelect.addEventListener("change", async () => {
  selectedLevelId = levelSelect.value || null;
  await loadCourses(selectedDepartmentId, selectedLevelId);
  showStatus("");
});

continueBtn.addEventListener("click", () => {
  const selectedCourses = Array.from(courseList.querySelectorAll('input[type="checkbox"]:checked')).map(
    (cb) => ({
      id: cb.value,
      code: cb.dataset.code,
      name: cb.dataset.name,
    })
  );

  const params = new URLSearchParams();
  params.set("department_id", selectedDepartmentId);
  params.set("level_id", selectedLevelId);
  selectedCourses.forEach((c, i) => {
    params.set(`course_ids[${i}]`, c.id);
    params.set(`course_codes[${i}]`, c.code);
    params.set(`course_names[${i}]`, c.name);
  });

  window.location.href = `/static/register.html?${params.toString()}`;
});

async function init() {
  await loadDepartments();
}

init();
