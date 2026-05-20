"""
Minimal GitHub REST API client for reading files and creating PRs.
Uses only the standard library + requests (already a dep via DRF).
"""
import base64
import logging
from datetime import datetime

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_BASE = 'https://api.github.com'


def _headers():
    return {
        'Authorization': f'token {settings.GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }


def get_repo_tree(repo: str, max_files: int = 500) -> list[str]:
    """Return list of file paths in repo (flat tree, default branch)."""
    url = f'{_BASE}/repos/{repo}/git/trees/HEAD?recursive=1'
    r = requests.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    tree = r.json().get('tree', [])
    return [
        item['path'] for item in tree
        if item['type'] == 'blob'
    ][:max_files]


def get_file_content(repo: str, path: str) -> str | None:
    """Return decoded file content, or None if too large / not found."""
    url = f'{_BASE}/repos/{repo}/contents/{path}'
    r = requests.get(url, headers=_headers(), timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    if data.get('encoding') != 'base64':
        return None
    # Skip files larger than 100 KB
    if data.get('size', 0) > 100_000:
        return f'[File too large to read: {data["size"]} bytes]'
    return base64.b64decode(data['content']).decode('utf-8', errors='replace')


def get_default_branch(repo: str) -> str:
    url = f'{_BASE}/repos/{repo}'
    r = requests.get(url, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()['default_branch']


def get_branch_sha(repo: str, branch: str) -> str:
    url = f'{_BASE}/repos/{repo}/git/ref/heads/{branch}'
    r = requests.get(url, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()['object']['sha']


def create_branch(repo: str, new_branch: str, from_sha: str) -> None:
    url = f'{_BASE}/repos/{repo}/git/refs'
    r = requests.post(url, headers=_headers(), timeout=10, json={
        'ref': f'refs/heads/{new_branch}',
        'sha': from_sha,
    })
    r.raise_for_status()


def update_file(repo: str, path: str, content: str, message: str, branch: str) -> None:
    """Create or update a file on a branch."""
    url = f'{_BASE}/repos/{repo}/contents/{path}'
    # Get current SHA if file exists
    r = requests.get(url, headers=_headers(), params={'ref': branch}, timeout=10)
    sha = r.json().get('sha') if r.status_code == 200 else None

    encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
    payload = {'message': message, 'content': encoded, 'branch': branch}
    if sha:
        payload['sha'] = sha

    r = requests.put(url, headers=_headers(), timeout=15, json=payload)
    r.raise_for_status()


def create_pull_request(repo: str, title: str, body: str, head: str, base: str) -> str:
    """Create a PR and return its HTML URL."""
    url = f'{_BASE}/repos/{repo}/pulls'
    r = requests.post(url, headers=_headers(), timeout=15, json={
        'title': title,
        'body': body,
        'head': head,
        'base': base,
    })
    r.raise_for_status()
    return r.json()['html_url']
