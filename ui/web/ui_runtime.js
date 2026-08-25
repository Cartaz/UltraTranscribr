"use strict";

// Single composition boundary for the local frontend. app.js owns the base
// presentation; domain modules register optional hooks here without replacing
// one another's globals.
const uiBase = {
  bind,
  hydrate,
  event,
  sessionBusy,
  liveUI,
  fileUI,
  sourceUI,
  switchView,
  updateSelectedStreamMeta,
  startLive,
  saveSettings,
  showHistorySession,
  clearHistorySelection,
  refreshHistoryList,
  historyTitle,
  lockSettings,
  refreshStreams,
  refreshDevices,
};

const uiModules = [];
const uiRuntime = {bound: false, bootstrap: null};

function registerUIModule(module) {
  if (!module || typeof module !== "object") return;
  uiModules.push(module);
  if (uiRuntime.bound && typeof module.bind === "function") module.bind();
  if (uiRuntime.bootstrap && typeof module.hydrate === "function") {
    module.hydrate(uiRuntime.bootstrap);
  }
}

window.UltraUI = Object.freeze({register: registerUIModule});

bind = function() {
  uiBase.bind();
  uiRuntime.bound = true;
  uiModules.forEach(module => module.bind?.());
};

hydrate = function(bootstrap) {
  uiRuntime.bootstrap = bootstrap;
  let baseBootstrap = bootstrap;
  uiModules.forEach(module => {
    if (typeof module.transformBootstrap === "function") {
      baseBootstrap = module.transformBootstrap(baseBootstrap) || baseBootstrap;
    }
  });
  uiBase.hydrate(baseBootstrap);
  uiModules.forEach(module => module.hydrate?.(bootstrap));
};

event = function(name, payload) {
  const value = json(payload);
  let consumed = false;
  uiModules.forEach(module => {
    if (module.event?.(name, value, payload) === true) consumed = true;
  });
  if (!consumed) uiBase.event(name, payload);
};

sessionBusy = function() {
  return uiBase.sessionBusy() || uiModules.some(module => module.isBusy?.() === true);
};

liveUI = function(statusText) {
  const handler = uiModules.find(module => typeof module.liveUI === "function");
  if (handler) handler.liveUI(statusText);
  else uiBase.liveUI(statusText);
};

fileUI = function(statusText) {
  uiBase.fileUI(statusText);
  uiModules.forEach(module => module.fileUI?.(statusText));
};

sourceUI = function() {
  uiBase.sourceUI();
  uiModules.forEach(module => module.sourceUI?.());
};

switchView = function(name) {
  uiBase.switchView(name);
  uiModules.forEach(module => module.view?.(name));
};

updateSelectedStreamMeta = function() {
  uiBase.updateSelectedStreamMeta();
  uiModules.forEach(module => module.streamMeta?.());
};

startLive = function() {
  const handler = [...uiModules].reverse().find(module => typeof module.startLive === "function");
  if (!handler || handler.startLive() !== true) uiBase.startLive();
};

saveSettings = function(eventObject) {
  const handler = [...uiModules].reverse().find(module => typeof module.saveSettings === "function");
  if (!handler || handler.saveSettings(eventObject) !== true) uiBase.saveSettings(eventObject);
};

showHistorySession = function(session) {
  uiBase.showHistorySession(session);
  uiModules.forEach(module => module.historySession?.(session));
};

clearHistorySelection = function() {
  uiBase.clearHistorySelection();
  uiModules.forEach(module => module.historyClear?.());
};

refreshHistoryList = function() {
  const handler = [...uiModules].reverse().find(module => typeof module.refreshHistoryList === "function");
  if (!handler || handler.refreshHistoryList() !== true) uiBase.refreshHistoryList();
};

historyTitle = function(session) {
  return uiModules.reduce(
    (current, module) => module.historyTitle?.(session, current) ?? current,
    uiBase.historyTitle(session),
  );
};

lockSettings = function() {
  uiBase.lockSettings();
  uiModules.forEach(module => module.lockSettings?.());
};

refreshStreams = function() {
  const handler = [...uiModules].reverse().find(module => typeof module.refreshStreams === "function");
  if (!handler || handler.refreshStreams() !== true) uiBase.refreshStreams();
};

refreshDevices = function() {
  const handler = [...uiModules].reverse().find(module => typeof module.refreshDevices === "function");
  if (!handler || handler.refreshDevices() !== true) uiBase.refreshDevices();
};
