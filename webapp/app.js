// The web app: the bot's chat (typed or held-to-talk, replies spoken) and the next days.
// Talks to handlers/webapp.py; inside Telegram it logs in with initData, in a browser with the Login Widget.
"use strict";

const tg = window.Telegram && window.Telegram.WebApp;
const $ = (id) => document.getElementById(id);

let token = null;
let soundOn = true;
const player = new Audio();
let recorder = null;
let chunks = [];

// --- storage (may be unavailable: private windows, blocked site data) ---------

function load(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

function save(key, value) {
  try {
    if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
  } catch (e) { /* only a convenience */ }
}

// --- the API ------------------------------------------------------------------

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
  }
  const response = await fetch(path, { method: options.method || "GET", headers, body: options.body });
  if (response.status === 401 && path !== "/api/login") {
    token = null;
    save("token", null);
    await logIn();
    throw new Error("logged out");
  }
  return response;
}

async function logIn() {
  if (tg && tg.initData) {
    const response = await api("/api/login", { method: "POST", json: { init_data: tg.initData } });
    if (response.ok) return started((await response.json()).token);
  }
  // A browser: the Telegram Login Widget
  $("login").hidden = false;
  $("chat").hidden = $("upcoming").hidden = $("composer").hidden = true;
  const config = await (await fetch("/api/config")).json();
  if (!config.bot) return;
  const script = document.createElement("script");
  script.async = true;
  script.src = "https://telegram.org/js/telegram-widget.js?22";
  script.dataset.telegramLogin = config.bot;
  script.dataset.size = "large";
  script.dataset.onauth = "onTelegramAuth(user)";
  script.dataset.requestAccess = "write";
  $("widget").replaceChildren(script);
}

window.onTelegramAuth = async (user) => {
  const response = await api("/api/login", { method: "POST", json: { login: user } });
  if (!response.ok) {
    $("login-error").textContent = "That login didn't work. Try again.";
    $("login-error").hidden = false;
    return;
  }
  started((await response.json()).token);
};

function started(newToken) {
  token = newToken;
  save("token", token);
  $("login").hidden = true;
  showTab(load("tab") || "chat");
  if (!$("messages").children.length) {
    addMessage({ id: 0, text: "Hi! Tell me what to remind you about, e.g. “remind me tomorrow at 9 to call mom”, " +
      "or hold 🎙 and say it.", buttons: [] });
  }
}

// --- the chat -------------------------------------------------------------------

function addMessage(message, mine = false) {
  const item = document.createElement("li");
  item.className = "message" + (mine ? " mine" : "");
  item.dataset.id = message.id;
  fill(item, message);
  $("messages").append(item);
  item.scrollIntoView({ block: "end" });
  return item;
}

function fill(item, message) {
  if (message.text !== undefined) {
    item.replaceChildren(document.createTextNode(message.text));
    item.dataset.text = message.text;
  } else {
    item.querySelector(".buttons")?.remove();
  }
  if (!message.buttons || !message.buttons.length) return;
  const rows = document.createElement("div");
  rows.className = "buttons";
  for (const row of message.buttons) {
    const line = document.createElement("div");
    line.className = "row";
    for (const button of row) {
      if (button.url) {
        const link = document.createElement("a");
        link.href = button.url;
        link.textContent = button.text;
        link.addEventListener("click", (event) => {
          if (tg && tg.openLink) { event.preventDefault(); tg.openLink(button.url); }
        });
        line.append(link);
      } else {
        const tap = document.createElement("button");
        tap.type = "button";
        tap.textContent = button.text;
        tap.addEventListener("click", () => press(item, button.data));
        line.append(tap);
      }
    }
    rows.append(line);
  }
  item.append(rows);
}

function show(result) {
  for (const edit of result.edits || []) {
    const item = document.querySelector(`.message[data-id="${edit.id}"]`);
    if (item) fill(item, edit);
  }
  const fresh = (result.messages || []).map((message) => { addMessage(message); return message; });
  if (result.alert) {
    if (tg && tg.showAlert) tg.showAlert(result.alert);
    else {
      const note = document.createElement("li");
      note.className = "alert";
      note.textContent = result.alert;
      $("messages").append(note);
      note.scrollIntoView({ block: "end" });
    }
  }
  // Said out loud: the bot's replies, not the echo of what was heard
  const spoken = fresh.map((m) => m.text).filter((t) => t && !t.startsWith("🎙 “")).join("\n");
  if (spoken) say(spoken);
}

async function thinking(work) {
  const note = addMessage({ id: "pending", text: "…", buttons: [] });
  note.classList.add("thinking");
  try {
    const response = await work();
    note.remove();
    if (response.ok) show(await response.json());
    else show({ messages: [{ id: "error", text: "Sorry, that didn't work. Try again in a moment.", buttons: [] }] });
  } catch (error) {
    note.remove();
    if (error.message !== "logged out") {
      show({ messages: [{ id: "error", text: "I can't reach the bot right now. Check your connection.", buttons: [] }] });
    }
  }
}

$("send").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("text").value.trim();
  if (!text) return;
  $("text").value = "";
  addMessage({ id: "mine", text, buttons: [] }, true);
  thinking(() => api("/api/message", { method: "POST", json: { text } }));
});

function press(item, data) {
  if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
  const id = Number(item.dataset.id);
  thinking(() => api("/api/button", { method: "POST", json: { data, message_id: id, text: item.dataset.text } }));
}

// --- hold to talk ---------------------------------------------------------------

async function startRecording(event) {
  event.preventDefault();
  unlockAudio();
  if (recorder) return;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    show({ messages: [{ id: "mic", text: "🎙 I can't use the microphone. Allow it, or type instead.", buttons: [] }] });
    return;
  }
  chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.addEventListener("dataavailable", (e) => { if (e.data.size) chunks.push(e.data); });
  recorder.addEventListener("stop", () => {
    stream.getTracks().forEach((track) => track.stop());
    const audio = new Blob(chunks, { type: recorder.mimeType });
    recorder = null;
    $("mic").classList.remove("recording");
    if (audio.size < 1000) return; // a tap, not speech
    thinking(() => api("/api/voice", { method: "POST", body: audio, headers: { "Content-Type": audio.type } }));
  });
  recorder.start();
  $("mic").classList.add("recording");
  if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
}

function stopRecording(event) {
  event.preventDefault();
  if (recorder && recorder.state === "recording") recorder.stop();
}

$("mic").addEventListener("pointerdown", startRecording);
$("mic").addEventListener("pointerup", stopRecording);
$("mic").addEventListener("pointercancel", stopRecording);
$("mic").addEventListener("pointerleave", stopRecording);
$("mic").addEventListener("contextmenu", (event) => event.preventDefault());

// --- spoken replies ---------------------------------------------------------------

// Phones only play sound started by a tap: play (silence) once on the first one, then replies can play later
let unlocked = false;
function unlockAudio() {
  if (unlocked) return;
  unlocked = true;
  player.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
  player.play().catch(() => {});
}
document.addEventListener("pointerdown", unlockAudio, { once: true });

async function say(text) {
  if (!soundOn) return;
  try {
    const response = await api("/api/speak", { method: "POST", json: { text } });
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    player.pause();
    player.src = url;
    player.onended = () => URL.revokeObjectURL(url);
    await player.play();
  } catch (error) { /* the text is there anyway */ }
}

function setSound(on) {
  soundOn = on;
  $("sound").textContent = on ? "🔊" : "🔇";
  $("sound").setAttribute("aria-pressed", String(on));
  save("sound", on ? "on" : "off");
  if (!on) player.pause();
}

$("sound").addEventListener("click", () => setSound(!soundOn));

// --- tabs: chat, upcoming ---------------------------------------------------------

function showTab(name) {
  for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.tab === name);
  $("chat").hidden = name !== "chat";
  $("composer").hidden = name !== "chat";
  $("upcoming").hidden = name !== "upcoming";
  save("tab", name);
  if (name === "upcoming") loadUpcoming();
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => { if (token) showTab(tab.dataset.tab); });
}

async function loadUpcoming() {
  let days;
  try {
    const response = await api("/api/upcoming");
    if (!response.ok) return;
    days = (await response.json()).days;
  } catch (error) { return; }
  const blocks = days.map((day) => {
    const block = document.createElement("section");
    block.className = "day";
    const title = document.createElement("h2");
    title.textContent = day.label;
    const list = document.createElement("ul");
    if (!day.items.length) {
      const none = document.createElement("li");
      none.className = "empty";
      none.textContent = "Nothing";
      list.append(none);
    }
    for (const item of day.items) {
      const line = document.createElement("li");
      const when = document.createElement("span");
      when.className = "time";
      when.textContent = item.time || "all day";
      const what = document.createElement("span");
      what.textContent = `${item.kind === "event" ? "📅" : "⏰"} ${item.text}`;
      line.append(when, what);
      list.append(line);
    }
    block.append(title, list);
    return block;
  });
  $("days").replaceChildren(...blocks);
}

// --- start ------------------------------------------------------------------------

if (tg) {
  tg.ready();
  tg.expand();
}
setSound(load("sound") !== "off");
token = load("token");
if (token && !(tg && tg.initData)) started(token); else logIn();
