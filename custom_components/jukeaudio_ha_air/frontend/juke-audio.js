const JUKE_ZONE_CARD = "juke-zone-card";
const JUKE_AUDIO_PANEL = "juke-audio-panel";
const HA_PANEL = `ha-panel-${JUKE_AUDIO_PANEL}`;

const create = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};

const createStyle = (cssText) => {
  const style = document.createElement("style");
  style.textContent = cssText;
  return style;
};

const zoneOptions = (state) => {
  const options = state?.attributes?.juke_input_options;
  return Array.isArray(options) ? options : [];
};

const readableLabel = (value, fallback) => {
  const label = String(value ?? "")
    .trim()
    .replace(/^juke[-_\s]+/i, "")
    .replace(/^zone[-_\s]?(\d+)$/i, "Zone $1")
    .replace(/[_-]+/g, " ");
  return label || fallback;
};

const formatSourceLabel = (value) => {
  const label = readableLabel(value, "Unknown source");
  const normalized = label.replace(/[\s_-]+/g, "").toLowerCase();
  if (normalized === "airplay" || normalized === "airplay2") return "AirPlay 2";
  if (normalized === "dlna2") return "DLNA 2";
  return label.replace(/\bAirplay2\b/gi, "AirPlay 2").replace(/\bDlna2\b/gi, "DLNA 2");
};

const zoneDisplayName = (state, entityId) =>
  readableLabel(state?.attributes?.juke_zone_name || state?.attributes?.juke_zone_id || entityId, "Unknown zone");

const inputDisplayName = (records, inputId) => {
  const namedRecord = records.find(
    ([, state]) => typeof state.attributes?.juke_input_name === "string",
  );
  return readableLabel(namedRecord?.[1].attributes.juke_input_name || inputId, "Unknown input");
};

const routeDisplayName = (route, entityId) =>
  readableLabel(
    route.attributes?.juke_zone_name || route.attributes?.juke_zone_id || entityId,
    "Unknown zone",
  );

const sourcePresentation = (option, activeSource, zoneState) => {
  const isCurrent = option?.source === activeSource;
  const isStreaming = option?.streaming === true;
  const zoneOperational = zoneState?.state !== "off" && zoneState?.state !== "unavailable";
  const selectable = Boolean(option && option.selectable === true && zoneOperational);
  const state = option?.enabled === false || !zoneOperational ? "disabled" : isCurrent ? "current" : selectable ? "available" : "waiting";
  const currentStreaming = isCurrent && isStreaming;
  const animate = zoneOperational && currentStreaming;
  return { isCurrent, isStreaming, selectable, state, animate };
};

const sourceStatus = (presentation) => {
  if (presentation.isCurrent) return presentation.isStreaming ? "Streaming now" : "Selected · idle";
  if (presentation.state === "available") return presentation.isStreaming ? "Available now" : "Available";
  if (presentation.state === "disabled") return "Disabled";
  return "Waiting for stream";
};

const zoneCardStyle = `
  :host { display: block; min-width: 0; }
  * { box-sizing: border-box; }
  ha-card {
    display: block;
    height: 100%;
    min-height: 255px;
    padding: 17px;
    color: var(--primary-text-color, #edf2f5);
    background: var(--card-background-color, #1b2025);
    border: 1px solid var(--divider-color, #37424b);
    border-radius: 15px;
    box-shadow: 0 12px 32px rgb(0 0 0 / 18%);
  }
  .card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .zone-name { font-size: 1rem; font-weight: 720; letter-spacing: -.015em; }
  .zone-meta { margin-top: 4px; color: var(--secondary-text-color, #aeb9c1); font-size: .78rem; }
  .power {
    width: 42px;
    height: 25px;
    flex: 0 0 auto;
    padding: 3px;
    border: 0;
    border-radius: 999px;
    background: var(--disabled-text-color, #4a565f);
    cursor: pointer;
    transition: background .18s;
  }
  .power::after {
    content: "";
    display: block;
    width: 19px;
    height: 19px;
    border-radius: 50%;
    background: var(--primary-background-color, #dce5ea);
    transition: transform .18s;
  }
  .power.on { background: var(--primary-color, #4fc3f7); }
  .power.on::after { transform: translateX(17px); background: #fff; }
  .power:disabled { cursor: not-allowed; opacity: .55; }
  ha-card.zone-off { opacity: .72; }
  ha-card.zone-unavailable { opacity: .58; }
  .now {
    margin: 17px 0 12px;
    padding: 10px 11px;
    border: 1px solid var(--divider-color, #2f3a42);
    border-radius: 10px;
    background: var(--primary-background-color, #171c20);
  }
  .now-label {
    color: var(--secondary-text-color, #75838d);
    font-size: .7rem;
    letter-spacing: .08em;
    text-transform: uppercase;
  }
  .now-main { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 3px; font-size: .9rem; font-weight: 650; }
  .live { display: inline-flex; align-items: center; gap: 5px; color: var(--success-color, #66d19e); font-size: .73rem; font-weight: 700; }
  .live::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
  .inputs { display: flex; flex-wrap: wrap; gap: 7px; margin-top: auto; }
  .source-option {
    min-width: 112px;
    min-height: 54px;
    flex: 1 1 112px;
    padding: 8px 9px;
    border: 1px solid var(--divider-color, #37424b);
    border-radius: 9px;
    color: var(--secondary-text-color, #aeb9c1);
    background: var(--secondary-background-color, #232a30);
    text-align: left;
    cursor: pointer;
    transition: border-color .16s, background .16s, color .16s, opacity .16s;
  }
  .source-option:hover:not(:disabled) { border-color: var(--primary-color, #4fc3f7); color: var(--primary-text-color, #edf2f5); }
  .source-option:focus-visible, .power:focus-visible, button:focus-visible, select:focus-visible { outline: 2px solid var(--primary-color, #4fc3f7); outline-offset: 2px; }
  .source-option.selected, .source-option.source-current {
    border-color: var(--success-color, #66d19e);
    color: var(--primary-text-color, #edf2f5);
    background: rgb(23 58 43 / 90%);
  }
  .source-option.source-available { border-color: var(--primary-color, #4fc3f7); }
  .source-option.source-waiting { border-color: var(--warning-color, #eeb55c); color: var(--secondary-text-color, #aeb9c1); }
  .source-option.source-disabled { opacity: .55; cursor: not-allowed; }
  .source-option:disabled { cursor: not-allowed; }
  .source-label { display: block; font-size: .78rem; font-weight: 650; }
  .source-status { display: block; margin-top: 2px; color: var(--secondary-text-color, #75838d); font-size: .65rem; }
  .source-option.source-waiting .source-status { color: var(--warning-color, #bb9560); }
  .source-option.source-live .source-status { color: var(--success-color, #a9dfc1); }
  .source-live .activity { display: inline-block; width: 6px; height: 6px; margin-right: 5px; border-radius: 50%; background: var(--success-color, #66d19e); animation: juke-pulse 1.3s ease-in-out infinite; }
  .notice { padding: 10px; color: var(--secondary-text-color, #aeb9c1); }
  @keyframes juke-pulse { 50% { box-shadow: 0 0 0 6px rgb(102 209 158 / 0); transform: scale(.8); } }
  @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
`;

class JukeZoneCard extends HTMLElement {
  constructor() {
    super();
    this._shadow = this.attachShadow({ mode: "open" });
    this._shadow.append(createStyle(zoneCardStyle));
    this._content = create("div", "zone-card-content");
    this._shadow.append(this._content);
  }

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
    const state = this._hass.states?.[this.config.entity];
    this._content.replaceChildren();
    const card = create(
      "ha-card",
      state?.state === "off" ? "zone-off" : state?.state === "unavailable" ? "zone-unavailable" : "",
    );
    const header = create("div", "card-head");
    const zoneName = zoneDisplayName(state, this.config.entity);
    const heading = create("div");
    heading.append(
      create("div", "zone-name", zoneName),
      create(
        "div",
        "zone-meta",
        !state ? "Zone unavailable" : state.state === "off" ? "Zone disabled" : "Zone enabled",
      ),
    );
    const powerOn = state?.state !== "off";
    const power = create("button", `power${powerOn ? " on" : ""}`);
    power.type = "button";
    power.disabled = !state || state.state === "unavailable";
    power.setAttribute("aria-label", `${powerOn ? "Turn off" : "Turn on"} ${zoneName}`);
    power.setAttribute("aria-pressed", String(powerOn));
    power.addEventListener("click", () => {
      this._call("media_player", powerOn ? "turn_off" : "turn_on", { entity_id: this.config.entity });
    });
    header.append(heading, power);
    card.append(header);

    if (!state) {
      card.append(create("div", "notice", "Zone entity is unavailable."));
      this._content.append(card);
      return;
    }

    const activeSource = state.attributes?.source || null;
    const now = create("div", "now");
    now.append(create("div", "now-label", "Selected source"));
    const nowMain = create("div", "now-main");
    nowMain.append(create("span", null, activeSource ? formatSourceLabel(activeSource) : "No selected input"));
    if (state.state === "playing") nowMain.append(create("span", "live", "Live"));
    else nowMain.append(create("span", "zone-meta", "Idle"));
    now.append(nowMain);
    card.append(now);

    const inputs = create("div", "inputs");
    for (const option of zoneOptions(state)) {
      const presentation = sourcePresentation(option, activeSource, state);
      const button = create(
        "button",
        `source-option source-${presentation.state}${presentation.isCurrent ? " source-current selected" : ""}${presentation.animate ? " source-live" : ""}`,
      );
      button.type = "button";
      button.disabled = !presentation.selectable;
      button.setAttribute("aria-pressed", String(presentation.isCurrent));
      button.title = presentation.isCurrent
        ? presentation.isStreaming
          ? "Currently selected and streaming"
          : "Currently selected; waiting for stream"
        : presentation.state === "available"
          ? "Select this Juke streaming input"
          : presentation.state === "disabled"
            ? "Disabled in Juke"
            : "Waiting for Juke to report this input as streaming";
      const sourceLabel = create("span", "source-label", formatSourceLabel(option.source || option.input_id));
      const status = create("span", "source-status");
      if (presentation.animate) status.append(create("span", "activity"));
      status.append(document.createTextNode(sourceStatus(presentation)));
      button.append(sourceLabel, status);
      if (presentation.selectable) {
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
    this._content.append(card);
  }
}

const panelStyle = `
  :host { display: block; min-height: 100%; }
  * { box-sizing: border-box; }
  .panel-shell {
    max-width: 1480px;
    margin: 0 auto;
    padding: 28px clamp(16px, 3vw, 46px) 54px;
    color: var(--primary-text-color, #edf2f5);
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .eyebrow { color: var(--primary-color, #4fc3f7); font-size: .72rem; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
  .hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 28px; }
  h1 { margin: 5px 0 7px; font-size: clamp(1.7rem, 4vw, 2.55rem); letter-spacing: -.045em; }
  h2 { margin: 0; font-size: 1.15rem; letter-spacing: -.025em; }
  .lede { max-width: 620px; margin: 0; color: var(--secondary-text-color, #aeb9c1); font-size: .95rem; line-height: 1.55; }
  .summary { display: flex; align-items: center; gap: 10px; color: var(--secondary-text-color, #aeb9c1); font-size: .85rem; white-space: nowrap; }
  .summary-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--success-color, #66d19e); box-shadow: 0 0 0 4px rgb(102 209 158 / 14%); }
  .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin: 22px 0 16px; }
  .section-title { display: flex; align-items: baseline; gap: 10px; }
  .count { color: var(--secondary-text-color, #75838d); font-size: .82rem; }
  .legend { display: flex; flex-wrap: wrap; gap: 8px; color: var(--secondary-text-color, #aeb9c1); font-size: .78rem; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .legend i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
  .legend .stream { background: var(--success-color, #66d19e); }
  .legend .waiting { background: var(--warning-color, #eeb55c); }
  .legend .off { background: var(--disabled-text-color, #6f7b84); }
  .zone-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
  .input-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 16px; }
  .input-section { margin-top: 39px; padding-top: 3px; }
  .input-card {
    display: block;
    padding: 18px;
    color: var(--primary-text-color, #edf2f5);
    background: var(--card-background-color, #1b2025);
    border: 1px solid var(--divider-color, #37424b);
    border-radius: 15px;
    box-shadow: 0 12px 32px rgb(0 0 0 / 18%);
  }
  .input-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .input-name { font-size: 1rem; font-weight: 720; }
  .state-badge { padding: 5px 8px; border-radius: 999px; color: #9bdbbb; background: rgb(23 58 43 / 90%); font-size: .73rem; font-weight: 700; }
  .state-badge.disabled { color: #c5a7a7; background: rgb(57 36 38 / 90%); }
  .config { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 16px 0 14px; }
  .control-label { display: block; margin-bottom: 6px; color: var(--secondary-text-color, #75838d); font-size: .7rem; font-weight: 720; letter-spacing: .065em; text-transform: uppercase; }
  select, .input-card button {
    font: inherit;
    border: 1px solid var(--divider-color, #37424b);
    border-radius: 9px;
    color: var(--primary-text-color, #edf2f5);
    background: var(--secondary-background-color, #232a30);
  }
  select { width: 100%; padding: 9px; }
  select:disabled { cursor: not-allowed; opacity: .55; }
  .switch-line { display: flex; align-items: center; justify-content: space-between; min-height: 39px; padding: 0 10px; border: 1px solid var(--divider-color, #37424b); border-radius: 9px; color: var(--secondary-text-color, #aeb9c1); background: var(--secondary-background-color, #232a30); font-size: .84rem; }
  .tiny-switch { width: 32px; height: 18px; padding: 2px; border: 0 !important; border-radius: 99px !important; background: var(--disabled-text-color, #49555f) !important; cursor: pointer; }
  .tiny-switch::after { content: ""; display: block; width: 14px; height: 14px; border-radius: 50%; background: var(--primary-background-color, #eaf1f5); transition: transform .16s; }
  .tiny-switch.on { background: var(--primary-color, #4fc3f7) !important; }
  .tiny-switch.on::after { transform: translateX(14px); }
  .routes-title { display: flex; justify-content: space-between; margin: 3px 0 9px; color: var(--secondary-text-color, #aeb9c1); font-size: .78rem; }
  .routes { display: flex; flex-wrap: wrap; gap: 7px; }
  .route { padding: 7px 9px; color: var(--secondary-text-color, #aeb9c1); background: transparent !important; cursor: pointer; font-size: .77rem; }
  .route:hover:not(:disabled) { border-color: var(--primary-color, #4fc3f7); color: var(--primary-text-color, #edf2f5); }
  .route.on { border-color: var(--success-color, #4d986f); color: var(--success-color, #b6edce); background: rgb(23 58 43 / 90%) !important; }
  .route:disabled { cursor: not-allowed; opacity: .55; }
  .prototype-note { margin-top: 24px; color: var(--secondary-text-color, #75838d); font-size: .78rem; line-height: 1.45; }
  .notice { padding: 10px; color: var(--secondary-text-color, #aeb9c1); }
  @media (max-width: 1060px) { .zone-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 680px) {
    .hero, .toolbar { align-items: flex-start; flex-direction: column; }
    .zone-grid, .input-grid { grid-template-columns: 1fr; }
    .panel-shell { padding-top: 20px; }
  }
  /* Mobile browsers can report a wide CSS viewport; use touch capability too. */
  @media (pointer: coarse) {
    .input-grid { grid-template-columns: 1fr; }
  }
  @media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition: none !important; } }
`;

class JukeAudioPanel extends HTMLElement {
  constructor() {
    super();
    this._shadow = this.attachShadow({ mode: "open" });
    this._shadow.append(createStyle(panelStyle));
    this._content = create("div", "panel-content");
    this._shadow.append(this._content);
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;
    this._content.replaceChildren();
    const states = this._hass.states || {};
    const zoneStates = Object.entries(states)
      .filter(([, state]) => Array.isArray(state.attributes?.juke_input_options))
      .sort(([leftId, left], [rightId, right]) =>
        zoneDisplayName(left, leftId).localeCompare(zoneDisplayName(right, rightId)),
      );

    const root = create("main", "panel-shell");
    const hero = create("header", "hero");
    const heroCopy = create("div");
    heroCopy.append(
      create("div", "eyebrow", "Audio routing"),
      create("h1", null, "Juke Audio"),
      create("p", "lede", "A compact control surface for zone power, available sources, and input routing — without turning every underlying entity into a wall of controls."),
    );
    const summary = create("div", "summary");
    summary.append(create("span", "summary-dot"), create("span", null, `${zoneStates.length} zones · Juke state from Home Assistant`));
    hero.append(heroCopy, summary);
    root.append(hero);

    const toolbar = create("div", "toolbar");
    const sectionTitle = create("div", "section-title");
    sectionTitle.append(create("h2", null, "Zones"), create("span", "count", `${zoneStates.length} zones`));
    const legend = create("div", "legend");
    const legendItems = [["stream", "streaming / selectable"], ["waiting", "waiting"], ["off", "disabled"]];
    for (const [className, label] of legendItems) {
      const item = create("span");
      item.append(create("i", className), create("span", null, label));
      legend.append(item);
    }
    toolbar.append(sectionTitle, legend);
    root.append(toolbar);

    const zoneGrid = create("div", "zone-grid");
    for (const [entityId, state] of zoneStates) {
      const card = document.createElement(JUKE_ZONE_CARD);
      card.setConfig({ entity: entityId });
      card.hass = this._hass;
      zoneGrid.append(card);
    }
    if (!zoneStates.length) zoneGrid.append(create("div", "notice", "No Juke zones are currently available."));
    root.append(zoneGrid);

    const inputSection = create("section", "input-section");
    const inputToolbar = create("div", "toolbar");
    const inputTitle = create("div", "section-title");
    inputTitle.append(create("h2", null, "Inputs & routing"), create("span", "count", "Configuration only — not media players"));
    inputToolbar.append(inputTitle);
    inputSection.append(inputToolbar);

    const inputGrid = create("div", "input-grid");
    const inputIds = new Set(
      Object.values(states)
        .map((state) => state.attributes?.juke_input_id)
        .filter((inputId) => typeof inputId === "string"),
    );
    const entities = Object.entries(states);
    const sortedInputIds = [...inputIds].sort((leftId, rightId) => {
      const leftRecords = entities.filter(([, state]) => state.attributes?.juke_input_id === leftId);
      const rightRecords = entities.filter(([, state]) => state.attributes?.juke_input_id === rightId);
      return inputDisplayName(leftRecords, leftId).localeCompare(inputDisplayName(rightRecords, rightId));
    });

    for (const inputId of sortedInputIds) {
      const records = entities.filter(([, state]) => state.attributes?.juke_input_id === inputId);
      const enabled = records.find(([, state]) => state.attributes?.juke_entity_role === "input_enabled");
      const type = records.find(([, state]) => state.attributes?.juke_entity_role === "input_type");
      const routes = records
        .filter(([, state]) => state.attributes?.juke_entity_role === "input_route")
        .sort(([leftId, left], [rightId, right]) => routeDisplayName(left, leftId).localeCompare(routeDisplayName(right, rightId)));
      const card = create("ha-card", "input-card");
      const inputTop = create("div", "input-top");
      const inputName = inputDisplayName(records, inputId);
      inputTop.append(create("div", "input-name", inputName));
      if (enabled) {
        const enabledState = enabled[1].state === "on";
        inputTop.append(create("span", `state-badge${enabledState ? "" : " disabled"}`, enabledState ? "Enabled" : "Disabled"));
      }
      card.append(inputTop);

      const config = create("div", "config");
      if (type) {
        const typeControl = create("div");
        typeControl.append(create("label", "control-label", "Input type"));
        const selector = document.createElement("select");
        selector.disabled = type[1].state === "unavailable";
        for (const value of type[1].attributes?.options || []) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = formatSourceLabel(value);
          option.selected = value === type[1].state;
          selector.append(option);
        }
        selector.addEventListener("change", () => this._hass.callService("select", "select_option", { entity_id: type[0], option: selector.value }));
        typeControl.append(selector);
        config.append(typeControl);
      }
      if (enabled) {
        const availability = create("div");
        availability.append(create("label", "control-label", "Availability"));
        const switchLine = create("div", "switch-line");
        const enabledState = enabled[1].state === "on";
        switchLine.append(create("span", null, enabledState ? "Available" : "Disabled"));
        const toggle = create("button", `tiny-switch${enabledState ? " on" : ""}`);
        toggle.type = "button";
        toggle.disabled = enabled[1].state === "unavailable";
        toggle.setAttribute("aria-label", `${enabledState ? "Disable" : "Enable"} ${inputName}`);
        toggle.setAttribute("aria-pressed", String(enabledState));
        toggle.addEventListener("click", () => this._hass.callService("homeassistant", enabledState ? "turn_off" : "turn_on", { entity_id: enabled[0] }));
        switchLine.append(toggle);
        availability.append(switchLine);
        config.append(availability);
      }
      if (config.childElementCount) card.append(config);

      const routesTitle = create("div", "routes-title");
      routesTitle.append(create("span", null, "Routed zones"), create("span", null, "tap to edit"));
      card.append(routesTitle);
      const routeList = create("div", "routes");
      for (const [entityId, route] of routes) {
        const routeOn = route.state === "on";
        const routeButton = create("button", `route${routeOn ? " on" : ""}`, routeDisplayName(route, entityId));
        routeButton.type = "button";
        routeButton.setAttribute("aria-pressed", String(routeOn));
        routeButton.disabled = route.state === "unavailable";
        routeButton.addEventListener("click", () => this._hass.callService("homeassistant", routeOn ? "turn_off" : "turn_on", { entity_id: entityId }));
        routeList.append(routeButton);
      }
      if (!routes.length) routeList.append(create("div", "notice", "No routed zones reported."));
      card.append(routeList);
      inputGrid.append(card);
    }
    if (!inputIds.size) inputGrid.append(create("div", "notice", "Input configuration entities will appear when the Juke integration is loaded."));
    inputSection.append(inputGrid);
    inputSection.append(create("p", "prototype-note", "Juke remains authoritative for zone state, source availability, and routing. General inputs are configuration controls, not playback targets."));
    root.append(inputSection);
    this._content.append(root);
  }
}

const registerJukeElements = () => {
  if (!customElements.get(JUKE_ZONE_CARD)) customElements.define(JUKE_ZONE_CARD, JukeZoneCard);
  if (!customElements.get(HA_PANEL)) customElements.define(HA_PANEL, JukeAudioPanel);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === JUKE_ZONE_CARD)) {
    window.customCards.push({ type: JUKE_ZONE_CARD, name: "Juke Zone Card", description: "Juke-aware zone input control" });
  }
};

const registerJukeElementsWhenReady = () => {
  // HA's scoped custom-element registry must own the definitions first.
  if (customElements.get("home-assistant")) {
    registerJukeElements();
    return;
  }
  window.setTimeout(registerJukeElementsWhenReady, 0);
};

registerJukeElementsWhenReady();
