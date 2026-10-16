// App State
let authToken = localStorage.getItem("campusbot_token") || "";
let currentUser = null;
let currentSessionId = null;
let isSubmitting = false;

// DOM Elements
const authModal = document.getElementById("authModal");
const authForm = document.getElementById("authForm");
const authUsername = document.getElementById("authUsername");
const authPassword = document.getElementById("authPassword");
const authEmail = document.getElementById("authEmail");
const emailField = document.getElementById("emailField");
const authError = document.getElementById("authError");
const authBtnText = document.getElementById("authBtnText");
const tabLogin = document.getElementById("tabLogin");
const tabRegister = document.getElementById("tabRegister");
const quickDemoBtn = document.getElementById("quickDemoBtn");

const sessionsList = document.getElementById("sessionsList");
const newChatBtn = document.getElementById("newChatBtn");
const currentChatTitle = document.getElementById("currentChatTitle");
const chatMessages = document.getElementById("chatMessages");
const welcomeScreen = document.getElementById("welcomeScreen");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const voiceBtn = document.getElementById("voiceBtn");

const userNameDisplay = document.getElementById("userNameDisplay");
const userAvatar = document.getElementById("userAvatar");
const logoutBtn = document.getElementById("logoutBtn");

const openCrawlerBtn = document.getElementById("openCrawlerBtn");
const crawlerModal = document.getElementById("crawlerModal");
const closeCrawlerModal = document.getElementById("closeCrawlerModal");
const crawlerSummaryText = document.getElementById("crawlerSummaryText");
const modalTargetUrl = document.getElementById("modalTargetUrl");
const modalLastSyncText = document.getElementById("modalLastSyncText");
const modalTotalPages = document.getElementById("modalTotalPages");
const modalTotalChunks = document.getElementById("modalTotalChunks");
const crawledPagesList = document.getElementById("crawledPagesList");
const modalSyncNowBtn = document.getElementById("modalSyncNowBtn");
const quickSyncBtn = document.getElementById("quickSyncBtn");
const syncSpinIcon = document.getElementById("syncSpinIcon");

const openConfigBtn = document.getElementById("openConfigBtn");
const configModal = document.getElementById("configModal");
const closeConfigModal = document.getElementById("closeConfigModal");
const configForm = document.getElementById("configForm");
const configProvider = document.getElementById("configProvider");
const configGroqKey = document.getElementById("configGroqKey");
const configGeminiKey = document.getElementById("configGeminiKey");
const configOpenaiKey = document.getElementById("configOpenaiKey");
const modelBadge = document.getElementById("modelBadge");

let isRegisterTab = false;

// --- API Helper ---
async function apiRequest(endpoint, options = {}) {
  const headers = options.headers || {};
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  if (options.body && typeof options.body === "object") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  options.headers = headers;

  const res = await fetch(endpoint, options);
  if (res.status === 401 && !endpoint.includes("/auth/")) {
    handleLogout();
    throw new Error("Session expired. Please log in.");
  }
  // Error responses (e.g. a proxy's 502 page) are not always JSON.
  let data = {};
  try {
    data = await res.json();
  } catch (e) {
    if (!res.ok) throw new Error(`Server error (${res.status})`);
  }
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join("; ") : data.detail;
    throw new Error(detail || data.message || `Request failed (${res.status})`);
  }
  return data;
}

// --- Initialization ---
async function initApp() {
  if (window.lucide) lucide.createIcons();

  if (!authToken) {
    showAuthModal();
  } else {
    try {
      const data = await apiRequest("/api/auth/me");
      currentUser = data.user;
      setupUserUI();
      await fetchSessions();
      await updateCrawlerStatus();
      await refreshModelBadge();
    } catch (e) {
      showAuthModal();
    }
  }
  setupEventListeners();
}

function setupUserUI() {
  if (currentUser) {
    userNameDisplay.textContent = currentUser.username;
    userAvatar.textContent = currentUser.username.charAt(0).toUpperCase();
  }
}

// --- Auth Handling ---
function showAuthModal() {
  authModal.classList.remove("hidden");
  authUsername.focus();
}

function hideAuthModal() {
  authModal.classList.add("hidden");
}

tabLogin.addEventListener("click", () => {
  isRegisterTab = false;
  tabLogin.className = "flex-1 py-2 text-sm font-semibold border-b-2 border-indigo-500 text-indigo-400 focus:outline-none transition";
  tabRegister.className = "flex-1 py-2 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-200 focus:outline-none transition";
  emailField.classList.add("hidden");
  authBtnText.textContent = "Sign In";
  authError.classList.add("hidden");
});

tabRegister.addEventListener("click", () => {
  isRegisterTab = true;
  tabRegister.className = "flex-1 py-2 text-sm font-semibold border-b-2 border-indigo-500 text-indigo-400 focus:outline-none transition";
  tabLogin.className = "flex-1 py-2 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-200 focus:outline-none transition";
  emailField.classList.remove("hidden");
  authBtnText.textContent = "Create Account";
  authError.classList.add("hidden");
});

authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  authError.classList.add("hidden");
  const username = authUsername.value.trim();
  const password = authPassword.value;
  const email = authEmail.value.trim();

  try {
    const endpoint = isRegisterTab ? "/api/auth/register" : "/api/auth/login";
    const payload = isRegisterTab ? { username, password, email } : { username, password };
    const res = await apiRequest(endpoint, { method: "POST", body: payload });

    authToken = res.token;
    localStorage.setItem("campusbot_token", authToken);
    currentUser = res.user;

    setupUserUI();
    hideAuthModal();
    await fetchSessions();
    await updateCrawlerStatus();
    await refreshModelBadge();
  } catch (err) {
    authError.textContent = err.message;
    authError.classList.remove("hidden");
  }
});

quickDemoBtn.addEventListener("click", async () => {
  try {
    // Attempt login as demo_student or register if not existing
    try {
      const res = await apiRequest("/api/auth/login", {
        method: "POST",
        body: { username: "demo_student", password: "password123" }
      });
      authToken = res.token;
      currentUser = res.user;
    } catch (e) {
      const res = await apiRequest("/api/auth/register", {
        method: "POST",
        body: { username: "demo_student", password: "password123", email: "demo@iiitkottayam.ac.in" }
      });
      authToken = res.token;
      currentUser = res.user;
    }
    localStorage.setItem("campusbot_token", authToken);
    setupUserUI();
    hideAuthModal();
    await fetchSessions();
    await updateCrawlerStatus();
    await refreshModelBadge();
  } catch (err) {
    alert("Demo login error: " + err.message);
  }
});

function handleLogout() {
  if (authToken) {
    // Revoke the token server-side; ignore network errors, we log out locally anyway.
    fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${authToken}` } }).catch(() => {});
  }
  stopSyncPolling();
  authToken = "";
  localStorage.removeItem("campusbot_token");
  currentUser = null;
  currentSessionId = null;
  sessionsList.innerHTML = "";
  chatMessages.innerHTML = "";
  chatMessages.appendChild(welcomeScreen);
  welcomeScreen.classList.remove("hidden");
  currentChatTitle.textContent = "New Conversation";
  showAuthModal();
}

logoutBtn.addEventListener("click", handleLogout);

// --- Sessions & Chat History ---
async function fetchSessions() {
  try {
    const res = await apiRequest("/api/sessions");
    renderSessions(res.sessions);
    if (res.sessions.length > 0 && !currentSessionId) {
      loadSession(res.sessions[0].id);
    } else if (res.sessions.length === 0) {
      await startNewChat();
    }
  } catch (err) {
    console.error("Failed to load chat history:", err);
  }
}

function renderSessions(sessions) {
  sessionsList.innerHTML = "";
  if (!sessions || sessions.length === 0) {
    sessionsList.innerHTML = `<div class="text-center py-6 text-xs text-slate-500">No chat history yet</div>`;
    return;
  }

  sessions.forEach(s => {
    const item = document.createElement("div");
    item.className = `session-item flex items-center justify-between p-2.5 rounded-xl cursor-pointer text-xs transition group border border-transparent hover:bg-slate-800/80 ${s.id === currentSessionId ? "active" : ""}`;
    item.dataset.id = s.id;

    item.innerHTML = `
      <div class="flex items-center space-x-2 truncate flex-1 pr-2">
        <i data-lucide="message-square" class="w-3.5 h-3.5 text-slate-400 group-hover:text-indigo-400 shrink-0"></i>
        <span class="session-title text-slate-300 truncate">${escapeHtml(s.title)}</span>
      </div>
      <button class="delete-session-btn opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-400 rounded transition" title="Delete Chat">
        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
      </button>
    `;

    item.addEventListener("click", (e) => {
      if (!e.target.closest(".delete-session-btn")) {
        loadSession(s.id);
      }
    });

    const delBtn = item.querySelector(".delete-session-btn");
    delBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (confirm(`Delete conversation "${s.title}"?`)) {
        await deleteSession(s.id);
      }
    });

    sessionsList.appendChild(item);
  });

  if (window.lucide) lucide.createIcons();
}

async function startNewChat() {
  try {
    const res = await apiRequest("/api/sessions", {
      method: "POST",
      body: { title: "New Conversation" }
    });
    currentSessionId = res.session.id;
    currentChatTitle.textContent = "New Conversation";
    chatMessages.innerHTML = "";
    chatMessages.appendChild(welcomeScreen);
    welcomeScreen.classList.remove("hidden");
    await fetchSessions();
  } catch (err) {
    console.error("Failed to create new chat:", err);
  }
}

newChatBtn.addEventListener("click", startNewChat);

async function loadSession(sessionId) {
  currentSessionId = sessionId;
  document.querySelectorAll(".session-item").forEach(el => {
    el.classList.toggle("active", el.dataset.id === sessionId);
  });

  try {
    const res = await apiRequest(`/api/sessions/${sessionId}`);
    currentChatTitle.textContent = res.session.title;
    renderMessages(res.messages);
  } catch (err) {
    console.error("Failed to load session messages:", err);
  }
}

async function deleteSession(sessionId) {
  try {
    await apiRequest(`/api/sessions/${sessionId}`, { method: "DELETE" });
    if (currentSessionId === sessionId) {
      currentSessionId = null;
    }
    await fetchSessions();
  } catch (err) {
    alert("Could not delete session: " + err.message);
  }
}

// --- Message Rendering ---
function renderMessages(messages) {
  chatMessages.innerHTML = "";
  if (!messages || messages.length === 0) {
    chatMessages.appendChild(welcomeScreen);
    welcomeScreen.classList.remove("hidden");
    return;
  }

  welcomeScreen.classList.add("hidden");
  messages.forEach(m => {
    appendMessageBubble(m.role, m.content, m.sources);
  });
  scrollToBottom();
}

function appendMessageBubble(role, content, sources = []) {
  welcomeScreen.classList.add("hidden");
  const isUser = role === "user";
  const wrapper = document.createElement("div");
  wrapper.className = `flex items-start space-x-3 ${isUser ? "flex-row-reverse space-x-reverse" : ""}`;

  const avatar = document.createElement("div");
  avatar.className = `w-8 h-8 rounded-xl flex items-center justify-center shrink-0 text-xs font-bold ${
    isUser 
      ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30" 
      : "bg-slate-800 border border-slate-700 text-emerald-400"
  }`;
  avatar.innerHTML = isUser ? `<i data-lucide="user" class="w-4 h-4"></i>` : `<i data-lucide="bot" class="w-4 h-4"></i>`;

  const bubble = document.createElement("div");
  bubble.className = `max-w-2xl rounded-2xl p-4 text-sm leading-relaxed ${
    isUser 
      ? "bg-indigo-600 text-white rounded-tr-none shadow-md shadow-indigo-600/20" 
      : "bg-slate-900 border border-slate-800/80 text-slate-100 rounded-tl-none shadow-xl"
  }`;

  // Content rendering with Markdown for assistant
  if (isUser) {
    bubble.textContent = content;
  } else {
    const prose = document.createElement("div");
    prose.className = "prose-custom";
    // Answers are generated from crawled web text, so sanitize before inserting.
    prose.innerHTML = DOMPurify.sanitize(marked.parse(content || ""));
    prose.querySelectorAll("a").forEach(a => {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    });
    bubble.appendChild(prose);

    // Render Source Citations
    if (sources && sources.length > 0) {
      const citationsDiv = document.createElement("div");
      citationsDiv.className = "mt-3 pt-3 border-t border-slate-800/80 flex flex-wrap gap-1.5 items-center";
      
      const label = document.createElement("span");
      label.className = "text-[10px] uppercase font-semibold tracking-wider text-slate-400 mr-1";
      label.textContent = "Sources:";
      citationsDiv.appendChild(label);

      sources.forEach(s => {
        const chip = document.createElement("a");
        chip.href = safeUrl(s.url);
        chip.target = "_blank";
        chip.rel = "noopener noreferrer";
        chip.className = "inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-slate-950 border border-slate-800 hover:border-indigo-500/60 text-[11px] text-indigo-300 hover:text-indigo-200 transition shadow-sm";
        chip.innerHTML = `
          <span>${escapeHtml(s.title || "IIITK Page")}</span>
          <i data-lucide="external-link" class="w-3 h-3 ml-1 text-slate-400"></i>
        `;
        citationsDiv.appendChild(chip);
      });

      bubble.appendChild(citationsDiv);
    }
  }

  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  chatMessages.appendChild(wrapper);

  if (window.lucide) lucide.createIcons();
}

function showTypingIndicator() {
  const indicator = document.createElement("div");
  indicator.id = "typingIndicator";
  indicator.className = "flex items-start space-x-3";
  indicator.innerHTML = `
    <div class="w-8 h-8 rounded-xl bg-slate-800 border border-slate-700 text-emerald-400 flex items-center justify-center shrink-0">
      <i data-lucide="bot" class="w-4 h-4"></i>
    </div>
    <div class="bg-slate-900 border border-slate-800/80 rounded-2xl rounded-tl-none p-4 flex items-center space-x-1.5 shadow-xl">
      <span class="w-2 h-2 rounded-full bg-indigo-400 typing-dot"></span>
      <span class="w-2 h-2 rounded-full bg-indigo-400 typing-dot"></span>
      <span class="w-2 h-2 rounded-full bg-indigo-400 typing-dot"></span>
    </div>
  `;
  chatMessages.appendChild(indicator);
  if (window.lucide) lucide.createIcons();
  scrollToBottom();
}

function hideTypingIndicator() {
  const el = document.getElementById("typingIndicator");
  if (el) el.remove();
}

function scrollToBottom() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// --- Submit Message ---
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (!text || isSubmitting) return;

  if (!currentSessionId) {
    await startNewChat();
  }

  // Add user bubble
  appendMessageBubble("user", text);
  messageInput.value = "";
  messageInput.style.height = "auto";
  scrollToBottom();

  isSubmitting = true;
  sendBtn.disabled = true;
  showTypingIndicator();

  try {
    const res = await apiRequest(`/api/sessions/${currentSessionId}/message`, {
      method: "POST",
      body: { content: text }
    });

    hideTypingIndicator();
    appendMessageBubble("assistant", res.message.content, res.sources);
    scrollToBottom();

    // Refresh titles in sidebar
    await fetchSessions();
  } catch (err) {
    hideTypingIndicator();
    appendMessageBubble("assistant", `⚠️ **Error retrieving information**: ${err.message}`);
    scrollToBottom();
  } finally {
    isSubmitting = false;
    sendBtn.disabled = false;
  }
});

// Auto-expand textarea
messageInput.addEventListener("input", function() {
  this.style.height = "auto";
  this.style.height = (this.scrollHeight) + "px";
});

messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});

// Prompt Chips trigger
document.querySelectorAll(".prompt-chip").forEach(chip => {
  chip.addEventListener("click", () => {
    const q = chip.querySelector(".text-slate-300").textContent.trim();
    messageInput.value = q;
    chatForm.requestSubmit();
  });
});

// --- Speech to Text ---
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;

  voiceBtn.addEventListener("click", () => {
    recognition.start();
    voiceBtn.classList.add("text-rose-400", "animate-pulse");
  });

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    messageInput.value = transcript;
    voiceBtn.classList.remove("text-rose-400", "animate-pulse");
    messageInput.focus();
  };

  recognition.onerror = () => {
    voiceBtn.classList.remove("text-rose-400", "animate-pulse");
  };

  recognition.onend = () => {
    voiceBtn.classList.remove("text-rose-400", "animate-pulse");
  };
} else {
  voiceBtn.style.display = "none";
}

// --- Crawler & Sync Management ---
async function updateCrawlerStatus() {
  try {
    const status = await apiRequest("/api/crawler/status");
    crawlerSummaryText.textContent = `${status.total_pages} pages • ${status.total_chunks} chunks`;
    modalTargetUrl.textContent = status.target_url;
    modalTotalPages.textContent = status.total_pages;
    modalTotalChunks.textContent = status.total_chunks;
    modalLastSyncText.textContent = status.last_sync_time 
      ? `Last Synced: ${new Date(status.last_sync_time).toLocaleString()}` 
      : "Last Synced: Never";

    if (status.is_running) {
      syncSpinIcon.classList.add("animate-spin");
      modalSyncNowBtn.disabled = true;
      modalSyncNowBtn.innerHTML = `<i data-lucide="refresh-cw" class="w-3.5 h-3.5 animate-spin"></i><span>Crawling...</span>`;
    } else {
      syncSpinIcon.classList.remove("animate-spin");
      modalSyncNowBtn.disabled = false;
      modalSyncNowBtn.innerHTML = `<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>Crawl & Sync Now</span>`;
    }
    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error("Failed to fetch crawler status:", err);
  }
}

let syncPollTimer = null;

function stopSyncPolling() {
  if (syncPollTimer) {
    clearInterval(syncPollTimer);
    syncPollTimer = null;
  }
}

async function triggerSync() {
  try {
    syncSpinIcon.classList.add("animate-spin");
    await apiRequest("/api/crawler/sync", { method: "POST" });
    await updateCrawlerStatus();
    // Poll until the background crawl finishes
    stopSyncPolling();
    syncPollTimer = setInterval(async () => {
      try {
        const s = await apiRequest("/api/crawler/status");
        await updateCrawlerStatus();
        if (!s.is_running) {
          stopSyncPolling();
          await loadCrawledPages();
        }
      } catch (err) {
        stopSyncPolling();
        console.error("Sync status polling failed:", err);
      }
    }, 2000);
  } catch (err) {
    syncSpinIcon.classList.remove("animate-spin");
    alert("Sync failed: " + err.message);
  }
}

quickSyncBtn.addEventListener("click", triggerSync);
modalSyncNowBtn.addEventListener("click", triggerSync);

async function loadCrawledPages() {
  try {
    const res = await apiRequest("/api/crawler/pages");
    crawledPagesList.innerHTML = "";
    if (res.pages.length === 0) {
      crawledPagesList.innerHTML = `<div class="text-center py-6 text-xs text-slate-500">No pages indexed yet. Click "Crawl & Sync Now" above.</div>`;
      return;
    }

    res.pages.forEach(p => {
      const row = document.createElement("div");
      row.className = "flex items-center justify-between p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 text-xs";
      row.innerHTML = `
        <div class="truncate mr-3">
          <div class="font-semibold text-slate-200 truncate">${escapeHtml(p.title)}</div>
          <a href="${escapeHtml(safeUrl(p.url))}" target="_blank" rel="noopener noreferrer" class="text-[10px] text-indigo-400 hover:underline truncate block">${escapeHtml(p.url)}</a>
        </div>
        <div class="flex items-center space-x-2 shrink-0">
          <span class="px-2 py-0.5 rounded-md text-[10px] font-medium bg-slate-800 text-slate-300">
            ${p.chunk_count} chunks
          </span>
          <span class="px-2 py-0.5 rounded-md text-[10px] font-medium ${
            p.status === 'updated' ? 'bg-amber-950/60 text-amber-400 border border-amber-800/40' :
            p.status === 'new' ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40' :
            'bg-slate-800 text-slate-400'
          }">
            ${escapeHtml(p.status)}
          </span>
        </div>
      `;
      crawledPagesList.appendChild(row);
    });
  } catch (err) {
    console.error("Failed to load crawled pages:", err);
  }
}

openCrawlerBtn.addEventListener("click", async () => {
  crawlerModal.classList.remove("hidden");
  await updateCrawlerStatus();
  await loadCrawledPages();
});

closeCrawlerModal.addEventListener("click", () => {
  crawlerModal.classList.add("hidden");
});

// --- Settings Modal ---
openConfigBtn.addEventListener("click", async () => {
  configModal.classList.remove("hidden");
  try {
    const cfg = await apiRequest("/api/config");
    configProvider.value = cfg.llm_provider || "local";
    configGroqKey.placeholder = cfg.has_groq_key ? "Saved (leave blank to keep)" : "gsk_...";
    configGeminiKey.placeholder = cfg.has_gemini_key ? "Saved (leave blank to keep)" : "AIzaSy...";
    configOpenaiKey.placeholder = cfg.has_openai_key ? "Saved (leave blank to keep)" : "sk-...";
  } catch (err) {
    console.error("Failed to load settings:", err);
  }
});

closeConfigModal.addEventListener("click", () => {
  configModal.classList.add("hidden");
});

configForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    llm_provider: configProvider.value,
  };
  if (configGroqKey.value.trim()) payload.groq_api_key = configGroqKey.value.trim();
  if (configGeminiKey.value.trim()) payload.gemini_api_key = configGeminiKey.value.trim();
  if (configOpenaiKey.value.trim()) payload.openai_api_key = configOpenaiKey.value.trim();

  try {
    await apiRequest("/api/config", { method: "POST", body: payload });
    configModal.classList.add("hidden");
    configGroqKey.value = "";
    configGeminiKey.value = "";
    configOpenaiKey.value = "";
    await refreshModelBadge();
    alert("Settings saved successfully!");
  } catch (err) {
    alert("Failed to save settings: " + err.message);
  }
});

async function refreshModelBadge() {
  try {
    const cfg = await apiRequest("/api/config");
    modelBadge.textContent = `Model: ${(cfg.llm_provider || "local").toUpperCase()}`;
  } catch (err) {
    console.error("Failed to load model info:", err);
  }
}

// --- Utilities ---
function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Only allow http(s) links, so a crawled "javascript:" URL can never become clickable.
function safeUrl(url) {
  return /^https?:\/\//i.test(url || "") ? url : "#";
}

function setupEventListeners() {
  // Mobile sidebar toggle
  const toggleSidebarBtn = document.getElementById("toggleSidebarBtn");
  const sidebar = document.getElementById("sidebar");
  if (toggleSidebarBtn) {
    toggleSidebarBtn.addEventListener("click", () => {
      sidebar.classList.toggle("-translate-x-full");
    });
  }
}

// Start app
window.addEventListener("DOMContentLoaded", initApp);
