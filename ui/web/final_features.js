"use strict";

function finalEnsureUI() {
  const historyHead = document.querySelector('[data-panel="history"] #history-title')?.closest('.card-head');
  if (historyHead && !$("history-rename")) {
    const tools = historyHead.querySelector('.toolbar');
    if (tools) {
      const input = document.createElement('input');
      input.id = 'history-name';
      input.type = 'text';
      input.maxLength = 120;
      input.placeholder = 'Nome sessione';
      input.setAttribute('aria-label', 'Nome sessione');
      input.disabled = true;
      const button = document.createElement('button');
      button.id = 'history-rename';
      button.type = 'button';
      button.textContent = 'Rinomina';
      button.disabled = true;
      tools.prepend(button);
      tools.prepend(input);
    }
  }

  const backendCard = [...document.querySelectorAll('[data-settings-pane="advanced"] .card')]
    .find(card => card.querySelector('input[name="server_port"]'));
  if (backendCard && !document.querySelector('[name="backend_instances"]')) {
    const fields = backendCard.querySelector('.fields');
    fields?.insertAdjacentHTML('beforeend', `
      <div><label for="s-instances">Istanze backend</label><input id="s-instances" name="backend_instances" type="number" min="1" max="4"></div>
      <div><label class="toggle-row compact-toggle" for="s-preload"><span><strong>Preload all'avvio</strong><small>Carica il modello installato all'apertura.</small></span><input id="s-preload" name="preload_model" type="checkbox"><i></i></label></div>`);
  }
}

const finalLegacyHistoryTitle = historyTitle;
historyTitle = function(session) {
  const custom = String(session?.name || '').trim();
  return custom || finalLegacyHistoryTitle(session);
};

const finalLegacyShowHistorySession = showHistorySession;
showHistorySession = function(session) {
  finalLegacyShowHistorySession(session);
  finalEnsureUI();
  const input = $("history-name");
  const button = $("history-rename");
  if (input) {
    input.disabled = !session;
    input.value = String(session?.name || '');
  }
  if (button) button.disabled = !session;
};

const finalLegacyClearHistorySelection = clearHistorySelection;
clearHistorySelection = function() {
  finalLegacyClearHistorySelection();
  finalEnsureUI();
  if ($("history-name")) { $("history-name").value = ''; $("history-name").disabled = true; }
  if ($("history-rename")) $("history-rename").disabled = true;
};

function finalRenameHistory() {
  if (!state.historySelected) return;
  const name = $("history-name")?.value || '';
  call('renameHistorySession', [state.historySelected, name], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || 'Rinomina non riuscita', 'history');
      return;
    }
    if (powerCurrentSession && powerCurrentSession.id === state.historySelected) {
      powerCurrentSession.name = response.name || '';
      $("history-title").textContent = historyTitle(powerCurrentSession);
    }
    refreshHistoryList();
    notice(response.name ? 'Nome sessione salvato' : 'Nome sessione rimosso');
  });
}

const finalLegacyBind = bind;
bind = function() {
  finalEnsureUI();
  finalLegacyBind();
  if ($("history-rename")) $("history-rename").onclick = finalRenameHistory;
  if ($("history-name")) $("history-name").onkeydown = eventObject => {
    if (eventObject.key === 'Enter') {
      eventObject.preventDefault();
      finalRenameHistory();
    }
  };
};

const finalLegacyHydrate = hydrate;
hydrate = function(bootstrap) {
  finalEnsureUI();
  finalLegacyHydrate(bootstrap);
  phase6HydrateSettings(bootstrap.settings || {});
};

const finalLegacyResetSettingsSection = resetSettingsSection;
resetSettingsSection = function(sectionName) {
  if (sectionName !== 'backend') return finalLegacyResetSettingsSection(sectionName);
  if (sessionBusy() || state.modelBusy) {
    notice('Ferma le operazioni attive prima di ripristinare questa sezione', true);
    return;
  }
  phase6LoadDefaults(defaults => {
    const keys = ['server_port', 'gpu_layers', 'compute_type', 'backend_instances', 'preload_model'];
    const payload = {};
    keys.forEach(key => { payload[key] = defaults[key]; });
    phase6ApplySettings(payload, 'Sezione ripristinata ai valori predefiniti');
  });
};

finalEnsureUI();
