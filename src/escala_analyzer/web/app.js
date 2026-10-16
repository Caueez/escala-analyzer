'use strict';

const MONTH_NAMES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
];
const MONTH_SHORT = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
const WEEKDAY_SHORT = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
const WEEKDAY_LONG = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo'];
const PROFILE_PRESETS = {
  baseline: {
    label: 'Referência base — revisar conforme a legislação e a convenção aplicáveis',
    weekly_max_hours: 44,
    min_rest_days_in_rolling_7: 1,
    max_consecutive_work_days: 6,
    explainer: 'Referência de cálculo para comparação. Os parâmetros não substituem a conferência da legislação vigente nem do instrumento coletivo da categoria.'
  },
  transition: {
    label: 'Cenário de transição proposto — pendente de confirmação de vigência',
    weekly_max_hours: 42,
    min_rest_days_in_rolling_7: 2,
    max_consecutive_work_days: 5,
    explainer: 'Cenário hipotético de 42 horas semanais e dois dias de descanso em sete dias corridos. Use-o para planejamento, não como declaração de que a regra já está em vigor.'
  },
  target: {
    label: 'Meta proposta — pendente de confirmação de vigência',
    weekly_max_hours: 40,
    min_rest_days_in_rolling_7: 2,
    max_consecutive_work_days: 5,
    explainer: 'Cenário hipotético de 40 horas semanais e dois dias de descanso em sete dias corridos. A forma de aplicar o texto final deve ser validada com o RH e a assessoria jurídica.'
  }
};

let project = null;
let analysis = null;
let currentView = 'timeline';
let draggedCell = null;
let suppressClickUntil = 0;
let analysisFilter = 'all';
let toastTimeouts = new Set();

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

function localDate(year, monthIndex, day) {
  return new Date(year, monthIndex, day, 12, 0, 0, 0);
}

function toIsoDate(year, monthIndex, day) {
  return `${year}-${String(monthIndex + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function parseIsoLocal(value) {
  const [year, month, day] = value.split('-').map(Number);
  return localDate(year, month - 1, day);
}

function weekdayIndexMondayFirst(date) {
  return (date.getDay() + 6) % 7;
}

function daysInMonth(year, monthIndex) {
  return new Date(year, monthIndex + 1, 0).getDate();
}

function groupByShift(shiftId) {
  return project.groups.filter((group) => group.shift_id === shiftId);
}

function shiftFor(group) {
  return project.shifts.find((shift) => shift.id === group.shift_id);
}

function baseStatus(group, isoDate) {
  const target = parseIsoLocal(isoDate);
  const anchor = parseIsoLocal(group.cycle_anchor);
  const deltaDays = Math.round((target.getTime() - anchor.getTime()) / 86400000);
  const cycleLength = Number(group.work_days) + Number(group.rest_days);
  const position = ((deltaDays % cycleLength) + cycleLength) % cycleLength;
  return position < Number(group.work_days);
}

function statusFor(group, isoDate) {
  if (Object.prototype.hasOwnProperty.call(group.overrides || {}, isoDate)) {
    return Boolean(group.overrides[isoDate]);
  }
  return baseStatus(group, isoDate);
}

function setStatus(group, isoDate, isWorking) {
  if (!group.overrides) group.overrides = {};
  if (Boolean(isWorking) === baseStatus(group, isoDate)) {
    delete group.overrides[isoDate];
  } else {
    group.overrides[isoDate] = Boolean(isWorking);
  }
}

function setSaveState(message, type = 'normal') {
  $('#saveState').textContent = message;
  const dot = $('.state-dot');
  dot.classList.toggle('saving', type === 'saving');
  dot.classList.toggle('error', type === 'error');
}

function notify(message, type = 'success', duration = 3400) {
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = message;
  $('#toastRegion').appendChild(node);
  const timer = window.setTimeout(() => {
    node.remove();
    toastTimeouts.delete(timer);
  }, duration);
  toastTimeouts.add(timer);
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `Erro HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body);
    } catch (_) { /* Keep the HTTP status as the error message. */ }
    throw new Error(message);
  }
  return response.json();
}

async function saveProject({ refresh = true, successMessage = null } = {}) {
  if (!project) return;
  setSaveState('Salvando…', 'saving');
  try {
    project = await apiRequest('/api/project', { method: 'PUT', body: JSON.stringify(project) });
    setSaveState('Salvo localmente');
    $('#sidebarProjectName').textContent = project.name;
    if (refresh) await recalculate({ renderTimeline: true, renderAnalysis: currentView === 'analysis' });
    if (successMessage) notify(successMessage);
  } catch (error) {
    setSaveState('Falha ao salvar', 'error');
    notify(`Não foi possível salvar: ${error.message}`, 'error', 6000);
    throw error;
  }
}

async function recalculate({ renderTimeline = false, renderAnalysis = true } = {}) {
  if (!project) return;
  try {
    analysis = await apiRequest('/api/analyze', { method: 'POST', body: JSON.stringify(project) });
    renderStats();
    if (renderTimeline) renderTimelineView();
    if (renderAnalysis) renderAnalysisView();
  } catch (error) {
    notify(`Falha ao analisar o projeto: ${error.message}`, 'error', 6000);
  }
}

async function loadProject() {
  setSaveState('Carregando…', 'saving');
  try {
    project = await apiRequest('/api/project');
    $('#sidebarProjectName').textContent = project.name;
    $('#projectName').value = project.name;
    fillMonthSelect();
    await recalculate({ renderTimeline: true, renderAnalysis: true });
    setSaveState('Salvo localmente');
  } catch (error) {
    setSaveState('Falha ao carregar', 'error');
    $('#timelineContainer').innerHTML = `<div class="empty-state">Não foi possível carregar o projeto.<br><br>${escapeHtml(error.message)}</div>`;
    notify(`Falha ao abrir o projeto: ${error.message}`, 'error', 8000);
  }
}

function renderStats() {
  if (!project || !analysis) return;
  $('#statPeople').textContent = Number(analysis.people_total).toLocaleString('pt-BR');
  $('#statGroups').textContent = Number(analysis.group_count).toLocaleString('pt-BR');
  const month = Number(project.selected_month || 1);
  const monthSummary = analysis.monthly_summary[month - 1];
  $('#statDeficitDays').textContent = monthSummary ? monthSummary.coverage_gap_count.toLocaleString('pt-BR') : '0';
  $('#statDeficitFoot').textContent = 'Combinações turno/dia abaixo da demanda';
  $('#statWorstDeficit').textContent = monthSummary ? monthSummary.worst_single_shift_deficit.toLocaleString('pt-BR') : '0';
  $('#yearLabel').textContent = project.year;
  $('#sidebarProjectName').textContent = project.name;
}

function fillMonthSelect() {
  const select = $('#monthSelect');
  select.innerHTML = MONTH_NAMES.map((name, index) => `<option value="${index + 1}">${name}</option>`).join('');
  select.value = String(project.selected_month || 1);
  $('#yearLabel').textContent = project.year;
}

function renderTimelineView() {
  if (!project || !analysis) return;
  const container = $('#timelineContainer');
  const oldScrollLeft = container.scrollLeft;
  const oldScrollTop = container.scrollTop;
  const monthIndex = Number(project.selected_month) - 1;
  const year = Number(project.year);
  const dayCount = daysInMonth(year, monthIndex);
  const firstDate = localDate(year, monthIndex, 1);
  const lastDate = localDate(year, monthIndex, dayCount);
  const selectedMonth = MONTH_NAMES[monthIndex];

  if (project.shifts.length === 0) {
    container.innerHTML = '<div class="empty-state">Nenhum turno cadastrado. Abra Configurações e adicione um turno para começar.</div>';
  } else {
    const sections = project.shifts.map((shift, shiftIndex) => {
      const groups = groupByShift(shift.id);
      const gridTemplate = `225px repeat(${dayCount}, 32px)`;
      const headLabel = `<div class="group-label-cell"><div class="group-label-main"><div class="group-name-label">Grupo / ciclo</div><div class="group-label-meta">Pessoas e padrão de repetição</div></div></div>`;
      const dayHeaders = Array.from({ length: dayCount }, (_, index) => {
        const dayNum = index + 1;
        const day = localDate(year, monthIndex, dayNum);
        const dayOfWeek = weekdayIndexMondayFirst(day);
        const iso = toIsoDate(year, monthIndex, dayNum);
        const isSunday = dayOfWeek === 6;
        const isToday = iso === toIsoDate(new Date().getFullYear(), new Date().getMonth(), new Date().getDate());
        return `<div class="timeline-day-head ${isSunday ? 'is-sunday' : ''} ${isToday ? 'is-today' : ''}" title="${WEEKDAY_LONG[dayOfWeek]}, ${dayNum} de ${selectedMonth.toLowerCase()} de ${year}"><span class="dow">${WEEKDAY_SHORT[dayOfWeek]}</span><span class="dom">${dayNum}</span></div>`;
      }).join('');
      const groupRows = groups.map((group, groupIndex) => {
        const overridesCount = Object.keys(group.overrides || {}).filter((dateText) => dateText.startsWith(`${year}-${String(monthIndex + 1).padStart(2, '0')}-`)).length;
        const metadata = `${group.employee_count} pessoas · ${group.work_days}T/${group.rest_days}F${overridesCount ? ` · ${overridesCount} ajuste(s)` : ''}`;
        const cells = Array.from({ length: dayCount }, (_, index) => {
          const dayNum = index + 1;
          const day = localDate(year, monthIndex, dayNum);
          const iso = toIsoDate(year, monthIndex, dayNum);
          const isWorking = statusFor(group, iso);
          const isOverride = Object.prototype.hasOwnProperty.call(group.overrides || {}, iso);
          const dow = weekdayIndexMondayFirst(day);
          const stateLabel = isWorking ? 'Trabalho' : 'Folga';
          const title = `${group.name} · ${dayNum}/${String(monthIndex + 1).padStart(2, '0')}/${year} · ${stateLabel}${isOverride ? ' · ajuste manual' : ''}`;
          return `<button class="timeline-cell ${isWorking ? 'work' : 'rest'} ${dow === 6 ? 'is-sunday' : ''} ${isOverride ? 'is-override' : ''}" data-group-id="${escapeHtml(group.id)}" data-date="${iso}" data-working="${isWorking}" draggable="${!isWorking}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"><span class="cell-mark">${isWorking ? 'TRAB' : 'FOLGA'}</span></button>`;
        }).join('');
        return `<div class="group-label-cell"><div class="group-label-main"><div class="group-name-label">${escapeHtml(group.name)}</div><div class="group-label-meta">${escapeHtml(metadata)}</div></div><div class="group-tools"><button type="button" data-action="edit-group" data-id="${escapeHtml(group.id)}" title="Editar grupo" aria-label="Editar ${escapeHtml(group.name)}">✎</button><button type="button" data-action="delete-group" data-id="${escapeHtml(group.id)}" title="Excluir grupo" aria-label="Excluir ${escapeHtml(group.name)}">×</button></div></div>${cells}`;
      }).join('');
      return `<section class="shift-section"><div class="shift-section-heading"><span class="shift-indicator"></span>${escapeHtml(shift.name)}<span class="shift-group-count">${groups.length} grupo(s) · ${groups.reduce((sum, item) => sum + Number(item.employee_count), 0)} pessoa(s) cadastradas</span></div><div class="timeline-grid" style="grid-template-columns:${gridTemplate}">${headLabel}${dayHeaders}${groupRows}</div></section>`;
    }).join('');
    container.innerHTML = sections;
  }

  $('#timelineRangeLabel').textContent = `${selectedMonth} de ${year} · ${dayCount} dias`;
  container.scrollLeft = oldScrollLeft;
  container.scrollTop = oldScrollTop;
  updateGroupShiftOptions();
}

function changeMonth(delta) {
  const next = Number(project.selected_month) + delta;
  if (next < 1) {
    if (project.year <= 2000) return notify('O ano mínimo do projeto é 2000.', 'error');
    project.selected_month = 12;
    project.year -= 1;
  } else if (next > 12) {
    if (project.year >= 2100) return notify('O ano máximo do projeto é 2100.', 'error');
    project.selected_month = 1;
    project.year += 1;
  } else {
    project.selected_month = next;
  }
  $('#monthSelect').value = String(project.selected_month);
  saveProject({ refresh: true });
}

function setView(viewName) {
  currentView = viewName;
  $$('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.view === viewName));
  $$('.view').forEach((view) => view.classList.toggle('active-view', view.id === `view-${viewName}`));
  const titles = { timeline: 'Linha do tempo', analysis: 'Análise anual', settings: 'Configurações' };
  $('#breadcrumbTitle').textContent = titles[viewName] || 'Linha do tempo';
  if (viewName === 'settings') fillSettingsForm();
  if (viewName === 'analysis') renderAnalysisView();
}

function openGroupDialog(group = null) {
  $('#groupDialog').hidden = false;
  $('#groupId').value = group?.id || '';
  $('#groupDialogTitle').textContent = group ? 'Editar grupo' : 'Novo grupo';
  $('#groupName').value = group?.name || `Grupo ${String.fromCharCode(65 + project.groups.length % 26)}`;
  $('#groupEmployees').value = group?.employee_count ?? 7;
  $('#groupWorkDays').value = group?.work_days ?? 3;
  $('#groupRestDays').value = group?.rest_days ?? 1;
  $('#groupAnchor').value = group?.cycle_anchor || `${project.year}-${String(project.selected_month).padStart(2, '0')}-01`;
  $('#deleteGroupButton').hidden = !group;
  updateGroupShiftOptions(group?.shift_id);
  if (!group && project.shifts.length === 0) {
    notify('Cadastre pelo menos um turno nas Configurações antes de criar um grupo.', 'error');
    closeModal('groupDialog');
    setView('settings');
    return;
  }
  updateCyclePreview();
  window.setTimeout(() => $('#groupName').focus(), 40);
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.hidden = true;
}

function updateGroupShiftOptions(selectedId = null) {
  const select = $('#groupShift');
  if (!select || !project) return;
  const current = selectedId || select.value || project.shifts[0]?.id;
  select.innerHTML = project.shifts.map((shift) => `<option value="${escapeHtml(shift.id)}">${escapeHtml(shift.name)}</option>`).join('');
  if (current && project.shifts.some((shift) => shift.id === current)) select.value = current;
}

function updateCyclePreview() {
  const workDays = Math.max(1, Math.min(31, Number($('#groupWorkDays').value) || 1));
  const restDays = Math.max(1, Math.min(31, Number($('#groupRestDays').value) || 1));
  const cycle = [...Array.from({ length: workDays }, () => ({ label: 'TRABALHO', className: 'work' })), ...Array.from({ length: restDays }, () => ({ label: 'FOLGA', className: 'rest' }))];
  const preview = cycle.slice(0, 16).map((item) => `<span class="cycle-chip ${item.className}">${item.label}</span>`).join('');
  $('#cyclePreview').innerHTML = `<div class="cycle-preview-title">Prévia do ciclo · ${workDays}x${restDays}</div><div class="cycle-preview-track">${preview}${cycle.length > 16 ? `<span class="cycle-chip">+${cycle.length - 16}</span>` : ''}</div>`;
}

function deleteGroup(groupId) {
  const group = project.groups.find((item) => item.id === groupId);
  if (!group) return;
  if (!window.confirm(`Excluir o ${group.name}? Os ajustes manuais deste grupo serão removidos.`)) return;
  project.groups = project.groups.filter((item) => item.id !== groupId);
  if ($('#groupId').value === groupId) closeModal('groupDialog');
  saveProject({ refresh: true, successMessage: 'Grupo excluído.' });
}

function fillSettingsForm() {
  if (!project) return;
  $('#projectName').value = project.name;
  $('#projectYear').value = project.year;
  $('#projectNotes').value = project.notes || '';
  $('#ruleProfile').value = project.rules.profile;
  $('#weeklyMaxHours').value = project.rules.weekly_max_hours;
  $('#minRestRolling').value = project.rules.min_rest_days_in_rolling_7;
  $('#minSundays').value = project.rules.min_sundays_off_per_month;
  $('#minMonthlyRest').value = project.rules.min_days_off_per_month;
  $('#checkMonthlyRest').checked = project.rules.check_min_days_off_per_month;
  $('#maxConsecutive').value = project.rules.max_consecutive_work_days;
  renderShiftSettings();
  updateProfileExplainer();
}

function updateProfileExplainer() {
  const profile = PROFILE_PRESETS[$('#ruleProfile').value] || PROFILE_PRESETS.transition;
  $('#profileExplainer').innerHTML = `<strong>${escapeHtml(profile.label)}.</strong> ${escapeHtml(profile.explainer)} Os valores podem ser alterados manualmente.`;
}

function renderShiftSettings() {
  const container = $('#shiftSettingsList');
  if (!project.shifts.length) {
    container.innerHTML = '<div class="empty-state">Nenhum turno cadastrado. Use “Adicionar turno” para começar.</div>';
    return;
  }
  container.innerHTML = project.shifts.map((shift) => `
    <article class="shift-config-card" data-shift-card="${escapeHtml(shift.id)}">
      <div class="shift-config-head"><div><strong>${escapeHtml(shift.name)}</strong><small>${groupByShift(shift.id).length} grupo(s) vinculados</small></div><button type="button" class="button button-quiet" data-action="rename-shift" data-id="${escapeHtml(shift.id)}">Renomear</button></div>
      <div class="shift-config-grid">
        <div class="field"><label for="shift-name-${escapeHtml(shift.id)}">Nome do turno</label><input id="shift-name-${escapeHtml(shift.id)}" data-shift-id="${escapeHtml(shift.id)}" data-field="name" value="${escapeHtml(shift.name)}" required></div>
        <div class="field"><label for="shift-hours-${escapeHtml(shift.id)}">Horas/dia</label><input id="shift-hours-${escapeHtml(shift.id)}" data-shift-id="${escapeHtml(shift.id)}" data-field="hours_per_day" type="number" min="0" max="24" step="0.25" value="${shift.hours_per_day}" required></div>
        ${WEEKDAY_SHORT.map((dayLabel, index) => `<div class="field"><label for="demand-${escapeHtml(shift.id)}-${index}">${dayLabel}</label><input id="demand-${escapeHtml(shift.id)}-${index}" data-shift-id="${escapeHtml(shift.id)}" data-field="demand" data-weekday="${index}" type="number" min="0" max="100000" step="1" value="${shift.demand_by_weekday[index]}" required></div>`).join('')}
      </div>
    </article>`).join('');
}

function applyProfilePreset() {
  const preset = PROFILE_PRESETS[$('#ruleProfile').value];
  if (!preset) return;
  $('#weeklyMaxHours').value = preset.weekly_max_hours;
  $('#minRestRolling').value = preset.min_rest_days_in_rolling_7;
  $('#maxConsecutive').value = preset.max_consecutive_work_days;
  updateProfileExplainer();
}

async function saveSettingsFromForm(event) {
  event?.preventDefault();
  if (!$('#settingsForm').reportValidity()) return;
  const year = Number($('#projectYear').value);
  if (!Number.isInteger(year) || year < 2000 || year > 2100) {
    notify('Informe um ano válido entre 2000 e 2100.', 'error');
    return;
  }
  project.name = $('#projectName').value.trim() || 'Projeto de escalas';
  project.year = year;
  project.notes = $('#projectNotes').value.trim();
  project.rules.profile = $('#ruleProfile').value;
  project.rules.profile_label = PROFILE_PRESETS[project.rules.profile].label;
  project.rules.weekly_max_hours = Number($('#weeklyMaxHours').value);
  project.rules.min_rest_days_in_rolling_7 = Number($('#minRestRolling').value);
  project.rules.min_sundays_off_per_month = Number($('#minSundays').value);
  project.rules.min_days_off_per_month = Number($('#minMonthlyRest').value);
  project.rules.check_min_days_off_per_month = $('#checkMonthlyRest').checked;
  project.rules.max_consecutive_work_days = Number($('#maxConsecutive').value);
  const shiftNodes = $$('.shift-config-card');
  for (const card of shiftNodes) {
    const shiftId = card.dataset.shiftCard;
    const shift = project.shifts.find((item) => item.id === shiftId);
    if (!shift) continue;
    const name = $(`[data-shift-id="${CSS.escape(shiftId)}"][data-field="name"]`, card).value.trim();
    const hours = Number($(`[data-shift-id="${CSS.escape(shiftId)}"][data-field="hours_per_day"]`, card).value);
    const demands = $$(`[data-shift-id="${CSS.escape(shiftId)}"][data-field="demand"]`, card).map((input) => Number(input.value));
    if (!name || !Number.isFinite(hours) || hours < 0 || hours > 24 || demands.length !== 7 || demands.some((value) => !Number.isInteger(value) || value < 0)) {
      notify(`Confira o nome, as horas e a demanda do turno ${shift.name}.`, 'error');
      return;
    }
    shift.name = name;
    shift.hours_per_day = hours;
    shift.demand_by_weekday = demands;
  }
  fillMonthSelect();
  $('#analysisYearHeading').textContent = project.year;
  await saveProject({ refresh: true, successMessage: 'Parâmetros salvos e análise recalculada.' });
  setView('timeline');
}

function renderAnalysisView() {
  if (!project || !analysis) return;
  $('#analysisYearHeading').textContent = analysis.year;
  $('#analysisDisclaimer').textContent = analysis.disclaimer;
  $('#profileTag').textContent = project.rules.profile_label || (PROFILE_PRESETS[project.rules.profile]?.label ?? 'Cenário configurado');
  const stats = [
    { label: 'Pessoas em grupos', value: analysis.people_total, detail: `${analysis.group_count} grupo(s) cadastrados`, alert: false },
    { label: 'Combinações com déficit', value: analysis.coverage_gap_count, detail: 'Turno/dia em que a escala fica abaixo da demanda', alert: analysis.coverage_gap_count > 0 },
    { label: 'Datas com algum déficit', value: analysis.days_with_any_coverage_gap, detail: `De ${analysis.days_in_year} dias do ano`, alert: analysis.days_with_any_coverage_gap > 0 },
    { label: 'Achados de regras', value: analysis.rule_issue_count, detail: 'Conforme os parâmetros atualmente marcados', alert: analysis.rule_issue_count > 0 },
  ];
  $('#analysisStats').innerHTML = stats.map((item) => `<article class="analysis-metric ${item.alert ? 'metric-alert' : ''}"><div class="metric-label">${escapeHtml(item.label)}</div><div class="metric-value">${Number(item.value).toLocaleString('pt-BR')}</div><div class="metric-detail">${escapeHtml(item.detail)}</div></article>`).join('');

  const tbody = $('#monthlyTable tbody');
  tbody.innerHTML = analysis.monthly_summary.map((month) => {
    const ruleCount = analysis.rule_issues.filter((issue) => issue.month === month.month).length;
    const hasCoverageGap = month.coverage_gap_count > 0;
    const hasRuleIssue = ruleCount > 0;
    const status = hasCoverageGap || hasRuleIssue
      ? `<span class="status-pill alert">● Revisar</span>`
      : '<span class="status-pill ok">● Sem alertas</span>';
    return `<tr><td>${escapeHtml(month.month_name)}</td><td>${month.coverage_gap_count.toLocaleString('pt-BR')}</td><td>${month.worst_single_shift_deficit.toLocaleString('pt-BR')}</td><td>${ruleCount.toLocaleString('pt-BR')}</td><td>${status}</td></tr>`;
  }).join('');
  renderIssues();
}

function renderIssues() {
  if (!analysis) return;
  let issues = analysis.issues.slice();
  if (analysisFilter === 'coverage') issues = issues.filter((item) => item.code === 'coverage-gap');
  if (analysisFilter === 'rules') issues = issues.filter((item) => item.code !== 'coverage-gap');
  issues.sort((left, right) => {
    const a = left.code === 'coverage-gap' ? 0 : 1;
    const b = right.code === 'coverage-gap' ? 0 : 1;
    if (a !== b) return a - b;
    const aDate = left.date || left.first_window_start || `${left.month || 1}`;
    const bDate = right.date || right.first_window_start || `${right.month || 1}`;
    return String(aDate).localeCompare(String(bDate)) || String(left.group_name || '').localeCompare(String(right.group_name || ''));
  });
  const displayedIssues = issues.slice(0, 120);
  const container = $('#issuesList');
  if (!displayedIssues.length) {
    container.innerHTML = '<div class="empty-state">Nenhum achado com esse filtro. Confira se os parâmetros do projeto representam as regras que precisam ser verificadas.</div>';
  } else {
    container.innerHTML = displayedIssues.map((issue) => {
      const isCoverage = issue.code === 'coverage-gap';
      let meta = '';
      if (issue.date) {
        const [year, month, day] = issue.date.split('-');
        meta = `${day}/${month}/${year}`;
      } else if (issue.month) {
        meta = MONTH_NAMES[issue.month - 1];
      }
      if (issue.windows_count) meta += ` · ${issue.windows_count} janela(s)`;
      if (issue.shift_name) meta += ` · ${issue.shift_name}`;
      if (issue.group_name) meta += ` · ${issue.group_name}`;
      return `<article class="issue-row ${isCoverage ? '' : 'rule-issue'}"><div class="issue-marker">${isCoverage ? '↓' : '!'}</div><div class="issue-main"><div class="issue-title">${escapeHtml(issue.title)}</div><div class="issue-message">${escapeHtml(issue.message)}</div><div class="issue-meta">${escapeHtml(meta)}</div></div></article>`;
    }).join('');
  }
  $('#issuesFooter').textContent = issues.length > displayedIssues.length
    ? `Mostrando ${displayedIssues.length} de ${issues.length} achados. Exporte o CSV e revise os filtros para examinar o ano completo.`
    : `${issues.length} achado(s) nesse filtro.`;
}

function exportJson() {
  const data = JSON.stringify(project, null, 2);
  const url = URL.createObjectURL(new Blob([data], { type: 'application/json;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `escala-visual-${project.year}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  notify('Backup JSON exportado.');
}

async function importJsonFile(file) {
  try {
    const parsed = JSON.parse(await file.text());
    project = await apiRequest('/api/project', { method: 'PUT', body: JSON.stringify(parsed) });
    fillMonthSelect();
    await recalculate({ renderTimeline: true, renderAnalysis: true });
    fillSettingsForm();
    setSaveState('Salvo localmente');
    notify('Projeto importado e salvo localmente.');
  } catch (error) {
    notify(`Não foi possível importar o projeto: ${error.message}`, 'error', 6000);
  } finally {
    $('#importJsonInput').value = '';
  }
}

async function resetProject() {
  if (!window.confirm('Restaurar o modelo demonstrativo? Isso substituirá o projeto salvo neste computador. Exporte um backup JSON antes, caso queira preservá-lo.')) return;
  try {
    project = await apiRequest('/api/project/reset', { method: 'POST', body: '{}' });
    fillMonthSelect();
    await recalculate({ renderTimeline: true, renderAnalysis: true });
    fillSettingsForm();
    setSaveState('Salvo localmente');
    setView('timeline');
    notify('Modelo demonstrativo restaurado.');
  } catch (error) {
    notify(`Falha ao restaurar: ${error.message}`, 'error');
  }
}

async function addShift() {
  const rawName = window.prompt('Nome do novo turno:', `Turno ${project.shifts.length + 1}`);
  if (rawName === null) return;
  const name = rawName.trim();
  if (!name) {
    notify('O nome do turno não pode ficar vazio.', 'error');
    return;
  }
  if (project.shifts.some((shift) => shift.name.toLocaleLowerCase('pt-BR') === name.toLocaleLowerCase('pt-BR'))) {
    notify('Já existe um turno com esse nome.', 'error');
    return;
  }
  const countRaw = window.prompt('Demanda inicial para cada dia da semana:', '0');
  if (countRaw === null) return;
  const demand = Number(countRaw);
  if (!Number.isInteger(demand) || demand < 0 || demand > 100000) {
    notify('Informe uma quantidade inteira válida.', 'error');
    return;
  }
  const id = `turno-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
  project.shifts.push({ id, name, hours_per_day: 8, demand_by_weekday: Array(7).fill(demand) });
  await saveProject({ refresh: true, successMessage: 'Turno adicionado.' });
  fillSettingsForm();
}

async function handleRenameShift(shiftId) {
  const shift = project.shifts.find((item) => item.id === shiftId);
  if (!shift) return;
  const proposed = window.prompt('Nome do turno:', shift.name);
  if (proposed === null) return;
  const name = proposed.trim();
  if (!name) return notify('O nome do turno não pode ficar vazio.', 'error');
  shift.name = name;
  await saveProject({ refresh: true, successMessage: 'Turno renomeado.' });
  fillSettingsForm();
}

function attachEvents() {
  $$('.nav-item').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
  $('#settingsButton').addEventListener('click', () => setView('settings'));
  $('#addGroupButton').addEventListener('click', () => openGroupDialog());
  $('#prevMonthButton').addEventListener('click', () => changeMonth(-1));
  $('#nextMonthButton').addEventListener('click', () => changeMonth(1));
  $('#monthSelect').addEventListener('change', () => {
    project.selected_month = Number($('#monthSelect').value);
    saveProject({ refresh: true });
  });
  $('#dismissDemoNotice').addEventListener('click', () => { $('#demoNotice').hidden = true; });
  $('#exportCsvButton').addEventListener('click', () => { window.location.href = '/api/export.csv'; });
  $('#analysisRefreshButton').addEventListener('click', () => recalculate({ renderTimeline: false, renderAnalysis: true }));
  $('#saveSettingsButton').addEventListener('click', saveSettingsFromForm);
  $('#settingsForm').addEventListener('submit', saveSettingsFromForm);
  $('#ruleProfile').addEventListener('change', applyProfilePreset);
  $('#addShiftButton').addEventListener('click', addShift);
  $('#exportJsonButton').addEventListener('click', exportJson);
  $('#importJsonInput').addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    if (file) importJsonFile(file);
  });
  $('#resetProjectButton').addEventListener('click', resetProject);
  $('#issueFilter').addEventListener('change', (event) => {
    analysisFilter = event.target.value;
    renderIssues();
  });
  $('#groupForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const groupId = $('#groupId').value;
    const groupData = {
      id: groupId || `grupo-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`,
      name: $('#groupName').value.trim(),
      shift_id: $('#groupShift').value,
      employee_count: Number($('#groupEmployees').value),
      work_days: Number($('#groupWorkDays').value),
      rest_days: Number($('#groupRestDays').value),
      cycle_anchor: $('#groupAnchor').value,
      overrides: {},
    };
    const existing = project.groups.find((group) => group.id === groupId);
    if (existing) {
      groupData.overrides = existing.overrides || {};
      Object.assign(existing, groupData);
    } else {
      project.groups.push(groupData);
    }
    closeModal('groupDialog');
    await saveProject({ refresh: true, successMessage: existing ? 'Grupo atualizado.' : 'Grupo criado.' });
  });
  $('#deleteGroupButton').addEventListener('click', () => deleteGroup($('#groupId').value));
  ['groupWorkDays', 'groupRestDays'].forEach((id) => $(`#${id}`).addEventListener('input', updateCyclePreview));
  $$('[data-close-modal]').forEach((button) => button.addEventListener('click', () => closeModal(button.dataset.closeModal)));
  $$('.modal-backdrop').forEach((backdrop) => backdrop.addEventListener('click', (event) => {
    if (event.target === backdrop) closeModal(backdrop.id);
  }));

  $('#timelineContainer').addEventListener('click', async (event) => {
    if (Date.now() < suppressClickUntil) return;
    const actionButton = event.target.closest('[data-action]');
    if (actionButton) {
      const { action, id } = actionButton.dataset;
      if (action === 'edit-group') openGroupDialog(project.groups.find((group) => group.id === id));
      if (action === 'delete-group') deleteGroup(id);
      return;
    }
    const cell = event.target.closest('.timeline-cell');
    if (!cell) return;
    const group = project.groups.find((item) => item.id === cell.dataset.groupId);
    if (!group) return;
    const iso = cell.dataset.date;
    setStatus(group, iso, !statusFor(group, iso));
    await saveProject({ refresh: true });
  });

  $('#timelineContainer').addEventListener('dragstart', (event) => {
    const cell = event.target.closest('.timeline-cell');
    if (!cell || statusFor(project.groups.find((group) => group.id === cell.dataset.groupId), cell.dataset.date)) {
      event.preventDefault();
      return;
    }
    draggedCell = { groupId: cell.dataset.groupId, date: cell.dataset.date };
    cell.classList.add('drag-source');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', `${draggedCell.groupId}|${draggedCell.date}`);
  });
  $('#timelineContainer').addEventListener('dragover', (event) => {
    const cell = event.target.closest('.timeline-cell');
    if (!cell || !draggedCell || cell.dataset.groupId !== draggedCell.groupId) return;
    if (statusFor(project.groups.find((group) => group.id === cell.dataset.groupId), cell.dataset.date)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      cell.classList.add('drop-target');
    }
  });
  $('#timelineContainer').addEventListener('dragleave', (event) => {
    const cell = event.target.closest('.timeline-cell');
    if (cell) cell.classList.remove('drop-target');
  });
  $('#timelineContainer').addEventListener('drop', async (event) => {
    const cell = event.target.closest('.timeline-cell');
    if (!cell || !draggedCell || cell.dataset.groupId !== draggedCell.groupId) return;
    event.preventDefault();
    const group = project.groups.find((item) => item.id === draggedCell.groupId);
    const targetDate = cell.dataset.date;
    const sourceDate = draggedCell.date;
    if (group && sourceDate !== targetDate && !statusFor(group, sourceDate) && statusFor(group, targetDate)) {
      setStatus(group, sourceDate, true);
      setStatus(group, targetDate, false);
      suppressClickUntil = Date.now() + 700;
      await saveProject({ refresh: true, successMessage: 'Folga deslocada. O ajuste foi incluído na análise anual.' });
    }
    draggedCell = null;
  });
  $('#timelineContainer').addEventListener('dragend', () => {
    draggedCell = null;
    $$('.timeline-cell.drag-source, .timeline-cell.drop-target').forEach((cell) => cell.classList.remove('drag-source', 'drop-target'));
  });
  $('#shiftSettingsList').addEventListener('click', (event) => {
    const button = event.target.closest('[data-action="rename-shift"]');
    if (button) handleRenameShift(button.dataset.id);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') $$('.modal-backdrop:not([hidden])').forEach((modal) => closeModal(modal.id));
  });
}

attachEvents();
loadProject();
