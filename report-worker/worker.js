/**
 * Turns a report from the store into an issue in this repository.
 *
 * The store cannot open an issue itself: that needs a GitHub token, and a
 * token inside an APK is a token anyone holding the APK can lift. This worker
 * holds the token instead, as a secret, and accepts one narrow kind of request:
 * a report about one catalog package, with a reason from a fixed list and a
 * short free text. Everything else is refused.
 *
 * Secrets and variables (set in the Cloudflare dashboard, never committed):
 *   GITHUB_TOKEN   fine-grained token, Issues: read and write, this repo only
 *   GITHUB_REPO    "abaye123/shani-shvilin-catalog"
 *   REPORT_KEY     a shared value the app sends in X-Report-Key. Not a secret
 *                  from someone who unpacks the APK, but it keeps the endpoint
 *                  closed to anything that merely found the URL.
 *
 * Abuse limits: one report per package and reason per IP per hour, through
 * the Cache API, and a duplicate of an open issue becomes a comment on it
 * rather than a new issue.
 */

const REASONS = {
  not_working: "האפליקציה לא עובדת",
  blocked_content: "תוכן שצריך לחסום",
  missing_feature: "חלק באפליקציה חסום ולא צריך להיות",
  update_problem: "בעיה בהתקנה או בעדכון",
  inappropriate: "תוכן לא ראוי בחנות",
  other: "אחר",
};

const PACKAGE_RE = /^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$/;
const MAX_DETAILS = 1500;
const RATE_WINDOW_SECONDS = 3600;

export default {
  async fetch(request, env) {
    if (request.method !== "POST" || new URL(request.url).pathname !== "/report") {
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

    const report = validate(body);
    if (typeof report === "string") return json({ ok: false, error: report }, 400);

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
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
  };
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
  const cache = caches.default;
  const key = new Request(
    `https://rate.limit/${encodeURIComponent(ip)}/${report.packageName}/${report.reason}`,
  );
  if (await cache.match(key)) return true;
  await cache.put(
    key,
    new Response("1", { headers: { "Cache-Control": `max-age=${RATE_WINDOW_SECONDS}` } }),
  );
  return false;
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
