# Production Readiness

This document tracks what is already implemented in the new Digi7 ZSP build and what must still be completed before replacing the current live ZSP app.

## Implemented

- Django REST backend with PostgreSQL.
- Next.js frontend with TypeScript.
- Container management.
- Spare-parts inventory management.
- Separate container inventory and calculated parts inventory views.
- Customer management.
- Auction sale recording.
- Quantity-based auction sale lines.
- One auction sale can include multiple items.
- Customer required for non-cash sales.
- Cash sales do not create customer balance entries.
- Gate-pass creation from the auction-sale workflow.
- Gate-pass print action from the sale record.
- Gate-pass print status and two-copy browser print layout.
- Gate-pass details synchronize when an editable sale changes.
- Cheque register.
- System and custom cheque statuses.
- Configurable cheque-status balance effects.
- Cheque sale creation from auction-sale entry.
- Separately entered cleared cheques allocate to the oldest open balances first.
- Split cheque settlements are stored explicitly for balance breakdowns.
- Ledger-based customer balances.
- Merged customer and balance view with ledger breakdown.
- Active/inactive customer status control.
- Modal-driven data entry/editing instead of side-mounted forms.
- Persisted dropdown options for banks, categories, conditions, and units.
- Basic audit log entries for sales, gate passes, and cheque status changes.
- API role permissions for admin, operations, finance, and gatekeeper.
- Local seed data and role-specific demo users.
- Backend service tests for quantity-based sale, sale-created gate-pass, and cheque-allocation logic.

## Required Before Live Replacement

### Live Cutover Blockers

The new build should not replace the current live ZSP deployment until these are done:

- Create/connect the Git remote for this new repository.
- Create Render services for backend, frontend, and managed PostgreSQL. A starter `render.yaml` is now included.
- Set production environment variables for both services.
- Run migrations on a staging/prod clone.
- Migrate useful production data from the current live app into the new PostgreSQL schema.
- Reconcile inventory, sales, customer balances, cheques, and gate-pass records after migration.
- Configure `zsp.digi7.org` routing only after staging verification passes.
- Configure an API hostname such as `zsp-api.digi7.org` for the backend service, or add a proper reverse proxy if frontend and API must share one hostname.
- Keep a rollback path to the current live Laravel deployment.

### Gate Pass Scanning

The current system creates and prints gate passes from the sale record. Production should still add QR/barcode scanning. A gatekeeper needs a fast validation screen that can scan the pass, show all items, and clearly mark whether the pass is valid, cancelled, or not found.

### Manifest Import

Manual inventory entry works, but real containers can include many parts. Production should support CSV/Excel import with validation, duplicate detection, and an import error report.

### User and Role Administration

Roles exist at API level, but the frontend does not yet include a user-management screen. Production needs admin UI for creating users, assigning roles, resetting passwords, and disabling accounts.

### Reports

Minimum production reports should include:

- Container inventory status.
- Available inventory.
- Sales by gate-pass print status.
- Sold quantities by container and part.
- Customer receivables.
- Cheque ageing and expiry.
- Daily auction sales.
- Daily gate-pass releases.

### Data Migration

Before replacing the live app, export and inspect existing ZSP data. Build a migration script only for useful production data. Do not migrate demo, test, or corrupted records.

### Production Deployment

Production still needs:

- Managed PostgreSQL instance.
- Backend service.
- Frontend service.
- HTTPS domain routing.
- Secure environment variables.
- Database backups.
- Error logging/monitoring.
- Deployment runbook.

### Security Hardening

Before launch:

- Enforce strong production passwords.
- Confirm CSRF/CORS production origins.
- Add login monitoring.
- Add rate limiting beyond login if abuse becomes a concern.
- Review all permissions with actual staff responsibilities.
- Disable demo seed command in production workflow.

## Optional Later Enhancements

- Urdu/local-language interface.
- Item photos and document attachments.
- Auction bidder history.
- Customer credit limits.
- Automated cheque expiry reminders.
- Printable customer statements.
- Multi-tenant Digi7 SaaS architecture.
- Dedicated mobile gatekeeper view.
