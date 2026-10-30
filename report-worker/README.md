# report-worker

Turns a report from the store, or a request from the app itself (POST
/feedback, label "feedback"), into an issue in the private reports repository. Deployed as
the Cloudflare Worker `shani-shvilin-report`
(`https://shani-shvilin-report.8140hp.workers.dev/report`).

The store cannot open an issue itself: that needs a GitHub token, and a token
inside an APK can be lifted by anyone holding the APK. The worker holds it.

## Settings (Cloudflare dashboard, never committed)

| Name | Kind | Value |
|---|---|---|
| `GITHUB_TOKEN` | secret | fine-grained token, Issues read/write, the reports repository only |
| `GITHUB_REPO` | variable | `abaye123/shani-shvilin-support` (private) |

Reports go to a private repository, not to this public one: they carry the
device model and free text, and may carry the app's diagnostic log, which
names installed applications and the sites that were blocked. The labels
`report` and `feedback` must exist there.
| `REPORT_KEY` | secret | the same value as `ReportClient.REPORT_KEY` in the app |

## Behaviour

- `POST /report` with `X-Report-Key` and a JSON body; anything else is refused.
- The reason must be one of the keys in `REASONS`; free text is capped and
  stripped of `@` mentions.
- One report per IP, package and reason per hour.
- An open issue for the same package and reason gets a comment instead of a
  new issue. New issues carry the `report` label.
- Either kind may carry `log`, the last minutes of the app's diagnostic log,
  sent only when the user leaves "attach the diagnostic log" ticked. It is
  cut to its newest 50000 characters and added as a collapsed block.

## Deploying

Paste `worker.js` into the worker's editor in the dashboard and deploy. The
`workers.dev` address has to be allowed by network filters (NetFree) for
reports to reach it from filtered devices.
