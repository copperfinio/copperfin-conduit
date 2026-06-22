## 1. Donor Audit

- [x] 1.1 Inspect Fair Weather Conduit shell layout, rail dimensions, topbar, cards, and panel CSS.
- [x] 1.2 Identify Copperfin dashboard elements that map to donor shell elements.
- [ ] 1.3 Record any donor elements intentionally deferred to later phases.

## 2. Shell Implementation

- [x] 2.1 Replace the dashboard root layout with icon rail, menu rail, workspace, and topbar.
- [ ] 2.2 Normalize CSS variables for backgrounds, panels, borders, text, and accent colors.
- [ ] 2.3 Add stable grid dimensions for metric cards and panels.
- [x] 2.4 Add responsive behavior for narrow viewports without breaking desktop layout.
- [ ] 2.5 Make offline, empty, and partial telemetry states render inside the same shell.

## 3. Cleanup

- [x] 3.1 Remove unused shell markup and CSS selectors from prior experiments.
- [ ] 3.2 Confirm generated folders are not staged.
- [ ] 3.3 Leave dashboard content intact unless required for shell correctness.

## 4. Verification

- [x] 4.1 Run a Python import or compile check for dashboard modules.
- [x] 4.2 Run a JavaScript syntax check for dashboard static code.
- [ ] 4.3 Use Playwright to screenshot `/dashboard`.
- [ ] 4.4 Verify no browser console errors during initial load.
