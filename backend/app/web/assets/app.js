"use strict";

// Токен только в оперативной памяти вкладки; после перезагрузки нужен новый вход.
const state = { token: null, user: null, settings: null, view: "overview" };
const $ = (id) => document.getElementById(id);
const roleNames = { doctor: "Врач", patient: "Пациент", admin: "Администратор" };

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

function showMessage(id, text, ok = false) {
  const el = $(id);
  el.textContent = text;
  el.classList.toggle("success", ok);
}

function endSession(message = "") {
  state.token = null;
  state.user = null;
  state.settings = null;
  state.view = "overview";
  $("patient-details").hidden = true;
  showMessage("patient-status", "");
  clearAdminData();
  $("workspace").hidden = true;
  $("login-screen").hidden = false;
  $("login-password").value = "";
  $("login-username").focus();
  showMessage("login-status", message);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`/api/v1${path}`, {
    ...options, headers, credentials: "same-origin", cache: "no-store",
  });
  if (response.status === 401 && state.user) {
    endSession("Сессия истекла. Выполните вход повторно.");
    throw new ApiError("Сессия истекла", 401);
  }
  if (!response.ok) {
    let description = `Ошибка сервера (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") description = body.detail;
    } catch { /* HTTP-ответ может не содержать JSON. */ }
    throw new ApiError(description, response.status);
  }
  return response.status === 204 ? null : response.json();
}

function roleLayout(user) {
  const doctor = user.role === "doctor";
  const patient = user.role === "patient";
  const admin = user.role === "admin";
  $("login-screen").hidden = true;
  $("workspace").hidden = false;
  $("account-name").textContent = user.username;
  $("account-avatar").textContent = user.username.charAt(0).toUpperCase();
  $("account-role").textContent = roleNames[user.role];
  $("role-breadcrumb").textContent = `Кабинет: ${roleNames[user.role]}`;
  $("overview-nav").hidden = !doctor;
  $("settings-nav").hidden = !doctor;
  $("patient-nav").hidden = !patient;
  $("admin-nav").hidden = !admin;
  if (doctor) {
    $("stat-role").textContent = roleNames[user.role];
    $("overview-title").textContent = "Кабинет врача";
    $("overview-description").textContent =
      "Доступные вам пациенты и настройки для будущего клинического контекста.";
    $("overview-notice").textContent =
      "Просмотр визитов, назначения, тесты и AI-область подключаются следующими инкрементами. На UI-1B назначения не создаются.";
  }
  showView(doctor ? "overview" : patient ? "patient" : "admin");
}

function showView(name) {
  if (!state.user) return;
  const permitted = state.user.role === "doctor"
    ? ["overview", "settings"] : state.user.role === "patient" ? ["patient"] : ["admin"];
  if (!permitted.includes(name)) return;
  state.view = name;
  $("overview-view").hidden = name !== "overview";
  $("patient-view").hidden = name !== "patient";
  $("settings-view").hidden = name !== "settings";
  $("admin-view").hidden = name !== "admin";
  document.querySelectorAll("[data-view]").forEach((node) => {
    const active = node.dataset.view === name;
    node.classList.toggle("active", active);
    if (active) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  if (name === "settings") loadSettings();
  if (name === "patient") loadPatientPortal();
  if (name === "admin") loadAdmin();
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Дата неизвестна" : date.toLocaleDateString("ru-RU");
}

async function loadPatientPortal() {
  const accountId = state.user?.id;
  if (state.user?.role !== "patient") return;
  $("patient-details").hidden = true;
  showMessage("patient-status", "Загрузка карточки…");
  try {
    const record = await api("/patients/me/portal");
    if (state.user?.id !== accountId || state.view !== "patient") return;
    $("patient-alias").textContent = record.alias;
    $("patient-id").textContent = record.patient_id;
    $("patient-created").textContent = formatDate(record.created_at);
    $("patient-details").hidden = false;
    showMessage("patient-status", "");
  } catch (error) {
    if (state.user?.id !== accountId || state.view !== "patient") return;
    const message = error.status === 404
      ? "Учётная запись пока не связана с активной карточкой пациента. Попросите администратора выполнить привязку."
      : `Не удалось загрузить карточку: ${error.message}`;
    showMessage("patient-status", message);
  }
}

function patientItem(patient) {
  const row = document.createElement("div");
  row.className = "patient-entry";
  const title = document.createElement("span");
  title.textContent = patient.alias || "Без псевдонима";
  const id = document.createElement("small");
  id.textContent = `ID: ${patient.id}`;
  row.append(title, id);
  return row;
}

async function loadOverview() {
  const root = $("patients-list");
  root.replaceChildren();
  $("stat-patients").textContent = "…";
  try {
    const data = await api("/patients");
    const patients = Array.isArray(data.items) ? data.items : [];
    $("stat-patients").textContent = String(data.total ?? patients.length);
    if (!patients.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "Нет доступных пациентов.";
      root.append(empty);
    } else {
      patients.forEach((p) => root.append(patientItem(p)));
    }
  } catch (error) {
    $("stat-patients").textContent = "—";
    root.textContent = "Не удалось получить пациентов: " + error.message;
  }
}

const profileMapping = {
  full_name: "profile-full-name", specialty: "profile-specialty",
  institution: "profile-institution", professional_info: "profile-info",
  contact_email: "profile-email",
};
const clinicalMapping = {
  practice_country: "clinical-country", rki_mode: "clinical-rki",
  institution_type: "clinical-institution", clinical_specialty: "clinical-specialty",
};

function fillForm(mapping, source) {
  Object.entries(mapping).forEach(([key, id]) => {
    $(id).value = source[key] ?? "";
  });
}

function readForm(mapping) {
  return Object.fromEntries(
    Object.entries(mapping).map(([key, id]) => [key, $(id).value.trim() || null])
  );
}

function setSettings(data) {
  state.settings = data;
  $("settings-version").textContent = `Версия настроек: ${data.version}`;
  fillForm(profileMapping, data.profile);
  fillForm(clinicalMapping, data.clinical);
}

async function loadSettings() {
  showMessage("global-status", "");
  try {
    const data = await api("/doctors/me/settings");
    if (state.view === "settings" && state.user?.role === "doctor") setSettings(data);
  } catch (error) {
    showMessage("global-status", "Не удалось загрузить настройки: " + error.message);
  }
}

function selectTab(tab) {
  $("profile-form").hidden = tab !== "profile";
  $("clinical-form").hidden = tab !== "clinical";
  document.querySelectorAll("[data-tab]").forEach((node) => {
    const active = node.dataset.tab === tab;
    node.classList.toggle("selected", active);
    node.setAttribute("aria-selected", String(active));
    node.tabIndex = active ? 0 : -1;
  });
  $("tab-" + tab).focus();
}

async function saveSettings(section, form) {
  const statusId = section + "-status";
  if (!state.settings) return showMessage(statusId, "Настройки ещё не загружены.");
  const btn = form.querySelector('button[type="submit"]');
  const mapping = section === "profile" ? profileMapping : clinicalMapping;
  const values = readForm(mapping);
  if (section === "clinical" && !values.rki_mode) values.rki_mode = "disabled";
  btn.disabled = true;
  showMessage(statusId, "Сохранение…");
  try {
    const data = await api(`/doctors/me/settings/${section}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...values, expected_version: state.settings.version }),
    });
    setSettings(data);
    showMessage(statusId, "Сохранено в PostgreSQL", true);
  } catch (error) {
    const text = error.status === 409
      ? "Конфликт версии. Перезагрузите настройки перед повторным сохранением."
      : `Не сохранено: ${error.message}`;
    showMessage(statusId, text);
  } finally { btn.disabled = false; }
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = event.currentTarget.querySelector("button");
  btn.disabled = true;
  showMessage("login-status", "");
  try {
    const tokens = await api("/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: $("login-username").value, password: $("login-password").value,
      }),
    });
    state.token = tokens.access_token;
    const user = await api("/auth/me");
    if (!["doctor", "patient", "admin"].includes(user.role)) {
      try { await api("/auth/logout", { method: "POST" }); }
      catch { /* Токен в любом случае будет забыт этой вкладкой. */ }
      throw new Error("Неизвестная роль пользователя.");
    }
    state.user = user;
    $("login-password").value = "";
    roleLayout(user);
    if (user.role === "doctor") await loadOverview();
  } catch (error) { endSession(error.message); }
  finally { btn.disabled = false; }
});

$("logout-button").addEventListener("click", async () => {
  let text = "";
  try { await api("/auth/logout", { method: "POST" }); }
  catch { text = "Токен удалён из вкладки, но сервер не подтвердил завершение сессии."; }
  endSession(text);
});

document.querySelectorAll("[data-view]").forEach((node) => {
  node.addEventListener("click", () => showView(node.dataset.view));
});
document.querySelectorAll("[data-tab]").forEach((node) => {
  node.addEventListener("click", () => selectTab(node.dataset.tab));
});
$("profile-form").addEventListener("submit", (event) => {
  event.preventDefault(); saveSettings("profile", event.currentTarget);
});
$("clinical-form").addEventListener("submit", (event) => {
  event.preventDefault(); saveSettings("clinical", event.currentTarget);
});
// UI-1C: административные действия. Только безопасные текстовые DOM-узлы.
const adminState = { users: [], patients: [], links: [] };

function clearAdminData() {
  adminState.users = [];
  adminState.patients = [];
  adminState.links = [];
  for (const id of ["admin-users", "admin-patients", "admin-links", "admin-audit"]) {
    $(id).replaceChildren();
  }
}

function adminEntry(primary, secondary, action = null) {
  const row = document.createElement("div");
  row.className = "admin-entry";
  const info = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = primary;
  const small = document.createElement("small");
  small.textContent = secondary;
  info.append(strong, small);
  row.append(info);
  if (action) row.append(action);
  return row;
}

function fillSelect(id, options, emptyLabel) {
  const select = $(id);
  select.replaceChildren();
  if (!options.length) {
    select.add(new Option(emptyLabel, ""));
    select.disabled = true;
  } else {
    select.disabled = false;
    options.forEach(([value, label]) => select.add(new Option(label, value)));
  }
}

function userLabel(id) {
  const account = adminState.users.find((x) => x.id === id);
  return account ? account.username : `ID ${id}`;
}

function patientLabel(id) {
  const card = adminState.patients.find((x) => x.id === id);
  return card ? card.alias : `ID ${id}`;
}

async function loadAdmin() {
  if (state.user?.role !== "admin" || state.view !== "admin") return;
  const actorId = state.user.id;
  showMessage("admin-status", "Загрузка…");
  try {
    const [users, patients, links, audit] = await Promise.all([
      api("/admin/users"), api("/admin/patients"),
      api("/admin/links"), api("/admin/audit"),
    ]);
    if (state.user?.id !== actorId || state.view !== "admin") return;
    adminState.users = users;
    adminState.patients = patients;
    adminState.links = links;
    renderAdmin(audit);
    showMessage("admin-status", "Данные обновлены", true);
  } catch (error) {
    if (state.user?.id === actorId && state.view === "admin") {
      clearAdminData();
      showMessage("admin-status", `Ошибка: ${error.message}`);
    }
  }
}

function renderAdmin(audit) {
  const users = $("admin-users");
  users.replaceChildren();
  adminState.users.forEach((u) => {
    users.append(adminEntry(u.username, `${roleNames[u.role] || u.role} · ${u.id}`));
  });

  const patients = $("admin-patients");
  patients.replaceChildren();
  adminState.patients.forEach((p) => {
    patients.append(adminEntry(
      p.alias,
      `${p.synthetic ? "Синтетический" : "Без признака synthetic"} · ${p.id}` +
        (p.user_id ? ` · ${userLabel(p.user_id)}` : " · аккаунт не привязан")
    ));
  });

  const links = $("admin-links");
  links.replaceChildren();
  adminState.links.forEach((link) => {
    const button = document.createElement("button");
    button.className = "button subtle";
    button.type = "button";
    button.textContent = "Отозвать";
    button.addEventListener("click", () => revokeLink(link));
    links.append(adminEntry(
      `${userLabel(link.doctor_id)} → ${patientLabel(link.patient_id)}`,
      `Связь: ${link.id}`, button
    ));
  });
  if (!adminState.links.length) links.append(adminEntry("Связей пока нет", ""));

  const doctors = adminState.users.filter((x) => x.role === "doctor");
  const accounts = adminState.users.filter(
    (x) => x.role === "patient" && !adminState.patients.some((p) => p.user_id === x.id)
  );
  const unbound = adminState.patients.filter((p) => !p.user_id);
  fillSelect("admin-doctor-select",
    doctors.map((x) => [x.id, x.username]), "Нет врачей");
  fillSelect("admin-link-patient-select",
    adminState.patients.map((x) => [x.id, x.alias]), "Нет пациентов");
  fillSelect("admin-patient-account-select",
    accounts.map((x) => [x.id, x.username]), "Нет свободных аккаунтов");
  fillSelect("admin-bind-patient-select",
    unbound.map((x) => [x.id, x.alias]), "Нет свободных карточек");

  const history = $("admin-audit");
  history.replaceChildren();
  audit.forEach((e) => history.append(adminEntry(
    e.action,
    `${formatDate(e.created_at)} · ${userLabel(e.actor_id)} · объект ${e.target_id}`
  )));
  if (!audit.length) history.append(adminEntry("Административных событий пока нет", ""));
}

async function sendAdmin(form, endpoint, values, statusId) {
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  showMessage(statusId, "Сохранение…");
  try {
    await api(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    form.reset();
    showMessage(statusId, "Сохранено в PostgreSQL", true);
    await loadAdmin();
  } catch (error) {
    showMessage(statusId, `Ошибка: ${error.message}`);
  } finally { button.disabled = false; }
}

async function revokeLink(link) {
  if (!window.confirm(
    `Отозвать доступ врача ${userLabel(link.doctor_id)} к пациенту ${patientLabel(link.patient_id)}?`
  )) return;
  showMessage("admin-link-status", "Отзыв доступа…");
  try {
    await api(`/admin/links/${encodeURIComponent(link.id)}`, { method: "DELETE" });
    showMessage("admin-link-status", "Доступ отозван", true);
    await loadAdmin();
  } catch (error) {
    showMessage("admin-link-status", `Ошибка: ${error.message}`);
  }
}

$("admin-refresh").addEventListener("click", loadAdmin);
$("admin-user-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendAdmin(event.currentTarget, "/admin/users", {
    username: $("admin-username").value.trim(),
    password: $("admin-user-password").value,
    role: $("admin-user-role").value,
  }, "admin-user-status");
});
$("admin-patient-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendAdmin(event.currentTarget, "/admin/synthetic-patients", {
    alias: $("admin-patient-alias").value.trim(),
  }, "admin-patient-status");
});
$("admin-link-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendAdmin(event.currentTarget, "/access/link", {
    doctor_id: $("admin-doctor-select").value,
    patient_id: $("admin-link-patient-select").value,
  }, "admin-link-status");
});
$("admin-bind-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendAdmin(event.currentTarget, "/access/patient-account", {
    user_id: $("admin-patient-account-select").value,
    patient_id: $("admin-bind-patient-select").value,
  }, "admin-bind-status");
});
