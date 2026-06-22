## 1. Admin Inventory

- [ ] 1.1 Inventory existing CLI/status commands that expose provider, auth, model, and route state.
- [ ] 1.2 Inventory current dashboard telemetry endpoints.
- [ ] 1.3 Identify which admin pages can be read-only in the first pass.
- [ ] 1.4 Identify unsafe actions that require later specs.

## 2. Navigation

- [ ] 2.1 Add donor-style grouped navigation for operations, configuration, observability, and diagnostics.
- [ ] 2.2 Add active page highlighting.
- [ ] 2.3 Ensure navigation remains usable on narrow viewports.
- [ ] 2.4 Ensure generated or placeholder links do not ship as dead UI.

## 3. Admin Pages

- [ ] 3.1 Add Models page with aliases, upstream model IDs, provider family, and endpoint compatibility.
- [ ] 3.2 Add Providers page with redacted auth readiness and provider status.
- [ ] 3.3 Add Routes page with endpoint and model routing behavior.
- [ ] 3.4 Add Request Log page with recent local proxy requests.
- [ ] 3.5 Add Diagnostics page with redacted local health checks.
- [ ] 3.6 Add Settings page for read-only effective settings.

## 4. Controls and Data

- [ ] 4.1 Use global duration controls on time-series and log pages.
- [ ] 4.2 Hide duration controls on non-time-series configuration pages.
- [ ] 4.3 Use explicit redaction for credentials and tokens.
- [ ] 4.4 Avoid mock data on all admin pages.

## 5. Verification

- [ ] 5.1 Browser-check every admin page.
- [ ] 5.2 Verify no console errors.
- [ ] 5.3 Verify no secrets render in the DOM.
- [ ] 5.4 Verify shared duration applies to log and telemetry pages.

