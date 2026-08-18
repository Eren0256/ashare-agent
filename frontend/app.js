const loginScreen = document.querySelector("#loginScreen");
const bootScreen = document.querySelector("#bootScreen");
const appShell = document.querySelector("#appShell");
const loginForm = document.querySelector("#loginForm");
const usernameInput = document.querySelector("#usernameInput");
const passwordInput = document.querySelector("#passwordInput");
const loginButton = document.querySelector("#loginButton");
const loginError = document.querySelector("#loginError");
const sessionList = document.querySelector("#sessionList");
const newChatButton = document.querySelector("#newChatButton");
const logoutButton = document.querySelector("#logoutButton");
const userMenuButton = document.querySelector("#userMenuButton");
const userPopover = document.querySelector("#userPopover");
const userInitial = document.querySelector("#userInitial");
const userName = document.querySelector("#userName");
const messages = document.querySelector("#messages");
const composer = document.querySelector("#composer");
const queryInput = document.querySelector("#queryInput");
const sendButton = document.querySelector("#sendButton");

const apiBase = getApiBase();
const terminalStatuses = new Set(["succeeded", "failed"]);
const syncIntervalMs = 4000;
const pendingSteps = {
  submitting: {
    title: "正在提交问题",
    detail: "正在保存消息并创建研究任务",
    progress: 18,
  },
  queued: {
    title: "任务已排队",
    detail: "后端已接收请求，正在等待执行",
    progress: 38,
  },
  running: {
    title: "正在研究",
    detail: "正在识别意图、检索数据并生成回答",
    progress: 68,
  },
  finishing: {
    title: "正在整理结果",
    detail: "正在保存回复并刷新会话标题",
    progress: 88,
  },
  succeeded: {
    title: "正在整理结果",
    detail: "研究已完成，正在渲染回复",
    progress: 96,
  },
};
const syncChannel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("ashare-agent-sync");
const syncSourceId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;

const state = {
  token: window.localStorage.getItem("ASHARE_AGENT_TOKEN") || "",
  user: null,
  sessions: [],
  sessionsNextCursor: "",
  sessionsLoadingMore: false,
  messagesNextCursor: "",
  messagesLoadingOlder: false,
  currentSessionId: "",
  busy: false,
  sessionsLoaded: false,
  syncTimerId: 0,
  syncInFlight: false,
};

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await login(usernameInput.value, passwordInput.value);
});

newChatButton.addEventListener("click", async () => {
  if (state.busy) {
    return;
  }
  startDraftSession();
});

logoutButton.addEventListener("click", logout);

userMenuButton.addEventListener("click", () => {
  userPopover.hidden = !userPopover.hidden;
});

document.addEventListener("click", (event) => {
  if (!event.target.closest("#userMenu")) {
    userPopover.hidden = true;
  }
});

window.addEventListener("focus", () => {
  void syncFromServer();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    void syncFromServer();
  }
});

sessionList.addEventListener("scroll", () => {
  const nearBottom = sessionList.scrollTop + sessionList.clientHeight >= sessionList.scrollHeight - 24;
  if (nearBottom) {
    void loadMoreSessions();
  }
});

messages.addEventListener("scroll", () => {
  if (messages.scrollTop <= 24) {
    void loadOlderMessages();
  }
});

window.addEventListener("storage", (event) => {
  if (event.key === "ASHARE_AGENT_SYNC_EVENT" && event.newValue) {
    try {
      handleSyncEvent(JSON.parse(event.newValue));
    } catch {
    }
  }
});

if (syncChannel) {
  syncChannel.addEventListener("message", (event) => {
    handleSyncEvent(event.data);
  });
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitQuery(queryInput.value);
});

queryInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    await submitQuery(queryInput.value);
  }
});

queryInput.addEventListener("input", autosizeComposer);

bootstrap();

async function bootstrap() {
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    const user = await fetchCurrentUser();
    showApp(user);
    await loadSessions();
  } catch {
    logout();
  }
}

async function login(username, password) {
  const cleanUsername = username.trim();
  if (!cleanUsername || !password || state.busy) {
    return;
  }
  loginError.textContent = "";
  loginButton.disabled = true;
  try {
    const response = await fetch(`${apiBase}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: cleanUsername, password }),
    });
    const payload = await readJsonResponse(response);
    state.token = payload.access_token;
    state.user = payload.user;
    window.localStorage.setItem("ASHARE_AGENT_TOKEN", state.token);
    showApp(payload.user);
    await loadSessions();
  } catch (error) {
    loginError.textContent = error.message;
  } finally {
    loginButton.disabled = false;
  }
}

async function fetchCurrentUser() {
  const response = await fetch(`${apiBase}/auth/me`, {
    headers: authHeaders(),
  });
  return readJsonResponse(response);
}

function logout() {
  state.token = "";
  state.user = null;
  state.sessions = [];
  state.sessionsNextCursor = "";
  state.sessionsLoadingMore = false;
  state.messagesNextCursor = "";
  state.messagesLoadingOlder = false;
  state.currentSessionId = "";
  state.sessionsLoaded = false;
  stopSyncLoop();
  window.localStorage.removeItem("ASHARE_AGENT_TOKEN");
  userPopover.hidden = true;
  showLogin();
}

function showLogin() {
  finishBoot();
  appShell.hidden = true;
  loginScreen.hidden = false;
  loginError.textContent = "";
  passwordInput.focus();
}

function showApp(user) {
  finishBoot();
  state.user = user;
  loginScreen.hidden = true;
  appShell.hidden = false;
  userInitial.textContent = userInitialFrom(user);
  userName.textContent = user?.display_name || user?.username || "-";
  queryInput.focus();
  startSyncLoop();
}

function finishBoot() {
  document.body.classList.remove("booting");
  if (bootScreen) {
    bootScreen.hidden = true;
  }
}

async function loadSessions(preferredSessionId = "") {
  if (!state.sessionsLoaded) {
    renderSessionSkeletons();
  }
  const page = await fetchSessionsPage();
  state.sessions = page.items;
  state.sessionsNextCursor = page.next_cursor || "";
  state.sessionsLoaded = true;
  const visible = visibleSessions();
  const currentVisible = state.currentSessionId && visible.some((session) => session.id === state.currentSessionId);
  const targetId = preferredSessionId || (currentVisible ? state.currentSessionId : "") || visible[0]?.id || "";
  renderSessions(targetId);
  if (!targetId || !state.sessions.some((session) => session.id === targetId)) {
    startDraftSession();
    return;
  }
  await loadMessages(targetId);
}

async function fetchSessionsPage(cursor = "") {
  const params = new URLSearchParams({ limit: "20" });
  if (cursor) {
    params.set("cursor", cursor);
  }
  const response = await fetch(`${apiBase}/sessions?${params.toString()}`, { headers: authHeaders() });
  return normalizeSessionsPage(await readJsonResponse(response));
}

function normalizeSessionsPage(payload) {
  return {
    items: Array.isArray(payload?.items) ? payload.items : [],
    next_cursor: typeof payload?.next_cursor === "string" ? payload.next_cursor : "",
  };
}

async function loadMoreSessions() {
  if (!state.sessionsLoaded || state.sessionsLoadingMore || !state.sessionsNextCursor) {
    return;
  }
  state.sessionsLoadingMore = true;
  const loading = document.createElement("div");
  loading.className = "session-loading-more";
  loading.textContent = "加载中";
  sessionList.appendChild(loading);
  try {
    const page = await fetchSessionsPage(state.sessionsNextCursor);
    state.sessions = mergeSessions(state.sessions, page.items);
    state.sessionsNextCursor = page.next_cursor || "";
  } catch (error) {
    if (error.status !== 401) {
      console.warn("加载更多会话失败", error);
    }
  } finally {
    state.sessionsLoadingMore = false;
    renderSessions(state.currentSessionId);
  }
}

async function createSession() {
  const response = await fetch(`${apiBase}/sessions`, {
    method: "POST",
    headers: authHeaders(),
  });
  return readJsonResponse(response);
}

function renderSessions(activeId) {
  sessionList.innerHTML = "";
  for (const session of visibleSessions()) {
    const row = document.createElement("div");
    row.className = session.id === activeId ? "session-row active" : "session-row";

    const button = document.createElement("button");
    button.className = "session-item";
    button.type = "button";
    button.textContent = session.title || "新对话";
    button.addEventListener("click", async () => {
      if (state.busy || session.id === state.currentSessionId) {
        return;
      }
      renderSessions(session.id);
      await loadMessages(session.id);
    });

    const deleteButton = document.createElement("button");
    deleteButton.className = "delete-session-button";
    deleteButton.type = "button";
    deleteButton.setAttribute("aria-label", "删除会话");
    deleteButton.textContent = "×";
    deleteButton.addEventListener("click", async (event) => {
      event.stopPropagation();
      await deleteSession(session.id);
    });

    row.append(button, deleteButton);
    sessionList.appendChild(row);
  }
  if (state.sessionsLoadingMore) {
    const loading = document.createElement("div");
    loading.className = "session-loading-more";
    loading.textContent = "加载中";
    sessionList.appendChild(loading);
  }
}

function renderSessionSkeletons() {
  sessionList.innerHTML = "";
  for (let index = 0; index < 4; index += 1) {
    const item = document.createElement("div");
    item.className = "session-skeleton";
    item.style.setProperty("--skeleton-width", `${76 - index * 9}%`);
    sessionList.appendChild(item);
  }
}

async function deleteSession(sessionId) {
  if (state.busy) {
    return;
  }
  const response = await fetch(`${apiBase}/sessions/${sessionId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  await readJsonResponse(response);
  if (sessionId === state.currentSessionId) {
    state.currentSessionId = "";
  }
  publishSyncEvent("session_deleted", { sessionId });
  await loadSessions();
}

function startDraftSession(message = "可以开始提问。") {
  state.currentSessionId = "";
  state.messagesNextCursor = "";
  state.messagesLoadingOlder = false;
  messages.innerHTML = "";
  renderSessions("");
  appendMessage("assistant", message);
  setStatus("就绪");
  queryInput.focus();
}

async function loadMessages(sessionId) {
  if (!sessionId) {
    startDraftSession();
    return;
  }
  state.currentSessionId = sessionId;
  state.messagesNextCursor = "";
  state.messagesLoadingOlder = false;
  messages.innerHTML = "";
  let page;
  try {
    page = await fetchMessagesPage(sessionId);
  } catch (error) {
    if (error.status === 404) {
      state.sessions = state.sessions.filter((session) => session.id !== sessionId);
      startDraftSession("当前会话已在其他窗口删除，可以重新开始提问。");
      return;
    }
    throw error;
  }
  const items = page.items;
  state.messagesNextCursor = page.next_cursor || "";
  if (items.length === 0) {
    appendMessage("assistant", "可以开始提问。");
  } else {
    for (const item of items) {
      appendMessage(item.role, item.content, item.metadata || null);
    }
  }
  setStatus("就绪");
}

async function fetchMessagesPage(sessionId, cursor = "") {
  const params = new URLSearchParams({ limit: "20" });
  if (cursor) {
    params.set("cursor", cursor);
  }
  const response = await fetch(`${apiBase}/sessions/${sessionId}/messages?${params.toString()}`, { headers: authHeaders() });
  return normalizeMessagesPage(await readJsonResponse(response));
}

function normalizeMessagesPage(payload) {
  return {
    items: Array.isArray(payload?.items) ? payload.items : [],
    next_cursor: typeof payload?.next_cursor === "string" ? payload.next_cursor : "",
  };
}

async function loadOlderMessages() {
  if (!state.currentSessionId || state.messagesLoadingOlder || !state.messagesNextCursor) {
    return;
  }
  state.messagesLoadingOlder = true;
  const loading = document.createElement("div");
  loading.className = "older-messages-loading";
  loading.textContent = "加载更早消息";
  messages.prepend(loading);
  const previousHeight = messages.scrollHeight;
  try {
    const page = await fetchMessagesPage(state.currentSessionId, state.messagesNextCursor);
    const fragment = document.createDocumentFragment();
    for (const item of page.items) {
      fragment.appendChild(createMessageElement(item.role, item.content, item.metadata || null));
    }
    loading.replaceWith(fragment);
    state.messagesNextCursor = page.next_cursor || "";
    messages.scrollTop = messages.scrollHeight - previousHeight;
  } catch (error) {
    loading.remove();
    if (error.status === 404) {
      await syncFromServer({ missingMessage: "当前会话已在其他窗口删除，可以重新开始提问。" });
      return;
    }
    if (error.status !== 401) {
      console.warn("加载更早消息失败", error);
    }
  } finally {
    state.messagesLoadingOlder = false;
  }
}

async function submitQuery(rawQuery) {
  const query = rawQuery.trim();
  if (!query || state.busy) {
    return;
  }

  setBusy(true);
  queryInput.value = "";
  queryInput.style.height = "auto";
  appendMessage("user", query);
  appendPendingMessage("submitting");
  setStatus("提交任务");

  try {
    let sessionId = state.currentSessionId;
    if (!sessionId) {
      const session = await createSession();
      sessionId = session.id;
      state.currentSessionId = sessionId;
      renderSessions(sessionId);
    }

    const submitted = await createSessionMessage(sessionId, query);
    publishSyncEvent("messages_changed", { sessionId });
    updatePendingMessage("queued");
    setStatus("任务已提交");
    const job = await pollJob(submitted.job_id);
    updatePendingMessage("finishing");
    removePendingMessage();

    if (job.status === "failed") {
      appendMessage("error", job.error || "任务失败");
      setStatus("失败");
      return;
    }

    const payload = job.result || {};
    const reply = payload.reply || "暂无结果。";
    appendMessage("assistant", reply, payload);
    setStatus("完成");
    await loadSessions(sessionId);
    publishSyncEvent("messages_changed", { sessionId });
  } catch (error) {
    removePendingMessage();
    if (error.status === 404) {
      queryInput.value = query;
      autosizeComposer();
      await syncFromServer({ missingMessage: "当前会话已在其他窗口删除，刚才的问题已放回输入框，可以重新发送。" });
      setStatus("会话已删除");
      return;
    }
    appendMessage("error", `请求失败：${error.message}`);
    setStatus("请求失败");
  } finally {
    setBusy(false);
  }
}

async function createSessionMessage(sessionId, query) {
  const response = await fetch(`${apiBase}/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ query }),
  });
  return readJsonResponse(response);
}

async function pollJob(jobId) {
  let delay = 350;
  for (;;) {
    await sleep(delay);
    const response = await fetch(`${apiBase}/jobs/${jobId}`, { headers: authHeaders() });
    const job = await readJsonResponse(response);
    updatePendingMessage(job.status);
    setStatus(statusText(job.status));
    if (terminalStatuses.has(job.status)) {
      return job;
    }
    delay = Math.min(delay + 250, 1600);
  }
}

async function readJsonResponse(response) {
  const payload = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      logout();
    }
    const error = new Error(payload.detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function appendMessage(role, text, payload = null) {
  messages.appendChild(createMessageElement(role, text, payload));
  messages.scrollTop = messages.scrollHeight;
}

function createMessageElement(role, text, payload = null) {
  const article = document.createElement("article");
  article.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? userInitialFrom(state.user) : role === "error" ? "!" : "M";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const body = document.createElement("div");
  body.className = "message-body";
  body.innerHTML = renderMarkdown(text);

  bubble.append(body);
  article.append(avatar, bubble);

  const artifacts = Array.isArray(payload?.artifacts) ? payload.artifacts : [];
  if (artifacts.length > 0) {
    const gallery = document.createElement("div");
    gallery.className = "artifact-gallery";
    for (const artifact of artifacts) {
      if (artifact?.type !== "image" || !artifact?.url) {
        continue;
      }
      const figure = document.createElement("figure");
      figure.className = "chart-card chart-loading";

      const image = document.createElement("img");
      image.className = "chart-image";
      image.alt = artifact.title || "财务分析图表";

      const caption = document.createElement("figcaption");
      caption.className = "chart-caption";
      caption.textContent = artifact.title || "财务分析图表";

      figure.append(image, caption);
      gallery.appendChild(figure);
      void loadArtifactImage(artifact, image, figure);
    }
    if (gallery.childElementCount > 0) {
      bubble.appendChild(gallery);
    }
  }

  return article;
}

function appendPendingMessage(step = "submitting") {
  const article = document.createElement("article");
  article.className = "message assistant pending";
  article.dataset.pending = "true";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "M";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const body = document.createElement("div");
  body.className = "message-body";
  body.innerHTML = pendingMessageHtml(step);

  bubble.append(body);
  article.append(avatar, bubble);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
}

function updatePendingMessage(step) {
  const pending = messages.querySelector("[data-pending='true'] .message-body");
  if (pending) {
    pending.innerHTML = pendingMessageHtml(step);
    messages.scrollTop = messages.scrollHeight;
  }
}

function removePendingMessage() {
  const pending = messages.querySelector("[data-pending='true']");
  if (pending) {
    pending.remove();
  }
}

function pendingMessageHtml(step) {
  const spec = pendingSteps[step] || pendingSteps.running;
  return `
    <div class="thinking-card">
      <div class="thinking-head">
        <span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>
        <span class="thinking-title">${escapeHtml(spec.title)}</span>
      </div>
      <div class="thinking-detail">${escapeHtml(spec.detail)}</div>
      <div class="thinking-track" aria-hidden="true">
        <span style="width: ${spec.progress}%"></span>
      </div>
    </div>
  `;
}

function renderMarkdown(markdown) {
  const lines = escapeHtml(markdown || "").split(/\r?\n/);
  const html = [];
  let inList = false;

  for (const line of lines) {
    if (line.startsWith("### ")) {
      closeList();
      html.push(`<h3>${line.slice(4)}</h3>`);
    } else if (line.startsWith("## ")) {
      closeList();
      html.push(`<h2>${line.slice(3)}</h2>`);
    } else if (line.startsWith("# ")) {
      closeList();
      html.push(`<h2>${line.slice(2)}</h2>`);
    } else if (line.startsWith("- ")) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${line.slice(2)}</li>`);
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      html.push(`<p>${line}</p>`);
    }
  }
  closeList();
  return html.join("");

  function closeList() {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  }
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function absoluteApiUrl(path) {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${apiBase}${path.startsWith("/") ? path : `/${path}`}`;
}

async function loadArtifactImage(artifact, image, figure) {
  try {
    const response = await fetch(absoluteApiUrl(artifact.url), { headers: authHeaders() });
    if (!response.ok) {
      if (response.status === 401) {
        logout();
      }
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    image.addEventListener("load", () => {
      figure.classList.remove("chart-loading");
    }, { once: true });
    image.src = url;
    image.addEventListener("click", () => window.open(url, "_blank", "noopener"));
  } catch (error) {
    figure.classList.remove("chart-loading");
    figure.classList.add("chart-error");
    image.remove();
    const caption = figure.querySelector(".chart-caption");
    caption.textContent = `图片加载失败：${error.message}`;
  }
}

function startSyncLoop() {
  stopSyncLoop();
  if (!state.token) {
    return;
  }
  state.syncTimerId = window.setInterval(() => {
    if (!document.hidden) {
      void syncFromServer();
    }
  }, syncIntervalMs);
}

function stopSyncLoop() {
  if (state.syncTimerId) {
    window.clearInterval(state.syncTimerId);
    state.syncTimerId = 0;
  }
  state.syncInFlight = false;
}

async function syncFromServer(options = {}) {
  if (!state.token || state.syncInFlight || loginScreen.hidden === false) {
    return;
  }

  const missingMessage = options.missingMessage || "当前会话已在其他窗口删除，可以重新开始提问。";
  const previousSessions = state.sessions;
  const previousCurrentId = state.currentSessionId;
  state.syncInFlight = true;

  try {
    const page = await fetchSessionsPage();
    const nextSessions = page.items;
    const mergedSessions = mergeSessions(previousSessions, nextSessions);
    const currentStillExists = !previousCurrentId || mergedSessions.some((session) => session.id === previousCurrentId);
    const currentChanged = sessionVersion(previousSessions, previousCurrentId) !== sessionVersion(mergedSessions, previousCurrentId);

    state.sessions = mergedSessions;
    state.sessionsNextCursor = page.next_cursor || "";

    if (previousCurrentId && !currentStillExists) {
      startDraftSession(missingMessage);
      return;
    }

    renderSessions(state.currentSessionId);
    if (state.currentSessionId && currentChanged && !state.busy) {
      await loadMessages(state.currentSessionId);
    }
  } catch (error) {
    if (error.status !== 401) {
      console.warn("同步会话失败", error);
    }
  } finally {
    state.syncInFlight = false;
  }
}

function publishSyncEvent(type, payload = {}) {
  if (!state.user) {
    return;
  }
  const event = {
    type,
    payload,
    sourceId: syncSourceId,
    userId: state.user.id,
    at: Date.now(),
  };
  if (syncChannel) {
    syncChannel.postMessage(event);
    return;
  }
  try {
    window.localStorage.setItem("ASHARE_AGENT_SYNC_EVENT", JSON.stringify(event));
  } catch {
  }
}

function handleSyncEvent(event) {
  if (!event || event.sourceId === syncSourceId || event.userId !== state.user?.id) {
    return;
  }
  if (event.type === "session_deleted" && event.payload?.sessionId === state.currentSessionId && !state.busy) {
    state.sessions = state.sessions.filter((session) => session.id !== event.payload.sessionId);
    startDraftSession("当前会话已在其他窗口删除，可以重新开始提问。");
    return;
  }
  if (["session_deleted", "sessions_changed", "messages_changed"].includes(event.type)) {
    void syncFromServer();
  }
}

function sessionVersion(sessions, sessionId) {
  const session = sessions.find((item) => item.id === sessionId);
  return session ? `${session.title}|${session.updated_at}` : "";
}

function mergeSessions(existing, incoming) {
  const byId = new Map();
  for (const session of existing) {
    byId.set(session.id, session);
  }
  for (const session of incoming) {
    byId.set(session.id, session);
  }
  return Array.from(byId.values()).sort(compareSessions);
}

function compareSessions(left, right) {
  const byUpdatedAt = String(right.updated_at || "").localeCompare(String(left.updated_at || ""));
  if (byUpdatedAt !== 0) {
    return byUpdatedAt;
  }
  return String(right.id || "").localeCompare(String(left.id || ""));
}

function visibleSessions() {
  return state.sessions.filter((session) => session.title && session.title !== "新对话");
}

function setStatus(text) {
  document.title = text === "就绪" ? "A股分析智能体" : `${text} - A股分析智能体`;
}

function statusText(status) {
  if (status === "queued") {
    return "排队中";
  }
  if (status === "running") {
    return "研究中";
  }
  if (status === "succeeded") {
    return "完成";
  }
  if (status === "failed") {
    return "失败";
  }
  return status || "处理中";
}

function formatNumber(value) {
  if (Math.abs(value) >= 10000) {
    return `${(value / 10000).toFixed(1)}万`;
  }
  return value.toFixed(1);
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function setBusy(busy) {
  state.busy = busy;
  sendButton.disabled = busy;
  queryInput.disabled = busy;
  sendButton.classList.toggle("is-loading", busy);
  sendButton.textContent = busy ? "发送中" : "发送";
}

function authHeaders(extra = {}) {
  return {
    ...extra,
    Authorization: `Bearer ${state.token}`,
  };
}

function userInitialFrom(user) {
  const name = user?.display_name || user?.username || "U";
  return name.trim().slice(0, 1).toUpperCase();
}

function autosizeComposer() {
  queryInput.style.height = "auto";
  queryInput.style.height = `${Math.min(queryInput.scrollHeight, 150)}px`;
}

function getApiBase() {
  const configured = window.localStorage.getItem("ASHARE_AGENT_API_BASE");
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  const host = window.location.hostname || "127.0.0.1";
  return `${window.location.protocol}//${host}:8000`;
}
