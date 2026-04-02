# Telegram Dialog Picker Design

## Goal

Add a post-login Settings UI that lets the user search their Telegram dialogs, inspect usable IDs, and click a result to prefill the existing "add monitored group" form.

## Scope

- Add a backend endpoint that returns normalized Telegram dialog metadata for the currently authorized account.
- Keep the existing manual add-group form and `/groups/` submission flow intact.
- Show all dialogs in the picker, but sort group-like dialogs ahead of non-group dialogs.
- Use Telegram raw entity IDs for prefilling the monitored group form.

## Non-Goals

- No direct "add monitoring" action from the search results.
- No server-side live search or pagination in the first iteration.
- No attempt to infer hidden/private group IDs beyond what the logged-in account can already see.

## Backend Design

- Add a dialog listing helper in the Telegram client module that reads from `iter_dialogs()`.
- Normalize each dialog into a small JSON shape:
  - `raw_id`
  - `dialog_id`
  - `name`
  - `username`
  - `type`
  - `is_group_like`
- Expose a new authenticated endpoint at `GET /auth/dialogs`.
- If Telegram is not configured or the user is not authorized, return a clear 4xx error instead of an empty list.

## Frontend Design

- In Settings, when Telegram is authorized, show a new "search Telegram dialogs" section above the manual add-group form.
- Add a local search box that filters by dialog name, username, raw ID, or dialog ID.
- Sort results so group/channel-like items appear before other dialogs.
- Clicking a result prefills the existing fields:
  - `群组 ID` gets `raw_id`
  - `名称` gets dialog `name`
  - `类型` gets normalized dialog `type`
- Keep manual editing available after prefilling.

## Error Handling

- If dialog loading fails, show the backend error message and a retry affordance.
- If a dialog lacks a usable `raw_id`, show it as unavailable for selection.
- Do not hide or break the existing manual form when dialog loading fails.

## Testing

- Add backend tests for `GET /auth/dialogs` covering:
  - authorized and configured success path
  - unauthorized path
  - normalized response shape and type mapping
- Verify frontend integration by rebuilding the Docker frontend image and restarting services.
