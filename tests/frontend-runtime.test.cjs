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

  dispatch(name) {
    this.listeners[name]?.({ target: this });
  }
}

function loadFrontend() {
  const registry = new Map();
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
  const context = {
    document,
    customElements: {
      get: (name) => registry.get(name),
      define: (name, Constructor) => registry.set(name, Constructor),
    },
    HTMLElement: FakeElement,
    window: { customCards: [] },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "custom_components", "jukeaudio_ha_air", "frontend", "juke-audio.js"),
    "utf8",
  );
  vm.runInNewContext(source, context, { filename: "juke-audio.js" });
  return { context, registry };
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
