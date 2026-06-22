## 1. Admin Inventory

- [x] 1.1 Inventory existing CLI/status commands that expose provider, auth, model, and route state.
- [x] 1.2 Inventory current dashboard telemetry endpoints.
- [x] 1.3 Identify which admin pages can be read-only in the first pass.
- [x] 1.4 Identify unsafe actions that require later specs.

## 2. Navigation

- [x] 2.1 Add donor-style grouped navigation for operations, configuration, observability, and diagnostics.
- [x] 2.2 Add active page highlighting.
- [x] 2.3 Ensure navigation remains usable on narrow viewports.
- [x] 2.4 Ensure generated or placeholder links do not ship as dead UI.

## 3. Admin Pages

- [x] 3.1 Add Models page with aliases, upstream model IDs, provider family, and endpoint compatibility.
- [x] 3.2 Add Providers page with redacted auth readiness and provider status.
- [x] 3.3 Add Routes page with endpoint and model routing behavior.
- [x] 3.4 Add Request Log page with recent local proxy requests.
- [x] 3.5 Add Diagnostics page with redacted local health checks.
- [x] 3.6 Add Settings page for read-only effective settings.

## 4. Controls and Data

- [x] 4.1 Use global duration controls on time-series and log pages.
- [ ] 4.2 Hide duration controls on non-time-series configuration pages.
- [x] 4.3 Use explicit redaction for credentials and tokens.
- [x] 4.4 Avoid mock data on all admin pages.

## 5. Verification

- [ ] 5.1 Browser-check every admin page.
- [ ] 5.2 Verify no console errors.
- [ ] 5.3 Verify no secrets render in the DOM.
- [ ] 5.4 Verify shared duration applies to log and telemetry pages.
