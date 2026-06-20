# Growth Optimization Rollout Implementation Plan

> **For agentic workers:** implement task-by-task with verification after each task. This plan follows the project rule that implementation plans live in `docs/plans/`.

**Goal:** Turn intent routing, quality evaluation, A/B testing, and attribution into real growth optimization loops for Mory's Telegram conversion bot.

**Architecture:** Add one thin orchestration layer that reuses existing `IntentRouter`, `conversation_telemetry`, `conversion_events`, `ab_test_metrics`, and Dashboard report APIs. The layer will enrich AI prompts with experiment-specific guidance, write attribution/telemetry events, and keep all new behavior controlled by config switches.

**Tech Stack:** Python, SQLite, Flask Dashboard, existing Bot dispatch pipeline, pytest.

---

### Task 1: Growth Optimization Core

**Files:**
- Create: `core/growth_optimizer.py`
- Test: `tests/unit/test_growth_optimizer.py`

- [ ] Define ten experiment IDs for purchase capture, product recommendation, private handoff, broadcast attribution, persona quality, cold user wakeup, entertainment conversion, button style, ad governance, and funnel optimization.
- [ ] Provide deterministic A/B variant assignment using `uid + experiment_id`.
- [ ] Provide prompt hints for purchase intent, consultation, flirt, complaint, tarot/treehole/dream, and cold users.
- [ ] Provide safe event logging helpers that write to `conversion_events`, `telemetry_events`, and `conversation_telemetry` without blocking the main reply flow.

### Task 2: AI Reply Integration

**Files:**
- Modify: `core/handlers/ai_reply_handler.py`

- [ ] Before calling `ai.ask`, call `build_growth_context()` and append its stage hint.
- [ ] After a successful reply, call `record_growth_reply()` to persist attribution and conversation telemetry.
- [ ] Preserve existing FAQ, relay, admin notification, memory, and conversion behavior.

### Task 3: Configuration And Reporting

**Files:**
- Modify: `config.json`
- Modify: `config.json.example`
- Modify: `dashboard/api/attribution_api.py`

- [ ] Enable guarded switches for intent routing, A/B telemetry, attribution report, and quality evaluation.
- [ ] Keep expensive quality evaluation capped with low sample rate and daily limit.
- [ ] Add a compact `/api/attribution/growth-summary` endpoint for the ten optimization tracks.

### Task 4: Verification

**Files:**
- Test: `tests/unit/test_growth_optimizer.py`
- Run existing focused tests.

- [ ] Run `python -m compileall main.py core modules dashboard scripts version.py -q`.
- [ ] Run growth optimizer tests.
- [ ] Run Dashboard smoke, RBAC, settings, broadcast, attribution-related tests.

### Task 5: Deploy And Runtime Check

**Files:**
- Use existing `deploy_vps.py`
- Use existing `scripts/health_check.py`

- [ ] Deploy via safe config merge.
- [ ] Verify `mory-assistant` and `mory-dashboard` are active.
- [ ] Verify `/api/health` returns version and HTTP 200.
- [ ] Confirm guarded config switches are present on VPS.
