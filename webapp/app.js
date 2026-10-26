// The web app as an assistant (#61): a briefing and what it can do, then turns of
// what you said → the steps it took → its replies (as result cards where it can), with follow-ups to tap.
// Talks to handlers/webapp.py; inside Telegram it logs in with initData, in a browser with the Login Widget.
"use strict";

// Telegram's script is there in a browser too; only inside Telegram does it have who's logged in
const tg = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData
  ? window.Telegram.WebApp : null;
const $ = (id) => document.getElementById(id);

let token = null;
let soundOn = true;
const player = new Audio();
let recorder = null;
let chunks = [];
// message id → {element, text, card, buttons}: what edits change in place
const replies = new Map();

// --- icons (constant markup) ----------------------------------------------------

const ICONS = {
  reminders: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M5 4L2.5 6.5M19 4l2.5 2.5"/>',
  events: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c1-3.5 3.5-5.5 6.5-5.5s5.5 2 6.5 5.5M16 5.5a3.5 3.5 0 010 6.5M18 14.8c1.8.7 3 2.5 3.5 5.2"/>',
  calendar: '<path d="M20 12a8 8 0 01-14 5.3M4 12a8 8 0 0114-5.3M18 3v4h-4M6 21v-4h4"/>',
  today: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  week: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4M8 14h2M12 14h2M16 14h.01M8 17h2"/>',
  soundOn: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 010 6M18 6.5a7.5 7.5 0 010 11"/>',
  soundOff: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
  send: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0013 0M12 17.5V21"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  repeat: '<path d="M17 2l3 3-3 3M4 11V9a4 4 0 014-4h12M7 22l-3-3 3-3M20 13v2a4 4 0 01-4 4H4"/>',
};

function icon(name, size = 20) {
  const span = document.createElement("span");
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
  return span.firstChild;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// The bot's buttons start with an emoji ("↩️ Undo"); the page draws its own look
function plain(label) {
  const bare = label.replace(/^(?:\p{Extended_Pictographic}|️|⃣|[0-9#*](?=️?⃣))+\s*/u, "");
  return bare || label;
}

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
  if (tg) {
    const response = await api("/api/login", { method: "POST", json: { init_data: tg.initData } });
    if (response.ok) return started((await response.json()).token);
  }
  // A browser: the Telegram Login Widget
  $("login").hidden = false;
  $("main").hidden = $("composer").hidden = $("week").hidden = true;
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
  $("main").hidden = $("composer").hidden = $("week").hidden = false;
  loadBriefing();
}

// --- home: the briefing and what I can do ---------------------------------------

async function loadBriefing() {
  let brief;
  try {
    const response = await api("/api/briefing");
    if (!response.ok) return;
    brief = await response.json();
  } catch (error) { return; }
  $("greeting").textContent = `${brief.greeting}.`;
  $("today-date").textContent = `${brief.date} · ${brief.time}`;

  const lines = [];
  for (const block of brief.blocks) {
    const line = el("div", "line");
    line.append(icon(block.block, 18), el("span", "", block.text));
    lines.push(line);
    if (block.items && block.items.length) {
      const list = el("ul", "agenda");
      for (const item of block.items) {
        const row = el("li");
        row.append(el("span", item.time ? "time" : "time all-day", item.time || "all day"), el("span", "", item.text));
        list.append(row);
      }
      lines.push(list);
    }
    if (block.after) {
      const after = el("div", "line after");
      after.append(icon("week", 18), el("span", "", block.after));
      lines.push(after);
    }
  }
  $("briefing").replaceChildren(...lines);

  $("skills").replaceChildren(...brief.skills.map((skill) => {
    const tile = el("button", "skill");
    tile.type = "button";
    const name = el("span", "name");
    name.append(icon(skill.skill, 17), el("span", "", skill.title));
    tile.append(name, el("span", "example", `“${skill.example}”`));
    tile.addEventListener("click", () => fillIn(skill.example));
    return tile;
  }));
}

function fillIn(text) {
  $("text").value = text;
  $("text").focus();
}

// --- turns ------------------------------------------------------------------------

function newTurn(said) {
  const turn = el("li", "turn");
  if (said !== undefined) turn.append(el("div", "you", said));
  $("turns").append(turn);
  turn.scrollIntoView({ block: "end", behavior: "smooth" });
  return turn;
}

function showSteps(turn, steps) {
  if (!steps || !steps.length) return;
  const list = el("ol", "steps");
  steps.forEach((step, n) => {
    const item = el("li", "", step);
    item.style.animationDelay = `${n * 120}ms`;
    list.append(item);
  });
  turn.append(list);
}

function addReply(turn, message) {
  const element = el("div", "reply");
  replies.set(message.id, { element, text: message.text, card: message.card || null, buttons: message.buttons || [] });
  draw(message.id);
  turn.append(element);
}

function update(edit) {
  const reply = replies.get(edit.id);
  if (!reply) return;
  if (edit.text !== undefined) {
    reply.text = edit.text;
    // A new text (↩️ Cancelled…) replaces the card, unless it comes with one
    reply.card = edit.card || null;
  } else if (edit.card) {
    reply.card = edit.card;
  }
  reply.buttons = edit.buttons || [];
  draw(edit.id);
}

function draw(id) {
  const reply = replies.get(id);
  const actions = buttons(id, reply);
  if (reply.card) {
    reply.element.replaceChildren(card(reply.card, actions));
  } else {
    reply.element.replaceChildren(el("p", "text", reply.text || ""));
    if (actions) reply.element.append(actions);
  }
}

function card(data, actions) {
  const box = el("div", "card");
  const body = el("div", "body");
  const badge = el("div", "badge");
  const [year, month, day] = data.date.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  badge.append(el("div", "weekday", date.toLocaleDateString("en-GB", { weekday: "short" })),
               el("div", "day", String(day)));
  const info = el("div");
  info.append(el("div", "kind", data.kind === "event" ? "Event" : data.whom ? `Reminder for ${data.whom}` : "Reminder"),
              el("div", "title", data.title), el("div", "meta", data.when));
  if (data.repeat) info.append(el("div", "meta", `Repeats ${data.repeat}`));
  body.append(badge, info);
  box.append(body);
  if (actions) {
    // An event's first row is "a reminder before it?"
    if (data.kind === "event" && actions.children.length > 1) {
      actions.firstChild.before(el("div", "hint", "A reminder before it?"));
    }
    box.append(actions);
  }
  return box;
}

function buttons(id, reply) {
  if (!reply.buttons.length) return null;
  const rows = el("div", "actions");
  for (const row of reply.buttons) {
    const line = el("div", "row");
    for (const button of row) {
      if (button.url) {
        const link = el("a", "", plain(button.text));
        link.href = button.url;
        link.addEventListener("click", (event) => {
          if (tg && tg.openLink) { event.preventDefault(); tg.openLink(button.url); }
        });
        line.append(link);
      } else {
        const tap = el("button", "", plain(button.text));
        tap.type = "button";
        tap.addEventListener("click", () => press(id, button.data, tap));
        line.append(tap);
      }
    }
    rows.append(line);
  }
  return rows;
}

function show(result, turn) {
  for (const edit of result.edits || []) update(edit);
  showSteps(turn, result.steps);
  // The echo of what was heard is the turn's own bubble
  const fresh = (result.messages || []).filter((m) => !(result.heard && m.text && m.text.startsWith("🎙 “")));
  for (const message of fresh) addReply(turn, message);
  if (result.alert) {
    if (tg && tg.showAlert) tg.showAlert(result.alert);
    else turn.append(el("div", "alert", result.alert));
  }
  setSuggestions(result.suggestions || []);
  if (turn.children.length) turn.scrollIntoView({ block: "end", behavior: "smooth" });
  else turn.remove();
  const spoken = fresh.map((m) => m.text).filter(Boolean).join("\n");
  if (spoken) say(spoken);
}

function setSuggestions(phrases) {
  $("suggestions").replaceChildren(...phrases.map((phrase) => {
    const chip = el("button", "", phrase);
    chip.type = "button";
    chip.addEventListener("click", () => fillIn(phrase));
    return chip;
  }));
}

async function thinking(turn, work) {
  document.body.classList.add("working");
  const now = el("ol", "steps");
  now.append(el("li", "now", "Working on it…"));
  turn.append(now);
  setSuggestions([]);
  let result;
  try {
    const response = await work();
    result = response.ok ? await response.json()
      : { messages: [{ id: "error", text: "Sorry, that didn't work. Try again in a moment.", buttons: [] }] };
  } catch (error) {
    result = error.message === "logged out" ? {}
      : { messages: [{ id: "error", text: "I can't reach the bot right now. Check your connection.", buttons: [] }] };
  }
  now.remove();
  document.body.classList.remove("working");
  show(result, turn);
  return result;
}

$("send").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("text").value.trim();
  if (!text) return;
  $("text").value = "";
  thinking(newTurn(text), () => api("/api/message", { method: "POST", json: { text } }));
});

function press(id, data, tap) {
  if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
  tap.disabled = true;
  const reply = replies.get(id);
  thinking(newTurn(), () => api("/api/button", {
    method: "POST", json: { data, message_id: Number(id), text: reply ? reply.text : undefined },
  })).finally(() => { tap.disabled = false; });
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
    show({ messages: [{ id: "mic", text: "I can't use the microphone. Allow it, or type instead.", buttons: [] }] },
         newTurn());
    return;
  }
  chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.addEventListener("dataavailable", (e) => { if (e.data.size) chunks.push(e.data); });
  recorder.addEventListener("stop", async () => {
    stream.getTracks().forEach((track) => track.stop());
    const audio = new Blob(chunks, { type: recorder.mimeType });
    recorder = null;
    $("mic").classList.remove("recording");
    if (audio.size < 1000) return; // a tap, not speech
    const turn = newTurn("…");
    const said = turn.firstChild;
    said.classList.add("listening");
    const result = await thinking(turn, () => api("/api/voice", {
      method: "POST", body: audio, headers: { "Content-Type": audio.type },
    }));
    if (result.heard) {
      said.textContent = result.heard;
      said.classList.remove("listening");
    } else {
      said.remove();
    }
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
  $("sound").replaceChildren(icon(on ? "soundOn" : "soundOff"));
  $("sound").setAttribute("aria-pressed", String(on));
  save("sound", on ? "on" : "off");
  if (!on) player.pause();
}

$("sound").addEventListener("click", () => setSound(!soundOn));

// --- the next 7 days ----------------------------------------------------------------

async function openWeek() {
  $("week-sheet").hidden = false;
  let days;
  try {
    const response = await api("/api/upcoming");
    if (!response.ok) return;
    days = (await response.json()).days;
  } catch (error) { return; }
  $("days").replaceChildren(...days.map((day) => {
    const block = el("section", "day");
    const list = el("ul");
    if (!day.items.length) list.append(el("li", "empty", "Nothing"));
    for (const item of day.items) {
      const line = el("li");
      line.append(el("span", "time", item.time || "all day"), el("span", "", item.text));
      list.append(line);
    }
    block.append(el("h3", "", day.label), list);
    return block;
  }));
}

$("week").addEventListener("click", openWeek);
$("week-close").addEventListener("click", () => { $("week-sheet").hidden = true; });
$("week-sheet").addEventListener("click", (event) => {
  if (event.target === $("week-sheet")) $("week-sheet").hidden = true;
});

$("top").addEventListener("click", () => {
  $("main").scrollTo({ top: 0, behavior: "smooth" });
  if (token) loadBriefing();
});

// --- start ------------------------------------------------------------------------

$("week").append(icon("week"));
$("week-close").append(icon("close"));
$("send-button").append(icon("send"));
$("mic").append(icon("mic"));
if (tg) {
  tg.ready();
  tg.expand();
  if (tg.colorScheme) document.documentElement.dataset.theme = tg.colorScheme;
}
setSound(load("sound") !== "off");
token = load("token");
if (token && !tg) started(token); else logIn();
