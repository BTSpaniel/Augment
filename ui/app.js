const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const els = {
  messages: qs('#messages'),
  form: qs('#composer'),
  input: qs('#input'),
  sessionList: qs('#session-list'),
  sessionSearch: qs('#session-search'),
  sessionsCount: qs('#sessions-count'),
  sessionTitle: qs('#session-title'),
  sessionPill: qs('#session-pill'),
  sessionProviderSelect: qs('#session-provider-select'),
  sessionModelSelect: qs('#session-model-select'),
  sessionRefreshModelsBtn: qs('#session-refresh-models-btn'),
  modelIndicator: qs('#model-indicator'),
  providerIndicator: qs('#providers-health'),
  agentName: qs('#active-agent-name'),
  agentDot: qs('#active-agent-dot'),
  inspectorTabs: qsa('.lab-inspector__tab'),
  inspectorPanels: qsa('.lab-inspector__panel'),
  navItems: qsa('.lab-nav__item'),
  pages: qsa('.lab-page'),
  statusSession: qs('#status-session'),
  statusTokens: qs('#status-tokens'),
  statusContext: qs('#status-context'),
  statusbarDot: qs('#statusbar-dot'),
  statusbarState: qs('#statusbar-state'),
  inspectorStatus: qs('#insp-status'),
  inspectorStatusRow: qs('#insp-status-row'),
  inspectorAvatar: qs('#insp-avatar'),
  inspectorName: qs('#insp-name'),
  inspectorRole: qs('#insp-role'),
  inspectorRoleRow: qs('#insp-role-row'),
  inspectorProfileName: qs('#insp-profile-name'),
  inspectorModel: qs('#insp-model'),
  inspectorProvider: qs('#insp-provider'),
  inspectorTools: qs('#insp-tools'),
  inspectorToolsPage: qs('#insp-tools-page'),
  inspectorMemory: qs('#insp-memory'),
  inspectorLogs: qs('#insp-logs'),
  capTools: qs('#cap-tools'),
  capSuccess: qs('#cap-success'),
  capRuns: qs('#cap-runs'),
  capSessions: qs('#cap-sessions'),
  capResumed: qs('#cap-resumed'),
  ctxOriginal: qs('#ctx-original'),
  ctxFinal: qs('#ctx-final'),
  ctxTruncated: qs('#ctx-truncated'),
  mailboxForm: qs('#mailbox-form'),
  mailboxInput: qs('#mailbox-input'),
  mailboxList: qs('#mailbox-list'),
  memoryList: qs('#memory-list'),
  toolpacksGrid: qs('#toolpacks-grid'),
  skillpacksStats: qs('#skillpacks-stats'),
  skillpacksDormant: qs('#skillpacks-dormant'),
  skillpacksAdaptive: qs('#skillpacks-adaptive'),
  skillpacksGenerateBtn: qs('#skillpacks-generate-btn'),
  skillpacksRefreshBtn: qs('#skillpacks-refresh-btn'),
  codexCard: qs('#codex-card'),
  codexDot: qs('#codex-dot'),
  codexVersion: qs('#codex-version'),
  codexState: qs('#codex-state'),
  codexPending: qs('#codex-pending'),
  codexVerificationRow: qs('#codex-verification-row'),
  codexVerificationLink: qs('#codex-verification-link'),
  codexUserCodeRow: qs('#codex-user-code-row'),
  codexUserCode: qs('#codex-user-code'),
  codexAuthLink: qs('#codex-auth-link'),
  codexLoginBtn: qs('#codex-login-btn'),
  codexRefreshBtn: qs('#codex-refresh-btn'),
  codexCancelBtn: qs('#codex-cancel-btn'),
  logsList: qs('#logs-list'),
  providerCards: qs('#provider-cards'),
  addProviderSelect: qs('#add-provider-select'),
  addProviderBtn: qs('#add-provider-btn'),
  agentForm: qs('#agent-form'),
  agentNameInput: qs('#agent-name-input'),
  agentRoleInput: qs('#agent-role-input'),
  agentDescriptionInput: qs('#agent-description-input'),
  agentPersonaInput: qs('#agent-persona-input'),
  agentNameCounter: qs('#agent-name-counter'),
  agentRoleCounter: qs('#agent-role-counter'),
  agentDescriptionCounter: qs('#agent-description-counter'),
  agentAvatar: qs('#agent-avatar'),
  agentDisplayName: qs('#agent-display-name'),
  agentDisplayRole: qs('#agent-display-role'),
  agentDisplayStatus: qs('#agent-display-status'),
  agentSaveBtn: qs('#agent-save-btn'),
  agentResetSoulBtn: qs('#agent-reset-soul-btn'),
  agentTabs: qsa('[data-agent-tab]'),
  agentPanels: qsa('[data-agent-panel]'),
  agentSoulEnabled: qs('#agent-soul-enabled'),
  agentSoulSoul: qs('#agent-soul-soul'),
  agentSoulPersonality: qs('#agent-soul-personality'),
  agentSoulHistory: qs('#agent-soul-history'),
  agentSoulPath: qs('#agent-soul-path'),
  agentSoulLessonForm: qs('#agent-soul-lesson-form'),
  agentSoulLessonInput: qs('#agent-soul-lesson-input'),
  newSessionBtn: qs('#new-session-btn'),
  newProjectBtn: qs('#new-project-btn'),
  sidebarCollapseBtn: qs('.lab-sidebar__collapse'),
  sidebar: qs('.lab-sidebar'),
  welcomeQuickButtons: qsa('.lab-welcome-card__btn[data-quick]'),
  composerQuickButtons: qsa('.lab-composer__icon[data-quick]'),
  clearSessionBtn: qs('#clear-session-btn'),
  attachImageBtn: qs('#attach-image-btn'),
  attachImageInput: qs('#attach-image-input'),
  composeAttachments: qs('#compose-attachments'),
  thinkingStartBtn: qs('#thinking-start-btn'),
  thinkingStopBtn: qs('#thinking-stop-btn'),
  thinkingRefreshBtn: qs('#thinking-refresh-btn'),
  thinkingIntervalInput: qs('#thinking-interval-input'),
  thinkingStatus: qs('#thinking-status'),
  thinkingLog: qs('#thinking-log'),
};

const state = {
  sessionId: localStorage.getItem('augment.sessionId') || '',
  sessions: [],
  presets: [],
  profiles: [],
  defaultId: '',
  removedPresets: [],
  health: {},
  agent: null,
  // Active streaming chats keyed by session id so that switching sessions
  // mid-stream doesn't destroy the in-flight bubble — we re-attach it when
  // the user navigates back. Each entry: { userEl, bubble }.
  activeStreams: new Map(),
  // Images attached to the *next* chat message. Each entry: { dataUrl, name }.
  pendingImages: [],
  // Whether the active provider advertises vision capability.
  visionEnabled: false,
};

document.addEventListener('DOMContentLoaded', boot);

async function boot() {
  bindEvents();
  await Promise.all([loadPresets(), loadProviders(), loadAgent(), loadMemory(), loadSessions()]);
  if (state.sessionId) await openSession(state.sessionId, { force: true });
  setStatusbar('idle', 'Idle');
}

function bindEvents() {
  els.newSessionBtn.addEventListener('click', startNewSession);
  els.newProjectBtn?.addEventListener('click', startNewProject);
  els.sidebarCollapseBtn?.addEventListener('click', toggleSidebar);
  els.welcomeQuickButtons.forEach((btn) =>
    btn.addEventListener('click', () => handleQuickAction(btn.dataset.quick)),
  );
  els.composerQuickButtons.forEach((btn) =>
    btn.addEventListener('click', (event) => {
      event.preventDefault();
      handleQuickAction(btn.dataset.quick);
    }),
  );
  els.clearSessionBtn.addEventListener('click', clearCurrentSession);
  els.agentForm.addEventListener('submit', saveAgentProfile);
  els.agentSaveBtn?.addEventListener('click', saveAgentProfile);
  els.agentResetSoulBtn?.addEventListener('click', resetAgentSoul);
  els.agentSoulEnabled?.addEventListener('change', toggleAgentSoulEnabled);
  els.agentSoulSoul?.addEventListener('input', () => scheduleSoulSave());
  els.agentSoulPersonality?.addEventListener('input', () => scheduleSoulSave());
  els.agentSoulHistory?.addEventListener('input', () => scheduleSoulSave());
  els.agentSoulLessonForm?.addEventListener('submit', appendSoulLesson);
  els.agentTabs.forEach((tab) => tab.addEventListener('click', () => openAgentTab(tab.dataset.agentTab)));
  for (const [input, counter, max] of [
    [els.agentNameInput, els.agentNameCounter, 50],
    [els.agentRoleInput, els.agentRoleCounter, 75],
    [els.agentDescriptionInput, els.agentDescriptionCounter, 280],
  ]) {
    if (!input || !counter) continue;
    input.addEventListener('input', () => { counter.textContent = `${input.value.length}/${max}`; });
  }
  els.mailboxForm.addEventListener('submit', addMailboxNote);
  els.sessionSearch.addEventListener('input', renderSessions);
  els.input.addEventListener('input', resizeInput);
  els.input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      els.form.requestSubmit();
    }
  });
  els.form.addEventListener('submit', submitChat);
  els.inspectorTabs.forEach((tab) => tab.addEventListener('click', () => openInspectorTab(tab.dataset.tab)));
  els.navItems.forEach((item) => item.addEventListener('click', () => openPage(item.dataset.page)));
  els.addProviderBtn.addEventListener('click', addProviderFromSelect);
  els.discoverBtn?.addEventListener('click', runDiscovery);
  els.skillpacksRefreshBtn?.addEventListener('click', loadSkillPacks);
  els.skillpacksGenerateBtn?.addEventListener('click', generateAdaptiveSkills);
  els.codexLoginBtn?.addEventListener('click', startCodexLogin);
  els.codexRefreshBtn?.addEventListener('click', loadCodex);
  els.codexCancelBtn?.addEventListener('click', cancelCodexLogin);
  els.sessionProviderSelect?.addEventListener('change', onSessionProviderChange);
  els.sessionModelSelect?.addEventListener('change', onSessionModelChange);
  els.sessionRefreshModelsBtn?.addEventListener('click', onSessionRefreshModels);
  bindComposerPickers();
  els.attachImageBtn?.addEventListener('click', () => els.attachImageInput?.click());
  els.attachImageInput?.addEventListener('change', onAttachImageChange);
  els.input?.addEventListener('paste', onComposerPaste);
  els.input?.addEventListener('dragover', onComposerDragOver);
  els.input?.addEventListener('drop', onComposerDrop);
  els.thinkingStartBtn?.addEventListener('click', startThinking);
  els.thinkingStopBtn?.addEventListener('click', stopThinking);
  els.thinkingRefreshBtn?.addEventListener('click', loadThinking);
}

async function runDiscovery() {
  if (els.discoverBtn) els.discoverBtn.disabled = true;
  try {
    const data = await request('/api/providers/discover', { method: 'POST' });
    await loadProviders();
    await loadAgent();
    const added = (data && data.added) || [];
    if (added.length) {
      flash(`Discovered ${added.length} provider${added.length === 1 ? '' : 's'}`);
    } else {
      flash('No new providers found');
    }
  } catch (error) {
    flash(`Discover failed: ${error.message}`);
  } finally {
    if (els.discoverBtn) els.discoverBtn.disabled = false;
  }
}

async function restoreRemovedPreset(presetId) {
  try {
    await request(`/api/providers/discover/restore/${encodeURIComponent(presetId)}`, { method: 'POST' });
    await loadProviders();
    await loadAgent();
    flash(`Restored ${presetId}`);
  } catch (error) {
    flash(`Restore failed: ${error.message}`);
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.text()).slice(0, 800));
  return response.json();
}

/* ── Presets ──────────────────────────────────────────────────────── */
async function loadPresets() {
  try {
    const data = await request('/api/providers/presets');
    state.presets = data.presets || [];
  } catch (error) {
    state.presets = [];
  }
  renderPresetDropdown();
}

function renderPresetDropdown() {
  if (!els.addProviderSelect) return;
  const options = ['<option value="">Add Provider…</option>']
    .concat(state.presets.map((preset) => `<option value="${esc(preset.id)}">${esc(preset.name)}</option>`));
  els.addProviderSelect.innerHTML = options.join('');
}

async function addProviderFromSelect() {
  const preset = els.addProviderSelect.value;
  if (!preset) {
    flash('Pick a preset to add');
    return;
  }
  try {
    await request('/api/providers/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset }),
    });
    els.addProviderSelect.value = '';
    await loadProviders();
    flash(`Added ${preset}`);
  } catch (error) {
    flash(`Add failed: ${error.message}`);
  }
}

/* ── Providers ────────────────────────────────────────────────────── */
async function loadProviders() {
  try {
    const data = await request('/api/providers');
    state.profiles = data.profiles || [];
    state.defaultId = data.default_id || '';
    state.removedPresets = data.removed_presets || [];
    state.health = data.health || {};
    const defaultProfile = state.profiles.find((profile) => profile.id === state.defaultId) || state.profiles[0] || {};
    els.providerIndicator.textContent = providerHealthText(defaultProfile);
    els.modelIndicator.textContent = defaultProfile.model || '—';
    renderSessionPicker(defaultProfile);
    updateVisionAvailability(defaultProfile);
  } catch (error) {
    state.profiles = [];
    state.removedPresets = [];
    els.providerIndicator.textContent = 'Unavailable';
  }
  renderProviderCards();
  renderRemovedPresets();
}

function renderRemovedPresets() {
  if (!els.removedPresets) return;
  if (!state.removedPresets || !state.removedPresets.length) {
    els.removedPresets.innerHTML = '';
    return;
  }
  els.removedPresets.innerHTML = '<span class="lab-removed-presets__label">Restore removed:</span>'
    + state.removedPresets.map((preset) => `<button type="button" data-restore="${esc(preset)}">+ ${esc(preset)}</button>`).join('');
  qsa('button[data-restore]', els.removedPresets).forEach((button) => {
    button.addEventListener('click', () => restoreRemovedPreset(button.dataset.restore));
  });
}

function providerHealthText(profile) {
  if (!profile) return '—';
  if (profile.has_inline_key || profile.has_env_key) return 'Configured';
  if (!profile.key_required) return 'Local';
  return 'Missing key';
}

function renderSessionPicker(defaultProfile) {
  const providerSel = els.sessionProviderSelect;
  const modelSel = els.sessionModelSelect;
  if (!providerSel || !modelSel) return;
  if (!state.profiles.length) {
    providerSel.innerHTML = '<option value="">No providers</option>';
    modelSel.innerHTML = '<option value="">—</option>';
    providerSel.disabled = true;
    modelSel.disabled = true;
    return;
  }
  providerSel.disabled = false;
  modelSel.disabled = false;
  providerSel.innerHTML = state.profiles.map((p) => {
    const label = p.name || p.id;
    return `<option value="${esc(p.id)}" ${p.id === state.defaultId ? 'selected' : ''}>${esc(label)}</option>`;
  }).join('');
  const active = defaultProfile || state.profiles[0] || {};
  const models = (active.models && active.models.length) ? active.models : (active.model ? [active.model] : []);
  if (!models.length) {
    modelSel.innerHTML = `<option value="${esc(active.model || '')}">${esc(active.model || '—')}</option>`;
  } else {
    modelSel.innerHTML = models.map((m) => `<option value="${esc(m)}" ${m === active.model ? 'selected' : ''}>${esc(m.split('/').pop())}</option>`).join('');
  }
  // Mirror the same selection into the composer's pretty picker pills.
  syncComposerPickers();
}

async function onSessionProviderChange() {
  const id = els.sessionProviderSelect?.value;
  if (!id || id === state.defaultId) return;
  try {
    await request(`/api/providers/${encodeURIComponent(id)}/default`, { method: 'POST' });
    await loadProviders();
    await loadAgent();
    flash(`Switched provider → ${id}`);
  } catch (error) {
    flash(`Provider switch failed: ${error.message}`);
  }
}

async function onSessionModelChange() {
  const model = els.sessionModelSelect?.value;
  if (!model) return;
  const profileId = state.defaultId || (state.profiles[0] && state.profiles[0].id);
  if (!profileId) return;
  try {
    await request(`/api/providers/${encodeURIComponent(profileId)}/model`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    await loadProviders();
    await loadAgent();
    flash(`Model → ${model.split('/').pop()}`);
  } catch (error) {
    flash(`Model switch failed: ${error.message}`);
  }
}

async function onSessionRefreshModels() {
  const profileId = state.defaultId || (state.profiles[0] && state.profiles[0].id);
  if (!profileId) {
    flash('No active provider');
    return;
  }
  const btn = els.sessionRefreshModelsBtn;
  if (btn) btn.disabled = true;
  try {
    await request(`/api/providers/${encodeURIComponent(profileId)}/models/refresh`, { method: 'POST' });
    await loadProviders();
    flash(`Refreshed models for ${profileId}`);
  } catch (error) {
    flash(`Refresh failed: ${error.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ── Provider/model picker pills (composer) ─────────────────────── */

/**
 * Inline-SVG marks for each provider preset. These are stylized monograms
 * — recognizable brand colors with a 1–3 char letter mark — chosen to
 * avoid trademark issues with malformed real logos. Keys match the
 * provider preset ids in augment/providers/presets.py.
 */
const PROVIDER_LOGOS = {
  openai:     { color: '#10A37F', text: 'AI' },
  anthropic:  { color: '#D97757', text: 'An' },
  groq:       { color: '#F55036', text: 'Gq' },
  openrouter: { color: '#6467F2', text: 'OR' },
  together:   { color: '#7C3AED', text: 'T'  },
  fireworks:  { color: '#F59E0B', text: 'Fw' },
  cerebras:   { color: '#DC2626', text: 'Ce' },
  mistral:    { color: '#FF6F00', text: 'Mi' },
  ollama:     { color: '#2563EB', text: 'Oll'},
  lmstudio:   { color: '#8B5CF6', text: 'LM' },
  llamacpp:   { color: '#10B981', text: 'Lcp'},
  codex:      { color: '#111111', text: 'Cx' },
  custom:     { color: '#6B7280', text: '?'  },
};

/**
 * Map a provider profile (id, name, preset) to its logo entry. Falls
 * back to `custom` if the provider id isn't a known preset.
 */
function providerLogoEntry(profile) {
  if (!profile) return PROVIDER_LOGOS.custom;
  const candidates = [profile.preset, profile.id, profile.name && String(profile.name).toLowerCase()];
  for (const key of candidates) {
    if (key && PROVIDER_LOGOS[key]) return PROVIDER_LOGOS[key];
  }
  return PROVIDER_LOGOS.custom;
}

/**
 * Build SVG markup for a provider mark. 18×18 by default; the consumer
 * can scale via CSS. Uses a colored rounded square with a centered
 * monogram in white.
 */
function providerLogoSvg(profile) {
  const entry = providerLogoEntry(profile);
  const text = entry.text || '?';
  // Shrink the font slightly for 3-letter monograms so they fit.
  const fontSize = text.length >= 3 ? 6.5 : (text.length === 2 ? 8 : 10);
  return `
    <svg viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
      <rect width="18" height="18" rx="4" fill="${entry.color}"/>
      <text x="9" y="9" text-anchor="middle" dominant-baseline="central"
            font-family="-apple-system, system-ui, sans-serif"
            font-weight="700" font-size="${fontSize}" fill="#fff">${esc(text)}</text>
    </svg>
  `;
}

/** Short, displayable model name — strips org/path prefixes. */
function shortModelName(model) {
  if (!model) return '—';
  return String(model).split('/').pop();
}

/**
 * Sync the two composer picker buttons with the currently active
 * provider/model. Called from renderSessionPicker() so the buttons
 * stay in step with the underlying <select> elements.
 */
function syncComposerPickers() {
  const provBtn  = qs('#composer-provider-btn');
  const modelBtn = qs('#composer-model-btn');
  if (!provBtn || !modelBtn) return;
  const active = state.profiles.find((p) => p.id === state.defaultId) || state.profiles[0];
  // Provider pill
  const provLogo  = provBtn.querySelector('[data-pill-logo]');
  const provLabel = provBtn.querySelector('[data-pill-label]');
  if (active) {
    if (provLogo)  provLogo.innerHTML = providerLogoSvg(active);
    if (provLabel) provLabel.textContent = active.name || active.id;
  } else {
    if (provLogo)  provLogo.innerHTML = providerLogoSvg(null);
    if (provLabel) provLabel.textContent = 'No provider';
  }
  // Model pill — share the active provider's logo
  const modelLogo  = modelBtn.querySelector('[data-pill-logo]');
  const modelLabel = modelBtn.querySelector('[data-pill-label]');
  if (modelLogo)  modelLogo.innerHTML = providerLogoSvg(active);
  if (modelLabel) modelLabel.textContent = shortModelName(active && active.model);
}

/**
 * Render the popover with a list of options for `kind` (provider | model)
 * and toggle visibility. Anchors below either pill button.
 */
function openComposerPopover(kind, anchor) {
  const popover = qs('#composer-picker-popover');
  if (!popover || !anchor) return;
  // Close handling — clicking the same pill again hides the popover.
  if (popover._kind === kind && !popover.hidden) {
    closeComposerPopover();
    return;
  }
  popover._kind = kind;
  // Position the popover left-aligned to the anchor button.
  popover.style.left = `${anchor.offsetLeft}px`;

  let html = '';
  if (kind === 'provider') {
    if (!state.profiles.length) {
      html = '<div class="lab-picker-popover__empty">No providers configured. Add one in Settings.</div>';
    } else {
      html = state.profiles.map((p) => {
        const isActive = p.id === state.defaultId;
        return `
          <button class="lab-picker-popover__option ${isActive ? 'is-active' : ''}" data-provider-id="${esc(p.id)}" type="button">
            <span class="lab-picker-pill__logo">${providerLogoSvg(p)}</span>
            <span class="lab-picker-popover__option-body">
              <span class="lab-picker-popover__option-name">${esc(p.name || p.id)}</span>
              <span class="lab-picker-popover__option-sub">${esc(shortModelName(p.model))}</span>
            </span>
            ${isActive ? '<span class="lab-picker-popover__option-meta">active</span>' : ''}
          </button>
        `;
      }).join('');
    }
  } else { // model
    const active = state.profiles.find((p) => p.id === state.defaultId) || state.profiles[0];
    const models = (active && active.models && active.models.length)
      ? active.models
      : (active && active.model ? [active.model] : []);
    if (!active) {
      html = '<div class="lab-picker-popover__empty">No active provider.</div>';
    } else if (!models.length) {
      html = '<div class="lab-picker-popover__empty">No models advertised. Click ↻ in the topbar to refresh.</div>';
    } else {
      html = models.map((m) => {
        const isActive = m === active.model;
        return `
          <button class="lab-picker-popover__option ${isActive ? 'is-active' : ''}" data-model="${esc(m)}" type="button">
            <span class="lab-picker-pill__logo">${providerLogoSvg(active)}</span>
            <span class="lab-picker-popover__option-body">
              <span class="lab-picker-popover__option-name">${esc(shortModelName(m))}</span>
              <span class="lab-picker-popover__option-sub">${esc(m)}</span>
            </span>
            ${isActive ? '<span class="lab-picker-popover__option-meta">active</span>' : ''}
          </button>
        `;
      }).join('');
    }
  }
  popover.innerHTML = html;
  popover.hidden = false;
  // Mark the open pill as expanded.
  qsa('.lab-picker-pill').forEach((b) => b.setAttribute('aria-expanded', String(b === anchor)));
  // Wire option clicks. Each option routes back through the existing
  // hidden <select> + change-event handlers so all server calls stay
  // exactly the same as before.
  qsa('.lab-picker-popover__option', popover).forEach((opt) => {
    opt.addEventListener('click', () => {
      if (kind === 'provider') {
        const id = opt.dataset.providerId;
        if (id && els.sessionProviderSelect) {
          els.sessionProviderSelect.value = id;
          els.sessionProviderSelect.dispatchEvent(new Event('change'));
        }
      } else {
        const model = opt.dataset.model;
        if (model && els.sessionModelSelect) {
          els.sessionModelSelect.value = model;
          els.sessionModelSelect.dispatchEvent(new Event('change'));
        }
      }
      closeComposerPopover();
    });
  });
}

function closeComposerPopover() {
  const popover = qs('#composer-picker-popover');
  if (!popover) return;
  popover.hidden = true;
  popover.innerHTML = '';
  popover._kind = null;
  qsa('.lab-picker-pill').forEach((b) => b.setAttribute('aria-expanded', 'false'));
}

/** Bind the picker pills + outside-click dismissal. Called once at boot. */
function bindComposerPickers() {
  const provBtn  = qs('#composer-provider-btn');
  const modelBtn = qs('#composer-model-btn');
  if (provBtn)  provBtn.addEventListener('click', () => openComposerPopover('provider', provBtn));
  if (modelBtn) modelBtn.addEventListener('click', () => openComposerPopover('model', modelBtn));
  // Click-outside / Escape to close.
  document.addEventListener('click', (event) => {
    const popover = qs('#composer-picker-popover');
    if (!popover || popover.hidden) return;
    if (event.target.closest('#composer-picker-popover')) return;
    if (event.target.closest('#composer-provider-btn')) return;
    if (event.target.closest('#composer-model-btn')) return;
    closeComposerPopover();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeComposerPopover();
  });
}

/* ── Vision / image attachments ─────────────────────────────────── */

function updateVisionAvailability(profile) {
  state.visionEnabled = Boolean(profile && profile.vision);
  if (els.attachImageBtn) {
    els.attachImageBtn.hidden = !state.visionEnabled;
    els.attachImageBtn.title = state.visionEnabled
      ? 'Attach image (vision)'
      : 'Active model does not support vision';
  }
  if (!state.visionEnabled && state.pendingImages.length) {
    state.pendingImages = [];
    renderPendingImages();
  }
}

function renderPendingImages() {
  const root = els.composeAttachments;
  if (!root) return;
  if (!state.pendingImages.length) {
    root.hidden = true;
    root.innerHTML = '';
    return;
  }
  root.hidden = false;
  root.innerHTML = state.pendingImages.map((item, index) => `
    <div class="lab-compose-thumb" title="${esc(item.name || 'image')}">
      <img src="${esc(item.dataUrl)}" alt="${esc(item.name || 'image')}" />
      <button type="button" class="lab-compose-thumb__remove" data-index="${index}" aria-label="Remove">×</button>
    </div>
  `).join('');
  qsa('.lab-compose-thumb__remove', root).forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.index || -1);
      if (idx >= 0) {
        state.pendingImages.splice(idx, 1);
        renderPendingImages();
      }
    });
  });
}

async function attachImageFiles(files) {
  if (!state.visionEnabled) {
    flash('Active model does not support vision');
    return;
  }
  const list = Array.from(files || []).filter((f) => f && (f.type || '').startsWith('image/'));
  if (!list.length) return;
  for (const file of list) {
    if (file.size > 20 * 1024 * 1024) {
      flash(`${file.name || 'image'} skipped: > 20 MB`);
      continue;
    }
    try {
      const dataUrl = await readAsDataURL(file);
      state.pendingImages.push({ dataUrl, name: file.name || 'image' });
    } catch (err) {
      flash(`Could not read ${file.name || 'image'}: ${err.message || err}`);
    }
  }
  renderPendingImages();
}

function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('read failed'));
    reader.readAsDataURL(file);
  });
}

function onAttachImageChange(event) {
  attachImageFiles(event.target.files);
  event.target.value = '';
}

function onComposerPaste(event) {
  if (!state.visionEnabled) return;
  const items = event.clipboardData?.items || [];
  const files = [];
  for (const item of items) {
    if (item.kind === 'file' && (item.type || '').startsWith('image/')) {
      const f = item.getAsFile();
      if (f) files.push(f);
    }
  }
  if (files.length) {
    event.preventDefault();
    attachImageFiles(files);
  }
}

function onComposerDragOver(event) {
  if (!state.visionEnabled) return;
  if ((event.dataTransfer?.types || []).includes('Files')) {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }
}

function onComposerDrop(event) {
  if (!state.visionEnabled) return;
  const files = event.dataTransfer?.files;
  if (files && files.length) {
    event.preventDefault();
    attachImageFiles(files);
  }
}

function renderProviderCards() {
  if (!els.providerCards) return;
  if (!state.profiles.length) {
    // Empty state: leave the grid blank so only the "Add Provider…" control is visible.
    els.providerCards.innerHTML = '';
    return;
  }
  els.providerCards.innerHTML = state.profiles.map((profile) => providerCardHtml(profile)).join('');
  qsa('.lab-provider-card', els.providerCards).forEach(bindProviderCard);
}

function providerCardHtml(profile) {
  const isDefault = profile.id === state.defaultId;
  const ok = profile.has_inline_key || profile.has_env_key || !profile.key_required;
  const dotClass = ok ? 'lab-provider-card__dot--ok' : (profile.key_required ? 'lab-provider-card__dot--err' : '');
  const endpoint = (profile.endpoint || '').replace(/^https?:\/\//, '');
  const keyCount = profile.has_inline_key || profile.has_env_key ? '1 key' : (profile.key_required ? '0 keys' : 'no key required');
  let statusBlock;
  if (profile.has_inline_key || profile.has_env_key) {
    statusBlock = `<div class="lab-provider-card__status lab-provider-card__status--ok">● Key configured${profile.has_env_key && !profile.has_inline_key ? ' (env)' : ''}</div>`;
  } else if (!profile.key_required) {
    statusBlock = '<div class="lab-provider-card__status lab-provider-card__status--ok">● No API key required</div>';
  } else {
    statusBlock = '<div class="lab-provider-card__status lab-provider-card__status--warn">⚠ No key — paste one below</div>';
  }
  const controls = profile.key_required
    ? `<div class="lab-provider-card__controls">
        <input class="lab-input js-key-input" type="password" placeholder="Add API key…" autocomplete="off" />
        <button class="lab-btn lab-btn--sm js-key-save" type="button">Save key</button>
        <button class="lab-btn lab-btn--sm js-refresh" type="button">↻</button>
        <button class="lab-btn lab-btn--sm lab-btn--danger js-remove" type="button">Remove</button>
      </div>`
    : `<div class="lab-provider-card__controls">
        <button class="lab-btn lab-btn--sm js-refresh" type="button">↻ Refresh models</button>
        <button class="lab-btn lab-btn--sm lab-btn--danger js-remove" type="button">Remove</button>
      </div>`;
  const models = (profile.models || []).slice(0, 8);
  const modelsBlock = models.length
    ? `<div class="lab-provider-card__models"><strong>Models:</strong> ${models.map((model) => `<span class="lab-chip">${esc(model.split('/').pop())}</span>`).join(' ')}</div>`
    : '';
  const setDefault = isDefault
    ? '<span class="lab-provider-card__badge">Default</span>'
    : `<button class="lab-provider-card__set-default lab-btn lab-btn--sm js-default" type="button">Make default</button>`;
  const sourceBadge = sourceBadgeHtml(profile.source);
  return `<article class="lab-provider-card ${isDefault ? 'is-default' : ''}" data-profile="${esc(profile.id)}">
    <div class="lab-provider-card__top">
      <span class="lab-provider-card__dot ${dotClass}"></span>
      <span class="lab-provider-card__name">${esc(profile.name || profile.id)}</span>
      <span class="lab-provider-card__endpoint">${esc(endpoint || '—')}</span>
      <span class="lab-provider-card__meta">${esc(keyCount)}</span>
      ${sourceBadge}
      ${setDefault}
    </div>
    ${statusBlock}
    ${controls}
    ${modelsBlock}
  </article>`;
}

function sourceBadgeHtml(source) {
  const value = String(source || '').trim();
  if (!value) return '';
  if (value.startsWith('env:')) {
    return `<span class="lab-provider-card__source lab-provider-card__source--env" title="${esc(value)}">env</span>`;
  }
  if (/fail[\\/]data/i.test(value)) {
    return `<span class="lab-provider-card__source lab-provider-card__source--fail" title="${esc(value)}">FAIL</span>`;
  }
  return `<span class="lab-provider-card__source" title="${esc(value)}">imported</span>`;
}

function bindProviderCard(card) {
  const profileId = card.dataset.profile;
  card.querySelector('.js-default')?.addEventListener('click', () => setDefaultProfile(profileId));
  card.querySelector('.js-refresh')?.addEventListener('click', () => refreshProfileModels(profileId, card));
  card.querySelector('.js-remove')?.addEventListener('click', () => removeProfile(profileId));
  card.querySelector('.js-key-save')?.addEventListener('click', () => saveProfileKey(profileId, card));
  card.querySelector('.js-key-input')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      saveProfileKey(profileId, card);
    }
  });
}

async function setDefaultProfile(profileId) {
  try {
    await request(`/api/providers/${encodeURIComponent(profileId)}/default`, { method: 'POST' });
    await loadProviders();
    await loadAgent();
    flash(`Default → ${profileId}`);
  } catch (error) {
    flash(`Default failed: ${error.message}`);
  }
}

async function refreshProfileModels(profileId, card) {
  const button = card.querySelector('.js-refresh');
  if (button) button.disabled = true;
  try {
    await request(`/api/providers/${encodeURIComponent(profileId)}/models/refresh`, { method: 'POST' });
    await loadProviders();
    flash(`Loaded models for ${profileId}`);
  } catch (error) {
    flash(`Refresh failed: ${error.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

async function removeProfile(profileId) {
  if (!confirm(`Remove provider “${profileId}”?`)) return;
  try {
    await request(`/api/providers/${encodeURIComponent(profileId)}`, { method: 'DELETE' });
    await loadProviders();
    await loadAgent();
    flash(`Removed ${profileId}`);
  } catch (error) {
    flash(`Remove failed: ${error.message}`);
  }
}

async function saveProfileKey(profileId, card) {
  const input = card.querySelector('.js-key-input');
  const value = (input?.value || '').trim();
  if (!value) {
    flash('Paste a key first');
    return;
  }
  try {
    await request(`/api/providers/${encodeURIComponent(profileId)}/key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    });
    input.value = '';
    await loadProviders();
    await loadAgent();
    flash(`Saved key for ${profileId}`);
  } catch (error) {
    flash(`Key save failed: ${error.message}`);
  }
}

/* ── Agent + inspector ───────────────────────────────────────────── */
async function loadAgent() {
  try {
    state.agent = await request('/api/agent');
    renderAgent(state.agent);
  } catch (error) {
    /* keep prior render */
  }
}

function renderAgent(data) {
  const agent = data.agent || {};
  const provider = data.provider || {};
  const tools = data.tools || [];
  const context = data.context || {};
  const capability = agent.capability || {};
  const stats = agent.stats || {};

  els.agentName.textContent = agent.name || 'Augment';
  els.inspectorName.textContent = agent.name || 'Augment';
  els.inspectorRole.textContent = agent.role || 'Single-loop coding assistant';
  els.inspectorAvatar.textContent = (agent.name || 'A').slice(0, 1).toUpperCase();
  els.inspectorProfileName.textContent = agent.name || 'Augment';
  els.inspectorModel.textContent = provider.model || '—';
  els.inspectorProvider.textContent = provider.name || provider.id || '—';
  els.inspectorRoleRow.textContent = agent.role || '—';

  const status = agent.status || 'idle';
  els.inspectorStatus.textContent = status;
  els.inspectorStatus.dataset.status = status;
  els.inspectorStatusRow.textContent = status;
  els.agentDot.className = `lab-agent-dot lab-agent-dot--${status}`;

  els.capTools.textContent = tools.length;
  els.capSuccess.textContent = `${Math.round((capability.success_rate ?? 1) * 100)}%`;
  els.capRuns.textContent = stats.tool_runs ?? 0;
  els.capSessions.textContent = stats.sessions_started ?? 0;
  els.capResumed.textContent = stats.sessions_resumed ?? 0;

  els.inspectorTools.innerHTML = tools.map((tool) => `
    <div class="lab-insp-tool" title="${esc(tool.description || '')}">
      <span class="lab-insp-tool__dot ${tool.read_only ? '' : 'lab-insp-tool__dot--mutating'}"></span>
      <span class="lab-insp-tool__name">${esc(tool.name)}</span>
    </div>
  `).join('') || '<div class="lab-empty">No tools registered.</div>';

  const toolsHtml = tools.map((tool) => toolCardHtml(tool)).join('') || '<div class="lab-empty">No tools registered.</div>';
  els.inspectorToolsPage.innerHTML = toolsHtml;

  els.ctxOriginal.textContent = context.original_chars ?? 0;
  els.ctxFinal.textContent = context.final_chars ?? 0;
  els.ctxTruncated.textContent = (context.truncated || []).join(', ') || 'none';
  if (context.final_chars != null) {
    els.statusContext.textContent = `Context: ${context.final_chars} / ${context.original_chars || 0} chars`;
  }

  const activity = (agent.recent_activity || []).slice().reverse();
  const logsHtml = activity.map((event) => `
    <li>
      <span class="lab-logs__kind">${esc(event.kind)}</span>
      <span class="lab-logs__detail">${esc(event.detail || '')}</span>
      <time>${esc(formatTime(event.ts))}</time>
    </li>
  `).join('') || '<li class="lab-empty">No activity yet.</li>';
  els.inspectorLogs.innerHTML = logsHtml;
  els.logsList.innerHTML = logsHtml;

  els.agentNameInput.value = agent.name || '';
  els.agentRoleInput.value = agent.role || '';
  els.agentDescriptionInput.value = agent.description || '';
  els.agentPersonaInput.value = agent.persona || '';
  if (els.agentNameCounter) els.agentNameCounter.textContent = `${(agent.name || '').length}/50`;
  if (els.agentRoleCounter) els.agentRoleCounter.textContent = `${(agent.role || '').length}/75`;
  if (els.agentDescriptionCounter) els.agentDescriptionCounter.textContent = `${(agent.description || '').length}/280`;

  if (els.agentAvatar) els.agentAvatar.textContent = (agent.name || 'A').slice(0, 1).toUpperCase();
  if (els.agentDisplayName) els.agentDisplayName.textContent = agent.name || 'Augment';
  if (els.agentDisplayRole) els.agentDisplayRole.textContent = agent.role || 'Single-loop coding assistant';
  if (els.agentDisplayStatus) {
    els.agentDisplayStatus.textContent = agent.status || 'idle';
    els.agentDisplayStatus.dataset.status = agent.status || 'idle';
  }
  if (els.agentSoulEnabled) els.agentSoulEnabled.checked = agent.soul_enabled !== false;
}

function toolCardHtml(tool) {
  return `
    <article class="lab-list-item">
      <header>
        <strong>${esc(tool.name)}</strong>
        <span class="lab-tag ${tool.read_only ? 'lab-tag--safe' : 'lab-tag--mutating'}">${tool.read_only ? 'read-only' : 'mutates'}</span>
      </header>
      <p>${esc(tool.description || '')}</p>
    </article>
  `;
}

async function saveAgentProfile(event) {
  event?.preventDefault?.();
  const body = {
    name: els.agentNameInput.value.trim(),
    role: els.agentRoleInput.value.trim(),
    description: els.agentDescriptionInput.value.trim(),
    persona: els.agentPersonaInput.value.trim(),
    soul_enabled: els.agentSoulEnabled?.checked ?? true,
  };
  try {
    await request('/api/agent', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    await Promise.all([loadAgent(), loadAgentSoul()]);
    flash('Agent profile saved');
  } catch (error) {
    flash(`Save failed: ${error.message}`);
  }
}

function openAgentTab(name) {
  if (!name) return;
  els.agentTabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.agentTab === name));
  els.agentPanels.forEach((panel) => panel.classList.toggle('lab-agent__panel--active', panel.dataset.agentPanel === name));
  if (name === 'soul') loadAgentSoul();
}

async function loadAgentSoul() {
  if (!els.agentSoulSoul) return;
  try {
    const data = await request('/api/agent/soul');
    renderAgentSoul(data);
  } catch (error) {
    flash(`Soul load failed: ${error.message}`);
  }
}

function renderAgentSoul(data) {
  const files = data?.files || {};
  if (els.agentSoulSoul) els.agentSoulSoul.value = files.soul || '';
  if (els.agentSoulPersonality) els.agentSoulPersonality.value = files.personality || '';
  if (els.agentSoulHistory) els.agentSoulHistory.value = files.history || '';
  if (els.agentSoulEnabled) els.agentSoulEnabled.checked = data?.enabled !== false;
  if (els.agentSoulPath && data?.path) els.agentSoulPath.textContent = data.path;
}

let _soulSaveTimer = null;
function scheduleSoulSave() {
  if (_soulSaveTimer) clearTimeout(_soulSaveTimer);
  _soulSaveTimer = setTimeout(() => { saveAgentSoul().catch(() => {}); }, 700);
}

async function saveAgentSoul() {
  const body = {
    enabled: els.agentSoulEnabled?.checked ?? true,
    files: {
      soul: els.agentSoulSoul?.value || '',
      personality: els.agentSoulPersonality?.value || '',
      history: els.agentSoulHistory?.value || '',
    },
  };
  try {
    const data = await request('/api/agent/soul', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    renderAgentSoul(data);
  } catch (error) {
    flash(`Soul save failed: ${error.message}`);
  }
}

async function toggleAgentSoulEnabled() {
  const enabled = els.agentSoulEnabled?.checked ?? true;
  try {
    const data = await request('/api/agent/soul', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, files: {} }),
    });
    renderAgentSoul(data);
    await loadAgent();
    flash(enabled ? 'Soul injection ON' : 'Soul injection OFF');
  } catch (error) {
    flash(`Toggle failed: ${error.message}`);
  }
}

async function resetAgentSoul() {
  if (!confirm('Reset SOUL.md / PERSONALITY.md / HISTORY.md to defaults? Your edits will be overwritten.')) return;
  try {
    const data = await request('/api/agent/soul/reset', { method: 'POST' });
    renderAgentSoul(data);
    flash('Soul files reset to defaults');
  } catch (error) {
    flash(`Reset failed: ${error.message}`);
  }
}

async function appendSoulLesson(event) {
  event?.preventDefault?.();
  const lesson = els.agentSoulLessonInput?.value.trim();
  if (!lesson) return;
  try {
    const data = await request('/api/agent/soul/history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lesson, metadata: state.sessionId ? { session: state.sessionId.slice(0, 12) } : {} }),
    });
    renderAgentSoul(data);
    if (els.agentSoulLessonInput) els.agentSoulLessonInput.value = '';
    flash('History lesson appended');
  } catch (error) {
    flash(`Lesson append failed: ${error.message}`);
  }
}

/* ── Sessions ─────────────────────────────────────────────────────── */
async function loadSessions() {
  try {
    const data = await request('/api/sessions?limit=100');
    state.sessions = data.sessions || [];
    if (!state.sessionId && state.sessions.length) state.sessionId = state.sessions[0].session_id;
    renderSessions();
  } catch (error) {
    flash(`Sessions unavailable: ${error.message}`);
  }
}

function renderSessions() {
  const q = els.sessionSearch.value.trim().toLowerCase();
  const filtered = q ? state.sessions.filter((s) => `${s.title} ${s.last_preview} ${s.project || ''}`.toLowerCase().includes(q)) : state.sessions;
  els.sessionsCount.textContent = state.sessions.length;

  // Group by project — sessions with no project tag fall under "Unassigned".
  const groups = new Map();
  for (const s of filtered) {
    const key = s.project || '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  }
  // Sort groups by most-recently-updated session inside them.
  const sortedGroups = [...groups.entries()].sort((a, b) => {
    const aTime = Math.max(...a[1].map((s) => s.updated_at || 0));
    const bTime = Math.max(...b[1].map((s) => s.updated_at || 0));
    return bTime - aTime;
  });

  if (!sortedGroups.length) {
    els.sessionList.innerHTML = '<div class="lab-empty">No sessions yet.</div>';
    return;
  }

  // Persist collapsed-project state across renders so the user's expand
  // choices survive every session-list refresh.
  state.collapsedProjects = state.collapsedProjects || new Set();

  els.sessionList.innerHTML = sortedGroups.map(([project, items]) => {
    const label = project || 'Unassigned';
    const collapsed = state.collapsedProjects.has(label);
    const sessionsHtml = items.map((s) => `
      <button class="lab-session-item ${s.session_id === state.sessionId ? 'active' : ''}" data-session="${esc(s.session_id)}" type="button">
        <span class="lab-session-item__name">${esc(s.title || 'New chat')}</span>
        <span class="lab-session-item__meta">${esc(s.last_preview || `${s.message_count || 0} messages`)}</span>
      </button>
    `).join('');
    return `
      <section class="lab-session-group ${collapsed ? 'is-collapsed' : ''}" data-group="${esc(label)}">
        <header class="lab-session-group__head" data-toggle-group="${esc(label)}">
          <span class="lab-session-group__chevron" aria-hidden="true">▾</span>
          <span class="lab-session-group__title">${esc(label)}</span>
          <span class="lab-session-group__count">${items.length}</span>
          ${project ? `<button class="lab-btn-ghost lab-session-group__grill" data-project="${esc(project)}" type="button" title="Grill all sessions in this project">Grill</button>` : ''}
        </header>
        <div class="lab-session-group__items">${sessionsHtml}</div>
      </section>
    `;
  }).join('');

  qsa('.lab-session-item', els.sessionList).forEach((item) =>
    item.addEventListener('click', () => openSession(item.dataset.session)),
  );
  qsa('.lab-session-group__grill', els.sessionList).forEach((btn) =>
    btn.addEventListener('click', (event) => {
      event.stopPropagation();
      grillProject(btn.dataset.project);
    }),
  );
  // Header click toggles project collapsed state (but not when the click
  // bubbled from the inline Grill button — see stopPropagation above).
  qsa('.lab-session-group__head', els.sessionList).forEach((head) =>
    head.addEventListener('click', () => {
      const key = head.dataset.toggleGroup;
      if (!key) return;
      if (state.collapsedProjects.has(key)) state.collapsedProjects.delete(key);
      else state.collapsedProjects.add(key);
      head.parentElement.classList.toggle('is-collapsed');
    }),
  );
}

async function grillProject(project) {
  if (!project) return;
  flash(`Grilling sessions in "${project}"…`);
  try {
    const data = await request('/api/sessions/grill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, max_sessions: 20 }),
    });
    if (!data.summary) {
      flash(`No summary returned for "${project}"`);
      return;
    }
    // Surface the brief as an assistant message in the current chat.
    addMessage(
      'assistant',
      `**Project brief — ${project}**\n\n${data.summary}\n\n_Synthesized across ${data.sessions?.length || 0} sessions._`,
    );
    flash(`Grill complete (${data.sessions?.length || 0} sessions)`);
  } catch (error) {
    flash(`Grill failed: ${error.message}`);
  }
}

async function openSession(id, { force = false } = {}) {
  const targetId = id || '';
  // Clicking a session from Memory / Settings / etc. should snap the user
  // back to the chat view.
  openPage('sessions');
  // No-op when clicking the already-active session — prevents the chat area
  // from being wiped (which destroys any in-flight streaming bubble that
  // hasn't been registered in state.activeStreams yet, e.g. a freshly
  // created `sess_local_*` session waiting for its first SSE event).
  if (!force && targetId && targetId === state.sessionId && els.messages.childElementCount > 0) {
    renderSessions();
    return;
  }
  state.sessionId = targetId;
  if (state.sessionId) localStorage.setItem('augment.sessionId', state.sessionId);
  updateSessionHeader();
  els.messages.innerHTML = '<div class="lab-chat__welcome"><p>Loading session…</p></div>';
  try {
    const data = await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/history?limit=200`);
    els.messages.innerHTML = '';
    for (const item of data.history || []) addMessage(item.role, item.content);
    // Re-attach any in-flight stream belonging to this session so the user
    // sees their pending user message + the live "Thinking…" bubble after
    // navigating back. Only re-attach if the live message isn't already in
    // the history we just rendered.
    const active = state.activeStreams.get(state.sessionId);
    if (active) {
      const haveLive = Array.from(els.messages.children).some(
        (el) => el === active.userEl || el === active.bubble.root,
      );
      if (!haveLive) {
        if (active.userEl && !active.userEl.isConnected) els.messages.appendChild(active.userEl);
        if (active.bubble?.root && !active.bubble.root.isConnected) els.messages.appendChild(active.bubble.root);
      }
    }
    const hasContent = (data.history || []).length > 0 || Boolean(active);
    if (!hasContent) showEmpty();
    els.messages.scrollTop = els.messages.scrollHeight;
    await loadMailbox();
  } catch (error) {
    els.messages.innerHTML = '';
    addMessage('assistant', `Could not load session: ${error.message}`);
  }
  renderSessions();
}

function startNewSession() {
  state.sessionId = `sess_${Math.random().toString(16).slice(2, 14)}`;
  localStorage.setItem('augment.sessionId', state.sessionId);
  els.messages.innerHTML = '';
  showEmpty();
  els.mailboxList.innerHTML = '';
  updateSessionHeader();
  renderSessions();
  // If the user is currently on Memory / Settings / etc., jump back to
  // the Sessions page so they actually see the new chat.
  openPage('sessions');
  els.input.focus();
}

/**
 * "+ New Project" — prompts for a project name, creates a local session
 * tagged with that project, opens it, and persists the project tag via
 * the existing /api/sessions/{id}/project endpoint so it shows up in the
 * project tree immediately.
 */
async function startNewProject() {
  const name = (window.prompt('Project name', '') || '').trim();
  if (!name) return;
  const sid = `sess_${Math.random().toString(16).slice(2, 14)}`;
  state.sessionId = sid;
  localStorage.setItem('augment.sessionId', sid);
  els.messages.innerHTML = '';
  showEmpty();
  els.mailboxList && (els.mailboxList.innerHTML = '');
  updateSessionHeader();
  openPage('sessions');
  // Optimistically insert a stub session so the project shows up in the
  // sidebar before the server round-trip completes.
  state.sessions.unshift({
    session_id: sid,
    title: 'New chat',
    project: name,
    message_count: 0,
    updated_at: Date.now() / 1000,
    last_preview: '',
    last_role: 'user',
  });
  renderSessions();
  try {
    await request(`/api/sessions/${encodeURIComponent(sid)}/project`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: name }),
    });
    flash(`Project "${name}" created`);
    await loadSessions();
  } catch (error) {
    flash(`Could not save project: ${error.message}`);
  }
  els.input.focus();
}

/**
 * Toggle the collapsed state of the sidebar — adds the
 * `lab-sidebar--collapsed` class which the CSS hooks for narrowing it.
 */
function toggleSidebar() {
  if (!els.sidebar) return;
  els.sidebar.classList.toggle('lab-sidebar--collapsed');
}

/**
 * Dispatch a welcome-card or composer quick action.
 * `kind` ∈ { 'new-session' | 'upload' | 'tool' | 'memory' }.
 */
function handleQuickAction(kind) {
  switch (kind) {
    case 'new-session':
      startNewSession();
      break;
    case 'upload':
      els.attachImageInput?.click();
      break;
    case 'tool':
      openPage('toolpacks');
      break;
    case 'memory':
      openPage('memory');
      break;
    default:
      break;
  }
}

async function clearCurrentSession() {
  if (!state.sessionId) return;
  await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/history`, { method: 'DELETE' });
  els.messages.innerHTML = '';
  showEmpty();
  await loadSessions();
  flash('Conversation cleared');
}

async function submitChat(event) {
  event.preventDefault();
  const text = els.input.value.trim();
  const images = state.pendingImages.map((img) => img.dataUrl);
  if (!text && !images.length) return;
  if (!state.sessionId) startNewSession();
  els.input.value = '';
  resizeInput();
  clearEmpty();
  const userEl = addMessage('user', text, null, { imageThumbs: state.pendingImages.slice() });
  // Clear the queued attachments now that they're attached to the bubble +
  // about to be sent — keeps the composer thumb strip in sync with the chat.
  state.pendingImages = [];
  renderPendingImages();
  setStatusbar('thinking', 'Thinking');
  els.form.querySelector('button[type="submit"]').disabled = true;

  // Pin this chat run to the session that was active when the user hit send.
  // If the user navigates to a different session mid-stream, we use this id
  // to ignore UI side-effects so we don't clobber the newly opened session.
  const requestSessionId = state.sessionId;

  // Optimistically add a sidebar entry so a fresh chat is reachable even
  // before the SSE stream completes and `loadSessions()` refreshes.
  upsertSidebarSession(requestSessionId, text);

  // Build a live assistant bubble that the SSE stream will fill in.
  const bubble = createStreamingBubble();
  bubble.sessionId = requestSessionId;
  els.messages.appendChild(bubble.root);
  els.messages.scrollTop = els.messages.scrollHeight;

  // Register the in-flight bubble + the user message DOM node so we can
  // re-attach them when the user navigates back to this session.
  state.activeStreams.set(requestSessionId, { userEl, bubble });

  try {
    await chatStream(text, requestSessionId, (eventType, data) => {
      handleChatEvent(bubble, eventType, data, requestSessionId);
    }, images);
    // Always refresh the sidebar/agent — but only realign the header/status
    // if the user is still looking at the session this chat belonged to.
    await Promise.all([loadSessions(), loadAgent(), loadMemory()]);
    if (state.sessionId === requestSessionId) {
      updateSessionHeader();
      setStatusbar('idle', 'Idle');
    }
  } catch (error) {
    bubble.finalize(`Error: ${error.message || error}`, { stopped_reason: 'error' });
    if (state.sessionId === requestSessionId) setStatusbar('error', 'Error');
  } finally {
    state.activeStreams.delete(requestSessionId);
    els.form.querySelector('button[type="submit"]').disabled = false;
    els.input.focus();
  }
}

function upsertSidebarSession(sessionId, previewText) {
  if (!sessionId) return;
  const existing = state.sessions.find((s) => s.session_id === sessionId);
  if (existing) {
    existing.last_preview = previewText.slice(0, 160);
    existing.updated_at = Date.now() / 1000;
  } else {
    state.sessions.unshift({
      session_id: sessionId,
      title: previewText.slice(0, 48) || 'New chat',
      last_preview: previewText.slice(0, 160),
      message_count: 1,
      updated_at: Date.now() / 1000,
      last_role: 'user',
    });
  }
  renderSessions();
}

/** Stream chat events over SSE, invoking `onEvent(type, data)` for each. */
async function chatStream(message, sessionId, onEvent, images = []) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId || '',
      images: Array.isArray(images) ? images : [],
    }),
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith('data: ') && eventType) {
        try {
          onEvent(eventType, JSON.parse(line.slice(6)));
        } catch (err) {
          console.warn('chat stream parse failed', err, line);
        }
        eventType = '';
      } else if (!line.trim()) {
        eventType = '';
      }
    }
  }
}

function createStreamingBubble() {
  const root = document.createElement('article');
  root.className = 'lab-chat-msg lab-chat-msg--assistant lab-chat-msg--streaming';

  const thinking = document.createElement('div');
  thinking.className = 'lab-chat-thinking';
  thinking.innerHTML = `
    <span class="lab-chat-thinking__dot"></span>
    <span class="lab-chat-thinking__dot"></span>
    <span class="lab-chat-thinking__dot"></span>
    <span class="lab-chat-thinking__label">Thinking…</span>
  `;
  root.appendChild(thinking);

  const artifacts = document.createElement('div');
  artifacts.className = 'lab-chat-artifacts';
  artifacts.hidden = true;
  root.appendChild(artifacts);

  const body = document.createElement('div');
  body.className = 'lab-chat-msg__body';
  body.hidden = true;
  root.appendChild(body);

  const meta = document.createElement('div');
  meta.className = 'lab-chat-msg__meta';
  meta.hidden = true;
  root.appendChild(meta);

  const setStatus = (label) => {
    const labelEl = thinking.querySelector('.lab-chat-thinking__label');
    if (labelEl) labelEl.textContent = label;
  };

  const addArtifact = (innerHtml) => {
    artifacts.hidden = false;
    const item = document.createElement('div');
    item.className = 'lab-chat-artifact';
    item.innerHTML = innerHtml;
    artifacts.appendChild(item);
    return item;
  };

  // ── Live reasoning panel ──────────────────────────────────────
  // Mirrors Luna's `thinking-bar` (ui/index.html#thinking) — a single
  // collapsible row with a pulsing dot, one-line status, and a scrollable
  // <pre>-style body that accumulates the agent's monologue as it streams.
  // No context-inspector grid — Luna doesn't have one, and Blackboard's
  // "bleeping" is just a phase label on its progress bar, not a panel.
  const reasoning = document.createElement('details');
  reasoning.className = 'lab-chat-reasoning';
  reasoning.open = true;
  reasoning.hidden = true; // shown the moment the first chunk arrives
  reasoning.innerHTML = `
    <summary class="lab-chat-reasoning__summary">
      <span class="lab-chat-reasoning__pulse" aria-hidden="true"></span>
      <span class="lab-chat-reasoning__label">live thinking</span>
      <span class="lab-chat-reasoning__count" aria-live="polite"></span>
    </summary>
    <div class="lab-chat-reasoning__body"></div>
  `;
  root.insertBefore(reasoning, artifacts);

  let reasoningEvents = 0;
  const reasoningBody = reasoning.querySelector('.lab-chat-reasoning__body');
  const reasoningCount = reasoning.querySelector('.lab-chat-reasoning__count');

  /**
   * Close the currently-open streaming reasoning item, if any.
   * Strips the `streaming` flag + `streaming` meta label so subsequent
   * reasoning_delta events spawn a fresh block instead of growing this
   * one. Called when a non-reasoning event arrives (tool_call,
   * tool_result, final, etc.) — matches Luna/Blackboard behaviour.
   */
  function _closeOpenReasoningItem() {
    if (!reasoningBody) return;
    const open = reasoningBody.lastElementChild;
    if (
      open
      && open.classList.contains('lab-chat-reasoning__item--thought')
      && open.dataset.streaming === '1'
    ) {
      delete open.dataset.streaming;
      const meta = open.querySelector('.lab-chat-reasoning__meta');
      if (meta) meta.remove();
    }
  }

  /**
   * Append one chunk to the live reasoning panel.
   * `kind` ∈ { 'thought' | 'tool' | 'result' | 'error' } — drives the
   * accent colour and prefix.
   */
  const appendReasoningChunk = (kind, text, meta = '') => {
    if (!reasoningBody) return;
    reasoning.hidden = false;
    reasoningEvents += 1;
    if (reasoningCount) {
      reasoningCount.textContent = `${reasoningEvents} step${reasoningEvents === 1 ? '' : 's'}`;
    }
    const item = document.createElement('div');
    item.className = `lab-chat-reasoning__item lab-chat-reasoning__item--${kind}`;
    const headHtml = `<span class="lab-chat-reasoning__kind">${esc(kind)}</span>${meta ? `<span class="lab-chat-reasoning__meta">${esc(meta)}</span>` : ''}`;
    const textHtml = `<div class="lab-chat-reasoning__text">${esc(String(text || '').trim() || '(empty)')}</div>`;
    item.innerHTML = `<header class="lab-chat-reasoning__head">${headHtml}</header>${textHtml}`;
    reasoningBody.appendChild(item);
    // Trim the panel if it gets long — keep the last 50 chunks (the
    // collapsed scroll history is searchable via the prompt preview).
    while (reasoningBody.children.length > 50) {
      reasoningBody.removeChild(reasoningBody.firstChild);
    }
    reasoningBody.scrollTop = reasoningBody.scrollHeight;
  };

  return {
    root,
    thinking,
    body,
    meta,
    setStatus,
    /**
     * Push a full thinking chunk into the live reasoning panel — the
     * primary "you can watch the agent think" surface. Each chunk is
     * one ReAct iteration's monologue, rendered as its own block so the
     * stream reads as a sequence of paragraphs.
     */
    addThought(text) {
      appendReasoningChunk('thought', text || '');
    },
    /** Mirror a tool plan into the reasoning narrative. */
    addReasoningTool(tool, args) {
      const argSummary = args ? JSON.stringify(args).slice(0, 240) : '';
      appendReasoningChunk('tool', argSummary, `→ ${tool}`);
    },
    /** Mirror a tool result into the reasoning narrative. */
    addReasoningResult(tool, success, durationMs, output, errorText) {
      const text = success ? (output || '').toString() : (errorText || 'failed').toString();
      appendReasoningChunk(
        success ? 'result' : 'error',
        text.slice(0, 800),
        `${success ? '✓' : '✗'} ${tool} · ${Math.round(durationMs || 0)}ms`,
      );
    },
    /**
     * Append a real per-token content delta to the assistant body.
     *
     * Dual-render pattern (ported from Luna's chat.js):
     *
     * 1. Append the raw chunk as a text node BEFORE the streaming
     *    cursor — zero-cost, instant feedback per token.
     * 2. Debounced (200 ms) markdown re-render so headings, lists, and
     *    code blocks light up while still feeling live. Balances
     *    formatting freshness against DOM thrashing.
     *
     * The streaming buffer ``body._streamingBuffer`` is the source of
     * truth for the next markdown pass and for ``finalize()``.
     */
    appendBodyDelta(text) {
      if (!text) return;
      if (thinking && !thinking.hidden) thinking.hidden = true;
      if (body.hidden) body.hidden = false;
      body._streamingBuffer = (body._streamingBuffer || '') + text;
      // Immediate: drop a text node in front of the streaming cursor so
      // there's no perceptible latency per chunk.
      let cursor = body.querySelector('.lab-stream-cursor');
      if (!cursor) {
        // First chunk — bootstrap the cursor sentinel.
        body.innerHTML = '<span class="lab-stream-cursor"></span>';
        cursor = body.querySelector('.lab-stream-cursor');
      }
      if (cursor) {
        cursor.before(document.createTextNode(text));
      } else {
        body.appendChild(document.createTextNode(text));
      }
      // Deferred: re-render full markdown at ~5 fps so code blocks /
      // lists / headings appear while streaming continues.
      if (!body._markdownTimer) {
        body._markdownTimer = setTimeout(() => {
          body._markdownTimer = null;
          if (!body._streamingBuffer) return;
          body.innerHTML = renderMarkdown(body._streamingBuffer)
            + '<span class="lab-stream-cursor"></span>';
          hydrateRenderedMarkdown(body);
        }, 200);
      }
      els.messages.scrollTop = els.messages.scrollHeight;
    },
    /**
     * Append a real per-token reasoning delta to the live-thinking panel.
     *
     * Unlike `addThought` (which appends a NEW reasoning chunk per
     * call), this grows a single "thinking" entry as the chain-of-
     * thought streams. We keep one open item per reasoning stream and
     * close it whenever a non-reasoning event arrives.
     */
    appendReasoningDelta(text) {
      if (!text) return;
      // Reuse the open reasoning entry if there is one; otherwise spawn
      // a fresh one and remember its body element.
      const body = reasoningBody;
      if (!body) return;
      reasoning.hidden = false;
      let open = body.lastElementChild;
      if (
        !open ||
        !open.classList.contains('lab-chat-reasoning__item--thought') ||
        open.dataset.streaming !== '1'
      ) {
        // Create a new streaming thought block.
        reasoningEvents += 1;
        if (reasoningCount) {
          reasoningCount.textContent = `${reasoningEvents} step${reasoningEvents === 1 ? '' : 's'}`;
        }
        open = document.createElement('div');
        open.className = 'lab-chat-reasoning__item lab-chat-reasoning__item--thought';
        open.dataset.streaming = '1';
        open.innerHTML = '<header class="lab-chat-reasoning__head"><span class="lab-chat-reasoning__kind">thought</span><span class="lab-chat-reasoning__meta">streaming</span></header><div class="lab-chat-reasoning__text"></div>';
        body.appendChild(open);
      }
      const textEl = open.querySelector('.lab-chat-reasoning__text');
      if (textEl) textEl.textContent = (textEl.textContent || '') + text;
      body.scrollTop = body.scrollHeight;
    },
    addToolCall(tool, args) {
      const argSummary = args ? esc(JSON.stringify(args).slice(0, 140)) : '';
      const argTag = argSummary ? ` <code class="lab-chat-artifact__args">${argSummary}</code>` : '';
      // A new tool call means whatever was streaming as "reasoning"
      // just ended — close the open reasoning item so the next
      // reasoning_delta starts a fresh block.
      _closeOpenReasoningItem();
      return addArtifact(`<span class="lab-chat-artifact__kind lab-chat-artifact__kind--call">→ ${esc(tool)}</span>${argTag}<span class="lab-chat-artifact__status" data-status="running">…</span>`);
    },
    completeToolCall(tool, success, durationMs, errorText, receipt = null) {
      const calls = artifacts.querySelectorAll('.lab-chat-artifact');
      let matched = null;
      for (let i = calls.length - 1; i >= 0; i--) {
        const item = calls[i];
        if (item.querySelector('.lab-chat-artifact__kind--call')?.textContent.endsWith(tool)) {
          matched = item;
          break;
        }
      }
      if (matched) {
        const status = matched.querySelector('.lab-chat-artifact__status');
        if (status) {
          status.dataset.status = success ? 'ok' : 'err';
          status.textContent = `${success ? '✓' : '✗'} ${Math.round(durationMs || 0)}ms${success ? '' : (errorText ? ` — ${errorText.slice(0, 80)}` : '')}`;
        }
        if (receipt) attachReceiptDiff(matched, receipt);
        return;
      }
      const fresh = addArtifact(`<span class="lab-chat-artifact__kind lab-chat-artifact__kind--result">${success ? '✓' : '✗'} ${esc(tool)}</span><span class="lab-chat-artifact__status" data-status="${success ? 'ok' : 'err'}">${Math.round(durationMs || 0)}ms${errorText ? ` — ${esc(errorText.slice(0, 80))}` : ''}</span>`);
      if (receipt) attachReceiptDiff(fresh, receipt);
    },
    finalize(content, data = {}) {
      thinking.hidden = true;
      body.hidden = false;
      // Cancel any pending streaming re-render — we're about to do the
      // authoritative pass.
      if (body._markdownTimer) {
        clearTimeout(body._markdownTimer);
        body._markdownTimer = null;
      }
      const streamed = body._streamingBuffer || '';
      const final = content || '';
      // Pick the authoritative source for the final render. The server's
      // final content is the truth; if streaming missed chunks, the
      // server's payload still includes them. Otherwise fall back to
      // whatever we accumulated mid-stream.
      const source = (final && final.length >= streamed.length) ? final : streamed;
      if (source) {
        body.innerHTML = renderMarkdown(source);
        hydrateRenderedMarkdown(body);
      } else if (!streamed) {
        body.textContent = '';
      }
      body._streamingBuffer = '';
      // Close any reasoning item left open mid-stream.
      _closeOpenReasoningItem();
      // Add the action bar (Copy / Retry / Delete) if it isn't already
      // attached. Retry replays the user's prior message; Delete drops
      // the bubble locally.
      if (!root.querySelector('.lab-chat-actions')) {
        const actions = document.createElement('div');
        actions.className = 'lab-chat-actions';
        actions.innerHTML = `
          <button class="lab-chat-actions__btn" data-action="copy" type="button" title="Copy reply">⧉ Copy</button>
          <button class="lab-chat-actions__btn" data-action="retry" type="button" title="Send the prior user message again">↻ Retry</button>
          <button class="lab-chat-actions__btn lab-chat-actions__btn--danger" data-action="delete" type="button" title="Remove this message">✕ Delete</button>
        `;
        root.appendChild(actions);
        actions.addEventListener('click', (event) => {
          const btn = event.target.closest('[data-action]');
          if (!btn) return;
          const kind = btn.dataset.action;
          handleChatActionClick(kind, root, body, btn);
        });
      }
      const stopped = data.stopped_reason || 'done';
      const iter = data.iterations || 0;
      const tools = data.tool_calls || 0;
      meta.hidden = false;
      meta.textContent = `${stopped} · ${iter} iter · ${tools} tools`;
      root.classList.remove('lab-chat-msg--streaming');
      // Collapse the reasoning panel on completion (kills the pulse) so
      // the final answer is the focal point — but leave it in the DOM
      // so the user can re-expand to review the full thought trail.
      if (!reasoning.hidden) {
        reasoning.classList.add('lab-chat-reasoning--done');
        reasoning.open = false;
      }
      els.messages.scrollTop = els.messages.scrollHeight;
    },
  };
}

function attachReceiptDiff(artifactEl, receipt) {
  // Already attached? avoid duplicates if the SSE result fires twice.
  if (artifactEl.querySelector('.lab-chat-receipt')) return;
  const targets = Array.isArray(receipt?.targets) ? receipt.targets : [];
  if (!targets.length) return;
  const wrap = document.createElement('details');
  wrap.className = 'lab-chat-receipt';
  if (receipt.status === 'blocked') wrap.classList.add('lab-chat-receipt--blocked');

  const summary = document.createElement('summary');
  const fileNames = targets.map((t) => t.path).join(', ').slice(0, 96);
  const verb = receipt.status === 'blocked' ? '⛔ blocked' : (receipt.success ? '◆ diff' : '× failed');
  summary.innerHTML = `<span class="lab-chat-receipt__verb">${esc(verb)}</span><span class="lab-chat-receipt__files">${esc(fileNames || 'no targets')}</span>`;
  wrap.appendChild(summary);

  for (const target of targets) {
    const block = document.createElement('div');
    block.className = 'lab-chat-receipt__target';
    const ranges = Array.isArray(target.changed_ranges) ? target.changed_ranges : [];
    const totalLines = ranges.reduce((acc, r) => acc + Math.max(0, (r.after_end || 0) - (r.after_start || 0) + 1), 0);
    const meta = [];
    if (target.full_rewrite) meta.push('full rewrite');
    if (!target.pattern_preserved && !target.full_rewrite) meta.push('pattern disturbed');
    if (target.changed_sections?.length) meta.push(`sections: ${target.changed_sections.slice(0, 4).join(', ')}`);
    if (totalLines) meta.push(`${ranges.length} hunk${ranges.length === 1 ? '' : 's'} · ${totalLines} lines`);
    block.innerHTML = `
      <div class="lab-chat-receipt__path">${esc(target.path)}</div>
      ${meta.length ? `<div class="lab-chat-receipt__meta">${esc(meta.join(' · '))}</div>` : ''}
    `;
    const diff = String(target.diff_preview || '').trim();
    if (diff) {
      const pre = document.createElement('pre');
      pre.className = 'lab-chat-receipt__diff';
      pre.textContent = diff;
      block.appendChild(pre);
    }
    wrap.appendChild(block);
  }
  artifactEl.appendChild(wrap);
}

function handleChatEvent(bubble, type, data, requestSessionId) {
  // Updating the bubble DOM is always safe: if the user switched sessions
  // mid-stream, the bubble was removed from the DOM tree when openSession()
  // cleared `els.messages`, so any further mutation is invisible. Global
  // state mutations (state.sessionId, status bars) are guarded so they don't
  // clobber the session the user is currently viewing.
  const stillActive = state.sessionId === (bubble.sessionId || requestSessionId);

  switch (type) {
    case 'started':
      // Server canonicalises empty/new session ids. Adopt the resolved id
      // (only if the user is still viewing this chat's session) so the
      // sidebar and localStorage stay aligned.
      if (data.session_id) {
        const resolved = String(data.session_id);
        if (bubble.sessionId && bubble.sessionId !== resolved && stillActive) {
          state.sessionId = resolved;
          localStorage.setItem('augment.sessionId', state.sessionId);
        }
        bubble.sessionId = resolved;
      }
      bubble.setStatus('Thinking…');
      break;
    case 'thinking': {
      const preview = String(data.content || '').slice(0, 120).replace(/\s+/g, ' ').trim();
      bubble.setStatus(preview ? `Thinking · ${preview}…` : 'Thinking…');
      bubble.addThought(data.content || '');
      break;
    }
    case 'token_delta': {
      // Real per-chunk content delta from provider.stream(). Append to
      // the assistant bubble body as it arrives so the user sees the
      // answer type out in real time (Luna/Blackboard parity).
      const chunk = String(data.content || '');
      if (chunk) bubble.appendBodyDelta(chunk);
      break;
    }
    case 'reasoning_delta': {
      // Streaming chain-of-thought delta (o1/o3/Claude/Codex). Route
      // into the live-thinking panel as one continuous "thinking"
      // narrative — accumulate into the same item rather than spawning
      // one item per token.
      const chunk = String(data.content || '');
      if (chunk) bubble.appendReasoningDelta(chunk);
      break;
    }
    case 'bleep': {
      // The backend's `bleep` event delivers context-budget stats. We don't
      // render an inspector card (Luna doesn't, Blackboard doesn't) — just
      // update the one-line Context stat in the diagnostics footer when
      // the user is still viewing this session.
      if (stillActive && els.statusContext) {
        const stats = data.stats || {};
        const used = Number(stats.final_chars || 0);
        const budget = Number(stats.total_budget || 0);
        els.statusContext.textContent = budget
          ? `${used.toLocaleString()} / ${budget.toLocaleString()} chars`
          : `${used.toLocaleString()} chars`;
      }
      break;
    }
    case 'tool_plan': {
      const calls = Array.isArray(data.calls) ? data.calls : [];
      bubble.setStatus(`Planning · ${calls.length} parallel call${calls.length === 1 ? '' : 's'}`);
      for (const call of calls) {
        const toolName = String(call.tool || call.name || 'tool');
        bubble.addToolCall(toolName, call.args || {});
        bubble.addReasoningTool(toolName, call.args || {});
      }
      break;
    }
    case 'tool_call':
      bubble.setStatus(`Using ${data.tool || 'tool'}…`);
      bubble.addToolCall(String(data.tool || 'tool'), data.args || {});
      bubble.addReasoningTool(String(data.tool || 'tool'), data.args || {});
      break;
    case 'tool_result':
      bubble.completeToolCall(
        String(data.tool || 'tool'),
        Boolean(data.success),
        Number(data.duration_ms || 0),
        String(data.error || ''),
        data.edit_receipt || null,
      );
      bubble.addReasoningResult(
        String(data.tool || 'tool'),
        Boolean(data.success),
        Number(data.duration_ms || 0),
        String(data.output || ''),
        String(data.error || ''),
      );
      bubble.setStatus(data.success ? `Got ${data.tool} result` : `${data.tool} failed`);
      break;
    case 'token':
      bubble.finalize(String(data.content || ''));
      break;
    case 'done':
      bubble.finalize(String(data.content || ''), data);
      // Status bars only follow the currently visible session.
      if (stillActive) {
        if (data.context_stats) {
          els.statusContext.textContent = `Context: ${data.context_stats.final_chars || 0} / ${data.context_stats.original_chars || 0} chars`;
        }
        els.statusTokens.textContent = `Tools: ${data.tool_calls || 0} calls`;
      }
      break;
    case 'error':
      bubble.finalize(`Error: ${data.error || data.content || 'unknown'}`, { stopped_reason: 'error' });
      break;
    case 'heartbeat':
      break;
    default:
      break;
  }
}

function updateSessionHeader() {
  const current = state.sessions.find((s) => s.session_id === state.sessionId);
  els.sessionTitle.textContent = current?.title || (state.sessionId ? 'New chat' : 'New chat');
  els.sessionPill.textContent = state.sessionId ? short(state.sessionId) : '';
  els.statusSession.textContent = `Session: ${state.sessionId ? short(state.sessionId) : '—'}`;
}

/* ── Mailbox ─────────────────────────────────────────────────────── */
async function loadMailbox() {
  if (!state.sessionId) {
    els.mailboxList.innerHTML = '';
    return;
  }
  try {
    const data = await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/mailbox?limit=100`);
    const items = data.mailbox || [];
    els.mailboxList.innerHTML = items.map((item) => `
      <article class="lab-mailbox-item">
        <strong>${esc(item.kind || 'note')}</strong>
        <p>${esc(item.content || '')}</p>
      </article>
    `).join('') || '<div class="lab-empty">No mailbox notes yet.</div>';
  } catch (error) {
    els.mailboxList.innerHTML = `<div class="lab-empty">Mailbox unavailable: ${esc(error.message)}</div>`;
  }
}

async function addMailboxNote(event) {
  event.preventDefault();
  const content = els.mailboxInput.value.trim();
  if (!content) return;
  if (!state.sessionId) startNewSession();
  await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/mailbox`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, kind: 'note' }),
  });
  els.mailboxInput.value = '';
  await loadMailbox();
  flash('Mailbox note saved');
}

/* ── Memory ──────────────────────────────────────────────────────── */
async function loadMemory() {
  if (!els.memoryList) return;
  els.memoryList.innerHTML = '<div class="lab-empty">Loading memory…</div>';
  try {
    const data = await request('/api/memory');
    const legacy = data.memory || [];
    const tiers = data.tiers || {};
    const legacyHtml = legacy.map((item) => `
      <article class="lab-list-item">
        <header><strong>${esc(item.fact || '')}</strong><span class="lab-tag">${esc(item.source || 'user')}</span></header>
        <p>seen ${item.count || 1}× · ${esc(formatTime(item.last_seen))}</p>
      </article>
    `).join('') || '<div class="lab-empty">No persistent facts yet.</div>';

    const tierCard = (label, snapshot, render) => {
      const items = (snapshot && (snapshot.items || snapshot.recent || snapshot.facts || snapshot.procedures)) || [];
      const count = snapshot ? (snapshot.count ?? items.length) : 0;
      const inner = items.length
        ? items.slice(0, 8).map(render).join('')
        : `<div class="lab-empty">No ${label.toLowerCase()} entries.</div>`;
      return `
        <section class="lab-memory-tier">
          <header class="lab-memory-tier__head">
            <strong>${esc(label)}</strong>
            <span class="lab-pill">${count}</span>
          </header>
          <div class="lab-memory-tier__items">${inner}</div>
        </section>
      `;
    };

    const tiersHtml = `
      <div class="lab-memory-tiers">
        ${tierCard('Working', tiers.working, (i) => `
          <article class="lab-list-item">
            <header><strong>${esc(i.key || '')}</strong><span class="lab-tag">p${esc(String(i.priority ?? '?'))}</span></header>
            <p>${esc(String(i.value || '').slice(0, 200))}</p>
          </article>`)}
        ${tierCard('Episodic', tiers.episodic, (e) => `
          <article class="lab-list-item">
            <header><strong>${esc((e.summary || '').slice(0, 80))}</strong><span class="lab-tag">${esc(e.outcome || '')}</span></header>
            <p>${esc(formatTime(e.ts))} · ${esc((e.tools_used || []).join(', ') || 'no tools')}</p>
          </article>`)}
        ${tierCard('Semantic', tiers.semantic, (f) => `
          <article class="lab-list-item">
            <header><strong>${esc(f.key || '')}</strong><span class="lab-tag">${esc(f.category || 'general')}</span></header>
            <p>${esc(String(f.value || '').slice(0, 200))}</p>
          </article>`)}
        ${tierCard('Procedural', tiers.procedural, (p) => `
          <article class="lab-list-item">
            <header><strong>${esc(p.name || '')}</strong><span class="lab-tag">${esc(Math.round((p.success_rate || 0) * 100) + '%')}</span></header>
            <p>${esc((p.steps || []).join(' → ').slice(0, 200))}</p>
          </article>`)}
      </div>
      <h3 class="lab-memory-tiers__legacy-title">Legacy Facts</h3>
      ${legacyHtml}
    `;

    els.memoryList.innerHTML = tiersHtml;
    if (els.inspectorMemory) els.inspectorMemory.innerHTML = legacyHtml;
  } catch (error) {
    els.memoryList.innerHTML = `<div class="lab-empty">Memory unavailable: ${esc(error.message)}</div>`;
  }
}

/* ── Chat rendering ──────────────────────────────────────────────── */
function addMessage(role, content, data = null, opts = {}) {
  const el = document.createElement('article');
  el.className = `lab-chat-msg lab-chat-msg--${role === 'user' ? 'user' : 'assistant'}`;
  const text = String(content || '');
  if (text) {
    const body = document.createElement('div');
    body.className = 'lab-chat-msg__body';
    if (role === 'assistant') {
      // Render markdown for assistant messages from history replay so
      // bullets / code / headings look right after the session reload.
      body.innerHTML = renderMarkdown(text);
      hydrateRenderedMarkdown(body);
    } else {
      body.textContent = text;
    }
    el.appendChild(body);
  }
  const thumbs = Array.isArray(opts.imageThumbs) ? opts.imageThumbs : [];
  if (thumbs.length) {
    const strip = document.createElement('div');
    strip.className = 'lab-chat-msg__images';
    for (const thumb of thumbs) {
      const img = document.createElement('img');
      img.src = thumb.dataUrl || thumb.url || thumb;
      img.alt = thumb.name || 'image';
      strip.appendChild(img);
    }
    el.appendChild(strip);
  }
  if (data) {
    const meta = document.createElement('div');
    meta.className = 'lab-chat-msg__meta';
    meta.textContent = `${data.stopped_reason || 'done'} · ${data.iterations || 0} iter · ${data.tool_calls || 0} tools`;
    el.appendChild(meta);
  }
  els.messages.appendChild(el);
  els.messages.scrollTop = els.messages.scrollHeight;
  return el;
}

/**
 * Action-bar dispatcher (Copy / Retry / Delete).
 *
 * Wired by the streaming bubble's finalize() so each finalized
 * assistant message can be copied, retried, or removed. Retry pulls
 * the latest user message and re-submits it through the composer.
 */
function handleChatActionClick(kind, root, body, btn) {
  switch (kind) {
    case 'copy': {
      const text = body?.textContent?.trim() || '';
      if (!text) return;
      navigator.clipboard.writeText(text).then(
        () => {
          const prev = btn.textContent;
          btn.textContent = '✓ Copied';
          setTimeout(() => { btn.textContent = prev; }, 1500);
        },
        () => { btn.textContent = 'Copy failed'; },
      );
      break;
    }
    case 'retry': {
      // Find the most recent user message above this bubble.
      let prior = root.previousElementSibling;
      while (prior && !prior.classList.contains('lab-chat-msg--user')) {
        prior = prior.previousElementSibling;
      }
      const userBody = prior?.querySelector('.lab-chat-msg__body');
      const text = userBody?.textContent?.trim() || '';
      if (!text || !els.input) return;
      els.input.value = text;
      resizeInput();
      els.input.focus();
      break;
    }
    case 'delete': {
      root.remove();
      break;
    }
    default:
      break;
  }
}

function showEmpty() {
  // Rebuild the v2 welcome card. The four data-quick buttons go through
  // the same dispatcher used at boot time (handleQuickAction).
  els.messages.innerHTML = `
    <article id="chat-empty-state" class="lab-welcome-card">
      <div class="lab-welcome-card__logo" aria-hidden="true">⬡</div>
      <h2 class="lab-welcome-card__title">Welcome to Augment Lab</h2>
      <p class="lab-welcome-card__blurb">Your AI workspace for deep thinking, building,<br/>and solving complex problems.</p>
      <div class="lab-welcome-card__actions">
        <button class="lab-welcome-card__btn" data-quick="new-session" type="button"><span>💬</span> New Session</button>
        <button class="lab-welcome-card__btn" data-quick="upload" type="button"><span>📎</span> Upload File</button>
        <button class="lab-welcome-card__btn" data-quick="tool" type="button"><span>🧩</span> Use a Tool</button>
        <button class="lab-welcome-card__btn" data-quick="memory" type="button"><span>📚</span> Open Memory</button>
      </div>
    </article>
  `;
  // The buttons are freshly created, so re-bind quick-action handlers.
  qsa('.lab-welcome-card__btn[data-quick]', els.messages).forEach((btn) =>
    btn.addEventListener('click', () => handleQuickAction(btn.dataset.quick)),
  );
}

function clearEmpty() { qs('#chat-empty-state')?.remove(); }

function resizeInput() {
  els.input.style.height = 'auto';
  els.input.style.height = `${Math.min(els.input.scrollHeight, 140)}px`;
}

/* ── Tool Packs ──────────────────────────────────────────────────── */
async function loadToolPacks() {
  if (!els.toolpacksGrid) return;
  els.toolpacksGrid.innerHTML = '<div class="lab-empty">Loading…</div>';
  try {
    const data = await request('/api/toolpacks');
    const packs = data.packs || [];
    if (!packs.length) {
      els.toolpacksGrid.innerHTML = '<div class="lab-empty">No tools registered.</div>';
      return;
    }
    els.toolpacksGrid.innerHTML = packs.map(toolPackCardHtml).join('');
  } catch (error) {
    els.toolpacksGrid.innerHTML = `<div class="lab-empty">Failed: ${esc(error.message)}</div>`;
  }
}

function toolPackCardHtml(pack) {
  const tools = pack.tools || [];
  return `<article class="lab-pack-card">
    <header class="lab-pack-card__head">
      <strong>${esc(pack.name)}</strong>
      <span class="lab-pack-card__count">${tools.length} tools</span>
    </header>
    <div class="lab-pack-card__body">
      ${tools.map(toolPackToolRow).join('')}
    </div>
  </article>`;
}

function toolPackToolRow(tool) {
  const state = tool.state || (tool.read_only ? 'ready' : 'effectful');
  const stateLabel = state === 'effectful' ? 'approval' : state;
  const stateClass = state === 'ready' ? 'lab-pack-state--ready' : 'lab-pack-state--approval';
  const stats = tool.stats || {};
  return `<div class="lab-pack-row" tabindex="0" title="${esc(tool.description || '')}">
    <span class="lab-pack-row__name">${esc(tool.name)}</span>
    <span class="lab-pack-state ${stateClass}">${esc(stateLabel)}</span>
    <div class="lab-pack-row__tooltip" role="tooltip">
      <strong>${esc(tool.name)}</strong>
      <p>${esc(tool.description || 'No description.')}</p>
      <dl>
        <dt>State</dt><dd>${esc(stateLabel)}</dd>
        <dt>Safety</dt><dd>${esc(stats.safety || (tool.read_only ? 'read_only' : 'approval'))}</dd>
        <dt>Timeout</dt><dd>${esc(String(stats.timeout_s ?? 0))}s</dd>
        <dt>Params</dt><dd>${esc(String(stats.parameter_count ?? 0))} total · ${esc(String(stats.required_count ?? 0))} required</dd>
        <dt>Tags</dt><dd>${esc((tool.tags || []).join(', ') || 'none')}</dd>
      </dl>
    </div>
  </div>`;
}

/* ── Skill Packs ─────────────────────────────────────────────────── */
async function loadSkillPacks() {
  if (!els.skillpacksDormant) return;
  els.skillpacksDormant.innerHTML = '<div class="lab-empty">Loading…</div>';
  els.skillpacksAdaptive.innerHTML = '';
  try {
    const data = await request('/api/skills/catalog');
    renderSkillStats(data);
    renderDormantPacks(data.dormant_packs || {});
    renderAdaptiveSkills(data.adaptive_skills || []);
  } catch (error) {
    els.skillpacksDormant.innerHTML = `<div class="lab-empty">Failed: ${esc(error.message)}</div>`;
  }
}

function renderSkillStats(data) {
  if (!els.skillpacksStats) return;
  const dormant = (data.dormant_packs || {}).packs || [];
  const adaptive = data.adaptive_skills || [];
  const categories = (data.dormant_packs || {}).categories || [];
  const cells = [
    { label: 'Specialty Categories', value: categories.length },
    { label: 'Dormant Packs', value: dormant.length },
    { label: 'Adaptive Skills', value: adaptive.length },
    { label: 'High Risk Packs', value: dormant.filter((p) => p.risk_level === 'high').length },
  ];
  els.skillpacksStats.innerHTML = cells.map((cell) => `<div class="lab-stat-card"><strong>${cell.value}</strong><span>${esc(cell.label)}</span></div>`).join('');
}

function renderDormantPacks(catalog) {
  const categories = catalog.categories || [];
  const byCategory = catalog.by_category || {};
  const html = categories.map((category) => {
    const packs = byCategory[category] || [];
    if (!packs.length) return '';
    return `<article class="lab-pack-card lab-pack-card--dormant">
      <header class="lab-pack-card__head">
        <strong>${esc(category)}</strong>
        <span class="lab-pack-card__count lab-pack-card__count--dormant">${packs.length} dormant</span>
      </header>
      <div class="lab-pack-card__body">
        ${packs.map(dormantPackRow).join('')}
      </div>
    </article>`;
  }).join('');
  els.skillpacksDormant.innerHTML = html || '<div class="lab-empty">No dormant skill packs registered.</div>';
}

function dormantPackRow(pack) {
  const risk = pack.risk_level || 'low';
  const riskClass = risk === 'high' ? 'lab-pack-state--high' : risk === 'medium' ? 'lab-pack-state--medium' : 'lab-pack-state--low';
  const when = (pack.when_to_use || []).join(' · ');
  const tools = (pack.required_tools || []).join(', ') || 'none';
  return `<div class="lab-pack-row" tabindex="0" title="${esc(pack.description || '')}">
    <span class="lab-pack-row__name">${esc(pack.name || pack.id)}</span>
    <span class="lab-pack-state ${riskClass}">${esc(risk)}</span>
    <div class="lab-pack-row__tooltip" role="tooltip">
      <strong>${esc(pack.name || pack.id)}</strong>
      <p>${esc(pack.description || '')}</p>
      <dl>
        <dt>Category</dt><dd>${esc(pack.category || 'general')}</dd>
        <dt>Risk</dt><dd>${esc(risk)}</dd>
        <dt>Use When</dt><dd>${esc(when || '—')}</dd>
        <dt>Tools</dt><dd>${esc(tools)}</dd>
        <dt>Handoffs</dt><dd>${esc((pack.handoff_targets || []).join(', ') || 'none')}</dd>
      </dl>
    </div>
  </div>`;
}

function renderAdaptiveSkills(skills) {
  if (!skills.length) {
    els.skillpacksAdaptive.innerHTML = '<div class="lab-empty">No adaptive skills yet — click <strong>Generate Adaptive Skills</strong> to build them from your workspace and tool registry.</div>';
    return;
  }
  const byKind = {};
  for (const skill of skills) {
    const kind = skill.kind || 'adaptive';
    if (!byKind[kind]) byKind[kind] = [];
    byKind[kind].push(skill);
  }
  els.skillpacksAdaptive.innerHTML = Object.entries(byKind).map(([kind, items]) => `
    <article class="lab-pack-card lab-pack-card--adaptive">
      <header class="lab-pack-card__head">
        <strong>${esc(kind.replaceAll('_', ' '))}</strong>
        <span class="lab-pack-card__count lab-pack-card__count--adaptive">${items.length} skill${items.length === 1 ? '' : 's'}</span>
      </header>
      <div class="lab-pack-card__body">
        ${items.map(adaptiveSkillRow).join('')}
      </div>
    </article>
  `).join('');
}

function adaptiveSkillRow(skill) {
  const priority = (skill.priority ?? 0).toFixed(2);
  return `<div class="lab-pack-row" tabindex="0" title="${esc(skill.instructions || '')}">
    <span class="lab-pack-row__name">${esc(skill.title || skill.id)}</span>
    <span class="lab-pack-state lab-pack-state--adaptive">p ${esc(priority)}</span>
    <div class="lab-pack-row__tooltip" role="tooltip">
      <strong>${esc(skill.title || skill.id)}</strong>
      <p>${esc(skill.instructions || 'Adaptive skill.')}</p>
      <dl>
        <dt>Kind</dt><dd>${esc(skill.kind || 'general')}</dd>
        <dt>Priority</dt><dd>${esc(priority)}</dd>
        <dt>Signals</dt><dd>${esc((skill.signals || []).slice(0, 5).join(' · ') || 'none')}</dd>
        <dt>Source</dt><dd>${esc(skill.source || 'adaptive_generator')}</dd>
      </dl>
    </div>
  </div>`;
}

async function generateAdaptiveSkills() {
  if (!els.skillpacksGenerateBtn) return;
  const original = els.skillpacksGenerateBtn.textContent;
  els.skillpacksGenerateBtn.disabled = true;
  els.skillpacksGenerateBtn.textContent = 'Generating…';
  try {
    await request('/api/skills/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId || '', objective: '' }),
    });
    await loadSkillPacks();
    flash('Adaptive skills regenerated');
  } catch (error) {
    flash(`Skill generation failed: ${error.message}`);
  } finally {
    els.skillpacksGenerateBtn.disabled = false;
    els.skillpacksGenerateBtn.textContent = original;
  }
}

/* ── Codex login bridge ──────────────────────────────────────────── */
const codexState = { status: null, account: null, login: null };

async function loadCodex() {
  if (!els.codexCard) return;
  els.codexCard.hidden = false;
  try {
    const [status, account, login] = await Promise.all([
      request('/api/codex/status'),
      request('/api/codex/account'),
      request('/api/codex/login'),
    ]);
    codexState.status = status;
    codexState.account = account;
    codexState.login = login;
  } catch (error) {
    codexState.status = { error: error.message };
    codexState.account = { authenticated: false, error: error.message };
    codexState.login = { status: 'idle' };
  }
  renderCodex();
}

function renderCodex() {
  const status = codexState.status || {};
  const account = codexState.account || {};
  const login = codexState.login || { status: 'idle' };

  els.codexDot.textContent = status.available ? '🟢' : status.executable_found ? '🟡' : '⚪';
  els.codexVersion.textContent = status.version || status.mode || 'not checked';

  if (account.authenticated) {
    els.codexState.textContent = 'Authenticated with Codex account.';
    els.codexState.className = 'lab-codex__state lab-codex__state--ok';
  } else if (status.available) {
    els.codexState.textContent = account.error || 'Ready to log in.';
    els.codexState.className = 'lab-codex__state';
  } else {
    els.codexState.textContent = status.error || account.error || 'Codex runtime not available.';
    els.codexState.className = 'lab-codex__state lab-codex__state--warn';
  }

  const pending = login.status === 'pending';
  els.codexPending.hidden = !pending;
  els.codexCancelBtn.hidden = !pending;

  if (pending) {
    if (login.verification_url) {
      els.codexVerificationRow.hidden = false;
      els.codexVerificationLink.textContent = login.verification_url;
      els.codexVerificationLink.href = login.verification_url;
    } else {
      els.codexVerificationRow.hidden = true;
    }
    if (login.user_code) {
      els.codexUserCodeRow.hidden = false;
      els.codexUserCode.textContent = login.user_code;
    } else {
      els.codexUserCodeRow.hidden = true;
    }
    if (login.auth_url) {
      els.codexAuthLink.hidden = false;
      els.codexAuthLink.href = login.auth_url;
    } else {
      els.codexAuthLink.hidden = true;
    }
  }
}

async function startCodexLogin() {
  if (!els.codexLoginBtn) return;
  const original = els.codexLoginBtn.textContent;
  els.codexLoginBtn.disabled = true;
  els.codexLoginBtn.textContent = 'Starting…';
  try {
    const result = await request('/api/codex/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ method: 'device_code' }),
    });
    if (!result.ok) {
      flash(`Codex login failed: ${result.error || 'unknown error'}`);
    } else {
      flash('Codex login started — follow the verification link.');
    }
    await loadCodex();
  } catch (error) {
    flash(`Codex login failed: ${error.message}`);
  } finally {
    els.codexLoginBtn.disabled = false;
    els.codexLoginBtn.textContent = original;
  }
}

async function cancelCodexLogin() {
  try {
    await request('/api/codex/login/cancel', { method: 'POST' });
    flash('Codex login cancelled.');
  } catch (error) {
    flash(`Cancel failed: ${error.message}`);
  }
  await loadCodex();
}

/* ── Background thinking ─────────────────────────────────────────── */
async function loadThinking() {
  if (!els.thinkingStatus) return;
  try {
    const data = await request('/api/mind/thinking?limit=20');
    renderThinking(data);
  } catch (error) {
    els.thinkingStatus.textContent = `Thinking unavailable: ${error.message}`;
  }
}

function renderThinking(data) {
  const status = data?.status || {};
  const log = data?.log || [];
  const running = Boolean(status.running);
  if (els.thinkingStartBtn) els.thinkingStartBtn.hidden = running;
  if (els.thinkingStopBtn) els.thinkingStopBtn.hidden = !running;
  if (els.thinkingIntervalInput && status.interval_s) {
    els.thinkingIntervalInput.value = Math.round(status.interval_s);
  }
  const dot = running ? '🟢' : '⚪';
  const count = status.thought_count ?? 0;
  const last = status.last_thought_ts ? formatTime(status.last_thought_ts) : 'never';
  const interval = status.interval_s ?? 120;
  const hasFn = status.has_think_fn ? '' : ' · no provider configured';
  els.thinkingStatus.innerHTML = `
    ${dot} <strong>${running ? 'Running' : 'Stopped'}</strong>
    <span class="lab-thinking__sep">·</span>
    <span>${count} reflection${count === 1 ? '' : 's'}</span>
    <span class="lab-thinking__sep">·</span>
    <span>every ${interval}s</span>
    <span class="lab-thinking__sep">·</span>
    <span>last ${esc(last)}${esc(hasFn)}</span>
  `;
  if (!log.length) {
    els.thinkingLog.innerHTML = '<div class="lab-empty">No reflections yet.</div>';
    return;
  }
  els.thinkingLog.innerHTML = log.slice().reverse().map((entry) => `
    <article class="lab-thinking__entry">
      <time>${esc(formatTime(entry.ts))}</time>
      <p>${esc(entry.content || '')}</p>
    </article>
  `).join('');
}

async function startThinking() {
  const interval = Number(els.thinkingIntervalInput?.value) || 120;
  if (!Number.isFinite(interval) || interval < 30) {
    flash('Interval must be at least 30 seconds');
    return;
  }
  if (els.thinkingStartBtn) els.thinkingStartBtn.disabled = true;
  try {
    await request('/api/mind/thinking/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interval_s: interval }),
    });
    flash(`Thinking started (every ${interval}s)`);
    await loadThinking();
  } catch (error) {
    flash(`Start failed: ${error.message}`);
  } finally {
    if (els.thinkingStartBtn) els.thinkingStartBtn.disabled = false;
  }
}

async function stopThinking() {
  if (els.thinkingStopBtn) els.thinkingStopBtn.disabled = true;
  try {
    await request('/api/mind/thinking/stop', { method: 'POST' });
    flash('Thinking stopped');
    await loadThinking();
  } catch (error) {
    flash(`Stop failed: ${error.message}`);
  } finally {
    if (els.thinkingStopBtn) els.thinkingStopBtn.disabled = false;
  }
}

/* ── Navigation ──────────────────────────────────────────────────── */
function openPage(page) {
  els.navItems.forEach((item) => item.classList.toggle('active', item.dataset.page === page));
  els.pages.forEach((el) => el.classList.toggle('active', el.dataset.page === page));
  // Project tree stays visible on every page so the user can switch
  // sessions from anywhere (Memory, Tool Packs, Settings, etc.).
  if (page === 'memory') loadMemory();
  if (page === 'toolpacks') loadToolPacks();
  if (page === 'skillpacks') loadSkillPacks();
  if (page === 'logs') loadAgent();
  if (page === 'settings') {
    loadProviders();
    loadAgent();
    loadAgentSoul();
    loadCodex();
    loadThinking();
  }
}

function openInspectorTab(tab) {
  els.inspectorTabs.forEach((item) => item.classList.toggle('active', item.dataset.tab === tab));
  els.inspectorPanels.forEach((panel) => panel.classList.toggle('active', panel.dataset.panel === tab));
  if (tab === 'memory') loadMemory();
  if (tab === 'tools' || tab === 'logs') loadAgent();
}

/* ── Utilities ───────────────────────────────────────────────────── */
function setStatusbar(status, label) {
  els.statusbarDot.dataset.status = status;
  els.statusbarState.textContent = label;
}

function flash(text) {
  els.statusbarState.textContent = text;
  clearTimeout(flash._timer);
  flash._timer = setTimeout(() => setStatusbar('idle', 'Idle'), 2500);
}

function short(value) { return String(value || '').slice(0, 14); }

function formatTime(ts) {
  if (!ts) return '';
  return new Date(Number(ts) * 1000).toLocaleTimeString();
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}


/* ── Markdown rendering (Luna parity) ────────────────────────────── */

// Configure marked.js once at module load. We use GFM (tables, strike,
// task-lists, autolink) + `breaks: true` so a single newline becomes a
// <br> (most chat models emit messages that way). Code-block syntax
// highlighting is delegated to highlight.js when present.
//
// Both libraries are loaded from CDN in index.html. If either fails to
// load (offline, blocked CSP), we degrade gracefully: renderMarkdown()
// falls back to escaped-text-with-<br>.
let _markedConfigured = false;
function _ensureMarkedConfigured() {
  if (_markedConfigured) return;
  if (typeof window === 'undefined' || typeof window.marked === 'undefined') return;
  try {
    window.marked.setOptions({
      breaks: true,
      gfm: true,
      // The highlight callback receives the raw code block contents +
      // optional language hint and must return *already-escaped* HTML.
      highlight(code, lang) {
        if (typeof window.hljs === 'undefined') return esc(code);
        try {
          if (lang && window.hljs.getLanguage(lang)) {
            return window.hljs.highlight(code, { language: lang }).value;
          }
          return window.hljs.highlightAuto(code).value;
        } catch (_e) {
          return esc(code);
        }
      },
    });
    _markedConfigured = true;
  } catch (_e) {
    // marked.setOptions threw — leave _markedConfigured=false so we
    // retry on the next render. Worst case we keep falling back to
    // the escaped-text path.
  }
}

/**
 * Render markdown source as HTML.
 *
 * Always returns a safe-ish HTML fragment:
 * - If marked is loaded, runs marked.parse() then post-processes the
 *   resulting <pre><code> blocks to wrap them in a header strip with
 *   a language label + copy button (Luna pattern).
 * - If marked isn't loaded, returns escaped text with newline → <br>
 *   conversion, so the chat still renders something useful.
 *
 * Note: we trust the upstream LLM not to inject hostile HTML. If you
 * ever serve user-controlled content into this path, run the output
 * through DOMPurify first.
 */
function renderMarkdown(text) {
  const source = String(text ?? '');
  if (!source) return '';
  _ensureMarkedConfigured();
  if (typeof window === 'undefined' || typeof window.marked === 'undefined') {
    return esc(source).replace(/\n/g, '<br>');
  }
  let html;
  try {
    html = window.marked.parse(source);
  } catch (_e) {
    return esc(source).replace(/\n/g, '<br>');
  }
  // Wrap fenced code blocks with a header + copy button.
  html = html.replace(
    /<pre><code class="language-([\w.+-]+)">([\s\S]*?)<\/code><\/pre>/g,
    (_match, lang, code) => codeBlockHtml(lang, code),
  );
  html = html.replace(
    /<pre><code>([\s\S]*?)<\/code><\/pre>/g,
    (_match, code) => codeBlockHtml('', code),
  );
  return html;
}

/**
 * Wrap a code block in a header strip + copy button.
 *
 * `lang` is the language tag (or '' for auto-detected). `code` is the
 * already-escaped HTML emitted by marked + the highlight callback.
 */
function codeBlockHtml(lang, code) {
  const langLabel = lang ? esc(lang) : 'text';
  // Strip trailing newline marked.js sometimes leaves behind so the
  // code block doesn't have a blank line at the bottom.
  const cleaned = String(code).replace(/\n$/, '');
  return `<div class="lab-code-block">
    <header class="lab-code-block__head">
      <span class="lab-code-block__lang">${langLabel}</span>
      <button class="lab-code-block__copy" type="button" data-action="copy-code">Copy</button>
    </header>
    <pre><code class="hljs language-${langLabel}">${cleaned}</code></pre>
  </div>`;
}

function localFilePathFromLink(anchor) {
  const values = [
    anchor.getAttribute('href') || '',
    anchor.textContent || '',
  ];
  for (const value of values) {
    let candidate = String(value).trim();
    if (!candidate) continue;
    try { candidate = decodeURIComponent(candidate); } catch (_e) {}
    if (/^file:/i.test(candidate)) {
      try {
        const url = new URL(candidate);
        candidate = decodeURIComponent(url.pathname || '');
      } catch (_e) {
        candidate = candidate.replace(/^file:\/+/i, '');
      }
      if (/^\/[a-zA-Z]:[\\/]/.test(candidate)) candidate = candidate.slice(1);
    }
    if (/^[a-zA-Z]:[\\/]/.test(candidate) || /^\\\\[^\\]+\\[^\\]+/.test(candidate)) return candidate;
  }
  return '';
}

async function revealLocalFile(path) {
  if (!path) return;
  try {
    await request('/api/files/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
  } catch (error) {
    flash(`Could not open file: ${error.message}`);
  }
}

/** Inline-code post-processor: nothing to do (marked already emits
 * `<code>` for backticks). Kept as a hook for future enhancements. */
function hydrateRenderedMarkdown(root) {
  if (!root) return;
  // Wire up code-block copy buttons. We do this every time the body is
  // re-rendered because the buttons live inside DOM that gets replaced.
  root.querySelectorAll('[data-action="copy-code"]').forEach((btn) => {
    if (btn._wired) return;
    btn._wired = true;
    btn.addEventListener('click', () => {
      const wrapper = btn.closest('.lab-code-block');
      const code = wrapper?.querySelector('pre code');
      if (!code) return;
      const text = code.textContent || '';
      navigator.clipboard.writeText(text).then(
        () => {
          const prev = btn.textContent;
          btn.textContent = 'Copied';
          btn.classList.add('lab-code-block__copy--done');
          setTimeout(() => {
            btn.textContent = prev;
            btn.classList.remove('lab-code-block__copy--done');
          }, 1500);
        },
        () => { btn.textContent = 'Copy failed'; },
      );
    });
  });
  // Make external links open in a new tab.
  root.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href') || '';
    const localPath = localFilePathFromLink(a);
    if (localPath) {
      a.dataset.localFilePath = localPath;
      a.addEventListener('click', (event) => {
        event.preventDefault();
        revealLocalFile(localPath);
      });
      return;
    }
    if (/^https?:/i.test(href)) {
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    }
  });
}
