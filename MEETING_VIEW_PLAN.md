# Meeting View (Sunum Modu) for Production Planning — Implementation Plan

> **Status:** planned, not started (saved 2026-07-22). No code from this plan exists yet.
> Scope spans two repos: this backend and the `white-app` frontend (sibling directory).
> To resume: hand this file to Claude and say "implement the meeting view plan".

## Context

The weekly review runs on the production-planning portfolio page (full-width verdict cards, projector). We want a dedicated **meeting view**: one job order filling the whole page, prev/next navigation (buttons on top + scroll/keys), showing the existing verdict card **plus** meeting context: NCR counts, revision counts (**both** technical-drawing revisions and target-date revisions — confirmed), procurement items waiting, cuts waiting, **manufacturing status — machining operations/hours and welding resource assignments ("the most important aspects")**, files (all sources, grouped — confirmed), and a financial-health flag (no amounts, just a verdict; naive spend-vs-progress misleads because procurement front-loads cost — so the rule compares **projected full cost vs price**, using the cached `estimated_total_cost`, which is built as a 100%-projection on top of actuals, making `max(actual, estimated)` the correct projected cost).

Slides iterate over the current portfolio result (same status filter + sort). All data covers the root's **whole subtree**. All backend claims below were verified against source by a validation pass.

## Backend (gemkom-backend)

### 1. New service `projects/services/meeting_brief.py` — `build_meeting_brief(root, request, include_financial)`

Subtree via existing `_collect_subtree_nodes` (projects/services/production_plan.py:82) → `job_nos`. Blocks:

- **quality**: `NCR.filter(job_order_id__in=job_nos)` (quality_control/models.py:116; index `(job_order, status)` exists): `total`, `open` (status in draft/submitted/rejected — same rule as the completion gate projects/models.py:1166), `open_by_severity`, `open_list` newest ≤5 `{ncr_number, title, severity(+display), status(+display), job_no, created_at}`.
- **revisions**:
  - `drawing` (subtree `TechnicalDrawingRelease`, projects/models.py:1990): `revision_count` = Count(status='superseded') (same semantics as list annotation views.py:194-198), `in_revision_count`, `current` = one query `filter(status='released').order_by('-released_at').first()` → `{revision_code, revision_number, released_at, job_no}` (do NOT use per-job `get_current_release`; revision_number is only unique per job).
  - `target_date` (ROOT only, `root.target_date_revisions`, projects/models.py:2364): `count`, `latest_list` ≤3 `{previous_date, new_date, reason, changed_by_name, changed_at}`.
- **procurement** — `PlanningRequestItem.filter(job_no__in=job_nos, quantity_to_purchase__gt=0)`. Do NOT touch `quantity_remaining_for_purchase` (its non-prefetched branch aggregates per item → N+1; the production_plan Prefetch doesn't feed it). One annotated query: `requested_qty=Sum('purchase_request_items__quantity', filter=~Q(purchase_request_items__purchase_request__status__in=('rejected','cancelled')))`, then classify in Python **delivered first**: `items_delivered` (is_delivered=True), else `requested_waiting` (requested_qty ≥ quantity_to_purchase), else `not_yet_requested`. (PR ≠ PO — labels say "talep", not "sipariş". Historical M2M-only rows count as not-requested; accepted.) Plus `items_total`.
- **cutting** (CNC only; linear-cutting bars aren't job-linked at completion level — known gap, note in docstring): one aggregate over `CncPart.filter(job_no__in=job_nos)` using `qty_expr = Coalesce(NullIf('quantity',0),1)` for part counts AND `weight_expr = Coalesce(weight_kg,0) * qty_expr` (same normalization as production_plan.py:299-314): `parts_total/parts_cut/parts_waiting`, `weight_total/weight_cut/weight_waiting`; cut = `cnc_task__completion_date__isnull=False`.
- **machining**: mirror the batched machining branch of `_batched_domain_progress` (production_plan.py — `Operation.filter(part__job_no__in=job_nos)` `.values('key','estimated_hours','completion_date')` + timers spent annotation `(Sum(finish)−Sum(start))/3600000.0`): `operations_total / operations_completed / operations_waiting`, `estimated_hours_total` (est>0 only), `hours_spent` (Σ raw spent), `hours_earned` (completed→est, open→min(spent,est)), `hours_remaining` (= est_total − earned). Plus one aggregate on `tasks.Part.filter(job_no__in=job_nos)`: `parts_total / parts_completed` (`completion_date` isnull).
- **welding** (resource assignments + their progress, NOT time entries): who is welding and how far along, from the welding board models:
  - Committed subcontractors: `SubcontractingAssignment.filter(department_task__job_order_id__in=job_nos, is_retired=False)` restricted to welding work (`department_task__task_type='welding'` OR `department_task__parent__task_type='welding'`; belt-and-braces `.exclude(price_tier__tier_type='paint')`) — subcontracting/models.py:107; `select_related('subcontractor','department_task')`.
  - Committed internal teams: `InternalTeamAssignment` (welding/models.py:168, OneToOne on the welding subtask) same task filter; `select_related('team','department_task')`.
  - Planned-only rows: `WeldingPlanAllocation` (welding/models.py:232) on subtree MAIN welding tasks where both `promoted_*` links are null — shows capacity plans not yet committed, with `planned_start_date/planned_end_date`.
  - Per-row payload `{name, kind: 'subcontractor'|'team', job_no, allocated_weight_kg, progress_pct, planned (bool), planned_start_date?, planned_end_date?}`. Progress = the assignment task's completion (`get_completion_percentage(skip_expensive_calculations=True)`; `Prefetch('department_task__subtasks')` so the skip path stays query-free — without it each call fires a count aggregate).
  - Rollup: `resources_total`, `allocated_kg_total`, `weighted_progress_pct` (Σkg×p ÷ Σkg over committed rows only).
- **files** — grouped, newest-first, cap 20/group + per-group `total` (a plain `.count()` per group is fine); entries `{id, name, url, uploaded_at, uploaded_by_name, job_no|context}`. **No `file_size` for storage-backed models** — `file_size` properties call `.file.size` = one S3/Supabase HEAD per file; only `DiscussionAttachment.size` (DB field) is safe to include. Build minimal dicts in the service (don't reuse the fat serializers); URLs via `request.build_absolute_uri(f.file.url)` mirroring JobOrderFileSerializer (projects/serializers.py:589).
  - `job_order`: `JobOrderFile.filter(job_order_id__in=job_nos)` (projects/models.py:665).
  - `offer`: ROOT only — `root.offer_files.all()` ∪ `root.source_offer.files.all()` deduped by pk (offer_files is a chosen subset of source_offer.files; children/phases share the same offer — skip them).
  - `task`: `JobOrderDepartmentTaskFile.filter(task__job_order_id__in=job_nos)` (projects/models.py:1661).
  - `discussion`: `DiscussionAttachment.filter(Q(topic__job_order_id__in=job_nos) | Q(comment__topic__job_order_id__in=job_nos))` — `topic` is nullable; comment-level attachments hang off `comment.topic`.
- **financial** — key present ONLY when `include_financial`; never any amounts, response = `{verdict, reason (TR sentence), price_is_derived}`:
  - Price: `DerivedSellingPriceResolver([root.job_no]).display_for(root.job_no)` (projects/services/selling_price.py:39, `display_for` :270) — handles authoritative → derived → `source:'none'`; ~4-5 queries priced, more for unpriced deep roots.
  - Costs: root's `JobOrderCostSummary` (subtree rollup, confirmed) — `actual_total_cost`, `estimated_total_cost`. **Never compute on the fly** (recompute writes rows and chains up parents — not acceptable in a GET).
  - Ladder (constants at module top):
    - `no_data`: summary missing OR (actual == 0 AND estimated in (None, 0))
    - `no_price`: resolver source == 'none' or price ≤ 0
    - `cost_projected = max(actual, estimated or 0)`
    - `critical`: actual ≥ price OR cost_projected > price
    - `risky`: cost_projected > 0.9 × price, OR (estimated > 0 AND actual > estimated)
    - `healthy` otherwise

### 2. Endpoint

`JobOrderViewSet` detail action `meeting_brief` (`url_path='meeting-brief'`, `permission_classes=[IsAuthenticated]`, precedent: `production_plan` views.py:501). **Guard: the detail route also matches children and phase nodes (`lookup_value_regex` views.py:147-151) — if `job_order.parent_id` is set, return 400 with a TR message.** Financial gating inline (NOT permission_classes): `include_financial=can_see_job_costs(request.user)` (users/permissions.py:74 — the `view_job_costs` role perm; there is no "IsCostVisible" class).

### 3. Tests `projects/tests_meeting_brief.py`

TestCase, fabricated subtree: NCR open/closed + severity counts; superseded vs released drawing counts + cross-job current release; target-date revision count; procurement classification incl. delivered-with-remaining classified delivered, partial-PR → requested_waiting, M2M-only historical → not_yet_requested; CNC sums incl. quantity NULL/0 → 1; machining hours (completed op → full est credit, open op → min(spent,est), est≤0 skipped) + parts counts; welding resources (subcontractor on welding subtask included, paint-tier + retired excluded, internal team included, unpromoted plan allocation listed as planned, promoted one NOT double-listed, weighted progress math, assignment in child job included); files grouping, offer dedupe, comment-level discussion attachment; financial ladder (each verdict + missing summary + derived price + no price); financial key ABSENT without `view_job_costs`; non-root job_no → 400. Query ceiling: assertNumQueries ≤ 35 (typical priced root ~25; resolver walk widens it for unpriced roots).

## Frontend (white-app)

### 4. API wrapper (`apis/projects/jobOrders.js`)

`getJobOrderMeetingBrief(jobNo)` → `/projects/job-orders/{jobNo}/meeting-brief/` (encodeURIComponent — phase job_nos contain `/`).

### 5. Meeting mode (`projects/production-planning/production-planning.js`)

- **Routing**: URL stays source of truth. `?meeting=1` → meeting mode; optional `&job_no=X` = current slide (shareable/deep-linkable). `handleRoute()` gains the meeting branch; `setModeChrome('meeting')` hides toolbar controls + shows the meeting bar. Esc / Çık pushes bare URL → portfolio; popstate already routes.
- **Slide list** = current portfolio items (respecting `overviewStatus` + `portfolioSort`); fetch overview first if missing. "Sunum Modu" button (fa-tv) in `#pp-portfolio-controls`; slide order == card order.
- **Meeting bar (top)**: ‹ Önceki · "3 / 84 · 035-170 — W&S PANEL" · Sonraki › · Planı Aç (→ detail) · Çık. Keyboard ← / → / Esc. Wheel advances only when the page is already at scroll top/bottom (600 ms debounce) so long slide content stays scrollable.
- **Slide body**: reuse `verdictCardHtml(item, item.summary, today, {clickable:false})` as hero, then `pp-meeting-grid` panels (2-col, 1-col <1200px), projector-sized numbers (~2.2rem):
  - **Kalite**: open-NCR big number + severity dots (reuse `pp-dot-*`; critical=red, major=orange, minor=grey — no yellow) + top open NCR lines with house `status-badge`s.
  - **Revizyonlar**: Teknik Resim (current `revision_code` big, "N kez revize", "M revizyonda" when in_revision_count>0) · Hedef Tarih ("N kez değişti" + latest reason line).
  - **Satın Alma**: bekleyen kalem big number, split "talebe dönüşmedi / talepte–teslim bekliyor", teslim edilen.
  - **Kesim**: bekleyen parça count + kg; kesilen/toplam mini bar.
  - **Talaşlı İmalat**: bekleyen operasyon big number; "N/M operasyon tamamlandı"; saat satırı "Tahmini X s · Harcanan Y s · Kalan ~Z s"; earned/estimated mini bar.
  - **Kaynaklı İmalat**: weighted overall % big number + Σ kg; then one row per resource — house badge for kind (Taşeron = status-purple, Dahili Takım = status-blue), name, allocated kg, per-row mini progress bar + %; planned-only rows greyed with "(plan)" + planned date range; "Atama yok" empty state.
  - **Dosyalar**: grouped lists (İş Emri / Teklif–Sözleşme / Görev Ekleri / Tartışma), links open in new tab, "+N daha" when capped.
  - **Finansal Durum**: only when `financial` present — status pill reusing `pp-vh-*` (green Sağlıklı / orange Riskli / red Kritik / grey Veri Yok·Fiyat Yok) + reason sentence + "(fiyat türetilmiş)" hint when `price_is_derived`. No numbers.
- **Data flow**: `meetingBriefCache = Map(jobNo → brief)`; on slide show render card instantly from overview, fetch brief if uncached (skeleton shimmer on panels), prefetch neighbors i±1. Bind meeting listeners once (`viewControlsBound`-style guard); detach key/wheel handlers on mode exit.

### 6. HTML/CSS

- `index.html`: `#pp-meeting-bar` (hidden) in the toolbar card, `#pp-meeting-container` after `#plan-verdict-container`, Sunum Modu button in portfolio controls.
- `production-planning.css`: `.pp-meeting-grid`, `.pp-panel` cards + big-number typography, skeleton shimmer, financial pill sizes. Layout-critical widths inline from JS (CSS cache gotcha).

## Verification

1. `python manage.py test projects` — new tests + existing 64 green.
2. Read-only smoke vs production data: brief for 035-170 + 2-3 other roots — counts sane vs known data, query count logged, financial key present for superuser and absent for a crafted non-cost user, child job_no → 400.
3. Browser (dev servers 8001/8080, cache-busting ritual, DOM-measurement verification): portfolio → Sunum Modu → navigate via buttons/keys/wheel-at-edge; counts match modal/known values; files open in new tab; Planı Aç lands on detail; Esc returns; popstate ok; simulated non-cost user sees no Finansal panel; zero console errors.
