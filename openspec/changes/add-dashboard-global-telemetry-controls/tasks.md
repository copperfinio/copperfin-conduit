## 1. Control Model

- [ ] 1.1 Define supported duration presets and labels.
- [ ] 1.2 Define supported grouping dimensions.
- [ ] 1.3 Define session storage keys and default values.
- [ ] 1.4 Define telemetry query params used by each dashboard page.

## 2. Topbar Controls

- [ ] 2.1 Move duration, group-by, refresh, and connection status into the topbar.
- [ ] 2.2 Replace text refresh buttons with a compact refresh icon button.
- [ ] 2.3 Hide group-by on pages where grouping does not apply.
- [ ] 2.4 Remove redundant panel-level control headers.

## 3. Data Flow

- [ ] 3.1 Centralize dashboard state read/write in one JavaScript module or object.
- [ ] 3.2 Refetch visible telemetry panels when global controls change.
- [ ] 3.3 Preserve control state across same-tab navigation.
- [ ] 3.4 Render browser-local range labels where shown.

## 4. Verification

- [ ] 4.1 Verify duration dropdown updates data.
- [ ] 4.2 Verify group-by dropdown updates grouped charts or lists.
- [ ] 4.3 Verify refresh button does not reset controls.
- [ ] 4.4 Verify control state survives navigation between dashboard sections.

