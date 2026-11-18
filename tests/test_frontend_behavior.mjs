import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const appJsPath = path.resolve("app/static/app.js");
const appJsCode = fs.readFileSync(appJsPath, "utf-8");

function makeElement(id = "") {
  const listeners = new Map();
  const children = [];
  const attrs = new Map();
  const classes = new Set();
  const el = {
    id,
    value: "",
    textContent: "",
    hidden: false,
    disabled: false,
    href: "",
    download: "",
    src: "",
    innerHTML: "",
    style: {},
    children,
    options: [],
    classList: {
      toggle(cls, force) {
        if (force === undefined) {
          if (classes.has(cls)) classes.delete(cls);
          else classes.add(cls);
        } else if (force) {
          classes.add(cls);
        } else {
          classes.delete(cls);
        }
      },
      contains(cls) {
        return classes.has(cls);
      },
    },
    setAttribute(k, v) {
      attrs.set(k, String(v));
    },
    getAttribute(k) {
      return attrs.get(k) ?? null;
    },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    dispatchEvent(evt) {
      const eventObj = {
        preventDefault() {
          eventObj.defaultPrevented = true;
        },
        defaultPrevented: false,
        ...evt,
      };
      for (const fn of listeners.get(evt.type) || []) {
        fn(eventObj);
      }
      return eventObj;
    },
    appendChild(child) {
      children.push(child);
      if (child.tagName === "OPTION") {
        el.options.push(child);
        if (el.options.length === 1) el.value = child.value;
      }
      return child;
    },
    prepend(child) {
      children.unshift(child);
    },
    replaceWith(replacement) {
      el.replacedBy = replacement;
    },
    focus() {
      el.focused = true;
    },
    click() {
      el.clicked = true;
      return el.dispatchEvent({ type: "click" });
    },
    remove() {
      el.removed = true;
    },
  };
  return el;
}

function createHarness(fetchImpl) {
  const ids = [
    "inspect-form",
    "url-input",
    "clear-url-btn",
    "fetch-btn",
    "error-banner",
    "error-text",
    "error-close",
    "preview-card",
    "thumb-img",
    "thumb-fallback",
    "media-title",
    "media-meta",
    "playlist-note",
    "format-mp3",
    "format-mp4",
    "quality-label",
    "quality-select",
    "hd-codec-hint",
    "status-text",
    "percent-text",
    "progress-bar",
    "progress-track",
    "download-btn",
    "cancel-btn",
    "download-another-btn",
    "history-count",
    "history-empty",
    "history-list",
  ];
  const elements = new Map(ids.map((id) => [id, makeElement(id)]));
  elements.get("preview-card").hidden = true;
  elements.get("error-banner").hidden = true;
  elements.get("download-another-btn").hidden = true;
  elements.get("cancel-btn").hidden = true;

  const eventSources = [];
  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.closed = false;
      eventSources.push(this);
    }
    close() {
      this.closed = true;
    }
  }

  const document = {
    body: makeElement("body"),
    getElementById(id) {
      return elements.get(id) || null;
    },
    createElement(tag) {
      const el = makeElement();
      el.tagName = tag.toUpperCase();
      return el;
    },
  };

  const context = {
    document,
    fetch: fetchImpl,
    EventSource: FakeEventSource,
    AbortController,
    encodeURIComponent,
    Date,
    console,
  };
  vm.runInNewContext(appJsCode, context);
  return { elements, eventSources };
}

// Test 1: Stale in-flight /api/inspect aborted/ignored on resetForAnother()
{
  let resolveSlowInspect;
  const fetchMock = (url, opts) => {
    if (url === "/api/inspect") {
      return new Promise((resolve) => {
        resolveSlowInspect = () =>
          resolve({
            ok: true,
            async json() {
              return {
                url: "https://example.com/slow",
                title: "Stale Slow Video",
                duration: 60,
                thumbnail: null,
                extractor: "youtube",
                is_playlist_url: false,
                mp3_bitrates: [320],
                mp4_heights: [1080],
              };
            },
          });
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  };

  const { elements } = createHarness(fetchMock);
  const urlInput = elements.get("url-input");
  const previewCard = elements.get("preview-card");

  urlInput.value = "https://example.com/slow";
  elements.get("inspect-form").dispatchEvent({ type: "submit" });
  elements.get("download-another-btn").click();
  resolveSlowInspect();

  await new Promise((r) => setTimeout(r, 20));
  assert.equal(previewCard.hidden, true, "Stale inspect must not reopen previewCard after reset");
  assert.equal(urlInput.value, "");
}

// Test 2: Clicking Save again after cache expiry checks HEAD 410, marks Expired, and stays in SPA
{
  const fetchMock = async (url, opts = {}) => {
    if (url === "/api/inspect") {
      return {
        ok: true,
        async json() {
          return {
            url: "https://example.com/track",
            title: "Track 1",
            duration: 90,
            thumbnail: null,
            extractor: "youtube",
            is_playlist_url: false,
            mp3_bitrates: [320],
            mp4_heights: [720],
          };
        },
      };
    }
    if (url === "/api/download") {
      return {
        ok: true,
        async json() {
          return { job_id: "job-expired-1" };
        },
      };
    }
    if (url === "/api/jobs/job-expired-1/file" && opts.method === "HEAD") {
      return {
        ok: false,
        status: 410,
      };
    }
    throw new Error(`Unexpected fetch: ${opts.method || "GET"} ${url}`);
  };

  const { elements, eventSources } = createHarness(fetchMock);
  elements.get("url-input").value = "https://example.com/track";
  elements.get("inspect-form").dispatchEvent({ type: "submit" });
  await new Promise((r) => setTimeout(r, 20));

  elements.get("download-btn").click();
  await new Promise((r) => setTimeout(r, 20));

  assert.equal(eventSources.length, 1);
  eventSources[0].onmessage({
    data: JSON.stringify({
      job_id: "job-expired-1",
      status: "ready",
      progress: 100,
      filename: "Track 1.mp3",
      size_bytes: 1234,
    }),
  });

  const historyItem = elements.get("history-list").children[0];
  const saveLink = historyItem.children[1];
  const clickEvt = saveLink.click();
  await new Promise((r) => setTimeout(r, 20));

  assert.equal(clickEvt.defaultPrevented, true, "Save again must intercept navigation");
  assert.ok(saveLink.replacedBy, "Expired link should be replaced by Expired badge");
  assert.equal(saveLink.replacedBy.textContent, "Expired");
  assert.equal(elements.get("error-banner").hidden, false);
}

console.log("frontend behavior checks passed");
