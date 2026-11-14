# PayTrust: progress and plan

A plain-language record of what has been changed in PayTrust, why, and what comes next. Updated at the end of every phase.

*Last updated: 2026-11-14 · current work: Phase 3 on branch `v2.3-product`*

---

## 1. What PayTrust is

AI agents can now spend money for people. A buggy, confused or manipulated agent can overspend, pay a gambling site, repeat a purchase in a loop, or be driven by a stolen key. PayTrust sits between "the agent wants to pay" and "the money moves": the agent asks first, and PayTrust answers **ALLOW**, **ASK_USER** (a human must confirm) or **DENY**, with the evidence for the decision.

It started as a Razorpay Buildathon entry (Track 02, AI Risk Manager). The Buildathon is over; the goal now is a **real product**.

**The bigger vision (later):** an agentic-commerce product where a user gives an AI agent a task ("book me a hotel in Goa, 12–14 Dec, under ₹6,000/night"), the agent does the work (search, compare, choose) and, at checkout, asks the user to pay, with PayTrust making that payment safe. **Decision: build PayTrust completely first**, then the agent app on top of it.

## 2. How the work is done

| Rule | Why |
|---|---|
| Each phase gets its own git branch (`v2.1-hardening`, `v2.2-reliability`, `v2.3-product` …) | `main` only gets finished, tested work |
| One commit per fix, each with a test that fails without the fix | every change can be reviewed, reverted or explained on its own |
| Before every commit: full test suite, lint, console build | nothing lands broken |
| Risky changes are also tried against a real running server | tests can miss what only shows up in a real run |
| CI on GitHub runs everything on SQLite **and** PostgreSQL, builds and starts the Docker image | proves it works on the production database too |
| Nothing is pushed or merged to `main` without your OK | you stay in control of what is published |
| The demo lives only in `demo/` and never changes the product | the product stays clean |

## 3. Status at a glance

| Phase | Item | Status | Where |
|---|---|---|---|
| **1. Security** | ① Merchant-name spoofing | ✅ done | `main` |
| | ② Callback URLs could reach the internal network (SSRF) | ✅ done | `main` |
| | ③ Approval re-checks the mandate | ✅ done | `main` |
| | ④ Live feed no longer puts the login token in URLs | ✅ done | `main` |
| **CI** | PostgreSQL job was broken since Oct 28; a racing test | ✅ fixed, CI green | `main` |
| **Demo** | Full simulation for presenting (`demo/`) | ✅ done | branch `demo-simulation` |
| **2. Reliability** | ⑪ Durable background jobs (outbox, retries, dead letters) | ✅ done | `main` |
| | Dead-letter page in the console | ✅ done | `main` |
| | ⑫ `httpx2` test warning | ✅ done | `main` |
| **3. Product** | ⑧ Richer policies: 8a per-agent limits + user budget | ✅ done | `v2.3-product` |
| | ⑧ Richer policies: 8b–8f | 🔵 **in progress** | `v2.3-product` |
| | ⑦ MCP server + Python SDK for agents | ⬜ next | |
| | ⑤ Approval by the real user (signed link + email) | ⬜ needs email key + public URL | |
| | ⑥ Real money flow (PAID / FAILED / REFUNDED) | ⬜ needs Razorpay test keys + public URL | |
| **4. Scale** | ⑨ Multi-tenant workspaces | ⬜ | |
| | ⑩ ML trained on reviewer decisions | ⬜ | |
| | Rewrite the v1-era business docs | ⬜ needs your pricing | |

**Done: 6 of 12 roadmap items, plus the demo and the CI fix.**

## 4. What has been done, in plain words

### Phase 1: security (merged to `main`)

| # | Problem | What changed |
|---|---|---|
| ① | An agent could pay a **blocked** merchant by sending a fake, trusted-sounding merchant name; the console then showed the fake name | Policy checks use the merchant's **registered** name. A name that clearly doesn't match is flagged as high risk and never auto-allowed |
| ② | An agent could make PayTrust send requests to `localhost`, private networks or cloud metadata (`169.254.169.254`) through the callback URL | Callback URLs are checked when submitted and again just before sending. PayTrust connects only to a vetted public IP and never follows redirects |
| ③ | A reviewer could approve a payment after the agent was disabled, its key revoked (e.g. stolen) or the policy tightened | Approval re-runs every check against the current state. If anything no longer holds, the payment is rejected automatically and nothing is paid |
| ④ | The console's 12-hour login token was put in the live-feed URL, where logs record it | The live feed now opens with a 60-second, stream-only ticket |

### CI fix (merged to `main`)

CI's PostgreSQL job had failed on every push since the v2 rebuild: the `alembic` command could not import the app, so the "migrations match models" check never actually ran. One line in `backend/alembic.ini` fixed it. CI is fully green, the PostgreSQL comparison passes, and the Docker image job now runs too.

### Demo (branch `demo-simulation`)

A self-contained environment in `demo/` to show PayTrust to people: 40 dummy users, 4 AI agents, 15 merchants, 24 h of history, a stand-in payment gateway (DemoPay) that collects payments and sends signed webhooks, an inbox that receives the agents' callbacks, live agent traffic, and a 10-scene guided story with 30 automatic checks. One command starts it: `.venv\Scripts\python demo\run_demo.py --open`. Details: `demo/README.md`.

### Phase 2: reliability (merged to `main`)

| Problem | What changed |
|---|---|
| Creating the payment order, writing the AI note and calling the agent back ran in memory: a restart lost them, a failed order was never retried, callbacks gave up after 3 quick tries | This work is saved as **jobs** in the database, in the same step as the decision itself. A worker runs them, retries failures with growing waits (5 s, 10 s, 20 s … up to 10 min), and after 8 tries marks them **dead** with the reason. A job whose worker crashed is picked up again by another worker |
| No way to see or fix failed background work | A **Background jobs** page in the console (red count in the menu) shows dead jobs and their errors; admins can retry them |
| Approving a payment that had *just* expired never told the agent | Fixed: the agent gets its "expired" callback |
| Retrying a dead order did nothing | Fixed: a successful retry creates the order and tells the agent again |

### Findings that are not bugs in a single line

- **Daily limits** (fixed in 8a): each user+agent policy has its own daily limit, but "spent today" counted what **all** of that user's agents spent, so one flight booked by TripMate could use up the same user's grocery agent's limit. Now each policy counts only its own agent's spending, and a user can also have an optional overall budget (per day, week and month) that caps all their agents together.

## 5. Now: Phase 3, item ⑧ (richer policies)

Built in this order, one commit each, with tests:

| Step | What it adds | Example |
|---|---|---|
| 8a ✅ | **Per-agent spending + optional user budget** (daily / weekly / monthly) | GroceryGenie's ₹5,000/day counts only GroceryGenie; Asha can also cap *all* her agents at ₹1,00,000/day |
| 8b | **Weekly and monthly limits** per policy | TripMate: ₹2,00,000 a month |
| 8c | **Per-category and per-merchant limits** | ShopBuddy: at most ₹5,000/day on fashion, ₹10,000/day at GadgetHub |
| 8d | **Time windows** (hours and weekdays, in the spend time zone) | CommuteBot may pay only 06:00–22:00, Monday–Saturday |
| 8e | **Policy history** | every change saved as a numbered version; each payment records which version decided it |
| 8f | **Console**: edit all of the above, user budgets on the Users page, policy history | |

Each new rule has its own violation code (for example `weekly_limit_exceeded`, `category_limit_exceeded`, `outside_allowed_hours`, `user_daily_budget_exceeded`), so every decision still explains exactly which rule stopped it. Approvals re-check all of them.

## 6. After that

1. **⑦ MCP server + Python SDK.** Agents connect with a few lines of code instead of raw HTTP. Needs nothing external.
2. **⑤ Approval by the real user.** PayTrust sends the person whose money it is a signed approval link (and an email). Needs an email API key (Resend, free tier) and a public URL (`cloudflared`, free).
3. **⑥ Real money flow.** Razorpay test-mode webhooks update payments to PAID / FAILED / REFUNDED, and limits count captured money. Needs Razorpay test keys (free, no KYC) and the public URL.
4. **Phase 4.** Multi-tenant workspaces, an ML model that learns from reviewer decisions, updated business docs.

## 7. What I need from you

| When | What |
|---|---|
| Before ⑤ | An email API key (e.g. Resend) and a sender address |
| Before ⑤ and ⑥ | `cloudflared` (or ngrok) installed, for a public URL |
| Before ⑥ | Razorpay **test** Key ID, Key Secret, and a webhook secret you choose in the dashboard |
| Phase 4 | Your pricing for the business docs |

Put keys in `.env` yourself, never in chat.

## 8. Check it yourself

```powershell
cd "S:\builder\builder 2.0\PayTrust_AI\backend"
..\.venv\Scripts\python -m pytest -q            # all tests
cd ..\frontend; npm run build                  # console builds
cd ..; .venv\Scripts\python demo\run_demo.py --open   # the demo (on branch demo-simulation)
```

CI results: https://github.com/Sanskar1724/PayTrust_AI/actions
