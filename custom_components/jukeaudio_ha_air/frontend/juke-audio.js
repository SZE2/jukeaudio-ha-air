const JUKE_ZONE_CARD = "juke-zone-card";
const JUKE_AUDIO_PANEL = "juke-audio-panel";
const HA_PANEL = `ha-panel-${JUKE_AUDIO_PANEL}`;

const create = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};

const zoneOptions = (state) => {
  const options = state?.attributes?.juke_input_options;
  return Array.isArray(options) ? options : [];
};

class JukeZoneCard extends HTMLElement {
  setConfig(config) {
    if (!config?.entity) throw new Error("Juke zone card requires an entity");
    this.config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { rows: 4, columns: 6, min_rows: 4 };
  }

  _call(domain, service, data) {
    this._hass?.callService(domain, service, data);
  }

  _render() {
    if (!this.config || !this._hass) return;
    const state = this._hass.states[this.config.entity];
    this.replaceChildren();
    const card = create("ha-card", "juke-zone-card");
    const header = create("div", "header");
    const title = create("div", "title", this.config.name || state?.attributes?.friendly_name || this.config.entity);
    const power = create("button", "power", state?.state === "off" ? "Turn on" : "Turn off");
    power.disabled = !state || state.state === "unavailable";
    power.addEventListener("click", () => {
      this._call("media_player", state?.state === "off" ? "turn_on" : "turn_off", { entity_id: this.config.entity });
    });
    header.append(title, power);
    card.append(header);

    if (!state) {
      card.append(create("div", "notice", "Zone entity is unavailable."));
      this.append(card);
      return;
    }

    const status = create("div", "status", `Zone: ${state.state}`);
    const active = state.attributes?.source || "No selected input";
    status.append(create("span", "active-source", `Selected: ${active}`));
    card.append(status);

    const inputs = create("div", "inputs");
    for (const option of zoneOptions(state)) {
      const selected = option.source === state.attributes?.source;
      const selectable = Boolean(option.selectable) && !selected;
      const button = create("button", "input-option");
      button.disabled = !selectable;
      button.classList.toggle("selected", selected);
      button.classList.toggle("streaming", Boolean(option.streaming));
      button.classList.toggle("unavailable", !option.selectable && !selected);
      button.title = selected
        ? "Selected by Juke"
        : option.selectable
          ? "Select this Juke streaming input"
          : option.enabled
            ? "Waiting for Juke to report this input as streaming"
            : "Disabled in Juke";
      const label = create("span", "input-label", option.source || option.input_id);
      button.append(label);
      if (option.streaming) button.append(create("span", "activity", "●"));
      if (selected) button.append(create("span", "selected-label", "Selected"));
      if (!option.selectable && !selected) button.append(create("span", "reason", option.enabled ? "Waiting" : "Disabled"));
      if (selectable) {
        button.addEventListener("click", () => {
          this._call("media_player", "select_source", {
            entity_id: this.config.entity,
            source: option.source,
          });
        });
      }
      inputs.append(button);
    }
    if (!inputs.childElementCount) inputs.append(create("div", "notice", "No routed Juke sources are available."));
    card.append(inputs);
    this.append(card);
  }
}

class JukeAudioPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;
    this.replaceChildren();
    const root = create("div", "panel");
    root.append(create("h1", null, "Juke Audio"));
    root.append(create("p", "lead", "Juke remains authoritative for zone state, routing, and source availability."));

    const zoneStates = Object.entries(this._hass.states)
      .filter(([, state]) => Array.isArray(state.attributes?.juke_input_options))
      .sort(([, left], [, right]) => String(left.attributes?.friendly_name || "").localeCompare(String(right.attributes?.friendly_name || "")));
    const zoneGrid = create("div", "zone-grid");
    for (const [entityId, state] of zoneStates) {
      const card = document.createElement(JUKE_ZONE_CARD);
      card.setConfig({ entity: entityId, name: state.attributes?.friendly_name });
      card.hass = this._hass;
      zoneGrid.append(card);
    }
    if (!zoneStates.length) zoneGrid.append(create("div", "notice", "No Juke zones are currently available."));
    root.append(zoneGrid);

    root.append(create("h2", null, "General inputs"));
    const inputGrid = create("div", "input-grid");
    const entities = Object.entries(this._hass.states);
    const inputIds = new Set(
      entities
        .map(([, state]) => state.attributes?.juke_input_id)
        .filter((inputId) => typeof inputId === "string"),
    );
    for (const inputId of [...inputIds].sort()) {
      const records = entities.filter(([, state]) => state.attributes?.juke_input_id === inputId);
      const enabled = records.find(([, state]) => state.attributes?.juke_entity_role === "input_enabled");
      const type = records.find(([, state]) => state.attributes?.juke_entity_role === "input_type");
      const routes = records.filter(([, state]) => state.attributes?.juke_entity_role === "input_route");
      const card = create("ha-card", "input-card");
      card.append(create("h3", null, enabled?.[1].attributes?.friendly_name?.replace(/ Enabled$/, "") || inputId));
      if (enabled) {
        const toggle = create("button", "input-toggle", enabled[1].state === "on" ? "Enabled" : "Disabled");
        toggle.addEventListener("click", () => this._hass.callService("homeassistant", enabled[1].state === "on" ? "turn_off" : "turn_on", { entity_id: enabled[0] }));
        card.append(toggle);
      }
      if (type) {
        const selector = document.createElement("select");
        for (const value of type[1].attributes?.options || []) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = value;
          option.selected = value === type[1].state;
          selector.append(option);
        }
        selector.addEventListener("change", () => this._hass.callService("select", "select_option", { entity_id: type[0], option: selector.value }));
        card.append(selector);
      }
      const routeList = create("div", "routes");
      for (const [entityId, route] of routes) {
        const routeButton = create("button", route.state === "on" ? "route on" : "route", route.attributes?.friendly_name || entityId);
        routeButton.addEventListener("click", () => this._hass.callService("homeassistant", route.state === "on" ? "turn_off" : "turn_on", { entity_id: entityId }));
        routeList.append(routeButton);
      }
      card.append(routeList);
      inputGrid.append(card);
    }
    if (!inputIds.size) inputGrid.append(create("div", "notice", "Input configuration entities will appear when the Juke integration is loaded."));
    root.append(inputGrid);
    this.append(root);
  }
}

const style = document.createElement("style");
style.textContent = `
  ${HA_PANEL} { display:block; padding:16px; max-width:1500px; margin:auto; }
  ${HA_PANEL} .lead, .juke-zone-card .status { color:var(--secondary-text-color); }
  ${HA_PANEL} .zone-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; }
  ${HA_PANEL} .input-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }
  .juke-zone-card { display:block; }
  .juke-zone-card ha-card, ${HA_PANEL} .input-card { padding:14px; }
  .juke-zone-card .header { display:flex; justify-content:space-between; gap:8px; align-items:center; }
  .juke-zone-card .title { font-size:1.1em; font-weight:600; }
  .juke-zone-card .status { display:flex; justify-content:space-between; gap:8px; font-size:.86em; margin:10px 0; }
  .juke-zone-card .inputs { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:8px; }
  .juke-zone-card .input-option { min-height:60px; text-align:left; display:grid; gap:3px; border:1px solid var(--divider-color); border-radius:8px; padding:8px; background:var(--card-background-color); color:var(--primary-text-color); }
  .juke-zone-card .input-option.selected { border:2px solid var(--primary-color); background:color-mix(in srgb,var(--primary-color) 12%,var(--card-background-color)); }
  .juke-zone-card .input-option.unavailable { opacity:.55; }
  .juke-zone-card .activity { color:var(--success-color,#43a047); animation:juke-pulse 1.2s ease-in-out infinite; }
  .juke-zone-card .selected-label, .juke-zone-card .reason { font-size:.78em; color:var(--secondary-text-color); }
  ${HA_PANEL} button, ${HA_PANEL} select { font:inherit; padding:7px 9px; border-radius:7px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); cursor:pointer; }
  ${HA_PANEL} button:disabled { cursor:not-allowed; }
  ${HA_PANEL} .input-card h3 { margin-top:0; }
  ${HA_PANEL} .routes { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
  ${HA_PANEL} .route.on { border-color:var(--primary-color); background:color-mix(in srgb,var(--primary-color) 12%,var(--card-background-color)); }
  .notice { padding:10px; color:var(--secondary-text-color); }
  @keyframes juke-pulse { 50% { opacity:.25; transform:scale(.85); } }
`;
document.head.append(style);

if (!customElements.get(JUKE_ZONE_CARD)) customElements.define(JUKE_ZONE_CARD, JukeZoneCard);
if (!customElements.get(HA_PANEL)) customElements.define(HA_PANEL, JukeAudioPanel);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === JUKE_ZONE_CARD)) {
  window.customCards.push({ type: JUKE_ZONE_CARD, name: "Juke Zone Card", description: "Juke-aware zone input control" });
}
