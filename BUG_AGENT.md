# Bug Report Agent — Implementation Summary

## What Was Built

A full end-to-end AI-powered bug reporting system. Users submit bug reports through the frontend, a Claude-powered agent investigates the code across both repositories, and either fixes the bug automatically (opening a GitHub PR) or asks the user a simple follow-up question.

---

## Architecture

```
User submits bug report (frontend form)
        ↓
BugReport created in DB + first message saved
        ↓
Cloud Tasks job enqueued (background thread locally)
        ↓
Agent wakes up:
  1. Fetches repo file trees (cached 10 min)
  2. Asks Claude to select relevant files based on page URL + description
  3. Fetches selected files in parallel (10 workers)
  4. Calls Claude with full code context
  5. Claude decides:
        → "ask": posts a user-friendly Turkish question, status = waiting_info
        → "fix": creates branch + PR on GitHub, status = pr_created
        → token limit exceeded: escalates to staff, status = escalated
        ↓
User notified (in-app + email)
Staff notified separately with full technical details + PR links
```

---

## Files Created / Modified

### Backend (`gemkom-backend`)

| File | Description |
|------|-------------|
| `bug_reports/models.py` | `BugReport`, `BugReportMessage`, `BugReportAttachment` models |
| `bug_reports/serializers.py` | List, detail, create, reply serializers |
| `bug_reports/views.py` | REST viewset + `AgentProcessTaskView` (Cloud Tasks callback) |
| `bug_reports/urls.py` | Routes at `/bug-reports/` |
| `bug_reports/agent.py` | Main AI agent: file selection, Claude API, PR creation |
| `bug_reports/github_client.py` | GitHub REST API: read files, create branches, commit, open PRs |
| `bug_reports/tasks.py` | Cloud Tasks enqueue (background thread in development) |
| `bug_reports/apps.py` | Startup recovery: resets stuck `in_progress` reports |
| `bug_reports/admin.py` | Django admin with inline messages and attachments |
| `notifications/models.py` | Added `BUG_REPORT_AGENT_REPLY`, `BUG_REPORT_PR_CREATED` types |
| `notifications/service.py` | Added defaults and templates for new notification types |
| `config/settings.py` | Added `GITHUB_TOKEN`, `GITHUB_BACKEND_REPO`, `GITHUB_FRONTEND_REPO`, `ANTHROPIC_API_KEY` |
| `config/urls.py` | Registered `/bug-reports/` |
| `requirements.txt` | Added `anthropic==0.103.1` |

### Frontend (`office-gemkom-app`)

| File | Description |
|------|-------------|
| `bug-reports/index.html` | Bug report page: form, list, chat UI |
| `bug-reports/bug-reports.js` | Full page logic: submit, reply, polling, page dropdown |
| `apis/bugReports.js` | API client + status labels/badge colors |

---

## Bug Report Statuses

| Status | Meaning |
|--------|---------|
| `open` | Submitted, agent hasn't run yet |
| `in_progress` | Agent is actively analyzing |
| `waiting_info` | Agent asked user a follow-up question |
| `pr_created` | Fix found, PR open — awaiting your review |
| `escalated` | Too complex or agent failed — needs manual review |
| `closed` | Resolved |

---

## How the Agent Works

1. **Page hint**: User selects which page they were on from a dropdown (filtered to their own accessible routes). The agent uses this to immediately target the right frontend file and trace through API calls to the backend.

2. **File selection**: Claude picks up to 12 backend + 12 frontend files most likely to contain the bug.

3. **Parallel fetching**: Both repo trees are fetched in parallel and cached for 10 minutes. All selected files are fetched in parallel (10 workers).

4. **Token budget**: If the code context exceeds ~150,000 tokens, the report is escalated to staff rather than attempting a low-quality fix.

5. **Two audiences**: The user always sees a friendly Turkish message with no technical details. Staff receive the full technical diagnosis + PR links via separate notification.

6. **Follow-up loop**: If the agent asks a question and the user replies, the agent re-runs automatically with the full conversation history.

---

## Environment Variables Required

```env
GITHUB_TOKEN=ghp_...                          # Classic PAT with repo scope
GITHUB_BACKEND_REPO=GEMKOM/gemkom-backend
GITHUB_FRONTEND_REPO=GEMKOM/office-gemkom-app
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Next Steps for Production

### 1. Add a dedicated Cloud Tasks queue for the agent

The current setup reuses the `email-notifications` queue. The agent tasks are much longer-running (30-60s) and should have their own queue with appropriate timeout settings.

```bash
gcloud tasks queues create bug-agent \
  --location=europe-west3 \
  --max-attempts=2 \
  --max-retry-duration=120s \
  --max-dispatches-per-second=5
```

Then add to `.env` / Cloud Run environment:
```env
BUG_AGENT_QUEUE=bug-agent
```

And update `tasks.py` to use `settings.BUG_AGENT_QUEUE` instead of `settings.CLOUD_TASKS_QUEUE`.

### 2. Set Cloud Run request timeout

The agent can take 30-60 seconds. Cloud Run's default timeout is 60s — increase it for safety:

In `cloudbuild.yaml` or Cloud Run settings:
```
--timeout=300
```

### 3. Add the bug-reports page to the frontend navigation

Add a link to `/bug-reports/` in `navigationStructure.js` and the navbar so users can find it.

### 4. Add the bug-reports route to the permission system

Decide who can submit bug reports — probably all logged-in users. Add the route to `accessControl.js` if needed, or confirm it's open to all authenticated users.

### 5. Seed the new notification types in the database

The `BUG_REPORT_AGENT_REPLY` and `BUG_REPORT_PR_CREATED` notification types need to be seeded into the `NotificationConfig` table. Run or write a management command / migration that calls your existing seed logic for these two new types.

### 6. Test the full Cloud Tasks flow end-to-end

Before going live:
- Set `USE_CLOUD_TASKS=true` in a staging environment
- Submit a test bug report and verify the task is enqueued and executed
- Verify the `X-Task-Secret` header check works correctly in `AgentProcessTaskView`
- Confirm OIDC token verification works with your Cloud Run service account

### 7. Set a spend limit on the Anthropic API key

In the Anthropic console under GEMKOM workspace, set a monthly spend limit (suggested: $50) so unexpected volume can't cause a large bill.

### 8. Monitor agent quality over time

After go-live, periodically review closed bug reports in Django admin to check:
- Is the agent asking unnecessary questions?
- Are the PRs it creates correct and getting merged?
- Are any reports getting stuck in `escalated` that could have been auto-fixed?

Adjust the system prompt and token budget based on what you observe.
