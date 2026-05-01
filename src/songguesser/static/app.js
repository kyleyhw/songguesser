// songguesser browser client.
//
// State machine
// -------------
//   landing  ──create-or-join──► game (LOBBY)
//   game LOBBY ──server "round_start"──► PLAYING
//   game PLAYING ──server "round_end"──► REVEAL
//   game REVEAL ──server "round_start" or "state(FINISHED)"──► next/end

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const state = {
  ws: null,
  code: null,
  playerId: localStorage.getItem("playerId") || crypto.randomUUID(),
  name: localStorage.getItem("playerName") || "",
  isHost: false,
  // Reveal-progress visuals — updated from `round_tick`.
  progress: 0.0,
};
localStorage.setItem("playerId", state.playerId);

function show(screenId) {
  $$(".screen").forEach((s) => s.classList.remove("visible"));
  $(`#${screenId}`).classList.add("visible");
}

function toast(msg, kind = "good") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ---- Landing flows ---------------------------------------------------------

$("#formCreate").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const playlist_url = $("#inpPlaylist").value.trim();
  const max_rounds = parseInt($("#inpRounds").value, 10);
  const round_seconds = parseFloat($("#inpRoundSec").value);
  const btn = ev.target.querySelector("button[type=submit]");
  btn.disabled = true;
  btn.textContent = "Resolving playlist…";
  try {
    const r = await fetch("/api/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ playlist_url, max_rounds, round_seconds }),
    });
    if (!r.ok) {
      const txt = await r.text();
      toast(`Failed: ${txt}`, "bad");
      return;
    }
    const j = await r.json();
    toast(`Room ${j.code}: ${j.track_count} tracks loaded.`, "good");
    state.code = j.code;
    state.name = state.name || "Host";
    localStorage.setItem("playerName", state.name);
    connect();
  } finally {
    btn.disabled = false;
    btn.textContent = "Create room";
  }
});

$("#formJoin").addEventListener("submit", (ev) => {
  ev.preventDefault();
  state.code = $("#inpCode").value.trim().toUpperCase();
  state.name = $("#inpName").value.trim();
  if (!state.code || !state.name) return;
  localStorage.setItem("playerName", state.name);
  connect();
});

// ---- Game connection -------------------------------------------------------

function connect() {
  if (state.ws) state.ws.close();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws/${state.code}`
    + `?player_id=${encodeURIComponent(state.playerId)}`
    + `&name=${encodeURIComponent(state.name)}`;
  const ws = new WebSocket(url);
  state.ws = ws;
  ws.addEventListener("open", () => {
    show("screen-game");
    $("#lblCode").textContent = state.code;
    chatPush("system", "Connected.");
  });
  ws.addEventListener("message", (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleMessage(msg);
  });
  ws.addEventListener("close", (ev) => {
    chatPush("system", `Disconnected (${ev.code} ${ev.reason || "closed"}).`);
    setEnabled(false);
  });
  ws.addEventListener("error", () => toast("Connection error", "bad"));
}

function send(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(obj));
  }
}

// ---- Message handling ------------------------------------------------------

function handleMessage(m) {
  switch (m.type) {
    case "state": return onState(m.room);
    case "round_start": return onRoundStart(m);
    case "round_tick": return onRoundTick(m);
    case "round_end": return onRoundEnd(m);
    case "guess_result": return onGuessResult(m);
    case "chat": return onChat(m);
    case "error": return toast(m.message, "bad");
    case "pong": return;
  }
}

function onState(room) {
  $("#lblPlaylist").textContent = room.playlist_name;
  $("#lblPhase").textContent = phaseLabel(room.phase);
  $("#lblRound").textContent = room.round_index >= 0
    ? `Round ${room.round_index + 1} / ${room.total_rounds}`
    : `${room.total_rounds} rounds`;
  renderPlayers(room.players);
  // Identify ourselves and whether we're host.
  const me = room.players.find((p) => p.id === state.playerId);
  state.isHost = !!(me && me.is_host);
  $("#btnHostStart").hidden = !(state.isHost && room.phase === "lobby");
  setEnabled(room.phase === "playing");
}

function onRoundStart(m) {
  // binb-style: cover is hidden until reveal. Stage shows just round number.
  state.pendingCoverUrl = m.cover_url || null;
  const cover = $("#cover");
  cover.removeAttribute("src");
  $("#stageRoundNumber").textContent = `Round ${m.round_index + 1}`;
  $("#stage").classList.remove("revealed");
  $("#progressBar").style.width = "0%";
  $("#revealBanner").hidden = true;
  $("#btnHostStart").hidden = true;
  const audio = $("#audio");
  audio.src = m.audio_url;
  audio.currentTime = 0;
  audio.play().catch(() => toast("Click anywhere to enable audio", "warn"));
  setEnabled(true);
  chatPush("system", `Round ${m.round_index + 1} started.`);
}

function onRoundTick(m) {
  // binb-style: progress bar only; cover stays hidden until reveal.
  $("#progressBar").style.width = `${(m.progress * 100).toFixed(1)}%`;
}

function onRoundEnd(m) {
  // Reveal: show the cover and post the answer to chat.
  const cover = $("#cover");
  if (m.track.cover_url) cover.src = m.track.cover_url;
  $("#stage").classList.add("revealed");
  $("#progressBar").style.width = "100%";
  setEnabled(false);
  renderPlayers(m.leaderboard);
  chatPush("answer", `${m.track.title} - ${m.track.artist}`);
  if (m.is_final) chatPush("system", "Final round complete.");
}

function onGuessResult(m) {
  const isMe = m.player_id === state.playerId;
  const verb = m.kind === "both" ? "got it" : (m.kind === "title" ? "got the title" : (m.kind === "artist" ? "got the artist" : ""));
  if (verb) {
    chatPush("correct", `${m.name} ${verb} (+${m.points})`);
    if (isMe) toast(`+${m.points}`, "good");
  }
}

function onChat(m) {
  const isMe = m.player_id === state.playerId;
  chatPush(isMe ? "self" : "", `${m.name}: ${m.text}`);
}

// ---- UI helpers ------------------------------------------------------------

function phaseLabel(phase) {
  return { lobby: "Lobby", playing: "Playing", reveal: "Reveal", finished: "Game over" }[phase] || phase;
}

function setEnabled(enabled) {
  $("#inpGuess").disabled = !enabled;
  $("#formGuess button").disabled = !enabled;
  if (enabled) $("#inpGuess").focus();
}

function renderPlayers(players) {
  const ul = $("#players");
  ul.innerHTML = "";
  for (const p of players) {
    const li = document.createElement("li");
    if (!p.connected) li.classList.add("dim");
    if (p.is_host) {
      const star = document.createElement("span"); star.className = "host-star"; star.textContent = "★";
      li.appendChild(star);
    }
    const name = document.createElement("span"); name.className = "name"; name.textContent = p.name;
    li.appendChild(name);
    if (p.round_kind && p.round_kind !== "none") {
      const kind = document.createElement("span");
      kind.className = `kind ${p.round_kind}`;
      kind.textContent = p.round_kind;
      li.appendChild(kind);
    }
    const score = document.createElement("span"); score.className = "score"; score.textContent = String(p.score);
    li.appendChild(score);
    ul.appendChild(li);
  }
}

function chatPush(cls, text) {
  const ul = $("#chat");
  const li = document.createElement("li");
  if (cls) li.className = cls;
  li.textContent = text;
  ul.appendChild(li);
  ul.scrollTop = ul.scrollHeight;
  // Cap chat history at 80 entries to keep DOM small.
  while (ul.children.length > 80) ul.removeChild(ul.firstChild);
}

// ---- Inputs ----------------------------------------------------------------

$("#formGuess").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const text = $("#inpGuess").value.trim();
  if (!text) return;
  send({ type: "guess", text });
  $("#inpGuess").value = "";
});

$("#btnHostStart").addEventListener("click", () => send({ type: "start" }));

// Volume control. Slider range is 0–50 (half of the full audio gain range);
// default audio.volume = 0.15 (the slider's centre). Persisted to localStorage.
const audio = $("#audio");
const volSlider = $("#inpVolume");
const VOL_MAX = 0.5;  // slider value 50 maps to audio.volume 0.5
const savedVol = parseFloat(localStorage.getItem("volume") ?? "0.15");
const initialVol = Number.isFinite(savedVol) ? Math.max(0, Math.min(VOL_MAX, savedVol)) : 0.15;
audio.volume = initialVol;
volSlider.value = String(Math.round(initialVol * 100));
volSlider.addEventListener("input", () => {
  const v = parseInt(volSlider.value, 10) / 100;
  audio.volume = v;
  localStorage.setItem("volume", String(v));
});

// Click-to-unlock audio (browsers block autoplay until a gesture).
document.body.addEventListener("click", () => {
  const a = $("#audio");
  if (a.paused && a.src) a.play().catch(() => {});
}, { once: true });

