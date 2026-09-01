const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class FakeNode {
  constructor(text = "") {
    this._text = text;
    this.children = [];
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this._text = String(value ?? "");
    this.children = [];
  }

  append(...nodes) {
    this._text = "";
    this.children.push(...nodes);
  }

  replaceChildren(...nodes) {
    this._text = "";
    this.children = [...nodes];
  }

  get childElementCount() {
    return this.children.length;
  }
}

class FakeElement extends FakeNode {
  constructor(tagName) {
    super();
    this.tagName = tagName;
    this._className = "";
    this.attributes = {};
    this.listeners = {};
    this.disabled = false;
    this.shadowRoot = null;
  }

  get className() {
    return this._className;
  }

  set className(value) {
    this._className = String(value ?? "");
  }

  get classList() {
    return {
      toggle: (name, force) => {
        const names = new Set(this._className.split(/\s+/).filter(Boolean));
        if (force) names.add(name);
        else names.delete(name);
        this._className = [...names].join(" ");
      },
      contains: (name) => this._className.split(/\s+/).includes(name),
    };
  }

  attachShadow() {
    this.shadowRoot = new FakeElement("#shadow-root");
    return this.shadowRoot;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  addEventListener(name, callback) {
    this.listeners[name] = callback;
  }

  dispatch(name, event = {}) {
    this.listeners[name]?.({ ...event, target: this });
  }
}

function loadFrontend({ homeAssistantReady = true } = {}) {
  const registry = new Map();
  const pendingTimers = [];
  const document = {
    head: new FakeElement("head"),
    createElement(tagName) {
      const Constructor = registry.get(tagName);
      return Constructor ? new Constructor() : new FakeElement(tagName);
    },
    createTextNode(text) {
      return new FakeNode(String(text));
    },
  };
  if (homeAssistantReady) registry.set("home-assistant", FakeElement);
  const context = {
    document,
    customElements: {
      get: (name) => registry.get(name),
      define: (name, Constructor) => registry.set(name, Constructor),
    },
    HTMLElement: FakeElement,
    window: {
      customCards: [],
      setTimeout(callback) {
        pendingTimers.push(callback);
        return pendingTimers.length;
      },
    },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "custom_components", "jukeaudio_ha_air", "frontend", "juke-audio.js"),
    "utf8",
  );
  vm.runInNewContext(source, context, { filename: "juke-audio.js" });
  return {
    context,
    registry,
    makeHomeAssistantReady() {
      registry.set("home-assistant", FakeElement);
      while (pendingTimers.length) pendingTimers.shift()();
    },
    flushTimers() {
      while (pendingTimers.length) pendingTimers.shift()();
    },
  };
}

function descendants(root) {
  const result = [];
  const visit = (node) => {
    for (const child of node.children || []) {
      result.push(child);
      visit(child);
      if (child.shadowRoot) visit(child.shadowRoot);
    }
  };
  visit(root);
  if (root.shadowRoot) visit(root.shadowRoot);
  return result;
}

function byClass(root, className) {
  return descendants(root).filter((node) => node.classList?.contains(className));
}

test("custom elements register after Home Assistant creates its scoped registry", () => {
  const { context, registry, makeHomeAssistantReady } = loadFrontend({ homeAssistantReady: false });

  assert.equal(registry.get("juke-zone-card"), undefined);
  assert.deepEqual(context.window.customCards, []);

  makeHomeAssistantReady();

  assert.equal(typeof registry.get("juke-zone-card"), "function");
  assert.equal(typeof registry.get("juke-audio-card"), "function");
  assert.equal(typeof registry.get("ha-panel-juke-audio-panel"), "function");
  assert.deepEqual(JSON.parse(JSON.stringify(context.window.customCards)), [{
    type: "juke-zone-card",
    name: "Juke Zone Card",
    description: "Juke-aware zone input control",
  }, {
    type: "juke-audio-card",
    name: "Juke Audio Dashboard",
    description: "Zones-first Juke controls and input routing",
  }]);
});

test("zone source states use backend selectability and animate only current streaming source", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  const calls = [];
  card.setConfig({ entity: "media_player.greatroom", name: "Long generated zone label" });
  card.hass = {
    states: {
      "media_player.greatroom": {
        state: "playing",
        attributes: {
          juke_zone_name: "Greatroom",
          source: "Juke-DLNA2",
          juke_input_options: [
            { source: "Juke-DLNA2", enabled: true, streaming: true, selectable: true },
            { source: "AirPlay 2", enabled: true, streaming: true, selectable: true },
            { source: "Spotify", enabled: true, streaming: false, selectable: false },
            { source: "Primary", enabled: false, streaming: true, selectable: false },
          ],
        },
      },
    },
    callService: (...args) => calls.push(args),
  };

  assert.equal(byClass(card, "zone-name")[0].textContent, "Greatroom");
  assert.equal(byClass(card, "source-label")[0].textContent, "DLNA 2");
  assert.equal(byClass(card, "source-current").length, 1);
  assert.equal(byClass(card, "source-available").length, 1);
  assert.equal(byClass(card, "source-waiting").length, 1);
  assert.equal(byClass(card, "source-disabled").length, 1);
  assert.equal(byClass(card, "source-live").length, 1);
  assert.equal(byClass(card, "activity").length, 1);
  assert.equal(byClass(card, "source-live")[0].classList.contains("source-current"), true);

  const available = byClass(card, "source-available")[0];
  assert.equal(available.disabled, false);
  available.dispatch("click");
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["media_player", "select_source", {
    entity_id: "media_player.greatroom",
    source: "AirPlay 2",
  }]]);

  const waiting = byClass(card, "source-waiting")[0];
  assert.equal(waiting.disabled, true);
});

test("zone tiles own selected, streaming, waiting, and disabled visual states", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = {
    states: {
      "media_player.greatroom": {
        state: "playing",
        attributes: {
          juke_zone_name: "Greatroom",
          source: "Juke-DLNA2",
          juke_input_options: [
            { source: "Juke-DLNA2", enabled: true, streaming: true, selectable: true },
            { source: "AirPlay 2", enabled: true, streaming: true, selectable: false },
            { source: "Spotify", enabled: true, streaming: false, selectable: true },
            { source: "Primary", enabled: false, streaming: true, selectable: false },
          ],
        },
      },
    },
    callService: () => {},
  };

  assert.equal(byClass(card, "now").length, 0);
  assert.equal(byClass(card, "source-selected").length, 1);
  const selected = byClass(card, "source-selected")[0];
  const streaming = byClass(card, "source-streaming")[0];
  const waiting = byClass(card, "source-waiting")[0];
  const disabled = byClass(card, "source-disabled")[0];
  assert.equal(byClass(selected, "source-dot-green").length, 1);
  assert.equal(byClass(card, "source-streaming").length, 1);
  assert.equal(streaming.classList.contains("source-selected"), false);
  assert.equal(byClass(streaming, "source-dot-green").length, 1);
  assert.equal(byClass(waiting, "source-dot-yellow").length, 1);
  assert.equal(waiting.disabled, true);
  assert.equal(byClass(disabled, "source-dot-grey").length, 1);
  assert.doesNotMatch(byClass(card, "zone-card-content")[0].textContent, /Zone enabled/);
  assert.match(card.shadowRoot.children[0].textContent, /\.source-option\.source-waiting\s*\{[^}]*border-color:\s*transparent;/s);
});

test("a globally reported source is not rendered as selected outside its zone tiles", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = {
    states: {
      "media_player.greatroom": {
        state: "on",
        attributes: {
          source: "Other zone source",
          juke_input_options: [{ source: "Greatroom source", enabled: true, streaming: true, selectable: true }],
        },
      },
    },
    callService: () => {},
  };

  assert.equal(byClass(card, "source-selected").length, 0);
  assert.equal(byClass(card, "source-streaming").length, 1);
});

test("a disabled active source keeps the disabled visual state instead of selected", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = {
    states: {
      "media_player.greatroom": {
        state: "playing",
        attributes: {
          source: "Disabled source",
          juke_input_options: [{
            source: "Disabled source",
            enabled: false,
            streaming: true,
            selectable: false,
          }],
        },
      },
    },
    callService: () => {},
  };

  const disabled = byClass(card, "source-disabled")[0];
  assert.equal(byClass(card, "source-current").length, 0);
  assert.equal(byClass(card, "selected").length, 0);
  assert.equal(byClass(card, "source-live").length, 0);
  assert.equal(disabled.attributes["aria-pressed"], "false");
  assert.equal(byClass(disabled, "source-dot-grey").length, 1);
});

test("zone cards expose a volume slider that calls Home Assistant volume_set", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  const calls = [];
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = {
    states: {
      "media_player.greatroom": {
        state: "on",
        attributes: {
          juke_zone_name: "Greatroom",
          volume_level: 0.42,
          juke_input_options: [],
        },
      },
    },
    callService: (...args) => calls.push(args),
  };

  const slider = byClass(card, "volume-slider")[0];
  assert.equal(slider.value, 42);
  slider.value = 63;
  slider.dispatch("change");

  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["media_player", "volume_set", {
    entity_id: "media_player.greatroom",
    volume_level: 0.63,
  }]]);
});

test("zone power shows inline pending state and clears on authoritative HA state", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  const calls = [];
  const hass = {
    states: {
      "media_player.greatroom": {
        state: "off",
        attributes: { juke_zone_name: "Greatroom", juke_input_options: [] },
      },
    },
    callService: (...args) => calls.push(args),
  };
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = hass;

  const power = byClass(card, "power")[0];
  power.dispatch("click");

  assert.equal(power.disabled, true);
  assert.equal(byClass(card, "pending-status")[0].textContent, "Updating…");
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["media_player", "turn_on", {
    entity_id: "media_player.greatroom",
  }]]);

  hass.states["media_player.greatroom"].state = "on";
  card.hass = hass;
  assert.equal(byClass(card, "pending-status").length, 0);
  assert.equal(byClass(card, "power")[0].disabled, false);
});

test("volume change shows inline pending state and reconciles only on HA volume", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  const calls = [];
  const hass = {
    states: {
      "media_player.greatroom": {
        state: "on",
        attributes: {
          juke_zone_name: "Greatroom",
          volume_level: 0.42,
          juke_input_options: [{ source: "AirPlay", enabled: true, streaming: true, selectable: true }],
        },
      },
    },
    callService: (...args) => calls.push(args),
  };
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = hass;

  const slider = byClass(card, "volume-slider")[0];
  slider.value = "63";
  slider.dispatch("change");

  assert.equal(slider.disabled, true);
  assert.equal(byClass(card, "pending-status").length, 1);
  assert.equal(byClass(card, "power")[0].disabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["media_player", "volume_set", {
    entity_id: "media_player.greatroom",
    volume_level: 0.63,
  }]]);

  hass.states["media_player.greatroom"].attributes.volume_level = 0.63;
  card.hass = hass;
  assert.equal(byClass(card, "pending-status").length, 0);
  assert.equal(byClass(card, "volume-slider")[0].disabled, false);
});

test("source selection shows pending only on the initiating source tile", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  const calls = [];
  const hass = {
    states: {
      "media_player.greatroom": {
        state: "playing",
        attributes: {
          juke_zone_name: "Greatroom",
          source: "DLNA",
          juke_input_options: [
            { source: "DLNA", enabled: true, streaming: true, selectable: true },
            { source: "AirPlay", enabled: true, streaming: true, selectable: true },
            { source: "Spotify", enabled: true, streaming: true, selectable: true },
          ],
        },
      },
    },
    callService: (...args) => calls.push(args),
  };
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = hass;

  const tiles = byClass(card, "source-streaming");
  const target = tiles.find((tile) => tile.textContent.includes("AirPlay"));
  const other = tiles.find((tile) => tile.textContent.includes("Spotify"));
  target.dispatch("click");

  assert.equal(target.disabled, true);
  assert.equal(other.disabled, false);
  assert.equal(byClass(target, "pending-status")[0].textContent, "Updating…");
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["media_player", "select_source", {
    entity_id: "media_player.greatroom",
    source: "AirPlay",
  }]]);

  hass.states["media_player.greatroom"].attributes.source = "AirPlay";
  card.hass = hass;
  assert.equal(byClass(card, "pending-status").length, 0);
  assert.equal(byClass(card, "source-selected")[0].disabled, false);
});

test("input routing cards stack into one column on touch/mobile screens", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "custom_components", "jukeaudio_ha_air", "frontend", "juke-audio.js"),
    "utf8",
  );
  assert.match(source, /@media \(pointer: coarse\)[\s\S]*?\.zone-grid, \.input-grid\s*\{\s*grid-template-columns:\s*1fr;/);
});

test("the unified Lovelace card keeps zones and inputs two-wide on desktop", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "custom_components", "jukeaudio_ha_air", "frontend", "juke-audio.js"),
    "utf8",
  );
  assert.match(source, /\.zone-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,/s);
  assert.match(source, /\.input-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,/s);
  assert.match(source, /@media \(max-width: 680px\)[\s\S]*?\.zone-grid, \.input-grid\s*\{\s*grid-template-columns:\s*1fr;/);
});

test("input configuration is vertically stacked with one right-aligned availability switch", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "custom_components", "jukeaudio_ha_air", "frontend", "juke-audio.js"),
    "utf8",
  );
  assert.match(source, /\.config\s*\{\s*display:\s*grid;\s*grid-template-columns:\s*1fr;/);
  assert.match(source, /\.config \.control-with-status\s*\{\s*display:\s*block;/);
  assert.match(source, /\.input-top\s*\{[^}]*justify-content:\s*space-between;/s);
  assert.doesNotMatch(source, /state-badge/);
  assert.doesNotMatch(source, /Availability/);
  assert.doesNotMatch(source, /switchLine\.append\(create\("span", null, enabledState \? "Available" : "Disabled"\)\);/);
});

test("panel labels use explicit Juke metadata without a generated friendly name", () => {
  const { registry } = loadFrontend();
  const panel = new (registry.get("ha-panel-juke-audio-panel"))();
  panel.hass = {
    states: {
      "media_player.primary_bed": {
        state: "on",
        attributes: {
          juke_zone_id: "zone-2",
          juke_zone_name: "Primary Bed",
          source: null,
          juke_input_options: [],
        },
      },
      "switch.input_enabled": {
        state: "on",
        attributes: {
          juke_entity_role: "input_enabled",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
        },
      },
      "select.input_type": {
        state: "DLNA",
        attributes: {
          juke_entity_role: "input_type",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          options: ["DLNA"],
        },
      },
      "switch.route": {
        state: "on",
        attributes: {
          juke_entity_role: "input_route",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          juke_zone_id: "zone-2",
          juke_zone_name: "Primary Bed",
        },
      },
    },
    callService: () => {},
  };

  assert.equal(byClass(panel, "zone-name")[0].textContent, "Primary Bed");
  assert.equal(byClass(panel, "input-name")[0].textContent, "DLNA 2");
  assert.equal(byClass(panel, "route")[0].textContent, "Primary Bed");
});

test("input type selection survives pointer handling and dispatches the chosen option", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-audio-card"))();
  const calls = [];
  card.setConfig({ type: "custom:juke-audio-card" });
  card.hass = {
    states: {
      "select.input_type": {
        state: "DLNA",
        attributes: {
          juke_entity_role: "input_type",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          options: ["DLNA", "Spotify"],
        },
      },
    },
    callService: (...args) => calls.push(args),
  };

  const selector = descendants(card).find((node) => node.tagName === "select");
  const stopped = [];
  selector.dispatch("pointerdown", { stopPropagation: () => stopped.push("pointerdown") });
  selector.dispatch("mousedown", { stopPropagation: () => stopped.push("mousedown") });
  selector.value = "Spotify";
  selector.dispatch("change", { stopPropagation: () => stopped.push("change") });

  assert.deepEqual(stopped, ["pointerdown", "mousedown", "change"]);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["select", "select_option", {
    entity_id: "select.input_type",
    option: "Spotify",
  }]]);
});

test("input enable shows inline pending only on its switch and reconciles on HA state", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-audio-card"))();
  const calls = [];
  const hass = {
    states: {
      "switch.input_enabled": {
        state: "off",
        attributes: {
          juke_entity_role: "input_enabled",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
        },
      },
      "select.input_type": {
        state: "DLNA",
        attributes: {
          juke_entity_role: "input_type",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          options: ["DLNA"],
        },
      },
      "switch.route": {
        state: "off",
        attributes: {
          juke_entity_role: "input_route",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          juke_zone_name: "Greatroom",
        },
      },
    },
    callService: (...args) => calls.push(args),
  };
  card.setConfig({ type: "custom:juke-audio-card" });
  card.hass = hass;

  const toggle = byClass(card, "tiny-switch")[0];
  toggle.dispatch("click");

  assert.equal(toggle.disabled, true);
  assert.equal(byClass(card, "pending-status").length, 1);
  assert.equal(byClass(card, "route")[0].disabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["homeassistant", "turn_on", {
    entity_id: "switch.input_enabled",
  }]]);

  hass.states["switch.input_enabled"].state = "on";
  card.hass = hass;
  assert.equal(byClass(card, "pending-status").length, 0);
  assert.equal(byClass(card, "tiny-switch")[0].disabled, false);
});

test("input type change shows pending on only its selector until HA reports the option", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-audio-card"))();
  const calls = [];
  const hass = {
    states: {
      "switch.input_enabled": {
        state: "on",
        attributes: {
          juke_entity_role: "input_enabled",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
        },
      },
      "select.input_type": {
        state: "DLNA",
        attributes: {
          juke_entity_role: "input_type",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          options: ["DLNA", "Spotify"],
        },
      },
      "switch.route": {
        state: "off",
        attributes: {
          juke_entity_role: "input_route",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          juke_zone_name: "Greatroom",
        },
      },
    },
    callService: (...args) => calls.push(args),
  };
  card.setConfig({ type: "custom:juke-audio-card" });
  card.hass = hass;

  const selector = descendants(card).find((node) => node.tagName === "select");
  selector.value = "Spotify";
  selector.dispatch("change", { stopPropagation: () => {} });

  assert.equal(selector.disabled, true);
  assert.equal(byClass(card, "pending-status").length, 1);
  assert.equal(byClass(card, "tiny-switch")[0].disabled, false);
  assert.equal(byClass(card, "route")[0].disabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["select", "select_option", {
    entity_id: "select.input_type",
    option: "Spotify",
  }]]);

  hass.states["select.input_type"].state = "Spotify";
  card.hass = hass;
  assert.equal(byClass(card, "pending-status").length, 0);
  assert.equal(descendants(card).find((node) => node.tagName === "select").disabled, false);
});

test("route toggle shows inline pending only on its route control until HA state", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-audio-card"))();
  const calls = [];
  const hass = {
    states: {
      "switch.input_enabled": {
        state: "on",
        attributes: {
          juke_entity_role: "input_enabled",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
        },
      },
      "select.input_type": {
        state: "DLNA",
        attributes: {
          juke_entity_role: "input_type",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          options: ["DLNA"],
        },
      },
      "switch.route": {
        state: "off",
        attributes: {
          juke_entity_role: "input_route",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          juke_zone_name: "Greatroom",
        },
      },
    },
    callService: (...args) => calls.push(args),
  };
  card.setConfig({ type: "custom:juke-audio-card" });
  card.hass = hass;

  const route = byClass(card, "route")[0];
  route.dispatch("click");

  assert.equal(route.disabled, true);
  assert.equal(byClass(card, "pending-status").length, 1);
  assert.equal(byClass(card, "tiny-switch")[0].disabled, false);
  assert.equal(descendants(card).find((node) => node.tagName === "select").disabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["homeassistant", "turn_on", {
    entity_id: "switch.route",
  }]]);

  hass.states["switch.route"].state = "on";
  card.hass = hass;
  assert.equal(byClass(card, "pending-status").length, 0);
  assert.equal(byClass(card, "route")[0].disabled, false);
});

test("unified card preserves a zone control's pending state across HA rerenders", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-audio-card"))();
  const hass = {
    states: {
      "media_player.greatroom": {
        state: "off",
        attributes: { juke_zone_name: "Greatroom", juke_input_options: [] },
      },
    },
    callService: () => {},
  };
  card.setConfig({ type: "custom:juke-audio-card" });
  card.hass = hass;

  byClass(card, "power")[0].dispatch("click");
  assert.equal(byClass(card, "pending-status").length, 1);

  hass.states.sensor = { state: "ok", attributes: {} };
  card.hass = hass;
  assert.equal(byClass(card, "pending-status").length, 1);
  assert.equal(byClass(card, "power")[0].disabled, true);
});

test("zone power pending does not clear on an incomplete HA update", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  const hass = {
    states: {
      "media_player.greatroom": {
        state: "off",
        attributes: { juke_zone_name: "Greatroom", juke_input_options: [] },
      },
    },
    callService: () => {},
  };
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = hass;
  byClass(card, "power")[0].dispatch("click");

  delete hass.states["media_player.greatroom"];
  card.hass = hass;
  assert.equal(byClass(card, "pending-status").length, 1);
  assert.equal(byClass(card, "power")[0].disabled, true);
});

test("pending controls fail safe by releasing inline state after the bounded timeout", () => {
  const { registry, flushTimers } = loadFrontend();
  const card = new (registry.get("juke-zone-card"))();
  const hass = {
    states: {
      "media_player.greatroom": {
        state: "off",
        attributes: { juke_zone_name: "Greatroom", juke_input_options: [] },
      },
    },
    callService: () => {},
  };
  card.setConfig({ entity: "media_player.greatroom" });
  card.hass = hass;
  byClass(card, "power")[0].dispatch("click");
  assert.equal(byClass(card, "pending-status").length, 1);

  flushTimers();
  assert.equal(byClass(card, "pending-status").length, 0);
  assert.equal(byClass(card, "power")[0].disabled, false);
  assert.equal(byClass(card, "blocking-modal").length, 0);
});

test("the unified Lovelace card renders the same zones-first friendly-label layout", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-audio-card"))();
  card.setConfig({ type: "custom:juke-audio-card" });
  card.hass = {
    states: {
      "media_player.generated_zone_entity": {
        state: "on",
        attributes: {
          juke_zone_id: "zone-2",
          juke_zone_name: "Primary Bed",
          source: null,
          juke_input_options: [],
        },
      },
      "switch.generated_input_enabled": {
        state: "on",
        attributes: {
          juke_entity_role: "input_enabled",
          juke_input_id: "input-dlna",
          juke_input_name: "Juke-DLNA2",
        },
      },
      "select.generated_input_type": {
        state: "DLNA",
        attributes: {
          juke_entity_role: "input_type",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          options: ["DLNA"],
        },
      },
      "switch.generated_route": {
        state: "on",
        attributes: {
          juke_entity_role: "input_route",
          juke_input_id: "input-dlna",
          juke_input_name: "DLNA 2",
          juke_zone_id: "zone-2",
          juke_zone_name: "Primary Bed",
        },
      },
    },
    callService: () => {},
  };

  const zoneGrid = byClass(card, "zone-grid")[0];
  const inputSection = byClass(card, "input-section")[0];
  assert.equal(zoneGrid.children[0].shadowRoot !== null, true);
  assert.equal(byClass(card, "zone-name")[0].textContent, "Primary Bed");
  assert.equal(byClass(card, "input-name")[0].textContent, "DLNA 2");
  assert.equal(byClass(card, "route")[0].textContent, "Primary Bed");
  assert.equal(inputSection.children[0].classList.contains("toolbar"), true);
  const root = card.shadowRoot.children[1].children[0];
  assert.equal(root.children[2], zoneGrid);
  assert.equal(root.children[3], inputSection);
});

test("missing Juke metadata never leaks generated Home Assistant entity labels", () => {
  const { registry } = loadFrontend();
  const card = new (registry.get("juke-audio-card"))();
  card.setConfig({ type: "custom:juke-audio-card" });
  card.hass = {
    states: {
      "media_player.generated_long_zone_entity": {
        state: "on",
        attributes: {
          juke_input_options: [{
            input_id: "input-generated-long-id",
            enabled: true,
            streaming: true,
            selectable: true,
          }],
        },
      },
      "switch.generated_long_input_entity": {
        state: "on",
        attributes: {
          juke_entity_role: "input_enabled",
          juke_input_id: "input-1",
        },
      },
      "switch.generated_long_route_entity": {
        state: "off",
        attributes: {
          juke_entity_role: "input_route",
          juke_input_id: "input-1",
        },
      },
    },
    callService: () => {},
  };

  const rendered = byClass(card, "panel-shell")[0].textContent;
  assert.doesNotMatch(rendered, /generated_long_(zone|input|route)_entity/);
  assert.doesNotMatch(rendered, /input-generated-long-id/);
  assert.equal(byClass(card, "zone-name")[0].textContent, "Unknown zone");
  assert.equal(byClass(card, "input-name")[0].textContent, "Unknown input");
  assert.equal(byClass(card, "route")[0].textContent, "Unknown zone");
  assert.equal(byClass(card, "source-label")[0].textContent, "Unknown source");
});
