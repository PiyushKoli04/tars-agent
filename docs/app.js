(() => {
  "use strict";

  const API_BASE = "https://api.github.com";
  const TOKEN_KEY = "ncs.token";
  const REPO_KEY = "ncs.repo";
  const BRANCH_KEY = "ncs.branch";
  const SETUP_KEY = "ncs.setup";
  const TAB_KEY = "ncs.tab";
  const CACHE_PREFIX = "ncs.cache.";
  const MAX_CAPTION = 2200;

  const CATEGORIES = [
    ["tech_ai", "Tech & AI", "tile-lavender"],
    ["business", "Business", "tile-amber"],
    ["science_space", "Science & Space", "tile-sky"],
    ["world", "World", "tile-pink"],
    ["sports", "Sports", "tile-amber"],
    ["health", "Health", "tile-sky"],
    ["entertainment", "Entertainment", "tile-pink"],
    ["environment", "Environment", "tile-lavender"],
  ];

  const STYLE_NAMES = [
    "Quiet Broadsheet",
    "Midnight Terminal",
    "Soft Editorial",
    "Bold Poster",
    "Newsprint Classic",
    "Swiss Grid",
    "Monochrome Minimal",
    "Magazine Cover",
    "Data Story",
    "Brutalist Type",
    "Warm Documentary",
    "Paper Cut",
    "Modern Luxe",
    "Zine Collage",
    "Blueprint",
    "Tabloid Sport",
    "Financial Daily",
    "Retro Print",
    "Cosmic Dark",
    "Gallery White",
  ];

  const STYLE_TONES = ["tile-lavender", "tile-amber", "tile-sky", "tile-pink"];
  const DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"];
  const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const PRESETS = [
    { id: "05:30", name: "Early edition", note: "Start the day ahead of the noise." },
    { id: "12:30", name: "Midday brief", note: "A quick catch-up over lunch." },
    { id: "18:30", name: "Evening wrap", note: "Close the day fully informed." },
    { id: "custom", name: "Your own times", note: "Choose up to three 30-minute slots." },
  ];
  const LLM_META = {
    nvidia: ["Nvidia NIM", "Free developer credits. OpenAI-compatible."],
    opencode: ["OpenCode Zen", "Free coding models via the Zen endpoint."],
    gemini: ["Google Gemini", "Free tier with a generous daily quota."],
    groq: ["Groq", "Very fast free tier."],
  };
  const IMAGE_META = {
    unsplash: ["Unsplash", "Best editorial quality. Needs a free Access Key."],
    article: ["Article photo", "Uses the story's own lead image when available."],
    pixabay: ["Pixabay", "Free stock photos. Needs a free API key."],
    wikimedia: ["Wikimedia Commons", "Free and keyless. Quality varies."],
    generated: ["Generated background", "Built in, always available as the final fallback."],
  };
  const ACTIVE_STAGES = new Set(["queued", "fetching", "writing", "designing", "rendering", "posting"]);
  const RUN_STEPS = [
    { label: "Fetching fresh stories", stage: "fetching" },
    { label: "Writing headline and caption", stage: "writing" },
    { label: "Designing the card", stage: "designing" },
    { label: "Rendering image", stage: "rendering" },
    { label: "Publishing / review", stage: "posting" },
  ];
  const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map(([id, label]) => [id, label]));
  const DEFAULT_CONFIG = {
    timezone: "Asia/Kolkata",
    posting_paused: false,
    mode: "approve",
    schedule: [
      { id: "slot_morning", time: "05:30", days: [0, 1, 2, 3, 4, 5, 6], enabled: true, mode: "global", topic_override: "" },
      { id: "slot_evening", time: "18:30", days: [0, 1, 2, 3, 4, 5, 6], enabled: true, mode: "global", topic_override: "" },
    ],
    topics: Object.fromEntries(CATEGORIES.map(([id]) => [id, true])),
    prefer_keywords: [],
    mute_keywords: [],
    style: "auto",
    avoid_repeat_style: true,
    brand: {
      name: "NewsCard Studio",
      handle: "@newscardstudio",
      accent_color: "#B7A0FF",
      footer_text: "Daily signals, beautifully told.",
      logo_path: "",
    },
    llm: { order: ["nvidia", "opencode", "gemini", "groq"], disabled: [] },
    image: {
      order: ["unsplash", "article", "pixabay", "wikimedia", "generated"],
      disabled: [],
      prefer_article_photo: false,
      show_credit: true,
    },
    max_posts_per_day: 2,
    news: { max_age_hours: 24 },
  };

  const state = {
    token: "",
    owner: "",
    name: "",
    branch: "main",
    setup: false,
    screen: "loading",
    activeTab: "home",
    config: null,
    queue: null,
    history: null,
    status: null,
    lastRunId: null,
    observedActive: false,
    awaiting: null,
    awaitingTimer: null,
    dispatching: false,
    busyIds: new Set(),
    polling: false,
    pollTimer: null,
    lastPollAt: 0,
    loading: true,
    cacheOnly: false,
    online: navigator.onLine,
    setupDraft: null,
    configSaveTimer: null,
    configSaving: false,
    configDirty: false,
    configMessage: "Settings updated.",
    queueLock: Promise.resolve(),
    historyLock: Promise.resolve(),
    runSheet: null,
    sheetController: null,
    viewerController: null,
    logoVersion: 0,
    refreshing: null,
    lastRenderScroll: 0,
  };

  const view = document.getElementById("view");
  const shell = document.getElementById("shell");
  const onboarding = document.getElementById("onboarding");
  const offlineBanner = document.getElementById("offline-banner");
  const toastRegion = document.getElementById("toast-region");

  const deepClone = (value) => JSON.parse(JSON.stringify(value));
  const $ = (id) => document.getElementById(id);

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));
  }

  function safeUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
    } catch {
      return "";
    }
  }

  function icon(name, className = "") {
    return `<svg class="icon ${className}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function basename(value) {
    const text = String(value || "").split("?")[0].split("#")[0];
    return text.split(/[\\/]/).pop() || "";
  }

  function cardUrl(item) {
    const name = basename(item?.jpg || item?.png || "");
    if (!name) return "";
    const version = encodeURIComponent(item?.updated_at || item?.posted_at || item?.created_at || "");
    return `cards/${encodeURIComponent(name)}${version ? `?v=${version}` : ""}`;
  }

  function brandLogoUrl() {
    const path = String(state.config?.brand?.logo_path || "");
    if (!path) return "";
    const clean = path.replace(/^docs\//, "").replace(/^\/+/, "");
    if (!clean || clean.includes("..")) return "";
    return encodeURI(`${clean}${state.logoVersion ? `?v=${state.logoVersion}` : ""}`);
  }

  function repoLabel() {
    return state.owner && state.name ? `${state.owner}/${state.name}` : "";
  }

  function repoWebUrl(path = "") {
    if (!state.owner || !state.name) return "";
    return `https://github.com/${encodeURIComponent(state.owner)}/${encodeURIComponent(state.name)}${path}`;
  }

  function safeStoreGet(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function safeStoreSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      return false;
    }
    return true;
  }

  function safeStoreRemove(key) {
    try {
      localStorage.removeItem(key);
    } catch {
      return;
    }
  }

  function cacheKey(path) {
    return `${CACHE_PREFIX}${state.owner}/${state.name}#${state.branch}:${path}`;
  }

  function cacheRead(path) {
    try {
      const raw = localStorage.getItem(cacheKey(path));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch {
      return null;
    }
  }

  function cacheWrite(path, entry) {
    try {
      localStorage.setItem(cacheKey(path), JSON.stringify(entry));
    } catch {
      return;
    }
  }

  function cacheClear() {
    try {
      const keys = [];
      for (let index = 0; index < localStorage.length; index += 1) {
        const key = localStorage.key(index);
        if (key && key.startsWith(CACHE_PREFIX)) keys.push(key);
      }
      keys.forEach((key) => localStorage.removeItem(key));
    } catch {
      return;
    }
  }

  function cacheHasData() {
    return Boolean(cacheRead("data/config.json")?.data);
  }

  function encodePath(path) {
    return String(path).split("/").map(encodeURIComponent).join("/");
  }

  function bytesToBase64(bytes) {
    let binary = "";
    const chunk = 0x8000;
    for (let index = 0; index < bytes.length; index += chunk) {
      binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
    }
    return btoa(binary);
  }

  function encodeTextBase64(text) {
    return bytesToBase64(new TextEncoder().encode(text));
  }

  function decodeTextBase64(value) {
    const cleaned = String(value || "").replace(/\s/g, "");
    const binary = atob(cleaned);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return new TextDecoder().decode(bytes);
  }

  function timeToMinutes(value) {
    const match = /^(\d{1,2}):(\d{2})$/.exec(String(value || ""));
    if (!match) return 0;
    return (Number(match[1]) % 24) * 60 + Number(match[2]);
  }

  function minutesToTime(minutes) {
    const total = ((Number(minutes) % 1440) + 1440) % 1440;
    return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
  }

  function normalizeTime(value) {
    const minutes = timeToMinutes(value);
    return minutesToTime(Math.round(minutes / 30) * 30);
  }

  function formatTime12(value) {
    const minutes = timeToMinutes(value);
    const hour24 = Math.floor(minutes / 60);
    const minute = minutes % 60;
    const suffix = hour24 >= 12 ? "PM" : "AM";
    const hour = hour24 % 12 || 12;
    return { time: `${hour}:${pad(minute)}`, suffix };
  }

  function formatTime12Text(value) {
    const parts = formatTime12(value);
    return `${parts.time} ${parts.suffix}`;
  }

  function slotName(value) {
    const minutes = timeToMinutes(value);
    if (minutes < 11 * 60) return "Morning edition";
    if (minutes < 16 * 60) return "Midday brief";
    if (minutes < 21 * 60) return "Evening edition";
    return "Late edition";
  }

  function formatCount(value) {
    const number = Number(value) || 0;
    return new Intl.NumberFormat().format(number);
  }

  function formatDateTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }

  function timeAgo(value) {
    if (!value) return "just now";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "just now";
    const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
    if (seconds < 45) return "just now";
    if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))}m ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.round(seconds / 86400)}d ago`;
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
  }

  function zonedParts(date, timeZone) {
    try {
      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone,
        hourCycle: "h23",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        weekday: "short",
      });
      const parts = {};
      formatter.formatToParts(date).forEach((part) => {
        if (part.type !== "literal") parts[part.type] = part.value;
      });
      const weekdays = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
      return {
        year: Number(parts.year),
        month: Number(parts.month),
        day: Number(parts.day),
        hour: Number(parts.hour) % 24,
        minute: Number(parts.minute),
        weekday: weekdays[parts.weekday] ?? 0,
      };
    } catch {
      return {
        year: date.getFullYear(),
        month: date.getMonth() + 1,
        day: date.getDate(),
        hour: date.getHours(),
        minute: date.getMinutes(),
        weekday: (date.getDay() + 6) % 7,
      };
    }
  }

  function zonedTimeToDate(year, month, day, hour, minute, timeZone) {
    const desiredWall = Date.UTC(year, month - 1, day, hour, minute);
    let guess = desiredWall;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const parts = zonedParts(new Date(guess), timeZone);
      const representedWall = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute);
      const correction = desiredWall - representedWall;
      if (correction === 0) break;
      guess += correction;
    }
    return new Date(guess);
  }

  function nextScheduledSlot(config) {
    if (!config) return null;
    const timeZone = config.timezone || "Asia/Kolkata";
    const slots = (config.schedule || [])
      .filter((slot) => slot && slot.enabled !== false)
      .slice()
      .sort((a, b) => timeToMinutes(a.time) - timeToMinutes(b.time));
    if (!slots.length) return null;
    const now = new Date();
    const nowParts = zonedParts(now, timeZone);
    for (let offset = 0; offset <= 7; offset += 1) {
      const dayDate = new Date(Date.UTC(nowParts.year, nowParts.month - 1, nowParts.day + offset));
      const weekday = (dayDate.getUTCDay() + 6) % 7;
      for (const slot of slots) {
        if (!Array.isArray(slot.days) || slot.days.length !== 7) {
          if (!Array.isArray(slot.days) || !slot.days.includes(weekday)) continue;
        }
        const slotMinutes = timeToMinutes(slot.time);
        if (offset === 0 && slotMinutes <= nowParts.hour * 60 + nowParts.minute) continue;
        const when = zonedTimeToDate(
          dayDate.getUTCFullYear(),
          dayDate.getUTCMonth() + 1,
          dayDate.getUTCDate(),
          Math.floor(slotMinutes / 60),
          slotMinutes % 60,
          timeZone,
        );
        const dayDifference = Math.round(
          (Date.UTC(dayDate.getUTCFullYear(), dayDate.getUTCMonth(), dayDate.getUTCDate()) -
            Date.UTC(nowParts.year, nowParts.month - 1, nowParts.day)) / 86400000,
        );
        let dayLabel;
        if (dayDifference === 0) dayLabel = "Today";
        else if (dayDifference === 1) dayLabel = "Tomorrow";
        else if (dayDifference < 7) dayLabel = DAY_NAMES[weekday];
        else dayLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(when);
        return {
          slot,
          when,
          dayLabel,
          dayDifference,
          time: slot.time,
          day: weekday,
          mode: slot.mode && slot.mode !== "global" ? slot.mode : config.mode,
        };
      }
    }
    return null;
  }

  function countdownText(when) {
    if (!when) return "";
    const milliseconds = Math.max(0, when.getTime() - Date.now());
    const minutes = Math.ceil(milliseconds / 60000);
    if (minutes <= 1) return "in less than a minute";
    if (minutes < 60) return `in ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    if (hours < 24) return remainder ? `in ${hours}h ${remainder}m` : `in ${hours}h`;
    const days = Math.floor(hours / 24);
    const hourRemainder = hours % 24;
    return hourRemainder ? `in ${days}d ${hourRemainder}h` : `in ${days}d`;
  }

  function weekStripData(config) {
    const timeZone = config?.timezone || "Asia/Kolkata";
    const now = new Date();
    const parts = zonedParts(now, timeZone);
    const mondayOffset = parts.weekday;
    const today = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
    const items = [];
    for (let index = 0; index < 7; index += 1) {
      const date = new Date(today.getTime() + (index - mondayOffset) * 86400000);
      const weekday = index;
      const scheduled = (config?.schedule || []).some(
        (slot) => slot && slot.enabled !== false && Array.isArray(slot.days) && slot.days.includes(weekday),
      );
      items.push({
        label: DAY_LABELS[index],
        dayNumber: date.getUTCDate(),
        isToday: date.getTime() === today.getTime(),
        scheduled,
      });
    }
    return items;
  }

  function greetingFor(config) {
    const timeZone = config?.timezone || "Asia/Kolkata";
    const hour = zonedParts(new Date(), timeZone).hour;
    if (hour < 12) return "Good morning";
    if (hour < 17) return "Good afternoon";
    return "Good evening";
  }

  function longDateFor(config) {
    const timeZone = config?.timezone || "Asia/Kolkata";
    try {
      return new Intl.DateTimeFormat("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
        timeZone,
      }).format(new Date());
    } catch {
      return new Intl.DateTimeFormat("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
      }).format(new Date());
    }
  }

  function statusIsActive(status) {
    return Boolean(status && ACTIVE_STAGES.has(status.stage));
  }

  function effectiveStatus() {
    if (state.awaiting) {
      return {
        run_id: null,
        action: state.awaiting.action,
        stage: "queued",
        step: 0,
        dry_run: Boolean(state.awaiting.dryRun),
        message: state.awaiting.message || "Run queued. Waiting for GitHub Actions to start.",
        awaiting: true,
      };
    }
    return state.status || null;
  }

  function runIsBusy() {
    return state.dispatching || Boolean(state.awaiting) || statusIsActive(effectiveStatus());
  }

  function runStatusView() {
    const status = effectiveStatus();
    if (state.awaiting) return { state: "running", label: "Queued" };
    if (!status || status.stage === "idle" || !status.run_id) return { state: "idle", label: "Idle" };
    if (statusIsActive(status)) return { state: "running", label: "Working" };
    if (status.stage === "failed") return { state: "failed", label: "Failed" };
    const updated = Date.parse(status.updated_at || "");
    if (Number.isFinite(updated) && Date.now() - updated < 10 * 60 * 1000) {
      return { state: "done", label: "Done" };
    }
    return { state: "idle", label: "Idle" };
  }

  function queueItems() {
    const items = state.queue?.items;
    return Array.isArray(items) ? items.filter((item) => item && typeof item === "object") : [];
  }

  function historyPosts() {
    const posts = state.history?.posts;
    return Array.isArray(posts) ? posts.filter((item) => item && typeof item === "object") : [];
  }

  function queueItemById(id) {
    return queueItems().find((item) => item.id === id) || null;
  }

  function historyItemById(id) {
    return historyPosts().find((item) => item.id === id) || null;
  }

  function providerEnabled(config, group, provider) {
    const disabled = config?.[group]?.disabled;
    return !Array.isArray(disabled) || !disabled.includes(provider);
  }

  function topicCount(config) {
    return CATEGORIES.filter(([id]) => Boolean(config?.topics?.[id])).length;
  }

  function styleDisplay(config) {
    const value = config?.style;
    if (value === "auto" || value === null || value === undefined) return "Auto style";
    const number = Number(value);
    return STYLE_NAMES[number - 1] ? `${number}. ${STYLE_NAMES[number - 1]}` : "Auto style";
  }

  function isValidRepoPart(value) {
    return /^[A-Za-z0-9_.-]+$/.test(String(value || ""));
  }

  function splitRepo(value) {
    const cleaned = String(value || "")
      .trim()
      .replace(/^https?:\/\/github\.com\//i, "")
      .replace(/\.git$/i, "")
      .replace(/^\/+|\/+$/g, "");
    const pieces = cleaned.split("/");
    if (pieces.length !== 2) return null;
    if (!isValidRepoPart(pieces[0]) || !isValidRepoPart(pieces[1])) return null;
    return { owner: pieces[0], name: pieces[1] };
  }

  class ApiError extends Error {
    constructor(status, message, details = "") {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.details = details;
    }
  }

  async function apiRequest(path, options = {}) {
    const method = options.method || "GET";
    const token = options.token ?? state.token;
    const headers = {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(options.headers || {}),
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
        cache: "no-store",
      });
    } catch {
      throw new ApiError(0, "Could not reach GitHub. Check your connection and try again.");
    }
    if (response.status === 304) {
      return { status: 304, data: null, etag: response.headers.get("etag") };
    }
    if (response.status === 204) {
      return { status: 204, data: null, etag: response.headers.get("etag") };
    }
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }
    if (!response.ok) {
      const detail = data?.message || response.statusText || "GitHub request failed.";
      let message = detail;
      if (response.status === 401) {
        message = "GitHub rejected the token. Reconnect with a valid fine-grained token.";
      } else if (response.status === 403 && response.headers.get("x-ratelimit-remaining") === "0") {
        message = "GitHub API rate limit reached. Try again after the hour resets.";
      } else if (response.status === 403) {
        message = "The token does not have permission for this action. Check Contents and Actions write access.";
      } else if (response.status === 404) {
        message = "Not found. Check the repo name, branch, and token access.";
      } else if (response.status === 409) {
        message = "The file changed on GitHub. Refresh and try again.";
      } else if (response.status === 422) {
        message = detail === "sha wasn't supplied." ? "The file changed on GitHub. Refreshing and retrying now." : detail;
      }
      throw new ApiError(response.status, message, detail);
    }
    return { status: response.status, data, etag: response.headers.get("etag") };
  }

  function repoApi(suffix) {
    return `/repos/${encodeURIComponent(state.owner)}/${encodeURIComponent(state.name)}${suffix}`;
  }

  function contentsApi(path, branch, auth) {
    const owner = auth?.owner || state.owner;
    const name = auth?.name || state.name;
    const ref = auth?.branch || branch || state.branch;
    return `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/contents/${encodePath(path)}?ref=${encodeURIComponent(ref)}`;
  }

  function authMatchesState(auth) {
    const token = auth?.token || state.token;
    const owner = auth?.owner || state.owner;
    const name = auth?.name || state.name;
    const branch = auth?.branch || state.branch;
    return Boolean(state.token && token === state.token && owner === state.owner && name === state.name && branch === state.branch);
  }

  async function fetchFile(path, options = {}) {
    const auth = options.auth || null;
    const force = Boolean(options.force);
    const cacheable = authMatchesState(auth);
    const cached = cacheable ? cacheRead(path) : null;
    const headers = {};
    if (!force && cached?.etag) headers["If-None-Match"] = cached.etag;
    const response = await apiRequest(contentsApi(path, options.branch, auth), {
      headers,
      token: auth?.token ?? state.token,
    });
    if (response.status === 304) {
      if (cached) return { ...cached, fromCache: true };
      return fetchFile(path, { ...options, force: true });
    }
    const meta = response.data;
    if (!meta || typeof meta !== "object") throw new ApiError(500, "GitHub returned an empty file response.");
    if (!meta.content) throw new ApiError(500, "This file is too large for the GitHub contents API.");
    const decoded = decodeTextBase64(meta.content);
    let data;
    try {
      data = JSON.parse(decoded);
    } catch {
      throw new ApiError(500, "This file is not valid JSON.");
    }
    const entry = {
      data,
      sha: meta.sha,
      etag: response.etag || null,
      savedAt: Date.now(),
      path: meta.path || path,
    };
    if (cacheable) cacheWrite(path, entry);
    return entry;
  }

  async function loadFile(path, options = {}) {
    try {
      return await fetchFile(path, options);
    } catch (error) {
      if (options.missing !== undefined && error.status === 404) {
        return { data: deepClone(options.missing), sha: null, etag: null, missing: true };
      }
      const cacheable = authMatchesState(options.auth);
      const cached = cacheable ? cacheRead(path) : null;
      const canUseCache =
        cached &&
        (error.status === 0 || error.status === 403 || error.status === 404 || error.status >= 500);
      if (canUseCache) {
        state.cacheOnly = true;
        return { ...cached, fromCache: true };
      }
      throw error;
    }
  }

  async function fileSha(path, options = {}) {
    try {
      const response = await apiRequest(contentsApi(path, options.branch, options.auth), {
        token: options.auth?.token ?? state.token,
      });
      return response.data?.sha || null;
    } catch (error) {
      if (error.status === 404) return null;
      throw error;
    }
  }

  async function putFile(path, content, message, options = {}) {
    const auth = options.auth || null;
    const branch = options.branch || auth?.branch || state.branch;
    let sha = options.sha || null;
    const baseBody = {
      message,
      content,
      branch,
      ...(sha ? { sha } : {}),
    };
    let response;
    try {
      response = await apiRequest(contentsApi(path, branch, auth), {
        method: "PUT",
        body: baseBody,
        token: auth?.token ?? state.token,
      });
    } catch (error) {
      if ((error.status === 409 || error.status === 422) && !options.retried) {
        const latestSha = await fileSha(path, options);
        const retryBody = { message, content, branch, ...(latestSha ? { sha: latestSha } : {}) };
        response = await apiRequest(contentsApi(path, branch, auth), {
          method: "PUT",
          body: retryBody,
          token: auth?.token ?? state.token,
        });
        sha = latestSha;
      } else {
        throw error;
      }
    }
    const newSha = response.data?.content?.sha || sha || null;
    if (authMatchesState(auth)) {
      cacheWrite(path, { data: null, sha: newSha, etag: null, savedAt: Date.now(), path });
    }
    return { sha: newSha };
  }

  async function putJsonFile(path, data, message, options = {}) {
    const text = `${JSON.stringify(data, null, 2)}\n`;
    const result = await putFile(path, encodeTextBase64(text), message, options);
    if (authMatchesState(options.auth)) {
      const cached = cacheRead(path);
      cacheWrite(path, {
        data: deepClone(data),
        sha: result.sha || cached?.sha || null,
        etag: null,
        savedAt: Date.now(),
        path,
      });
    }
    return result;
  }

  async function dispatchWorkflow(action, options = {}) {
    if (!navigator.onLine) throw new ApiError(0, "You are offline. Reconnect before starting a run.");
    const inputs = {
      action,
      topic: options.topic || "",
      style: options.style ? String(options.style) : "",
      queue_id: options.queueId || "",
      dry_run: options.dryRun ? "true" : "false",
    };
    await apiRequest(repoApi("/actions/workflows/tick.yml/dispatches"), {
      method: "POST",
      body: { ref: state.branch, inputs },
    });
  }

  function friendlyError(error) {
    if (error instanceof ApiError) return error.message;
    if (error?.message) return error.message;
    return "Something went wrong. Please try again.";
  }

  function toast(message, options = {}) {
    const element = document.createElement("div");
    element.className = "toast";
    element.setAttribute("role", "status");
    const text = document.createElement("span");
    text.textContent = message;
    element.appendChild(text);
    let timer = null;
    const dismiss = () => {
      if (timer) clearTimeout(timer);
      element.remove();
    };
    if (options.actionLabel && typeof options.onAction === "function") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "toast-action";
      button.textContent = options.actionLabel;
      button.addEventListener("click", () => {
        dismiss();
        try {
          options.onAction();
        } catch {
          return;
        }
      });
      element.appendChild(button);
    }
    if (options.closable !== false) {
      const close = document.createElement("button");
      close.type = "button";
      close.className = "toast-close";
      close.setAttribute("aria-label", "Dismiss notification");
      close.innerHTML = icon("close");
      close.addEventListener("click", dismiss);
      element.appendChild(close);
    }
    toastRegion.appendChild(element);
    while (toastRegion.children.length > 3) toastRegion.firstElementChild?.remove();
    timer = setTimeout(dismiss, options.duration || (options.actionLabel ? 7000 : 4200));
    return dismiss;
  }

  let modalFocusReturn = null;

  function trapKeydown(event, container, close) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      container.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => element.getClientRects().length > 0);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function closeSheet() {
    if (!state.sheetController) return;
    const controller = state.sheetController;
    state.sheetController = null;
    document.removeEventListener("keydown", controller.keyHandler);
    controller.backdrop.remove();
    controller.sheet.classList.remove("open");
    setTimeout(() => controller.sheet.remove(), 220);
    document.removeEventListener("keydown", controller.keyHandler);
    if (controller.onClose) controller.onClose();
    if (state.runSheet === controller) state.runSheet = null;
    if (modalFocusReturn && document.contains(modalFocusReturn)) {
      modalFocusReturn.focus({ preventScroll: true });
      modalFocusReturn = null;
    }
  }

  function closeViewer() {
    if (!state.viewerController) return;
    const controller = state.viewerController;
    state.viewerController = null;
    document.removeEventListener("keydown", controller.keyHandler);
    controller.element.remove();
    if (controller.onClose) controller.onClose();
    if (modalFocusReturn && document.contains(modalFocusReturn)) {
      modalFocusReturn.focus({ preventScroll: true });
      modalFocusReturn = null;
    }
  }

  function openSheet(options = {}) {
    closeSheet();
    closeViewer();
    modalFocusReturn = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    const sheet = document.createElement("section");
    sheet.className = `sheet ${options.className || ""}`.trim();
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-labelledby", "sheet-title");
    sheet.innerHTML = `
      <div class="sheet-handle-wrap" data-sheet-handle>
        <div class="sheet-handle"></div>
      </div>
      <div class="sheet-head">
        <div>
          <h2 id="sheet-title">${esc(options.title || "")}</h2>
          ${options.subtitle ? `<p>${esc(options.subtitle)}</p>` : ""}
        </div>
        <button class="sheet-close" type="button" aria-label="Close" data-sheet-close>${icon("close")}</button>
      </div>
      <div class="sheet-body">${options.body || ""}</div>
      ${options.actions?.length ? '<div class="sheet-actions"></div>' : ""}
    `;
    const root = $("sheet-root");
    root.appendChild(backdrop);
    root.appendChild(sheet);
    const actionsEl = sheet.querySelector(".sheet-actions");
    if (actionsEl && options.actions?.length) {
      options.actions.forEach((action) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `btn ${action.className || "btn-primary"}`;
        button.textContent = action.label;
        if (action.disabled) button.disabled = true;
        button.addEventListener("click", async () => {
          if (button.dataset.busy) return;
          button.dataset.busy = "1";
          const original = button.textContent;
          try {
            const result = action.onClick?.();
            if (result && typeof result.then === "function") {
              button.textContent = action.busyLabel || "Working...";
              button.disabled = true;
              await result;
            }
          } catch (error) {
            toast(friendlyError(error));
          } finally {
            if (document.contains(button)) {
              button.textContent = original;
              button.disabled = false;
              delete button.dataset.busy;
            }
          }
        });
        actionsEl.appendChild(button);
      });
    }
    const close = () => closeSheet();
    backdrop.addEventListener("click", close);
    sheet.querySelector("[data-sheet-close]")?.addEventListener("click", close);
    const keyHandler = (event) => trapKeydown(event, sheet, close);
    document.addEventListener("keydown", keyHandler);
    const controller = { sheet, backdrop, actionsEl, close, onClose: options.onClose, keyHandler };
    state.sheetController = controller;
    const handleWrap = sheet.querySelector("[data-sheet-handle]");
    let startY = null;
    let currentY = 0;
    handleWrap.addEventListener("touchstart", (event) => {
      startY = event.touches[0]?.clientY ?? null;
      currentY = 0;
      sheet.classList.add("dragging");
    }, { passive: true });
    handleWrap.addEventListener("touchmove", (event) => {
      if (startY === null) return;
      currentY = Math.max(0, (event.touches[0]?.clientY ?? startY) - startY);
      sheet.style.transform = `translate(-50%, ${currentY}px)`;
    }, { passive: true });
    handleWrap.addEventListener("touchend", () => {
      sheet.classList.remove("dragging");
      if (currentY > 95) close();
      else sheet.style.transform = "";
      startY = null;
      currentY = 0;
    });
    options.onMount?.(sheet, controller, close);
    requestAnimationFrame(() => {
      backdrop.classList.add("open");
      sheet.classList.add("open");
      const focusTarget = sheet.querySelector("[data-autofocus]") || sheet.querySelector("[data-sheet-close]");
      focusTarget?.focus({ preventScroll: true });
    });
    return controller;
  }

  function openViewer(options = {}) {
    closeSheet();
    closeViewer();
    modalFocusReturn = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const element = document.createElement("section");
    element.className = "viewer";
    element.setAttribute("role", "dialog");
    element.setAttribute("aria-modal", "true");
    element.setAttribute("aria-labelledby", "viewer-title");
    element.innerHTML = `
      <div class="viewer-head">
        <h2 id="viewer-title">${esc(options.title || "")}</h2>
        <button class="sheet-close" type="button" aria-label="Close" data-viewer-close>${icon("close")}</button>
      </div>
      ${options.body || ""}
    `;
    $("viewer-root").appendChild(element);
    const close = () => closeViewer();
    element.querySelector("[data-viewer-close]")?.addEventListener("click", close);
    const keyHandler = (event) => trapKeydown(event, element, close);
    document.addEventListener("keydown", keyHandler);
    const controller = { element, close, onClose: options.onClose, keyHandler };
    state.viewerController = controller;
    options.onMount?.(element, close);
    element.querySelector("[data-viewer-close]")?.focus({ preventScroll: true });
    return controller;
  }

  function openConfirm(options) {
    return openSheet({
      title: options.title,
      subtitle: options.subtitle || "",
      body: `<p class="small muted" style="line-height:1.6">${esc(options.body || "")}</p>`,
      actions: [
        {
          label: options.cancelLabel || "Cancel",
          className: "btn-soft",
          onClick: () => closeSheet(),
        },
        {
          label: options.confirmLabel || "Confirm",
          className: options.danger ? "btn-danger-solid" : "btn-primary",
          onClick: async () => {
            closeSheet();
            await options.onConfirm?.();
          },
        },
      ],
      onMount: (sheet) => {
        const buttons = sheet.querySelectorAll(".sheet-actions .btn");
        if (buttons[1]) buttons[1].setAttribute("data-autofocus", "");
      },
    });
  }

  function setOnline(isOnline) {
    state.online = isOnline;
    offlineBanner.hidden = isOnline;
    document.body.classList.toggle("offline", !isOnline);
    if (isOnline) state.cacheOnly = false;
  }

  window.addEventListener("online", () => {
    setOnline(true);
    toast("Back online. Refreshing your newsroom.");
    if (state.screen === "app") {
      refreshAll({ force: true }).catch(() => {});
      pollStatus(true);
    }
  });

  window.addEventListener("offline", () => {
    setOnline(false);
    toast("You are offline. Showing the last saved data.");
  });

  function mergeConfig(raw) {
    const merged = { ...deepClone(DEFAULT_CONFIG), ...(raw && typeof raw === "object" ? raw : {}) };
    merged.brand = { ...DEFAULT_CONFIG.brand, ...(raw?.brand || {}) };
    merged.llm = { ...DEFAULT_CONFIG.llm, ...(raw?.llm || {}) };
    merged.image = { ...DEFAULT_CONFIG.image, ...(raw?.image || {}) };
    merged.news = { ...DEFAULT_CONFIG.news, ...(raw?.news || {}) };
    merged.topics = { ...DEFAULT_CONFIG.topics, ...(raw?.topics || {}) };
    if (!Array.isArray(merged.schedule)) merged.schedule = deepClone(DEFAULT_CONFIG.schedule);
    if (!Array.isArray(merged.prefer_keywords)) merged.prefer_keywords = [];
    if (!Array.isArray(merged.mute_keywords)) merged.mute_keywords = [];
    if (!Array.isArray(merged.llm.order)) merged.llm.order = [...DEFAULT_CONFIG.llm.order];
    if (!Array.isArray(merged.llm.disabled)) merged.llm.disabled = [];
    if (!Array.isArray(merged.image.order)) merged.image.order = [...DEFAULT_CONFIG.image.order];
    if (!Array.isArray(merged.image.disabled)) merged.image.disabled = [];
    return merged;
  }

  function hydrateFromCache() {
    const configEntry = cacheRead("data/config.json");
    if (!configEntry?.data) return false;
    state.config = mergeConfig(configEntry.data);
    state.queue = cacheRead("data/queue.json")?.data || { items: [] };
    state.history = cacheRead("data/history.json")?.data || { posts: [], used_photos: [], meta: {} };
    state.status = cacheRead("data/status.json")?.data || null;
    state.loading = false;
    if (state.status?.run_id) state.lastRunId = state.status.run_id;
    return true;
  }

  async function refreshAll(options = {}) {
    if (state.refreshing) return state.refreshing;
    const run = (async () => {
      const configOptions = { force: Boolean(options.force) };
      const configFile = await loadFile("data/config.json", configOptions);
      const [queueFile, historyFile, statusFile] = await Promise.all([
        loadFile("data/queue.json", { missing: { items: [] } }),
        loadFile("data/history.json", { missing: { posts: [], used_photos: [], meta: {} } }),
        loadFile("data/status.json", { missing: { stage: "idle", message: "Waiting for the first run." } }),
      ]);
      state.config = mergeConfig(configFile.data);
      state.queue = queueFile.data?.items ? queueFile.data : { items: [] };
      state.history = historyFile.data?.posts ? historyFile.data : { posts: [], used_photos: [], meta: {} };
      state.status = statusFile.data || null;
      state.loading = false;
      if (options.initial) {
        state.lastRunId = state.status?.run_id || null;
        state.observedActive = false;
        state.activeSince = null;
        if (statusIsActive(state.status)) state.activeSince = Date.now();
      }
      refreshChrome();
      renderView({ preserveScroll: Boolean(options.preserveScroll) });
      return true;
    })();
    state.refreshing = run.catch((error) => {
      state.loading = false;
      if (error.status === 401) {
        showFatal(error.message, true);
      } else if (!state.config) {
        showFatal(friendlyError(error), false);
      } else {
        toast(friendlyError(error));
        refreshChrome();
        renderView({ preserveScroll: true });
      }
      return false;
    }).finally(() => {
      state.refreshing = null;
    });
    return state.refreshing;
  }

  async function refreshAfterRun() {
    try {
      const [queueFile, historyFile] = await Promise.all([
        loadFile("data/queue.json", { force: true, missing: { items: [] } }),
        loadFile("data/history.json", { force: true, missing: { posts: [], used_photos: [], meta: {} } }),
      ]);
      state.queue = queueFile.data?.items ? queueFile.data : { items: [] };
      state.history = historyFile.data?.posts ? historyFile.data : { posts: [], used_photos: [], meta: {} };
      state.busyIds.clear();
      refreshChrome();
      renderView({ preserveScroll: true });
    } catch (error) {
      toast(`Could not refresh the queue: ${friendlyError(error)}`);
    }
  }

  function showShell() {
    state.screen = "app";
    onboarding.hidden = true;
    shell.hidden = false;
    state.activeTab = ["home", "queue", "schedule", "settings"].includes(safeStoreGet(TAB_KEY))
      ? safeStoreGet(TAB_KEY)
      : "home";
  }

  function showFatal(message, reconnect) {
    state.screen = "fatal";
    shell.hidden = true;
    onboarding.hidden = false;
    onboarding.innerHTML = `
      <div class="onboard-top">
        <div class="onboard-brand">
          <div class="brand-avatar" aria-hidden="true">N</div>
          NewsCard Studio
        </div>
      </div>
      <div class="onboard-step">
        <p class="eyebrow">Connection problem</p>
        <h1>We could not open<br>your newsroom.</h1>
        <p class="lede">${esc(message)}</p>
        <div class="card">
          <p class="small muted" style="line-height:1.6">If the token expired or was replaced, reconnect. If this is a temporary network problem, retry.</p>
        </div>
        <div class="onboard-footer">
          <button class="btn btn-primary btn-block" type="button" data-onboard="retry">Retry</button>
          ${reconnect ? '<button class="help-link" type="button" data-onboard="reconnect" style="width:100%;justify-content:center">Reconnect GitHub</button>' : ""}
        </div>
      </div>
    `;
    window.scrollTo(0, 0);
  }

  function refreshChrome() {
    const config = state.config;
    const brand = config?.brand || DEFAULT_CONFIG.brand;
    $("topbar-name").textContent = brand.name || "NewsCard Studio";
    $("topbar-handle").textContent = brand.handle || "@newscardstudio";
    const avatar = $("brand-avatar");
    const logo = brandLogoUrl();
    if (logo) {
      avatar.innerHTML = `<img src="${esc(logo)}" alt="">`;
      avatar.querySelector("img")?.addEventListener("error", () => {
        avatar.textContent = (brand.name || "N").trim().charAt(0).toUpperCase() || "N";
      });
    } else {
      avatar.textContent = (brand.name || "N").trim().charAt(0).toUpperCase() || "N";
    }
    const run = runStatusView();
    const runButton = $("run-status");
    runButton.dataset.state = run.state;
    runButton.setAttribute("aria-label", `Run status: ${run.label}. Open run details.`);
    $("run-status-text").textContent = run.label;
    const badge = $("queue-badge");
    const pending = queueItems().length;
    badge.hidden = pending === 0;
    badge.textContent = pending > 99 ? "99+" : String(pending);
    document.querySelectorAll(".tab").forEach((tab) => {
      const selected = tab.dataset.tab === state.activeTab;
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.tabIndex = selected ? 0 : -1;
    });
  }

  function switchTab(tab) {
    if (!["home", "queue", "schedule", "settings"].includes(tab)) return;
    const changed = state.activeTab !== tab;
    state.activeTab = tab;
    safeStoreSet(TAB_KEY, tab);
    refreshChrome();
    renderView();
    if (changed) view.focus({ preventScroll: true });
    view.scrollTo({ top: 0, behavior: "auto" });
  }

  function renderView(options = {}) {
    if (state.screen !== "app") return;
    const scrollTop = options.preserveScroll ? view.scrollTop : 0;
    refreshChrome();
    if (state.loading && !state.config) {
      view.innerHTML = skeletonView();
      view.scrollTop = scrollTop;
      return;
    }
    if (!state.config) {
      view.innerHTML = `
        <div class="view-error">
          <strong>Configuration not loaded.</strong>
          <p style="margin-top:6px">Check the repository data folder, then try again.</p>
          <button class="btn btn-soft btn-sm" type="button" data-action="retry-load">Retry</button>
        </div>
      `;
      return;
    }
    let content = "";
    if (state.activeTab === "home") content = homeView();
    else if (state.activeTab === "queue") content = queueView();
    else if (state.activeTab === "schedule") content = scheduleView();
    else content = settingsView();
    view.innerHTML = `<div class="pull-indicator" id="pull-indicator">${icon("refresh")} Refreshing</div>${content}`;
    if (state.activeTab === "queue") bindQueueView();
    if (state.activeTab === "settings") bindSettingsView();
    view.scrollTop = scrollTop;
  }

  function renderViewPreserve() {
    renderView({ preserveScroll: true });
  }

  function skeletonView() {
    return `
      <div class="sk-title skeleton"></div>
      <div class="sk-hero skeleton"></div>
      <div class="sk-week skeleton"></div>
      <div class="sk-row skeleton"></div>
      <div class="sk-row skeleton"></div>
      <div class="sk-row skeleton"></div>
    `;
  }

  function postStatusPill(item) {
    if (!item) return "";
    if (item.status === "posted") return '<span class="status-pill status-posted">Posted</span>';
    if (item.status === "failed") return '<span class="status-pill status-failed">Failed</span>';
    if (item.status === "discarded") return '<span class="status-pill status-discarded">Discarded</span>';
    if (item.status === "dry_run" || item.dry_run) return '<span class="status-pill status-dry">Preview</span>';
    if (item.status === "pending") return '<span class="status-pill status-pending">Pending</span>';
    return '<span class="status-pill status-pending">Draft</span>';
  }

  function postImage(item, className = "post-thumb") {
    const source = cardUrl(item);
    if (!source) {
      return `<div class="${className === "post-thumb" ? "post-thumb-fallback" : "queue-thumb"}" aria-hidden="true">${icon("image")}</div>`;
    }
    return `<img class="${className}" src="${esc(source)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`;
  }

  function homeView() {
    const config = state.config;
    const next = nextScheduledSlot(config);
    const paused = Boolean(config.posting_paused);
    const busy = runIsBusy();
    const offline = !state.online;
    const nowMode = next?.mode || config.mode;
    const heroTone = paused
      ? "pastel-amber"
      : next
        ? timeToMinutes(next.time) < 660
          ? "pastel-amber"
          : timeToMinutes(next.time) < 960
            ? "pastel-sky"
            : timeToMinutes(next.time) < 1260
              ? "pastel-lavender"
              : "pastel-pink"
        : "pastel-lavender";
    const timeParts = next ? formatTime12(next.time) : null;
    const posts = historyPosts()
      .slice()
      .sort((a, b) => new Date(b.posted_at || b.created_at || 0) - new Date(a.posted_at || a.created_at || 0))
      .slice(0, 3);
    const week = weekStripData(config);
    const queueCountValue = queueItems().length;
    return `
      <header class="home-head">
        <p class="eyebrow">Your newsroom</p>
        <h1>${esc(greetingFor(config))}.</h1>
        <p>${esc(longDateFor(config))}${queueCountValue ? ` · ${queueCountValue} waiting` : ""}</p>
      </header>

      <section class="hero ${heroTone}${paused ? " hero-paused" : ""}" aria-label="Next scheduled post">
        <div class="hero-top">
          <span class="mode-badge">${paused ? "Paused" : nowMode === "auto" ? "Auto-post" : "Review first"}</span>
          <span class="tiny" style="font-weight:700">${esc(config.timezone.split("/").pop()?.replace(/_/g, " ") || "Local")}</span>
        </div>
        ${
          paused
            ? `<div class="hero-time">Posting paused</div>
               <div class="hero-meta">Your schedule is safe. Resume when you are ready.</div>
               <button class="resume-btn" type="button" data-action="resume-posting">${icon("play")} Resume posting</button>`
            : next
              ? `<div class="hero-time">${esc(timeParts.time)}<small>${esc(timeParts.suffix)}</small></div>
                 <div class="hero-meta">${esc(next.dayLabel)} · ${esc(countdownText(next.when))} · ${esc(slotName(next.time))}</div>`
              : `<div class="hero-time">—</div>
                 <div class="hero-meta">No active slots yet. Add one in Schedule.</div>`
        }
      </section>

      <div class="home-actions">
        <button class="btn btn-primary" type="button" data-action="post-now-sheet" ${paused || busy || offline ? "disabled" : ""}>
          ${icon("play")} Post now
        </button>
        <button class="btn btn-outline" type="button" data-action="preview" ${busy || offline ? "disabled" : ""}>
          ${icon("sparkle")} Preview
        </button>
      </div>

      <div class="section-head">
        <h2>This week</h2>
        <button class="link-btn" type="button" data-action="goto-schedule">Schedule ${icon("chevron-right")}</button>
      </div>
      <div class="week-strip" role="group" aria-label="This week's schedule">
        ${week.map((day, index) => `
          <button class="week-day${day.isToday ? " today" : ""}" type="button" data-action="goto-schedule" aria-label="${esc(DAY_NAMES[index])}${day.scheduled ? ", posting day" : ""}">
            <span class="dow">${esc(day.label)}</span>
            <span class="dom">${day.dayNumber}</span>
            ${day.scheduled ? '<span class="dot"></span>' : '<span style="height:4px"></span>'}
          </button>
        `).join("")}
      </div>

      <div class="section-head">
        <h2>Recent</h2>
        ${posts.length ? '<button class="link-btn" type="button" data-action="open-history">See all ' + icon("chevron-right") + "</button>" : ""}
      </div>
      ${posts.length ? `
        <div class="post-list">
          ${posts.map((post) => `
            <button class="post-row" type="button" data-action="open-post" data-id="${esc(post.id)}">
              ${postImage(post)}
              <span class="post-meta">
                <strong>${esc(post.headline || post.story_title || "Untitled card")}</strong>
                <span class="post-sub">${postStatusPill(post)}<span>${esc(timeAgo(post.posted_at || post.created_at))}</span></span>
              </span>
              ${icon("chevron-right")}
            </button>
          `).join("")}
        </div>
      ` : `
        <div class="empty-card">
          <div class="empty-illustration" aria-hidden="true"><span></span><span></span><span></span></div>
          <strong>Your first edition starts here.</strong>
          <p>Tap Preview to see a card without posting.</p>
        </div>
      `}
    `;
  }

  function queueView() {
    const items = queueItems().slice().sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
    const busy = runIsBusy();
    return `
      <div class="screen-head">
        <div>
          <p class="eyebrow">Review desk</p>
          <h1>Queue</h1>
        </div>
        <p>${items.length ? `${items.length} card${items.length === 1 ? "" : "s"} waiting` : "Nothing waiting"}</p>
      </div>
      ${items.length ? items.map((item) => queueCardView(item, busy)).join("") : `
        <div class="empty-card" style="margin-top:18px">
          <div class="empty-illustration" aria-hidden="true"><span></span><span></span><span></span></div>
          <strong>No cards waiting.</strong>
          <p>Previews and approvals land here. Generate one when you want a fresh card.</p>
          <button class="btn btn-primary" type="button" data-action="preview" style="margin-top:16px" ${busy || !state.online ? "disabled" : ""}>${icon("sparkle")} Preview a card</button>
        </div>
      `}
    `;
  }

  function queueCardView(item, busy) {
    const image = cardUrl(item);
    const isBusy = busy || state.busyIds.has(item.id);
    const failed = item.status === "failed" || Boolean(item.error);
    return `
      <div class="swipe-wrap" data-swipe-id="${esc(item.id)}">
        <div class="swipe-hint" aria-hidden="true"><span>Discard</span><span></span></div>
        <article class="queue-card" data-card-id="${esc(item.id)}">
          <button type="button" class="queue-open" data-action="open-card" data-id="${esc(item.id)}" aria-label="Open card preview">
            ${image ? `<img class="card-preview" src="${esc(image)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : `<div class="card-preview" style="display:grid;place-items:center">${icon("image")}</div>`}
          </button>
          <div class="queue-body">
            <div class="queue-meta">
              <span class="category-chip">${esc(CATEGORY_LABEL[item.category] || item.category_label || "News")}</span>
              <span class="style-chip">${esc(item.style_name || styleDisplay({ style: item.style }))}</span>
              ${item.dry_run ? '<span class="status-pill status-dry">Preview</span>' : ""}
            </div>
            <button type="button" class="queue-headline" style="text-align:left;width:100%" data-action="open-card" data-id="${esc(item.id)}">${esc(item.headline || item.story_title || "Untitled card")}</button>
            ${failed && item.error ? `<div class="queue-error">${esc(item.error)}</div>` : ""}
            <div class="queue-actions">
              <button class="btn btn-primary btn-block" type="button" data-action="publish-item" data-id="${esc(item.id)}" ${isBusy || !state.online ? "disabled" : ""}>
                ${failed ? "Try posting again" : "Approve & post"}
              </button>
              <div class="queue-secondary">
                <button class="btn btn-soft" type="button" data-action="regenerate-item" data-id="${esc(item.id)}" ${isBusy || !state.online ? "disabled" : ""}>${icon("refresh")} Regenerate</button>
                <button class="btn btn-soft" type="button" data-action="discard-item" data-id="${esc(item.id)}" ${!state.online ? "disabled" : ""}>${icon("trash")} Discard</button>
              </div>
            </div>
          </div>
        </article>
      </div>
    `;
  }

  function scheduleView() {
    const config = state.config;
    const next = nextScheduledSlot(config);
    const slots = (config.schedule || []).slice().sort((a, b) => timeToMinutes(a.time) - timeToMinutes(b.time));
    return `
      <div class="screen-head">
        <div>
          <p class="eyebrow">Automation</p>
          <h1>Schedule</h1>
        </div>
      </div>
      <p class="next-run">${icon("clock")}${next ? `Next: ${esc(next.dayLabel)} at ${esc(formatTime12Text(next.time))}` : "No active posting slots"}</p>

      <div class="settings-card">
        <div class="row">
          <div class="row-text">
            <strong>Posting</strong>
            <span>${config.posting_paused ? "Paused across all devices." : "Running on your schedule."}</span>
          </div>
          <button class="switch" type="button" role="switch" aria-checked="${config.posting_paused ? "false" : "true"}" aria-label="Posting enabled" data-action="toggle-paused"></button>
        </div>
        <div class="row" style="display:block;padding-top:12px">
          <div class="row-text" style="margin-bottom:8px">
            <strong>Default mode</strong>
            <span>Slots can inherit this or override it.</span>
          </div>
          <div class="segmented" role="group" aria-label="Default posting mode">
            <button type="button" data-action="set-mode" data-value="approve" aria-pressed="${config.mode === "approve"}">Review first</button>
            <button type="button" data-action="set-mode" data-value="auto" aria-pressed="${config.mode === "auto"}">Auto-post</button>
          </div>
          <div class="segment-note">
            <p>Review: cards wait in Queue for approval.</p>
            <p>Auto: posts at the slot time without asking.</p>
          </div>
        </div>
        <div class="row">
          <div class="row-text">
            <strong>Maximum posts per day</strong>
            <span>Extra due slots are skipped safely.</span>
          </div>
          <div class="stepper">
            <button type="button" data-action="max-posts" data-delta="-1" aria-label="One fewer post per day" ${config.max_posts_per_day <= 1 ? "disabled" : ""}>${icon("chevron-left")}</button>
            <span class="value">${Number(config.max_posts_per_day) || 1}</span>
            <button type="button" data-action="max-posts" data-delta="1" aria-label="One more post per day" ${config.max_posts_per_day >= 10 ? "disabled" : ""}>${icon("chevron-right")}</button>
          </div>
        </div>
        <div class="row">
          <div class="row-text">
            <strong>Time zone</strong>
            <span>${esc(config.timezone)}</span>
          </div>
          <span class="tiny muted">From your repo</span>
        </div>
      </div>

      ${slots.map((slot, index) => slotCardView(slot, index)).join("")}

      <div class="sticky-action">
        <button class="btn btn-outline btn-block" type="button" data-action="add-slot" ${!state.online ? "disabled" : ""}>${icon("plus")} Add a time slot</button>
      </div>
    `;
  }

  function slotCardView(slot, index) {
    const tone = ["pastel-lavender", "pastel-amber", "pastel-sky", "pastel-pink"][index % 4];
    const parts = formatTime12(slot.time);
    const mode = slot.mode || "global";
    return `
      <section class="slot-card ${tone}" aria-label="${esc(formatTime12Text(slot.time))} slot">
        <div class="slot-top">
          <div>
            <div class="slot-time">${esc(parts.time)}<small>${esc(parts.suffix)}</small></div>
            <div class="slot-sub">${esc(slotName(slot.time))} · ${slot.days?.length === 7 ? "Every day" : `${slot.days?.length || 0} days`}</div>
          </div>
          <button class="switch" type="button" role="switch" aria-label="Enable ${esc(formatTime12Text(slot.time))} slot" aria-checked="${slot.enabled !== false ? "true" : "false"}" data-action="toggle-slot" data-id="${esc(slot.id)}"></button>
        </div>
        <div class="day-row" role="group" aria-label="Days for ${esc(formatTime12Text(slot.time))}">
          ${DAY_LABELS.map((label, day) => `
            <button class="day-chip" type="button" data-action="toggle-slot-day" data-id="${esc(slot.id)}" data-day="${day}" aria-pressed="${slot.days?.includes(day) ? "true" : "false"}" aria-label="${esc(DAY_NAMES[day])}" ${slot.enabled === false ? "disabled" : ""}>${label}</button>
          `).join("")}
        </div>
        <div class="slot-bottom">
          <div class="slot-mode" role="group" aria-label="Mode for this slot">
            <button type="button" data-action="set-slot-mode" data-id="${esc(slot.id)}" data-value="global" aria-pressed="${mode === "global"}">Inherit</button>
            <button type="button" data-action="set-slot-mode" data-id="${esc(slot.id)}" data-value="auto" aria-pressed="${mode === "auto"}">Auto</button>
            <button type="button" data-action="set-slot-mode" data-id="${esc(slot.id)}" data-value="approve" aria-pressed="${mode === "approve"}">Review</button>
          </div>
          <button class="slot-edit" type="button" data-action="edit-slot" data-id="${esc(slot.id)}" aria-label="Edit or delete this slot">${icon("edit")}</button>
        </div>
      </section>
    `;
  }

  function styleGridHTML(selected, action = "choose-style") {
    return `
      <div class="style-grid" role="group" aria-label="Card styles">
        ${STYLE_NAMES.map((name, index) => `
          <button class="style-tile ${STYLE_TONES[index % 4]}" type="button" data-action="${action}" data-style="${index + 1}" aria-pressed="${Number(selected) === index + 1}">
            <span class="swatch"></span>
            <span>${index + 1}. ${esc(name)}</span>
          </button>
        `).join("")}
      </div>
    `;
  }

  function tagsHTML(keywords, list) {
    return (Array.isArray(keywords) ? keywords : []).map((word) => `
      <span class="tag">${esc(word)}
        <button type="button" data-action="remove-keyword" data-list="${list}" data-word="${esc(word)}" aria-label="Remove ${esc(word)}">${icon("close")}</button>
      </span>
    `).join("");
  }

  function settingsView() {
    const config = state.config;
    const status = state.status;
    const session = status?.ig_session || "unknown";
    const sessionLabel = session === "ok"
      ? "Connected"
      : session === "needs_refresh" || session === "refreshed"
        ? "Needs refresh"
        : "Not checked yet";
    const sessionClass = session === "ok" ? "status-posted" : session === "unknown" ? "status-pending" : "status-failed";
    const logo = brandLogoUrl();
    return `
      <div class="screen-head">
        <div>
          <p class="eyebrow">Control room</p>
          <h1>Settings</h1>
        </div>
      </div>

      <section class="settings-card">
        <h2>Brand</h2>
        <p class="hint">Appears on every card and in the top bar.</p>
        <div class="settings-inner">
          <div class="row">
            <div class="row-text"><strong>Logo</strong><span>Square PNG or JPG. Saved to the repo.</span></div>
            <div class="row-actions">
              ${logo ? `<img class="logo-preview" src="${esc(logo)}" alt="Brand logo" onerror="this.style.display='none'">` : '<div class="logo-preview" style="display:grid;place-items:center">' + icon("image") + "</div>"}
              <button class="btn btn-soft btn-sm" type="button" data-action="upload-logo" ${!state.online ? "disabled" : ""}>Upload</button>
            </div>
          </div>
          ${config.brand.logo_path ? `<button class="help-link" style="margin:0" type="button" data-action="remove-logo">Remove logo</button>` : ""}
          <input id="logo-file" type="file" accept="image/png,image/jpeg,image/webp" hidden>
          <div class="form-field">
            <label for="brand-name">Name</label>
            <input class="input" id="brand-name" type="text" maxlength="60" value="${esc(config.brand.name)}" autocomplete="organization">
          </div>
          <div class="form-field">
            <label for="brand-handle">Instagram handle</label>
            <input class="input" id="brand-handle" type="text" maxlength="40" value="${esc(config.brand.handle)}" autocomplete="off" autocapitalize="none" spellcheck="false">
          </div>
          <div class="form-field">
            <label for="brand-footer">Footer line</label>
            <input class="input" id="brand-footer" type="text" maxlength="100" value="${esc(config.brand.footer_text)}">
          </div>
          <div>
            <p class="form-field" style="margin-bottom:8px"><label>Accent</label></p>
            <div class="accent-row" role="group" aria-label="Brand accent colour">
              ${["#B7A0FF", "#FFBB5A", "#A9CCFF", "#FF9BF2", "#111111"].map((colour) => `
                <button class="accent-swatch" type="button" style="background:${colour}" data-action="set-accent" data-colour="${colour}" aria-label="Use ${colour}" aria-pressed="${config.brand.accent_color.toUpperCase() === colour}">
                  ${config.brand.accent_color.toUpperCase() === colour ? icon("check") : ""}
                </button>
              `).join("")}
            </div>
          </div>
          <button class="btn btn-primary btn-block" type="button" data-action="save-brand" ${!state.online ? "disabled" : ""}>Save brand details</button>
        </div>
      </section>

      <section class="settings-card">
        <h2>Topics</h2>
        <p class="hint">At least one topic must stay on. News is scored across the enabled mix.</p>
        <div class="settings-inner">
          <div class="topic-grid">
            ${CATEGORIES.map(([id, label, tone]) => `
              <button class="topic-choice ${tone}" type="button" data-action="toggle-topic" data-topic="${id}" aria-pressed="${Boolean(config.topics?.[id])}">
                <span>${esc(label)}</span>
                <span class="check">${config.topics?.[id] ? icon("check") : ""}</span>
              </button>
            `).join("")}
          </div>
        </div>
      </section>

      <section class="settings-card">
        <h2>Keywords</h2>
        <p class="hint">Prefer raises a story; mute removes it. Press Enter or use the plus button.</p>
        <div class="settings-inner">
          <div>
            <p class="form-field" style="margin-bottom:6px"><label>Prefer</label></p>
            <div class="tag-input">
              ${tagsHTML(config.prefer_keywords, "prefer")}
              <input type="text" maxlength="40" placeholder="e.g. open source" data-keyword-input="prefer" aria-label="Add preferred keyword">
              <button class="btn-icon" type="button" data-action="add-keyword" data-list="prefer" aria-label="Add preferred keyword">${icon("plus")}</button>
            </div>
          </div>
          <div>
            <p class="form-field" style="margin-bottom:6px"><label>Mute</label></p>
            <div class="tag-input">
              ${tagsHTML(config.mute_keywords, "mute")}
              <input type="text" maxlength="40" placeholder="e.g. celebrity" data-keyword-input="mute" aria-label="Add muted keyword">
              <button class="btn-icon" type="button" data-action="add-keyword" data-list="mute" aria-label="Add muted keyword">${icon("plus")}</button>
            </div>
          </div>
        </div>
      </section>

      <section class="settings-card">
        <h2>Style</h2>
        <p class="hint">Auto rotates to avoid repetition when possible.</p>
        <div class="settings-inner">
          <button class="chip" type="button" data-action="choose-style-auto" aria-pressed="${config.style === "auto"}" style="align-self:flex-start">${icon("sparkle")} Auto style</button>
          ${styleGridHTML(config.style === "auto" ? 0 : config.style)}
          <div class="row">
            <div class="row-text"><strong>Avoid repeating a style</strong><span>The next auto-picked style avoids the last one.</span></div>
            <button class="switch" type="button" role="switch" aria-checked="${config.avoid_repeat_style ? "true" : "false"}" aria-label="Avoid repeating styles" data-action="toggle-avoid-repeat"></button>
          </div>
        </div>
      </section>

      <section class="settings-card">
        <h2>Images</h2>
        <p class="hint">Tried in order. Generated is always the final safety net.</p>
        <div class="settings-inner">
          ${config.image.order.map((provider) => imageProviderRow(provider, config)).join("")}
          <div class="row">
            <div class="row-text"><strong>Prefer article image</strong><span>Jump the queue when the story has a strong lead photo.</span></div>
            <button class="switch" type="button" role="switch" aria-checked="${config.image.prefer_article_photo ? "true" : "false"}" aria-label="Prefer article image" data-action="toggle-image-pref"></button>
          </div>
          <div class="row">
            <div class="row-text"><strong>Show photo credit</strong><span>Unsplash credit is always included for licensing.</span></div>
            <button class="switch" type="button" role="switch" aria-checked="${config.image.show_credit ? "true" : "false"}" aria-label="Show photo credit" data-action="toggle-image-credit"></button>
          </div>
        </div>
      </section>

      <section class="settings-card">
        <h2>AI writers</h2>
        <p class="hint">This order is tried silently. Missing keys are skipped; the rule-based editor is the last resort.</p>
        <div class="settings-inner">
          ${config.llm.order.map((provider) => llmProviderRow(provider, config)).join("")}
        </div>
      </section>

      <section class="settings-card">
        <h2>Instagram</h2>
        <p class="hint">The dashboard never receives your Instagram password or session.</p>
        <div class="settings-inner">
          <div class="row">
            <div class="row-text"><strong>Session</strong><span>${session === "refreshed" ? "A run refreshed it. Update the secret." : "Stored as the IG_SESSION_JSON secret."}</span></div>
            <span class="status-pill ${sessionClass}">${esc(sessionLabel)}</span>
          </div>
          <div class="row">
            <div class="row-text"><strong>Secrets</strong><span>IG_SESSION_JSON is required for posting.</span></div>
            <a class="btn btn-soft btn-sm" href="${esc(repoWebUrl("/settings/secrets/actions"))}" target="_blank" rel="noopener">Open ${icon("external")}</a>
          </div>
          ${session !== "ok" ? '<div class="warning-note">Generate or refresh the session locally with <strong>python tools/get_session.py</strong>, then update IG_SESSION_JSON in GitHub secrets.</div>' : ""}
          <button class="help-link" type="button" data-action="session-help" style="margin:0">How to refresh your session</button>
        </div>
      </section>

      <section class="settings-card">
        <h2>Connection</h2>
        <p class="hint">Your fine-grained token stays in this browser only.</p>
        <div class="settings-inner">
          <div class="row">
            <div class="row-text"><strong>Repository</strong><span>${esc(repoLabel())} · ${esc(state.branch)}</span></div>
            <a class="btn btn-soft btn-sm" href="${esc(repoWebUrl(""))}" target="_blank" rel="noopener">GitHub ${icon("external")}</a>
          </div>
          <div class="row">
            <div class="row-text"><strong>Actions</strong><span>Runs, logs, and manual dispatch.</span></div>
            <a class="btn btn-soft btn-sm" href="${esc(repoWebUrl("/actions"))}" target="_blank" rel="noopener">Open ${icon("external")}</a>
          </div>
          <button class="btn btn-soft btn-block" type="button" data-action="test-connection" ${!state.online ? "disabled" : ""}>Test connection</button>
          <button class="btn btn-soft btn-block" type="button" data-action="clear-cache">Clear offline cache</button>
          <button class="btn btn-danger btn-block" type="button" data-action="disconnect">Disconnect GitHub</button>
        </div>
      </section>

      <section class="settings-card danger-zone">
        <h2>History</h2>
        <p class="hint">Clearing removes the dashboard record. Generated image files stay in the repo.</p>
        <button class="btn btn-danger btn-block" type="button" data-action="clear-history" ${!state.online ? "disabled" : ""} style="margin-top:12px">Clear post history</button>
      </section>

      <p class="tiny muted" style="text-align:center;padding:8px 0 16px">NewsCard Studio · free GitHub hosting</p>
    `;
  }

  function imageProviderRow(provider, config) {
    const [label, note] = IMAGE_META[provider] || [provider, ""];
    const enabled = provider === "generated" || providerEnabled(config, "image", provider);
    const order = config.image.order;
    const index = order.indexOf(provider);
    return `
      <div class="provider-row">
        <div class="provider-main"><strong>${esc(label)}</strong><span>${esc(note)}</span></div>
        <div class="provider-order">
          ${provider !== "generated" ? `
            <button class="btn-icon" type="button" data-action="reorder-provider" data-group="image" data-id="${provider}" data-dir="-1" aria-label="Move ${esc(label)} up" ${index <= 0 ? "disabled" : ""}>${icon("arrow-up")}</button>
            <button class="btn-icon" type="button" data-action="reorder-provider" data-group="image" data-id="${provider}" data-dir="1" aria-label="Move ${esc(label)} down" ${index >= order.length - 2 ? "disabled" : ""}>${icon("arrow-down")}</button>
          ` : ""}
          <button class="switch" type="button" role="switch" aria-checked="${enabled ? "true" : "false"}" aria-label="${esc(label)} ${enabled ? "enabled" : "disabled"}" data-action="toggle-image-provider" data-id="${provider}" ${provider === "generated" || !state.online ? "disabled" : ""}></button>
        </div>
      </div>
    `;
  }

  function llmProviderRow(provider, config) {
    const [label, note] = LLM_META[provider] || [provider, ""];
    const enabled = providerEnabled(config, "llm", provider);
    const order = config.llm.order;
    const index = order.indexOf(provider);
    return `
      <div class="provider-row">
        <div class="provider-main"><strong>${esc(label)}</strong><span>${esc(note)}</span></div>
        <div class="provider-order">
          <button class="btn-icon" type="button" data-action="reorder-provider" data-group="llm" data-id="${provider}" data-dir="-1" aria-label="Move ${esc(label)} up" ${index <= 0 ? "disabled" : ""}>${icon("arrow-up")}</button>
          <button class="btn-icon" type="button" data-action="reorder-provider" data-group="llm" data-id="${provider}" data-dir="1" aria-label="Move ${esc(label)} down" ${index >= order.length - 1 ? "disabled" : ""}>${icon("arrow-down")}</button>
          <button class="switch" type="button" role="switch" aria-checked="${enabled ? "true" : "false"}" aria-label="${esc(label)} ${enabled ? "enabled" : "disabled"}" data-action="toggle-llm-provider" data-id="${provider}" ${!state.online ? "disabled" : ""}></button>
        </div>
      </div>
    `;
  }

  function runShellTitle() {
    const status = effectiveStatus();
    if (state.awaiting) return "Run queued";
    if (!status || status.stage === "idle") return "Run status";
    if (statusIsActive(status)) return "Run in progress";
    if (status.stage === "failed") return "Run failed";
    return "Run complete";
  }

  function runSheetBody() {
    const status = effectiveStatus();
    if (!status || (!status.run_id && !state.awaiting) || status.stage === "idle") {
      return `
        <div class="run-message">${esc(status?.message || "Waiting for the first run. Preview a card or post now.")}</div>
        <button class="btn btn-outline btn-block" type="button" data-run-action="preview">${icon("sparkle")} Preview a card</button>
      `;
    }
    const active = statusIsActive(status);
    const done = status.stage === "done";
    const failed = status.stage === "failed";
    let activeIndex = -1;
    if (active && Number(status.step) > 0) activeIndex = Math.max(0, Math.min(4, Number(status.step) - 1));
    const providers = [];
    if (status.provider_used) providers.push(`Text · ${status.provider_used}`);
    if (status.image_source) providers.push(`Image · ${status.image_source}`);
    if (status.design_provider) providers.push(`Design · ${status.design_provider}`);
    const card = status.card_jpg || status.card_png || "";
    const cardSource = card
      ? card.includes("/") || card.startsWith("cards/")
        ? card.replace(/^\/+/, "")
        : cardUrl({ jpg: card })
      : "";
    const queueItem = status.queue_id ? queueItemById(status.queue_id) : null;
    const instagram = safeUrl(status.instagram_url);
    const canReview = Boolean(queueItem);
    const details = status.details ? String(status.details) : "";
    return `
      <div class="run-provider">
        <span class="provider-pill">${status.dry_run ? "Dry run" : status.mode === "auto" ? "Auto-post" : "Review"}</span>
        ${providers.map((provider) => `<span class="provider-pill">${esc(provider)}</span>`).join("")}
        ${status.updated_at ? `<span class="provider-pill">${esc(timeAgo(status.updated_at))}</span>` : ""}
      </div>
      <div class="steps">
        ${RUN_STEPS.map((step, index) => {
          const stepState = done || (active && index < activeIndex)
            ? "done"
            : active && index === activeIndex
              ? "active"
              : "";
          return `
            <div class="step ${stepState}">
              <span class="step-dot">${stepState === "done" ? icon("check") : index + 1}</span>
              <span class="step-label">${esc(step.label)}</span>
              <span class="step-state">${stepState === "done" ? "Done" : stepState === "active" ? "Now" : failed ? "Stopped" : "Pending"}</span>
            </div>
          `;
        }).join("")}
      </div>
      <div class="run-message">${esc(status.message || "Working...")}${state.awaiting ? '<br><span class="tiny">GitHub Actions usually starts within 10-20 seconds. This sheet updates itself.</span>' : ""}</div>
      ${failed ? `
        <div class="run-error-box">
          <strong>${esc(status.error || "The run stopped.")}</strong>
          <span>${status.dry_run ? "Dry runs never publish. " : ""}You can adjust settings and try again.</span>
        </div>
      ` : ""}
      ${cardSource && (done || failed) ? `
        <div class="run-result">
          <img src="${esc(cardSource)}" alt="Generated card preview" onerror="this.style.visibility='hidden'">
          <div class="run-result-body">
            <strong>${esc(status.headline || "Card ready")}</strong>
            <p>${esc(CATEGORY_LABEL[status.category] || status.category || "")}${status.style ? ` · ${esc(STYLE_NAMES[Number(status.style) - 1] || "")}` : ""}</p>
          </div>
        </div>
      ` : ""}
      <div style="display:grid;gap:8px;margin-top:12px">
        ${instagram ? `<a class="btn btn-primary btn-block" href="${esc(instagram)}" target="_blank" rel="noopener">${icon("external")} Open Instagram post</a>` : ""}
        ${canReview && done ? `<button class="btn btn-outline btn-block" type="button" data-run-action="review" data-id="${esc(status.queue_id)}">Review in Queue</button>` : ""}
        ${active ? '<button class="btn btn-soft btn-block" type="button" data-run-action="close">Run in background</button>' : ""}
      </div>
      ${details ? `<details class="details"><summary>Technical details</summary><pre>${esc(details)}</pre></details>` : ""}
    `;
  }

  function updateRunSheetChrome() {
    if (!state.runSheet) return;
    const sheet = state.runSheet.sheet;
    const title = sheet.querySelector("#sheet-title");
    if (title) title.textContent = runShellTitle();
    const subtitle = sheet.querySelector(".sheet-head p");
    if (subtitle) {
      const status = effectiveStatus();
      subtitle.textContent = status?.updated_at ? `Last update ${timeAgo(status.updated_at)}` : "Live pipeline status";
    }
    const body = sheet.querySelector(".sheet-body");
    if (body) body.innerHTML = runSheetBody();
  }

  function openRunSheet() {
    if (state.runSheet) {
      updateRunSheetChrome();
      return;
    }
    let controller;
    controller = openSheet({
      title: runShellTitle(),
      subtitle: effectiveStatus()?.updated_at ? `Last update ${timeAgo(effectiveStatus().updated_at)}` : "Live pipeline status",
      className: "run-sheet",
      body: runSheetBody(),
      actions: [{ label: "Close", className: "btn-soft", onClick: () => closeSheet() }],
      onMount: (sheet) => {
        sheet.addEventListener("click", (event) => {
          const target = event.target.closest("[data-run-action]");
          if (!target) return;
          const action = target.dataset.runAction;
          if (action === "close") closeSheet();
          if (action === "preview") {
            closeSheet();
            triggerAction("generate_preview", { dryRun: true });
          }
          if (action === "review") {
            const id = target.dataset.id;
            closeSheet();
            switchTab("queue");
            setTimeout(() => {
              if (queueItemById(id)) openCardViewer(id);
            }, 60);
          }
        });
      },
      onClose: () => {
        if (state.runSheet === controller) state.runSheet = null;
      },
    });
    state.runSheet = controller;
  }

  function clearAwaiting() {
    if (state.awaitingTimer) clearTimeout(state.awaitingTimer);
    state.awaitingTimer = null;
    state.awaiting = null;
  }

  async function triggerAction(action, options = {}) {
    if (!state.online) {
      toast("You are offline. Reconnect before starting a run.");
      return false;
    }
    if (state.dispatching) {
      toast("A run is already starting.");
      return false;
    }
    if (runIsBusy()) {
      toast("A run is already in progress. Watch it from the status pill.");
      openRunSheet();
      return false;
    }
    state.dispatching = true;
    refreshChrome();
    renderViewPreserve();
    try {
      await dispatchWorkflow(action, options);
      const messages = {
        generate_preview: "Preview run queued.",
        post_now: "Posting run queued.",
        publish_queued: "Publishing run queued.",
        regenerate: "Regeneration run queued.",
        tick: "Run queued.",
      };
      state.awaiting = {
        action,
        dryRun: Boolean(options.dryRun),
        queueId: options.queueId || "",
        startedAt: Date.now(),
        lastRunId: state.lastRunId,
        message: messages[action] || "Run queued.",
      };
      state.awaitingTimer = setTimeout(() => {
        if (!state.awaiting) return;
        toast("GitHub Actions has not reported yet. Check the Actions tab.", {
          actionLabel: "Open Actions",
          onAction: () => window.open(repoWebUrl("/actions"), "_blank", "noopener"),
          duration: 9000,
        });
        updateRunSheetChrome();
      }, 120000);
      refreshChrome();
      renderViewPreserve();
      openRunSheet();
      schedulePoll(2200);
      return true;
    } catch (error) {
      if (options.queueId) state.busyIds.delete(options.queueId);
      toast(friendlyError(error), {
        actionLabel: "Settings",
        onAction: () => switchTab("settings"),
      });
      refreshChrome();
      renderViewPreserve();
      return false;
    } finally {
      state.dispatching = false;
      refreshChrome();
      renderViewPreserve();
    }
  }

  function schedulePoll(delay) {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    const hidden = document.visibilityState === "hidden";
    const wait = hidden ? Math.max(delay, 20000) : delay;
    state.pollTimer = setTimeout(() => pollStatus(), wait);
  }

  function pollDelay() {
    const status = effectiveStatus();
    const active = Boolean(state.awaiting) || statusIsActive(status);
    if (!active) return 12000;
    if (statusIsActive(status) && state.activeSince && Date.now() - state.activeSince > 120000) return 8000;
    return 4000;
  }

  async function pollStatus(immediate = false) {
    if (state.screen !== "app") return;
    if (state.polling) {
      if (!immediate) schedulePoll(pollDelay());
      return;
    }
    if (!navigator.onLine) {
      schedulePoll(20000);
      return;
    }
    state.polling = true;
    state.lastPollAt = Date.now();
    try {
      const statusFile = await loadFile("data/status.json", {
        missing: { stage: "idle", message: "Waiting for the first run." },
      });
      handleNewStatus(statusFile.data);
    } catch (error) {
      if (error.status === 401) toast("GitHub token rejected. Reconnect from Settings.");
    } finally {
      state.polling = false;
      schedulePoll(pollDelay());
    }
  }

  function handleNewStatus(raw) {
    const previous = state.status;
    const previousRunId = state.lastRunId;
    const newRun = Boolean(raw?.run_id) && raw.run_id !== previousRunId;
    const wasAwaiting = Boolean(state.awaiting);
    if (wasAwaiting && !newRun) {
      refreshChrome();
      updateRunSheetChrome();
      return;
    }
    if (wasAwaiting && newRun) clearAwaiting();
    const previousActive = statusIsActive(previous);
    if (raw && raw.run_id) state.lastRunId = raw.run_id;
    state.status = raw || previous;
    if (statusIsActive(state.status)) {
      if (!previousActive || newRun) {
        state.activeSince = Date.now();
        if (!wasAwaiting) state.observedActive = true;
      }
    } else {
      const completed = previousActive || (wasAwaiting && newRun);
      const externallyCompleted = newRun && (state.status?.stage === "done" || state.status?.stage === "failed");
      state.activeSince = null;
      refreshChrome();
      if (completed || externallyCompleted) {
        const showToast = wasAwaiting || state.observedActive || state.status?.stage === "failed" || completed;
        const message = state.status?.stage === "failed"
          ? state.status?.error || state.status?.message || "The run failed."
          : state.status?.message || "Run complete.";
        refreshAfterRun();
        if (showToast) {
          toast(message, {
            actionLabel: "View run",
            onAction: () => openRunSheet(),
          });
        }
        state.observedActive = false;
      }
    }
    refreshChrome();
    renderView({ preserveScroll: true });
    updateRunSheetChrome();
  }

  function updateConfig(mutator, options = {}) {
    if (!state.config) return Promise.resolve();
    const next = deepClone(state.config);
    mutator(next);
    state.config = next;
    state.configDirty = true;
    state.configMessage = options.message || "Update settings from the dashboard";
    refreshChrome();
    if (options.rerender !== false) renderViewPreserve();
    if (state.configSaveTimer) clearTimeout(state.configSaveTimer);
    if (options.immediate) {
      state.configSaveTimer = null;
      return flushConfig();
    }
    state.configSaveTimer = setTimeout(flushConfig, 260);
    return Promise.resolve();
  }

  async function flushConfig() {
    if (state.configSaving || !state.configDirty || !state.config) return;
    if (state.configSaveTimer) {
      clearTimeout(state.configSaveTimer);
      state.configSaveTimer = null;
    }
    state.configDirty = false;
    state.configSaving = true;
    const content = deepClone(state.config);
    try {
      await putJsonFile("data/config.json", content, state.configMessage || "Update settings");
    } catch (error) {
      toast(`Could not save settings: ${friendlyError(error)}`);
      if (error.status === 401) showFatal(error.message, true);
    } finally {
      state.configSaving = false;
      if (state.configDirty) state.configSaveTimer = setTimeout(flushConfig, 160);
    }
  }

  function mutateQueue(mutator, options = {}) {
    if (!state.queue) state.queue = { items: [] };
    const optimistic = deepClone(state.queue);
    if (!Array.isArray(optimistic.items)) optimistic.items = [];
    options.optimistic?.(optimistic);
    state.queue = optimistic;
    refreshChrome();
    if (options.render !== false) renderViewPreserve();
    const task = state.queueLock.then(async () => {
      const fresh = await loadFile("data/queue.json", { force: true, missing: { items: [] } });
      const data = deepClone(fresh.data || { items: [] });
      if (!Array.isArray(data.items)) data.items = [];
      mutator(data);
      await putJsonFile("data/queue.json", data, options.message || "Update queue from dashboard", {
        sha: fresh.sha,
      });
      state.queue = data;
      refreshChrome();
      renderViewPreserve();
      return true;
    });
    state.queueLock = task.catch(() => {});
    return task.catch(async (error) => {
      toast(`Could not update the queue: ${friendlyError(error)}`);
      try {
        const fresh = await loadFile("data/queue.json", { force: true, missing: { items: [] } });
        state.queue = fresh.data?.items ? fresh.data : { items: [] };
        refreshChrome();
        renderViewPreserve();
      } catch {
        return false;
      }
      return false;
    });
  }

  function mutateHistory(mutator, options = {}) {
    if (!state.history) state.history = { posts: [], used_photos: [], meta: {} };
    const task = state.historyLock.then(async () => {
      const fresh = await loadFile("data/history.json", {
        force: true,
        missing: { posts: [], used_photos: [], meta: {} },
      });
      const data = deepClone(fresh.data || { posts: [], used_photos: [], meta: {} });
      if (!Array.isArray(data.posts)) data.posts = [];
      mutator(data);
      await putJsonFile("data/history.json", data, options.message || "Update history from dashboard", {
        sha: fresh.sha,
      });
      state.history = data;
      refreshChrome();
      renderViewPreserve();
      return true;
    });
    state.historyLock = task.catch(() => {});
    return task.catch((error) => {
      toast(`Could not update history: ${friendlyError(error)}`);
      return false;
    });
  }

  async function saveCaption(itemId, value) {
    const text = String(value || "").trim();
    if (!text) {
      toast("The caption cannot be empty.");
      return false;
    }
    if (text.length > MAX_CAPTION) {
      toast(`Captions can be up to ${MAX_CAPTION} characters.`);
      return false;
    }
    const item = queueItemById(itemId);
    if (!item) {
      toast("That card is no longer in the queue.");
      return false;
    }
    const queueOk = await mutateQueue((queue) => {
      const entry = queue.items.find((candidate) => candidate.id === itemId);
      if (!entry) return;
      entry.caption = text;
      entry.updated_at = new Date().toISOString();
    }, {
      message: "Update queued caption from dashboard",
      optimistic: (queue) => {
        const entry = queue.items.find((candidate) => candidate.id === itemId);
        if (entry) entry.caption = text;
      },
    });
    if (!queueOk) return false;
    const historyId = item.history_id || item.id;
    await mutateHistory((history) => {
      const entry = history.posts.find((candidate) => candidate.id === historyId);
      if (entry) entry.caption = text;
    }, { message: "Update caption in history" });
    toast("Caption saved.");
    return true;
  }

  async function publishQueueItem(id) {
    const item = queueItemById(id);
    if (!item) {
      toast("That card is no longer in the queue.");
      return;
    }
    if (state.config?.posting_paused) {
      toast("Posting is paused. Resume it before approving cards.", {
        actionLabel: "Resume",
        onAction: () => {
          updateConfig((config) => {
            config.posting_paused = false;
          }, { message: "Resume posting from dashboard", immediate: true });
          toast("Posting resumed.");
        },
      });
      return;
    }
    if (runIsBusy()) {
      toast("A run is already in progress.");
      openRunSheet();
      return;
    }
    state.busyIds.add(id);
    refreshChrome();
    renderViewPreserve();
    const ok = await triggerAction("publish_queued", { queueId: id, dryRun: false });
    if (!ok) {
      state.busyIds.delete(id);
      refreshChrome();
      renderViewPreserve();
    }
  }

  async function discardQueueItem(id) {
    const item = queueItemById(id);
    if (!item) return;
    const historyId = item.history_id || item.id;
    const historyEntry = historyItemById(historyId);
    const previousStatus = historyEntry?.status || "pending";
    const previousError = historyEntry?.error || "";
    closeViewer();
    const removed = deepClone(item);
    const queueOk = await mutateQueue((queue) => {
      queue.items = queue.items.filter((candidate) => candidate.id !== id);
    }, {
      message: "Discard card from queue",
      optimistic: (queue) => {
        queue.items = queue.items.filter((candidate) => candidate.id !== id);
      },
    });
    if (!queueOk) return;
    await mutateHistory((history) => {
      const entry = history.posts.find((candidate) => candidate.id === historyId);
      if (entry) {
        entry.status = "discarded";
        entry.error = "";
      }
    }, { message: "Mark card discarded in history" });
    toast("Card discarded.", {
      actionLabel: "Undo",
      onAction: async () => {
        if (queueItemById(removed.id)) return;
        await mutateQueue((queue) => {
          if (!queue.items.some((candidate) => candidate.id === removed.id)) queue.items.push(removed);
        }, {
          message: "Restore discarded card",
          optimistic: (queue) => {
            if (!queue.items.some((candidate) => candidate.id === removed.id)) queue.items.push(removed);
          },
        });
        await mutateHistory((history) => {
          const entry = history.posts.find((candidate) => candidate.id === historyId);
          if (entry) {
            entry.status = previousStatus;
            entry.error = previousError;
          }
        }, { message: "Restore discarded card in history" });
        toast("Card restored to the queue.");
      },
      duration: 8000,
    });
  }

  async function openPostNowSheet() {
    if (state.config?.posting_paused) {
      toast("Posting is paused. Resume it from Schedule.");
      return;
    }
    if (runIsBusy()) {
      toast("A run is already in progress.");
      openRunSheet();
      return;
    }
    let topic = "";
    const body = `
      <p class="small muted" style="line-height:1.55;margin-bottom:14px">This posts immediately, even when your default mode is Review first.</p>
      <p class="form-field" style="margin-bottom:8px"><label>Topic</label></p>
      <div class="chip-row" role="group" aria-label="Topic for this post">
        <button class="chip" type="button" data-postnow-topic="" aria-pressed="true">Auto</button>
        ${CATEGORIES.map(([id, label]) => `<button class="chip" type="button" data-postnow-topic="${id}" aria-pressed="false">${esc(label)}</button>`).join("")}
      </div>
      <div class="warning-note">Instagram posts cannot be edited or deleted from this dashboard. Use Review first if you want a safety check.</div>
    `;
    const controller = openSheet({
      title: "Post now?",
      subtitle: "A fresh story will be fetched, designed, and published.",
      body,
      actions: [
        { label: "Preview instead", className: "btn-soft", onClick: () => {
          closeSheet();
          triggerAction("generate_preview", { dryRun: true });
        } },
        { label: "Post now", className: "btn-primary", onClick: () => {
          closeSheet();
          triggerAction("post_now", { topic, dryRun: false });
        } },
      ],
      onMount: (sheet) => {
        sheet.querySelectorAll("[data-postnow-topic]").forEach((button) => {
          button.addEventListener("click", () => {
            topic = button.dataset.postnowTopic || "";
            sheet.querySelectorAll("[data-postnow-topic]").forEach((candidate) => {
              candidate.setAttribute("aria-pressed", candidate === button ? "true" : "false");
            });
          });
        });
      },
    });
    return controller;
  }

  function openTokenHelp() {
    openSheet({
      title: "Connect with a GitHub token",
      subtitle: "Fine-grained tokens keep access limited to one repo.",
      className: "help-sheet",
      body: `
        <ol>
          <li>Open <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener"><strong>github.com/settings/personal-access-tokens/new</strong></a>.</li>
          <li>Choose the repository that contains your NewsCard Studio copy.</li>
          <li>Under Repository permissions, set <strong>Contents: Read and write</strong> and <strong>Actions: Read and write</strong>.</li>
          <li>Set an expiry you are comfortable with, generate the token, and paste it here.</li>
        </ol>
        <p class="small muted" style="margin-top:12px;line-height:1.55">The token is stored only in this browser's localStorage. It is never written to the repo.</p>
        <div class="warning-note">Do not use a classic token with full account access. A fine-grained token limited to this repo is enough.</div>
      `,
      actions: [{ label: "Got it", className: "btn-soft", onClick: () => closeSheet() }],
    });
  }

  function openSessionHelp() {
    openSheet({
      title: "Refresh Instagram access",
      subtitle: "The session stays on your computer and in GitHub secrets.",
      className: "help-sheet",
      body: `
        <ol>
          <li>Run <code>python tools/get_session.py</code> on your computer.</li>
          <li>Sign in with the Instagram account that owns the posting profile. Complete any 2FA challenge.</li>
          <li>Copy the full contents of <code>ig_session.json</code>, including the outer braces.</li>
          <li>In GitHub, open <strong>Settings → Secrets and variables → Actions</strong> and update <code>IG_SESSION_JSON</code>.</li>
          <li>Delete the local file when you are done.</li>
        </ol>
        <p class="small muted" style="margin-top:12px;line-height:1.55">If a run refreshes the session automatically, it leaves the new session in the workflow output. Update the secret from that value.</p>
      `,
      actions: [{ label: "Close", className: "btn-soft", onClick: () => closeSheet() }],
    });
  }

  function openRegenerateSheet(id) {
    const item = queueItemById(id);
    if (!item) {
      toast("That card is no longer in the queue.");
      return;
    }
    let selected = Number(item.style) || 1;
    const body = `
      <p class="small muted" style="line-height:1.55;margin-bottom:14px">Pick a new look. Regenerate also fetches a fresh photo and updates the photo credit.</p>
      ${styleGridHTML(selected, "pick-regenerate-style")}
    `;
    openSheet({
      title: "Try another style",
      subtitle: item.headline || "Queued card",
      body,
      actions: [
        {
          label: "Regenerate card",
          className: "btn-primary",
          onClick: async () => {
            closeSheet();
            state.busyIds.add(id);
            refreshChrome();
            renderViewPreserve();
            const ok = await triggerAction("regenerate", { queueId: id, style: selected, dryRun: false });
            if (!ok) state.busyIds.delete(id);
          },
        },
      ],
      onMount: (sheet) => {
        sheet.querySelectorAll("[data-action='pick-regenerate-style']").forEach((tile) => {
          tile.addEventListener("click", () => {
            selected = Number(tile.dataset.style) || 1;
            sheet.querySelectorAll("[data-action='pick-regenerate-style']").forEach((candidate) => {
              candidate.setAttribute("aria-pressed", candidate === tile ? "true" : "false");
            });
          });
        });
      },
    });
  }

  function openCardViewer(id) {
    const item = queueItemById(id);
    if (!item) {
      toast("That card is no longer in the queue.");
      return;
    }
    const image = cardUrl(item);
    const caption = String(item.caption || "");
    const source = safeUrl(item.story_url);
    const body = `
      ${image ? `<img class="viewer-image" src="${esc(image)}" alt="Card preview" onerror="this.style.visibility='hidden'">` : '<div class="viewer-image" style="aspect-ratio:4/5;display:grid;place-items:center">' + icon("image") + "</div>"}
      <div class="queue-meta" style="margin-top:14px">
        <span class="category-chip">${esc(CATEGORY_LABEL[item.category] || item.category_label || "News")}</span>
        <span class="style-chip">${esc(item.style_name || styleDisplay({ style: item.style }))}</span>
        ${item.dry_run ? '<span class="status-pill status-dry">Preview</span>' : ""}
      </div>
      <h3 style="font-size:22px;line-height:1.2;letter-spacing:-0.03em;margin:8px 0 12px">${esc(item.headline || "Untitled card")}</h3>
      ${item.error ? `<div class="run-error-box" style="margin-bottom:12px"><strong>Last attempt failed</strong>${esc(item.error)}</div>` : ""}
      <label class="form-field" for="caption-edit" style="margin-bottom:6px"><span style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;font-weight:800;color:var(--muted)">Caption</span></label>
      <textarea class="input" id="caption-edit" maxlength="${MAX_CAPTION}" spellcheck="true">${esc(caption)}</textarea>
      <div class="input-counter"><span>Photo credit is added automatically.</span><span id="caption-count">${caption.length}/${MAX_CAPTION}</span></div>
      <button class="btn btn-soft btn-block" id="save-caption" type="button" style="margin-top:10px" ${!state.online ? "disabled" : ""}>Save caption</button>
      ${item.image_credit ? `<p class="tiny muted" style="margin-top:12px;line-height:1.5">${esc(item.image_credit)}</p>` : ""}
      ${source ? `<a class="help-link" href="${esc(source)}" target="_blank" rel="noopener" style="margin-top:6px">Source: ${esc(item.story_source || "article")} ${icon("external")}</a>` : ""}
      <div class="viewer-actions">
        <button class="btn btn-primary btn-block" type="button" data-card-action="publish" ${runIsBusy() || !state.online ? "disabled" : ""}>${icon("play")} Approve & post</button>
        <button class="btn btn-outline btn-block" type="button" data-card-action="regenerate" ${runIsBusy() || !state.online ? "disabled" : ""}>${icon("refresh")} Try another style or photo</button>
        <button class="btn btn-danger btn-block" type="button" data-card-action="discard" ${!state.online ? "disabled" : ""}>${icon("trash")} Discard card</button>
      </div>
      <p class="viewer-note">Review the image and caption carefully. Publishing sends this exact card to Instagram.</p>
    `;
    openViewer({
      title: "Review card",
      body,
      onMount: (element) => {
        const textarea = element.querySelector("#caption-edit");
        const count = element.querySelector("#caption-count");
        const save = element.querySelector("#save-caption");
        textarea?.addEventListener("input", () => {
          if (count) count.textContent = `${textarea.value.length}/${MAX_CAPTION}`;
        });
        save?.addEventListener("click", async () => {
          if (!textarea) return;
          save.disabled = true;
          save.textContent = "Saving...";
          const ok = await saveCaption(id, textarea.value);
          if (document.contains(save)) {
            save.disabled = !state.online;
            save.textContent = ok ? "Saved" : "Save caption";
            if (ok) setTimeout(() => {
              if (document.contains(save)) save.textContent = "Save caption";
            }, 1500);
          }
        });
        element.addEventListener("click", (event) => {
          const button = event.target.closest("[data-card-action]");
          if (!button) return;
          const action = button.dataset.cardAction;
          if (action === "publish") {
            closeViewer();
            publishQueueItem(id);
          } else if (action === "regenerate") {
            closeViewer();
            openRegenerateSheet(id);
          } else if (action === "discard") {
            closeViewer();
            discardQueueItem(id);
          }
        });
      },
      onClose: () => {},
    });
  }

  function copyText(text) {
    const value = String(text || "");
    if (!value) return Promise.resolve(false);
    if (navigator.clipboard?.writeText) {
      return navigator.clipboard.writeText(value).then(() => true).catch(() => false);
    }
    const area = document.createElement("textarea");
    area.value = value;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    area.remove();
    return Promise.resolve(ok);
  }

  function openPostViewer(id) {
    const post = historyItemById(id);
    if (!post) {
      toast("That post is no longer in your history.");
      return;
    }
    const image = cardUrl(post);
    const instagram = safeUrl(post.instagram_url);
    const source = safeUrl(post.story_url);
    const queueItem = post.status === "pending" ? queueItemById(post.id) : null;
    const body = `
      ${image ? `<img class="viewer-image" src="${esc(image)}" alt="Posted card" onerror="this.style.visibility='hidden'">` : '<div class="viewer-image" style="aspect-ratio:4/5;display:grid;place-items:center">' + icon("image") + "</div>"}
      <div class="queue-meta" style="margin-top:14px">
        ${postStatusPill(post)}
        <span class="style-chip">${esc(post.style_name || styleDisplay({ style: post.style }))}</span>
        <span class="tiny muted">${esc(post.posted_at ? formatDateTime(post.posted_at) : formatDateTime(post.created_at))}</span>
      </div>
      <h3 style="font-size:22px;line-height:1.2;letter-spacing:-0.03em;margin:8px 0 12px">${esc(post.headline || "Untitled card")}</h3>
      ${post.error ? `<div class="run-error-box" style="margin-bottom:12px"><strong>Error</strong>${esc(post.error)}</div>` : ""}
      <div class="viewer-caption">${esc(post.caption || "No caption saved.")}</div>
      ${post.image_credit ? `<p class="tiny muted" style="margin-top:10px;line-height:1.5">${esc(post.image_credit)}</p>` : ""}
      <div class="viewer-actions">
        ${instagram ? `<a class="btn btn-primary btn-block" href="${esc(instagram)}" target="_blank" rel="noopener">${icon("external")} Open Instagram post</a>` : ""}
        <button class="btn btn-soft btn-block" type="button" data-post-action="copy">${icon("copy")} Copy caption</button>
        ${queueItem ? `<button class="btn btn-outline btn-block" type="button" data-post-action="review" data-id="${esc(queueItem.id)}">Review in Queue</button>` : ""}
        ${source ? `<a class="btn btn-soft btn-block" href="${esc(source)}" target="_blank" rel="noopener">${icon("external")} Open source story</a>` : ""}
      </div>
    `;
    openViewer({
      title: "Post details",
      body,
      onMount: (element) => {
        element.addEventListener("click", async (event) => {
          const button = event.target.closest("[data-post-action]");
          if (!button) return;
          if (button.dataset.postAction === "copy") {
            const ok = await copyText(post.caption || "");
            toast(ok ? "Caption copied." : "Could not copy the caption.");
          }
          if (button.dataset.postAction === "review") {
            closeViewer();
            switchTab("queue");
            setTimeout(() => {
              if (queueItemById(button.dataset.id)) openCardViewer(button.dataset.id);
            }, 60);
          }
        });
      },
    });
  }

  function openHistorySheet() {
    const posts = historyPosts()
      .slice()
      .sort((a, b) => new Date(b.posted_at || b.created_at || 0) - new Date(a.posted_at || a.created_at || 0))
      .slice(0, 50);
    openSheet({
      title: "Post history",
      subtitle: posts.length ? `Last ${posts.length} card${posts.length === 1 ? "" : "s"}` : "No posts yet",
      body: posts.length
        ? `<div class="post-list">${posts.map((post) => `
            <button class="post-row" type="button" data-history-id="${esc(post.id)}">
              ${postImage(post)}
              <span class="post-meta">
                <strong>${esc(post.headline || post.story_title || "Untitled card")}</strong>
                <span class="post-sub">${postStatusPill(post)}<span>${esc(post.posted_at ? formatDateTime(post.posted_at) : timeAgo(post.created_at))}</span></span>
              </span>
              ${icon("chevron-right")}
            </button>
          `).join("")}</div>`
        : '<div class="empty-card"><strong>No history yet.</strong><p>Posted and previewed cards will appear here.</p></div>',
      actions: [{ label: "Close", className: "btn-soft", onClick: () => closeSheet() }],
      onMount: (sheet, controller) => {
        sheet.addEventListener("click", (event) => {
          const button = event.target.closest("[data-history-id]");
          if (!button) return;
          const id = button.dataset.historyId;
          controller.close();
          setTimeout(() => openPostViewer(id), 40);
        });
      },
    });
  }

  function bindQueueView() {
    view.querySelectorAll(".swipe-wrap").forEach((wrap) => {
      const card = wrap.querySelector(".queue-card");
      if (!card) return;
      let startX = 0;
      let startY = 0;
      let deltaX = 0;
      let horizontal = false;
      let active = false;
      card.addEventListener("touchstart", (event) => {
        if (event.target.closest(".queue-actions")) return;
        const touch = event.touches[0];
        if (!touch) return;
        active = true;
        horizontal = false;
        startX = touch.clientX;
        startY = touch.clientY;
        deltaX = 0;
        wrap.dataset.swiped = "";
      }, { passive: true });
      card.addEventListener("touchmove", (event) => {
        if (!active) return;
        const touch = event.touches[0];
        if (!touch) return;
        const dx = touch.clientX - startX;
        const dy = touch.clientY - startY;
        if (!horizontal && Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.3) horizontal = true;
        if (!horizontal) return;
        if (dx < 0) {
          event.preventDefault();
          deltaX = Math.max(-170, dx);
          card.style.transform = `translateX(${deltaX}px)`;
        }
      }, { passive: false });
      const finish = () => {
        if (!active) return;
        active = false;
        if (!horizontal) return;
        card.style.transition = "transform 170ms ease";
        if (deltaX < -95) {
          wrap.dataset.swiped = "1";
          card.style.transform = "translateX(-110%)";
          setTimeout(() => {
            discardQueueItem(wrap.dataset.swipeId);
          }, 170);
        } else {
          card.style.transform = "";
        }
        setTimeout(() => {
          card.style.transition = "";
        }, 200);
        horizontal = false;
        deltaX = 0;
      };
      card.addEventListener("touchend", finish);
      card.addEventListener("touchcancel", finish);
      wrap.addEventListener("click", (event) => {
        if (wrap.dataset.swiped) {
          event.preventDefault();
          event.stopPropagation();
          delete wrap.dataset.swiped;
        }
      }, true);
    });
  }

  function generateSlotId(time, schedule, existingId = "") {
    if (existingId) return existingId;
    const base = `slot_${String(time).replace(":", "")}`;
    const ids = new Set((schedule || []).map((slot) => slot.id));
    if (!ids.has(base)) return base;
    let suffix = 2;
    while (ids.has(`${base}_${suffix}`)) suffix += 1;
    return `${base}_${suffix}`;
  }

  function openSlotEditor(slotId = "") {
    const schedule = state.config?.schedule || [];
    const existing = slotId ? schedule.find((slot) => slot.id === slotId) : null;
    if (slotId && !existing) {
      toast("That slot no longer exists.");
      return;
    }
    const draft = {
      time: normalizeTime(existing?.time || "12:30"),
      days: Array.isArray(existing?.days) && existing.days.length ? [...existing.days].sort((a, b) => a - b) : [0, 1, 2, 3, 4, 5, 6],
      mode: existing?.mode || "global",
      enabled: existing?.enabled !== false,
    };
    const body = `
      <div class="form-field">
        <label for="slot-time">Time (${esc(state.config.timezone)})</label>
        <input class="input" id="slot-time" type="time" step="1800" value="${esc(draft.time)}" required>
        <span class="field-help">Runs on 30-minute marks. The scheduler checks for 29 minutes after this time.</span>
      </div>
      <div class="form-field">
        <label>Days</label>
        <div class="day-row">
          ${DAY_LABELS.map((label, day) => `
            <button class="day-chip" type="button" data-slot-day="${day}" aria-pressed="${draft.days.includes(day)}" aria-label="${esc(DAY_NAMES[day])}">${label}</button>
          `).join("")}
        </div>
      </div>
      <div class="form-field">
        <label>Mode</label>
        <div class="segmented" role="group" aria-label="Slot mode">
          <button type="button" data-slot-mode="global" aria-pressed="${draft.mode === "global"}">Inherit</button>
          <button type="button" data-slot-mode="auto" aria-pressed="${draft.mode === "auto"}">Auto</button>
          <button type="button" data-slot-mode="approve" aria-pressed="${draft.mode === "approve"}">Review</button>
        </div>
        <span class="field-help">Inherit uses the default ${state.config.mode === "auto" ? "Auto-post" : "Review first"} mode.</span>
      </div>
      ${existing ? `<button class="btn btn-danger btn-block" type="button" data-delete-slot style="margin-top:18px">${icon("trash")} Delete this slot</button>` : ""}
    `;
    const controller = openSheet({
      title: existing ? "Edit time slot" : "Add a time slot",
      subtitle: existing ? formatTime12Text(existing.time) : "Choose when the newsroom can post.",
      body,
      actions: [
        {
          label: existing ? "Save changes" : "Add slot",
          className: "btn-primary",
          onClick: async () => {
            const input = $("slot-time");
            const time = normalizeTime(input?.value || draft.time);
            const duplicate = schedule.some((slot) => slot.time === time && slot.id !== existing?.id);
            if (duplicate) {
              toast("Another slot already uses that time.");
              return;
            }
            const newSlot = {
              id: generateSlotId(time, schedule, existing?.id || ""),
              time,
              days: [...draft.days].sort((a, b) => a - b),
              enabled: existing?.enabled !== false,
              mode: draft.mode,
              topic_override: existing?.topic_override || "",
            };
            await updateConfig((config) => {
              if (!Array.isArray(config.schedule)) config.schedule = [];
              if (existing) {
                config.schedule = config.schedule.map((slot) => slot.id === existing.id ? newSlot : slot);
              } else {
                config.schedule = [...config.schedule, newSlot];
              }
              config.schedule.sort((a, b) => timeToMinutes(a.time) - timeToMinutes(b.time));
            }, { message: existing ? "Update posting slot" : "Add posting slot", immediate: true });
            closeSheet();
            toast(existing ? "Slot updated." : "Slot added.");
          },
        },
      ],
      onMount: (sheet) => {
        sheet.querySelectorAll("[data-slot-day]").forEach((button) => {
          button.addEventListener("click", () => {
            const day = Number(button.dataset.slotDay);
            if (draft.days.includes(day)) {
              if (draft.days.length === 1) {
                toast("Keep at least one day enabled.");
                return;
              }
              draft.days = draft.days.filter((value) => value !== day);
            } else {
              draft.days = [...draft.days, day].sort((a, b) => a - b);
            }
            button.setAttribute("aria-pressed", draft.days.includes(day) ? "true" : "false");
          });
        });
        sheet.querySelectorAll("[data-slot-mode]").forEach((button) => {
          button.addEventListener("click", () => {
            draft.mode = button.dataset.slotMode;
            sheet.querySelectorAll("[data-slot-mode]").forEach((candidate) => {
              candidate.setAttribute("aria-pressed", candidate === button ? "true" : "false");
            });
          });
        });
        sheet.querySelector("[data-delete-slot]")?.addEventListener("click", () => {
          const id = existing?.id;
          closeSheet();
          openConfirm({
            title: "Delete this slot?",
            body: `Posts scheduled at ${formatTime12Text(existing.time)} will stop. This does not delete existing cards.`,
            confirmLabel: "Delete slot",
            danger: true,
            onConfirm: async () => {
              await updateConfig((config) => {
                config.schedule = config.schedule.filter((slot) => slot.id !== id);
              }, { message: "Delete posting slot", immediate: true });
              toast("Slot deleted.");
            },
          });
        });
      },
    });
    return controller;
  }

  function bindSettingsView() {
    const fileInput = $("logo-file");
    fileInput?.addEventListener("change", () => {
      const file = fileInput.files?.[0];
      if (file) uploadLogo(file);
      fileInput.value = "";
    });
    view.querySelectorAll("[data-keyword-input]").forEach((input) => {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          addKeyword(input.dataset.keywordInput, input.value);
        }
      });
    });
  }

  async function uploadLogo(file) {
    if (!navigator.onLine) {
      toast("You are offline. Reconnect to upload a logo.");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      toast("Choose an image smaller than 8 MB.");
      return;
    }
    const objectUrl = URL.createObjectURL(file);
    try {
      const image = await new Promise((resolve, reject) => {
        const element = new Image();
        element.onload = () => resolve(element);
        element.onerror = () => reject(new Error("That image could not be read."));
        element.src = objectUrl;
      });
      const canvas = document.createElement("canvas");
      canvas.width = 512;
      canvas.height = 512;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Could not prepare the logo.");
      context.clearRect(0, 0, 512, 512);
      const scale = Math.min(512 / image.width, 512 / image.height);
      const width = Math.max(1, Math.round(image.width * scale));
      const height = Math.max(1, Math.round(image.height * scale));
      context.drawImage(image, Math.round((512 - width) / 2), Math.round((512 - height) / 2), width, height);
      const dataUrl = canvas.toDataURL("image/png");
      const base64 = dataUrl.split(",")[1];
      const sha = await fileSha("docs/brand/logo.png");
      await putFile("docs/brand/logo.png", base64, "Update brand logo from dashboard", { sha });
      state.logoVersion = Date.now();
      await updateConfig((config) => {
        config.brand.logo_path = "docs/brand/logo.png";
      }, { message: "Set brand logo path", immediate: true });
      toast("Logo uploaded and saved.");
    } catch (error) {
      toast(friendlyError(error));
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  }

  function addKeyword(list, rawValue) {
    const value = String(rawValue || "").trim().slice(0, 40);
    if (!value) return;
    const key = list === "mute" ? "mute_keywords" : "prefer_keywords";
    const current = state.config?.[key] || [];
    if (current.some((word) => word.toLowerCase() === value.toLowerCase())) {
      toast("That keyword is already in the list.");
      return;
    }
    updateConfig((config) => {
      config[key] = [...(Array.isArray(config[key]) ? config[key] : []), value].slice(0, 40);
    }, { message: `Add ${list} keyword` });
    toast("Keyword added.");
  }

  async function saveBrandDetails() {
    const name = $("brand-name")?.value.trim() || "";
    let handle = $("brand-handle")?.value.trim() || "";
    const footer = $("brand-footer")?.value.trim() || "";
    if (!name) {
      toast("Brand name cannot be empty.");
      return;
    }
    if (handle && !handle.startsWith("@")) handle = `@${handle}`;
    await updateConfig((config) => {
      config.brand.name = name;
      config.brand.handle = handle || "@newscardstudio";
      config.brand.footer_text = footer;
    }, { message: "Update brand details", immediate: true });
    toast("Brand details saved.");
  }

  function toggleTopic(id) {
    const config = state.config;
    if (!config) return;
    const enabled = CATEGORIES.filter(([key]) => Boolean(config.topics?.[key]));
    if (config.topics?.[id] && enabled.length === 1) {
      toast("Keep at least one topic enabled.");
      return;
    }
    updateConfig((next) => {
      next.topics[id] = !next.topics[id];
    }, { message: "Update topics" });
  }

  function reorderProvider(group, provider, direction) {
    const delta = Number(direction);
    if (!delta) return;
    updateConfig((config) => {
      const target = group === "llm" ? config.llm : config.image;
      const index = target.order.indexOf(provider);
      const nextIndex = index + delta;
      if (index < 0 || nextIndex < 0 || nextIndex >= target.order.length) return;
      [target.order[index], target.order[nextIndex]] = [target.order[nextIndex], target.order[index]];
      if (group === "image") {
        const generated = target.order.indexOf("generated");
        if (generated >= 0) {
          target.order.splice(generated, 1);
          target.order.push("generated");
        }
      }
    }, { message: "Reorder providers" });
  }

  function toggleProvider(group, provider) {
    if (group === "image" && provider === "generated") {
      toast("The generated background is always kept as the final fallback.");
      return;
    }
    updateConfig((config) => {
      const target = group === "llm" ? config.llm : config.image;
      const disabled = new Set(Array.isArray(target.disabled) ? target.disabled : []);
      if (disabled.has(provider)) disabled.delete(provider);
      else disabled.add(provider);
      target.disabled = Array.from(disabled);
    }, { message: `Toggle ${group} provider` });
  }

  async function testConnection() {
    try {
      await fetchFile("data/config.json", { force: true });
      await apiRequest(repoApi("/actions/workflows/tick.yml"));
      toast("Connection verified: repo, files, and workflow are reachable.");
    } catch (error) {
      toast(`Connection test failed: ${friendlyError(error)}`, {
        actionLabel: "Reconnect",
        onAction: () => {
          clearSavedSetup();
          location.reload();
        },
      });
    }
  }

  function clearSavedSetup() {
    try {
      const keys = [];
      for (let index = 0; index < localStorage.length; index += 1) {
        const key = localStorage.key(index);
        if (key && key.startsWith("ncs.")) keys.push(key);
      }
      keys.forEach((key) => localStorage.removeItem(key));
    } catch {
      return;
    }
  }

  function disconnect() {
    openConfirm({
      title: "Disconnect GitHub?",
      body: "This removes the token and cached dashboard data from this browser. Nothing changes in your repository.",
      confirmLabel: "Disconnect",
      danger: true,
      onConfirm: () => {
        clearSavedSetup();
        location.reload();
      },
    });
  }

  function clearHistory() {
    const count = historyPosts().length;
    until: {
      if (!count) {
        toast("History is already empty.");
        break until;
      }
      openConfirm({
        title: "Clear post history?",
        body: `This removes ${count} dashboard record${count === 1 ? "" : "s"} and the photo-reuse memory. Generated card files stay in the repo.`,
        confirmLabel: "Clear history",
        danger: true,
        onConfirm: async () => {
          const ok = await mutateHistory((history) => {
            history.posts = [];
            history.used_photos = [];
            history.meta = { last_style: null, last_run: null };
          }, { message: "Clear post history from dashboard" });
          if (ok) toast("Post history cleared.");
        },
      });
    }
  }

  async function handleViewAction(action, element) {
    const id = element.dataset.id || "";
    try {
      if (action === "goto-schedule") {
        switchTab("schedule");
      } else if (action === "goto-queue") {
        switchTab("queue");
      } else if (action === "preview") {
        triggerAction("generate_preview", { dryRun: true });
      } else if (action === "post-now-sheet") {
        openPostNowSheet();
      } else if (action === "resume-posting") {
        updateConfig((config) => {
          config.posting_paused = false;
        }, { message: "Resume posting", immediate: true });
        toast("Posting resumed.");
      } else if (action === "open-run") {
        openRunSheet();
      } else if (action === "open-card") {
        if (id) openCardViewer(id);
      } else if (action === "publish-item") {
        publishQueueItem(id);
      } else if (action === "regenerate-item") {
        openRegenerateSheet(id);
      } else if (action === "discard-item") {
        discardQueueItem(id);
      } else if (action === "open-post") {
        openPostViewer(id);
      } else if (action === "open-history") {
        openHistorySheet();
      } else if (action === "retry-load") {
        await refreshAll({ force: true, preserveScroll: true });
      } else if (action === "toggle-paused") {
        const paused = Boolean(state.config.posting_paused);
        updateConfig((config) => {
          config.posting_paused = !paused;
        }, { message: paused ? "Resume posting" : "Pause posting", immediate: true });
        toast(paused ? "Posting resumed." : "Posting paused. Scheduled runs will not post.");
      } else if (action === "set-mode") {
        const value = element.dataset.value === "auto" ? "auto" : "approve";
        updateConfig((config) => {
          config.mode = value;
        }, { message: "Update default posting mode" });
      } else if (action === "max-posts") {
        const delta = Number(element.dataset.delta) || 0;
        updateConfig((config) => {
          config.max_posts_per_day = Math.max(1, Math.min(10, (Number(config.max_posts_per_day) || 1) + delta));
        }, { message: "Update daily post limit" });
      } else if (action === "toggle-slot") {
        updateConfig((config) => {
          const slot = config.schedule.find((candidate) => candidate.id === id);
          if (slot) slot.enabled = slot.enabled === false;
        }, { message: "Toggle posting slot" });
      } else if (action === "toggle-slot-day") {
        const day = Number(element.dataset.day);
        updateConfig((config) => {
          const slot = config.schedule.find((candidate) => candidate.id === id);
          if (!slot) return;
          const days = new Set(Array.isArray(slot.days) ? slot.days : []);
          if (days.has(day)) {
            if (days.size === 1) {
              toast("Keep at least one day enabled.");
              return;
            }
            days.delete(day);
          } else {
            days.add(day);
          }
          slot.days = Array.from(days).sort((a, b) => a - b);
        }, { message: "Update slot days" });
      } else if (action === "set-slot-mode") {
        const value = ["global", "auto", "approve"].includes(element.dataset.value) ? element.dataset.value : "global";
        updateConfig((config) => {
          const slot = config.schedule.find((candidate) => candidate.id === id);
          if (slot) slot.mode = value;
        }, { message: "Update slot mode" });
      } else if (action === "add-slot") {
        openSlotEditor();
      } else if (action === "edit-slot") {
        openSlotEditor(id);
      } else if (action === "toggle-topic") {
        toggleTopic(element.dataset.topic);
      } else if (action === "add-keyword") {
        const list = element.dataset.list === "mute" ? "mute" : "prefer";
        const input = view.querySelector(`[data-keyword-input="${list}"]`);
        addKeyword(list, input?.value || "");
      } else if (action === "remove-keyword") {
        const list = element.dataset.list === "mute" ? "mute" : "prefer";
        const key = list === "mute" ? "mute_keywords" : "prefer_keywords";
        const word = element.dataset.word;
        updateConfig((config) => {
          config[key] = (config[key] || []).filter((candidate) => candidate !== word);
        }, { message: `Remove ${list} keyword` });
      } else if (action === "choose-style" || action === "choose-style-auto") {
        const value = action === "choose-style-auto" ? "auto" : Number(element.dataset.style);
        updateConfig((config) => {
          config.style = value === "auto" ? "auto" : value;
        }, { message: "Update card style" });
      } else if (action === "toggle-avoid-repeat") {
        updateConfig((config) => {
          config.avoid_repeat_style = !config.avoid_repeat_style;
        }, { message: "Update style repetition" });
      } else if (action === "set-accent") {
        const colour = element.dataset.colour;
        if (!/^#[0-9A-Fa-f]{6}$/.test(colour || "")) return;
        updateConfig((config) => {
          config.brand.accent_color = colour.toUpperCase();
        }, { message: "Update brand accent" });
      } else if (action === "save-brand") {
        await saveBrandDetails();
      } else if (action === "upload-logo") {
        $("logo-file")?.click();
      } else if (action === "remove-logo") {
        updateConfig((config) => {
          config.brand.logo_path = "";
        }, { message: "Remove brand logo", immediate: true });
        toast("Logo removed from cards.");
      } else if (action === "reorder-provider") {
        reorderProvider(element.dataset.group, element.dataset.id, element.dataset.dir);
      } else if (action === "toggle-image-provider" || action === "toggle-llm-provider") {
        toggleProvider(action === "toggle-image-provider" ? "image" : "llm", element.dataset.id);
      } else if (action === "toggle-image-pref") {
        updateConfig((config) => {
          config.image.prefer_article_photo = !config.image.prefer_article_photo;
        }, { message: "Update article photo preference" });
      } else if (action === "toggle-image-credit") {
        updateConfig((config) => {
          config.image.show_credit = !config.image.show_credit;
        }, { message: "Update photo credit setting" });
      } else if (action === "test-connection") {
        await testConnection();
      } else if (action === "clear-cache") {
        cacheClear();
        toast("Offline cache cleared.");
      } else if (action === "disconnect") {
        disconnect();
      } else if (action === "clear-history") {
        clearHistory();
      } else if (action === "session-help") {
        openSessionHelp();
      }
    } catch (error) {
      toast(friendlyError(error));
    }
  }

  function newSetupDraft() {
    const savedRepo = safeStoreGet(REPO_KEY) || "";
    return {
      step: 1,
      repoInput: savedRepo,
      token: "",
      owner: "",
      name: "",
      branch: "main",
      auth: null,
      config: null,
      sha: null,
      topics: null,
      times: ["05:30"],
      preset: "05:30",
      mode: "approve",
      error: "",
      busy: false,
    };
  }

  function showOnboarding() {
    state.screen = "onboarding";
    shell.hidden = true;
    onboarding.hidden = false;
    if (!state.setupDraft) state.setupDraft = newSetupDraft();
    renderOnboarding(true);
  }

  function renderOnboarding(resetScroll = false) {
    const draft = state.setupDraft;
    if (!draft) return;
    const previousScroll = onboarding.scrollTop;
    const progress = [1, 2, 3].map((step) => `<span class="${draft.step === step ? "active" : ""}"></span>`).join("");
    let stepBody = "";
    if (draft.step === 1) {
      stepBody = `
        <form id="ob-connect" class="onboard-step">
          <p class="eyebrow">Step 1 of 3</p>
          <h1>Connect your<br>newsroom.</h1>
          <p class="lede">Point this dashboard at the GitHub repository that runs your NewsCard Studio. The repo holds your settings, queue, history, and cards.</p>
          <div class="form-field">
            <label for="ob-repo">Repository</label>
            <input class="input" id="ob-repo" type="text" value="${esc(draft.repoInput)}" placeholder="yourname/newscard-studio" autocomplete="off" autocapitalize="none" spellcheck="false" required>
            <span class="field-help">Use the owner/name format, not the full URL.</span>
          </div>
          <div class="form-field">
            <label for="ob-token">Fine-grained token</label>
            <input class="input" id="ob-token" type="password" value="${esc(draft.token)}" placeholder="github_pat_..." autocomplete="off" autocapitalize="none" spellcheck="false" required>
            <span class="field-help">Contents and Actions: Read and write. Stored only in this browser.</span>
          </div>
          <button class="help-link" type="button" data-onboard="help-token">${icon("help")} Where do I get this token?</button>
          ${draft.error ? `<div class="run-error-box" role="alert" style="margin-top:12px"><strong>Could not connect</strong>${esc(draft.error)}</div>` : ""}
          <div class="onboard-footer">
            <button class="btn btn-primary btn-block" type="submit" ${draft.busy ? "disabled" : ""}>${draft.busy ? "Checking access..." : "Connect repository"}</button>
            <p class="tiny muted" style="text-align:center;margin-top:10px;line-height:1.5">A fine-grained token limited to this one repo is enough.</p>
          </div>
        </form>
      `;
    } else if (draft.step === 2) {
      stepBody = `
        <div class="onboard-step">
          <p class="eyebrow">Step 2 of 3</p>
          <h1>Pick your beat.</h1>
          <p class="lede">Enable the topics your audience should see. The pipeline balances the mix and avoids crowding one category.</p>
          <div class="topic-grid">
            ${CATEGORIES.map(([id, label, tone]) => `
              <button class="topic-choice ${tone}" type="button" data-onboard="topic" data-topic="${id}" aria-pressed="${Boolean(draft.config.topics?.[id])}">
                <span>${esc(label)}</span>
                <span class="check">${draft.config.topics?.[id] ? icon("check") : ""}</span>
              </button>
            `).join("")}
          </div>
          <div class="onboard-footer">
            <button class="btn btn-primary btn-block" type="button" data-onboard="step3" ${topicCount(draft.config) ? "" : "disabled"}>Continue</button>
            <button class="help-link" type="button" data-onboard="back" style="width:100%;justify-content:center">Back</button>
          </div>
        </div>
      `;
    } else {
      const custom = draft.preset === "custom";
      const actionsDisabled = draft.busy || (custom && draft.times.length === 0);
      stepBody = `
        <div class="onboard-step">
          <p class="eyebrow">Step 3 of 3</p>
          <h1>Set the rhythm.</h1>
          <p class="lede">Choose when the newsroom may publish. You can edit days, modes, and extra slots later.</p>
          <div class="preset-grid" role="group" aria-label="Schedule preset">
            ${PRESETS.map((preset) => {
              const selected = draft.preset === preset.id;
              return `
                <button class="preset" type="button" data-onboard="preset" data-preset="${preset.id}" aria-pressed="${selected}">
                  <span>
                    <strong>${esc(preset.name)}</strong>
                    <span>${esc(preset.note)}</span>
                  </span>
                  <span class="preset-time">${preset.id === "custom" ? "Own" : esc(formatTime12Text(preset.id))}</span>
                </button>
              `;
            }).join("")}
          </div>
          ${custom ? `
            <div class="custom-time">
              <div class="section-head" style="margin:16px 0 6px">
                <h2 style="font-size:14px">Your times</h2>
                <span class="tiny muted">${draft.times.length}/3 selected</span>
              </div>
              <div class="time-grid" role="group" aria-label="Choose posting times">
                ${Array.from({ length: 48 }, (_, index) => minutesToTime(index * 30)).map((time) => `
                  <button class="time-chip" type="button" data-onboard="time" data-time="${time}" aria-pressed="${draft.times.includes(time)}">${esc(formatTime12Text(time))}</button>
                `).join("")}
              </div>
            </div>
          ` : ""}
          <div class="section-head" style="margin:20px 0 8px"><h2 style="font-size:14px">Default mode</h2></div>
          <div class="segmented" role="group" aria-label="Default posting mode">
            <button type="button" data-onboard="mode" data-value="approve" aria-pressed="${draft.mode === "approve"}">Review first</button>
            <button type="button" data-onboard="mode" data-value="auto" aria-pressed="${draft.mode === "auto"}">Auto-post</button>
          </div>
          <p class="tiny muted" style="margin-top:8px;line-height:1.5">Review keeps every card in the Queue first. Auto-posts publish at the selected time.</p>
          ${draft.error ? `<div class="run-error-box" role="alert" style="margin-top:12px"><strong>Could not save</strong>${esc(draft.error)}</div>` : ""}
          <div class="onboard-footer">
            <button class="btn btn-primary btn-block" type="button" data-onboard="finish" ${actionsDisabled ? "disabled" : ""}>${draft.busy ? "Saving..." : "Enter the newsroom"}</button>
            <button class="help-link" type="button" data-onboard="back" style="width:100%;justify-content:center">Back</button>
          </div>
        </div>
      `;
    }
    onboarding.innerHTML = `
      <div class="onboard-top">
        <div class="onboard-brand">
          <div class="brand-avatar" aria-hidden="true">N</div>
          NewsCard Studio
        </div>
        <div class="progress-dots" aria-label="Setup progress">${progress}</div>
      </div>
      ${stepBody}
    `;
    if (resetScroll) onboarding.scrollTop = 0;
    else onboarding.scrollTop = previousScroll;
  }

  async function verifySetup() {
    const draft = state.setupDraft;
    if (!draft || draft.busy) return;
    const repoInput = $("ob-repo")?.value.trim() || "";
    const tokenInput = $("ob-token")?.value.trim() || "";
    const parsed = splitRepo(repoInput);
    if (!parsed) {
      draft.error = "Enter the repository as owner/name, for example yourname/newscard-studio.";
      renderOnboarding(true);
      return;
    }
    if (!tokenInput) {
      draft.error = "Paste a fine-grained GitHub token with Contents and Actions write access.";
      renderOnboarding(true);
      return;
    }
    draft.repoInput = repoInput;
    draft.token = tokenInput;
    draft.error = "";
    draft.busy = true;
    renderOnboarding(true);
    try {
      const repoResponse = await apiRequest(`/repos/${encodeURIComponent(parsed.owner)}/${encodeURIComponent(parsed.name)}`, {
        token: tokenInput,
      });
      const repoMeta = repoResponse.data || {};
      const branch = repoMeta.default_branch || "main";
      const auth = { token: tokenInput, owner: parsed.owner, name: parsed.name, branch };
      let configFile;
      try {
        configFile = await fetchFile("data/config.json", { auth, force: true, branch });
      } catch (error) {
        if (error.status === 404) {
          throw new ApiError(404, "Repository connected, but data/config.json was not found. Copy the full NewsCard Studio data folder into the repo.");
        }
        throw error;
      }
      const config = mergeConfig(configFile.data);
      const times = Array.from(new Set((config.schedule || []).map((slot) => normalizeTime(slot.time)))).slice(0, 3);
      draft.owner = parsed.owner;
      draft.name = parsed.name;
      draft.branch = branch;
      draft.auth = auth;
      draft.config = config;
      draft.sha = configFile.sha;
      draft.times = times.length ? times : ["05:30"];
      const singlePreset = draft.times.length === 1 && PRESETS.some((preset) => preset.id === draft.times[0]);
      draft.preset = singlePreset ? draft.times[0] : times.length ? "custom" : "05:30";
      draft.mode = config.mode === "auto" ? "auto" : "approve";
      draft.step = 2;
      draft.busy = false;
      renderOnboarding(true);
    } catch (error) {
      draft.busy = false;
      draft.error = friendlyError(error);
      if (error.status === 404 && error.message.includes("Could not reach")) {
        draft.error = "Repository connected, but data/config.json was not found. Copy the full NewsCard Studio data folder into the repo.";
      }
      renderOnboarding(true);
    }
  }

  async function finishSetup() {
    const draft = state.setupDraft;
    if (!draft || draft.busy || !draft.config) return;
    if (!topicCount(draft.config)) {
      draft.error = "Choose at least one topic.";
      renderOnboarding(false);
      return;
    }
    const times = Array.from(new Set(draft.times.map(normalizeTime))).sort((a, b) => timeToMinutes(a) - timeToMinutes(b));
    if (!times.length) {
      draft.error = "Choose at least one posting time.";
      renderOnboarding(false);
      return;
    }
    draft.busy = true;
    draft.error = "";
    renderOnboarding(false);
    try {
      const config = deepClone(draft.config);
      let timezone = draft.config.timezone || "Asia/Kolkata";
      try {
        const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (detected) {
          new Intl.DateTimeFormat("en-US", { timeZone: detected });
          timezone = detected;
        }
      } catch {
        timezone = draft.config.timezone || "Asia/Kolkata";
      }
      config.timezone = timezone;
      config.mode = draft.mode;
      config.posting_paused = false;
      config.schedule = times.map((time) => ({
        id: `slot_${time.replace(":", "")}`,
        time,
        days: [0, 1, 2, 3, 4, 5, 6],
        enabled: true,
        mode: "global",
        topic_override: "",
      }));
      const result = await putJsonFile("data/config.json", config, "Configure NewsCard Studio from dashboard", {
        auth: draft.auth,
        sha: draft.sha,
      });
      state.token = draft.token;
      state.owner = draft.owner;
      state.name = draft.name;
      state.branch = draft.branch;
      state.setup = true;
      state.config = mergeConfig(config);
      state.queue = { items: [] };
      state.history = { posts: [], used_photos: [], meta: { last_style: null, last_run: null } };
      state.status = { stage: "idle", message: "Waiting for the first run." };
      state.loading = false;
      state.setupDraft = null;
      state.activeTab = "home";
      safeStoreSet(TOKEN_KEY, draft.token);
      safeStoreSet(REPO_KEY, `${draft.owner}/${draft.name}`);
      safeStoreSet(BRANCH_KEY, draft.branch);
      safeStoreSet(SETUP_KEY, "1");
      safeStoreSet(TAB_KEY, "home");
      cacheWrite("data/config.json", {
        data: deepClone(config),
        sha: result.sha,
        etag: null,
        savedAt: Date.now(),
        path: "data/config.json",
      });
      showShell();
      refreshChrome();
      renderView();
      toast("Newsroom connected. Your schedule is live.");
      startPolling(2500);
      refreshAll({ initial: true }).catch(() => {});
    } catch (error) {
      draft.busy = false;
      draft.error = friendlyError(error);
      renderOnboarding(false);
    }
  }

  function handleOnboardClick(event) {
    const target = event.target.closest("[data-onboard]");
    if (!target) return;
    const draft = state.setupDraft;
    if (!draft) return;
    const action = target.dataset.onboard;
    if (action === "retry") {
      location.reload();
      return;
    }
    if (action === "reconnect") {
      clearSavedSetup();
      location.reload();
      return;
    }
    if (action === "help-token") {
      openTokenHelp();
      return;
    }
    if (draft.busy) return;
    if (action === "back") {
      draft.step = Math.max(1, draft.step - 1);
      draft.error = "";
      renderOnboarding(true);
      return;
    }
    if (action === "step3") {
      if (!topicCount(draft.config)) {
        toast("Choose at least one topic.");
        return;
      }
      draft.step = 3;
      draft.error = "";
      renderOnboarding(true);
      return;
    }
    if (action === "topic") {
      const id = target.dataset.topic;
      const enabled = CATEGORIES.filter(([key]) => Boolean(draft.config.topics?.[key]));
      if (draft.config.topics?.[id] && enabled.length === 1) {
        toast("Keep at least one topic enabled.");
        return;
      }
      draft.config.topics[id] = !draft.config.topics[id];
      renderOnboarding(false);
      return;
    }
    if (action === "preset") {
      const preset = target.dataset.preset;
      draft.preset = preset;
      if (preset === "custom") {
        if (!draft.times.length) draft.times = ["05:30"];
      } else {
        draft.times = [preset];
      }
      renderOnboarding(false);
      return;
    }
    if (action === "time") {
      const time = target.dataset.time;
      if (draft.times.includes(time)) {
        draft.times = draft.times.filter((value) => value !== time);
      } else {
        if (draft.times.length >= 3) {
          toast("Choose up to three posting times.");
          return;
        }
        draft.times = [...draft.times, time].sort((a, b) => timeToMinutes(a) - timeToMinutes(b));
      }
      renderOnboarding(false);
      return;
    }
    if (action === "mode") {
      draft.mode = target.dataset.value === "auto" ? "auto" : "approve";
      renderOnboarding(false);
      return;
    }
    if (action === "finish") {
      finishSetup();
    }
  }

  function handleViewClick(event) {
    const target = event.target.closest("[data-action]");
    if (!target || !view.contains(target) || target.disabled) return;
    event.preventDefault();
    handleViewAction(target.dataset.action, target);
  }

  function bindGlobalEvents() {
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => switchTab(tab.dataset.tab));
    });
    const tabbar = document.querySelector(".tabbar");
    tabbar?.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const tabs = Array.from(document.querySelectorAll(".tab"));
      const current = tabs.indexOf(document.activeElement);
      let next = current;
      if (event.key === "ArrowLeft") next = current <= 0 ? tabs.length - 1 : current - 1;
      if (event.key === "ArrowRight") next = current >= tabs.length - 1 ? 0 : current + 1;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabs.length - 1;
      tabs[next]?.focus();
      tabs[next]?.click();
    });
    $("run-status").addEventListener("click", openRunSheet);
    view.addEventListener("click", handleViewClick);
    onboarding.addEventListener("click", handleOnboardClick);
    onboarding.addEventListener("submit", (event) => {
      event.preventDefault();
      verifySetup();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && state.screen === "app") pollStatus(true);
    });
    let pullStart = null;
    let pullDistance = 0;
    view.addEventListener("touchstart", (event) => {
      if (state.sheetController || state.viewerController) return;
      if (view.scrollTop > 0 || event.touches.length !== 1) return;
      pullStart = event.touches[0].clientY;
      pullDistance = 0;
    }, { passive: true });
    view.addEventListener("touchmove", (event) => {
      if (pullStart === null || view.scrollTop > 0) return;
      const distance = event.touches[0].clientY - pullStart;
      pullDistance = Math.max(0, distance);
      const indicator = $("pull-indicator");
      if (indicator) indicator.classList.toggle("visible", pullDistance > 42);
    }, { passive: true });
    view.addEventListener("touchend", () => {
      const indicator = $("pull-indicator");
      indicator?.classList.remove("visible");
      if (pullDistance > 68 && state.screen === "app") {
        if (state.online) {
          refreshAll({ force: true, preserveScroll: true }).catch(() => {});
          pollStatus(true);
        } else {
          toast("You are offline. Reconnect to refresh.");
        }
      }
      pullStart = null;
      pullDistance = 0;
    }, { passive: true });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (state.viewerController) {
        event.preventDefault();
        closeViewer();
      } else if (state.sheetController) {
        event.preventDefault();
        closeSheet();
      }
    });
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(() => {});
    });
  }

  function startPolling(delay) {
    schedulePoll(delay || 6000);
  }

  function init() {
    bindGlobalEvents();
    setOnline(navigator.onLine);
    const token = safeStoreGet(TOKEN_KEY) || "";
    const repo = safeStoreGet(REPO_KEY) || "";
    const branch = safeStoreGet(BRANCH_KEY) || "main";
    const parsed = splitRepo(repo);
    const hasSetup = safeStoreGet(SETUP_KEY) === "1";
    if (token && parsed && hasSetup) {
      state.token = token;
      state.owner = parsed.owner;
      state.name = parsed.name;
      state.branch = branch;
      state.setup = true;
      showShell();
      hydrateFromCache();
      if (state.config) {
        state.loading = false;
        renderChrome();
        renderView();
      } else {
        state.loading = true;
        view.innerHTML = skeletonView();
      }
      refreshAll({ initial: true }).catch(() => {});
      startPolling(3000);
    } else {
      showOnboarding();
    }
    registerServiceWorker();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();