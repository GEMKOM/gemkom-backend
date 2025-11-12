# Department Request System - Simple Setup Guide

## Overview

A simple pre-procurement workflow for departments (maintenance, production, etc.) to submit material/part requests.

## Workflow

```
Department User creates request (auto-submitted) → Department Head (auto-selected) → Approved → Planning marks as Transferred
```

## Model

**DepartmentRequest** - Single model with JSON items field

### Fields
- `request_number`: Auto-generated (DR-YYYY-NNNN)
- `title`: Request title
- `description`: Description
- `department`: Department name (used to auto-select approver)
- `needed_date`: When items are needed
- `items`: JSON array of items (flexible structure)
- `requestor`: User who created request
- `priority`: normal/urgent/critical
- `status`: draft/submitted/approved/rejected/transferred/cancelled
- `approved_by`, `approved_at`: Approval tracking
- `created_at`, `submitted_at`: Timestamps

## API Endpoints

Base: `/api/procurement/department-requests/`

### Standard CRUD
- `GET /` - List (filtered by user role)
- `POST /` - Create
- `GET /{id}/` - Detail
- `PUT/PATCH /{id}/` - Update
- `DELETE /{id}/` - Delete

### Actions
- `POST /{id}/approve/` - Approve (department head)
- `POST /{id}/reject/` - Reject (department head)
- `GET /my_requests/` - User's own requests
- `GET /pending_approval/` - Requests awaiting user's approval
- `GET /approved_requests/` - Approved requests (planning only)
- `PATCH /{id}/mark_transferred/` - Mark as transferred (planning only)

**Note**: Creating a request (POST /) automatically submits it for approval - no separate submit action needed.

## Example Request

```json
POST /api/procurement/department-requests/
{
  "title": "Maintenance Tools",
  "description": "Tools for equipment maintenance",
  "department": "maintenance",
  "needed_date": "2025-12-01",
  "priority": "normal",
  "items": [
    {
      "description": "Adjustable wrench set",
      "quantity": 5,
      "unit": "adet",
      "specifications": "Chrome vanadium steel"
    },
    {
      "description": "Hydraulic pump seal",
      "quantity": 2,
      "unit": "adet"
    }
  ]
}
```

**Important**: This POST request will automatically:
1. Create the department request
2. Submit it for approval
3. Notify department head(s) via email

## Setup

### 1. Run Migrations
```bash
python manage.py makemigrations procurement
python manage.py migrate
```

### 2. Create Approval Policy
```python
from approvals.models import ApprovalPolicy, ApprovalStage

policy = ApprovalPolicy.objects.create(
    name="Department Request – Default",
    description="Department head approval",
    is_active=True,
    selection_priority=1
)

# Stage 1: Department head (auto-selected based on department)
ApprovalStage.objects.create(
    policy=policy,
    order=1,
    name="Department Head",
    required_approvals=1
)
```

### 3. Configure User Profiles
- **Department users**: `profile.team = "maintenance"`
- **Department heads**: `profile.team = "maintenance"` + `profile.occupation = "manager"`
- **Planning**: `profile.team = "planning"`

Department heads are automatically found by matching `team` and `occupation == "manager"`.

## Features

- **Auto-approver selection**: Department heads automatically assigned based on `department` field
- **Auto-skip empty stages**: If no department head exists, approval stage is skipped
- **Simple JSON items**: Flexible structure, no separate table
- **Status tracking**: Track progress from draft → transferred
- **Email notifications**: Automatic emails to approvers and requestor

## Notes

- Items stored as JSON for flexibility
- Status change to 'transferred' tracks that planning has processed the request
- No complex tracking fields - just simple status changes
- Department head approval is automatic based on user profiles
