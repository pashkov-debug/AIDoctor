"use strict";

// Токен только в оперативной памяти вкладки; после перезагрузки нужен новый вход.
const state = { token: null, user: null, settings: null, view: "overview", clinicalPatient: null, clinicalPublications: [] };
const $ = (id) => document.getElementById(id);
// AI располагается непосредственно рядом с картой. ID и обработчики сохраняются.
$("doctor-ai-column").append($("ai-view"));
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
  doctorPatients = [];
  $("sidebar-patient-select").replaceChildren();
  activePanels.clinical = "visits";
  activePanels.patient = "profile";
  activePanels.admin = "users";
  clearAIWorkspace();
  orderEditing = null;
  orderApproval = null;
  orderPendingKey = null;
  if ($("order-approval-dialog").open) $("order-approval-dialog").close();
  $("patient-details").hidden = true;
  $("patient-publications").replaceChildren();
  $("patient-orders").replaceChildren();
  $("patient-tests-list").replaceChildren();
  $("patient-test-form").hidden = true;
  activePatientTest = null;
  ["clinical-encounters", "clinical-history", "clinical-observations",
   "clinical-context", "clinical-orders-list", "clinical-tests-list",
   "patient-test-questions"].forEach((id) => $(id).replaceChildren());
  $("clinical-test-select").replaceChildren();
  ["patient-alias", "patient-id", "patient-created"].forEach((id) => {
    $(id).textContent = "—";
  });
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

// Навигация: врач работает со всеми разделами одной карты; пациент и администратор
// сохраняют прежнее переключение разделов.
const panelNames = {
  clinical: { visits: "Визиты", history: "Клиническая история",
    observations: "Наблюдения", orders: "Назначения",
    tests: "Психологические тесты", digest: "Клиническая сводка" },
  patient: { profile: "Моя карточка", publications: "Записи врача",
    orders: "Мои назначения", tests: "Мои тесты" },
  admin: { users: "Пользователи", patients: "Карточки пациентов",
    links: "Связи врач–пациент", accounts: "Привязка аккаунта", audit: "Аудит" },
};
const activePanels = { clinical: "visits", patient: "profile", admin: "users" };
let doctorPatients = [];

function roleLayout(user) {
  const doctor = user.role === "doctor";
  $("login-screen").hidden = true;
  $("workspace").hidden = false;
  $("account-name").textContent = user.username;
  $("account-avatar").textContent = user.username.charAt(0).toUpperCase();
  $("account-role").textContent = roleNames[user.role];
  $("role-breadcrumb").textContent = `Кабинет: ${roleNames[user.role]}`;
  // Список пунктов роли — единственный источник истины о видимости меню.
  document.querySelectorAll("[data-role]").forEach((node) => {
    node.hidden = node.dataset.role !== user.role;
  });
  if (doctor) {
    $("overview-title").textContent = "Кабинет врача";
    $("overview-description").textContent = "Выберите пациента в списке или слева.";
  }
  showView(doctor ? "overview" : user.role === "patient" ? "patient" : "admin");
}

function renderActivePanels(name) {
  document.querySelectorAll("[data-panel-group]").forEach((node) => {
    const selected = node.dataset.panelGroup === name
      && (name === "clinical" || node.dataset.panel === activePanels[name]);
    node.hidden = !selected || (name === "clinical" && !state.clinicalPatient);
  });
  $("clinical-no-patient").hidden = name !== "clinical" || Boolean(state.clinicalPatient);
  $("patient-workspace-grid").hidden = name !== "clinical" || !state.clinicalPatient;
  $("clinical-timeline").hidden = name !== "clinical" || !state.clinicalPatient;
  $("ai-view").hidden = name !== "clinical" || !state.clinicalPatient;
  $("clinical-refresh").disabled = !state.clinicalPatient;
  $("clinical-open-ai").disabled = !state.clinicalPatient;
}

function showView(name, panel = null) {
  if (!state.user) return;
  if (name === "ai") {
    showView("clinical");
    if (state.clinicalPatient) $("doctor-ai-column").scrollIntoView({behavior:"smooth",block:"start"});
    return;
  }
  const permitted = state.user.role === "doctor"
    ? ["overview", "settings", "clinical", "ai"]
    : state.user.role === "patient" ? ["patient"] : ["admin"];
  if (!permitted.includes(name)) return;
  if (panel !== null && panelNames[name] && panelNames[name][panel]) {
    activePanels[name] = panel;
  }
  const previousView = state.view;
  state.view = name;
  for (const view of ["overview", "patient", "settings", "clinical", "admin"]) {
    $(view + "-view").hidden = view !== name;
  }
  renderActivePanels(name);
  document.querySelectorAll("[data-view]").forEach((node) => {
    const active = node.dataset.view === name
      && (!node.dataset.panel || node.dataset.panel === activePanels[name]);
    node.classList.toggle("active", active);
    if (active) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  const title = name === "clinical" ? "Рабочее место" :
    panelNames[name]?.[activePanels[name]] || (
      {overview: "Пациенты", settings: "Настройки врача"}[name]
    );
  $("role-breadcrumb").textContent = `${roleNames[state.user.role]} / ${title}`;
  window.scrollTo(0, 0);
  if (name === "settings" && previousView !== name) loadSettings();
  if (name === "patient" && previousView !== name) loadPatientPortal();
  if (name === "admin" && previousView !== name) loadAdmin();
  if (name === "clinical" && state.clinicalPatient && previousView !== name) {
    loadClinical();
    loadAIWorkspace();
  }
  if (name === "clinical" && panel && previousView === name) {
    const target = $(`clinical-${panel}-section`);
    if (target) target.scrollIntoView({behavior:"smooth",block:"start"});
  }
}

function chooseDoctorPatient(id, openClinical = false) {
  if (state.user?.role !== "doctor") return;
  const patient = doctorPatients.find((item) => item.id === id);
  const changed = state.clinicalPatient?.id !== (patient?.id || null);
  state.clinicalPatient = patient
    ? { id: patient.id, alias: patient.alias || "Пациент" } : null;
  $("sidebar-patient-select").value = patient ? patient.id : "";
  if (changed) {
    state.clinicalPublications = [];
    clearAIWorkspace();
    $("clinical-title").textContent = patient?.alias || "Карточка пациента";
    $("clinical-identity").textContent = patient ? `${patient.alias || "Пациент"} · история наблюдения` : "Пациент не выбран.";
  }
  if (openClinical) {
    const wasClinical = state.view === "clinical";
    showView("clinical", "visits");
    if (changed && wasClinical && patient) {
      loadClinical();
      loadAIWorkspace();
    }
  } else if (changed && state.view === "clinical") {
    showView("clinical");
    if (patient) {
      loadClinical();
      loadAIWorkspace();
    }
  }
}

function updateDoctorPatientPicker(patients) {
  doctorPatients = patients;
  const select = $("sidebar-patient-select");
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Выберите пациента";
  select.append(placeholder);
  patients.forEach((patient) => {
    const option = document.createElement("option");
    option.value = patient.id;
    option.textContent = patient.alias || patient.id;
    select.append(option);
  });
  const selectedId = state.clinicalPatient?.id;
  if (selectedId && !patients.some((patient) => patient.id === selectedId)) {
    state.clinicalPatient = null;
    clearAIWorkspace();
    if (state.view === "clinical") showView("clinical");
  }
  select.value = state.clinicalPatient?.id || "";
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Дата неизвестна" : date.toLocaleDateString("ru-RU");
}
function formatDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Время неизвестно"
    : date.toLocaleString("ru-RU", {dateStyle:"short",timeStyle:"short"});
}
function clinicalDateTime(id) {
  const value = $(id).value;
  return value ? new Date(value).toISOString() : null;
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
    await loadPatientOrders(accountId);
    await loadPatientTests(accountId);
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
  row.append(title);
  if (state.user?.role === "doctor") {
    const open = document.createElement("button");
    open.type = "button";
    open.className = "button subtle";
    open.textContent = "Визиты и история →";
    open.addEventListener("click", () => {
      chooseDoctorPatient(patient.id, true);
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
    updateDoctorPatientPicker(patients);
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
  const target = $("clinical-encounters");
  target.replaceChildren();
  const timeline = $("clinical-timeline-items");
  timeline.replaceChildren();
  const sorted = [...items].sort((a, b) => new Date(a.occurred_at) - new Date(b.occurred_at));
  $("clinical-timeline-caption").textContent = sorted.length
    ? `${sorted.length} визитов · ${formatDate(sorted[0].occurred_at)} — ${formatDate(sorted[sorted.length - 1].occurred_at)}`
    : "Пока нет записанных визитов";
  if (!items.length) {
    target.textContent = "Визитов пока нет.";
    timeline.textContent = "После записи визита здесь появится контрольная точка.";
    return;
  }
  const nodes = new Map();
  for (const item of items.slice(0,100)) {
    const row = clinicalLine(
      `${formatDate(item.occurred_at)} · ${clinicalReasons[item.reason] || item.reason}`,
      (item.complaints || []).join("; ") || "Жалобы не внесены",
      `Статус: ${item.status === "draft" ? "Черновик" : item.status === "confirmed" ? "Подтверждён" : "Запись визита"}; ограничения: ${clinicalImpactLabels[item.functional_impact] || "не указаны"}` +
      (item.clinician_question ? `; заметки врача: ${item.clinician_question}` : ""),
    );
    row.classList.add("case-visit-entry");
    nodes.set(item.id, row);
    target.append(row);
  }
  if (items.length > 100) target.append(clinicalLine("Показано 100 визитов", "Остальные доступны в истории клинических событий."));
  for (const item of sorted.slice(-30)) {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "case-timeline-marker";
    marker.textContent = formatDate(item.occurred_at);
    marker.title = `${clinicalReasons[item.reason] || item.reason}. Перейти к записи визита`;
    marker.addEventListener("click", () => {
      const row = nodes.get(item.id);
      if (!row) return;
      timeline.querySelectorAll("button").forEach(node => node.classList.remove("selected"));
      marker.classList.add("selected");
      target.querySelectorAll(".case-visit-entry").forEach(node => node.classList.remove("selected"));
      row.classList.add("selected");
      row.scrollIntoView({behavior:"smooth",block:"center"});
    });
    timeline.append(marker);
  }
}
const clinicalFactLabels = {
  text: "Описание", symptoms: "Симптомы", complaints: "Жалобы",
  duration: "Продолжительность", status: "Состояние", medication: "Препарат",
  active_ingredient: "Действующее вещество", dose: "Доза",
  dosage: "Дозировка", source: "Источник сведений", notes: "Примечания",
  description: "Описание", reported_at: "Дата сообщения",
  sleep: "Сон", mood: "Настроение", anxiety: "Тревога",
};
const hiddenClinicalFactKeys = new Set(["synthetic", "seed_key", "source_ref"]);

function renderClinicalFact(fact) {
  const container = document.createElement("dl");
  container.className = "clinical-fact-fields";
  for (const [key, value] of Object.entries(fact || {})) {
    if (hiddenClinicalFactKeys.has(key) || value === null || value === undefined) continue;
    const field = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = clinicalFactLabels[key] || key.replaceAll("_", " ");
    const definition = document.createElement("dd");
    definition.textContent = Array.isArray(value)
      ? value.map((part) => typeof part === "object" ? Object.values(part).join(", ") : String(part)).join("; ")
      : typeof value === "object"
        ? Object.entries(value).map(([k, v]) => `${clinicalFactLabels[k] || k.replaceAll("_", " ")}: ${String(v)}`).join("; ")
        : typeof value === "boolean" ? (value ? "Да" : "Нет") : String(value);
    field.append(term, definition);
    container.append(field);
  }
  if (!container.children.length) {
    const noData = document.createElement("p");
    noData.textContent = "Подробности не указаны.";
    container.append(noData);
  }
  return container;
}

function renderClinicalHistory(items) {
  $("clinical-history-count").textContent = String(items.length);
  const records = new Map(state.clinicalPublications.map((p) => [p.history_event_id, p]));
  const superseded = new Set(items.map((item) => item.supersedes_id).filter(Boolean));
  showClinicalRecords("clinical-history", items, (item) => {
    const fact = item.fact || {};
    const description = typeof fact.text === "string"
      ? fact.text : "Сведения из клинической истории";
    const row = clinicalLine(
      `${formatDate(item.occurred_at)} · ${({
        self_report: "Со слов пациента", clinical: "Клиническая запись",
        treatment: "Лечение", observation: "Наблюдение",
      })[item.category] || "Событие истории"}`,
      description, "",
    );
    const fullFact = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Дополнительные сведения";
    fullFact.append(summary, renderClinicalFact(item.fact));
    row.append(fullFact);
    const release = records.get(item.id);
    const status = document.createElement("small");
    status.textContent = superseded.has(item.id) ? "Историческая версия исправлена"
      : release ? `Решение врача: ${({
          confirmed: "Подтверждено", published: "Опубликовано пациенту",
          revoked: "Публикация отозвана",
        })[release.status] || "Запись рассмотрена"}`
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

function renderClinicalObservations(context, observationRecords = []) {
  const stored = Array.isArray(observationRecords) ? observationRecords : [];
  const existing = (context.items || []).filter(item => item.kind === "observation");
  const items = stored.length ? stored.map(item => ({
    id: item.id, at: item.observed_at, code: item.code, value: item.value,
    source: item.code_system || "Запись наблюдения",
  })) : existing.map(item => ({
    at: item.at, code: item.payload?.code, value: item.payload?.value || {},
    source: "Наблюдение в истории пациента",
  }));
  items.sort((a,b) => new Date(b.at) - new Date(a.at));
  $("clinical-observations-count").textContent = String(items.length);
  showClinicalRecords("clinical-observations", items, (item) => {
    const values = item.value || {};
    const hasScore = typeof values.score === "number" && Number.isFinite(values.score);
    const score = hasScore ? `${values.score}${Number.isFinite(values.max) ? ` из ${values.max}` : ""}` : "";
    const details = [score, values.description || values.text || ""].filter(Boolean).join(" · ") || "Описание не указано";
    return clinicalLine(
      `${formatDate(item.at)} · ${observationNames[item.code] || item.code || "Наблюдение"}`,
      details, item.source,
    );
  }, "Наблюдений пока нет.");
}
function renderClinicalDigest(digest) {
  const counts = Object.entries(digest.counts_by_kind || {})
    .map(([kind, n]) => `${clinicalKinds[kind] || kind}: ${n}`).join(" · ");
  $("clinical-context").replaceChildren(
    clinicalLine(`Сведений в сводке: ${digest.total_facts}`, counts),
    clinicalLine("Период наблюдения",
      digest.earliest_fact_at
        ? `${formatDate(digest.earliest_fact_at)} — ${formatDate(digest.latest_fact_at)}`
        : "Сведения пока не добавлены"),
    clinicalLine("Полнота сводки", digest.complete
      ? "Учтены доступные клинические сведения"
      : "Часть исторических сведений не вошла в краткую сводку",
      digest.excluded_attachments_count
        ? "Непроверенные документы не включены"
        : ""),
  );
}

let clinicalLoadEpoch = 0;

async function loadClinical() {
  const patient = state.clinicalPatient;
  if (!patient || state.user?.role !== "doctor") return;
  const epoch = ++clinicalLoadEpoch;
  $("clinical-title").textContent = patient.alias;
  $("clinical-identity").textContent = `${patient.alias || "Пациент"} · история наблюдения`;
  $("clinical-publication-form").hidden = true;
  showMessage("clinical-card-status", "Загрузка карты пациента…");
  for (const id of ["clinical-encounters", "clinical-history", "clinical-observations",
                    "clinical-context", "clinical-orders-list", "clinical-tests-list"]) {
    $(id).textContent = "Загрузка…";
  }
  $("clinical-timeline-items").replaceChildren();
  $("clinical-timeline-caption").textContent = "Загрузка хронологии…";
  $("clinical-test-select").replaceChildren();
  for (const id of ["clinical-visits-count", "clinical-history-count",
                    "clinical-observations-count", "clinical-orders-count",
                    "clinical-tests-count"]) $(id).textContent = "…";

  const paths = [
    "encounters", "history-events", "context", "context/digest",
    "clinical-publications", "observations",
  ];
  const results = await Promise.allSettled(paths.map(path =>
    api(`/patients/${encodeURIComponent(patient.id)}/${path}`)
  ));
  if (epoch !== clinicalLoadEpoch || state.view !== "clinical" ||
      state.clinicalPatient?.id !== patient.id) return;
  const [visits, history, context, digest, publications, observations] = results.map(
    result => result.status === "fulfilled" ? result.value : null
  );
  const failures = [];
  const failed = (index, label) => {
    const error = results[index].reason;
    failures.push(`${label}: ${error?.message || "ошибка получения данных"}`);
  };

  if (visits) renderClinicalVisits(visits.items || []);
  else {
    failed(0, "Визиты");
    $("clinical-encounters").textContent = "Не удалось загрузить визиты.";
    $("clinical-timeline-caption").textContent = "Хронология временно недоступна.";
    $("clinical-visits-count").textContent = "—";
  }
  if (history) renderClinicalHistory(history.items || []);
  else {
    failed(1, "История");
    $("clinical-history").textContent = "Не удалось загрузить клиническую историю.";
    $("clinical-history-count").textContent = "—";
  }
  if (context || observations) {
    renderClinicalObservations(context || {items: []}, observations?.items || []);
    if (!observations) failed(5, "Наблюдения");
    if (!context) failed(2, "Контекст наблюдений");
  } else {
    failed(2, "Контекст наблюдений");
    failed(5, "Наблюдения");
    $("clinical-observations").textContent = "Не удалось загрузить наблюдения.";
    $("clinical-observations-count").textContent = "—";
  }
  if (digest) renderClinicalDigest(digest);
  else {
    failed(3, "Сводка");
    $("clinical-context").textContent = "Не удалось загрузить клиническую сводку.";
  }
  state.clinicalPublications = publications || [];
  if (!publications) failed(4, "Публикации");

  await Promise.all([
    loadClinicalOrders(patient.id, epoch),
    loadClinicalTests(patient.id, epoch),
  ]);
  if (epoch !== clinicalLoadEpoch || state.view !== "clinical" ||
      state.clinicalPatient?.id !== patient.id) return;
  showMessage("clinical-card-status", failures.length
    ? `Часть разделов недоступна. ${failures.join("; ")}`
    : "Карта пациента обновлена.", failures.length === 0);
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
    showMessage("clinical-save-status", "Визит сохранён", true);
    await loadClinical();
  } catch (error) {
    showMessage("clinical-save-status", `Не сохранено: ${error.message}`);
  } finally { button.disabled = false; }
});

// Запись врача: ручной ввод использует API этапа 1, не редактирует историю напрямую.
$("clinical-history-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const patientId = state.clinicalPatient?.id;
  if (!patientId || state.user?.role !== "doctor") return;
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const text = $("clinical-history-text").value.trim();
  if (!text) return;
  button.disabled = true;
  showMessage("clinical-history-entry-status", "Сохранение записи…");
  try {
    await api(`/patients/${encodeURIComponent(patientId)}/history-events`, {
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        category:$("clinical-history-category").value,
        fact:{text},
        occurred_at:clinicalDateTime("clinical-history-date"),
      }),
    });
    if (state.clinicalPatient?.id !== patientId) return;
    form.reset();
    await loadClinical();
    showMessage("clinical-history-entry-status", "Запись сохранена в истории пациента.", true);
  } catch (error) {
    showMessage("clinical-history-entry-status", `Запись не сохранена: ${error.message}`);
  } finally { button.disabled = false; }
});

$("clinical-observation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const patientId = state.clinicalPatient?.id;
  if (!patientId || state.user?.role !== "doctor") return;
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const rawScore = $("clinical-observation-score").value.trim();
  const rawMax = $("clinical-observation-max").value.trim();
  const description = $("clinical-observation-description").value.trim();
  if (!rawScore && !description) {
    showMessage("clinical-observation-entry-status", "Укажите числовое значение или описание.");
    return;
  }
  if (rawMax && (!rawScore || Number(rawMax) < Number(rawScore))) {
    showMessage("clinical-observation-entry-status", "Максимум шкалы должен быть не меньше значения.");
    return;
  }
  const value = {};
  if (rawScore) value.score = Number(rawScore);
  if (rawMax) value.max = Number(rawMax);
  if (description) value.description = description;
  button.disabled = true;
  showMessage("clinical-observation-entry-status", "Сохранение наблюдения…");
  try {
    await api(`/patients/${encodeURIComponent(patientId)}/observations`, {
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        code:$("clinical-observation-code").value.trim(),
        code_system:null,
        observed_at:clinicalDateTime("clinical-observation-date"),
        value,
      }),
    });
    if (state.clinicalPatient?.id !== patientId) return;
    form.reset();
    await loadClinical();
    showMessage("clinical-observation-entry-status", "Наблюдение сохранено.", true);
  } catch (error) {
    showMessage("clinical-observation-entry-status", `Наблюдение не сохранено: ${error.message}`);
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
    showMessage(statusId, "Изменения сохранены", true);
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
  node.addEventListener("click", () => showView(node.dataset.view, node.dataset.panel || null));
});
$("sidebar-patient-select").addEventListener("change", (event) => {
  chooseDoctorPatient(event.currentTarget.value);
});
$("clinical-select-from-overview").addEventListener("click", () => showView("overview"));
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
    showMessage(statusId, "Изменения сохранены", true);
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


// UI-3A: отдельный контракт ручных назначений. Ни AI, ни автоматических решений.
let orderEditing = null;
let orderApproval = null;
let orderPendingKey = null;
const orderMedicationFields = {
  active_ingredient: "order-active-ingredient",
  dosage_form: "order-dosage-form",
  strength: "order-strength",
  dose_value: "order-dose-value",
  dose_unit: "order-dose-unit",
  route: "order-route",
  frequency_per_day: "order-frequency",
  timezone: "order-timezone",
  start_date: "order-start-date",
  duration_days: "order-duration",
  administration_notes: "order-administration",
  contraindications: "order-contraindications",
};
const orderCommonFields = {
  indication: "order-indication", rationale: "order-rationale",
  source_reference: "order-source",
};

function orderEndpoint(patientId) {
  return `/patients/${encodeURIComponent(patientId)}/clinical-orders`;
}

function refreshOrderFields() {
  const med = $("order-kind").value === "medication";
  $("order-med-fields").hidden = !med;
  $("order-exam-fields").hidden = med;
}
$("order-kind").addEventListener("change", refreshOrderFields);

function orderPayload() {
  const kind = $("order-kind").value;
  const data = {
    kind, name: $("order-name").value.trim(),
    request_key: orderEditing?.request_key || (orderPendingKey ||= crypto.randomUUID()),
  };
  Object.entries(orderCommonFields).forEach(([key, field]) => {
    const v = $(field).value.trim();
    if (v) data[key] = v;
  });
  if (kind === "medication") {
    Object.entries(orderMedicationFields).forEach(([key, field]) => {
      const v = $(field).value.trim();
      if (v) data[key] = v;
    });
    if (data.frequency_per_day) data.frequency_per_day = Number(data.frequency_per_day);
    if (data.duration_days) data.duration_days = Number(data.duration_days);
    const times = $("order-times").value.split(",").map((x) => x.trim()).filter(Boolean);
    if (times.length) data.times_local = times;
  } else {
    const v = $("order-examination-details").value.trim();
    if (v) data.examination_details = v;
  }
  return data;
}

function resetOrderEditor() {
  orderEditing = null;
  orderPendingKey = null;
  $("order-form").reset();
  $("order-kind").disabled = false;
  $("order-form-title").textContent = "Новое назначение — черновик";
  $("order-save-button").textContent = "Сохранить черновик";
  $("order-edit-cancel").hidden = true;
  refreshOrderFields();
}
$("order-edit-cancel").addEventListener("click", resetOrderEditor);

function startOrderEdit(item) {
  orderEditing = item;
  $("order-kind").value = item.kind;
  $("order-kind").disabled = true;
  $("order-name").value = item.name;
  Object.entries(orderCommonFields).forEach(([key, id]) => {
    $(id).value = item[key] ?? "";
  });
  Object.entries(orderMedicationFields).forEach(([key, id]) => {
    $(id).value = item[key] ?? "";
  });
  $("order-times").value = (item.times_local || []).join(", ");
  $("order-examination-details").value = item.examination_details || "";
  $("order-form-title").textContent = `Редактирование черновика · версия ${item.version}`;
  $("order-save-button").textContent = "Сохранить изменения";
  $("order-edit-cancel").hidden = false;
  refreshOrderFields();
  $("order-form").scrollIntoView({ behavior: "smooth", block: "start" });
}

function orderDescription(item) {
  if (item.kind === "examination") {
    return [item.name, item.examination_details, item.indication]
      .filter(Boolean).join(" · ");
  }
  const dose = item.dose_value ? `${item.dose_value} ${item.dose_unit || ""}` : "доза не указана";
  const clock = (item.times_local || []).join(", ") || "время не указано";
  return [
    item.name, item.strength, dose, item.route,
    `приёмов/день: ${item.frequency_per_day || "—"}`,
    `часы: ${clock} (${item.timezone || "без часового пояса"})`,
    item.start_date ? `начало ${item.start_date}` : null,
    item.duration_days ? `${item.duration_days} дней` : null,
    item.administration_notes ? `Условия: ${item.administration_notes}` : null,
  ].filter(Boolean).join(" · ");
}

// Врач видит клинические сведения, а не внутреннюю структуру хранения.
const clinicalPreviewLabels = {
  name: "Название",
  active_ingredient: "Действующее вещество",
  dosage_form: "Форма выпуска",
  strength: "Содержание / концентрация",
  dose_value: "Разовая доза",
  dose_unit: "Единица дозы",
  route: "Способ приёма или введения",
  frequency_per_day: "Приёмов в сутки",
  times_local: "Время приёма",
  timezone: "Часовой пояс",
  start_date: "Начало",
  duration_days: "Продолжительность (дней)",
  administration_notes: "Условия приёма",
  examination_details: "Описание обследования",
  indication: "Показание",
  contraindications: "Противопоказания и взаимодействия",
  rationale: "Обоснование",
  source_reference: "Источник",
  test_id: "Психологический тест",
  test_version: "Версия методики",
  category: "Категория записи",
  code: "Код наблюдения",
  code_system: "Система кодирования",
  title: "Гипотеза",
  medication: "Препарат",
  risk: "Описанный риск",
  severity: "Уровень риска (оценка AI)",
  confidence: "Уверенность AI (не вероятность диагноза)",
  classification: "Статус",
  priority: "Приоритет",
};
const demoTestNames = {
  DEMO_ANX_7: "Учебный опросник о тревожных симптомах",
  DEMO_DEP_9: "Учебный опросник о снижении настроения",
};

function clinicalPreviewValue(key, value) {
  if (value === null || value === undefined || value === "") return "Не указано";
  if (key === "test_id") return demoTestNames[value] || "Учебный тест";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "Не указано";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderClinicalPreviewFields(data, original = null) {
  const list = document.createElement("dl");
  list.className = "clinical-preview-fields";
  const visible = data.fact ? {...data, ...data.fact} : data.value ? {...data, ...data.value} : data;
  const initial = original?.fact ? {...original, ...original.fact} :
    original?.value ? {...original, ...original.value} : original;
  for (const [key, caption] of Object.entries(clinicalPreviewLabels)) {
    if (!Object.hasOwn(visible, key) && !Object.hasOwn(initial || {}, key)) continue;
    const row = document.createElement("div");
    row.className = "clinical-preview-field";
    if (initial && JSON.stringify(visible[key] ?? null) !== JSON.stringify(initial[key] ?? null)) {
      row.classList.add("clinical-preview-changed");
    }
    const term = document.createElement("dt");
    term.textContent = caption;
    const description = document.createElement("dd");
    description.textContent = clinicalPreviewValue(key, visible[key]);
    row.append(term, description);
    list.append(row);
  }
  return list;
}

function orderRecord(item) {
  const statusName = { draft: "Черновик", approved: "Утверждено", cancelled: "Отменено" };
  const row = clinicalLine(
    `${item.kind === "medication" ? "Препарат" : "Обследование"} · ${statusName[item.status]}`,
    orderDescription(item),
    `Версия ${item.version}; ${item.kind === "medication" ? "врач обязан проверить дозировку" : "ручное назначение"}`,
  );
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Полные поля назначения";
  details.append(summary, renderClinicalPreviewFields(item));
  row.append(details);
  if (item.status === "draft") {
    if (item.author_id === state.user?.id) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "button subtle";
      edit.textContent = "Редактировать";
      edit.addEventListener("click", () => startOrderEdit(item));
      row.append(edit);
    }
    const approve = document.createElement("button");
    approve.type = "button";
    approve.className = "button primary";
    approve.textContent = "Проверить и утвердить";
    approve.addEventListener("click", () => {
      orderApproval = item;
      $("order-approval-preview").replaceChildren(renderClinicalPreviewFields(item));
      showMessage("order-approval-status", "");
      $("order-approval-dialog").showModal();
    });
    row.append(approve);
  }
  if (item.status !== "cancelled") {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button subtle";
    cancel.textContent = item.status === "approved" ? "Отменить утверждённое" : "Отменить черновик";
    cancel.addEventListener("click", () => cancelOrder(item, cancel));
    row.append(cancel);
  }
  return row;
}

async function loadClinicalOrders(patientId, clinicalEpoch = null) {
  $("clinical-orders-list").textContent = "Загрузка назначений…";
  try {
    const items = await api(orderEndpoint(patientId));
    if (state.view !== "clinical" || state.clinicalPatient?.id !== patientId ||
        (clinicalEpoch !== null && clinicalEpoch !== clinicalLoadEpoch)) return;
    $("clinical-orders-count").textContent = String(items.length);
    showClinicalRecords(
      "clinical-orders-list", items, orderRecord,
      "Назначений нет. Создайте черновик ниже.",
    );
  } catch (error) {
    if (state.view !== "clinical" || state.clinicalPatient?.id !== patientId ||
        (clinicalEpoch !== null && clinicalEpoch !== clinicalLoadEpoch)) return;
    $("clinical-orders-count").textContent = "—";
    $("clinical-orders-list").textContent = `Назначения недоступны: ${error.message}`;
  }
}

$("order-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const patient = state.clinicalPatient;
  if (!patient || state.user?.role !== "doctor") return;
  const button = $("order-save-button");
  button.disabled = true;
  showMessage("order-save-status", "Запись…");
  const data = orderPayload();
  try {
    if (orderEditing) {
      await api(`${orderEndpoint(patient.id)}/${encodeURIComponent(orderEditing.id)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: orderEditing.version, data }),
      });
    } else {
      await api(orderEndpoint(patient.id), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    }
    resetOrderEditor();
    showMessage("order-save-status", "Черновик сохранён. Пациент его не видит.", true);
    await loadClinicalOrders(patient.id);
  } catch (error) {
    showMessage("order-save-status", `Ошибка сохранения: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});

$("order-approval-cancel").addEventListener("click", () => {
  $("order-approval-dialog").close();
  orderApproval = null;
});
$("order-approval-submit").addEventListener("click", async () => {
  const item = orderApproval;
  if (!item || item.patient_id !== state.clinicalPatient?.id) return;
  const button = $("order-approval-submit");
  button.disabled = true;
  try {
    await api(`${orderEndpoint(item.patient_id)}/${encodeURIComponent(item.id)}/approve`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_version: item.version,
        confirm_patient_visibility: true, confirm_clinical_review: true,
      }),
    });
    $("order-approval-dialog").close();
    orderApproval = null;
    await loadClinicalOrders(item.patient_id);
  } catch (error) {
    showMessage("order-approval-status", `Не утверждено: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});

async function cancelOrder(item, button) {
  const reason = window.prompt("Причина отмены (не менее 3 символов):");
  if (reason === null) return;
  if (reason.trim().length < 3) {
    showMessage("order-save-status", "Укажите причину отмены от 3 символов.");
    return;
  }
  if (!window.confirm("Отменить назначение? Если оно опубликовано, пациент перестанет видеть его как актуальное.")) return;
  button.disabled = true;
  try {
    await api(`${orderEndpoint(item.patient_id)}/${encodeURIComponent(item.id)}/cancel`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: item.version, reason: reason.trim() }),
    });
    if (orderEditing?.id === item.id) resetOrderEditor();
    await loadClinicalOrders(item.patient_id);
  } catch (error) {
    showMessage("order-save-status", `Ошибка отмены: ${error.message}`);
    button.disabled = false;
  }
}

async function loadPatientOrders(accountId) {
  const target = $("patient-orders");
  target.textContent = "Загрузка назначений…";
  try {
    const data = await api("/patients/me/clinical-orders");
    if (state.user?.id !== accountId || state.view !== "patient") return;
    target.replaceChildren();
    if (!data.items.length) {
      target.textContent = "Актуальных утверждённых назначений пока нет.";
      return;
    }
    data.items.forEach((item) => target.append(
      clinicalLine(
        `${item.kind === "medication" ? "Препарат" : "Обследование"} · ${item.name}`,
        orderDescription(item),
        `Врачебное утверждение: ${formatDate(item.approved_at)}`,
      )
    ));
  } catch (error) {
    if (state.user?.id === accountId && state.view === "patient") {
      target.textContent = `Не удалось получить назначения: ${error.message}`;
    }
  }
}


/* UI-3B. Только учебные опросники; нет автоматической диагностики. */
let demoTestCatalog = [];
let activePatientTest = null;

function testCatalogItem(id, version) {
  return demoTestCatalog.find((item) => item.test_id === id && item.version === version);
}

async function fetchTestCatalog() {
  demoTestCatalog = await api("/questionnaire-catalog");
  return demoTestCatalog;
}

function testStatusName(status) {
  return { assigned: "Ожидает ответа", completed: "Завершён", cancelled: "Отменён" }[status] || status;
}

function testDescription(item) {
  return `${item.title} · ${testStatusName(item.status)} · ${formatDate(item.created_at)}`;
}

async function loadClinicalTests(patientId, clinicalEpoch = null) {
  const target = $("clinical-tests-list");
  target.textContent = "Загрузка тестов…";
  try {
    const [catalog, items] = await Promise.all([
      fetchTestCatalog(), api(`/patients/${encodeURIComponent(patientId)}/questionnaire-assignments`),
    ]);
    if (state.view !== "clinical" || state.clinicalPatient?.id !== patientId ||
        (clinicalEpoch !== null && clinicalEpoch !== clinicalLoadEpoch)) return;
    const select = $("clinical-test-select");
    select.replaceChildren();
    catalog.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.test_id;
      option.textContent = `${item.title} · ${item.version}`;
      select.append(option);
    });
    $("clinical-tests-count").textContent = String(items.length);
    target.replaceChildren();
    if (!items.length) target.textContent = "Психологических тестов ещё не назначено.";
    const grouped = new Map();
    items.forEach((item) => {
      if (item.result) {
        const previous = grouped.get(item.test_id) || [];
        previous.push(item.result.total_score);
        grouped.set(item.test_id, previous);
      }
      const line = clinicalLine(
        testDescription(item),
        item.result
          ? `Баллы: ${item.result.total_score}; ответы: ${item.result.answers.join(", ")}`
          : "Ответов нет.",
        item.result?.critical_flag
          ? "ВНИМАНИЕ: критический ответ; требуется проверка врачом и Safety Alert."
          : `Версия: ${item.test_version}, статус: ${item.status}`,
      );
      if (item.status === "assigned") {
        const button = document.createElement("button");
        button.className = "button subtle";
        button.type = "button";
        button.textContent = "Отменить";
        button.addEventListener("click", async () => {
          const reason = window.prompt("Причина отмены (не менее 3 символов):");
          if (reason === null || reason.trim().length < 3) return;
          button.disabled = true;
          try {
            await api(`/patients/${encodeURIComponent(patientId)}/questionnaire-assignments/${encodeURIComponent(item.id)}/cancel`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_revision: item.revision, reason: reason.trim() }),
            });
            await loadClinicalTests(patientId);
          } catch (error) {
            showMessage("clinical-test-status", error.message);
            button.disabled = false;
          }
        });
        line.append(button);
      }
      target.append(line);
    });
    [...grouped.entries()].forEach(([testId, values]) => {
      const timeline = values.reverse();
      if (timeline.length < 2) return;
      const result = clinicalLine(
        `Динамика · ${testCatalogItem(testId, "demo-1")?.title || testId}`,
        `Баллы по попыткам от ранней к поздней: ${timeline.join(" → ")}`,
        "Учебная сумма баллов, без клинической интерпретации",
      );
      const graph = document.createElement("div");
      graph.className = "test-trend";
      graph.setAttribute("role", "img");
      graph.setAttribute("aria-label", `Динамика баллов: ${timeline.join(", ")}`);
      const maxScore = testId === "DEMO_DEP_9" ? 27 : 21;
      timeline.forEach((value, index) => {
        const col = document.createElement("div");
        col.className = "test-trend-column";
        const bar = document.createElement("span");
        bar.className = "test-trend-bar";
        bar.style.height = `${Math.max(4, Math.round(value / maxScore * 100))}%`;
        bar.title = `Попытка ${index + 1}: ${value} из ${maxScore}`;
        const label = document.createElement("small");
        label.textContent = String(value);
        col.append(bar, label);
        graph.append(col);
      });
      result.append(graph);
      target.append(result);
    });
  } catch (error) {
    if (state.view !== "clinical" || state.clinicalPatient?.id !== patientId ||
        (clinicalEpoch !== null && clinicalEpoch !== clinicalLoadEpoch)) return;
    $("clinical-tests-count").textContent = "—";
    target.textContent = `Не удалось загрузить тесты: ${error.message}`;
  }
}

$("clinical-test-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const patient = state.clinicalPatient;
  if (!patient || state.user?.role !== "doctor") return;
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const result = await api(`/patients/${encodeURIComponent(patient.id)}/questionnaire-assignments`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        test_id: $("clinical-test-select").value, request_key: crypto.randomUUID(),
      }),
    });
    showMessage("clinical-test-status", `Назначено: ${result.title}`, true);
    await loadClinicalTests(patient.id);
  } catch (error) {
    showMessage("clinical-test-status", `Не назначено: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});

async function loadPatientTests(accountId) {
  const target = $("patient-tests-list");
  target.textContent = "Загрузка тестов…";
  $("patient-test-form").hidden = true;
  activePatientTest = null;
  try {
    const [catalog, items] = await Promise.all([
      fetchTestCatalog(), api("/patients/me/questionnaire-assignments"),
    ]);
    if (state.user?.id !== accountId || state.view !== "patient") return;
    target.replaceChildren();
    if (!items.length) target.textContent = "Врач пока не назначал вам тесты.";
    items.forEach((item) => {
      const line = clinicalLine(
        testDescription(item),
        item.result
          ? `Результат: ${item.result.total_score} баллов из ${item.test_id === "DEMO_DEP_9" ? 27 : 21}.`
          : "Вы можете заполнить опросник один раз.",
        item.result?.critical_flag
          ? "Отмечен ответ, требующий внимания врача. Если есть непосредственная опасность, обратитесь за экстренной помощью."
          : "Учебный результат, не диагноз",
      );
      if (item.status === "assigned") {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "button primary";
        button.textContent = "Пройти тест";
        button.addEventListener("click", () => startPatientTest(item, catalog));
        line.append(button);
      }
      target.append(line);
    });
  } catch (error) {
    target.textContent = `Не удалось получить тесты: ${error.message}`;
  }
}

function startPatientTest(assignment, catalog) {
  const entry = catalog.find((item) =>
    item.test_id === assignment.test_id && item.version === assignment.test_version
  );
  if (!entry) {
    $("patient-tests-list").textContent = "Версия теста не поддерживается.";
    return;
  }
  activePatientTest = assignment;
  $("patient-test-title").textContent = entry.title;
  const target = $("patient-test-questions");
  target.replaceChildren();
  entry.questions.forEach((question, index) => {
    const field = document.createElement("label");
    field.className = "test-question";
    const heading = document.createElement("span");
    heading.textContent = `${index + 1}. ${question}`;
    const select = document.createElement("select");
    select.required = true;
    select.dataset.testQuestion = String(index);
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Выберите ответ";
    select.append(placeholder);
    entry.answer_labels.forEach((text, score) => {
      const option = document.createElement("option");
      option.value = String(score);
      option.textContent = text;
      select.append(option);
    });
    field.append(heading, select);
    target.append(field);
  });
  showMessage("patient-test-status", "");
  $("patient-test-form").hidden = false;
  $("patient-test-form").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("patient-test-cancel").addEventListener("click", () => {
  activePatientTest = null;
  $("patient-test-form").hidden = true;
});

$("patient-test-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const assignment = activePatientTest;
  if (!assignment || state.user?.role !== "patient") return;
  const answers = [...$("patient-test-questions").querySelectorAll("select")].map(
    (select) => select.value === "" ? null : Number(select.value)
  );
  if (answers.some((value) => value === null)) {
    showMessage("patient-test-status", "Ответьте на все вопросы.");
    return;
  }
  const button = $("patient-test-submit");
  button.disabled = true;
  try {
    const result = await api(`/patients/me/questionnaire-assignments/${encodeURIComponent(assignment.id)}/submit`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: assignment.revision, answers }),
    });
    activePatientTest = null;
    $("patient-test-form").hidden = true;
    if (result.result?.critical_flag) {
      window.alert("Ваш ответ отмечен для срочной врачебной проверки. Приложение не является экстренной службой. При непосредственной опасности обратитесь за экстренной помощью.");
    }
    await loadPatientTests(state.user.id);
  } catch (error) {
    showMessage("patient-test-status", `Ошибка сохранения: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});

// UI-4A. Данные рабочей области очищаются при смене пациента и выходе.
let aiPendingKey = null;
let aiLoadEpoch = 0;
let syntheticReviewEnabled = false;

function clearAIWorkspace() {
  syntheticReviewEnabled = false;
  $("ai-review-workspace").hidden = true;
  clearAIReview();
  aiLoadEpoch += 1;
  aiPendingKey = null;
  for (const id of ["ai-files", "ai-requests"]) $(id).replaceChildren();
  $("ai-patient-select").replaceChildren();
  $("ai-question").value = "";
  $("ai-upload").value = "";
  $("ai-response").textContent =
    "Ответ AI отсутствует. Никаких рекомендаций или назначений автоматически не создаётся.";
  showMessage("ai-workspace-status", "");
}

async function loadAIWorkspace() {
  if (state.user?.role !== "doctor") return;
  const epoch = ++aiLoadEpoch;
  showMessage("ai-workspace-status", "Получение доступных пациентов…");
  try {
    const data = await api("/patients");
    if (epoch !== aiLoadEpoch || state.view !== "clinical") return;
    const select = $("ai-patient-select");
    const patientId = state.clinicalPatient?.id;
    const patients = Array.isArray(data.items) ? data.items : [];
    const patient = patients.find(item => item.id === patientId);
    select.replaceChildren();
    if (!patient) {
      showMessage("ai-workspace-status", "Выбранная карта больше недоступна врачу.");
      $("ai-review-workspace").hidden = true;
      return;
    }
    const option = document.createElement("option");
    option.value = patient.id;
    option.textContent = patient.alias || patient.id;
    select.append(option);
    select.value = patient.id;
    // AI использует только пациента открытой карты, независимо от истории запросов.
    await loadAIForPatient();
  } catch (error) {
    if (epoch === aiLoadEpoch && state.view === "clinical") showMessage("ai-workspace-status", error.message);
  }
}

async function loadAIForPatient() {
  clearAIReview();
  const patientId = $("ai-patient-select").value;
  const epoch = ++aiLoadEpoch;
  aiPendingKey = null;
  $("ai-files").replaceChildren();
  $("ai-requests").replaceChildren();
  $("ai-response").textContent = "Выберите сохранённый запрос, чтобы просмотреть ответ агента.";
  if (!patientId || state.user?.role !== "doctor") return;
  // Пациента выбирает только общая карта. AI не может подменить выбор.
  if (state.clinicalPatient?.id !== patientId) return;
  showMessage("ai-workspace-status", "Загрузка рабочей области…");
  try {
    const [info, files, requests] = await Promise.all([
      api(`/patients/${encodeURIComponent(patientId)}/ai-workspace`),
      api(`/patients/${encodeURIComponent(patientId)}/attachments`),
      api(`/patients/${encodeURIComponent(patientId)}/ai-requests`),
    ]);
    if (epoch !== aiLoadEpoch || state.view !== "clinical" ||
        state.clinicalPatient?.id !== patientId ||
        $("ai-patient-select").value !== patientId) return;
    syntheticReviewEnabled = info.synthetic_review_enabled === true;
    $("ai-review-workspace").hidden = !syntheticReviewEnabled;
    renderAIFiles(files);
    renderAIRequests(requests);
    showMessage(
      "ai-workspace-status",
      "Рабочая область синхронизирована с картой пациента. Ответы внешнего агента доступны в истории запросов.",
      true
    );
  } catch (error) {
    if (epoch === aiLoadEpoch) {
      syntheticReviewEnabled = false;
      $("ai-review-workspace").hidden = true;
      showMessage("ai-workspace-status", error.message);
    }
  }
}

function renderAIFiles(files) {
  const target = $("ai-files");
  target.replaceChildren();
  if (!files.length) {
    target.textContent = "Вложений у пациента пока нет.";
    return;
  }
  for (const file of files) {
    const row = document.createElement("div");
    row.className = "ai-file-row";
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = file.id;
    checkbox.className = "ai-attachment-choice";
    checkbox.addEventListener("change", () => { aiPendingKey = null; });
    const title = document.createElement("span");
    title.textContent = file.filename;
    label.append(checkbox, title);
    const status = document.createElement("small");
    status.textContent = "Файл сохранён. Содержимое не включено в AI-контекст без проверки.";
    row.append(label, status);
    target.append(row);
  }
}

function renderAIRequests(requests) {
  const target = $("ai-requests");
  target.replaceChildren();
  if (!requests.length) {
    target.textContent = "Подготовленных запросов ещё нет.";
    return;
  }
  for (const item of [...requests].sort((a,b) => new Date(b.created_at) - new Date(a.created_at))) {
    const row = document.createElement("div");
    row.className = "admin-entry";
    const detail = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${formatDateTime(item.created_at)} · Запрос врача`;
    const question = document.createElement("p");
    question.textContent = item.question;
    const meta = document.createElement("small");
    const attachmentCount = item.attachment_manifest?.length || 0;
    meta.textContent = attachmentCount
      ? `Прикреплено документов: ${attachmentCount} · содержимое исключено из контекста до проверки`
      : `ID запроса: ${item.id}`;
    detail.append(title, question, meta);
    const analysisButton = document.createElement("button");
    analysisButton.type = "button";
    analysisButton.className = "button subtle";
    analysisButton.textContent = "Открыть сохранённый AI-анализ";
    const analysisOutput = document.createElement("div");
    analysisOutput.className = "ai-analysis-result";
    analysisButton.addEventListener("click", async () => {
      if (state.user?.role !== "doctor" || state.clinicalPatient?.id !== item.patient_id) return;
      const epoch = aiLoadEpoch;
      analysisButton.disabled = true;
      analysisOutput.replaceChildren();
      try {
        const result = await api(
          `/patients/${encodeURIComponent(item.patient_id)}` +
          `/ai-requests/${encodeURIComponent(item.id)}/demo-analysis`
        );
        if (epoch !== aiLoadEpoch || state.clinicalPatient?.id !== item.patient_id) return;
        const analysis = result.analysis;
        const heading = document.createElement("strong");
        heading.textContent = `Сохранённый тестовый AI-анализ · ${formatDateTime(result.submitted_at)} · требуется проверка врача`;
        analysisOutput.append(heading);
        const summary = document.createElement("p");
        summary.textContent = analysis.summary;
        analysisOutput.append(summary);
        const provenance = document.createElement("small");
        provenance.textContent = `Пациент: ${item.patient_id} · Врач: ${item.doctor_id} · запрос: ${item.id}`;
        analysisOutput.append(provenance);
        const section = (label, entries) => {
          if (!Array.isArray(entries) || !entries.length) return;
          const head = document.createElement("strong");
          head.textContent = label;
          const list = document.createElement("ul");
          for (const entry of entries) {
            const li = document.createElement("li");
            li.textContent = typeof entry === "string"
              ? entry : Object.values(entry).filter(Boolean).join(" — ");
            list.append(li);
          }
          analysisOutput.append(head, list);
        };
        section("Диагностические гипотезы", analysis.hypotheses);
        section("Лекарственные риски", analysis.medication_risks);
        section("Недостающие сведения", analysis.missing_information);
        section("Предлагаемые обследования", analysis.suggested_examinations);
        section("Источники (проверить самостоятельно)", analysis.sources);
        section("Ограничения анализа", analysis.limitations);
        $("ai-response").replaceChildren(analysisOutput.cloneNode(true));
      } catch (error) {
        if (epoch === aiLoadEpoch && state.clinicalPatient?.id === item.patient_id) {
          analysisOutput.textContent = error.status === 404
            ? "Для этого запроса пока нет сохранённого AI-ответа."
            : `Не удалось получить AI-ответ: ${error.message}`;
        }
      } finally {
        analysisButton.disabled = false;
      }
    });
    detail.append(analysisButton, analysisOutput);
    if (syntheticReviewEnabled) {
      const open = document.createElement("button");
      open.type = "button";
      open.className = "button subtle";
      open.textContent = "Проверить предложения";
      open.addEventListener("click", () => openAIReview(item.id));
      row.append(open);
    }
    row.append(detail);
    target.append(row);
  }
}

$("clinical-open-ai").addEventListener("click", () => {
  $("doctor-ai-column").scrollIntoView({behavior:"smooth",block:"start"});
});
$("ai-question").addEventListener("input", () => { aiPendingKey = null; });
$("ai-refresh-files").addEventListener("click", () => loadAIForPatient());
$("ai-upload-button").addEventListener("click", async () => {
  const file = $("ai-upload").files[0];
  const patientId = $("ai-patient-select").value;
  if (!file || !patientId || state.user?.role !== "doctor") {
    showMessage("ai-workspace-status", "Выберите пациента и файл.");
    return;
  }
  const button = $("ai-upload-button");
  button.disabled = true;
  try {
    const data = new FormData();
    data.append("file", file);
    await api(`/patients/${encodeURIComponent(patientId)}/attachments`, {
      method: "POST", body: data,
    });
    if (state.user?.role === "doctor" && state.clinicalPatient?.id === patientId) {
      $("ai-upload").value = "";
      await loadAIForPatient();
      if (state.clinicalPatient?.id === patientId)
        showMessage("ai-workspace-status", "Документ сохранён. Для AI-контекста содержимое требует отдельной проверки.", true);
    }
  } catch (error) {
    if (state.clinicalPatient?.id === patientId)
      showMessage("ai-workspace-status", `Ошибка вложения: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});

$("ai-request-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const patientId = $("ai-patient-select").value;
  if (!patientId || state.user?.role !== "doctor") return;
  const question = $("ai-question").value.trim();
  if (question.length < 10) {
    showMessage("ai-workspace-status", "Напишите вопрос длиной не менее 10 символов.");
    return;
  }
  const attachment_ids = [...document.querySelectorAll(".ai-attachment-choice:checked")]
    .map((node) => node.value);
  if (attachment_ids.length > 10) {
    showMessage("ai-workspace-status", "Можно выбрать не более десяти файлов.");
    return;
  }
  if (!aiPendingKey) aiPendingKey = crypto.randomUUID();
  const button = $("ai-prepare");
  button.disabled = true;
  try {
    const result = await api(`/patients/${encodeURIComponent(patientId)}/ai-requests`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_key: aiPendingKey, question, attachment_ids }),
    });
    if (state.user?.role === "doctor" && $("ai-patient-select").value === patientId) {
      aiPendingKey = null;
      await loadAIForPatient();
      showMessage("ai-workspace-status",
        `Запрос ${result.id} сохранён с контекстом пациента. Для получения анализа используйте подключённого агента.`, true);
    }
  } catch (error) {
    if (state.clinicalPatient?.id === patientId)
      showMessage("ai-workspace-status", `Не удалось сохранить запрос: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});


// Врачебная проверка сохранённых структурированных предложений.
let reviewRequestId = null;
let reviewDraft = null;
let reviewPreview = null;
let reviewSelections = null;
let reviewEpoch = 0;

function clearAIReview() {
  reviewEpoch++;
  reviewRequestId = null;
  reviewDraft = null;
  reviewPreview = null;
  reviewSelections = null;
  $("ai-proposal-cards").replaceChildren();
  $("ai-review-preview-result").replaceChildren();
  $("ai-review-request-label").textContent = "Выберите подготовленный запрос в истории ниже.";
  $("ai-edit-reason").value = "";
  $("ai-clinician-order-details").hidden = true;
  $("ai-clinician-order-form").reset();
  for (const id of ["ai-demo-create", "ai-draft-revise", "ai-review-reject",
                    "ai-review-preview", "ai-review-approve"]) $(id).disabled = true;
  showMessage("ai-review-status", "");
}

function reviewPath(suffix = "") {
  return `/patients/${encodeURIComponent($("ai-patient-select").value)}` +
    `/ai-requests/${encodeURIComponent(reviewRequestId)}/review${suffix}`;
}


const reviewFieldLabels = {
  name: "Название", active_ingredient: "Действующее вещество",
  dosage_form: "Форма", strength: "Содержание / концентрация",
  dose_value: "Разовая доза", dose_unit: "Единица дозы",
  route: "Способ приёма", frequency_per_day: "Приёмов в сутки",
  times_local: "Время приёма (ЧЧ:ММ, через запятую)",
  timezone: "Часовой пояс IANA", start_date: "Дата начала",
  duration_days: "Длительность (дней)", administration_notes: "Условия приёма",
  examination_details: "Описание обследования", indication: "Показание",
  contraindications: "Ограничения / противопоказания",
  rationale: "Обоснование", source_reference: "Источник",
};

function readEditedOrder(card, original) {
  const data = structuredClone(original);
  for (const input of card.querySelectorAll("[data-order-field]")) {
    const name = input.dataset.orderField;
    const text = input.value.trim();
    if (name === "times_local") data[name] = text ? text.split(",").map(x => x.trim()) : null;
    else if (["dose_value", "frequency_per_day", "duration_days"].includes(name))
      data[name] = text ? text : null;
    else data[name] = text || null;
  }
  return data;
}

function readEditedHistory(card, original) {
  const history = structuredClone(original);
  for (const input of card.querySelectorAll("[data-fact-field]")) {
    history.fact[input.dataset.factField] = input.value.trim();
  }
  return history;
}

function readEditedObservation(card, original) {
  const observation = structuredClone(original);
  const code = card.querySelector("[data-observation-code]");
  const value = card.querySelector("[data-observation-value]");
  if (code) observation.code = code.value.trim();
  if (value) observation.value = JSON.parse(value.value);
  return observation;
}

function collectAISelections() {
  const selected = [];
  for (const item of reviewDraft.proposals) {
    const card = [...$("ai-proposal-cards").querySelectorAll("[data-proposal-id]")]
      .find(x => x.dataset.proposalId === item.id);
    if (!card?.querySelector(".ai-select-proposal").checked) continue;
    const entry = {proposal_id: item.id};
    if (item.order) entry.order = readEditedOrder(card, item.order);
    if (item.history) entry.history = readEditedHistory(card, item.history);
    if (item.observation) entry.observation = readEditedObservation(card, item.observation);
    selected.push(entry);
  }
  if (!selected.length) throw new Error("Выберите хотя бы одно предложение.");
  return {expected_version: reviewDraft.version, selections: selected,
          edit_reason: $("ai-edit-reason").value.trim() || null};
}

function invalidateAIReviewPreview() {
  reviewPreview = null;
  reviewSelections = null;
  $("ai-review-approve").disabled = true;
  $("ai-review-preview-result").replaceChildren();
}

function renderReviewDraft() {
  invalidateAIReviewPreview();
  const target = $("ai-proposal-cards");
  target.replaceChildren();
  const reviewStatuses = {
    open: "На рассмотрении", approved: "Утверждено",
    rejected: "Отклонено", historical: "Предыдущая версия",
  };
  $("ai-review-request-label").textContent = reviewDraft
    ? `Версия предложения: ${reviewDraft.version} · ${reviewStatuses[reviewDraft.status] || "Не рассмотрено"}`
    : "Для выбранного запроса пока нет предложений.";
  $("ai-demo-create").disabled = !syntheticReviewEnabled || !reviewRequestId || Boolean(reviewDraft);
  const editing = reviewDraft?.status === "open";
  for (const id of ["ai-review-reject", "ai-review-preview"]) $(id).disabled = !editing;
  $("ai-draft-revise").hidden = reviewDraft?.origin !== "synthetic_manual_test";
  $("ai-draft-revise").disabled = !editing || reviewDraft?.origin !== "synthetic_manual_test";
  $("ai-clinician-order-details").hidden = !editing || reviewDraft?.origin !== "site_builder_analysis_v1";
  if (!reviewDraft) return;
  const history = document.createElement("div");
  history.className = "actions";
  for (const version of reviewDraft.versions_available) {
    if (version === reviewDraft.version && reviewDraft.status !== "historical") continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button subtle";
    button.textContent = `Просмотреть версию ${version}`;
    button.addEventListener("click", async () => {
      const selectedRequest = reviewRequestId;
      const epoch = ++reviewEpoch;
      try {
        const record = await api(reviewPath(`/versions/${version}`));
        if (epoch !== reviewEpoch || selectedRequest !== reviewRequestId) return;
        reviewDraft = record;
        renderReviewDraft();
        showMessage("ai-review-status", "Историческая версия: только чтение.", true);
      } catch(error) {
        showMessage("ai-review-status", error.message);
      }
    });
    history.append(button);
  }
  if (reviewDraft.status === "historical") {
    const back = document.createElement("button");
    back.type = "button";
    back.className = "button subtle";
    back.textContent = "Вернуться к актуальной версии";
    back.addEventListener("click", () => openAIReview(reviewRequestId));
    history.append(back);
  }
  target.append(history);
  if (reviewDraft.approved_result) {
    const summary = document.createElement("p");
    summary.textContent = `Подтверждено: ${reviewDraft.approved_result.records.length} записей. ` +
      "Каждая запись доступна в соответствующем разделе карты пациента.";
    target.append(summary);
  }
  for (const proposal of reviewDraft.proposals) {
    const card = document.createElement("div");
    card.className = "ai-proposal-entry";
    card.dataset.proposalId = proposal.id;
    const label = document.createElement("label");
    const choice = document.createElement("input");
    choice.type = "checkbox";
    choice.className = "ai-select-proposal";
    choice.disabled = !editing;
    const kindTitles = {
      demo_test: "Тест", medication: "Препарат", examination: "Обследование",
      history_event: "Клиническая заметка", observation: "Наблюдение",
    };
    const proposalTitle = proposal.order?.name || proposal.test_id ||
      proposal.history?.fact?.title || proposal.history?.fact?.medication ||
      proposal.observation?.code || "Предложение";
    label.append(choice, document.createTextNode(
      ` Принять: ${proposalTitle} · ${kindTitles[proposal.kind] || proposal.kind}`
    ));
    if (proposal.source_locator) {
      const provenance = document.createElement("small");
      provenance.className = "clinical-hint";
      provenance.textContent = proposal.evidence_status === "clinician_added"
        ? "Источник: вручную добавленное врачом предложение, не из AI."
        : `Источник: сохранённый AI-анализ, ${proposal.source_locator}. До проверки врача не является клиническим фактом.`;
      card.append(provenance);
    }
    card.append(label);
    if (proposal.alternative_group) {
      const small = document.createElement("p");
      small.className = "clinical-hint";
      small.textContent = `Альтернатива (группа ${proposal.alternative_group}) — совместный выбор запрещён.`;
      card.append(small);
    }
    if (proposal.order) {
      const details = document.createElement("details");
      details.open = false;
      const summary = document.createElement("summary");
      summary.textContent = "Просмотр и изменение всех полей";
      details.append(summary);
      const fields = document.createElement("div");
      fields.className = "ai-proposal-fields";
      for (const [name, caption] of Object.entries(reviewFieldLabels)) {
        if (proposal.kind === "examination" &&
            ["active_ingredient","dosage_form","strength","dose_value","dose_unit","route",
             "frequency_per_day","times_local","timezone","duration_days",
             "administration_notes","contraindications"].includes(name)) continue;
        if (proposal.kind === "medication" && name === "examination_details") continue;
        const field = document.createElement("label");
        field.textContent = caption;
        const input = document.createElement("input");
        input.dataset.orderField = name;
        input.value = Array.isArray(proposal.order[name])
          ? proposal.order[name].join(", ") : (proposal.order[name] ?? "");
        input.disabled = !editing || (name === "source_reference" &&
          reviewDraft.origin === "site_builder_analysis_v1");
        field.append(input);
        fields.append(field);
      }
      details.append(fields);
      card.append(details);
    } else if (proposal.history) {
      const details = document.createElement("details");
      details.open = false;
      const summary = document.createElement("summary");
      summary.textContent = "Сведения и редактирование врачом";
      details.append(summary);
      const fields = document.createElement("div");
      fields.className = "ai-proposal-fields";
      for (const [key, value] of Object.entries(proposal.history.fact)) {
        const field = document.createElement("label");
        field.textContent = key;
        const input = document.createElement(typeof value === "string" && value.length > 100 ?
          "textarea" : "input");
        if (typeof value === "string" && !["classification","confidence","severity"].includes(key)) {
          input.dataset.factField = key;
        } else {
          input.disabled = true;
        }
        input.value = String(value);
        input.disabled ||= !editing;
        field.append(input);
        fields.append(field);
      }
      details.append(fields);
      card.append(details);
    } else if (proposal.observation) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Показатель и значение";
      details.append(summary);
      const code = document.createElement("input");
      code.dataset.observationCode = "";
      code.value = proposal.observation.code;
      code.disabled = !editing;
      const value = document.createElement("textarea");
      value.dataset.observationValue = "";
      value.value = JSON.stringify(proposal.observation.value, null, 2);
      value.disabled = !editing;
      details.append(code, value);
      card.append(details);
    } else {
      const note = document.createElement("small");
      note.textContent = "Опросник из каталога тестов.";
      card.append(note);
    }
    card.addEventListener("input", invalidateAIReviewPreview);
    card.addEventListener("change", invalidateAIReviewPreview);
    target.append(card);
  }
}

async function openAIReview(requestId) {
  // Очистка предыдущего запроса исключает показ старых предложений во время загрузки.
  clearAIReview();
  reviewRequestId = requestId;
  const epoch = ++reviewEpoch;
  showMessage("ai-review-status", "Загрузка предложений на проверку…");
  try {
    const data = await api(reviewPath());
    if (epoch !== reviewEpoch) return;
    reviewDraft = data;
    showMessage("ai-review-status", data.origin === "site_builder_analysis_v1"
      ? "Предложения связаны с сохранённым AI-ответом. Врач должен проверить каждый пункт."
      : "Загружен ранее созданный ручной тестовый черновик.", true);
  } catch (error) {
    if (epoch !== reviewEpoch) return;
    if (error.status !== 404) showMessage("ai-review-status", error.message);
    else showMessage("ai-review-status", "Предложений пока нет. Можно сформировать их из сохранённого AI-анализа.");
  }
  if (epoch === reviewEpoch) renderReviewDraft();
}

$("ai-demo-create").addEventListener("click", async () => {
  if (!syntheticReviewEnabled || !reviewRequestId) return;
  const requestId = reviewRequestId;
  const patientId = $("ai-patient-select").value;
  const epoch = reviewEpoch;
  const button = $("ai-demo-create");
  button.disabled = true;
  try {
    const data = await api(reviewPath("/from-analysis"), {method:"POST"});
    if (epoch !== reviewEpoch || reviewRequestId !== requestId ||
        patientId !== $("ai-patient-select").value) return;
    reviewDraft = data;
    renderReviewDraft();
    showMessage("ai-review-status",
      "Предложения извлечены из сохранённого AI-ответа. Дозировок в действующем формате ответа нет.", true);
  } catch (error) {
    if (epoch === reviewEpoch) showMessage("ai-review-status", error.message);
  } finally {
    if (epoch === reviewEpoch) button.disabled = Boolean(reviewDraft);
  }
});

$("ai-clinician-order-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (reviewDraft?.status !== "open" ||
      reviewDraft.origin !== "site_builder_analysis_v1") return;
  const requestId = reviewRequestId;
  const epoch = reviewEpoch;
  const form = event.currentTarget;
  const fields = new FormData(form);
  const text = (name) => String(fields.get(name) || "").trim();
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const order = {
      request_key: crypto.randomUUID(),
      kind: "medication",
      name: text("name"), active_ingredient: text("active_ingredient"),
      dosage_form: text("dosage_form"), strength: text("strength"),
      dose_value: text("dose_value"), dose_unit: text("dose_unit"),
      route: text("route"), frequency_per_day: Number(text("frequency_per_day")),
      times_local: text("times_local").split(",").map(x => x.trim()),
      timezone: text("timezone"), start_date: text("start_date"),
      duration_days: Number(text("duration_days")),
      administration_notes: text("administration_notes") || null,
      indication: text("indication"), contraindications: text("contraindications") || null,
      rationale: text("rationale"), source_reference: text("source_reference"),
    };
    const result = await api(reviewPath("/clinician-medication"), {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({expected_version:reviewDraft.version, order}),
    });
    if (epoch !== reviewEpoch || requestId !== reviewRequestId) return;
    reviewDraft = result;
    form.reset();
    renderReviewDraft();
    showMessage("ai-review-status",
      "Врачебное лекарственное предложение добавлено. Оно не является ответом AI и ещё не назначено.", true);
  } catch (error) {
    if (epoch === reviewEpoch) showMessage("ai-review-status", error.message);
  } finally {
    button.disabled = false;
  }
});

$("ai-draft-revise").addEventListener("click", async () => {
  if (reviewDraft?.status !== "open" ||
      reviewDraft.origin !== "synthetic_manual_test") return;
  try {
    const proposals = reviewDraft.proposals.map(item => {
      const card = [...$("ai-proposal-cards").querySelectorAll("[data-proposal-id]")]
        .find(x => x.dataset.proposalId === item.id);
      if (item.order) return {...item, order: readEditedOrder(card, item.order)};
      if (item.history) return {...item, history: readEditedHistory(card, item.history)};
      if (item.observation) return {...item, observation: readEditedObservation(card, item.observation)};
      return item;
    });
    const data = await api(reviewPath(), {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        origin:"synthetic_manual_test", expected_version:reviewDraft.version, proposals,
      }),
    });
    reviewDraft = data;
    renderReviewDraft();
    showMessage("ai-review-status", `Создана неизменяемая версия ${data.version}.`, true);
  } catch (error) {showMessage("ai-review-status", error.message);}
});

$("ai-review-preview").addEventListener("click", async () => {
  const epoch = reviewEpoch;
  const requestId = reviewRequestId;
  const patientId = $("ai-patient-select").value;
  try {
    const selection = collectAISelections();
    const data = await api(reviewPath("/preview"), {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify(selection),
    });
    if (epoch !== reviewEpoch || requestId !== reviewRequestId ||
        patientId !== $("ai-patient-select").value) return;
    reviewSelections = selection;
    reviewPreview = data;
    const output = $("ai-review-preview-result");
    output.replaceChildren();
    const title = document.createElement("h3");
    title.textContent = `Проверьте выбранные изменения (${data.changes.length})`;
    output.append(title);
    const explanation = document.createElement("p");
    explanation.className = "clinical-hint";
    explanation.textContent =
      "После подтверждения изменится только выбранное. " +
      "Неотмеченные предложения останутся в журнале без изменений карты.";
    output.append(explanation);
    for (const change of data.changes) {
      const section = document.createElement("section");
      section.className = "ai-preview-item";
      const heading = document.createElement("h4");
      const label = {
        questionnaire_assignments: "Тест", clinical_orders: "Назначение",
        history_events: "Клиническая заметка", medical_observations: "Наблюдение",
      }[change.table] || "Изменение";
      heading.textContent = `${label}: ${change.final?.name ||
        change.final?.fact?.title || change.final?.fact?.medication ||
        change.final?.code || change.final?.test_id || ""}`;
      section.append(heading);
      const status = document.createElement("p");
      status.className = "clinical-hint";
      status.textContent = change.edited
        ? "Врач внёс изменения. Изменённые поля отмечены."
        : "Без изменений по сравнению с исходным предложением.";
      section.append(status);

      const proposed = document.createElement("details");
      const proposedTitle = document.createElement("summary");
      proposedTitle.textContent = "Что было предложено";
      proposed.append(proposedTitle, renderClinicalPreviewFields(change.original));
      section.append(proposed);

      const finalTitle = document.createElement("h5");
      finalTitle.textContent = "Состояние после подтверждения";
      section.append(finalTitle, renderClinicalPreviewFields(change.final, change.original));
      output.append(section);
    }
    $("ai-review-approve").disabled = false;
    showMessage("ai-review-status", "Проверьте источник, исходные и изменённые поля каждого пункта.", true);
  } catch (error) {
    if (epoch !== reviewEpoch) return;
    invalidateAIReviewPreview();
    showMessage("ai-review-status", error.message);
  }
});

$("ai-review-approve").addEventListener("click", async () => {
  if (!reviewPreview || !reviewSelections) return;
  const epoch = reviewEpoch;
  const requestId = reviewRequestId;
  const patientId = $("ai-patient-select").value;
  if (!window.confirm("Подтвердить выбранные записи? Одобренные назначения будут доступны пациенту.")) return;
  $("ai-review-approve").disabled = true;
  try {
    const result = await api(reviewPath("/approve"), {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        ...reviewSelections, preview_sha256: reviewPreview.preview_sha256,
        confirm_patient_visibility:true, confirm_clinical_review:true,
      }),
    });
    if (epoch !== reviewEpoch || requestId !== reviewRequestId ||
        patientId !== $("ai-patient-select").value) return;
    showMessage("ai-review-status",
      `Применено записей: ${result.records.length}. Назначения и тесты доступны в соответствующих разделах.`, true);
    await loadClinical();
    if (requestId === reviewRequestId && patientId === $("ai-patient-select").value) {
      await openAIReview(requestId);
    }
  } catch (error) {
    if (epoch === reviewEpoch) showMessage("ai-review-status", error.message);
  }
});

$("ai-review-reject").addEventListener("click", async () => {
  if (reviewDraft?.status !== "open") return;
  const epoch = reviewEpoch;
  const requestId = reviewRequestId;
  const patientId = $("ai-patient-select").value;
  const reason = window.prompt("Причина отклонения предложений:");
  if (reason === null) return;
  const button = $("ai-review-reject");
  button.disabled = true;
  try {
    const data = await api(reviewPath("/reject"), {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({expected_version:reviewDraft.version, reason}),
    });
    if (epoch !== reviewEpoch || requestId !== reviewRequestId ||
        patientId !== $("ai-patient-select").value) return;
    reviewDraft = data;
    renderReviewDraft();
    showMessage("ai-review-status", "Предложения отклонены. Медицинская карта не изменена.", true);
  } catch (error) {
    if (epoch === reviewEpoch && patientId === $("ai-patient-select").value)
      showMessage("ai-review-status", error.message);
  } finally {
    if (epoch === reviewEpoch) button.disabled = reviewDraft?.status !== "open";
  }
});
