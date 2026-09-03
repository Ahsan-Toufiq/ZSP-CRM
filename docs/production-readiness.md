# Production Readiness

This document tracks what is already implemented in the new Digi7 ZSP build and what must still be completed before replacing the current live ZSP app.

## Implemented

- Django REST backend with PostgreSQL.
- Next.js frontend with TypeScript.
- Container management.
- Spare-parts inventory management.
- Customer management.
- Auction sale recording.
- Database protection against selling one item twice.
- Customer required for non-cash sales.
- Gate-pass issuing for multiple sold items.
- Database protection against issuing the same sold item to multiple gate passes.
- Gate-pass verification endpoint and UI.
- Cheque register.
- System and custom cheque statuses.
- Ledger-based customer balances.
- Basic audit log entries for sales, gate passes, and cheque status changes.
- API role permissions for admin, operations, finance, and gatekeeper.
- Local seed data and role-specific demo users.
- Backend service tests for core sale, gate-pass, and cheque logic.

## Required Before Live Replacement

### Gate Pass Printing and Scanning

The current system records and verifies gate passes, but production should have a printable gate pass with a unique code, barcode, or QR code. A gatekeeper needs a fast validation screen that can search/scan the pass, show all items, and clearly mark whether the pass is valid, already used, cancelled, or not found.

### Manifest Import

Manual inventory entry works, but real containers can include many parts. Production should support CSV/Excel import with validation, duplicate detection, and an import error report.

### User and Role Administration

Roles exist at API level, but the frontend does not yet include a user-management screen. Production needs admin UI for creating users, assigning roles, resetting passwords, and disabling accounts.

### Reports

Minimum production reports should include:

- Container inventory status.
- Available inventory.
- Sold items pending gate pass.
- Released items.
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
