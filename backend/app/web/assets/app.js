"use strict";

// Токен только в оперативной памяти вкладки; после перезагрузки нужен новый вход.
const state = { token: null, user: null, settings: null, view: "overview", clinicalPatient: null, clinicalPublications: [] };
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
  state.clinicalPatient = null;
  state.clinicalPublications = [];
  $("patient-details").hidden = true;
  $("patient-publications").replaceChildren();
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
  $("clinical-nav").hidden = !doctor || !state.clinicalPatient;
  $("patient-nav").hidden = !patient;
  $("admin-nav").hidden = !admin;
  if (doctor) {
    $("stat-role").textContent = roleNames[user.role];
    $("overview-title").textContent = "Кабинет врача";
    $("overview-description").textContent =
      "Доступные вам пациенты и настройки для будущего клинического контекста.";
    $("overview-notice").textContent =
      "Выберите пациента для просмотра истории и визитов. Назначения, тесты и AI-область пока не подключены.";
  }
  showView(doctor ? "overview" : patient ? "patient" : "admin");
}

function showView(name) {
  if (!state.user) return;
  const permitted = state.user.role === "doctor"
    ? ["overview", "settings", "clinical"] : state.user.role === "patient" ? ["patient"] : ["admin"];
  if (!permitted.includes(name) || (name === "clinical" && !state.clinicalPatient)) return;
  state.view = name;
  $("overview-view").hidden = name !== "overview";
  $("patient-view").hidden = name !== "patient";
  $("settings-view").hidden = name !== "settings";
  $("clinical-view").hidden = name !== "clinical";
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
  if (name === "clinical" && state.clinicalPatient) loadClinical();
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
  $("patient-publications").textContent = "Загрузка…";
  showMessage("patient-status", "Загрузка карточки…");
  try {
    const record = await api("/patients/me/portal");
    if (state.user?.id !== accountId || state.view !== "patient") return;
    $("patient-alias").textContent = record.alias;
    $("patient-id").textContent = record.patient_id;
    $("patient-created").textContent = formatDate(record.created_at);
    $("patient-details").hidden = false;
    showMessage("patient-status", "");
    await loadPatientPublications(accountId);
  } catch (error) {
    if (state.user?.id !== accountId || state.view !== "patient") return;
    const message = error.status === 404
      ? "Учётная запись пока не связана с активной карточкой пациента. Попросите администратора выполнить привязку."
      : `Не удалось загрузить карточку: ${error.message}`;
    showMessage("patient-status", message);
  }
}

async function loadPatientPublications(accountId) {
  const target = $("patient-publications");
  target.textContent = "Загрузка опубликованных записей…";
  try {
    const data = await api("/patients/me/clinical-publications");
    if (state.user?.id !== accountId || state.view !== "patient") return;
    target.replaceChildren();
    if (!data.items.length) {
      target.textContent = "Врач пока не публиковал записей для вас.";
      return;
    }
    data.items.forEach((item) => target.append(clinicalLine(
      formatDate(item.published_at), item.text, "Подтверждено и опубликовано врачом"
    )));
  } catch (error) {
    if (state.user?.id === accountId && state.view === "patient") {
      target.textContent = `Не удалось загрузить опубликованные записи: ${error.message}`;
    }
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
  if (state.user?.role === "doctor") {
    const open = document.createElement("button");
    open.type = "button";
    open.className = "button subtle";
    open.textContent = "Визиты и история →";
    open.addEventListener("click", () => {
      state.clinicalPatient = { id: patient.id, alias: patient.alias };
      $("clinical-nav").hidden = false;
      showView("clinical");
    });
    row.append(open);
  }
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

const clinicalReasons = {
  initial: "Первичный", follow_up: "Повторный", review: "Оценка динамики",
};
const clinicalImpactLabels = {
  none: "Нет", mild: "Лёгкие", moderate: "Умеренные", severe: "Выраженные",
};
const clinicalKinds = {
  encounter: "Визит", history_event: "Событие",
  observation: "Наблюдение", questionnaire: "Опросник",
};

function clinicalLine(title, details, note) {
  const row = document.createElement("div");
  row.className = "clinical-entry";
  const strong = document.createElement("strong");
  strong.textContent = title;
  const info = document.createElement("span");
  info.textContent = details;
  row.append(strong, info);
  if (note) {
    const small = document.createElement("small");
    small.textContent = note;
    row.append(small);
  }
  return row;
}

function showClinicalRecords(elementId, records, renderer, empty) {
  const target = $(elementId);
  target.replaceChildren();
  if (!records.length) {
    target.textContent = empty;
    return;
  }
  records.slice(0, 100).forEach((item) => target.append(renderer(item)));
  if (records.length > 100) target.append(clinicalLine("Показано 100 записей", "Для просмотра остальных потребуется отдельная пагинация."));
}

function renderClinicalVisits(items) {
  $("clinical-visits-count").textContent = String(items.length);
  showClinicalRecords("clinical-encounters", items, (item) =>
    clinicalLine(
      `${formatDate(item.occurred_at)} · ${clinicalReasons[item.reason] || item.reason}`,
      (item.complaints || []).join("; ") || "Жалобы не внесены",
      `Статус: ${item.status}; ограничения: ${clinicalImpactLabels[item.functional_impact] || "не указаны"}` +
      (item.clinician_question ? `; вопрос врача: ${item.clinician_question}` : ""),
    ), "Визитов пока нет. Для постоянного заполнения истории выполните seed UI-2B.");
}

function renderClinicalHistory(items) {
  $("clinical-history-count").textContent = String(items.length);
  const records = new Map(state.clinicalPublications.map((p) => [p.history_event_id, p]));
  const superseded = new Set(items.map((item) => item.supersedes_id).filter(Boolean));
  showClinicalRecords("clinical-history", items, (item) => {
    const fact = item.fact || {};
    const description = typeof fact.text === "string"
      ? fact.text : JSON.stringify(fact).slice(0, 500);
    const row = clinicalLine(
      `${formatDate(item.occurred_at)} · ${item.category}`,
      description, `Источник: ${item.source_ref}; приоритет: ${item.priority}`,
    );
    const fullFact = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Показать полный исходный факт перед подтверждением";
    const fullText = document.createElement("pre");
    fullText.textContent = JSON.stringify(item.fact || {}, null, 2);
    fullFact.append(summary, fullText);
    row.append(fullFact);
    const release = records.get(item.id);
    const status = document.createElement("small");
    status.textContent = superseded.has(item.id) ? "Историческая версия исправлена"
      : release ? `Решение врача: ${release.status}; версия ${release.version}`
        : "Запись ещё не подтверждена врачом";
    row.append(status);
    if (superseded.has(item.id)) return row;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button subtle";
    if (!release) {
      button.textContent = "Подтвердить запись";
      button.addEventListener("click", () => confirmHistory(item.id, button));
    } else if (release.status === "confirmed") {
      button.textContent = "Подготовить публикацию пациенту";
      button.addEventListener("click", () => preparePublication(item, release));
    } else if (release.status === "published") {
      button.textContent = "Отозвать публикацию";
      button.addEventListener("click", () => revokePublication(release, button));
    } else {
      return row;
    }
    row.append(button);
    return row;
  }, "Событий пока нет.");
}

async function confirmHistory(eventId, button) {
  const patient = state.clinicalPatient;
  if (!patient || !window.confirm(
    "Подтвердить клиническую запись? Это сохранит врачебное решение, но НЕ покажет запись пациенту."
  )) return;
  button.disabled = true;
  try {
    await api(`/patients/${encodeURIComponent(patient.id)}/history-events/${encodeURIComponent(eventId)}/confirm`, {
      method: "POST",
    });
    await loadClinical();
  } catch (error) {
    showMessage("clinical-publication-status", `Ошибка подтверждения: ${error.message}`);
    button.disabled = false;
  }
}

function preparePublication(item, release) {
  const form = $("clinical-publication-form");
  form.hidden = false;
  $("clinical-publication-id").value = release.id;
  $("clinical-publication-version").value = String(release.version);
  $("clinical-publication-source").textContent =
    `Источник: ${formatDate(item.occurred_at)}, ${item.category}, ID ${item.id}. Исходный текст не передаётся пациенту.`;
  $("clinical-publication-text").value = "";
  $("clinical-publication-confirm").checked = false;
  showMessage("clinical-publication-status", "Введите только те сведения, которые следует показать пациенту.");
  form.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function revokePublication(release, button) {
  const patient = state.clinicalPatient;
  if (!patient) return;
  const reason = window.prompt("Причина отзыва опубликованного текста (не менее 3 символов):");
  if (reason === null) return;
  if (reason.trim().length < 3) {
    showMessage("clinical-publication-status", "Укажите причину отзыва от 3 символов.");
    return;
  }
  if (!window.confirm("Отозвать публикацию? Пациент больше не увидит её в своём кабинете.")) return;
  button.disabled = true;
  try {
    await api(`/patients/${encodeURIComponent(patient.id)}/clinical-publications/${encodeURIComponent(release.id)}/revoke`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: release.version, reason: reason.trim() }),
    });
    await loadClinical();
  } catch (error) {
    showMessage("clinical-publication-status", `Ошибка отзыва: ${error.message}`);
    button.disabled = false;
  }
}

$("clinical-publication-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const patient = state.clinicalPatient;
  if (!patient || state.user?.role !== "doctor") return;
  const text = $("clinical-publication-text").value.trim();
  if (!text || !$("clinical-publication-confirm").checked) return;
  if (!window.confirm(
    `ПАЦИЕНТ УВИДИТ ИМЕННО ЭТОТ ТЕКСТ:\\n\\n${text}\\n\\nПодтвердить публикацию?`
  )) return;
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await api(`/patients/${encodeURIComponent(patient.id)}/clinical-publications/${encodeURIComponent($("clinical-publication-id").value)}/publish`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_version: Number($("clinical-publication-version").value),
        patient_text: text, confirm_patient_visibility: true,
      }),
    });
    $("clinical-publication-form").hidden = true;
    await loadClinical();
  } catch (error) {
    showMessage("clinical-publication-status", `Ошибка публикации: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});
$("clinical-publication-cancel").addEventListener("click", () => {
  $("clinical-publication-form").hidden = true;
});


const observationNames = {
  subjective_anxiety: "Самооценка тревожности",
  subjective_energy: "Самооценка энергии",
  subjective_sleep_quality: "Самооценка качества сна",
};

function renderClinicalObservations(context) {
  const items = (context.items || []).filter((item) => item.kind === "observation")
    .sort((a, b) => new Date(b.at) - new Date(a.at));
  $("clinical-observations-count").textContent = String(items.length);
  showClinicalRecords("clinical-observations", items, (item) => {
    const values = item.payload?.value || {};
    const score = typeof values.score === "number" && Number.isFinite(values.score)
      ? `${values.score} из ${values.max ?? 10}` : "Значение не указано";
    return clinicalLine(
      `${formatDate(item.at)} · ${observationNames[item.payload?.code] || item.payload?.code || "Наблюдение"}`,
      `${score}. ${values.description || "Описание отсутствует"}`,
      `Источник: ${item.source_ref}; только для врача`,
    );
  }, "Наблюдений пока нет.");
}

function renderClinicalDigest(digest) {
  const counts = Object.entries(digest.counts_by_kind || {})
    .map(([kind, n]) => `${clinicalKinds[kind] || kind}: ${n}`).join(" · ");
  $("clinical-context").replaceChildren(
    clinicalLine(`Фактов в контексте: ${digest.total_facts}`, counts,
      `Версия ${digest.schema_version}; SHA-256: ${digest.context_sha256}`),
    clinicalLine("Временной диапазон",
      digest.earliest_fact_at
        ? `${formatDate(digest.earliest_fact_at)} — ${formatDate(digest.latest_fact_at)}`
        : "Фактов пока нет"),
    clinicalLine("Контроль границ", digest.complete
      ? "Контекст не усечён" : `Усечены источники: ${digest.truncated_sources.join(", ")}`,
    `Непроверенных вложений исключено: ${digest.excluded_attachments_count}`),
  );
}

async function loadClinical() {
  const patient = state.clinicalPatient;
  if (!patient || state.user?.role !== "doctor") return;
  $("clinical-title").textContent = patient.alias;
  $("clinical-identity").textContent = `ID: ${patient.id} · Внутренняя клиническая карточка врача`;
  $("clinical-publication-form").hidden = true;
  showMessage("clinical-card-status", "Загрузка…");
  ["clinical-encounters", "clinical-history", "clinical-observations", "clinical-context"].forEach((id) => {
    $(id).textContent = "Загрузка…";
  });
  try {
    const [visits, history, context, digest, publications] = await Promise.all([
      api(`/patients/${encodeURIComponent(patient.id)}/encounters`),
      api(`/patients/${encodeURIComponent(patient.id)}/history-events`),
      api(`/patients/${encodeURIComponent(patient.id)}/context`),
      api(`/patients/${encodeURIComponent(patient.id)}/context/digest`),
      api(`/patients/${encodeURIComponent(patient.id)}/clinical-publications`),
    ]);
    if (state.view !== "clinical" || state.clinicalPatient?.id !== patient.id) return;
    state.clinicalPublications = publications;
    renderClinicalVisits(visits.items || []);
    renderClinicalHistory(history.items || []);
    renderClinicalObservations(context);
    renderClinicalDigest(digest);
    showMessage("clinical-card-status", "Данные обновлены", true);
  } catch (error) {
    if (state.view !== "clinical" || state.clinicalPatient?.id !== patient.id) return;
    showMessage("clinical-card-status", `Ошибка загрузки: ${error.message}`);
    ["clinical-encounters", "clinical-history", "clinical-observations", "clinical-context"].forEach((id) => {
      $(id).textContent = "Данные недоступны.";
    });
  }
}

document.querySelectorAll("[data-clinical-target]").forEach((button) => {
  button.addEventListener("click", () => {
    if (state.view !== "clinical") return;
    const target = $(button.dataset.clinicalTarget);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
$("clinical-back").addEventListener("click", () => showView("overview"));
$("clinical-refresh").addEventListener("click", loadClinical);
$("clinical-encounter-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const patient = state.clinicalPatient;
  if (!patient || state.user?.role !== "doctor") return;
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const complaints = $("clinical-complaints").value.split(/\r?\n/)
    .map((text) => text.trim()).filter(Boolean);
  if (complaints.length > 50) {
    showMessage("clinical-save-status", "Максимум 50 жалоб.");
    return;
  }
  const question = $("clinical-question").value.trim();
  button.disabled = true;
  showMessage("clinical-save-status", "Сохранение…");
  try {
    await api(`/patients/${encodeURIComponent(patient.id)}/encounters`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reason: $("clinical-reason").value, complaints,
        functional_impact: $("clinical-impact").value || null,
        clinician_question: question || null,
      }),
    });
    form.reset();
    showMessage("clinical-save-status", "Черновик визита сохранён в PostgreSQL", true);
    await loadClinical();
  } catch (error) {
    showMessage("clinical-save-status", `Не сохранено: ${error.message}`);
  } finally { button.disabled = false; }
});

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
