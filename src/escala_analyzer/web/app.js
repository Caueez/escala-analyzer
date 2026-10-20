const PRIORITY_LABELS = {
  deficit_staff_days: 'Falta de pessoas por dia', deficit_work_hours: 'Falta de horas-pessoa',
  pattern_count: 'Previsibilidade: menos tipos de escala', monthly_staff_cost: 'Menor custo mensal estimado',
  rule_violation_count: 'Violações de regras', group_count: 'Quantidade de grupos',
  surplus_staff_days: 'Excedente de pessoas por dia', people_total: 'Total de funcionários',
};
function renderBusinessPolicy(container, prefix) {
  const policy = project.business_constraints || {};
  const fields = [
    ['max_schedule_patterns', 'Máximo de tipos de escala diferentes', 2, 1, 200, 1],
    ['min_work_percent', 'Trabalho mínimo no ciclo (%)', 50, 0, 100, 0.1],
    ['max_consecutive_rest_days', 'Máximo de dias consecutivos de folga', 3, 1, '', 1],
    ['monthly_employee_cost', 'Custo mensal completo por funcionário (R$)', 0, 0, 1000000000, 0.01],
    ['monthly_budget', 'Orçamento mensal máximo (R$)', '', 0, 1000000000000, 0.01],
  ];
  $('#' + container).innerHTML = fields.map(([key,label,fallback,min,max,step]) => {
    const value = Object.prototype.hasOwnProperty.call(policy,key) ? policy[key] ?? '' : fallback;
    return `<div class="field"><label for="${prefix}_${key}">${label}</label><input id="${prefix}_${key}" data-business-key="${key}" type="number" min="${min}" ${max !== '' ? `max="${max}"` : ''} step="${step}" value="${value}" ${['min_work_percent','monthly_employee_cost'].includes(key) ? 'required' : ''}></div>`;
  }).join('') + '<small class="field-span-2">Padrão: até 2 tipos de escala, ao menos 50% de dias de trabalho e até 3 folgas consecutivas. Limites de tipos, folgas e orçamento podem ficar vazios. Para usar orçamento, informe custo positivo por funcionário. Ex.: orçamento R$ 40.000 e custo R$ 4.000 permitem até 10 funcionários.</small>';
}
function readBusinessPolicy(container) {
  return Object.fromEntries([...$('#' + container).querySelectorAll('[data-business-key]')].map(input => [input.dataset.businessKey, input.value === '' ? null : Number(input.value)]));
}
function cycleBlocks(group) { return group.cycle_blocks || [Number(group.work_days), Number(group.rest_days)]; }
function cycleLength(group) { return cycleBlocks(group).reduce((sum, n) => sum + n, 0); }
function cycleLabel(group) { return cycleBlocks(group).join('x'); }
function parseCycleBlocks(value) {
  if (!/^\s*\d+(\s*[xX×]\s*\d+)*\s*$/.test(value)) throw new Error('Informe blocos como 5x2x3x1x2.');
  const blocks = value.split(/[xX×]/).map(Number);
  if (blocks.some(n => !Number.isSafeInteger(n) || n < 1) || !Number.isSafeInteger(blocks.reduce((a,b) => a+b, 0))) throw new Error('Cada bloco deve conter um número inteiro positivo de dias.');
  return blocks;
}
function renderPriorities(order = project.optimization_priorities || Object.keys(PRIORITY_LABELS)) {
  $('#optimizationPriorities').innerHTML = order.map((key, index) => `<div class="field"><label for="priority${index}">${index + 1}ª prioridade</label><select id="priority${index}" data-priority-index="${index}">${Object.entries(PRIORITY_LABELS).map(([value,label]) => `<option value="${value}" ${key === value ? 'selected' : ''}>${label}</option>`).join('')}</select></div>`).join('');
  $('#optimizationPriorities').dataset.order = JSON.stringify(order);
}
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
  return project.groups.filter((group) => (group.allocations || { [group.shift_id]: group.employee_count })[shiftId] !== undefined)
    .sort((left, right) => (left.layer_by_shift?.[shiftId] || 0) - (right.layer_by_shift?.[shiftId] || 0));
}

function groupCountForShift(group, shiftId) {
  return Number((group.allocations || { [group.shift_id]: group.employee_count })[shiftId] || 0);
}

function shiftFor(group) {
  return project.shifts.find((shift) => shift.id === group.shift_id);
}

function baseStatus(group, isoDate) {
  const target = parseIsoLocal(isoDate);
  let anchor = parseIsoLocal(group.cycle_anchor);
  if (Number.isInteger(group.cycle_anchor_weekday)) {
    anchor = localDate(2024, 0, 1 + group.cycle_anchor_weekday);
  }
  const deltaDays = Math.round((target.getTime() - anchor.getTime()) / 86400000) + Number(group.cycle_phase_offset || 0);
  const length = cycleLength(group);
  const position = ((deltaDays % length) + length) % length;
  let remaining = position;
  for (const [index, length] of cycleBlocks(group).entries()) {
    if (remaining < length) return index % 2 === 0;
    remaining -= length;
  }
  return false;
}

function statusFor(group, isoDate) {
  if (group.work_hours_by_weekday?.[weekdayIndexMondayFirst(parseIsoLocal(isoDate))] === 0) return false;
  if (Object.prototype.hasOwnProperty.call(group.overrides || {}, isoDate)) {
    return Boolean(group.overrides[isoDate]);
  }
  return baseStatus(group, isoDate);
}

function rotationShiftOn(group, isoDate) {
  if (!group.rotation_shift_ids?.length) return null;
  let anchor = parseIsoLocal(group.cycle_anchor);
  if (Number.isInteger(group.cycle_anchor_weekday)) anchor = localDate(2024, 0, 1 + group.cycle_anchor_weekday);
  const delta = Math.round((parseIsoLocal(isoDate).getTime() - anchor.getTime()) / 86400000) + Number(group.cycle_phase_offset || 0);
  const cycle = Math.floor(delta / (cycleLength(group)));
  const length = group.rotation_shift_ids.length;
  return group.rotation_shift_ids[((cycle % length) + length) % length];
}
function worksShiftOn(group, shiftId, isoDate) {
  return statusFor(group, isoDate) && (!group.rotation_shift_ids?.length || rotationShiftOn(group, isoDate) === shiftId);
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

let saasMode = false;
let saasRole = 'admin';
const projectRevisions = new Map();
let pendingAnalysisJob = null;
function csrfToken() { return document.cookie.split('; ').find(item => item.startsWith('escala_csrf='))?.split('=')[1] || ''; }
async function apiRequest(path, options = {}) {
  const method = options.method || 'GET';
  const headers = {'Content-Type':'application/json', ...(options.headers || {})};
  let bodyProject = null;
  if (saasMode) {
    headers['X-CSRF-Token'] = csrfToken();
    if (['/api/analyze','/api/optimize','/api/export'].includes(path)) headers['Idempotency-Key'] = crypto.randomUUID();
    if (method === 'PUT' && path === '/api/project') bodyProject = JSON.parse(options.body);
    if (bodyProject) headers['If-Match'] = String(projectRevisions.get(bodyProject.project_id) ?? 0);
    else if (method === 'DELETE' || path.endsWith('/reuse-group') || path === '/api/project/reset') headers['If-Match'] = String(projectRevisions.get(project.project_id) ?? -1);
    if (path === '/api/analyze' && pendingAnalysisJob) {
      const old = pendingAnalysisJob; pendingAnalysisJob = null;
      await apiRequest(`/api/jobs/${old}/cancel`, {method:'POST'}).catch(() => {});
    }
  }
  const response = await fetch(path, {...options, credentials:'same-origin', headers});
  if (!response.ok) {
    if (response.status === 401 && saasMode) window.location.assign('/login');
    let message = `Erro HTTP ${response.status}`;
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body); } catch (_) {}
    throw new Error(message);
  }
  let data = await response.json();
  const revision = response.headers.get('ETag');
  if (saasMode && revision && data.project_id) projectRevisions.set(data.project_id, Number(revision.replaceAll('"','')));
  if (saasMode && response.status === 202 && data.status_url) {
    const jobId = data.id;
    if (path === '/api/analyze') pendingAnalysisJob = jobId;
    const deadline = Date.now() + 300000;
    while (data.state === 'queued' || data.state === 'running') {
      if (Date.now() >= deadline) throw new Error(`Trabalho ${jobId} ainda em processamento. Atualize mais tarde.`);
      await new Promise(resolve => setTimeout(resolve, 750));
      data = await apiRequest(data.status_url);
    }
    if (pendingAnalysisJob === jobId) pendingAnalysisJob = null;
    if (data.state === 'cancelled') throw new Error('Cálculo substituído por uma atualização mais recente.');
    if (data.state !== 'succeeded') throw new Error(`Não foi possível concluir o trabalho (${data.error_code || data.state}).`);
    return apiRequest(data.result_url);
  }
  return data;
}

async function saveProject({ refresh = true, successMessage = null } = {}) {
  if (!project) return;
  if (saasMode && saasRole === 'viewer') {
    renderStats(); renderTimelineView();
    if (currentView === 'analysis') renderAnalysisView();
    setSaveState('Somente leitura'); return;
  }
  setSaveState('Salvando…', 'saving');
  try {
    project = await apiRequest('/api/project', { method: 'PUT', body: JSON.stringify(project) });
    setSaveState(saasMode ? 'Salvo no servidor' : 'Salvo localmente');
    $('#sidebarProjectName').textContent = project.name;
    if (refresh) {
      await recalculate({ renderTimeline: true, renderAnalysis: currentView === 'analysis' });
      if (currentView === 'groups') renderGroupsView();
    }
    if (successMessage) notify(successMessage);
  } catch (error) {
    setSaveState('Falha ao salvar', 'error');
    notify(`Não foi possível salvar: ${error.message}`, 'error', 6000);
    throw error;
  }
}

let analysisSequence = 0;
async function recalculate({ renderTimeline = false, renderAnalysis = true } = {}) {
  const sequence = ++analysisSequence;
  if (!project) return;
  try {
    const result = await apiRequest('/api/analyze', { method: 'POST', body: JSON.stringify(project) });
    if (sequence !== analysisSequence) return;
    analysis = result;
    renderStats();
    if (renderTimeline) renderTimelineView();
    if (renderAnalysis) renderAnalysisView();
  } catch (error) {
    if (sequence !== analysisSequence) return;
    notify(`Falha ao analisar o projeto: ${error.message}`, 'error', 6000);
  }
}

async function loadProject() {
  setSaveState('Carregando…', 'saving');
  try {
    project = await apiRequest('/api/project');
    await refreshProjectSwitcher();
    $('#sidebarProjectName').textContent = project.name;
    renderPriorities();
  $('#projectName').value = project.name;
  if ($('#portfolioName')) $('#portfolioName').value = project.portfolio_name;
    fillMonthSelect();
    await recalculate({ renderTimeline: true, renderAnalysis: true });
    setSaveState(saasMode ? 'Salvo no servidor' : 'Salvo localmente');
  } catch (error) {
    setSaveState('Falha ao carregar', 'error');
    $('#timelineContainer').innerHTML = `<div class="empty-state">Não foi possível carregar o projeto.<br><br>${escapeHtml(error.message)}</div>`;
    notify(`Falha ao abrir o projeto: ${error.message}`, 'error', 8000);
  }
}

async function refreshProjectSwitcher() {
  const projects = await apiRequest('/api/projects');
  const portfolios = [...new Map(projects.map(item => [item.portfolio_id, item.portfolio_name])).entries()];
  $('#portfolioSelect').innerHTML = portfolios.map(([id,name]) => `<option value="${escapeHtml(id)}">${escapeHtml(name)}</option>`).join('');
  $('#portfolioSelect').value = project.portfolio_id;
  $('#projectSelect').innerHTML = projects.filter(item => item.portfolio_id === project.portfolio_id).map((item) => `<option value="${escapeHtml(item.project_id)}">${escapeHtml(item.name)}</option>`).join('');
  $('#projectSelect').value = project.project_id;
}

async function switchProject(projectId) {
  if (!saasMode || saasRole !== 'viewer') await saveProject({refresh:false});
  project = await apiRequest(`/api/projects/${encodeURIComponent(projectId)}`);
  if (!saasMode || saasRole !== 'viewer') await saveProject({refresh:false});
  fillMonthSelect();
  await recalculate({ renderTimeline: true, renderAnalysis: true });
  await refreshProjectSwitcher();
}

async function createProject(subdivision = false) {
  const name = window.prompt(subdivision ? 'Nome da subdivisão:' : 'Nome do novo projeto:', subdivision ? 'Nova subdivisão' : 'Novo projeto');
  if (!name?.trim()) return;
  const source = structuredClone(project);
  source.project_id = crypto.randomUUID();
  source.name = subdivision ? name.trim() : 'Escalas';
  source.groups = [];
  source.shared_group_links = {};
  if (!subdivision) {
    source.portfolio_id = crypto.randomUUID();
    source.portfolio_name = name.trim();
    source.shifts = [];
  }
  project = await apiRequest('/api/project', { method: 'PUT', body: JSON.stringify(source) });
  fillMonthSelect(); await recalculate({ renderTimeline: true, renderAnalysis: true }); await refreshProjectSwitcher();
}

async function reuseSavedGroup() {
  try {
    await saveProject();
    const projects = await apiRequest('/api/projects');
    const entries = projects.flatMap(p => p.groups.map(g => ({p, g})));
    if (!entries.length) return notify('Nenhum grupo salvo para reutilizar.');
    const choice = window.prompt('Escolha o número do grupo:\n' + entries.map(({p,g},i) => `${i+1}. ${p.portfolio_name} / ${p.name} / ${g.name}`).join('\n'));
    if (choice === null) return;
    const selected = entries[Number(choice)-1];
    if (!selected) return notify('Grupo inválido.', 'error');
    const mode = window.prompt('Digite copiar para criar uma cópia independente ou vincular para compartilhar as alterações do grupo entre subdivisões e projetos.', 'copiar');
    if (!['copiar', 'vincular'].includes(mode)) return;
    project = await apiRequest(`/api/projects/${encodeURIComponent(project.project_id)}/reuse-group`, {method:'POST', body:JSON.stringify({source_project_id:selected.p.project_id, group_id:selected.g.id, linked:mode === 'vincular'})});
    await recalculate({renderTimeline:true, renderAnalysis:true});
    notify(mode === 'vincular' ? 'Grupo vinculado. Alterações serão compartilhadas ao salvar.' : 'Grupo copiado.');
  } catch (error) { notify(error.message, 'error'); }
}

async function removeCurrentProject() {
  if (!window.confirm(`Excluir permanentemente a subdivisão ${project.name}?`)) return;
  await apiRequest(`/api/projects/${encodeURIComponent(project.project_id)}`, { method: 'DELETE' });
  await loadProject();
}

function renderStats() {
  if (!project || !analysis) return;
  $('#statPeople').textContent = Number(analysis.people_total).toLocaleString('pt-BR');
  $('#statGroups').textContent = Number(analysis.group_count).toLocaleString('pt-BR');
  const month = Number(project.selected_month ?? 1);
  const monthSummary = month === 0 ? null : analysis.monthly_summary[month - 1];
  const yearDeficits = analysis.monthly_summary.reduce((sum, item) => sum + item.coverage_gap_count, 0);
  const yearWorst = Math.max(...analysis.monthly_summary.map((item) => item.worst_single_shift_deficit), 0);
  $('#statDeficitDays').textContent = (monthSummary ? monthSummary.coverage_gap_count : yearDeficits).toLocaleString('pt-BR');
  $('#statDeficitFoot').textContent = 'Combinações turno/dia abaixo da demanda';
  $('#statWorstDeficit').textContent = (monthSummary ? monthSummary.worst_single_shift_deficit : yearWorst).toLocaleString('pt-BR');
  $('#yearLabel').textContent = project.year;
  $('#sidebarProjectName').textContent = project.name;
}

function renderProjectOverview() {
  if (!project || !analysis) return;
  const month = Number(project.selected_month ?? 1);
  const months = month === 0 ? analysis.monthly_summary : [analysis.monthly_summary[month - 1]];
  const deficit = months.reduce((sum, item) => sum + item.coverage_gap_count, 0);
  const ruleIssues = analysis.rule_issues.filter((issue) => month === 0 || issue.month === month).length;
  $('#projectOverviewText').textContent = `${project.year} · ${project.shifts.length} turno(s) · ${project.groups.length} grupo(s) · ${Object.keys(project.shared_group_links).length} vínculo(s)`;
  const issues = analysis.rule_issues.filter((issue) => month === 0 || issue.month === month).slice(0, 4);
  const issueText = issues.length ? issues.map((issue) => `${issue.group_name}: ${issue.title}`).join(' · ') : 'Nenhuma regra violada no período.';
  $('#projectOverviewDetails').innerHTML = `<span><strong>${analysis.people_total}</strong> pessoas alocadas</span><span><strong>${deficit}</strong> turno(s)/dia com déficit</span><span><strong>${ruleIssues}</strong> alerta(s) de regras</span><span>Regras: ${project.rules.check_min_days_off_per_month ? project.rules.min_days_off_per_month + ' folgas/mês' : 'mínimo mensal desativado'} · ${project.rules.min_sundays_off_per_month} domingos · até ${project.rules.max_consecutive_work_days} dias seguidos</span><div class="overview-issues">${escapeHtml(issueText)}</div>`;
}

function groupRuleHealth(groupId) {
  const count = analysis.rule_issues.filter((issue) => issue.group_id === groupId).length;
  return count === 0 ? { className: 'ok', icon: '✓', label: 'Todas as regras anuais atendidas' }
    : count === 1 ? { className: 'warning', icon: '!', label: '1 regra anual violada' }
      : { className: 'error', icon: '!', label: `${count} regras anuais violadas` };
}

function openGroupRuleDialog(groupId) {
  const group = project.groups.find((item) => item.id === groupId);
  if (!group || !analysis) return;
  const issues = analysis.rule_issues.filter((issue) => issue.group_id === groupId);
  $('#ruleDialogTitle').textContent = `Regras de ${group.name}`;
  $('#ruleDialogContent').innerHTML = issues.length
    ? `<p class="rule-dialog-intro">Estas ocorrências consideram o ano inteiro, mesmo quando o calendário está mostrando apenas um mês.</p>${issues.map((issue) => {
      const location = issue.date
        ? `Primeira ocorrência em ${issue.date}`
        : issue.first_window_start
        ? `Janela iniciada em ${issue.first_window_start}${issue.last_window_start && issue.last_window_start !== issue.first_window_start ? `; última em ${issue.last_window_start}` : ''}`
        : issue.month ? MONTH_NAMES[issue.month - 1] : 'Ano todo';
      return `<article class="rule-detail"><strong>${escapeHtml(issue.title)}</strong><div>${escapeHtml(issue.message)}</div><small>${escapeHtml(location)}${issue.windows_count || issue.occurrences_count ? ` · ${issue.windows_count || issue.occurrences_count} ocorrência(s)` : ''}</small>${issue.configuration_section === 'groupHoursRows' ? `<button type="button" class="button button-secondary" data-configure-group-hours="${escapeHtml(groupId)}">Configurar jornada semanal do grupo</button>` : issue.configuration_section ? '<button type="button" class="button button-secondary" data-configure-interval>Configurar intervalos do turno e regras</button>' : ''}</article>`;
    }).join('')}`
    : '<div class="empty-state">✓ Nenhuma violação nas regras configuradas para este grupo durante o ano.</div>';
  $('#ruleDialogContent').innerHTML += groupReport(groupId, true);
  $('#ruleDialog').hidden = false;
}

function hours(value) {
  return value == null ? 'Não calculado' : `${Number(value).toLocaleString('pt-BR', {maximumFractionDigits: 2})} h`;
}
function groupReport(groupId, includeJourneys = false) {
  const annual = (analysis.group_annual || []).find(row => row.group_id === groupId);
  const monthly = (analysis.group_monthly || []).filter(row => row.group_id === groupId);
  if (!annual) return '<p>Detalhes de jornada indisponíveis.</p>';
  const rows = [annual, ...monthly];
  const table = `<div class="table-wrap"><table><thead><tr><th>Período</th><th>Trabalho (dias)</th><th>Folgas</th>${WEEKDAY_SHORT.map(day => `<th>${day}</th>`).join('')}<th>Trabalho efetivo</th><th>Intervalos</th><th>Descanso fora jornada</th><th>Menor entre jornadas</th><th>Maior entre jornadas</th></tr></thead><tbody>${rows.map(row => `<tr><th>${row.month ? MONTH_NAMES[row.month - 1] : 'Ano inteiro'}</th><td>${row.work_days}</td><td>${row.days_off}</td>${(row.days_off_by_weekday || []).map(value => `<td>${value}</td>`).join('')}<td>${hours(row.work_hours)}</td><td>${hours(row.break_hours)}</td><td>${hours(row.rest_hours)}</td><td>${hours(row.min_intershift_hours)}</td><td>${hours(row.max_intershift_hours)}</td></tr>`).join('')}</tbody></table></div>`;
  const allocations = (annual.allocations || []).map(team => `<details><summary>${escapeHtml(team.shift_name || team.shift_id)} · ${team.employees} pessoa(s) · ${hours(team.work_hours)} trabalhadas</summary><p>Intervalos: ${hours(team.break_hours)} · descanso fora jornada: ${hours(team.rest_hours)} · menor descanso entre jornadas: ${hours(team.min_intershift_hours)} · maior: ${hours(team.max_intershift_hours)}.</p>${includeJourneys ? `<div class="table-wrap"><table><thead><tr><th>Data</th><th>Turno</th><th>Início</th><th>Fim</th><th>Trabalho</th><th>Intervalo</th><th>Descanso anterior</th></tr></thead><tbody>${(team.journeys || []).map(journey => `<tr><td>${escapeHtml(journey.date)}</td><td>${escapeHtml(journey.shift_name || '')}</td><td>${escapeHtml(journey.start || 'Não informado')}</td><td>${escapeHtml(journey.end || 'Não informado')}</td><td>${hours(journey.work_hours)}</td><td>${journey.break_minutes} min</td><td>${hours(journey.rest_before_hours)}</td></tr>`).join('')}</tbody></table></div>` : '<p>Abra a validação do grupo pelo botão ✓ / ! para consultar cada jornada.</p>'}</details>`).join('');
  return `<div class="group-report"><p>Folgas por dia da semana (Seg a Dom). Horas por pessoa da equipe com maior carga; as equipes por turno aparecem abaixo. Descanso fora jornada é o saldo de horas do calendário após trabalho e intervalos; jornadas são atribuídas ao dia em que começam.${annual.timing_complete ? '' : ' Há horários ausentes: a verificação entre jornadas está incompleta.'}</p>${table}${allocations}</div>`;
}
function renderGroupDetails() {
  $('#groupDetails').innerHTML = project.groups.map(group => `<details><summary>${escapeHtml(group.name)} · folgas e horas de ${project.year}</summary>${groupReport(group.id)}</details>`).join('') || '<div class="empty-state">Cadastre um grupo para consultar os detalhes.</div>';
}

function renderGroupsView() {
  if (!project || !analysis) return;
  $('#groupsList').innerHTML = project.groups.length ? project.groups.map((group) => {
    const health = groupRuleHealth(group.id);
    const allocations = project.shifts.filter((shift) => groupCountForShift(group, shift.id) > 0).map((shift) => `${shift.name}: ${groupCountForShift(group, shift.id)}`).join(' · ');
    return `<article class="group-card"><div><div class="group-card-name"><button class="group-rule-status ${health.className}" data-group-rules="${escapeHtml(group.id)}" title="${escapeHtml(health.label)}">${health.icon}</button>${escapeHtml(group.name)}${project.shared_group_links[group.id] ? ' · Vinculado' : ''}</div><div class="group-card-meta">${cycleLabel(group)} · ${cycleLength(group)} dias · ${escapeHtml(allocations || 'Sem turno alocado')}</div></div><div class="button-row"><button class="button button-quiet" data-group-rules="${escapeHtml(group.id)}">Ver regras</button><button class="button button-quiet" data-group-edit="${escapeHtml(group.id)}">Editar</button><button class="button button-danger-quiet" data-group-delete="${escapeHtml(group.id)}">Excluir</button></div></article>`;
  }).join('') : '<div class="empty-state">Nenhum grupo cadastrado.</div>';
}

function fillMonthSelect() {
  const select = $('#monthSelect');
  select.innerHTML = `<option value="0">Ano inteiro</option>${MONTH_NAMES.map((name, index) => `<option value="${index + 1}">${name}</option>`).join('')}`;
  select.value = String(project.selected_month ?? 1);
  $('#yearLabel').textContent = project.year;
}

function renderTimelineView() {
  if (!project || !analysis) return;
  const container = $('#timelineContainer');
  const oldScrollLeft = container.scrollLeft;
  const oldScrollTop = container.scrollTop;
  const year = Number(project.year);
  const selected = Number(project.selected_month ?? 1);
  const monthIndexes = selected === 0 ? Array.from({ length: 12 }, (_, index) => index) : [selected - 1];

  if (project.shifts.length === 0) {
    container.innerHTML = '<div class="empty-state">Nenhum turno cadastrado. Abra Configurações e adicione um turno para começar.</div>';
  } else {
    const sections = monthIndexes.map((monthIndex) => {
      const dayCount = daysInMonth(year, monthIndex);
      const selectedMonth = MONTH_NAMES[monthIndex];
      const shiftSections = project.shifts.map((shift) => {
      const groups = groupByShift(shift.id);
      const gridTemplate = `var(--timeline-label-width) repeat(${dayCount}, 36px)`;
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
      const coverageCells = Array.from({ length: dayCount }, (_, index) => {
        const iso = toIsoDate(year, monthIndex, index + 1);
        const dayCoverage = analysis.coverage_by_day.find((item) => item.date === iso);
        const coverage = dayCoverage?.shifts.find((item) => item.shift_id === shift.id);
        const scheduled = coverage?.scheduled ?? 0;
        const required = coverage?.required ?? 0;
        return `<button class="coverage-day ${scheduled < required || coverage?.deficit_work_hours > 0 ? 'has-deficit' : ''}" data-action="edit-demand" data-shift-id="${escapeHtml(shift.id)}" data-date="${iso}" title="Editar demanda desta data: ${scheduled} trabalhando; demanda ${required}; horas-pessoa ${coverage?.scheduled_work_hours ?? 0}/${coverage?.required_work_hours ?? 0}">${scheduled}/${required}</button>`;
      }).join('');
      const coverageRow = `<div class="coverage-label-cell"><strong>Trabalhando / demanda</strong><span>Quantidade exata por dia</span></div>${coverageCells}`;
      const groupRows = groups.map((group, groupIndex) => {
        const overridesCount = Object.keys(group.overrides || {}).filter((dateText) => dateText.startsWith(`${year}-${String(monthIndex + 1).padStart(2, '0')}-`)).length;
        const metadata = `${groupCountForShift(group, shift.id)} pessoas · ${cycleLabel(group)}${overridesCount ? ` · ${overridesCount} ajuste(s)` : ''}`;
        const cells = Array.from({ length: dayCount }, (_, index) => {
          const dayNum = index + 1;
          const day = localDate(year, monthIndex, dayNum);
          const iso = toIsoDate(year, monthIndex, dayNum);
          const isWorking = statusFor(group, iso);
          const isOverride = Object.prototype.hasOwnProperty.call(group.overrides || {}, iso);
          const dow = weekdayIndexMondayFirst(day);
          const otherShift = isWorking && group.rotation_shift_ids?.length && rotationShiftOn(group, iso) !== shift.id;
          const dailyHours = group.work_hours_by_weekday?.[dow] ?? (Number(shift.hours_per_day) - (shift.hours_include_break ? Number(shift.break_minutes || 0) / 60 : 0));
          const stateLabel = otherShift ? 'Em outro turno' : isWorking ? `Trabalho · ${Number(dailyHours.toFixed(2))} h efetivas` : 'Folga';
          const title = `${group.name} · ${dayNum}/${String(monthIndex + 1).padStart(2, '0')}/${year} · ${stateLabel}${isOverride ? ' · ajuste manual' : ''}`;
          return `<button class="timeline-cell ${otherShift ? 'other-shift' : isWorking ? 'work' : 'rest'} ${dow === 6 ? 'is-sunday' : ''} ${isOverride ? 'is-override' : ''}" data-group-id="${escapeHtml(group.id)}" data-date="${iso}" data-working="${isWorking}" draggable="${!isWorking && group.work_hours_by_weekday?.[dow] !== 0}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"><span class="cell-mark">${otherShift ? 'OUTRO' : isWorking ? Number(dailyHours.toFixed(2)) + 'h' : 'FOLGA'}</span></button>`;
        }).join('');
        const health = groupRuleHealth(group.id);
        return `<div class="group-label-cell"><div class="group-label-main"><div class="group-name-label"><button class="group-rule-status ${health.className}" data-action="show-group-rules" data-id="${escapeHtml(group.id)}" title="${escapeHtml(health.label)}">${health.icon}</button><span title="${escapeHtml(group.name)}">${escapeHtml(group.name)}</span></div><div class="group-label-meta">${escapeHtml(metadata)}</div></div><div class="group-tools">${[[-1, 'shift-cycle', '←', 'Retroceder ciclo um dia'], [1, 'shift-cycle', '→', 'Avançar ciclo um dia'], [-1, 'move-layer', '↑', 'Mover grupo para cima'], [1, 'move-layer', '↓', 'Mover grupo para baixo']].map(([direction, action, icon, label]) => `<button type="button" data-action="${action}" data-direction="${direction}" data-id="${escapeHtml(group.id)}" data-shift-id="${escapeHtml(shift.id)}" title="${label}" aria-label="${label}: ${escapeHtml(group.name)}">${icon}</button>`).join('')}<button type="button" data-action="group-menu" data-shift-id="${escapeHtml(shift.id)}" data-id="${escapeHtml(group.id)}" aria-label="Ações de ${escapeHtml(group.name)}" title="Ações do grupo">⋯</button></div></div>${cells}`;
      }).join('');
      return `<section class="shift-section"><div class="shift-section-heading"><span class="shift-indicator"></span>${escapeHtml(shift.name)}<span class="shift-group-count">${groups.length} grupo(s) · ${groups.reduce((sum, item) => sum + groupCountForShift(item, shift.id), 0)} pessoa(s) cadastradas</span></div><div class="timeline-grid" style="grid-template-columns:${gridTemplate}">${headLabel}${dayHeaders}${coverageRow}${groupRows}</div></section>`;
      }).join('');
      return `<section class="timeline-month"><div class="timeline-month-title">${selectedMonth} de ${year}</div>${shiftSections}</section>`;
    }).join('');
    container.innerHTML = sections;
  }

  $('#timelineRangeLabel').textContent = selected === 0 ? `Janeiro a Dezembro de ${year}` : `${MONTH_NAMES[selected - 1]} de ${year} · ${daysInMonth(year, selected - 1)} dias`;
  container.scrollLeft = oldScrollLeft;
  container.scrollTop = oldScrollTop;
  renderProjectOverview();
  renderGroupDetails();
}

function changeMonth(delta) {
  if (Number(project.selected_month) === 0) project.selected_month = delta > 0 ? 1 : 12;
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
  const titles = { timeline: 'Linha do tempo', groups: 'Grupos', analysis: 'Análise anual', settings: 'Configurações' };
  $('#breadcrumbTitle').textContent = titles[viewName] || 'Linha do tempo';
  if (viewName === 'settings') fillSettingsForm();
  if (viewName === 'analysis') renderAnalysisView();
  if (viewName === 'groups') renderGroupsView();
}

function openGroupDialog(group = null) {
  $('#groupDialog').hidden = false;
  $('#groupId').value = group?.id || '';
  $('#groupDialogTitle').textContent = group ? 'Editar grupo' : 'Novo grupo';
  $('#groupName').value = group?.name || `Grupo ${String.fromCharCode(65 + project.groups.length % 26)}`;
  $('#groupCycleBlocks').value = group?.cycle_blocks?.join('x') || '';
  $('#groupCycleDays').value = group?.cycle_days ?? '';
  $('#groupWorkDays').value = group?.work_days ?? 3;
  $('#groupRestDays').value = group?.rest_days ?? 1;
  $('#groupAnchorWeekday').value = group?.cycle_anchor_weekday == null ? '' : String(group.cycle_anchor_weekday);
  $('#groupAnchorDate').value = group?.cycle_anchor || `${project.year}-01-01`;
  $('#groupPhaseOffset').value = group?.cycle_phase_offset || 0;
  $('#groupOptimizeHours').checked = group?.allow_hours_optimization || false;
  $('#groupHoursRows').innerHTML = WEEKDAY_LONG.map((label, day) => `<tr><th>${label}</th><td><input aria-label="Horas efetivas ${label}" data-group-hour="${day}" type="number" min="0" max="24" step="any" placeholder="Herdar turno" value="${group?.work_hours_by_weekday?.[day] ?? ''}"></td><td><input aria-label="Mínimo ${label}" data-group-min-hour="${day}" type="number" min="0" max="24" step="any" value="${group?.min_hours_by_weekday?.[day] ?? 6}" required></td><td><input aria-label="Máximo ${label}" data-group-max-hour="${day}" type="number" min="0" max="24" step="any" value="${group?.max_hours_by_weekday?.[day] ?? 8}" required></td></tr>`).join('');
  $('#groupTimingHint').textContent = 'Início e pausa vêm dos turnos; dias sem jornada própria também herdam as horas. ' + project.shifts.filter(s => group ? Object.hasOwn(group.allocations, s.id) : true).map(s => `${s.name}: ${shiftHoursLabel(s)}`).join(' · ');
  $('#groupRotation').checked = Boolean(group?.rotation_shift_ids?.length);
  $('#groupRotation').disabled = false;
  $('#deleteGroupButton').hidden = !group;
  renderGroupAllocations(group);
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

function renderGroupAllocations(group = null) {
  $('#groupAllocations').innerHTML = project.shifts.map((shift) => {
    const existing = groupCountForShift(group || { allocations: {} }, shift.id);
    return `<label class="group-allocation"><span>${escapeHtml(shift.name)}</span><input data-allocation-shift="${escapeHtml(shift.id)}" type="number" min="0" max="100000" step="1" required value="${existing}"></label>`;
  }).join('');
}

function updateCyclePreview() {
  const custom = Boolean($('#groupCycleBlocks').value.trim());
  $('#groupWorkDays').disabled = custom;
  $('#groupRestDays').disabled = custom;
  try {
    const blocks = $('#groupCycleBlocks').value.trim() ? parseCycleBlocks($('#groupCycleBlocks').value) : [Number($('#groupWorkDays').value), Number($('#groupRestDays').value)];
    const total = blocks.reduce((sum, n) => sum + n, 0);
    const declared = $('#groupCycleDays').value;
    const mismatch = declared !== '' && Number(declared) !== total;
    $('#groupCycleDays').setCustomValidity(mismatch ? `A soma é ${total} dias e deve ser ${declared}.` : '');
    $('#groupCycleBlocks').setCustomValidity('');
    $('#cyclePreview').textContent = `Ciclo: ${blocks.map((n, i) => `${n} dia(s) de ${i % 2 ? 'folga' : 'trabalho'}`).join(' → ')} · Total: ${total} dias${mismatch ? ' · Total não confere' : ''}`;
  } catch (error) {
    $('#groupCycleBlocks').setCustomValidity(error.message);
    $('#cyclePreview').textContent = error.message;
  }
}

function deleteGroup(groupId) {
  const group = project.groups.find((item) => item.id === groupId);
  if (!group) return;
  if (!window.confirm(`Excluir o ${group.name}? Os ajustes manuais deste grupo serão removidos.`)) return;
  project.groups = project.groups.filter((item) => item.id !== groupId);
  delete project.shared_group_links[groupId];
  if ($('#groupId').value === groupId) closeModal('groupDialog');
  saveProject({ refresh: true, successMessage: 'Grupo excluído.' });
}

async function duplicateGroup(groupId) {
  const source = project.groups.find((item) => item.id === groupId);
  if (!source) return;
  const copy = structuredClone(source);
  copy.id = `grupo-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
  copy.name = `${source.name} (cópia)`;
  copy.overrides = {};
  project.groups.push(copy);
  await saveProject({ refresh: true, successMessage: 'Grupo duplicado. Revise a quantidade automática e o ciclo, se necessário.' });
}

function hideGroupContextMenu() {
  $('#groupContextMenu').hidden = true;
}

function showGroupContextMenu(groupId, x, y, shiftId = null) {
  const menu = $('#groupContextMenu');
  const button = (action, label, direction = '') => `<button data-context-action="${action}" data-id="${escapeHtml(groupId)}" data-shift-id="${escapeHtml(shiftId || '')}" data-direction="${direction}">${label}</button>`;
  menu.innerHTML = button('edit', 'Editar grupo') + button('rules', 'Ver regras do grupo') + button('phase', 'Retroceder ciclo um dia', -1) + button('phase', 'Avançar ciclo um dia', 1) + (shiftId ? button('layer', 'Mover grupo para cima', -1) + button('layer', 'Mover grupo para baixo', 1) : '') + button('duplicate', 'Duplicar grupo') + button('delete', 'Excluir grupo');
  menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - 235))}px`;
  menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - 310))}px`;
  menu.hidden = false;
}

function fillSettingsForm() {
  if (!project) return;
  renderBusinessPolicy('settingsBusiness', 'business');
  renderPriorities();
  $('#projectName').value = project.name;
  if ($('#portfolioName')) $('#portfolioName').value = project.portfolio_name;
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
  fillCompanyAndRules();
  updateProfileExplainer();
}

function updateProfileExplainer() {
  const profile = PROFILE_PRESETS[$('#ruleProfile').value] || PROFILE_PRESETS.transition;
  $('#profileExplainer').innerHTML = `<strong>${escapeHtml(profile.label)}.</strong> ${escapeHtml(profile.explainer)} Os valores podem ser alterados manualmente.`;
}

function shiftHoursLabel(shift) {
  const pause = Number(shift.break_minutes || 0) / 60;
  const informed = Number(shift.hours_per_day || 0);
  const worked = shift.hours_include_break ? informed - pause : informed;
  const elapsed = shift.hours_include_break ? informed : informed + pause;
  return `${hours(worked)} de trabalho efetivo + ${shift.break_minutes || 0} min de pausa = ${hours(elapsed)} no turno`;
}

function renderShiftSettings() {
  const container = $('#shiftSettingsList');
  if (!project.shifts.length) {
    container.innerHTML = '<div class="empty-state">Nenhum turno cadastrado. Use “Adicionar turno” para começar.</div>';
    return;
  }
  container.innerHTML = project.shifts.map((shift) => `
    <article class="shift-config-card" data-shift-card="${escapeHtml(shift.id)}">
      <div class="shift-config-head"><div><strong>${escapeHtml(shift.name)}</strong><small>${groupByShift(shift.id).length} grupo(s) vinculados</small></div><div class="button-row"><button type="button" class="button button-quiet" data-action="rename-shift" data-id="${escapeHtml(shift.id)}">Renomear</button><button type="button" class="button button-danger-quiet" data-action="delete-shift" data-id="${escapeHtml(shift.id)}">Excluir turno</button></div></div>
      <div class="shift-config-grid">
        <div class="field"><label>Todos os dias</label><input data-demand-all="${escapeHtml(shift.id)}" type="number" min="0" max="100000" step="1" placeholder="Aplicar"></div>
        <div class="field"><label for="shift-name-${escapeHtml(shift.id)}">Nome do turno</label><input id="shift-name-${escapeHtml(shift.id)}" data-shift-id="${escapeHtml(shift.id)}" data-field="name" value="${escapeHtml(shift.name)}" required></div>
        <div class="field"><label for="shift-hours-${escapeHtml(shift.id)}">Duração informada (h)</label><input id="shift-hours-${escapeHtml(shift.id)}" data-shift-id="${escapeHtml(shift.id)}" data-field="hours_per_day" type="number" min="0" max="24" step="0.25" value="${shift.hours_per_day}" required></div>
        <div class="field"><label>Estas horas representam<select data-field="hours_include_break"><option value="true" ${shift.hours_include_break ? 'selected' : ''}>Turno completo, incluindo a pausa</option><option value="false" ${!shift.hours_include_break ? 'selected' : ''}>Somente trabalho efetivo, sem a pausa</option></select></label></div>
        <div class="field"><label>Início do turno<input data-field="start_time" type="time" value="${escapeHtml((shift.start_time || '').slice(0, 5))}"></label></div>
        <div class="field"><label>Intervalo (min)<input data-field="break_minutes" type="number" min="0" max="1440" value="${shift.break_minutes || 0}" required></label></div>
        <div class="field field-span-2"><label>Exceções de demanda por data<textarea data-field="demand_by_date" rows="3" placeholder="2027-12-25=0">${escapeHtml(Object.entries(shift.demand_by_date || {}).map(([day, count]) => `${day}=${count}`).join('\n'))}</textarea></label><small>Uma linha por data: AAAA-MM-DD=quantidade. Use para feriados, paradas e sazonalidade.</small></div>
        <p class="shift-hours-summary field-span-2" data-shift-hours-summary>${escapeHtml(shiftHoursLabel(shift))} A pausa entra na conta mesmo com a validação do mínimo desativada.</p>
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
  const previous = structuredClone(project);
  try {
  project.business_constraints = readBusinessPolicy('settingsBusiness');
  project.optimization_priorities = [...document.querySelectorAll('[data-priority-index]')].map(select => select.value);
  project.name = $('#projectName').value.trim() || 'Subdivisão';
  project.portfolio_name = $('#portfolioName').value.trim() || 'Projeto';
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
  readCompanyAndRules();
  const shiftNodes = $$('.shift-config-card');
  for (const card of shiftNodes) {
    const shiftId = card.dataset.shiftCard;
    const shift = project.shifts.find((item) => item.id === shiftId);
    if (!shift) continue;
    const name = $(`[data-shift-id="${CSS.escape(shiftId)}"][data-field="name"]`, card).value.trim();
    const hours = Number($(`[data-shift-id="${CSS.escape(shiftId)}"][data-field="hours_per_day"]`, card).value);
    const demands = $$(`[data-shift-id="${CSS.escape(shiftId)}"][data-field="demand"]`, card).map((input) => Number(input.value));
    if (!name || !Number.isFinite(hours) || hours < 0 || hours > 24 || demands.length !== 7 || demands.some((value) => !Number.isInteger(value) || value < 0)) {
      throw new Error(`Confira o nome, as horas e a demanda do turno ${shift.name}.`);
    }
    shift.name = name;
    shift.hours_per_day = hours;
    shift.hours_include_break = $('[data-field="hours_include_break"]', card).value === 'true';
    shift.demand_by_weekday = demands;
    shift.start_time = $('[data-field="start_time"]', card).value || null;
    for (const field of ['break_minutes']) shift[field] = Number($(`[data-field="${field}"]`, card).value);
    shift.demand_by_date = parseDemandDates($('[data-field="demand_by_date"]', card).value);
  }
  fillMonthSelect();
  $('#analysisYearHeading').textContent = project.year;
  await saveProject({ refresh: true, successMessage: 'Parâmetros salvos e análise recalculada.' });
  await refreshProjectSwitcher();
  setView('timeline');
  } catch (error) {
    project = previous;
    notify(error.message, 'error', 6000);
  }
}

function renderAnalysisView() {
  if (!project || !analysis) return;
  $('#analysisYearHeading').textContent = analysis.year;
  $('#analysisDisclaimer').textContent = analysis.disclaimer;
  $('#profileTag').textContent = (project.rules.profile_label || (PROFILE_PRESETS[project.rules.profile]?.label ?? 'Cenário configurado')) + (project.rule_periods?.length ? ` · ${project.rule_periods.length} vigência(s) cadastrada(s)` : '');
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
  if (analysisFilter === 'coverage') issues = issues.filter((item) => item.code.startsWith('coverage-'));
  if (analysisFilter === 'rules') issues = issues.filter((item) => !item.code.startsWith('coverage-'));
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

async function exportJson() {
  await saveProject({refresh:false});
  const projects = (await apiRequest('/api/projects')).filter(p => p.portfolio_id === project.portfolio_id);
  const data = JSON.stringify({schema_version:2, active_id:project.project_id, projects}, null, 2);
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
    project = (saasMode || parsed.projects)
      ? await apiRequest('/api/projects/import', {method:'POST',body:JSON.stringify(parsed.projects ? parsed : {schema_version:2, active_id:parsed.project_id, projects:[parsed]})})
      : await apiRequest('/api/project', {method:'PUT',body:JSON.stringify(parsed)});
    await refreshProjectSwitcher();
    fillMonthSelect();
    await recalculate({ renderTimeline: true, renderAnalysis: true });
    fillSettingsForm();
    setSaveState(saasMode ? 'Salvo no servidor' : 'Salvo localmente');
    notify('Projeto importado e salvo localmente.');
  } catch (error) {
    notify(`Não foi possível importar o projeto: ${error.message}`, 'error', 6000);
  } finally {
    $('#importJsonInput').value = '';
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
  project.shifts.push({ id, name, hours_per_day: 8, hours_include_break: true, demand_by_weekday: Array(7).fill(demand) });
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

async function deleteShift(shiftId) {
  const shift = project.shifts.find((item) => item.id === shiftId);
  if (!shift) return;
  if (!window.confirm(`Excluir o turno ${shift.name}? Ele será removido das alocações dos grupos.`)) return;
  project.shifts = project.shifts.filter((item) => item.id !== shiftId);
  project.groups.forEach((group) => {
    group.rotation_shift_ids = (group.rotation_shift_ids || []).filter(id => id !== shiftId);
    if (group.allocations) delete group.allocations[shiftId];
    if (group.shift_id === shiftId) group.shift_id = Object.keys(group.allocations || {})[0] || '';
  });
  project.groups = project.groups.filter((group) => Object.keys(group.allocations || {}).length > 0 || group.shift_id);
  await saveProject({ refresh: true, successMessage: 'Turno excluído.' });
  fillSettingsForm();
}

function attachEvents() {
  document.addEventListener('click', event => {
    const groupHours = event.target.closest('[data-configure-group-hours]');
    if (groupHours) {
      closeModal('ruleDialog');
      openGroupDialog(project.groups.find(g => g.id === groupHours.dataset.configureGroupHours));
      $('#groupHoursRows').scrollIntoView({block: 'center'});
      return;
    }
    if (!event.target.closest('[data-configure-interval]')) return;
    closeModal('ruleDialog');
    closeModal('groupDialog');
    setView('settings');
    $('#timingRules').scrollIntoView({block: 'center', behavior: 'smooth'});
  });
  document.addEventListener('click', event => {
    const close = event.target.closest('[data-close-modal]');
    if (close) { event.preventDefault(); closeModal(close.dataset.closeModal); }
    else if (event.target.classList.contains('modal-backdrop')) closeModal(event.target.id);
  });
  $$('.nav-item').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
  $('#settingsButton').addEventListener('click', () => setView('settings'));
  $('#projectSelect').addEventListener('change', (event) => switchProject(event.target.value));
  $('#newProjectButton').addEventListener('click', () => createProject(false));
  $('#newSubdivisionButton').addEventListener('click', () => createProject(true));
  $('#reuseGroupButton').addEventListener('click', reuseSavedGroup);
  $('#unlinkGroupButton').addEventListener('click', async () => {
    const linked = project.groups.filter(g => project.shared_group_links[g.id]);
    if (!linked.length) return notify('Esta subdivisão não tem grupos vinculados.');
    const choice = window.prompt('Qual grupo deve se tornar independente?\n' + linked.map((g,i) => `${i+1}. ${g.name}`).join('\n'));
    if (choice === null || !linked[Number(choice)-1]) return;
    delete project.shared_group_links[linked[Number(choice)-1].id];
    await saveProject();
    notify('Vínculo removido. O grupo foi preservado como cópia independente.');
  });
  $('#portfolioSelect').addEventListener('change', async event => {
    const projects = await apiRequest('/api/projects');
    const first = projects.find(p => p.portfolio_id === event.target.value);
    if (first) await switchProject(first.project_id);
  });
  $('#deleteProjectButton').addEventListener('click', removeCurrentProject);
  $('#addGroupButton').addEventListener('click', () => openGroupDialog());
  $('#addGroupPageButton').addEventListener('click', () => openGroupDialog());
  $('#prevMonthButton').addEventListener('click', () => changeMonth(-1));
  $('#nextMonthButton').addEventListener('click', () => changeMonth(1));
  $('#allMonthsButton').addEventListener('click', () => { project.selected_month = 0; $('#monthSelect').value = '0'; saveProject({ refresh: true }); });
  $('#toggleProjectOverview').addEventListener('click', () => {
    const details = $('#projectOverviewDetails');
    const hidden = details.hidden = !details.hidden;
    $('#toggleProjectOverview').textContent = hidden ? 'Mostrar' : 'Ocultar';
  });
  $('#monthSelect').addEventListener('change', () => {
    project.selected_month = Number($('#monthSelect').value);
    saveProject({ refresh: true });
  });
  $('#exportCsvButton').addEventListener('click', async () => {
    try {
      if (!saasMode) { window.location.href = '/api/export.csv'; return; }
      const result = await apiRequest('/api/export', {method:'POST', body:JSON.stringify(project)});
      window.location.assign(result.download_url);
    } catch(error) { notify(error.message, 'error'); }
  });
  $('#analysisRefreshButton').addEventListener('click', () => recalculate({ renderTimeline: false, renderAnalysis: true }));
  $('#saveSettingsButton').addEventListener('click', saveSettingsFromForm);
  $('#settingsForm').addEventListener('submit', saveSettingsFromForm);
  $('#optimizationPriorities').addEventListener('change', event => {
    const index = Number(event.target.dataset.priorityIndex);
    const order = JSON.parse($('#optimizationPriorities').dataset.order);
    const previousIndex = order.indexOf(event.target.value);
    [order[index], order[previousIndex]] = [order[previousIndex], order[index]];
    renderPriorities(order);
  });
  $('#ruleProfile').addEventListener('change', applyProfilePreset);
  $('#addShiftButton').addEventListener('click', addShift);
  $('#exportJsonButton').addEventListener('click', exportJson);
  $('#importJsonInput').addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    if (file) importJsonFile(file);
  });
  $('#issueFilter').addEventListener('change', (event) => {
    analysisFilter = event.target.value;
    renderIssues();
  });
  $('#deleteGroupButton').addEventListener('click', () => deleteGroup($('#groupId').value));
  $('#groupForm').addEventListener('input', updateCyclePreview);
  $('#groupForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    updateCyclePreview();
    if (!$('#groupForm').reportValidity()) return;
    const groupId = $('#groupId').value;
    const allocations = {};
    $$('[data-allocation-shift]').forEach((input) => {
      if (Number(input.value) > 0) allocations[input.dataset.allocationShift] = Number(input.value);
    });
    if (!Object.keys(allocations).length) return notify('Informe uma quantidade em pelo menos um turno.', 'error');
    const groupData = {
      id: groupId || `grupo-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`,
      name: $('#groupName').value.trim(),
      shift_id: Object.keys(allocations)[0],
      employee_count: allocations[Object.keys(allocations)[0]],
      allocations,
      automatic_shift_ids: [],
      work_hours_by_weekday: $$('[data-group-hour]').map(input => input.value === '' ? null : Number(input.value)),
      min_hours_by_weekday: $$('[data-group-min-hour]').map(input => Number(input.value)),
      max_hours_by_weekday: $$('[data-group-max-hour]').map(input => Number(input.value)),
      allow_hours_optimization: $('#groupOptimizeHours').checked,
      cycle_blocks: $('#groupCycleBlocks').value.trim() ? parseCycleBlocks($('#groupCycleBlocks').value) : null,
      cycle_days: $('#groupCycleDays').value === '' ? null : Number($('#groupCycleDays').value),
      work_days: Number($('#groupWorkDays').value),
      rest_days: Number($('#groupRestDays').value),
      cycle_anchor_weekday: $('#groupAnchorWeekday').value === '' ? null : Number($('#groupAnchorWeekday').value),
      cycle_anchor: $('#groupAnchorDate').value,
      cycle_phase_offset: Number($('#groupPhaseOffset').value),
      rotation_shift_ids: $('#groupRotation').checked ? Object.keys(allocations) : [],
      overrides: {},
    };
    if (!$('#groupForm').reportValidity()) return;
    if (groupData.min_hours_by_weekday.some((min, day) => min > groupData.max_hours_by_weekday[day])) return notify('O mínimo de horas não pode ser maior que o máximo do dia.', 'error');
    if (project.shifts.filter(s => allocations[s.id] > 0).some(s => groupData.work_hours_by_weekday.some(h => h != null && h > 0 && h + s.break_minutes / 60 > 24))) return notify('As horas do grupo somadas à pausa do turno não podem ultrapassar 24 horas.', 'error');
    if (groupData.rotation_shift_ids.length && (new Set(Object.values(allocations)).size > 1)) return notify('No revezamento, informe o mesmo tamanho fixo em todos os turnos alocados; use zero nos demais.', 'error');
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
  $('#timelineContainer').addEventListener('click', async (event) => {
    hideGroupContextMenu();
    if (Date.now() < suppressClickUntil) return;
    const actionButton = event.target.closest('[data-action]');
    if (actionButton) {
      const { action, id } = actionButton.dataset;
      if (action === 'group-menu') {
        event.stopPropagation();
        const rect = actionButton.getBoundingClientRect();
        showGroupContextMenu(id, rect.left, rect.bottom, actionButton.dataset.shiftId);
      }
      if (action === 'edit-group') openGroupDialog(project.groups.find((group) => group.id === id));
      if (action === 'delete-group') deleteGroup(id);
      if (action === 'show-group-rules') openGroupRuleDialog(id);
      if (action === 'shift-cycle') { const group = project.groups.find((item) => item.id === id); group.cycle_phase_offset = (group.cycle_phase_offset || 0) + Number(actionButton.dataset.direction); await saveProject({ refresh: true }); }
      if (action === 'move-layer') {
        const group = project.groups.find((item) => item.id === id); const shiftId = actionButton.dataset.shiftId;
        if (group && shiftId) {
          const groups = groupByShift(shiftId); const index = groups.findIndex(g => g.id === id); const target = index + Number(actionButton.dataset.direction);
          if (target >= 0 && target < groups.length) {
            [groups[index], groups[target]] = [groups[target], groups[index]];
            groups.forEach((g, layer) => { g.layer_by_shift ||= {}; g.layer_by_shift[shiftId] = layer; });
            await saveProject({refresh: true});
          }
        }
      }
      if (action === 'edit-demand') {
        const shift = project.shifts.find((item) => item.id === actionButton.dataset.shiftId);
        const current = shift.demand_by_date?.[actionButton.dataset.date] ?? shift.demand_by_weekday[parseIsoLocal(actionButton.dataset.date).getDay() === 0 ? 6 : parseIsoLocal(actionButton.dataset.date).getDay() - 1];
        const raw = window.prompt(`Demanda de ${shift.name} em ${actionButton.dataset.date}:`, current);
        if (raw !== null && Number.isInteger(Number(raw)) && Number(raw) >= 0) {
          shift.demand_by_date = shift.demand_by_date || {};
          shift.demand_by_date[actionButton.dataset.date] = Number(raw);
          await saveProject({ refresh: true, successMessage: 'Demanda diária atualizada.' });
        }
      }
      return;
    }
    const cell = event.target.closest('.timeline-cell');
    if (!cell) return;
    const group = project.groups.find((item) => item.id === cell.dataset.groupId);
    if (!group) return;
    const iso = cell.dataset.date;
    if (group.work_hours_by_weekday?.[weekdayIndexMondayFirst(parseIsoLocal(iso))] === 0) {
      notify('Este dia tem jornada de zero horas no grupo. Edite a jornada semanal para voltar a trabalhar nesse dia.', 'error');
      return;
    }
    setStatus(group, iso, !statusFor(group, iso));
    await saveProject({ refresh: true });
  });
  $('#timelineContainer').addEventListener('contextmenu', (event) => {
    const label = event.target.closest('.group-label-cell');
    const groupButton = label?.querySelector('[data-action="group-menu"]');
    if (!groupButton) return;
    event.preventDefault();
    showGroupContextMenu(groupButton.dataset.id, event.clientX, event.clientY, groupButton.dataset.shiftId);
  });
  $('#groupContextMenu').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-context-action]');
    if (!button) return;
    hideGroupContextMenu();
    const group = project.groups.find((item) => item.id === button.dataset.id);
    if (button.dataset.contextAction === 'rules') openGroupRuleDialog(group.id);
    if (button.dataset.contextAction === 'phase') {
      group.cycle_phase_offset = (group.cycle_phase_offset || 0) + Number(button.dataset.direction);
      await saveProject({refresh: true});
    }
    if (button.dataset.contextAction === 'layer') {
      const groups = groupByShift(button.dataset.shiftId);
      const index = groups.findIndex(g => g.id === group.id);
      const target = index + Number(button.dataset.direction);
      if (target >= 0 && target < groups.length) {
        [groups[index], groups[target]] = [groups[target], groups[index]];
        groups.forEach((g, layer) => { g.layer_by_shift ||= {}; g.layer_by_shift[button.dataset.shiftId] = layer; });
        await saveProject({refresh: true});
      }
    }
    if (button.dataset.contextAction === 'edit') openGroupDialog(group);
    if (button.dataset.contextAction === 'duplicate') duplicateGroup(button.dataset.id);
    if (button.dataset.contextAction === 'delete') deleteGroup(button.dataset.id);
  });
  document.addEventListener('click', hideGroupContextMenu);

  $('#timelineContainer').addEventListener('dragstart', (event) => {
    const cell = event.target.closest('.timeline-cell');
    if (!cell || statusFor(project.groups.find((group) => group.id === cell.dataset.groupId), cell.dataset.date) || project.groups.find(group => group.id === cell.dataset.groupId)?.work_hours_by_weekday?.[weekdayIndexMondayFirst(parseIsoLocal(cell.dataset.date))] === 0) {
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
    const button = event.target.closest('[data-action]');
    if (button?.dataset.action === 'rename-shift') handleRenameShift(button.dataset.id);
    if (button?.dataset.action === 'delete-shift') deleteShift(button.dataset.id);
  });
  $('#shiftSettingsList').addEventListener('input', (event) => {
    const card = event.target.closest('.shift-config-card');
    if (card) {
      $('[data-shift-hours-summary]', card).textContent = shiftHoursLabel({
        hours_per_day: $('[data-field="hours_per_day"]', card).value,
        break_minutes: $('[data-field="break_minutes"]', card).value,
        hours_include_break: $('[data-field="hours_include_break"]', card).value === 'true'
      }) + ' A validação do mínimo é uma opção separada.';
    }
    const input = event.target.closest('[data-demand-all]');
    if (!input || input.value === '') return;
    const shiftId = input.dataset.demandAll;
    $$(`[data-shift-id="${CSS.escape(shiftId)}"][data-field="demand"]`, $('#shiftSettingsList')).forEach((dayInput) => { dayInput.value = input.value; });
  });
  $('#groupsList').addEventListener('click', (event) => {
    const edit = event.target.closest('[data-group-edit]');
    const remove = event.target.closest('[data-group-delete]');
    const rules = event.target.closest('[data-group-rules]');
    if (edit) openGroupDialog(project.groups.find((group) => group.id === edit.dataset.groupEdit));
    if (remove) deleteGroup(remove.dataset.groupDelete);
    if (rules) openGroupRuleDialog(rules.dataset.groupRules);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') $$('.modal-backdrop:not([hidden])').forEach((modal) => closeModal(modal.id));
  });
}

const TIMING_FIELDS = [
  ['check_intershift_rest', 'Verificar descanso entre jornadas', 'checkbox'],
  ['min_intershift_hours', 'Descanso mínimo entre jornadas (h)', 'number', 0, 168, 0.25],
  ['check_breaks', 'Validar mínimo da pausa (não altera a conta de horas)', 'checkbox'],
  ['min_break_over_6h_minutes', 'Mínimo da pausa acima de 6 h efetivas (min)', 'number', 0, 240],
  ['min_break_over_4h_minutes', 'Mínimo da pausa acima de 4 até 6 h efetivas (min)', 'number', 0, 240]
];
const PERIOD_FIELDS = [
  ['weekly_max_hours', 'Máximo de horas em 7 dias', 'number', 0, 168, 0.5],
  ['min_rest_days_in_rolling_7', 'Folgas mínimas em 7 dias', 'number', 0, 7],
  ['max_consecutive_work_days', 'Máximo de dias consecutivos', 'number', 1, 31],
  ['min_sundays_off_per_month', 'Domingos de folga no mês', 'number', 0, 5],
  ['check_min_days_off_per_month', 'Verificar folgas mensais', 'checkbox'],
  ['min_days_off_per_month', 'Folgas mínimas no mês', 'number', 0, 31], ...TIMING_FIELDS
];
const COMPANY_FIELDS = [
  ['state', 'Estado (UF)', 'text'], ['city', 'Município', 'text'], ['sector', 'Setor', 'text'],
  ['category', 'Categoria profissional', 'text'], ['collective_agreement', 'Convenção / acordo coletivo', 'text']
];
function configFields(schema, values, prefix) {
  return schema.map(([key, label, type, min, max, step]) => {
    const id = `${prefix}-${key}`;
    if (type === 'checkbox') return `<div class="field checkbox-field"><label class="checkbox-label" for="${id}"><input id="${id}" data-config="${key}" type="checkbox" ${values[key] ? 'checked' : ''}><span>${escapeHtml(label)}</span></label></div>`;
    return `<div class="field"><label for="${id}">${escapeHtml(label)}</label><input id="${id}" data-config="${key}" type="${type}" value="${escapeHtml(values[key] ?? '')}" ${type === 'number' ? `min="${min}" max="${max}" step="${step || 1}" required` : ''}></div>`;
  }).join('');
}
function readConfig(root, schema, target) {
  for (const [key, , type] of schema) {
    const input = $(`[data-config="${key}"]`, root);
    target[key] = type === 'checkbox' ? input.checked : type === 'number' ? Number(input.value) : input.value.trim();
  }
}
function fillCompanyAndRules() {
  $('#companyFields').innerHTML = configFields(COMPANY_FIELDS, project.company || {}, 'company');
  $('#timingRules').innerHTML = configFields(TIMING_FIELDS, project.rules, 'timing');
  renderRulePeriods();
}
function renderRulePeriods() {
  $('#rulePeriods').innerHTML = (project.rule_periods || []).map((period, index) => `<article class="rule-period" data-period="${index}"><div class="button-row"><strong>Vigência ${index + 1}</strong><button class="button button-danger-quiet" type="button" data-remove-period="${index}">Remover</button></div><div class="form-grid"><div class="field"><label>Início<input data-period-date type="date" value="${escapeHtml(period.effective_from)}" required></label></div><div class="field"><label>Nome da regra / cenário<input data-period-label value="${escapeHtml(period.label)}" required></label></div><div class="field field-span-2"><label>Fonte / referência<input data-period-source value="${escapeHtml(period.source)}"></label></div>${configFields(PERIOD_FIELDS, period.rules, `period-${index}`)}</div></article>`).join('') || '<p>Nenhuma mudança programada. Os parâmetros atuais valem para todo o ano.</p>';
}
function readPeriods() {
  return $$('.rule-period').map((card) => {
    const original = project.rule_periods[Number(card.dataset.period)];
    const period = structuredClone(original);
    period.effective_from = $('[data-period-date]', card).value;
    period.label = $('[data-period-label]', card).value.trim();
    period.source = $('[data-period-source]', card).value.trim();
    readConfig(card, PERIOD_FIELDS, period.rules);
    return period;
  });
}
function readCompanyAndRules() {
  const periods = readPeriods();
  if (new Set(periods.map(p => p.effective_from)).size !== periods.length) throw new Error('Cada vigência deve começar em uma data diferente.');
  project.company ||= {country: 'BR'};
  readConfig($('#companyFields'), COMPANY_FIELDS, project.company);
  readConfig($('#timingRules'), TIMING_FIELDS, project.rules);
  project.rule_periods = periods;
}
function parseDemandDates(text) {
  const result = {};
  for (const line of text.split('\n').map(l => l.trim()).filter(Boolean)) {
    const match = /^(\d{4}-\d{2}-\d{2})\s*=\s*(\d+)$/.exec(line);
    if (!match || !Number.isSafeInteger(Number(match[2]))) throw new Error(`Demanda inválida: ${line}. Use AAAA-MM-DD=quantidade.`);
    if (Object.hasOwn(result, match[1])) throw new Error(`Data de demanda repetida: ${match[1]}.`);
    result[match[1]] = Number(match[2]);
  }
  return result;
}
function allocationsLabel(group) {
  if (!group) return '—';
  return project.shifts.filter(s => Object.hasOwn(group.allocations, s.id)).map(s => `${s.name}: ${group.allocations[s.id]}`).join(' · ') || 'Sem pessoas alocadas';
}
function attachRulePeriodEvents() {
  $('#addRulePeriodButton').addEventListener('click', () => {
    project.rule_periods = readPeriods();
    project.rule_periods.push({effective_from: `${project.year}-07-01`, label: 'Novo cenário', source: '', rules: structuredClone(project.rules)});
    renderRulePeriods();
  });
  $('#rulePeriods').addEventListener('click', event => {
    const remove = event.target.closest('[data-remove-period]');
    if (!remove) return;
    project.rule_periods = readPeriods().filter((_, index) => index !== Number(remove.dataset.removePeriod));
    renderRulePeriods();
  });
}
let optimizationProposal = null;
let optimizationSnapshot = null;
let optimizationHoursAllowed = false;
let optimizationExisting = false;
let optimizationOptions = {};

function equalProjectValue(left, right) {
  if (left === right) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) && equalProjectValue(left[key], right[key]));
}
let optimizationSolutions = [];
let selectedOptimizationId = null;
let optimizationResponse = null;

function renderOptimizationResult(result) {
  optimizationResponse = result;
  optimizationSolutions = [...(result.solutions || [])].sort((left, right) => {
    if ((left.business_acceptable === false) !== (right.business_acceptable === false)) return left.business_acceptable === false ? 1 : -1;
    const a = left.ranking || [], b = right.ranking || [];
    for (let index = 0; index < Math.max(a.length, b.length); index++) { const difference = Number(a[index] || 0) - Number(b[index] || 0); if (difference) return difference; }
    return 0;
  });
  if (!optimizationSolutions.some(solution => String(solution.id) === selectedOptimizationId)) selectedOptimizationId = optimizationSolutions.length ? String(optimizationSolutions[0].id) : null;
  const selected = optimizationSolutions.find(solution => String(solution.id) === selectedOptimizationId);
  optimizationProposal = selected || null;
  const warnings = result.warnings || [];
  const box = $('#optimizeResult');
  box.hidden = false;
  const metric = (solution, name, fallback = '—') => solution.metrics?.[name] ?? fallback;
  box.innerHTML = `<h3>${optimizationSolutions.length} alternativa(s) encontrada(s)</h3><p>${escapeHtml(result.message || '')}</p><p>Limite solicitado: ${result.solution_limit ?? $('#optimizeSolutions').value} alternativa(s). ${(result.limit_reached || result.truncated) ? 'O limite de alternativas foi atingido.' : ''} ${result.search_complete ? 'A busca terminou no universo configurado.' : 'A busca não esgotou todas as combinações de grupos e perfis de horas; respeitou o prazo e os limites configurados.'} A lista inclui a escala atual e não é exaustiva.</p><p>A ordem compara: ${escapeHtml((result.priorities || Object.keys(PRIORITY_LABELS)).map(key => PRIORITY_LABELS[key]).join(' → '))}.</p>${result.scope ? `<p>${escapeHtml(result.scope)}</p>` : ''}${warnings.length ? `<div class="notice notice-warning"><div><strong>Atenção às verificações configuradas</strong><ul>${warnings.map(warning => `<li>${escapeHtml(warning)}</li>`).join('')}</ul></div></div>` : ''}<div class="table-wrap"><table><thead><tr><th>Escolher</th><th>Alternativa</th><th>Déficit pessoas-dia</th><th>Horas-pessoa faltantes</th><th>Violações</th><th>Tipos de escala</th><th>Custo mensal (R$)</th><th>Grupos</th><th>Excedente pessoas-dia</th><th>Pessoas</th></tr></thead><tbody>${optimizationSolutions.map((solution, index) => `<tr class="${String(solution.id) === selectedOptimizationId ? 'selected-alternative' : ''}"><td><input type="radio" name="optimizationSolution" aria-label="Selecionar ${escapeHtml(solution.baseline ? 'Escala atual' : solution.label || `Alternativa ${index + 1}`)}" data-solution-id="${escapeHtml(solution.id)}" ${String(solution.id) === selectedOptimizationId ? 'checked' : ''}></td><th>${escapeHtml(solution.baseline ? 'Escala atual' : solution.label || `Alternativa ${index + 1}`)}</th><td>${metric(solution, 'deficit_staff_days')}</td><td>${metric(solution, 'deficit_work_hours', 0)}</td><td>${metric(solution, 'rule_violation_count')}</td><td>${metric(solution, 'pattern_count')}</td><td>${metric(solution, 'monthly_staff_cost', 0)}</td><td>${metric(solution, 'group_count', solution.project?.groups.length || 0)}</td><td>${metric(solution, 'surplus_staff_days')}</td><td>${metric(solution, 'people_total')}</td></tr>`).join('')}</tbody></table></div>${selected ? renderSelectedAlternative(selected) : '<p>Nenhuma alternativa retornada.</p>'}`;
}
function renderSelectedAlternative(solution) {
  const groups = solution.project?.groups || [];
  const shifts = solution.project?.shifts || [];
  const issues = Array.isArray(solution.issues) ? solution.issues : [...(solution.issues?.rule_issues || []), ...(solution.issues?.coverage_issues || [])];
  const existingIds = new Set(JSON.parse(optimizationSnapshot).groups.map(group => group.id));
  const added = groups.filter(group => !existingIds.has(group.id)).length;
  return `<h3>${escapeHtml(solution.baseline ? 'Escala atual' : solution.label || 'Alternativa selecionada')}</h3><p>${added} novo(s) grupo(s). ${(solution.group_changes || []).length} grupo(s) atual(is) ajustado(s). ${(solution.hour_changes || []).length} grupo(s) com jornadas ajustadas.${issues.length ? ` Solução com pendências: esta alternativa apresenta ${issues.length} achado(s); revise os detalhes antes de aplicar.` : ' Confira as métricas e as verificações habilitadas antes de aplicar.'}</p>${solution.metrics?.limit_violation_count ? `<div class="notice notice-warning"><div><strong>Limites excedidos: ${solution.metrics.limit_violation_count}</strong><p>Confira os limites de grupos e pessoas e os achados desta alternativa.</p></div></div>` : ''}<div class="table-wrap"><table><thead><tr><th>Grupo</th><th>Origem</th><th>Turno / pessoas</th><th>Ciclo</th><th>Referência / fase</th><th>Horas efetivas · Seg a Dom</th></tr></thead><tbody>${groups.map(group => `<tr><th>${escapeHtml(group.name)}</th><td>${existingIds.has(group.id) ? (solution.group_changes || []).some(change => change.group_id === group.id) ? 'Ajustado' : 'Atual preservado' : 'Novo'}</td><td>${escapeHtml(shifts.filter(shift => (group.allocations || {})[shift.id] > 0).map(shift => `${shift.name}: ${group.allocations[shift.id]}`).join(' · '))}</td><td>${cycleLabel(group)}</td><td>${escapeHtml(group.cycle_anchor)} / ${group.cycle_phase_offset || 0}</td><td>${escapeHtml((group.work_hours_by_weekday || Array(7).fill(null)).map((value, day) => `${WEEKDAY_SHORT[day]}: ${value == null ? 'turno' : value + ' h'}`).join(' · '))}</td></tr>`).join('')}</tbody></table></div><div class="button-row"><button type="button" id="applyOptimizationButton" class="button button-primary" ${solution.business_acceptable === false ? 'disabled title="A escala atual ultrapassa os limites da empresa"' : ''}>Aplicar alternativa</button><button type="button" id="exportOptimizationButton" class="button button-secondary">Exportar alternativa JSON</button></div><details><summary>Achados desta alternativa (${issues.length})</summary>${issues.length ? `<div class="alternative-issues">${issues.map(issue => `<article><strong>${escapeHtml(issue.title || issue.code || 'Achado')}</strong><p>${escapeHtml(issue.message || issue.detail || '')}</p><small>${escapeHtml([issue.date || issue.first_window_start || (issue.month ? MONTH_NAMES[issue.month - 1] : ''), issue.group_name || groups.find(group => group.id === issue.group_id)?.name || issue.group_id, issue.shift_name || shifts.find(shift => shift.id === issue.shift_id)?.name || issue.shift_id].filter(Boolean).join(' · '))}</small></article>`).join('')}</div>` : '<p>Nenhum achado retornado nas verificações habilitadas.</p>'}</details>${solution.stages ? `<details><summary>Etapas da busca</summary><pre>${escapeHtml(JSON.stringify(solution.stages, null, 2))}</pre></details>` : ''}`;
}
function attachOptimizationEvents() {
  function openOptimization(existing) {
    optimizationExisting = existing;
    $('#existingOptimizationPermissions').hidden = !existing;
    $('#optimizeDialogTitle').textContent = existing ? 'Otimizar subdivisão atual' : 'Buscar complementos';
    $('#optimizationModeDescription').textContent = existing ? 'Otimiza os grupos já cadastrados, considerando seus parâmetros e as permissões abaixo.' : 'Busca novos grupos para complementar a escala. Preserva os ciclos e as quantidades dos grupos atuais.';
    $('#optimizeResult').hidden = true;
    const saved = project.search_options || {};
    $('#automaticCycles').checked = saved.automatic_cycles ?? true;
    $('#mixedCycles').checked = saved.allow_mixed_cycles_per_shift ?? true;
    $('#maxCycleDays').value = saved.max_cycle_days ?? 7;
    const fields = {optimizeHours:'optimize_work_hours', optimizeHoursStep:'hours_step_minutes', optimizeMinHours:'new_group_min_hours', optimizeMaxHours:'new_group_max_hours', optimizeGroupSize:'max_group_size', optimizePeople:'max_employees', optimizeGroups:'max_groups', optimizeSeconds:'time_limit_seconds', optimizeSolutions:'max_solutions'};
    for (const [id,key] of Object.entries(fields)) { if (saved[key] !== undefined) { const input = $('#' + id); if (input.type === 'checkbox') input.checked = saved[key]; else input.value = saved[key]; } }
    if (saved.cycles) $('#optimizeCycles').value = saved.cycles.map(c => (c.cycle_blocks || [c.work_days,c.rest_days]).join('x')).join(', ');
    $('#optimizeCycles').disabled = false;
    renderBusinessPolicy('searchBusiness', 'searchBusiness');
    $('#optimizeDialog').hidden = false;
  }
  $('#optimizeCycles').addEventListener('input', () => { $('#automaticCycles').checked = false; });
  $('#openOptimizeButton').addEventListener('click', () => openOptimization(false));
  $('#optimizeExistingButton').addEventListener('click', () => openOptimization(true));
  $('#optimizeForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (!$('#optimizeForm').reportValidity()) return;
    const button = $('#runOptimizeButton');
    try {
      const automatic_cycles = $('#automaticCycles').checked;
      const cycles = automatic_cycles ? undefined : $('#optimizeCycles').value.split(',').map(value => ({cycle_blocks: parseCycleBlocks(value)}));
      const options = {automatic_cycles, max_cycle_days:Number($('#maxCycleDays').value), allow_mixed_cycles_per_shift:$('#mixedCycles').checked, optimize_existing: optimizationExisting, change_employee_counts: $('#optimizeExistingCounts').checked, change_cycles: $('#optimizeExistingCycles').checked, cycles, max_group_size: Number($('#optimizeGroupSize').value), max_employees: Number($('#optimizePeople').value), max_groups: Number($('#optimizeGroups').value), time_limit_seconds: Number($('#optimizeSeconds').value), max_solutions: Number($('#optimizeSolutions').value), optimize_work_hours: $('#optimizeHours').checked, hours_step_minutes: Number($('#optimizeHoursStep').value), new_group_min_hours: Number($('#optimizeMinHours').value), new_group_max_hours: Number($('#optimizeMaxHours').value)};
      optimizationOptions = structuredClone(options);
      optimizationProposal = null;
      optimizationSnapshot = JSON.stringify(project);
      project.business_constraints = readBusinessPolicy('searchBusiness');
      project.search_options = options;
      await saveProject();
      optimizationSnapshot = JSON.stringify(project);
      optimizationHoursAllowed = options.optimize_work_hours;
      $('#optimizeResult').hidden = true;
      button.disabled = true;
      $('#optimizeProgress').textContent = 'Verificando ciclos e buscando grupos…';
      const result = await apiRequest('/api/optimize', {method: 'POST', body: JSON.stringify({project: JSON.parse(optimizationSnapshot), options})});
      selectedOptimizationId = null;
      renderOptimizationResult(result);
    } catch (error) { notify(`Falha na busca: ${error.message}`, 'error', 7000); }
    finally { button.disabled = false; $('#optimizeProgress').textContent = ''; }
  });
  $('#optimizeResult').addEventListener('change', event => {
    const selected = event.target.closest('[data-solution-id]');
    if (selected) { selectedOptimizationId = selected.dataset.solutionId; renderOptimizationResult(optimizationResponse); }
  });
  $('#optimizeResult').addEventListener('click', async event => {
    const action = event.target.closest('button')?.id;
    if (!optimizationProposal) return;
    if (action === 'exportOptimizationButton') {
      const url = URL.createObjectURL(new Blob([JSON.stringify(optimizationProposal.project, null, 2)], {type: 'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = `proposta-escala-${project.year}.json`; link.click(); URL.revokeObjectURL(url);
    }
    if (action === 'applyOptimizationButton') {
      const button = event.target.closest('button');
      try {
        if (JSON.stringify(project) !== optimizationSnapshot) throw new Error('O projeto foi alterado depois da busca. Busque novamente antes de aplicar.');
        button.disabled = true;
        const previous = structuredClone(project);
        const candidate = optimizationProposal.project;
        if (!previous.groups.every(group => candidate.groups.some(other => {
          if (other.id !== group.id) return false;
          if (equalProjectValue(other, group)) return true;
          const allowed = {...other};
          if (optimizationHoursAllowed && group.allow_hours_optimization) allowed.work_hours_by_weekday = group.work_hours_by_weekday;
          if (optimizationOptions.optimize_existing && optimizationOptions.change_employee_counts) {
            allowed.allocations = group.allocations; allowed.employee_count = group.employee_count;
          }
          if (optimizationOptions.optimize_existing && optimizationOptions.change_cycles) {
            allowed.cycle_blocks = group.cycle_blocks; allowed.cycle_phase_offset = group.cycle_phase_offset;
          }
          return equalProjectValue(allowed, group);
        }))) throw new Error('A alternativa modificou grupos atuais. Busque novamente antes de aplicar.');
        project = structuredClone(candidate);
        try { await saveProject({refresh: true}); }
        catch (error) { project = previous; throw error; }
        optimizationProposal = null;
        closeModal('optimizeDialog');
        notify('Alternativa aplicada e salva, preservando os grupos atuais. Confira o calendário e as validações.');
      } catch (error) { button.disabled = false; notify(error.message, 'error', 7000); }
    }
  });
}

attachEvents();
attachRulePeriodEvents();
attachOptimizationEvents();
async function initializeSession() {
  try {
    const health = await apiRequest('/api/health');
    saasMode = health.mode === 'saas';
    if (saasMode) {
      const identity = await apiRequest('/api/auth/me');
      saasRole = identity.role;
      document.body.classList.toggle('is-readonly', saasRole === 'viewer');
      const account = document.getElementById('accountLink'); if (account) { account.hidden = false; account.textContent = identity.name; }
      document.querySelector('.version-label').textContent = 'VERSÃO 0.2.0 RC1 · SAAS';
    }
    await loadProject();
  } catch(error) { notify(error.message, 'error', 8000); }
}
initializeSession();

// Permission enforcement remains on the API; this avoids offering edits to readers.
for (const eventName of ['click','dragstart','contextmenu','submit','change']) {
  document.addEventListener(eventName, event => {
    if (!saasMode || saasRole !== 'viewer') return;
    const target = event.target;
    const action = target.closest('[data-action]');
    const readOnly = target.closest('.timeline-cell, .group-tools, #view-settings, #groupDialog, #importJsonInput, #addGroupButton, #newProjectButton, #newSubdivisionButton, #deleteProjectButton, #reuseGroupButton, #unlinkGroupButton, #openOptimizeButton, #optimizeExistingButton');
    if (readOnly || (action && action.dataset.action !== 'show-group-rules')) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
}
