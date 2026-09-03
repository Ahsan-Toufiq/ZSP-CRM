'use client';

import {
  BadgeCheck,
  Banknote,
  Boxes,
  ClipboardCheck,
  Container as ContainerIcon,
  FileCheck2,
  Gavel,
  LayoutDashboard,
  LogIn,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Users,
  WalletCards,
} from 'lucide-react';
import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import { get, list, post } from '@/lib/api';
import type {
  AuctionSale,
  AuctionSaleLine,
  Cheque,
  ChequeStatus,
  Container,
  ContainerItem,
  Customer,
  DashboardSummary,
  GatePass,
  Paginated,
  User,
} from '@/lib/types';

type Tab = 'dashboard' | 'customers' | 'containers' | 'items' | 'sales' | 'gate-passes' | 'cheques' | 'balances';

const tabs: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={18} /> },
  { id: 'customers', label: 'Customers', icon: <Users size={18} /> },
  { id: 'containers', label: 'Containers', icon: <ContainerIcon size={18} /> },
  { id: 'items', label: 'Inventory', icon: <Boxes size={18} /> },
  { id: 'sales', label: 'Auction Sales', icon: <Gavel size={18} /> },
  { id: 'gate-passes', label: 'Gate Passes', icon: <FileCheck2 size={18} /> },
  { id: 'cheques', label: 'Cheques', icon: <WalletCards size={18} /> },
  { id: 'balances', label: 'Balances', icon: <Banknote size={18} /> },
];

const emptyPage = <T,>(): Paginated<T> => ({ count: 0, next: null, previous: null, results: [] });

function settledValue<T>(result: PromiseSettledResult<T>, fallback: T): T {
  return result.status === 'fulfilled' ? result.value : fallback;
}

function money(value: string | number | null | undefined) {
  const amount = Number(value ?? 0);
  return new Intl.NumberFormat('en-PK', { style: 'currency', currency: 'PKR', maximumFractionDigits: 0 }).format(amount);
}

function statusClass(status: string) {
  if (['available', 'cleared', 'verified', 'released'].includes(status.toLowerCase())) return 'badge good';
  if (['sold', 'issued', 'ready_for_auction'].includes(status.toLowerCase())) return 'badge warn';
  if (['bounced', 'cancelled', 'void'].includes(status.toLowerCase())) return 'badge bad';
  return 'badge';
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [isAuthenticated, setAuthenticated] = useState(false);
  const [authError, setAuthError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [containers, setContainers] = useState<Container[]>([]);
  const [items, setItems] = useState<ContainerItem[]>([]);
  const [sales, setSales] = useState<AuctionSale[]>([]);
  const [soldPendingGatePass, setSoldPendingGatePass] = useState<AuctionSaleLine[]>([]);
  const [gatePasses, setGatePasses] = useState<GatePass[]>([]);
  const [cheques, setCheques] = useState<Cheque[]>([]);
  const [chequeStatuses, setChequeStatuses] = useState<ChequeStatus[]>([]);
  const [message, setMessage] = useState('');

  const availableItems = useMemo(() => items.filter((item) => item.status === 'available'), [items]);

  async function refreshData() {
    setLoading(true);
    setMessage('');
    try {
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
      ]);
      setSummary(settledValue(summaryData, null));
      setCustomers(settledValue(customerData, emptyPage<Customer>()).results);
      setContainers(settledValue(containerData, emptyPage<Container>()).results);
      setItems(settledValue(itemData, emptyPage<ContainerItem>()).results);
      setSales(settledValue(salesData, emptyPage<AuctionSale>()).results);
      setSoldPendingGatePass(settledValue(pendingGatePassData, emptyPage<AuctionSaleLine>()).results);
      setGatePasses(settledValue(gatePassData, emptyPage<GatePass>()).results);
      setCheques(settledValue(chequeData, emptyPage<Cheque>()).results);
      setChequeStatuses(settledValue(statusData, emptyPage<ChequeStatus>()).results);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to load data.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    async function boot() {
      try {
        await get('/auth/csrf/');
        const user = await get<User>('/auth/me/');
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
      await post('/auth/login/', {
        username: form.get('username'),
        password: form.get('password'),
      });
      const user = await get<User>('/auth/me/');
      setCurrentUser(user);
      setAuthenticated(true);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Login failed.');
    }
  }

  async function submitJson(
    event: FormEvent<HTMLFormElement>,
    path: string,
    transform?: (payload: Record<string, FormDataEntryValue>, form: HTMLFormElement) => unknown,
  ) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    await post(path, transform ? transform(payload, form) : payload);
    form.reset();
    setRefreshKey((key) => key + 1);
  }

  async function submitDynamic(
    event: FormEvent<HTMLFormElement>,
    pathBuilder: (payload: Record<string, FormDataEntryValue>) => string,
    transform?: (payload: Record<string, FormDataEntryValue>, form: HTMLFormElement) => unknown,
  ) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    await post(pathBuilder(payload), transform ? transform(payload, form) : payload);
    form.reset();
    setRefreshKey((key) => key + 1);
  }

  if (!isAuthenticated) {
    return (
      <main className="login-screen">
        <section className="login-card">
          <div className="brand">
            <span className="brand-mark">D7</span>
            <div>
              <h1>Digi7 ZSP</h1>
              <p className="muted">Auction operations and gate control</p>
            </div>
          </div>
          <form onSubmit={handleLogin} className="grid">
            <div className="field">
              <label htmlFor="username">Username</label>
              <input id="username" name="username" autoComplete="username" required />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input id="password" name="password" type="password" autoComplete="current-password" required />
            </div>
            {authError ? <div className="alert">{authError}</div> : null}
            <button className="btn primary" type="submit"><LogIn size={18} /> Sign in</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">D7</span>
          <div>
            <strong>Digi7</strong>
            <div className="muted">{currentUser?.full_name ?? 'ZSP operations'}</div>
          </div>
        </div>
        <nav className="nav">
          {tabs.map((tab) => (
            <button key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => setActiveTab(tab.id)}>
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <section className="main">
        <header className="topbar">
          <div>
            <p className="eyebrow">Spare parts auction management</p>
            <h1>{tabs.find((tab) => tab.id === activeTab)?.label}</h1>
            <p className="muted">Containers, sold lots, gate clearance, cheques, and real customer balances.</p>
          </div>
          <button className="btn" onClick={() => setRefreshKey((key) => key + 1)}>
            <RefreshCw size={18} /> Refresh
          </button>
        </header>

        {message ? <div className="alert">{message}</div> : null}
        {loading ? <div className="empty-state">Loading operational data...</div> : null}
        {!loading && activeTab === 'dashboard' ? <Dashboard summary={summary} soldPendingGatePass={soldPendingGatePass} /> : null}
        {!loading && activeTab === 'customers' ? <Customers customers={customers} onSubmit={submitJson} /> : null}
        {!loading && activeTab === 'containers' ? <Containers containers={containers} onSubmit={submitJson} /> : null}
        {!loading && activeTab === 'items' ? <Items containers={containers} items={items} onSubmit={submitJson} /> : null}
        {!loading && activeTab === 'sales' ? <Sales customers={customers} availableItems={availableItems} sales={sales} onSubmit={submitJson} /> : null}
        {!loading && activeTab === 'gate-passes' ? <GatePasses gatePasses={gatePasses} soldPendingGatePass={soldPendingGatePass} onSubmit={submitJson} onDynamicSubmit={submitDynamic} /> : null}
        {!loading && activeTab === 'cheques' ? <Cheques customers={customers} cheques={cheques} statuses={chequeStatuses} onSubmit={submitJson} onDynamicSubmit={submitDynamic} /> : null}
        {!loading && activeTab === 'balances' ? <Balances customers={customers} /> : null}
      </section>
    </main>
  );
}

function Customers({ customers, onSubmit }: { customers: Customer[]; onSubmit: any }) {
  return (
    <div className="split">
      <section className="panel"><h2>Customer directory</h2><DataTable headers={['Name', 'Type', 'Phone', 'Email', 'Balance', 'Status']} rows={customers.map((customer) => [customer.name, customer.customer_type, customer.phone || '-', customer.email || '-', money(customer.balance), customer.is_active ? <span className="badge good">Active</span> : <span className="badge bad">Inactive</span>])} /></section>
      <form className="form-panel" onSubmit={(event) => onSubmit(event, '/operations/customers/')}><h2>Add customer</h2><Field name="name" label="Customer name" required /><Select name="customer_type" label="Customer type" options={[['individual', 'Individual'], ['business', 'Business']]} required /><Field name="phone" label="Phone" /><Field name="email" label="Email" type="email" /><Field name="cnic_or_tax_id" label="CNIC / tax ID" /><Field name="address" label="Address" textarea /><button className="btn primary" type="submit"><Plus size={18} /> Save customer</button></form>
    </div>
  );
}

function Dashboard({ summary, soldPendingGatePass }: { summary: DashboardSummary | null; soldPendingGatePass: AuctionSaleLine[] }) {
  return (
    <div className="grid">
      <div className="grid grid-4">
        <Metric label="Containers" value={summary?.containers ?? 0} />
        <Metric label="Inventory items" value={summary?.items.total ?? 0} />
        <Metric label="Auction sales" value={summary?.auction_sales ?? 0} />
        <Metric label="Customer receivable" value={money(summary?.customer_receivable ?? 0)} />
      </div>
      <section className="panel">
        <h2>Gate-pass exposure</h2>
        <div className="grid grid-3">
          <Metric label="Sold, not issued" value={soldPendingGatePass.length} tone="warning" />
          <Metric label="Issued" value={summary?.gate_passes.issued ?? 0} />
          <Metric label="Verified" value={summary?.gate_passes.verified ?? 0} tone="success" />
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, tone = '' }: { label: string; value: string | number; tone?: string }) {
  return <div className={`metric-card ${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}

function Containers({ containers, onSubmit }: { containers: Container[]; onSubmit: any }) {
  return (
    <div className="split">
      <section className="panel"><h2>Container registry</h2><DataTable headers={['Reference', 'Origin', 'Supplier', 'Arrival', 'Status', 'Items']} rows={containers.map((c) => [c.reference, c.origin_country || '-', c.supplier_name || '-', c.arrival_date || '-', <span key="status" className={statusClass(c.status)}>{c.status}</span>, c.item_count])} /></section>
      <form className="form-panel" onSubmit={(event) => onSubmit(event, '/operations/containers/')}><h2>Add container</h2><Field name="reference" label="Container reference" required /><Field name="origin_country" label="Origin country" /><Field name="supplier_name" label="Supplier" /><Field name="arrival_date" label="Arrival date" type="date" /><Field name="manifest_notes" label="Manifest notes" textarea /><button className="btn primary" type="submit"><Plus size={18} /> Save container</button></form>
    </div>
  );
}

function Items({ containers, items, onSubmit }: { containers: Container[]; items: ContainerItem[]; onSubmit: any }) {
  return (
    <div className="split">
      <section className="panel"><h2>Container inventory</h2><DataTable headers={['Lot', 'Part', 'Part no.', 'Container', 'Category', 'Qty', 'Status']} rows={items.map((item) => [item.lot_number, item.part_name, item.part_number || '-', item.container_reference, item.category || '-', `${item.quantity} ${item.unit}`, <span key="status" className={statusClass(item.status)}>{item.status}</span>])} /></section>
      <form className="form-panel" onSubmit={(event) => onSubmit(event, '/operations/items/', (payload: any) => ({ ...payload, quantity: Number(payload.quantity || 1), reserve_price: payload.reserve_price || null }))}><h2>Add spare part</h2><Select name="container" label="Container" options={containers.map((c) => [c.id, c.reference])} required /><Field name="lot_number" label="Lot number" required /><Field name="part_name" label="Part name" required /><Field name="part_number" label="Part number" /><Field name="category" label="Category" /><Field name="quantity" label="Quantity" type="number" defaultValue="1" /><Field name="reserve_price" label="Reserve price" type="number" /><button className="btn primary" type="submit"><Plus size={18} /> Save item</button></form>
    </div>
  );
}

function Sales({ customers, availableItems, sales, onSubmit }: { customers: Customer[]; availableItems: ContainerItem[]; sales: AuctionSale[]; onSubmit: any }) {
  return (
    <div className="split">
      <section className="panel"><h2>Auction transactions</h2><DataTable headers={['Sale no.', 'Date', 'Customer', 'Payment', 'Total', 'Items']} rows={sales.map((sale) => [sale.sale_number, sale.sale_date, sale.customer_name || 'Cash customer', sale.payment_type, money(sale.total_amount), sale.lines.length])} /></section>
      <form className="form-panel" onSubmit={(event) => onSubmit(event, '/operations/auction-sales/', (payload: any) => ({ sale_date: payload.sale_date, customer: payload.customer || null, payment_type: payload.payment_type, notes: payload.notes || '', lines: [{ item: payload.item, sold_price: payload.sold_price, notes: payload.line_notes || '' }] }))}><h2>Record sold lot</h2><Field name="sale_date" label="Sale date" type="date" required /><Select name="payment_type" label="Payment type" options={[['cash', 'Cash'], ['credit', 'Credit'], ['cheque', 'Cheque'], ['mixed', 'Mixed']]} required /><Select name="customer" label="Customer" options={customers.map((c) => [c.id, c.name])} /><Select name="item" label="Available item" options={availableItems.map((item) => [item.id, `${item.container_reference} / ${item.lot_number} - ${item.part_name}`])} required /><Field name="sold_price" label="Sold price" type="number" required /><Field name="notes" label="Notes" textarea /><button className="btn primary" type="submit"><Gavel size={18} /> Record sale</button></form>
    </div>
  );
}

function GatePasses({ gatePasses, soldPendingGatePass, onSubmit, onDynamicSubmit }: { gatePasses: GatePass[]; soldPendingGatePass: AuctionSaleLine[]; onSubmit: any; onDynamicSubmit: any }) {
  const issuedPasses = gatePasses.filter((gatePass) => gatePass.status === 'issued');

  return (
    <div className="split">
      <section className="panel"><h2>Gate passes</h2><DataTable headers={['Gate pass', 'Issued to', 'Vehicle', 'Status', 'Issued at', 'Items']} rows={gatePasses.map((gp) => [gp.gate_pass_number, gp.issued_to_name, gp.vehicle_number || '-', <span key="status" className={statusClass(gp.status)}>{gp.status}</span>, new Date(gp.issued_at).toLocaleString(), gp.lines.length])} /></section>
      <div className="grid">
        <form className="form-panel" onSubmit={(event) => onSubmit(event, '/operations/gate-passes/', (_payload: Record<string, FormDataEntryValue>, form: HTMLFormElement) => {
          const formData = new FormData(form);
          return {
            issued_to_name: formData.get('issued_to_name'),
            issued_to_phone: formData.get('issued_to_phone') || '',
            vehicle_number: formData.get('vehicle_number') || '',
            driver_name: formData.get('driver_name') || '',
            notes: formData.get('notes') || '',
            sale_line_ids: formData.getAll('sale_line_ids'),
          };
        })}><h2>Issue gate pass</h2><Select name="sale_line_ids" label="Sold items pending gate pass" options={soldPendingGatePass.map((line) => [line.id, `${line.item.container_reference} / ${line.item.lot_number} - ${line.item.part_name} (${money(line.sold_price)})`])} required multiple /><Field name="issued_to_name" label="Issued to" required /><Field name="issued_to_phone" label="Phone" /><Field name="vehicle_number" label="Vehicle number" /><Field name="driver_name" label="Driver name" /><Field name="notes" label="Notes" textarea /><button className="btn primary" type="submit"><ClipboardCheck size={18} /> Issue pass</button></form>
        <form className="form-panel" onSubmit={(event) => onDynamicSubmit(event, (payload: Record<string, FormDataEntryValue>) => `/operations/gate-passes/${payload.gate_pass}/verify/`, () => ({}))}><h2>Verify at gate</h2><Select name="gate_pass" label="Issued gate pass" options={issuedPasses.map((pass) => [pass.id, `${pass.gate_pass_number} - ${pass.issued_to_name}`])} required /><button className="btn primary" type="submit"><ShieldCheck size={18} /> Verify release</button></form>
      </div>
    </div>
  );
}

function Cheques({ customers, cheques, statuses, onSubmit, onDynamicSubmit }: { customers: Customer[]; cheques: Cheque[]; statuses: ChequeStatus[]; onSubmit: any; onDynamicSubmit: any }) {
  return (
    <div className="split">
      <section className="panel"><h2>Cheque register</h2><DataTable headers={['Cheque', 'Customer', 'Bank', 'Amount', 'Date', 'Expiry', 'Status']} rows={cheques.map((cheque) => [cheque.cheque_number, cheque.customer_name, cheque.bank_name, money(cheque.amount), cheque.cheque_date, cheque.expiry_date, <span key="status" className={statusClass(cheque.status_name)}>{cheque.status_name}</span>])} /></section>
      <div className="grid">
        <form className="form-panel" onSubmit={(event) => onSubmit(event, '/finance/cheques/')}><h2>Add cheque</h2><Field name="cheque_number" label="Cheque number" required /><Select name="customer" label="Customer" options={customers.map((c) => [c.id, c.name])} required /><Field name="bank_name" label="Bank" required /><Field name="amount" label="Amount" type="number" required /><Field name="cheque_date" label="Cheque date" type="date" required /><Field name="expiry_date" label="Expiry date" type="date" required /><Field name="received_date" label="Received date" type="date" required /><Select name="status" label="Status" options={statuses.map((s) => [s.id, s.name])} required /><button className="btn primary" type="submit"><Plus size={18} /> Save cheque</button></form>
        <form className="form-panel" onSubmit={(event) => onDynamicSubmit(event, (payload: any) => `/finance/cheques/${payload.cheque}/change-status/`, (payload: any) => ({ status: payload.status, notes: payload.notes || '' }))}><h2>Change cheque status</h2><Select name="cheque" label="Cheque" options={cheques.map((cheque) => [cheque.id, `${cheque.cheque_number} - ${cheque.customer_name}`])} required /><Select name="status" label="New status" options={statuses.map((s) => [s.id, s.name])} required /><Field name="notes" label="Notes" textarea /><button className="btn primary" type="submit"><BadgeCheck size={18} /> Update status</button></form>
        <form className="form-panel" onSubmit={(event) => onSubmit(event, '/finance/cheque-statuses/')}><h2>Add custom status</h2><Field name="name" label="Status name" required /><Select name="balance_effect" label="Balance effect" options={[['none', 'No automatic balance effect'], ['settles_balance', 'Settles customer balance'], ['reverses_settlement', 'Reverses settlement']]} required /><button className="btn" type="submit"><Plus size={18} /> Save status</button></form>
      </div>
    </div>
  );
}

function Balances({ customers }: { customers: Customer[] }) {
  return (
    <section className="panel"><h2>Customer balances</h2><DataTable headers={['Customer', 'Phone', 'Type', 'Balance']} rows={customers.map((customer) => [customer.name, customer.phone || '-', customer.customer_type, money(customer.balance)])} /></section>
  );
}

function Field({ name, label, type = 'text', required = false, textarea = false, defaultValue = '' }: { name: string; label: string; type?: string; required?: boolean; textarea?: boolean; defaultValue?: string }) {
  return <div className="field"><label htmlFor={name}>{label}</label>{textarea ? <textarea id={name} name={name} required={required} defaultValue={defaultValue} /> : <input id={name} name={name} type={type} required={required} defaultValue={defaultValue} />}</div>;
}

function Select({ name, label, options, required = false, multiple = false }: { name: string; label: string; options: [string, string][]; required?: boolean; multiple?: boolean }) {
  return <div className="field"><label htmlFor={name}>{label}</label><select id={name} name={name} required={required} multiple={multiple}>{multiple ? null : <option value="">Select...</option>}{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></div>;
}

function DataTable({ headers, rows }: { headers: string[]; rows: React.ReactNode[][] }) {
  if (rows.length === 0) return <div className="empty-state"><Search size={22} /> No records yet.</div>;
  return <div className="table-wrap"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
}
