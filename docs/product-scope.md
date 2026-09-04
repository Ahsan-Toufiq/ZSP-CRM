# Product Scope: ZSP Spare-Parts Auctions

## Business Model

ZSP imports containers of spare parts from overseas. Each container arrives with a list of individual spare parts. The parts are auctioned individually, then released from the premises only after a controlled gate-pass process.

The critical business risk is inventory leakage. Sold quantities should not physically leave unless they are covered by a printed gate pass generated from the sale.

## Core Objects

### Customers

Customers represent real parties with balances. Non-cash transactions must be linked to a customer. Cash sales may be recorded without a customer.

Customer phone numbers are mandatory and must include a country code.

### Containers

Containers represent incoming shipments. Each container has a reference, origin, supplier, arrival date, status, and notes.

### Container Items

Container items represent spare-part inventory lines inside a specific container. Each item has a lot number, part name, optional part number/category/condition, quantity, reserve price, and lifecycle status.

Sales consume quantities from a container item. The original container inventory quantity changes only when a user intentionally edits inventory from the container screen.

### Auction Sales

Auction sales record the transaction price for sold parts. One auction sale can include multiple items, and each sale line has its own quantity and unit sold price.

If payment type is cheque, cheque details are captured from the same sale dialog and a pending cheque record is created automatically. Customer balance increases at the sale date for non-cash sales, then reduces only when the cheque reaches a settlement status.

### Gate Passes

Gate passes are generated from the auction sale. The separate gate-pass tab is intentionally removed from the main workflow.

Printing happens from the sale record. The printed document contains two copies and includes an authorisation-stamp area.

If a sale is edited, gate-pass details and sale lines synchronize with it, and print status resets to not printed.

### Cheques

Cheques are linked to customers and track date, expiry, bank, amount, status, and history. The system statuses are:

- `Pending`
- `Bounced`
- `Settled`
- `Settled by Cash`
- `Cleared`

Custom statuses can be added and persist for all users.

Cheque statuses have configurable balance effects. A status can have no automatic effect, settle customer balance, or reverse a previous settlement.

`Pending` is retained as the pre-clearance holding status because a cheque cannot be `Cleared`, `Settled`, or `Bounced` at the moment it is merely received.

Separately entered cheques, when moved to a settlement status, allocate against the customer's oldest open non-cash sales first. Split settlements are stored explicitly so a balance can show which cheque paid which sale.

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
- Quantity sale limits are enforced server-side, not just by the UI.
- The app is currently ZSP-specific, not multi-tenant SaaS.
- Lifecycle statuses are controlled by workflow services, not arbitrary dropdown text.
- Descriptive dropdowns such as bank, category, condition, and unit are persisted option records.

## Open Business Questions

- Should container manifests be imported from Excel/CSV instead of only manual entry?
- Should gate passes include QR codes or barcode scanning?
- What exact printed gate-pass format does the gatekeeper need after real-world use?
- Can auction sales be cancelled after a gate pass is printed?
- What approval is required for reversing a cheque settlement?
- Do customer balances need manual adjustment entries from finance?
- Are item photos or document attachments required?
- Is Urdu or another language required at launch, or only in phase two?
- Does ZSP need branch/location-level inventory separation?
- What reports are mandatory for daily closing?
