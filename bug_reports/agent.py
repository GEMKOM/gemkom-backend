"""
Bug report AI agent.

Flow:
  1. Load full conversation for the bug report
  2. Build codebase context by asking Claude which files are relevant
  3. Ask Claude to decide: need more info? or produce a fix?
  4. Post a follow-up comment OR create a GitHub PR (or both repos)
"""
import concurrent.futures
import json
import logging
import re
import time
import threading
from datetime import datetime

import anthropic
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models

from notifications.models import Notification
from notifications.service import notify, bulk_notify

# Max tokens the agent may spend on a single bug report investigation.
# If the code context alone would exceed this, escalate to staff instead of guessing.
_MAX_INVESTIGATION_TOKENS = 150_000

from .github_client import (
    create_branch,
    create_pull_request,
    get_branch_sha,
    get_default_branch,
    get_file_content,
    get_repo_tree,
    update_file,
)
from .models import BugReport, BugReportMessage

logger = logging.getLogger(__name__)

_client = None

# ---------------------------------------------------------------------------
# Repo tree cache — refreshed every 10 minutes, shared across threads
# ---------------------------------------------------------------------------
_tree_cache: dict[str, tuple[list[str], float]] = {}
_tree_lock = threading.Lock()
_TREE_TTL = 600  # seconds


def _get_repo_tree_cached(repo: str) -> list[str]:
    with _tree_lock:
        entry = _tree_cache.get(repo)
        if entry and (time.time() - entry[1]) < _TREE_TTL:
            return entry[0]
    tree = get_repo_tree(repo)
    with _tree_lock:
        _tree_cache[repo] = (tree, time.time())
    return tree


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a senior full-stack software engineer working on the GEMKOM internal ERP system.
The system has two repositories:
- Backend: Django + Django REST Framework (Python), PostgreSQL via Supabase. Repo: {backend_repo}
- Frontend: Vanilla JavaScript, organized by feature folders. Repo: {frontend_repo}

You are investigating a bug report submitted by a NON-TECHNICAL end user (a factory/office worker, not a developer).
You have already been given the relevant source code. Use it to find the bug yourself.

CRITICAL RULES about asking follow-up questions:
- NEVER ask about code, files, components, functions, or anything technical.
- NEVER ask "which file renders X" or "can you share the code for Y".
- You may ONLY ask things a non-technical user can answer, such as:
  * What exactly did they click or do before the problem appeared?
  * What did they see on screen (error message text, what was missing)?
  * What is their role/department in the system?
  * Does the problem happen every time or only sometimes?
  * Which browser are they using?
- Only ask if the user's description is genuinely too vague to locate the bug even with the code in front of you.
- If you have the code and can see a likely cause, attempt a fix — do not ask questions.

User-facing message rules (the "message" field):
- Always write in Turkish, friendly and simple. No technical jargon whatsoever.
- When action is "ask": ask your single simple question.
- When action is "fix": write ONLY something like "Sorununuz tespit edildi ve teknik ekibimize iletildi. İncelendikten sonra düzeltilecektir. Bildirdiğiniz için teşekkürler!" — do NOT explain the technical cause.

Your job:
1. Read the provided source code carefully.
2. Either fix the bug (action: "fix") or ask ONE simple user-facing question (action: "ask").

Response schema (always valid JSON):
{{
  "action": "ask" | "fix",
  "message": "Your reply to the user in Turkish, simple language",
  "repo": "backend" | "frontend" | "both" | null,
  "files": [
    {{
      "repo": "backend" | "frontend",
      "path": "relative/path/to/file.py",
      "content": "full new file content as a string"
    }}
  ],
  "pr_title": "Short PR title in English",
  "pr_body": "PR description in English explaining root cause and fix"
}}

When action is "ask", files/pr_title/pr_body can be null/empty.
"""

_FILE_SELECTION_PROMPT = """A non-technical user reported this bug. You need to find ALL files that could be involved so a developer can investigate without asking the user any questions.

Be generous — it is better to read too many files than too few. Include:
- The feature's main frontend JS file and its HTML page
- Any related API/service files on the frontend
- The Django view, serializer, model, and URL file for that feature on the backend
- Any permission/approval logic files if the bug involves buttons not appearing or actions being blocked

{page_hint}

Return a JSON object:
{{
  "backend_files": ["path/to/file.py", ...],
  "frontend_files": ["path/to/file.js", ...]
}}
Limit to at most 12 backend files and 12 frontend files. Be selective — only the files most directly involved in the reported page/feature, not generic utilities.

Bug report title: {title}
Description: {description}

Available backend files:
{backend_tree}

Available frontend files:
{frontend_tree}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_conversation_text(bug_report: BugReport) -> str:
    messages = bug_report.messages.all()
    parts = [f"Bug Report #{bug_report.pk}: {bug_report.title}\n"]
    for msg in messages:
        role = 'User' if msg.sender_type == BugReportMessage.SENDER_USER else 'Agent'
        parts.append(f"[{role}]: {msg.content}")
    return '\n\n'.join(parts)


def _select_relevant_files(title: str, description: str, backend_tree: list[str], frontend_tree: list[str], page_url: str = '', page_label: str = '') -> dict:
    backend_sample = '\n'.join(backend_tree[:400])
    frontend_sample = '\n'.join(frontend_tree[:400])

    if page_url:
        page_hint = (
            f'IMPORTANT: The user reported this bug on the page "{page_label}" (URL: {page_url}). '
            f'Prioritise files under the frontend folder matching that URL path and the corresponding backend endpoints.'
        )
    else:
        page_hint = 'The user did not specify which page the bug occurred on.'

    prompt = _FILE_SELECTION_PROMPT.format(
        title=title,
        description=description,
        backend_tree=backend_sample,
        frontend_tree=frontend_sample,
        page_hint=page_hint,
    )

    response = _get_client().messages.create(
        model='claude-sonnet-4-6',
        max_tokens=1024,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = response.content[0].text.strip()
    # Extract JSON from response
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return {'backend_files': [], 'frontend_files': []}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {'backend_files': [], 'frontend_files': []}


def _build_code_context(selected_files: dict) -> str:
    tasks = []
    for path in selected_files.get('backend_files', []):
        tasks.append(('backend', path, settings.GITHUB_BACKEND_REPO))
    for path in selected_files.get('frontend_files', []):
        tasks.append(('frontend', path, settings.GITHUB_FRONTEND_REPO))

    def fetch(item):
        label, path, repo = item
        content = get_file_content(repo, path)
        return (label, path, content)

    parts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for label, path, content in ex.map(fetch, tasks):
            if content:
                parts.append(f'=== {label.upper()}: {path} ===\n{content}')

    return '\n\n'.join(parts)


def _parse_agent_response(text: str) -> dict:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return {
            'action': 'ask',
            'message': 'Üzgünüm, yanıtı işleyemedim. Lütfen hata raporunuzu daha ayrıntılı açıklayabilir misiniz?',
            'repo': None,
            'files': [],
            'pr_title': '',
            'pr_body': '',
        }
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {
            'action': 'ask',
            'message': 'Üzgünüm, yanıtı işleyemedim. Lütfen hata raporunuzu daha ayrıntılı açıklayabilir misiniz?',
            'repo': None,
            'files': [],
            'pr_title': '',
            'pr_body': '',
        }


def _create_pr_for_repo(repo_key: str, repo: str, files: list[dict], pr_title: str, pr_body: str, bug_id: int) -> str:
    branch_name = f'fix/bug-report-{bug_id}-{repo_key}-{datetime.now().strftime("%Y%m%d%H%M%S")}'
    default_branch = get_default_branch(repo)
    sha = get_branch_sha(repo, default_branch)
    create_branch(repo, branch_name, sha)

    for file_change in files:
        update_file(
            repo=repo,
            path=file_change['path'],
            content=file_change['content'],
            message=f'fix: {pr_title} (bug report #{bug_id})',
            branch=branch_name,
        )

    pr_url = create_pull_request(
        repo=repo,
        title=pr_title,
        body=f'{pr_body}\n\n---\n_Auto-generated fix for [Bug Report #{bug_id}]_',
        head=branch_name,
        base=default_branch,
    )
    return pr_url


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def _notify_reporter(bug_report: BugReport, notification_type: str, title: str, body: str) -> None:
    if not bug_report.reported_by:
        return
    notify(
        user=bug_report.reported_by,
        notification_type=notification_type,
        title=title,
        body=body,
        link=f'/bug-reports/{bug_report.pk}',
        source_type='bug_report',
        source_id=str(bug_report.pk),
    )


def _notify_staff(bug_report: BugReport, notification_type: str, title: str, body: str) -> None:
    staff_users = list(User.objects.filter(is_active=True).filter(models.Q(is_staff=True) | models.Q(is_superuser=True)))
    if not staff_users:
        return
    bulk_notify(
        users=staff_users,
        notification_type=notification_type,
        title=title,
        body=body,
        link=f'/bug-reports/{bug_report.pk}',
        source_type='bug_report',
        source_id=str(bug_report.pk),
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_bug_report(bug_report_id: int) -> None:
    try:
        bug_report = BugReport.objects.select_related('reported_by').prefetch_related('messages').get(pk=bug_report_id)
    except BugReport.DoesNotExist:
        logger.error('BugReport %s not found', bug_report_id)
        return

    if bug_report.status == BugReport.STATUS_CLOSED:
        return

    bug_report.status = BugReport.STATUS_IN_PROGRESS
    bug_report.save(update_fields=['status', 'updated_at'])

    try:
        # 1. Get file trees from both repos (cached + parallel)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_backend_tree  = ex.submit(_get_repo_tree_cached, settings.GITHUB_BACKEND_REPO)
            f_frontend_tree = ex.submit(_get_repo_tree_cached, settings.GITHUB_FRONTEND_REPO)
            backend_tree  = f_backend_tree.result()
            frontend_tree = f_frontend_tree.result()

        # 2. Select relevant files based on bug description
        conversation_text = _build_conversation_text(bug_report)
        selected_files = _select_relevant_files(
            title=bug_report.title,
            description=conversation_text,
            backend_tree=backend_tree,
            frontend_tree=frontend_tree,
            page_url=bug_report.page_url,
            page_label=bug_report.page_label,
        )

        # 3. Fetch file contents and check token budget
        code_context = _build_code_context(selected_files)

        # Rough token estimate: ~4 chars per token
        estimated_tokens = (len(conversation_text) + len(code_context)) // 4
        if estimated_tokens > _MAX_INVESTIGATION_TOKENS:
            _escalate_to_staff(bug_report, conversation_text)
            return

        # 4. Call Claude with full context
        system = _SYSTEM_PROMPT.format(
            backend_repo=settings.GITHUB_BACKEND_REPO,
            frontend_repo=settings.GITHUB_FRONTEND_REPO,
        )
        user_message = f'{conversation_text}\n\n--- Relevant Code ---\n{code_context}'

        response = _get_client().messages.create(
            model='claude-sonnet-4-6',
            max_tokens=8096,
            system=system,
            messages=[{'role': 'user', 'content': user_message}],
        )
        result = _parse_agent_response(response.content[0].text)

        action = result.get('action', 'ask')

        if action == 'ask':
            BugReportMessage.objects.create(
                bug_report=bug_report,
                sender_type=BugReportMessage.SENDER_AGENT,
                content=result['message'],
            )
            bug_report.status = BugReport.STATUS_WAITING
            bug_report.save(update_fields=['status', 'updated_at'])

            _notify_reporter(
                bug_report,
                Notification.BUG_REPORT_AGENT_REPLY,
                title=f'Hata raporunuz hakkında bir soru var – #{bug_report.pk}',
                body=result['message'][:500],
            )

        elif action == 'fix':
            files = result.get('files') or []
            pr_title = result.get('pr_title', f'Fix: Bug Report #{bug_report.pk}')
            pr_body = result.get('pr_body', '')
            repo_target = result.get('repo', 'unknown')

            pr_backend_url = ''
            pr_frontend_url = ''

            backend_files = [f for f in files if f.get('repo') == 'backend']
            frontend_files = [f for f in files if f.get('repo') == 'frontend']

            if backend_files:
                pr_backend_url = _create_pr_for_repo(
                    'backend', settings.GITHUB_BACKEND_REPO,
                    backend_files, pr_title, pr_body, bug_report.pk,
                )

            if frontend_files:
                pr_frontend_url = _create_pr_for_repo(
                    'frontend', settings.GITHUB_FRONTEND_REPO,
                    frontend_files, pr_title, pr_body, bug_report.pk,
                )

            # User sees a friendly message — no technical details
            user_message_text = 'Sorununuz tespit edildi ve teknik ekibimize iletildi. İncelendikten sonra düzeltilecektir. Bildirdiğiniz için teşekkürler!'
            BugReportMessage.objects.create(
                bug_report=bug_report,
                sender_type=BugReportMessage.SENDER_AGENT,
                content=user_message_text,
            )

            bug_report.status = BugReport.STATUS_PR_CREATED
            bug_report.repo_target = repo_target
            bug_report.pr_backend_url = pr_backend_url
            bug_report.pr_frontend_url = pr_frontend_url
            bug_report.save(update_fields=['status', 'repo_target', 'pr_backend_url', 'pr_frontend_url', 'updated_at'])

            # Notify reporter — friendly, no PR links
            _notify_reporter(
                bug_report,
                Notification.BUG_REPORT_PR_CREATED,
                title=f'Hata raporunuz inceleniyor – #{bug_report.pk}',
                body='Sorununuz tespit edildi ve teknik ekibimize iletildi. İncelendikten sonra düzeltilecektir.',
            )

            # Notify staff — full technical details including PR links
            pr_links = []
            if pr_backend_url:
                pr_links.append(f'Backend PR: {pr_backend_url}')
            if pr_frontend_url:
                pr_links.append(f'Frontend PR: {pr_frontend_url}')
            staff_body = (
                f'Bug Report #{bug_report.pk}: {bug_report.title}\n'
                f'Bildiren: {bug_report.reported_by}\n\n'
                f'Ajan tespiti:\n{result.get("pr_body", "")}\n\n'
                + '\n'.join(pr_links)
            )
            _notify_staff(
                bug_report,
                Notification.BUG_REPORT_PR_CREATED,
                title=f'[Hata Raporu] #{bug_report.pk} – PR oluşturuldu, inceleme gerekli',
                body=staff_body,
            )

    except Exception:
        logger.exception('Agent failed processing bug report %s', bug_report_id)
        bug_report.status = BugReport.STATUS_ESCALATED
        bug_report.save(update_fields=['status', 'updated_at'])
        BugReportMessage.objects.create(
            bug_report=bug_report,
            sender_type=BugReportMessage.SENDER_AGENT,
            content='Sorununuz alındı ve teknik ekibimize iletildi. En kısa sürede incelenecektir.',
        )
        _notify_staff(
            bug_report,
            Notification.BUG_REPORT_AGENT_REPLY,
            title=f'[Hata Raporu] #{bug_report.pk} – Ajan başarısız, manuel inceleme gerekli',
            body=f'Bug Report #{bug_report.pk}: {bug_report.title}\nBildiren: {bug_report.reported_by}\n\nAjan işlemi başarısız oldu. Manuel inceleme gerekiyor.',
        )


def _escalate_to_staff(bug_report: BugReport, conversation_text: str) -> None:
    """Called when the bug is too complex for the agent to handle within token budget."""
    logger.info('Bug report %s exceeds token budget, escalating to staff', bug_report.pk)

    user_message_text = 'Sorununuz alındı ve teknik ekibimize iletildi. En kısa sürede incelenecektir. Bildirdiğiniz için teşekkürler!'
    BugReportMessage.objects.create(
        bug_report=bug_report,
        sender_type=BugReportMessage.SENDER_AGENT,
        content=user_message_text,
    )

    bug_report.status = BugReport.STATUS_ESCALATED
    bug_report.save(update_fields=['status', 'updated_at'])

    _notify_reporter(
        bug_report,
        Notification.BUG_REPORT_AGENT_REPLY,
        title=f'Hata raporunuz alındı – #{bug_report.pk}',
        body=user_message_text,
    )

    _notify_staff(
        bug_report,
        Notification.BUG_REPORT_AGENT_REPLY,
        title=f'[Hata Raporu] #{bug_report.pk} – Manuel inceleme gerekli (karmaşık)',
        body=(
            f'Bug Report #{bug_report.pk}: {bug_report.title}\n'
            f'Bildiren: {bug_report.reported_by}\n\n'
            f'Bu rapor ajan token limitini aştığı için otomatik çözülemedi. Manuel inceleme gerekiyor.\n\n'
            f'Rapor özeti:\n{conversation_text[:1000]}'
        ),
    )
