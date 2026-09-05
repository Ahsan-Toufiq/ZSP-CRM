export type UUID = string;

export interface User {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  is_superuser: boolean;
  full_name: string;
  access_tabs: string[];
  tab_permissions?: Record<string, 'none' | 'view' | 'full'>;
  is_permanent_admin: boolean;
}

export interface ManagedUser extends User {
  is_active: boolean;
  effective_tab_permissions: Record<string, 'none' | 'view' | 'full'>;
  date_joined: string;
  last_login: string | null;
}

export interface Customer {
  id: UUID;
  name: string;
  customer_type: 'individual' | 'business';
  phone: string;
  email: string;
  cnic_or_tax_id: string;
  address: string;
  notes: string;
  is_active: boolean;
  balance: string | number;
  can_delete: boolean;
}

export interface Container {
  id: UUID;
  reference: string;
  origin_country: string;
  supplier_name: string;
  arrival_date: string | null;
  manifest_notes: string;
  status: string;
  added_cost: string;
  raw_parts_cost: string;
  total_container_cost: string;
  item_count: number;
}

export interface ContainerItem {
  id: UUID;
  container: UUID;
  container_reference: string;
  lot_number: string;
  part_name: string;
  part_number: string;
  description: string;
  category: string;
  condition: string;
  quantity: number;
  unit: string;
  reserve_price: string | null;
  raw_unit_cost: string;
  raw_total_cost: string;
  added_cost_share: string;
  net_unit_cost: string;
  net_total_cost: string;
  status: string;
}

export interface PartInventory {
  id: UUID;
  part_name: string;
  part_number: string;
  description: string;
  category: string;
  condition: string;
  quantity: number;
  unit: string;
  reserve_price: string | null;
  sold_quantity: number;
  available_quantity: number;
  batches: InventoryBatch[];
}

export interface InventoryBatch {
  id: UUID;
  item: UUID;
  part_name: string;
  part_number: string;
  category: string;
  condition: string;
  unit: string;
  container: UUID | null;
  container_reference: string | null;
  container_item: UUID | null;
  source_label: string;
  quantity: number;
  sold_quantity: number;
  available_quantity: number;
  raw_unit_cost: string;
  net_unit_cost: string;
  notes: string;
}

export interface AuctionSaleLine {
  id: UUID;
  item: PartInventory;
  inventory_batch: UUID | null;
  inventory_batch_label: string;
  quantity: number;
  sold_price: string;
  raw_unit_cost_snapshot: string;
  net_unit_cost_snapshot: string;
  line_total: string;
  notes: string;
}

export interface AuctionSale {
  id: UUID;
  sale_number: string;
  sale_date: string;
  customer: UUID | null;
  customer_name: string | null;
  payment_type: string;
  notes: string;
  total_amount: string;
  is_cancelled: boolean;
  lines: AuctionSaleLine[];
  gate_pass: {
    id: UUID;
    gate_pass_number: string;
    print_status: string;
    issued_to_name: string;
    vehicle_number: string;
    driver_name: string;
    printed_at: string | null;
  } | null;
}

export interface GatePass {
  id: UUID;
  gate_pass_number: string;
  issued_to_name: string;
  issued_to_phone: string;
  vehicle_number: string;
  driver_name: string;
  notes: string;
  print_status: string;
  printed_at: string | null;
  issued_at: string;
  lines: { id: UUID; sale_line: AuctionSaleLine }[];
}

export interface ChequeStatus {
  id: UUID;
  name: string;
  balance_effect: string;
  is_system: boolean;
  is_active: boolean;
}

export interface Cheque {
  id: UUID;
  cheque_number: string;
  customer: UUID;
  customer_name: string;
  name_on_cheque: string;
  bank_name: string;
  branch_name: string;
  account_title: string;
  amount: string;
  cheque_date: string;
  expiry_date: string;
  received_date: string;
  status: UUID;
  status_name: string;
  sale: UUID | null;
  settlement_allocations: ChequeSettlementAllocation[];
  notes: string;
}

export interface ChequeSettlementAllocation {
  id: UUID;
  cheque: UUID;
  sale: UUID;
  sale_number: string;
  sale_date: string;
  amount: string;
  is_reversed: boolean;
  created_at: string;
}

export interface DropdownOption {
  id: UUID;
  group: 'bank' | 'part_name' | 'item_category' | 'item_condition' | 'item_unit';
  label: string;
  value: string;
  is_system: boolean;
  is_active: boolean;
  sort_order: number;
}

export interface CustomerLedgerEntry {
  id: UUID;
  customer: UUID;
  customer_name: string;
  entry_date: string;
  entry_type: string;
  description: string;
  debit: string;
  credit: string;
  sale: UUID | null;
  sale_number: string | null;
  cheque: UUID | null;
  cheque_number: string | null;
  created_at: string;
}

export interface DashboardSummary {
  containers: number;
  items: {
    total: number;
    by_status: Record<string, number>;
  };
  auction_sales: number;
  gate_passes: {
    issued: number;
    not_printed: number;
    printed: number;
    verified?: number;
  };
  cheques_by_status: Record<string, number>;
  customer_receivable: string | number;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
