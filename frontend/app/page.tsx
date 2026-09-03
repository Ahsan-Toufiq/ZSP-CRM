'use client';

import {
  BadgeCheck,
  Banknote,
  Boxes,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Container as ContainerIcon,
  FileCheck2,
  Gavel,
  LayoutDashboard,
  LogIn,
  Pencil,
  Plus,
  Printer,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Users,
  WalletCards,
  X,
} from 'lucide-react';
import Image from 'next/image';
import PhoneInput from 'react-phone-number-input';
import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import { destroy, get, list, patch, post } from '@/lib/api';
import type {
  AuctionSale,
  AuctionSaleLine,
  Cheque,
  ChequeStatus,
  Container,
  ContainerItem,
  Customer,
  CustomerLedgerEntry,
  DashboardSummary,
  DropdownOption,
  GatePass,
  Paginated,
  User,
  UUID,
} from '@/lib/types';

type Tab = 'dashboard' | 'customers' | 'containers' | 'sales' | 'gate-passes' | 'cheques' | 'settings';
type ModalState =
  | { type: 'customer'; customer?: Customer }
  | { type: 'container'; container?: Container }
  | { type: 'item'; item?: ContainerItem; containerId?: UUID }
  | { type: 'sale'; sale?: AuctionSale }
  | { type: 'gate-pass'; gatePass?: GatePass }
  | { type: 'cheque'; cheque?: Cheque }
  | { type: 'cheque-status' }
  | { type: 'dropdown-option'; group?: DropdownOption['group'] }
  | null;

const tabs: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={18} /> },
  { id: 'customers', label: 'Customers & Balances', icon: <Users size={18} /> },
  { id: 'containers', label: 'Containers & Inventory', icon: <ContainerIcon size={18} /> },
  { id: 'sales', label: 'Auction Sales', icon: <Gavel size={18} /> },
  { id: 'gate-passes', label: 'Gate Passes', icon: <FileCheck2 size={18} /> },
  { id: 'cheques', label: 'Cheques', icon: <WalletCards size={18} /> },
  { id: 'settings', label: 'Dropdown Settings', icon: <Boxes size={18} /> },
];

const emptyPage = <T,>(): Paginated<T> => ({ count: 0, next: null, previous: null, results: [] });
const valueOf = <T,>(result: PromiseSettledResult<T>, fallback: T): T => result.status === 'fulfilled' ? result.value : fallback;

function money(value: string | number | null | undefined) {
  const amount = Number(value ?? 0);
  return new Intl.NumberFormat('en-PK', { style: 'currency', currency: 'PKR', maximumFractionDigits: 0 }).format(amount);
}

function statusClass(status: string) {
  const normalized = status.toLowerCase().replaceAll(' ', '_');
  if (['available', 'cleared', 'verified', 'released', 'active', 'printed', 'settled'].includes(normalized)) return 'badge good';
  if (['sold', 'issued', 'ready_for_auction', 'pending', 'not_printed', 'settled_by_cash'].includes(normalized)) return 'badge warn';
  if (['bounced', 'cancelled', 'void', 'inactive', 'damaged'].includes(normalized)) return 'badge bad';
  return 'badge';
}

function optionLabels(options: DropdownOption[], group: DropdownOption['group']) {
  return options.filter((option) => option.group === group && option.is_active).map((option) => option.label);
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [isAuthenticated, setAuthenticated] = useState(false);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [modal, setModal] = useState<ModalState>(null);
  const [expandedContainers, setExpandedContainers] = useState<Set<UUID>>(new Set());
  const [expandedCustomers, setExpandedCustomers] = useState<Set<UUID>>(new Set());
  const [message, setMessage] = useState('');

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [containers, setContainers] = useState<Container[]>([]);
  const [items, setItems] = useState<ContainerItem[]>([]);
  const [sales, setSales] = useState<AuctionSale[]>([]);
  const [soldPendingGatePass, setSoldPendingGatePass] = useState<AuctionSaleLine[]>([]);
  const [gatePasses, setGatePasses] = useState<GatePass[]>([]);
  const [cheques, setCheques] = useState<Cheque[]>([]);
  const [chequeStatuses, setChequeStatuses] = useState<ChequeStatus[]>([]);
  const [ledgerEntries, setLedgerEntries] = useState<CustomerLedgerEntry[]>([]);
  const [dropdownOptions, setDropdownOptions] = useState<DropdownOption[]>([]);

  const availableItems = useMemo(() => items.filter((item) => item.status === 'available'), [items]);
  const currentTitle = tabs.find((tab) => tab.id === activeTab)?.label ?? 'Dashboard';

  async function refreshData() {
    setLoading(true);
    setMessage('');
    const [
      summaryData,
      customerData,
      containerData,
      itemData,
      salesData,
      pendingGatePassData,
      gatePassData,
      chequeData,
      statusData,
      ledgerData,
      optionData,
    ] = await Promise.allSettled([
      get<DashboardSummary>('/finance/dashboard-summary/'),
      list<Customer>('/operations/customers/'),
      list<Container>('/operations/containers/'),
      list<ContainerItem>('/operations/items/'),
      list<AuctionSale>('/operations/auction-sales/'),
      list<AuctionSaleLine>('/operations/auction-sales/sold-without-gate-pass/'),
      list<GatePass>('/operations/gate-passes/'),
      list<Cheque>('/finance/cheques/'),
      list<ChequeStatus>('/finance/cheque-statuses/'),
      list<CustomerLedgerEntry>('/finance/ledger/?page_size=200'),
      list<DropdownOption>('/catalog/dropdown-options/?page_size=200'),
    ]);

    setSummary(valueOf(summaryData, null));
    setCustomers(valueOf(customerData, emptyPage<Customer>()).results);
    setContainers(valueOf(containerData, emptyPage<Container>()).results);
    setItems(valueOf(itemData, emptyPage<ContainerItem>()).results);
    setSales(valueOf(salesData, emptyPage<AuctionSale>()).results);
    setSoldPendingGatePass(valueOf(pendingGatePassData, emptyPage<AuctionSaleLine>()).results);
    setGatePasses(valueOf(gatePassData, emptyPage<GatePass>()).results);
    setCheques(valueOf(chequeData, emptyPage<Cheque>()).results);
    setChequeStatuses(valueOf(statusData, emptyPage<ChequeStatus>()).results);
    setLedgerEntries(valueOf(ledgerData, emptyPage<CustomerLedgerEntry>()).results);
    setDropdownOptions(valueOf(optionData, emptyPage<DropdownOption>()).results);
    setLoading(false);
  }

  useEffect(() => {
    async function boot() {
      try {
        await get('/auth/csrf/');
        const user = await get<User & { authenticated?: boolean }>('/auth/me/');
        if (user.authenticated === false) {
          setAuthenticated(false);
          setLoading(false);
          return;
        }
        setCurrentUser(user);
        setAuthenticated(true);
        await refreshData();
      } catch {
        setAuthenticated(false);
        setLoading(false);
      }
    }
    boot();
  }, [refreshKey]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError('');
    const form = new FormData(event.currentTarget);
    try {
      await get('/auth/csrf/');
      await post('/auth/login/', { username: form.get('username'), password: form.get('password') });
      const user = await get<User>('/auth/me/');
      setCurrentUser(user);
      setAuthenticated(true);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Login failed.');
    }
  }

  async function save(path: string, payload: unknown, method: 'post' | 'patch' = 'post') {
    setMessage('');
    try {
      method === 'patch' ? await patch(path, payload) : await post(path, payload);
      setModal(null);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to save record.');
    }
  }

  async function remove(path: string) {
    setMessage('');
    try {
      await destroy(path);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to delete record.');
    }
  }

  async function quickPatch(path: string, payload: unknown) {
    setMessage('');
    try {
      await patch(path, payload);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to update record.');
    }
  }

  function toggleSet(setter: (value: (previous: Set<UUID>) => Set<UUID>) => void, id: UUID) {
    setter((previous) => {
      const next = new Set(previous);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function markChequeStatus(cheque: Cheque, statusId: UUID) {
    await post(`/finance/cheques/${cheque.id}/change-status/`, { status: statusId, notes: '' });
    setRefreshKey((key) => key + 1);
  }

  async function verifyGatePass(gatePass: GatePass) {
    await post(`/operations/gate-passes/${gatePass.id}/verify/`, {});
    setRefreshKey((key) => key + 1);
  }

  async function printGatePass(gatePass: GatePass) {
    const printWindow = window.open('', '_blank', 'width=920,height=720');
    if (!printWindow) {
      setMessage('Browser blocked the print window. Allow popups for this site and try again.');
      return;
    }
    printWindow.document.write(gatePassPrintHtml(gatePass));
    printWindow.document.close();
    printWindow.focus();
    printWindow.print();
    await post(`/operations/gate-passes/${gatePass.id}/mark-printed/`, {});
    setRefreshKey((key) => key + 1);
  }

  if (!isAuthenticated) {
    return (
      <main className="login-screen">
        <section className="login-card">
          <div className="login-brand">
            <Image src="/digi7-logo.png" alt="Digi7" width={291} height={90} priority />
            <div>
              <p className="eyebrow">ZSP spare-parts operations</p>
              <h1>Secure auction control</h1>
              <p className="muted">Containers, sold lots, gate release, cheques, and customer balances in one controlled workflow.</p>
            </div>
          </div>
          <form onSubmit={handleLogin} className="login-form">
            <Field name="username" label="Username" required />
            <Field name="password" label="Password" type="password" required />
            {authError ? <div className="alert">{authError}</div> : null}
            <button className="btn primary wide" type="submit"><LogIn size={18} /> Sign in</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <Image src="/digi7-logo.png" alt="Digi7" width={194} height={60} priority />
          <div><strong>ZSP Control</strong><span>{currentUser?.full_name ?? 'Operations'}</span></div>
        </div>
        <nav className="nav">
          {tabs.map((tab) => <button key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => setActiveTab(tab.id)}>{tab.icon}<span>{tab.label}</span></button>)}
        </nav>
      </aside>
      <section className="main">
        <header className="topbar">
          <div><p className="eyebrow">Digi7 for ZSP spare-parts auctions</p><h1>{currentTitle}</h1><p className="muted">Fast operational entry with guarded inventory release and auditable receivables.</p></div>
          <button className="btn" onClick={() => setRefreshKey((key) => key + 1)}><RefreshCw size={18} /> Refresh</button>
        </header>
        {message ? <div className="alert">{message}</div> : null}
        {loading ? <div className="empty-state">Loading operational data...</div> : null}
        {!loading && activeTab === 'dashboard' ? <Dashboard summary={summary} soldPendingGatePass={soldPendingGatePass} /> : null}
        {!loading && activeTab === 'customers' ? <CustomersPanel customers={customers} ledgerEntries={ledgerEntries} expanded={expandedCustomers} onToggle={(id) => toggleSet(setExpandedCustomers, id)} onAdd={() => setModal({ type: 'customer' })} onEdit={(customer) => setModal({ type: 'customer', customer })} onStatus={(customer) => quickPatch(`/operations/customers/${customer.id}/`, { is_active: !customer.is_active })} /> : null}
        {!loading && activeTab === 'containers' ? <ContainersPanel containers={containers} items={items} expanded={expandedContainers} onToggle={(id) => toggleSet(setExpandedContainers, id)} onAdd={() => setModal({ type: 'container' })} onEdit={(container) => setModal({ type: 'container', container })} onAddItem={(containerId) => setModal({ type: 'item', containerId })} onEditItem={(item) => setModal({ type: 'item', item })} onDeleteItem={(item) => remove(`/operations/items/${item.id}/`)} /> : null}
        {!loading && activeTab === 'sales' ? <SalesPanel sales={sales} onAdd={() => setModal({ type: 'sale' })} onEdit={(sale) => setModal({ type: 'sale', sale })} /> : null}
        {!loading && activeTab === 'gate-passes' ? <GatePassPanel gatePasses={gatePasses} onAdd={() => setModal({ type: 'gate-pass' })} onEdit={(gatePass) => setModal({ type: 'gate-pass', gatePass })} onPrint={printGatePass} onVerify={verifyGatePass} /> : null}
        {!loading && activeTab === 'cheques' ? <ChequesPanel cheques={cheques} statuses={chequeStatuses} onAdd={() => setModal({ type: 'cheque' })} onEdit={(cheque) => setModal({ type: 'cheque', cheque })} onStatus={markChequeStatus} onAddStatus={() => setModal({ type: 'cheque-status' })} /> : null}
        {!loading && activeTab === 'settings' ? <SettingsPanel options={dropdownOptions} onAdd={(group) => setModal({ type: 'dropdown-option', group })} /> : null}
      </section>
      <ModalShell modal={modal} onClose={() => setModal(null)}>
        {modal?.type === 'customer' ? <CustomerForm customer={modal.customer} onSave={save} /> : null}
        {modal?.type === 'container' ? <ContainerForm container={modal.container} onSave={save} /> : null}
        {modal?.type === 'item' ? <ItemForm item={modal.item} containerId={modal.containerId} containers={containers} options={dropdownOptions} onSave={save} /> : null}
        {modal?.type === 'sale' ? <SaleForm sale={modal.sale} customers={customers} availableItems={availableItems} banks={optionLabels(dropdownOptions, 'bank')} onSave={save} onAddCustomer={() => setModal({ type: 'customer' })} /> : null}
        {modal?.type === 'gate-pass' ? <GatePassForm gatePass={modal.gatePass} pending={soldPendingGatePass} onSave={save} /> : null}
        {modal?.type === 'cheque' ? <ChequeForm cheque={modal.cheque} customers={customers} statuses={chequeStatuses} banks={optionLabels(dropdownOptions, 'bank')} onSave={save} /> : null}
        {modal?.type === 'cheque-status' ? <ChequeStatusForm onSave={save} /> : null}
        {modal?.type === 'dropdown-option' ? <DropdownOptionForm group={modal.group} onSave={save} /> : null}
      </ModalShell>
    </main>
  );
}

function Dashboard({ summary, soldPendingGatePass }: { summary: DashboardSummary | null; soldPendingGatePass: AuctionSaleLine[] }) {
  return <div className="dashboard-grid"><Metric icon={<ContainerIcon size={22} />} label="Containers" value={summary?.containers ?? 0} /><Metric icon={<Boxes size={22} />} label="Inventory items" value={summary?.items.total ?? 0} /><Metric icon={<Gavel size={22} />} label="Auction sales" value={summary?.auction_sales ?? 0} /><Metric icon={<Banknote size={22} />} label="Receivable" value={money(summary?.customer_receivable ?? 0)} tone="cash" /><section className="panel span-2"><div className="section-head"><div><h2>Gate exposure</h2><p className="muted">Sold inventory must be controlled until a pass is printed and verified.</p></div></div><div className="metric-row"><Metric compact label="Sold, no pass" value={soldPendingGatePass.length} tone="warning" /><Metric compact label="Issued" value={summary?.gate_passes.issued ?? 0} /><Metric compact label="Verified" value={summary?.gate_passes.verified ?? 0} tone="success" /></div></section><section className="panel span-2"><h2>Inventory state</h2><div className="status-strip">{Object.entries(summary?.items.by_status ?? {}).map(([status, count]) => <div key={status}><span className={statusClass(status)}>{status}</span><strong>{count}</strong></div>)}</div></section></div>;
}

function Metric({ label, value, icon, tone = '', compact = false }: { label: string; value: string | number; icon?: ReactNode; tone?: string; compact?: boolean }) {
  return <div className={`metric-card ${tone} ${compact ? 'compact' : ''}`}>{icon ? <span className="metric-icon">{icon}</span> : null}<div><span>{label}</span><strong>{value}</strong></div></div>;
}

function CustomersPanel({ customers, ledgerEntries, expanded, onToggle, onAdd, onEdit, onStatus }: { customers: Customer[]; ledgerEntries: CustomerLedgerEntry[]; expanded: Set<UUID>; onToggle: (id: UUID) => void; onAdd: () => void; onEdit: (customer: Customer) => void; onStatus: (customer: Customer) => void }) {
  return <section className="panel"><div className="section-head"><div><h2>Customers and balance breakdown</h2><p className="muted">Balances are calculated from sales, cheque settlements, reversals, and adjustments.</p></div><button className="btn primary" onClick={onAdd}><Plus size={18} /> Customer</button></div><div className="record-stack">{customers.map((customer) => { const entries = ledgerEntries.filter((entry) => entry.customer === customer.id); return <article className="record-card" key={customer.id}><button className="record-main" onClick={() => onToggle(customer.id)}>{expanded.has(customer.id) ? <ChevronDown size={18} /> : <ChevronRight size={18} />}<div><strong>{customer.name}</strong><span>{customer.phone} · {customer.customer_type}</span></div><b>{money(customer.balance)}</b><span className={customer.is_active ? 'badge good' : 'badge bad'}>{customer.is_active ? 'Active' : 'Inactive'}</span></button><div className="record-actions"><button className="icon-btn" onClick={() => onEdit(customer)} aria-label={`Edit ${customer.name}`}><Pencil size={16} /></button><button className="btn small" onClick={() => onStatus(customer)}>{customer.is_active ? 'Mark inactive' : 'Mark active'}</button></div>{expanded.has(customer.id) ? <DataTable headers={['Date', 'Type', 'Description', 'Debit', 'Credit']} rows={entries.map((entry) => [entry.entry_date, entry.entry_type, entry.description, money(entry.debit), money(entry.credit)])} /> : null}</article>; })}</div></section>;
}

function ContainersPanel({ containers, items, expanded, onToggle, onAdd, onEdit, onAddItem, onEditItem, onDeleteItem }: { containers: Container[]; items: ContainerItem[]; expanded: Set<UUID>; onToggle: (id: UUID) => void; onAdd: () => void; onEdit: (container: Container) => void; onAddItem: (containerId: UUID) => void; onEditItem: (item: ContainerItem) => void; onDeleteItem: (item: ContainerItem) => void }) {
  return <section className="panel"><div className="section-head"><div><h2>Containers and inventory</h2><p className="muted">Original container inventory changes only when a user intentionally adds, edits, or deletes items here.</p></div><button className="btn primary" onClick={onAdd}><Plus size={18} /> Container</button></div><div className="container-grid">{containers.map((container) => { const containerItems = items.filter((item) => item.container === container.id); return <article className="container-card" key={container.id}><div className="container-top"><button className="record-main compact-main" onClick={() => onToggle(container.id)}>{expanded.has(container.id) ? <ChevronDown size={18} /> : <ChevronRight size={18} />}<div><strong>{container.reference}</strong><span>{container.origin_country || 'Origin not set'} · {container.supplier_name || 'Supplier not set'}</span></div></button><span className={statusClass(container.status)}>{container.status}</span></div><div className="container-meta"><span>{container.arrival_date || 'No arrival date'}</span><span>{containerItems.length} items</span></div><div className="record-actions"><button className="btn small" onClick={() => onAddItem(container.id)}><Plus size={16} /> Add inventory</button><button className="icon-btn" onClick={() => onEdit(container)} aria-label={`Edit ${container.reference}`}><Pencil size={16} /></button></div>{expanded.has(container.id) ? <DataTable headers={['Lot', 'Part', 'Category', 'Qty', 'Condition', 'Status', 'Actions']} rows={containerItems.map((item) => [item.lot_number, <div key={item.id}><strong>{item.part_name}</strong><span className="cell-note">{item.part_number || 'No part number'}</span></div>, item.category || '-', `${item.quantity} ${item.unit}`, item.condition, <span key="status" className={statusClass(item.status)}>{item.status}</span>, <div className="table-actions" key="actions"><button className="icon-btn" onClick={() => onEditItem(item)} aria-label={`Edit ${item.part_name}`}><Pencil size={16} /></button><button className="icon-btn danger" onClick={() => onDeleteItem(item)} aria-label={`Delete ${item.part_name}`}><Trash2 size={16} /></button></div>])} /> : null}</article>; })}</div></section>;
}

function SalesPanel({ sales, onAdd, onEdit }: { sales: AuctionSale[]; onAdd: () => void; onEdit: (sale: AuctionSale) => void }) {
  return <section className="panel"><div className="section-head"><div><h2>Auction sale ledger</h2><p className="muted">Cheque sales create the cheque record from the same sale dialog.</p></div><button className="btn primary" onClick={onAdd}><Gavel size={18} /> Record sale</button></div><DataTable headers={['Sale', 'Date', 'Customer', 'Payment', 'Total', 'Items', 'Actions']} rows={sales.map((sale) => [sale.sale_number, sale.sale_date, sale.customer_name || 'Cash sale', sale.payment_type, money(sale.total_amount), sale.lines.length, <button className="icon-btn" key="edit" onClick={() => onEdit(sale)} aria-label={`Edit ${sale.sale_number}`}><Pencil size={16} /></button>])} /></section>;
}

function GatePassPanel({ gatePasses, onAdd, onEdit, onPrint, onVerify }: { gatePasses: GatePass[]; onAdd: () => void; onEdit: (gatePass: GatePass) => void; onPrint: (gatePass: GatePass) => void; onVerify: (gatePass: GatePass) => void }) {
  const ordered = [...gatePasses].sort((a, b) => new Date(b.issued_at).getTime() - new Date(a.issued_at).getTime());
  return <section className="panel"><div className="section-head"><div><h2>Gate passes</h2><p className="muted">Print two copies, stamp them, then verify the pass at release.</p></div><button className="btn primary" onClick={onAdd}><ClipboardCheck size={18} /> Issue pass</button></div><DataTable headers={['Gate pass', 'Issued to', 'Vehicle', 'Release', 'Print', 'Items', 'Actions']} rows={ordered.map((pass) => [pass.gate_pass_number, pass.issued_to_name, pass.vehicle_number || '-', <span key="release" className={statusClass(pass.status)}>{pass.status}</span>, <span key="print" className={statusClass(pass.print_status)}>{pass.print_status.replace('_', ' ')}</span>, pass.lines.length, <div className="table-actions" key="actions"><button className="icon-btn" onClick={() => onEdit(pass)} aria-label={`Edit ${pass.gate_pass_number}`}><Pencil size={16} /></button><button className="icon-btn" onClick={() => onPrint(pass)} aria-label={`Print ${pass.gate_pass_number}`}><Printer size={16} /></button>{pass.status === 'issued' ? <button className="icon-btn success" onClick={() => onVerify(pass)} aria-label={`Verify ${pass.gate_pass_number}`}><ShieldCheck size={16} /></button> : null}</div>])} /></section>;
}

function ChequesPanel({ cheques, statuses, onAdd, onEdit, onStatus, onAddStatus }: { cheques: Cheque[]; statuses: ChequeStatus[]; onAdd: () => void; onEdit: (cheque: Cheque) => void; onStatus: (cheque: Cheque, statusId: UUID) => void; onAddStatus: () => void }) {
  return <section className="panel"><div className="section-head"><div><h2>Cheque control</h2><p className="muted">Receivables reduce only when a cheque reaches a settlement status.</p></div><div className="head-actions"><button className="btn" onClick={onAddStatus}><Plus size={18} /> Status</button><button className="btn primary" onClick={onAdd}><Plus size={18} /> Cheque</button></div></div><DataTable headers={['Cheque', 'Customer', 'Name on cheque', 'Bank', 'Amount', 'Dates', 'Status', 'Actions']} rows={cheques.map((cheque) => [cheque.cheque_number, cheque.customer_name, cheque.name_on_cheque || '-', cheque.bank_name, money(cheque.amount), <div key="dates">Cheque: {cheque.cheque_date}<span className="cell-note">Expiry: {cheque.expiry_date}</span></div>, <select key="status" value={cheque.status} onChange={(event) => onStatus(cheque, event.target.value)}>{statuses.map((status) => <option key={status.id} value={status.id}>{status.name}</option>)}</select>, <button className="icon-btn" key="edit" onClick={() => onEdit(cheque)} aria-label={`Edit ${cheque.cheque_number}`}><Pencil size={16} /></button>])} /></section>;
}

function SettingsPanel({ options, onAdd }: { options: DropdownOption[]; onAdd: (group?: DropdownOption['group']) => void }) {
  const groups: DropdownOption['group'][] = ['bank', 'item_category', 'item_condition', 'item_unit'];
  return <section className="panel"><div className="section-head"><div><h2>Dropdown settings</h2><p className="muted">Persisted values here appear in future entry dialogs for all users.</p></div><button className="btn primary" onClick={() => onAdd()}><Plus size={18} /> Dropdown value</button></div><div className="settings-grid">{groups.map((group) => <article className="option-card" key={group}><div className="section-head slim"><h3>{group.replace('_', ' ')}</h3><button className="icon-btn" onClick={() => onAdd(group)} aria-label={`Add ${group}`}><Plus size={16} /></button></div><div className="chips">{options.filter((option) => option.group === group && option.is_active).map((option) => <span className="chip" key={option.id}>{option.label}</span>)}</div></article>)}</div></section>;
}

function CustomerForm({ customer, onSave }: { customer?: Customer; onSave: (path: string, payload: unknown, method?: 'post' | 'patch') => void }) {
  const [phone, setPhone] = useState(customer?.phone || '+92');
  return <FormFrame title={customer ? 'Edit customer' : 'Add customer'} onSubmit={(form) => onSave(customer ? `/operations/customers/${customer.id}/` : '/operations/customers/', { ...form, phone, is_active: form.is_active === 'true' }, customer ? 'patch' : 'post')}><Field name="name" label="Customer name" defaultValue={customer?.name} required /><PhoneField value={phone} onChange={(value) => setPhone(value || '')} /><Select name="customer_type" label="Customer type" defaultValue={customer?.customer_type} options={[['individual', 'Individual'], ['business', 'Business']]} required /><Field name="email" label="Email" type="email" defaultValue={customer?.email} /><Field name="cnic_or_tax_id" label="CNIC / tax ID" defaultValue={customer?.cnic_or_tax_id} /><Select name="is_active" label="Status" defaultValue={String(customer?.is_active ?? true)} options={[['true', 'Active'], ['false', 'Inactive']]} required /><Field name="address" label="Address" defaultValue={customer?.address} textarea /></FormFrame>;
}

function ContainerForm({ container, onSave }: { container?: Container; onSave: (path: string, payload: unknown, method?: 'post' | 'patch') => void }) {
  return <FormFrame title={container ? 'Edit container' : 'Add container'} onSubmit={(form) => onSave(container ? `/operations/containers/${container.id}/` : '/operations/containers/', form, container ? 'patch' : 'post')}><Field name="reference" label="Container reference" defaultValue={container?.reference} required /><Field name="origin_country" label="Origin country" defaultValue={container?.origin_country} /><Field name="supplier_name" label="Supplier" defaultValue={container?.supplier_name} /><Field name="arrival_date" label="Arrival date" type="date" defaultValue={container?.arrival_date || ''} /><Select name="status" label="Status" defaultValue={container?.status} options={[['draft', 'Draft'], ['receiving', 'Receiving'], ['ready_for_auction', 'Ready for auction'], ['closed', 'Closed']]} required /><Field name="manifest_notes" label="Manifest notes" defaultValue={container?.manifest_notes} textarea /></FormFrame>;
}

function ItemForm({ item, containerId, containers, options, onSave }: { item?: ContainerItem; containerId?: UUID; containers: Container[]; options: DropdownOption[]; onSave: (path: string, payload: unknown, method?: 'post' | 'patch') => void }) {
  return <FormFrame title={item ? 'Edit inventory item' : 'Add inventory item'} onSubmit={(form) => onSave(item ? `/operations/items/${item.id}/` : '/operations/items/', { ...form, quantity: Number(form.quantity || 1), reserve_price: form.reserve_price || null }, item ? 'patch' : 'post')}><Select name="container" label="Container" defaultValue={item?.container || containerId} options={containers.map((container) => [container.id, container.reference])} required /><Field name="lot_number" label="Lot number" defaultValue={item?.lot_number} required /><Field name="part_name" label="Part name" defaultValue={item?.part_name} required /><Field name="part_number" label="Part number" defaultValue={item?.part_number} /><OptionText name="category" label="Category" defaultValue={item?.category} options={optionLabels(options, 'item_category')} /><OptionText name="condition" label="Condition" defaultValue={item?.condition} options={optionLabels(options, 'item_condition')} /><Field name="quantity" label="Quantity" type="number" defaultValue={String(item?.quantity ?? 1)} required /><OptionText name="unit" label="Unit" defaultValue={item?.unit || 'piece'} options={optionLabels(options, 'item_unit')} /><Field name="reserve_price" label="Reserve price" type="number" defaultValue={item?.reserve_price || ''} /><Field name="description" label="Description" defaultValue={item?.description} textarea /></FormFrame>;
}

function SaleForm({ sale, customers, availableItems, banks, onSave, onAddCustomer }: { sale?: AuctionSale; customers: Customer[]; availableItems: ContainerItem[]; banks: string[]; onSave: (path: string, payload: unknown, method?: 'post' | 'patch') => void; onAddCustomer: () => void }) {
  const [paymentType, setPaymentType] = useState(sale?.payment_type || 'cash');
  const firstLine = sale?.lines[0];
  return <FormFrame title={sale ? 'Edit sale' : 'Record auction sale'} onSubmit={(form) => { if (sale) { onSave(`/operations/auction-sales/${sale.id}/`, { sale_date: form.sale_date, customer: form.customer || null, notes: form.notes || '', lines: sale.lines.map((line) => ({ id: line.id, sold_price: form[`sold_price_${line.id}`], notes: form[`notes_${line.id}`] || '' })) }, 'patch'); return; } const payload: Record<string, unknown> = { sale_date: form.sale_date, customer: form.customer || null, payment_type: paymentType, notes: form.notes || '', lines: [{ item: form.item, sold_price: form.sold_price, notes: form.line_notes || '' }] }; if (paymentType === 'cheque') { payload.cheque = { cheque_number: form.cheque_number, name_on_cheque: form.name_on_cheque, bank_name: form.bank_name, branch_name: form.branch_name || '', account_title: form.account_title || '', amount: form.sold_price, cheque_date: form.cheque_date, expiry_date: form.expiry_date, received_date: form.received_date || null, notes: form.cheque_notes || '' }; } onSave('/operations/auction-sales/', payload); }}><div className="inline-between"><span className="form-note">Customer is mandatory unless payment type is cash.</span><button type="button" className="btn small" onClick={onAddCustomer}><Plus size={16} /> New customer</button></div><Field name="sale_date" label="Sale date" type="date" defaultValue={sale?.sale_date} required />{!sale ? <Select name="payment_type" label="Payment type" value={paymentType} onChange={setPaymentType} options={[['cash', 'Cash'], ['credit', 'Credit'], ['cheque', 'Cheque'], ['mixed', 'Mixed']]} required /> : null}<Select name="customer" label="Customer" defaultValue={sale?.customer || ''} options={customers.map((customer) => [customer.id, customer.name])} required={paymentType !== 'cash' || Boolean(sale?.customer)} />{!sale ? <Select name="item" label="Available item" options={availableItems.map((item) => [item.id, `${item.container_reference} / ${item.lot_number} - ${item.part_name}`])} required /> : <div className="locked-row">Item: {firstLine?.item.container_reference} / {firstLine?.item.lot_number} - {firstLine?.item.part_name}</div>}{!sale ? <Field name="sold_price" label="Sold price" type="number" required /> : sale.lines.map((line) => <div className="line-edit" key={line.id}><Field name={`sold_price_${line.id}`} label={`Sold price: ${line.item.lot_number}`} type="number" defaultValue={line.sold_price} required /><Field name={`notes_${line.id}`} label="Line notes" defaultValue={line.notes} /></div>)}{paymentType === 'cheque' && !sale ? <ChequeFields banks={banks} /> : null}<Field name="notes" label="Sale notes" defaultValue={sale?.notes} textarea /></FormFrame>;
}

function GatePassForm({ gatePass, pending, onSave }: { gatePass?: GatePass; pending: AuctionSaleLine[]; onSave: (path: string, payload: unknown, method?: 'post' | 'patch') => void }) {
  const currentLines = gatePass?.lines.map((line) => line.sale_line) ?? [];
  const options = [...currentLines, ...pending.filter((line) => !currentLines.some((current) => current.id === line.id))];
  return <FormFrame title={gatePass ? 'Edit gate pass' : 'Issue gate pass'} onSubmit={(form, raw) => onSave(gatePass ? `/operations/gate-passes/${gatePass.id}/` : '/operations/gate-passes/', { issued_to_name: form.issued_to_name, issued_to_phone: form.issued_to_phone || '', vehicle_number: form.vehicle_number || '', driver_name: form.driver_name || '', notes: form.notes || '', sale_line_ids: raw.getAll('sale_line_ids') }, gatePass ? 'patch' : 'post')}><Select name="sale_line_ids" label="Sold items for gate pass" defaultValue={currentLines.map((line) => line.id)} options={options.map((line) => [line.id, `${line.item.container_reference} / ${line.item.lot_number} - ${line.item.part_name} (${money(line.sold_price)})`])} required multiple /><Field name="issued_to_name" label="Issued to" defaultValue={gatePass?.issued_to_name} required /><Field name="issued_to_phone" label="Phone" defaultValue={gatePass?.issued_to_phone} /><Field name="vehicle_number" label="Vehicle number" defaultValue={gatePass?.vehicle_number} /><Field name="driver_name" label="Driver name" defaultValue={gatePass?.driver_name} /><Field name="notes" label="Notes" defaultValue={gatePass?.notes} textarea /></FormFrame>;
}

function ChequeForm({ cheque, customers, statuses, banks, onSave }: { cheque?: Cheque; customers: Customer[]; statuses: ChequeStatus[]; banks: string[]; onSave: (path: string, payload: unknown, method?: 'post' | 'patch') => void }) {
  return <FormFrame title={cheque ? 'Edit cheque' : 'Add cheque'} onSubmit={(form) => onSave(cheque ? `/finance/cheques/${cheque.id}/` : '/finance/cheques/', { ...form, received_date: form.received_date || null }, cheque ? 'patch' : 'post')}><Field name="cheque_number" label="Cheque number" defaultValue={cheque?.cheque_number} required /><Select name="customer" label="Customer" defaultValue={cheque?.customer} options={customers.map((customer) => [customer.id, customer.name])} required /><Field name="name_on_cheque" label="Name on cheque" defaultValue={cheque?.name_on_cheque} required /><OptionText name="bank_name" label="Bank" defaultValue={cheque?.bank_name} options={banks} required /><Field name="branch_name" label="Branch" defaultValue={cheque?.branch_name} /><Field name="account_title" label="Account title" defaultValue={cheque?.account_title} /><Field name="amount" label="Amount" type="number" defaultValue={cheque?.amount} required /><Field name="cheque_date" label="Cheque date" type="date" defaultValue={cheque?.cheque_date} required /><Field name="expiry_date" label="Expiry date" type="date" defaultValue={cheque?.expiry_date} required /><Field name="received_date" label="Received date" type="date" defaultValue={cheque?.received_date || ''} />{!cheque ? <Select name="status" label="Status" defaultValue={statuses.find((status) => status.name === 'Pending')?.id} options={statuses.map((status) => [status.id, status.name])} required /> : null}<Field name="notes" label="Notes" defaultValue={cheque?.notes} textarea /></FormFrame>;
}

function ChequeStatusForm({ onSave }: { onSave: (path: string, payload: unknown) => void }) {
  return <FormFrame title="Add cheque status" onSubmit={(form) => onSave('/finance/cheque-statuses/', form)}><Field name="name" label="Status name" required /><Select name="balance_effect" label="Balance effect" options={[['none', 'No automatic balance effect'], ['settles_balance', 'Settles customer balance'], ['reverses_settlement', 'Reverses settlement']]} required /></FormFrame>;
}

function DropdownOptionForm({ group, onSave }: { group?: DropdownOption['group']; onSave: (path: string, payload: unknown) => void }) {
  return <FormFrame title="Add dropdown value" onSubmit={(form) => onSave('/catalog/dropdown-options/', { ...form, sort_order: Number(form.sort_order || 100) })}><Select name="group" label="Dropdown" defaultValue={group} options={[['bank', 'Bank'], ['item_category', 'Item category'], ['item_condition', 'Item condition'], ['item_unit', 'Item unit']]} required /><Field name="label" label="Value" required /><Field name="sort_order" label="Sort order" type="number" defaultValue="100" /></FormFrame>;
}

function ChequeFields({ banks }: { banks: string[] }) {
  return <div className="subform"><h3>Cheque details</h3><Field name="cheque_number" label="Cheque number" required /><Field name="name_on_cheque" label="Name on cheque" required /><OptionText name="bank_name" label="Bank" options={banks} required /><Field name="branch_name" label="Branch" /><Field name="account_title" label="Account title" /><Field name="cheque_date" label="Cheque date" type="date" required /><Field name="expiry_date" label="Expiry date" type="date" required /><Field name="received_date" label="Received date" type="date" /><Field name="cheque_notes" label="Cheque notes" textarea /></div>;
}

function FormFrame({ title, onSubmit, children }: { title: string; onSubmit: (payload: Record<string, FormDataEntryValue>, raw: FormData) => void; children: ReactNode }) {
  return <form className="modal-form" onSubmit={(event) => { event.preventDefault(); const raw = new FormData(event.currentTarget); onSubmit(Object.fromEntries(raw.entries()), raw); }}><h2>{title}</h2><div className="form-grid">{children}</div><button className="btn primary wide" type="submit"><BadgeCheck size={18} /> Save</button></form>;
}

function ModalShell({ modal, onClose, children }: { modal: ModalState; onClose: () => void; children: ReactNode }) {
  if (!modal) return null;
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}><section className="modal-panel" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><button className="modal-close" onClick={onClose} aria-label="Close dialog"><X size={18} /></button>{children}</section></div>;
}

function Field({ name, label, type = 'text', required = false, textarea = false, defaultValue = '' }: { name: string; label: string; type?: string; required?: boolean; textarea?: boolean; defaultValue?: string | number | null }) {
  return <div className="field"><label htmlFor={name}>{label}</label>{textarea ? <textarea id={name} name={name} required={required} defaultValue={String(defaultValue ?? '')} /> : <input id={name} name={name} type={type} required={required} defaultValue={String(defaultValue ?? '')} />}</div>;
}

function PhoneField({ value, onChange }: { value: string; onChange: (value?: string) => void }) {
  return <div className="field"><label htmlFor="phone">Phone number</label><PhoneInput id="phone" name="phone" international defaultCountry="PK" value={value} onChange={onChange} required /></div>;
}

function Select({ name, label, options, required = false, multiple = false, defaultValue, value, onChange }: { name: string; label: string; options: [string, string][]; required?: boolean; multiple?: boolean; defaultValue?: string | string[] | null; value?: string; onChange?: (value: string) => void }) {
  return <div className="field"><label htmlFor={name}>{label}</label><select id={name} name={name} required={required} multiple={multiple} defaultValue={defaultValue ?? (multiple ? [] : '')} value={value} onChange={onChange ? (event) => onChange(event.currentTarget.value) : undefined}>{multiple ? null : <option value="">Select...</option>}{options.map(([optionValue, text]) => <option key={optionValue} value={optionValue}>{text}</option>)}</select></div>;
}

function OptionText({ name, label, options, required = false, defaultValue = '' }: { name: string; label: string; options: string[]; required?: boolean; defaultValue?: string | null }) {
  return <div className="field"><label htmlFor={name}>{label}</label><input id={name} name={name} required={required} defaultValue={defaultValue ?? ''} list={`${name}-options`} /><datalist id={`${name}-options`}>{options.map((option) => <option key={option} value={option} />)}</datalist><span className="help-text">Add new persistent values from Dropdown Settings.</span></div>;
}

function DataTable({ headers, rows }: { headers: string[]; rows: React.ReactNode[][] }) {
  if (rows.length === 0) return <div className="empty-state"><Search size={22} /> No records yet.</div>;
  return <div className="table-wrap"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
}

function gatePassPrintHtml(gatePass: GatePass) {
  const copies = [1, 2].map((copy) => `<section class="copy"><header><div><h1>ZSP Gate Pass</h1><p>Digi7 controlled inventory release</p></div><strong>${gatePass.gate_pass_number}</strong></header><div class="grid"><p><b>Issued to</b><span>${gatePass.issued_to_name}</span></p><p><b>Phone</b><span>${gatePass.issued_to_phone || '-'}</span></p><p><b>Vehicle</b><span>${gatePass.vehicle_number || '-'}</span></p><p><b>Driver</b><span>${gatePass.driver_name || '-'}</span></p><p><b>Copy</b><span>${copy} of 2</span></p><p><b>Issued at</b><span>${new Date(gatePass.issued_at).toLocaleString()}</span></p></div><table><thead><tr><th>Lot</th><th>Part</th><th>Container</th><th>Sold price</th></tr></thead><tbody>${gatePass.lines.map((line) => `<tr><td>${line.sale_line.item.lot_number}</td><td>${line.sale_line.item.part_name}</td><td>${line.sale_line.item.container_reference}</td><td>${money(line.sale_line.sold_price)}</td></tr>`).join('')}</tbody></table><footer><div><span></span><b>Issued by</b></div><div class="stamp"><span></span><b>Authorisation stamp</b></div><div><span></span><b>Gatekeeper</b></div></footer></section>`).join('');
  return `<!doctype html><html><head><title>${gatePass.gate_pass_number}</title><style>body{font-family:Arial,sans-serif;margin:0;color:#111827;background:#fff}.copy{page-break-after:always;padding:28px;min-height:92vh;border:2px solid #111827;margin:18px}header{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #111827;padding-bottom:16px}h1{margin:0;font-size:28px}p{margin:0}header p{color:#4b5563;margin-top:4px}header strong{font-size:20px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}.grid p{border:1px solid #d1d5db;padding:10px}.grid b{display:block;font-size:11px;text-transform:uppercase;color:#4b5563}.grid span{display:block;margin-top:5px;font-size:15px}table{width:100%;border-collapse:collapse;margin-top:16px}th,td{border:1px solid #111827;padding:10px;text-align:left}th{background:#f3f4f6}footer{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-top:60px}footer span{display:block;height:72px;border:1px dashed #6b7280;margin-bottom:8px}.stamp span{height:96px}footer b{font-size:12px;text-transform:uppercase;color:#374151}@media print{.copy{margin:0;border:2px solid #111827}.copy:last-child{page-break-after:auto}}</style></head><body>${copies}</body></html>`;
}
