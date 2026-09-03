export type UUID = string;

export interface User {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  is_staff: boolean;
  is_superuser: boolean;
  full_name: string;
  roles: string[];
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
}

export interface Container {
  id: UUID;
  reference: string;
  origin_country: string;
  supplier_name: string;
  arrival_date: string | null;
  manifest_notes: string;
  status: string;
  item_count: number;
}

export interface ContainerItem {
  id: UUID;
  container: UUID;
  container_reference: string;
  lot_number: string;
  part_name: string;
  part_number: string;
  category: string;
  condition: string;
  quantity: number;
  unit: string;
  reserve_price: string | null;
  status: string;
}

export interface AuctionSaleLine {
  id: UUID;
  item: ContainerItem;
  sold_price: string;
  notes: string;
}

export interface AuctionSale {
  id: UUID;
  sale_number: string;
  sale_date: string;
  customer: UUID | null;
  customer_name: string | null;
  payment_type: string;
  total_amount: string;
  is_cancelled: boolean;
  lines: AuctionSaleLine[];
}

export interface GatePass {
  id: UUID;
  gate_pass_number: string;
  issued_to_name: string;
  issued_to_phone: string;
  vehicle_number: string;
  driver_name: string;
  status: string;
  issued_at: string;
  verified_at: string | null;
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
  bank_name: string;
  amount: string;
  cheque_date: string;
  expiry_date: string;
  received_date: string;
  status: UUID;
  status_name: string;
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
    verified: number;
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
