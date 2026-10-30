/**
 * Turns a report from the store, or a request from the app itself, into an
 * issue in the reports repository named by GITHUB_REPO.
 *
 * The store cannot open an issue itself: that needs a GitHub token, and a
 * token inside an APK is a token anyone holding the APK can lift. This worker
 * holds the token instead, as a secret, and accepts one narrow kind of request:
 * a report about one catalog package (POST /report), or a request about the
 * app itself (POST /feedback), each with a subject from a fixed list and a
 * short free text. Everything else is refused.
 *
 * Secrets and variables (set in the Cloudflare dashboard, never committed):
 *   GITHUB_TOKEN   fine-grained token, Issues: read and write, this repo only
 *   GITHUB_REPO    "abaye123/shani-shvilin-catalog"
 *   REPORT_KEY     a shared value the app sends in X-Report-Key. Not a secret
 *                  from someone who unpacks the APK, but it keeps the endpoint
 *                  closed to anything that merely found the URL.
 *
 * Abuse limits: one report per package and reason per IP per hour, and one
 * request per kind per IP per ten minutes, through the Cache API. A duplicate
 * of an open report becomes a comment on it rather than a new issue; requests
 * are each different and always open their own.
 *
 * Labels: "report" and "feedback" must exist in the repository.
 */

const REASONS = {
  not_working: "האפליקציה לא עובדת",
  blocked_content: "תוכן שצריך לחסום",
  missing_feature: "חלק באפליקציה חסום ולא צריך להיות",
  update_problem: "בעיה בהתקנה או בעדכון",
  inappropriate: "תוכן לא ראוי בחנות",
  other: "אחר",
};

const FEEDBACK_KINDS = {
  bug: "תקלה באפליקציה",
  filter: "בעיה בסינון",
  app_request: "בקשה להוספת אפליקציה",
  idea: "הצעה לשיפור",
  other: "אחר",
};

const PACKAGE_RE = /^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$/;
const MAX_DETAILS = 1500;
// The diagnostic log the app attaches on request, cut from the start so the
// newest lines are kept. Well inside the 65536 characters of an issue body.
const MAX_LOG = 50000;
const RATE_WINDOW_SECONDS = 3600;
const FEEDBACK_WINDOW_SECONDS = 600;

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (request.method !== "POST" || (path !== "/report" && path !== "/feedback")) {
      return json({ ok: false, error: "not_found" }, 404);
    }
    if (request.headers.get("X-Report-Key") !== env.REPORT_KEY) {
      return json({ ok: false, error: "forbidden" }, 403);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ ok: false, error: "bad_json" }, 400);
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";

    if (path === "/feedback") {
      const feedback = validateFeedback(body);
      if (typeof feedback === "string") return json({ ok: false, error: feedback }, 400);
      if (await limited(`feedback/${encodeURIComponent(ip)}/${feedback.kind}`, FEEDBACK_WINDOW_SECONDS)) {
        return json({ ok: false, error: "too_many" }, 429);
      }
      try {
        return json({ ok: true, ...(await fileFeedback(env, feedback)) });
      } catch (e) {
        return json({ ok: false, error: "github", detail: String(e).slice(0, 200) }, 502);
      }
    }

    const report = validate(body);
    if (typeof report === "string") return json({ ok: false, error: report }, 400);

    if (await rateLimited(ip, report)) {
      return json({ ok: false, error: "too_many" }, 429);
    }

    try {
      const result = await fileIssue(env, report);
      return json({ ok: true, ...result });
    } catch (e) {
      return json({ ok: false, error: "github", detail: String(e).slice(0, 200) }, 502);
    }
  },
};

function validate(body) {
  if (!body || typeof body !== "object") return "bad_body";
  const packageName = String(body.packageName || "");
  if (!PACKAGE_RE.test(packageName) || packageName.length > 200) return "bad_package";
  const reason = String(body.reason || "");
  if (!(reason in REASONS)) return "bad_reason";
  return {
    packageName,
    reason,
    details: clean(body.details, MAX_DETAILS),
    appName: clean(body.appName, 100),
    appVersion: clean(body.appVersion, 60),
    installedVersion: clean(body.installedVersion, 60),
    storeVersion: clean(body.storeVersion, 60),
    catalogRevision: clean(body.catalogRevision, 60),
    userMode: clean(body.userMode, 40),
    device: clean(body.device, 100),
    sdk: clean(body.sdk, 10),
    log: cleanLog(body.log),
  };
}

function validateFeedback(body) {
  if (!body || typeof body !== "object") return "bad_body";
  const kind = String(body.kind || "");
  if (!(kind in FEEDBACK_KINDS)) return "bad_kind";
  const details = clean(body.details, MAX_DETAILS);
  if (details.length < 10) return "too_short";
  return {
    kind,
    details,
    appVersion: clean(body.appVersion, 60),
    catalogRevision: clean(body.catalogRevision, 60),
    userMode: clean(body.userMode, 40),
    device: clean(body.device, 100),
    sdk: clean(body.sdk, 10),
    log: cleanLog(body.log),
  };
}

/** The diagnostic log: lines kept, the newest end kept, no mentions. */
function cleanLog(value) {
  return String(value ?? "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "")
    .replace(/@/g, "@​")
    .slice(-MAX_LOG)
    .trim();
}

/** The log as a collapsed block at the end of an issue, or nothing. */
function logBlock(log) {
  if (!log) return [];
  return [
    "",
    "<details><summary>יומן אבחון (30 הדקות האחרונות)</summary>",
    "",
    "````text",
    log.replace(/````/g, "```"),
    "````",
    "",
    "</details>",
  ];
}

/** Plain text, bounded, with nothing that GitHub would turn into a mention or a link to run. */
function clean(value, max) {
  return String(value ?? "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "")
    .replace(/@/g, "@​")
    .slice(0, max)
    .trim();
}

async function rateLimited(ip, report) {
  return limited(
    `${encodeURIComponent(ip)}/${report.packageName}/${report.reason}`,
    RATE_WINDOW_SECONDS,
  );
}

async function limited(path, seconds) {
  const cache = caches.default;
  const key = new Request(`https://rate.limit/${path}`);
  if (await cache.match(key)) return true;
  await cache.put(key, new Response("1", { headers: { "Cache-Control": `max-age=${seconds}` } }));
  return false;
}

async function fileFeedback(env, feedback) {
  // The first words of the text make the title, so the issue list reads as a
  // list of subjects rather than a column of identical "request" lines.
  const firstLine = feedback.details.split("\n")[0];
  const summary = firstLine.length > 60 ? `${firstLine.slice(0, 60)}…` : firstLine;
  const title = `[${FEEDBACK_KINDS[feedback.kind]}] ${summary}`;
  const body = [
    `<!-- feedback:${feedback.kind} -->`,
    `**נושא:** ${FEEDBACK_KINDS[feedback.kind]}`,
    "",
    feedback.details,
    "",
    "| | |",
    "|---|---|",
    `| גרסת שני שבילין | ${feedback.appVersion || "-"} |`,
    `| מהדורת קטלוג | ${feedback.catalogRevision || "-"} |`,
    `| מצב סינון | ${feedback.userMode || "-"} |`,
    `| מכשיר | ${feedback.device || "-"} (SDK ${feedback.sdk || "-"}) |`,
    ...logBlock(feedback.log),
  ].join("\n");

  const created = await github(env, `/repos/${env.GITHUB_REPO}/issues`, {
    method: "POST",
    body: JSON.stringify({ title, body, labels: ["feedback"] }),
  });
  return { issue: created.number, duplicate: false };
}

async function fileIssue(env, report) {
  const title = `[דיווח] ${report.appName || report.packageName}: ${REASONS[report.reason]}`;
  const marker = `<!-- report:${report.packageName}:${report.reason} -->`;
  const body = [
    marker,
    `**אפליקציה:** ${report.appName || "-"} (\`${report.packageName}\`)`,
    `**סיבה:** ${REASONS[report.reason]}`,
    "",
    report.details ? report.details : "_לא נכתב פירוט._",
    "",
    "| | |",
    "|---|---|",
    `| גרסה מותקנת | ${report.installedVersion || "-"} |`,
    `| גרסה בחנות | ${report.storeVersion || "-"} |`,
    `| גרסת שני שבילין | ${report.appVersion || "-"} |`,
    `| מהדורת קטלוג | ${report.catalogRevision || "-"} |`,
    `| מצב סינון | ${report.userMode || "-"} |`,
    `| מכשיר | ${report.device || "-"} (SDK ${report.sdk || "-"}) |`,
    ...logBlock(report.log),
  ].join("\n");

  // An open report on the same package and reason gets a comment, not a twin.
  const query = encodeURIComponent(
    `repo:${env.GITHUB_REPO} is:issue is:open in:body "report:${report.packageName}:${report.reason}"`,
  );
  const search = await github(env, `/search/issues?q=${query}&per_page=1`);
  const existing = search.items && search.items[0];
  if (existing) {
    await github(env, `/repos/${env.GITHUB_REPO}/issues/${existing.number}/comments`, {
      method: "POST",
      body: JSON.stringify({ body: `דיווח נוסף:\n\n${body}` }),
    });
    return { issue: existing.number, duplicate: true };
  }

  const created = await github(env, `/repos/${env.GITHUB_REPO}/issues`, {
    method: "POST",
    body: JSON.stringify({ title, body, labels: ["report"] }),
  });
  return { issue: created.number, duplicate: false };
}

async function github(env, path, init = {}) {
  const response = await fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "shani-shvilin-report-worker",
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) throw new Error(`GitHub ${response.status}: ${await response.text()}`);
  return response.json();
}

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
