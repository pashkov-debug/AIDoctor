"use strict";

// Токен только в оперативной памяти вкладки; после перезагрузки нужен новый вход.
const state = { token: null, user: null, settings: null, view: "overview" };
const $ = (id) => document.getElementById(id);
const roleNames = { doctor: "Врач" };

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
  $("login-screen").hidden = true;
  $("workspace").hidden = false;
  $("account-name").textContent = user.username;
  $("account-avatar").textContent = user.username.charAt(0).toUpperCase();
  $("account-role").textContent = roleNames[user.role];
  $("role-breadcrumb").textContent = `Кабинет: ${roleNames[user.role]}`;
  $("stat-role").textContent = roleNames[user.role];
  $("settings-nav").hidden = user.role !== "doctor";
  $("overview-title").textContent = `Кабинет ${roleNames[user.role].toLowerCase()}`;
  $("overview-description").textContent =
    "Доступные вам пациенты и настройки для будущего клинического контекста.";
  $("overview-notice").textContent =
    "Просмотр визитов, назначения, тесты и AI-область подключаются следующими инкрементами. На UI-1A назначения не создаются.";
  showView("overview");
}

function showView(name) {
  if (name === "settings" && state.user?.role !== "doctor") return;
  state.view = name;
  $("overview-view").hidden = name !== "overview";
  $("settings-view").hidden = name !== "settings";
  document.querySelectorAll("[data-view]").forEach((node) => {
    const active = node.dataset.view === name;
    node.classList.toggle("active", active);
    if (active) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  if (name === "settings") loadSettings();
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
    if (user.role !== "doctor") {
      try { await api("/auth/logout", { method: "POST" }); }
      catch { /* Токен в любом случае будет забыт этой вкладкой. */ }
      throw new Error("На UI-1A доступен только кабинет врача. Кабинеты пациента и администратора ещё не реализованы.");
    }
    state.user = user;
    $("login-password").value = "";
    roleLayout(user);
    await loadOverview();
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
