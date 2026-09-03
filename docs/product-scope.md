# Product Scope: ZSP Spare-Parts Auctions

## Business Model

ZSP imports containers of spare parts from overseas. Each container arrives with a list of individual spare parts. The parts are auctioned individually, then released from the premises only after a controlled gate-pass process.

The critical business risk is inventory leakage. A sold item should not physically leave unless it is linked to a verified gate pass.

## Core Objects

### Customers

Customers represent real parties with balances. Non-cash transactions must be linked to a customer. Cash sales may be recorded without a customer.

### Containers

Containers represent incoming shipments. Each container has a reference, origin, supplier, arrival date, status, and notes.

### Container Items

Container items represent auctionable spare parts. Each item has a lot number, part name, optional part number/category/condition, quantity, reserve price, and lifecycle status.

An item can be sold once only.

### Auction Sales

Auction sales record the transaction price for sold parts. The backend supports multiple lines per sale, but the current frontend records one sold lot at a time because the described business process auctions parts individually.

### Gate Passes

Gate passes are issued for sold items waiting for release. A gate pass may include multiple sold items. A sold item can belong to only one gate pass.

Verification at the gate changes the gate pass to verified and marks its items as released.

### Cheques

Cheques are linked to customers and track date, expiry, bank, amount, status, and history. The system statuses are:

- `Settle for Cash`
- `Bounced`
- `Cleared`

Custom statuses can be added and persist for all users.

### Customer Balances

Balances are calculated from ledger entries instead of storing a mutable balance on the customer. This keeps sales, settlements, reversals, and adjustments auditable.

## Role Model

Current roles:

- Admin: full access.
- Operations: customers, containers, inventory, auction sales, gate-pass issuing, and read-only finance visibility.
- Finance: customers, cheques, statuses, ledger, balances, and dashboard.
- Gatekeeper: gate-pass lookup and verification only.

## Important Product Decisions

- PostgreSQL is the source database from day one.
- Session authentication is used instead of browser localStorage tokens.
- Customer balance is ledger-derived for auditability.
- Item sale and gate-pass uniqueness are enforced with database constraints, not just UI checks.
- The app is currently ZSP-specific, not multi-tenant SaaS.

## Open Business Questions

- Should container manifests be imported from Excel/CSV instead of only manual entry?
- Should gate passes include QR codes or barcode scanning?
- What exact printed gate-pass format does the gatekeeper need?
- Can auction sales be cancelled after a gate pass is issued?
- What approval is required for reversing a cheque settlement?
- Do customer balances need manual adjustment entries from finance?
- Are item photos or document attachments required?
- Is Urdu or another language required at launch, or only in phase two?
- Does ZSP need branch/location-level inventory separation?
- What reports are mandatory for daily closing?
