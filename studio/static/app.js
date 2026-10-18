// Catalog Studio front end. Talks to studio.py on the same origin; no build step.
const $ = (id) => document.getElementById(id);
const MAX_SHOTS = 8;
const CATEGORY_LABELS = {
  NAVIGATION: "ניווט", MAIL: "דואר", COMMUNICATION: "תקשורת", MUSIC_AUDIO: "מוזיקה ואודיו",
  VIDEO: "וידאו", TORAH: "תורה", PRODUCTIVITY: "פרודוקטיביות", TOOLS: "כלים", FINANCE: "פיננסים",
  HEALTH_FITNESS: "בריאות", NEWS: "חדשות", GOVERNMENT: "ממשלה", HOME: "בית חכם", SYSTEM: "מערכת",
};
const MODE_LABELS = {
  OFFLINE: "0 - ללא רשת", LOCAL_ONLY: "1 - רשת מקומית", NAVIGATION_ONLY: "2 - ניווט בלבד",
  NAVIGATION_AND_MAIL_ONLY: "3 - ניווט ודואר", REDUCED_RISK: "4 - סיכון מופחת", MOST_OPEN: "5 - הכי פתוח",
};
const MODE_ORDER = Object.keys(MODE_LABELS);

let apps = [];
let current = null;        // the loaded entry, untouched fields kept on save
let currentPolicy = null;  // the loaded policy
let playShots = [];        // screenshot URLs Play offers
let chosen = [];           // screenshot URLs chosen, in order
let apk = null;            // the last APK read

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  return response.json();
}

function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 3500);
}

function showLog(text) {
  $("log-text").textContent = text;
  $("log").classList.remove("hidden");
}

async function busy(button, work) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "…" + label;
  try { return await work(); } finally { button.disabled = false; button.textContent = label; }
}

// ---------------------------------------------------------------- list

async function loadList(select) {
  const data = await api("/api/apps");
  apps = data.apps;
  fillSelect($("category"), data.categories, (c) => CATEGORY_LABELS[c] || c);
  fillSelect($("min-mode"), MODE_ORDER, (m) => MODE_LABELS[m]);
  renderList();
  refreshStatus();
  if (select) openApp(select);
}

function fillSelect(select, values, label) {
  if (select.options.length) return;
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label(value);
    select.appendChild(option);
  }
}

function renderList() {
  const filter = $("filter").value.trim().toLowerCase();
  const list = $("app-list");
  list.innerHTML = "";
  const groups = {};
  for (const app of apps) {
    if (filter && !app.name.toLowerCase().includes(filter) && !app.packageName.includes(filter)) continue;
    (groups[app.category] ||= []).push(app);
  }
  for (const [category, items] of Object.entries(groups)) {
    const head = document.createElement("li");
    head.className = "group";
    head.textContent = CATEGORY_LABELS[category] || category;
    list.appendChild(head);
    for (const app of items) {
      const li = document.createElement("li");
      li.dataset.pkg = app.packageName;
      if (current && current.packageName === app.packageName) li.classList.add("active");
      const marks = [
        app.grantsNetworkAccess ? "רשת" : "",
        app.availableInStore ? "" : "לא בחנות",
        app.screenshots ? `${app.screenshots} צילומים` : "",
        app.hasPolicy ? "מדיניות" : "",
      ].filter(Boolean).join(" · ");
      li.innerHTML = `<div>${escapeHtml(app.name)}</div><div class="pkg">${app.packageName}</div>` +
        (marks ? `<div class="muted">${marks}</div>` : "");
      li.onclick = () => openApp(app.packageName);
      list.appendChild(li);
    }
  }
}

async function refreshStatus() {
  const status = await api("/api/status");
  const lines = status.output ? status.output.split("\n").filter(Boolean).length : 0;
  $("repo-status").textContent = lines ? `${lines} קבצים שונו מאז ה-commit האחרון` : "אין שינויים שלא נשמרו ל-git";
}

// ---------------------------------------------------------------- editor

function showEditor() {
  $("welcome").classList.add("hidden");
  $("editor").classList.remove("hidden");
}

function blankEntry(pkg = "") {
  return {
    packageName: pkg, displayName: { he: "", en: "" }, category: "TOOLS", minimumVersionCode: 0,
    sha256: "", availableInStore: true, grantsNetworkAccess: false, minUserMode: "MOST_OPEN",
    flags: {}, screenshots: [],
  };
}

async function openApp(pkg) {
  const data = await api(`/api/app?pkg=${encodeURIComponent(pkg)}`);
  current = data.entry || blankEntry(pkg);
  currentPolicy = data.policy;
  fillForm(current, currentPolicy);
  showEditor();
  renderList();
  resetPlay();
  if (current.screenshots?.length) renderShots();
}

function newApp() {
  current = blankEntry();
  currentPolicy = null;
  fillForm(current, null);
  resetPlay();
  showEditor();
  $("pkg").focus();
}

function resetPlay() {
  playShots = [];
  apk = null;
  $("play-box").classList.add("hidden");
  $("apk-box").classList.add("hidden");
  $("found-hosts").innerHTML = "";
  renderShots();
}

function fillForm(entry, policy) {
  $("pkg").value = entry.packageName || "";
  $("pkg").readOnly = !!(entry.packageName && apps.some((a) => a.packageName === entry.packageName));
  $("name-he").value = entry.displayName?.he || "";
  $("name-en").value = entry.displayName?.en || "";
  $("category").value = entry.category || "TOOLS";
  $("min-mode").value = entry.minUserMode || "MOST_OPEN";
  $("min-version").value = entry.minimumVersionCode ?? 0;
  $("sha256").value = entry.sha256 || "";
  $("extra-sha").value = (entry.additionalSha256 || []).join("\n");
  $("source-type").value = entry.source?.type || "";
  $("source-id").value = entry.source?.id || "";
  $("source-url").value = entry.source?.directUrl || "";
  $("in-store").checked = entry.availableInStore !== false;
  $("network").checked = !!entry.grantsNetworkAccess;
  const flags = entry.flags || {};
  $("f-recommended").checked = !!flags.isRecommendedInStore;
  $("f-unmodest").checked = !!flags.hasUnmodestImage;
  $("f-dangerous").checked = !!flags.isPotentiallyDangerous;
  $("f-play").checked = !!flags.requiresPlayStoreInstallation;
  $("notes").value = entry.notes || "";
  chosen = [...(entry.screenshots || [])];

  $("has-policy").checked = !!policy;
  const fixed = !policy || policy.type === "Fixed";
  $("fixed-policy").classList.toggle("hidden", !fixed);
  $("raw-policy").classList.toggle("hidden", fixed);
  if (fixed) {
    const net = policy?.networkPolicy || { mode: "BLACKLIST" };
    $("net-mode").value = net.mode;
    $("net-desc").value = net.desc || "";
    $("hosts").value = (net.spec?.hosts || []).join("\n");
  } else {
    $("policy-json").value = JSON.stringify(policy, null, 2);
  }
  syncPolicyVisibility();
  $("save-result").textContent = "";
}

function syncPolicyVisibility() {
  $("policy-box").classList.toggle("hidden", !$("has-policy").checked);
  const listed = ["BLACKLIST", "WHITELIST"].includes($("net-mode").value);
  $("hosts-label").classList.toggle("hidden", !listed);
}

function lines(text) {
  return text.split(/\n/).map((s) => s.trim()).filter(Boolean);
}

function collect() {
  const entry = { ...current };
  entry.packageName = $("pkg").value.trim();
  entry.displayName = { ...(current.displayName || {}), he: $("name-he").value.trim(), en: $("name-en").value.trim() };
  entry.category = $("category").value;
  entry.minimumVersionCode = parseInt($("min-version").value || "0", 10);
  entry.sha256 = $("sha256").value.trim().toLowerCase();
  const extra = lines($("extra-sha").value).map((s) => s.toLowerCase());
  if (extra.length) entry.additionalSha256 = extra; else delete entry.additionalSha256;
  entry.availableInStore = $("in-store").checked;
  entry.grantsNetworkAccess = $("network").checked;
  entry.minUserMode = $("min-mode").value;
  const flags = {};
  if ($("f-recommended").checked) flags.isRecommendedInStore = true;
  if ($("f-unmodest").checked) flags.hasUnmodestImage = true;
  if ($("f-dangerous").checked) flags.isPotentiallyDangerous = true;
  if ($("f-play").checked) flags.requiresPlayStoreInstallation = true;
  if (Object.keys(flags).length) entry.flags = flags; else delete entry.flags;
  const type = $("source-type").value;
  if (type) {
    entry.source = { type, id: $("source-id").value.trim() || entry.packageName };
    if (type === "DIRECT_URL") entry.source.directUrl = $("source-url").value.trim();
    // GITHUB takes owner/repo as its id, or a github.com link in the URL field.
    if (type === "GITHUB" && $("source-url").value.trim()) entry.source.directUrl = $("source-url").value.trim();
  } else {
    delete entry.source;
  }
  if (chosen.length) entry.screenshots = [...chosen]; else delete entry.screenshots;
  const notes = $("notes").value.trim();
  if (notes) entry.notes = notes; else delete entry.notes;

  let policy = null;
  if ($("has-policy").checked) {
    if (!$("raw-policy").classList.contains("hidden")) {
      policy = JSON.parse($("policy-json").value);
    } else {
      const mode = $("net-mode").value;
      const networkPolicy = { mode };
      const desc = $("net-desc").value.trim();
      if (desc) networkPolicy.desc = desc;
      if (mode === "BLACKLIST" || mode === "WHITELIST") {
        networkPolicy.spec = { type: "HostList", hosts: lines($("hosts").value) };
      }
      policy = {
        ...(currentPolicy || {}), type: "Fixed", packageName: entry.packageName, category: entry.category,
        minimumVersionCode: entry.minimumVersionCode, networkPolicy,
      };
      if (entry.flags?.isRecommendedInStore) policy.isRecommendedInStore = true;
    }
  }
  return { entry, policy };
}

async function save() {
  let payload;
  try { payload = collect(); } catch (e) { return showResult(false, ["ה-JSON של המדיניות לא תקין: " + e.message]); }
  const result = await api("/api/save", payload);
  if (!result.ok) return showResult(false, result.errors || [result.error]);
  current = payload.entry;
  currentPolicy = payload.policy;
  showResult(true, result.warnings || []);
  await loadList();
}

function showResult(ok, messages) {
  const el = $("save-result");
  el.className = ok ? "ok" : "err";
  el.innerHTML = (ok ? "נשמר." : "לא נשמר:") +
    (messages.length ? "<br>" + messages.map(escapeHtml).join("<br>") : "");
}

// ---------------------------------------------------------------- Google Play

async function fetchPlay() {
  const pkg = $("pkg").value.trim();
  if (!pkg) return toast("הזינו שם חבילה");
  const data = await busy($("btn-play"), () => api(`/api/play?pkg=${encodeURIComponent(pkg)}`));
  if (!data.ok) return toast(data.error);
  const info = data.info;
  $("play-box").classList.remove("hidden");
  $("play-icon").src = info.icon || "";
  $("play-title").textContent = info.title || "";
  $("play-dev").textContent = info.developer || "";
  $("play-summary").textContent = info.summary || "";
  $("play-desc").textContent = (info.description || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "");
  const meta = [
    info.genre, info.installs && `${info.installs} התקנות`, info.score && `★ ${Number(info.score).toFixed(1)}`,
    info.version && `גרסה ${info.version}`, info.updated && `עודכן ${new Date(info.updated * 1000).toLocaleDateString("he-IL")}`,
    info.released && `הופצה ${info.released}`, info.contentRating, info.containsAds ? "מכילה פרסומות" : "",
    info.offersIAP ? "רכישות באפליקציה" : "", info.free === false ? "בתשלום" : "",
  ].filter(Boolean);
  $("play-meta").innerHTML = meta.map((m) => `<span class="chip">${escapeHtml(String(m))}</span>`).join("");

  // Fill only what is empty: an existing entry's names are someone's decision.
  if (!$("name-he").value) $("name-he").value = info.title || "";
  if (!$("name-en").value) $("name-en").value = info.title || "";
  if (!$("source-type").value) { $("source-type").value = "PLAY"; $("source-id").value = pkg; }
  playShots = info.screenshots || [];
  renderShots();
}

function renderShots() {
  const box = $("shots");
  box.innerHTML = "";
  const all = [...chosen, ...playShots.filter((u) => !chosen.includes(u))];
  for (const url of all) {
    const index = chosen.indexOf(url);
    const el = document.createElement("div");
    el.className = "shot" + (index >= 0 ? " selected" : "");
    el.innerHTML = `<img loading="lazy" src="${url}">` + (index >= 0 ? `<span class="badge">${index + 1}</span>` : "");
    el.onclick = () => toggleShot(url);
    box.appendChild(el);
  }
  $("shot-count").textContent = `(${chosen.length}/${MAX_SHOTS})`;
  if (!all.length) box.innerHTML = `<span class="muted">אין צילומים. שלפו מ-Google Play או הוסיפו כתובת.</span>`;
}

function toggleShot(url) {
  const index = chosen.indexOf(url);
  if (index >= 0) chosen.splice(index, 1);
  else if (chosen.length >= MAX_SHOTS) return toast(`אפשר לבחור עד ${MAX_SHOTS} צילומים`);
  else chosen.push(url);
  renderShots();
}

function addShot() {
  const url = $("shot-url").value.trim();
  if (!url.startsWith("https://")) return toast("כתובת התמונה חייבת להתחיל ב-https://");
  if (!chosen.includes(url) && chosen.length < MAX_SHOTS) chosen.push(url);
  $("shot-url").value = "";
  renderShots();
}

// ---------------------------------------------------------------- APK

async function fetchApk() {
  const pkg = $("pkg").value.trim();
  if (!pkg) return toast("הזינו שם חבילה");
  const data = await busy($("btn-apk"), () => api("/api/apk", { pkg }));
  const box = $("apk-box");
  box.classList.remove("hidden");
  if (!data.ok) { box.innerHTML = `<span class="err">${escapeHtml(data.error)}</span>`; return; }
  apk = data;
  const mismatch = data.packageName && data.packageName !== pkg;
  box.innerHTML = `
    <div><b>${escapeHtml(data.archive)}</b> · ${(data.size / 1048576).toFixed(1)} MB · ${data.files.length} קבצי APK</div>
    <div>גרסה: <span class="mono">${escapeHtml(data.versionName || "?")}</span> (versionCode <span class="mono">${data.versionCode ?? "?"}</span>)
      <button id="use-version">קביעה כגרסה מינימלית</button></div>
    ${mismatch ? `<div class="err">שימו לב: בקובץ כתוב ${escapeHtml(data.packageName)}</div>` : ""}
    ${data.sha256.map((s) => `<div>חתימה: <span class="mono">${s}</span> <button data-sha="${s}">שימוש</button></div>`).join("")}
    ${data.notes.map((n) => `<div class="muted">${escapeHtml(n)}</div>`).join("")}`;
  $("use-version")?.addEventListener("click", () => { $("min-version").value = data.versionCode; toast("עודכן"); });
  box.querySelectorAll("button[data-sha]").forEach((b) =>
    b.addEventListener("click", () => { $("sha256").value = b.dataset.sha; toast("עודכן"); }));
  if (!$("sha256").value && data.sha256.length === 1) $("sha256").value = data.sha256[0];
}

async function findHosts() {
  const pkg = $("pkg").value.trim();
  const data = await busy($("btn-hosts"), () => api("/api/hosts", { pkg }));
  const box = $("found-hosts");
  if (!data.ok) { box.innerHTML = `<span class="err">${escapeHtml(data.error)}</span>`; return; }
  const listed = new Set(lines($("hosts").value));
  const items = (hosts) => hosts.map((h) =>
    `<label><input type="checkbox" value="${escapeHtml(h)}" ${listed.has(h) ? "checked" : ""}>${escapeHtml(h)}</label>`).join("");
  const section = (title, hosts) => !hosts.length ? "" : `<h4>${title} (${hosts.length})</h4>` + items(hosts);
  box.innerHTML =
    section("מתוך הגדרות האבטחה של האפליקציה (האות החזק ביותר)", data.nsc) +
    section("מתוך כתובות מלאות בקוד", data.urls) +
    (data.bare.length ? `<details><summary>שמות שנראים כמו כתובות, רועש (${data.bare.length})</summary>${items(data.bare)}</details>` : "") ||
    `<span class="muted">לא נמצאו כתובות</span>`;
  box.querySelectorAll("input").forEach((input) => input.addEventListener("change", () => {
    const hosts = lines($("hosts").value);
    const next = input.checked ? [...new Set([...hosts, input.value])] : hosts.filter((h) => h !== input.value);
    $("hosts").value = next.join("\n");
  }));
}

// ---------------------------------------------------------------- repository

async function build() {
  const result = await busy($("btn-build"), () => api("/api/build", {}));
  showLog((result.ok ? "הבנייה הצליחה\n\n" : "הבנייה נכשלה\n\n") + result.output);
  refreshStatus();
}

async function release() {
  const key = prompt("נתיב למפתח הפרטי (ריק = ברירת המחדל של release.sh):", "") ?? null;
  if (key === null) return;
  const result = await busy($("btn-release"), () => api("/api/release", { key: key.trim() }));
  showLog((result.ok ? "נחתם בהצלחה\n\n" : "החתימה נכשלה\n\n") + result.output);
  refreshStatus();
}

async function commit() {
  const message = prompt("הודעת commit:", current ? `Update ${current.packageName}` : "Update catalog");
  if (!message) return;
  const result = await busy($("btn-commit"), () => api("/api/commit", { message }));
  showLog((result.ok ? "נשמר ל-git (בלי push)\n\n" : "ה-commit נכשל\n\n") + result.output);
  refreshStatus();
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------------------------------------------------------------- wiring

$("filter").addEventListener("input", renderList);
$("btn-new").onclick = newApp;
$("btn-play").onclick = fetchPlay;
$("btn-apk").onclick = fetchApk;
$("btn-hosts").onclick = findHosts;
$("btn-add-shot").onclick = addShot;
$("btn-save").onclick = save;
$("btn-build").onclick = build;
$("btn-release").onclick = release;
$("btn-commit").onclick = commit;
$("has-policy").onchange = syncPolicyVisibility;
$("net-mode").onchange = syncPolicyVisibility;
$("log-close").onclick = () => $("log").classList.add("hidden");
loadList(new URLSearchParams(location.search).get("pkg"));
