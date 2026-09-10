'use client';

import {
  BadgeCheck,
  Banknote,
  Boxes,
  ChevronDown,
  ChevronRight,
  Container as ContainerIcon,
  FileDown,
  Gavel,
  LayoutDashboard,
  LogIn,
  LogOut,
  Pencil,
  Plus,
  Printer,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
  WalletCards,
  X,
} from 'lucide-react';
import Image from 'next/image';
import PhoneInput from 'react-phone-number-input';
import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { destroy, get, list, patch, post } from '@/lib/api';
import type {
  AuctionSale,
  Cheque,
  ChequeStatus,
  Container,
  ContainerItem,
  CreditReport,
  Customer,
  CustomerLedgerEntry,
  DashboardSummary,
  DropdownOption,
  GatePass,
  InventoryBatch,
  ManagedUser,
  Paginated,
  PartInventory,
  User,
  UUID,
} from '@/lib/types';

type Tab = 'dashboard' | 'customers' | 'containers' | 'sales' | 'cheques' | 'settings' | 'users';
type AccessLevel = 'none' | 'view' | 'full';
type ModalState =
  | { type: 'customer'; customer?: Customer }
  | { type: 'container'; container?: Container }
  | { type: 'item'; item?: ContainerItem; containerId?: UUID }
  | { type: 'part'; part?: PartInventory }
  | { type: 'subparts'; parentItem: ContainerItem }
  | { type: 'sale'; sale?: AuctionSale }
  | { type: 'cheque'; cheque?: Cheque }
  | { type: 'cheque-status' }
  | { type: 'dropdown-option'; group?: DropdownOption['group'] }
  | { type: 'user'; user?: ManagedUser }
  | null;

type SaleLineDraft = {
  key: string;
  id?: UUID;
  inventory_batch: string;
  quantity: number;
  sold_price: string;
  notes: string;
};

type BatchWithPart = InventoryBatch & { item_detail: PartInventory };
type PartSourceDraft = {
  key: string;
  container: string;
  quantity: number;
  raw_unit_cost: string;
  description: string;
};
type SubpartDraft = {
  key: string;
  part_name: string;
  part_number: string;
  category: string;
  quantity: number;
  unit: string;
  raw_unit_cost: string;
  description: string;
};
type ComboOption = {
  value: string;
  label: string;
  meta?: string;
  featured?: boolean;
};

type SaveHandler = (path: string, payload: unknown, method?: 'post' | 'patch') => Promise<void>;

const tabs: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={18} /> },
  { id: 'customers', label: 'Customers & Balances', icon: <Users size={18} /> },
  { id: 'containers', label: 'Containers & Inventory', icon: <ContainerIcon size={18} /> },
  { id: 'sales', label: 'Auction Sales', icon: <Gavel size={18} /> },
  { id: 'cheques', label: 'Cheques', icon: <WalletCards size={18} /> },
  { id: 'settings', label: 'Dropdown Settings', icon: <Boxes size={18} /> },
  { id: 'users', label: 'Users', icon: <ShieldCheck size={18} /> },
];

const tabOptions: { id: Tab; label: string }[] = tabs.map((tab) => ({ id: tab.id, label: tab.label }));
const tabRoutes: Record<Tab, string> = {
  dashboard: '/dashboard',
  customers: '/customers',
  containers: '/containers',
  sales: '/sales',
  cheques: '/cheques',
  settings: '/settings',
  users: '/users',
};
const routeTabs = Object.entries(tabRoutes).reduce<Record<string, Tab>>((routes, [tab, path]) => {
  routes[path] = tab as Tab;
  return routes;
}, {});
const accessOptions: { id: AccessLevel; label: string }[] = [
  { id: 'none', label: 'No access' },
  { id: 'view', label: 'View only' },
  { id: 'full', label: 'Full use' },
];

const emptyPage = <T,>(): Paginated<T> => ({ count: 0, next: null, previous: null, results: [] });
const valueOf = <T,>(result: PromiseSettledResult<T>, fallback: T): T => result.status === 'fulfilled' ? result.value : fallback;
const containerStatusOptions: [string, string][] = [
  ['container_bought', 'Container Bought'],
  ['godown_loading', 'Godown Loading'],
  ['ship_loading', 'Ship Loading'],
  ['port_loading', 'Port Loading'],
  ['port_open', 'Port Open'],
  ['port_close', 'Port Close'],
  ['edan_gate', 'EDAN Gate'],
  ['ready_for_auction', 'Ready For Auction'],
  ['closed', 'Closed'],
];

function money(value: string | number | null | undefined) {
  const amount = Number(value ?? 0);
  return new Intl.NumberFormat('en-PK', { style: 'currency', currency: 'PKR', maximumFractionDigits: 0 }).format(amount);
}

function shortDate(value: string | null | undefined) {
  if (!value) return '-';
  return new Intl.DateTimeFormat('en-PK', { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`));
}

function statusClass(status: string) {
  const normalized = status.toLowerCase().replaceAll(' ', '_');
  if (['available', 'cleared', 'verified', 'released', 'active', 'printed', 'settled'].includes(normalized)) return 'badge good';
  if (['sold', 'issued', 'ready_for_auction', 'pending', 'not_printed', 'settled_by_cash'].includes(normalized)) return 'badge warn';
  if (['bounced', 'cancelled', 'void', 'inactive', 'damaged'].includes(normalized)) return 'badge bad';
  return 'badge';
}

function statusLabel(status: string) {
  return status
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function accessLabel(level: AccessLevel | string | undefined) {
  if (level === 'full') return 'Full use';
  if (level === 'view') return 'View only';
  return 'No access';
}

function accessClass(level: AccessLevel | string | undefined) {
  if (level === 'full') return 'chip access-full';
  if (level === 'view') return 'chip access-view';
  return 'chip access-none';
}

function optionLabels(options: DropdownOption[], group: DropdownOption['group']) {
  return options.filter((option) => option.group === group && option.is_active).map((option) => option.label);
}

function pakistanLocalDate() {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Karachi',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function partIdentity(name: string, number: string, category: string, unit: string) {
  return [name.trim().toLowerCase(), number.trim().toLowerCase(), category.trim().toLowerCase(), unit.trim().toLowerCase()].join('|');
}

function itemSearchText(item: ContainerItem) {
  return `${item.part_name} ${item.part_number} ${item.category} ${item.unit} ${item.description}`.toLowerCase();
}

function tabFromPath(pathname: string): Tab {
  return routeTabs[pathname.replace(/\/$/, '') || '/dashboard'] ?? 'dashboard';
}

function chequeRowClass(cheque: Cheque) {
  const status = cheque.status_name.toLowerCase();
  if (['cleared', 'settled', 'settled by cash'].includes(status)) return '';
  const today = pakistanLocalDate();
  if (cheque.expiry_date < today) return 'row-danger';
  if (cheque.cheque_date <= today && cheque.expiry_date >= today) return 'row-success';
  return '';
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>(() => typeof window === 'undefined' ? 'dashboard' : tabFromPath(window.location.pathname));
  const [isAuthenticated, setAuthenticated] = useState(false);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState('');
  const [booting, setBooting] = useState(true);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<ModalState>(null);
  const [saleCustomerOverlayOpen, setSaleCustomerOverlayOpen] = useState(false);
  const [newSaleCustomer, setNewSaleCustomer] = useState<Customer | null>(null);
  const [expandedContainers, setExpandedContainers] = useState<Set<UUID>>(new Set());
  const [expandedCustomers, setExpandedCustomers] = useState<Set<UUID>>(new Set());
  const [expandedParts, setExpandedParts] = useState<Set<UUID>>(new Set());
  const [inventoryPane, setInventoryPane] = useState<'parts' | 'containers'>('parts');
  const [message, setMessage] = useState('');
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingPath, setDeletingPath] = useState('');
  const loadToken = useRef(0);

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [containers, setContainers] = useState<Container[]>([]);
  const [items, setItems] = useState<ContainerItem[]>([]);
  const [parts, setParts] = useState<PartInventory[]>([]);
  const [sales, setSales] = useState<AuctionSale[]>([]);
  const [cheques, setCheques] = useState<Cheque[]>([]);
  const [chequeStatuses, setChequeStatuses] = useState<ChequeStatus[]>([]);
  const [ledgerEntries, setLedgerEntries] = useState<CustomerLedgerEntry[]>([]);
  const [creditReport, setCreditReport] = useState<CreditReport | null>(null);
  const [dropdownOptions, setDropdownOptions] = useState<DropdownOption[]>([]);
  const [managedUsers, setManagedUsers] = useState<ManagedUser[]>([]);

  const availableBatches = useMemo<BatchWithPart[]>(() => parts.flatMap((part) => (part.batches ?? []).map((batch) => ({ ...batch, item_detail: part }))).filter((batch) => batch.available_quantity > 0), [parts]);
  const visibleTabs = useMemo(() => {
    const allowed = new Set(currentUser?.access_tabs ?? []);
    return tabs.filter((tab) => allowed.has(tab.id));
  }, [currentUser]);
  const canWrite = (tab: Tab) => currentUser?.tab_permissions?.[tab] === 'full';
  const itemsByContainer = useMemo(() => {
    const grouped = new Map<UUID, ContainerItem[]>();
    for (const item of items) {
      const existing = grouped.get(item.container);
      existing ? existing.push(item) : grouped.set(item.container, [item]);
    }
    return grouped;
  }, [items]);
  const ledgerByCustomer = useMemo(() => {
    const grouped = new Map<UUID, CustomerLedgerEntry[]>();
    for (const entry of ledgerEntries) {
      const existing = grouped.get(entry.customer);
      existing ? existing.push(entry) : grouped.set(entry.customer, [entry]);
    }
    return grouped;
  }, [ledgerEntries]);
  const currentTitle = tabs.find((tab) => tab.id === activeTab)?.label ?? 'Dashboard';

  async function loadTabData(tab: Tab) {
    const token = loadToken.current + 1;
    loadToken.current = token;
    setLoading(true);
    setMessage('');
    try {
      if (tab === 'dashboard') {
        const summaryData = await get<DashboardSummary>('/finance/dashboard-summary/');
        if (loadToken.current === token) setSummary(summaryData);
      }

      if (tab === 'customers') {
        const [customerData, ledgerData, reportData] = await Promise.allSettled([
          list<Customer>('/operations/customers/?page_size=200'),
          list<CustomerLedgerEntry>('/finance/ledger/?page_size=200'),
          get<CreditReport>('/finance/credit-report/'),
        ]);
        if (loadToken.current === token) {
          setCustomers(valueOf(customerData, emptyPage<Customer>()).results);
          setLedgerEntries(valueOf(ledgerData, emptyPage<CustomerLedgerEntry>()).results);
          setCreditReport(valueOf(reportData, null));
        }
      }

      if (tab === 'containers') {
        const [containerData, itemData, partData, optionData] = await Promise.allSettled([
          list<Container>('/operations/containers/?page_size=200'),
          list<ContainerItem>('/operations/items/?page_size=200'),
          list<PartInventory>('/operations/parts/?page_size=200'),
          list<DropdownOption>('/catalog/dropdown-options/?page_size=200'),
        ]);
        if (loadToken.current === token) {
          setContainers(valueOf(containerData, emptyPage<Container>()).results);
          setItems(valueOf(itemData, emptyPage<ContainerItem>()).results);
          setParts(valueOf(partData, emptyPage<PartInventory>()).results);
          setDropdownOptions(valueOf(optionData, emptyPage<DropdownOption>()).results);
        }
      }

      if (tab === 'sales') {
        const [salesData, customerData, partData, optionData] = await Promise.allSettled([
          list<AuctionSale>('/operations/auction-sales/?page_size=100'),
          list<Customer>('/operations/customers/?page_size=200'),
          list<PartInventory>('/operations/parts/?page_size=200'),
          list<DropdownOption>('/catalog/dropdown-options/?page_size=200'),
        ]);
        if (loadToken.current === token) {
          setSales(valueOf(salesData, emptyPage<AuctionSale>()).results);
          setCustomers(valueOf(customerData, emptyPage<Customer>()).results);
          setParts(valueOf(partData, emptyPage<PartInventory>()).results);
          setDropdownOptions(valueOf(optionData, emptyPage<DropdownOption>()).results);
        }
      }

      if (tab === 'cheques') {
        const [chequeData, customerData, statusData, optionData] = await Promise.allSettled([
          list<Cheque>('/finance/cheques/?page_size=100'),
          list<Customer>('/operations/customers/?page_size=200'),
          list<ChequeStatus>('/finance/cheque-statuses/?page_size=100'),
          list<DropdownOption>('/catalog/dropdown-options/?page_size=200'),
        ]);
        if (loadToken.current === token) {
          setCheques(valueOf(chequeData, emptyPage<Cheque>()).results);
          setCustomers(valueOf(customerData, emptyPage<Customer>()).results);
          setChequeStatuses(valueOf(statusData, emptyPage<ChequeStatus>()).results);
          setDropdownOptions(valueOf(optionData, emptyPage<DropdownOption>()).results);
        }
      }

      if (tab === 'settings') {
        const [statusData, optionData] = await Promise.allSettled([
          list<ChequeStatus>('/finance/cheque-statuses/?page_size=100'),
          list<DropdownOption>('/catalog/dropdown-options/?page_size=200'),
        ]);
        if (loadToken.current === token) {
          setChequeStatuses(valueOf(statusData, emptyPage<ChequeStatus>()).results);
          setDropdownOptions(valueOf(optionData, emptyPage<DropdownOption>()).results);
        }
      }

      if (tab === 'users') {
        const userData = await list<ManagedUser>('/auth/users/?page_size=200');
        if (loadToken.current === token) setManagedUsers(userData.results);
      }
    } catch (error) {
      if (loadToken.current === token) {
        setMessage(error instanceof Error ? error.message : 'Unable to load data.');
      }
    } finally {
      if (loadToken.current === token) setLoading(false);
    }
  }

  useEffect(() => {
    function handlePopState() {
      setActiveTab(tabFromPath(window.location.pathname));
    }
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    async function boot() {
      try {
        await get('/auth/csrf/');
        const user = await get<User & { authenticated?: boolean }>('/auth/me/');
        if (user.authenticated === false) {
          setAuthenticated(false);
          if (window.location.pathname !== '/login') window.history.replaceState(null, '', '/login');
          setBooting(false);
          return;
        }
        setCurrentUser(user);
        setLoading(true);
        setAuthenticated(true);
        if (window.location.pathname === '/' || window.location.pathname === '/login') {
          window.history.replaceState(null, '', tabRoutes[tabFromPath(window.location.pathname)]);
        }
      } catch {
        setAuthenticated(false);
        if (window.location.pathname !== '/login') window.history.replaceState(null, '', '/login');
      } finally {
        setBooting(false);
      }
    }
    boot();
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    const handle = window.setTimeout(() => {
      if (visibleTabs.length > 0 && !visibleTabs.some((tab) => tab.id === activeTab)) {
        setActiveTab(visibleTabs[0].id);
        return;
      }
      if (visibleTabs.length > 0) void loadTabData(activeTab);
    }, 0);
    return () => window.clearTimeout(handle);
  }, [activeTab, isAuthenticated, visibleTabs]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (authSubmitting) return;
    setAuthError('');
    setAuthSubmitting(true);
    const form = new FormData(event.currentTarget);
    try {
      await get('/auth/csrf/');
      await post('/auth/login/', { username: form.get('username'), password: form.get('password') });
      const user = await get<User>('/auth/me/');
      setCurrentUser(user);
      setLoading(true);
      setAuthenticated(true);
      const nextTab = tabFromPath(window.location.pathname);
      window.history.replaceState(null, '', tabRoutes[nextTab]);
      setActiveTab(nextTab);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Login failed.');
    } finally {
      setAuthSubmitting(false);
    }
  }

  async function handleLogout() {
    if (signingOut) return;
    setSigningOut(true);
    setMessage('');
    try {
      await post('/auth/logout/', {});
      setAuthenticated(false);
      setCurrentUser(null);
      setActiveTab('dashboard');
      window.history.replaceState(null, '', '/login');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to sign out.');
    } finally {
      setSigningOut(false);
    }
  }

  async function save(path: string, payload: unknown, method: 'post' | 'patch' = 'post') {
    if (saving) return;
    setMessage('');
    setSaving(true);
    try {
      method === 'patch' ? await patch(path, payload) : await post(path, payload);
      setModal(null);
      await loadTabData(activeTab);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to save record.');
    } finally {
      setSaving(false);
    }
  }

  async function saveSaleCustomer(path: string, payload: unknown, method: 'post' | 'patch' = 'post') {
    if (saving) return;
    setMessage('');
    setSaving(true);
    try {
      const customer = method === 'patch'
        ? await patch<Customer>(path, payload)
        : await post<Customer>(path, payload);
      setCustomers((previous) => {
        const next = previous.filter((existing) => existing.id !== customer.id);
        next.push(customer);
        return next.sort((a, b) => a.name.localeCompare(b.name));
      });
      setNewSaleCustomer(customer);
      setSaleCustomerOverlayOpen(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to save customer.');
    } finally {
      setSaving(false);
    }
  }

  async function remove(path: string) {
    if (!window.confirm('Delete this record? This cannot be undone.')) return;
    setMessage('');
    setDeletingPath(path);
    try {
      await destroy(path);
      await loadTabData(activeTab);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to delete record.');
    } finally {
      setDeletingPath('');
    }
  }

  async function quickPatch(path: string, payload: unknown) {
    setMessage('');
    try {
      await patch(path, payload);
      await loadTabData(activeTab);
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

  function navigateTab(tab: Tab) {
    setActiveTab(tab);
    if (window.location.pathname !== tabRoutes[tab]) {
      window.history.pushState(null, '', tabRoutes[tab]);
    }
  }

  async function downloadCreditReport(format: 'csv' | 'pdf') {
    setMessage('');
    try {
      const response = await fetch(`/api/finance/credit-report/?export=${format}`, {
        credentials: 'include',
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(`Unable to download ${format.toUpperCase()} report.`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `zsp-credit-aging-report.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to download report.');
    }
  }

  async function markChequeStatus(cheque: Cheque, statusId: UUID) {
    await post(`/finance/cheques/${cheque.id}/change-status/`, { status: statusId, notes: '' });
    await loadTabData(activeTab);
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
    await loadTabData(activeTab);
  }

  async function printSaleGatePass(sale: AuctionSale) {
    if (!sale.gate_pass) {
      setMessage('This sale does not have a gate pass yet.');
      return;
    }
    const gatePass = await get<GatePass>(`/operations/gate-passes/${sale.gate_pass.id}/`);
    await printGatePass(gatePass);
  }

  if (booting) {
    return (
      <main className="login-screen">
        <LoadingState label="Loading Digi7..." />
      </main>
    );
  }

  if (!isAuthenticated) {
    return (
      <main className="login-screen">
        <section className="login-card">
          <div className="login-brand">
            <Image src="/digi7-logo.png" alt="ZSP" width={96} height={96} priority />
            <div>
              <p className="eyebrow">ZSP spare-parts operations</p>
              <h1>Secure auction control</h1>
              <p className="muted">Containers, sold lots, gate passes, cheques, and customer balances in one controlled workflow.</p>
            </div>
          </div>
          <form onSubmit={handleLogin} className="login-form">
            <Field name="username" label="Username" autoComplete="username" required />
            <Field name="password" label="Password" type="password" autoComplete="current-password" required />
            {authError ? <div className="alert">{authError}</div> : null}
            <button className="btn primary wide" type="submit" disabled={authSubmitting}>{authSubmitting ? <ProcessingLoader /> : <LogIn size={18} />} {authSubmitting ? 'Signing in...' : 'Sign in'}</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <Image src="/digi7-logo.png" alt="ZSP" width={64} height={64} priority />
          <div><strong>ZSP Control</strong><span>{currentUser?.full_name ?? 'Operations'}</span></div>
        </div>
        <nav className="nav">
          {visibleTabs.map((tab) => <button key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => navigateTab(tab.id)}>{tab.icon}<span>{tab.label}</span></button>)}
        </nav>
        <button className="btn sidebar-signout" onClick={handleLogout} disabled={signingOut}>{signingOut ? <ProcessingLoader /> : <LogOut size={18} />} {signingOut ? 'Signing out...' : 'Sign out'}</button>
      </aside>
      <section className="main">
        <header className="topbar">
          <div><p className="eyebrow">Digi7 for ZSP spare-parts auctions</p><h1>{currentTitle}</h1><p className="muted">Fast operational entry with guarded inventory release and auditable receivables.</p></div>
          <button className="btn" onClick={() => loadTabData(activeTab)} disabled={loading}>{loading ? <ProcessingLoader /> : <RefreshCw size={18} />} Refresh</button>
        </header>
        {message ? <div className="alert">{message}</div> : null}
        {visibleTabs.length === 0 ? <div className="empty-state"><ShieldCheck size={22} /> No product tabs are enabled for this account.</div> : null}
        {loading ? <LoadingState label={`Loading ${currentTitle.toLowerCase()}...`} /> : null}
        {!loading && activeTab === 'dashboard' ? <Dashboard summary={summary} /> : null}
        {!loading && activeTab === 'customers' ? <CustomersPanel canWrite={canWrite('customers')} customers={customers} ledgerByCustomer={ledgerByCustomer} creditReport={creditReport} expanded={expandedCustomers} onToggle={(id) => toggleSet(setExpandedCustomers, id)} onAdd={() => setModal({ type: 'customer' })} onEdit={(customer) => setModal({ type: 'customer', customer })} onDelete={(customer) => remove(`/operations/customers/${customer.id}/`)} onStatus={(customer) => quickPatch(`/operations/customers/${customer.id}/`, { is_active: !customer.is_active })} onDownloadReport={downloadCreditReport} /> : null}
        {!loading && activeTab === 'containers' ? <ContainersPanel canWrite={canWrite('containers')} containers={containers} items={items} itemsByContainer={itemsByContainer} parts={parts} expandedContainers={expandedContainers} expandedParts={expandedParts} inventoryPane={inventoryPane} onInventoryPaneChange={setInventoryPane} onToggleContainer={(id) => toggleSet(setExpandedContainers, id)} onTogglePart={(id) => toggleSet(setExpandedParts, id)} onAdd={() => setModal({ type: 'container' })} onEdit={(container) => setModal({ type: 'container', container })} onDelete={(container) => remove(`/operations/containers/${container.id}/`)} onAddItem={(containerId) => setModal({ type: 'item', containerId })} onEditItem={(item) => setModal({ type: 'item', item })} onDeleteItem={(item) => remove(`/operations/items/${item.id}/`)} onAddSubparts={(item) => setModal({ type: 'subparts', parentItem: item })} onAddPart={() => setModal({ type: 'part' })} onEditPart={(part) => setModal({ type: 'part', part })} onDeletePart={(part) => remove(`/operations/parts/${part.id}/`)} /> : null}
        {!loading && activeTab === 'sales' ? <SalesPanel canWrite={canWrite('sales')} sales={sales} onAdd={() => { setNewSaleCustomer(null); setModal({ type: 'sale' }); }} onEdit={(sale) => { setNewSaleCustomer(null); setModal({ type: 'sale', sale }); }} onPrint={printSaleGatePass} /> : null}
        {!loading && activeTab === 'cheques' ? <ChequesPanel canWrite={canWrite('cheques')} cheques={cheques} statuses={chequeStatuses} onAdd={() => setModal({ type: 'cheque' })} onEdit={(cheque) => setModal({ type: 'cheque', cheque })} onStatus={markChequeStatus} onAddStatus={() => setModal({ type: 'cheque-status' })} /> : null}
        {!loading && activeTab === 'settings' ? <SettingsPanel canWrite={canWrite('settings')} options={dropdownOptions} chequeStatuses={chequeStatuses} onAdd={(group) => setModal({ type: 'dropdown-option', group })} onAddChequeStatus={() => setModal({ type: 'cheque-status' })} /> : null}
        {!loading && activeTab === 'users' ? <UsersPanel canWrite={canWrite('users')} users={managedUsers} currentUserId={currentUser?.id} deletingPath={deletingPath} onAdd={() => setModal({ type: 'user' })} onEdit={(user) => setModal({ type: 'user', user })} onDelete={(user) => remove(`/auth/users/${user.id}/`)} /> : null}
      </section>
      <ModalShell modal={modal} onClose={() => setModal(null)}>
        {modal?.type === 'customer' ? <CustomerForm customer={modal.customer} onSave={save} isSaving={saving} /> : null}
        {modal?.type === 'container' ? <ContainerForm container={modal.container} onSave={save} isSaving={saving} /> : null}
        {modal?.type === 'item' ? <ItemForm item={modal.item} containerId={modal.containerId} containers={containers} items={items} parts={parts} options={dropdownOptions} onSave={save} isSaving={saving} /> : null}
        {modal?.type === 'part' ? <PartForm part={modal.part} containers={containers} parts={parts} options={dropdownOptions} onSave={save} isSaving={saving} /> : null}
        {modal?.type === 'subparts' ? <SubpartForm parentItem={modal.parentItem} parts={parts} options={dropdownOptions} onSave={save} isSaving={saving} /> : null}
        {modal?.type === 'sale' ? <SaleForm sale={modal.sale} customers={customers} availableBatches={availableBatches} banks={optionLabels(dropdownOptions, 'bank')} onSave={save} isSaving={saving} selectedCustomer={newSaleCustomer} onAddCustomer={() => setSaleCustomerOverlayOpen(true)} /> : null}
        {modal?.type === 'cheque' ? <ChequeForm cheque={modal.cheque} customers={customers} statuses={chequeStatuses} banks={optionLabels(dropdownOptions, 'bank')} onSave={save} isSaving={saving} /> : null}
        {modal?.type === 'cheque-status' ? <ChequeStatusForm onSave={save} isSaving={saving} /> : null}
        {modal?.type === 'dropdown-option' ? <DropdownOptionForm group={modal.group} onSave={save} isSaving={saving} /> : null}
        {modal?.type === 'user' ? <UserForm user={modal.user} onSave={save} isSaving={saving} /> : null}
      </ModalShell>
      {saleCustomerOverlayOpen ? <ModalShell modal={{ type: 'customer' }} onClose={() => setSaleCustomerOverlayOpen(false)}><CustomerForm onSave={saveSaleCustomer} isSaving={saving} /></ModalShell> : null}
    </main>
  );
}

function Dashboard({ summary }: { summary: DashboardSummary | null }) {
  const pendingCheques = summary?.pending_in_date_cheques ?? [];
  const chequeStatuses = Object.entries(summary?.cheques_by_status ?? {});
  return (
    <div className="dashboard-grid">
      <Metric icon={<ContainerIcon size={22} />} label="Containers" value={summary?.containers ?? 0} />
      <Metric icon={<Boxes size={22} />} label="Inventory items" value={summary?.items.total ?? 0} />
      <Metric icon={<Gavel size={22} />} label="Auction sales" value={summary?.auction_sales ?? 0} />
      <Metric icon={<Banknote size={22} />} label="Receivable" value={money(summary?.customer_receivable ?? 0)} tone="cash" />
      <section className="panel span-2">
        <div className="section-head">
          <div>
            <h2>Creditors summary</h2>
            <p className="muted">Customers currently owing money to ZSP.</p>
          </div>
        </div>
        <div className="metric-row two">
          <Metric compact label="Creditors" value={summary?.creditors.count ?? 0} tone="warning" />
          <Metric compact label="Outstanding" value={money(summary?.creditors.total_outstanding ?? 0)} tone="cash" />
        </div>
      </section>
      <section className="panel span-2">
        <div className="section-head">
          <div>
            <h2>Cheque summary</h2>
            <p className="muted">Cheque records grouped by current status.</p>
          </div>
        </div>
        <div className="status-strip">
          {chequeStatuses.length === 0 ? <span className="muted">No cheques yet.</span> : null}
          {chequeStatuses.map(([status, count]) => (
            <div key={status}>
              <span className={statusClass(status)}>{statusLabel(status)}</span>
              <strong>{count}</strong>
              <small>{money(summary?.cheque_amounts_by_status?.[status] ?? 0)}</small>
            </div>
          ))}
        </div>
      </section>
      <section className="panel span-2">
        <div className="section-head">
          <div>
            <h2>Cheques ready to deposit</h2>
            <p className="muted">Pending cheques whose cheque date has arrived and expiry date has not passed.</p>
          </div>
        </div>
        <DataTable
          headers={['Cheque', 'Customer', 'Bank', 'Amount', 'Date Window']}
          rows={pendingCheques.map((cheque) => ({
            className: 'row-success',
            cells: [
              cheque.cheque_number,
              cheque.customer_name,
              cheque.bank_name,
              money(cheque.amount),
              <div key="window">Cheque: {shortDate(cheque.cheque_date)}<span className="cell-note">Expiry: {shortDate(cheque.expiry_date)}</span></div>,
            ],
          }))}
        />
      </section>
      <section className="panel span-2">
        <div className="section-head">
          <div>
            <h2>Gate pass print queue</h2>
            <p className="muted">Gate passes are controlled by print status only.</p>
          </div>
        </div>
        <div className="metric-row two">
          <Metric compact label="Not printed" value={summary?.gate_passes.not_printed ?? 0} tone="warning" />
          <Metric compact label="Printed" value={summary?.gate_passes.printed ?? 0} tone="success" />
        </div>
      </section>
      <section className="panel span-2">
        <h2>Inventory state</h2>
        <div className="status-strip">
          {Object.entries(summary?.items.by_status ?? {}).map(([status, count]) => (
            <div key={status}><span className={statusClass(status)}>{statusLabel(status)}</span><strong>{count}</strong></div>
          ))}
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, icon, tone = '', compact = false }: { label: string; value: string | number; icon?: ReactNode; tone?: string; compact?: boolean }) {
  return <div className={`metric-card ${tone} ${compact ? 'compact' : ''}`}>{icon ? <span className="metric-icon">{icon}</span> : null}<div><span>{label}</span><strong>{value}</strong></div></div>;
}

function SearchField({ label, value, onChange, compact = false }: { label: string; value: string; onChange: (value: string) => void; compact?: boolean }) {
  return (
    <label className={compact ? 'search-box compact' : 'search-box'}>
      <Search size={17} />
      <input value={value} onChange={(event) => onChange(event.currentTarget.value)} placeholder={label} aria-label={label} />
    </label>
  );
}

function UsersPanel({ users, currentUserId, deletingPath, canWrite, onAdd, onEdit, onDelete }: { users: ManagedUser[]; currentUserId?: number; deletingPath: string; canWrite: boolean; onAdd: () => void; onEdit: (user: ManagedUser) => void; onDelete: (user: ManagedUser) => void }) {
  return <section className="panel"><div className="section-head"><div><h2>User access control</h2><p className="muted">Create staff accounts and control module access per user.</p></div>{canWrite ? <button className="btn primary" onClick={onAdd}><UserPlus size={18} /> User</button> : null}</div><DataTable headers={['User', 'Module access', 'Status', 'Actions']} rows={users.map((user) => { const permanent = user.is_permanent_admin; return [<div key={user.id}><strong>{user.full_name}</strong><span className="cell-note">{user.username}{permanent ? ' · Permanent Digi7 Admin' : ''}</span></div>, <PermissionSummary key="access" permissions={user.effective_tab_permissions || user.tab_permissions} />, <span key="status" className={user.is_active ? 'badge good' : 'badge bad'}>{user.is_active ? 'Active' : 'Inactive'}</span>, <div className="table-actions" key="actions">{canWrite && !permanent ? <button className="icon-btn" onClick={() => onEdit(user)} aria-label={`Edit ${user.username}`}><Pencil size={16} /></button> : null}{canWrite && !permanent ? <button className="icon-btn danger" onClick={() => onDelete(user)} aria-label={`Delete ${user.username}`} disabled={user.id === currentUserId || deletingPath === `/auth/users/${user.id}/`} title={user.id === currentUserId ? 'You cannot delete your own account.' : `Delete ${user.username}`}>{deletingPath === `/auth/users/${user.id}/` ? <ProcessingLoader /> : <Trash2 size={16} />}</button> : null}{!canWrite || permanent ? <span className="muted">{permanent ? 'Locked' : 'View only'}</span> : null}</div>]; })} /></section>;
}

function CustomersPanel({ customers, ledgerByCustomer, creditReport, expanded, canWrite, onToggle, onAdd, onEdit, onDelete, onStatus, onDownloadReport }: { customers: Customer[]; ledgerByCustomer: Map<UUID, CustomerLedgerEntry[]>; creditReport: CreditReport | null; expanded: Set<UUID>; canWrite: boolean; onToggle: (id: UUID) => void; onAdd: () => void; onEdit: (customer: Customer) => void; onDelete: (customer: Customer) => void; onStatus: (customer: Customer) => void; onDownloadReport: (format: 'csv' | 'pdf') => void }) {
  const agingBuckets = creditReport?.aging_buckets ?? [];
  const reportCustomers = creditReport?.customers ?? [];
  const reportByCustomer = new Map(reportCustomers.map((customer) => [customer.id, customer]));
  return (
    <section className="panel">
      <div className="section-head">
        <div>
          <h2>Customers and balance breakdown</h2>
          <p className="muted">Total credit report, aging, and per-customer balances in one place.</p>
        </div>
        <div className="head-actions">
          <button className="btn" onClick={() => onDownloadReport('csv')}><FileDown size={18} /> CSV</button>
          <button className="btn" onClick={() => onDownloadReport('pdf')}><FileDown size={18} /> PDF</button>
          {canWrite ? <button className="btn primary" onClick={onAdd}><Plus size={18} /> Customer</button> : null}
        </div>
      </div>
      {creditReport ? (
        <div className="report-summary">
          <Metric compact label="Creditors" value={creditReport.totals.creditor_count} tone="warning" />
          <Metric compact label="Outstanding" value={money(creditReport.totals.total_outstanding)} tone="cash" />
          <Metric compact label="Customer credit" value={money(creditReport.totals.customer_credit_balance)} tone="success" />
          <div className="generated-card">
            <span>Generated</span>
            <strong>{new Date(creditReport.generated_at).toLocaleString('en-PK')}</strong>
          </div>
        </div>
      ) : null}
      {creditReport ? (
        <div className="aging-grid">
          {agingBuckets.map((bucket) => (
            <article className="aging-card" key={bucket.key}>
              <span>{bucket.label}</span>
              <strong>{money(creditReport.totals.aging[bucket.key] ?? 0)}</strong>
            </article>
          ))}
        </div>
      ) : null}
      <DataTable
        headers={['Customer', 'Contact Number', 'Remaining Balance', 'Last Payment', ...agingBuckets.map((bucket) => bucket.label)]}
        rows={reportCustomers.filter((customer) => Number(customer.remaining_balance) > 0).map((customer) => [
          customer.name,
          customer.phone,
          <strong className="money-bad" key="balance">{money(customer.remaining_balance)}</strong>,
          shortDate(customer.last_payment_date),
          ...agingBuckets.map((bucket) => <span key={bucket.key} className={Number(customer.aging[bucket.key] ?? 0) > 0 ? 'money-bad' : 'muted'}>{money(customer.aging[bucket.key] ?? 0)}</span>),
        ])}
      />
      <div className="record-stack">
        {customers.map((customer) => {
          const entries = ledgerByCustomer.get(customer.id) ?? [];
          const reportCustomer = reportByCustomer.get(customer.id);
          const balance = Number(customer.balance);
          return (
            <article className="record-card" key={customer.id}>
              <button className="record-main" onClick={() => onToggle(customer.id)}>
                {expanded.has(customer.id) ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                <div><strong>{customer.name}</strong><span>{customer.phone} · {customer.customer_type}</span></div>
                <b className={balance > 0 ? 'money-bad' : 'money-good'}>{money(customer.balance)}</b>
                <span className={customer.is_active ? 'badge good' : 'badge bad'}>{customer.is_active ? 'Active' : 'Inactive'}</span>
              </button>
              {canWrite ? (
                <div className="record-actions">
                  <button className="icon-btn" onClick={() => onEdit(customer)} aria-label={`Edit ${customer.name}`}><Pencil size={16} /></button>
                  <button className="icon-btn danger" onClick={() => onDelete(customer)} aria-label={`Delete ${customer.name}`} disabled={!customer.can_delete} title={customer.can_delete ? `Delete ${customer.name}` : 'Customers with transactions cannot be deleted.'}><Trash2 size={16} /></button>
                  <button className="btn small" onClick={() => onStatus(customer)}>{customer.is_active ? 'Mark inactive' : 'Mark active'}</button>
                </div>
              ) : null}
              {expanded.has(customer.id) ? (
                <div className="customer-detail-grid">
                  <div>
                    <h3>Ledger</h3>
                    <DataTable headers={['Date', 'Type', 'Description', 'Debit', 'Credit', 'Ref']} rows={entries.map((entry) => [entry.entry_date, statusLabel(entry.entry_type), entry.description, <span className="money-bad" key="debit">{money(entry.debit)}</span>, <span className="money-good" key="credit">{money(entry.credit)}</span>, entry.sale_number || entry.cheque_number || '-'])} />
                  </div>
                  <div>
                    <h3>Outstanding sales</h3>
                    <DataTable
                      headers={['Sale', 'Date', 'Outstanding', 'Items']}
                      rows={(reportCustomer?.sale_breakdown ?? []).map((sale) => [
                        sale.sale_number,
                        `${shortDate(sale.sale_date)} · ${sale.days_old} days`,
                        <strong className="money-bad" key="outstanding">{money(sale.outstanding_amount)}</strong>,
                        <div className="line-stack" key="items">{sale.items.map((item) => <span key={`${sale.sale_number}-${item.part_name}-${item.part_number}`}>{item.quantity} x {item.part_name}<small>{item.part_number || 'No number'} · {item.category || 'No category'} · {money(item.line_total)}</small></span>)}</div>,
                      ])}
                    />
                  </div>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ContainersPanel({
  containers,
  items,
  itemsByContainer,
  parts,
  expandedContainers,
  expandedParts,
  inventoryPane,
  canWrite,
  onInventoryPaneChange,
  onToggleContainer,
  onTogglePart,
  onAdd,
  onEdit,
  onDelete,
  onAddItem,
  onEditItem,
  onDeleteItem,
  onAddSubparts,
  onAddPart,
  onEditPart,
  onDeletePart,
}: {
  containers: Container[];
  items: ContainerItem[];
  itemsByContainer: Map<UUID, ContainerItem[]>;
  parts: PartInventory[];
  expandedContainers: Set<UUID>;
  expandedParts: Set<UUID>;
  inventoryPane: 'parts' | 'containers';
  canWrite: boolean;
  onInventoryPaneChange: (pane: 'parts' | 'containers') => void;
  onToggleContainer: (id: UUID) => void;
  onTogglePart: (id: UUID) => void;
  onAdd: () => void;
  onEdit: (container: Container) => void;
  onDelete: (container: Container) => void;
  onAddItem: (containerId: UUID) => void;
  onEditItem: (item: ContainerItem) => void;
  onDeleteItem: (item: ContainerItem) => void;
  onAddSubparts: (item: ContainerItem) => void;
  onAddPart: () => void;
  onEditPart: (part: PartInventory) => void;
  onDeletePart: (part: PartInventory) => void;
}) {
  const [partSearch, setPartSearch] = useState('');
  const [containerSearch, setContainerSearch] = useState('');
  const [containerItemSearch, setContainerItemSearch] = useState<Record<string, string>>({});
  const partQuery = partSearch.trim().toLowerCase();
  const containerQuery = containerSearch.trim().toLowerCase();
  const filteredParts = parts.filter((part) => {
    if (!partQuery) return true;
    const batchSources = (part.batches ?? []).map((batch) => `${batch.container_reference || ''} ${batch.source_label || ''}`).join(' ');
    return `${part.part_name} ${part.part_number} ${part.category} ${batchSources}`.toLowerCase().includes(partQuery);
  });
  const filteredContainers = containers.filter((container) => {
    if (!containerQuery) return true;
    return `${container.reference} ${container.origin_country} ${container.supplier_name} ${container.status}`.toLowerCase().includes(containerQuery);
  });

  return (
    <section className="panel inventory-workspace">
      <div className="section-head inventory-workspace-head">
        <div>
          <h2>Containers & Inventory</h2>
        </div>
        <div className="segmented-control" role="tablist" aria-label="Inventory views">
          <button
            type="button"
            role="tab"
            aria-selected={inventoryPane === 'parts'}
            className={inventoryPane === 'parts' ? 'active' : ''}
            onClick={() => onInventoryPaneChange('parts')}
          >
            <Boxes size={16} /> Parts Inventory
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={inventoryPane === 'containers'}
            className={inventoryPane === 'containers' ? 'active' : ''}
            onClick={() => onInventoryPaneChange('containers')}
          >
            <ContainerIcon size={16} /> Container Inventory
          </button>
        </div>
      </div>

      {inventoryPane === 'parts' ? (
        <div className="inventory-pane" role="tabpanel">
          <div className="section-head pane-head">
            <div>
              <h3>Parts inventory</h3>
              <p className="muted">Aggregate sellable stock. Expand a part to see the container cost layers behind it.</p>
            </div>
            {canWrite ? <button className="btn primary" onClick={onAddPart}><Plus size={18} /> Part</button> : null}
          </div>
          <SearchField label="Search parts by name, number, category, or container" value={partSearch} onChange={setPartSearch} />
          <div className="record-stack">
            {filteredParts.length === 0 ? <div className="empty-state"><Search size={22} /> No matching parts.</div> : null}
            {filteredParts.map((part) => {
              const expanded = expandedParts.has(part.id);
              return (
                <article className="record-card" key={part.id}>
                  <button className="record-main inventory-main" onClick={() => onTogglePart(part.id)}>
                    {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                    <div>
                      <strong>{part.part_name}</strong>
                      <span>{part.part_number || 'No part number'} · {part.category || 'No category'}</span>
                    </div>
                    <span className="stock-pill">Lifetime {part.quantity} {part.unit}</span>
                    <span className="stock-pill">{part.batches?.length || 0} price source{(part.batches?.length || 0) === 1 ? '' : 's'}</span>
                    <strong>{part.available_quantity} {part.unit} available</strong>
                  </button>
                  {canWrite ? (
                    <div className="record-actions">
                      <button className="icon-btn" onClick={() => onEditPart(part)} aria-label={`Edit ${part.part_name}`}><Pencil size={16} /></button>
                      <button className="icon-btn danger" onClick={() => onDeletePart(part)} aria-label={`Delete ${part.part_name}`} disabled={part.sold_quantity > 0} title={part.sold_quantity > 0 ? 'Parts with sale history cannot be deleted.' : `Delete ${part.part_name}`}><Trash2 size={16} /></button>
                    </div>
                  ) : null}
                  {expanded ? (
                    <DataTable
                      headers={['Source', 'Raw unit cost', 'Net unit cost', 'Batch quantity', 'Available', 'Actions']}
                      rows={(part.batches ?? []).map((batch) => [
                        <div key={batch.id}><strong>{batch.container_reference || batch.source_label || 'Manual adjustment'}</strong><span className="cell-note">{batch.notes || 'No notes'}</span></div>,
                        money(batch.raw_unit_cost),
                        money(batch.net_unit_cost),
                        `${batch.quantity} ${batch.unit}`,
                        <strong key="available">{batch.available_quantity} {batch.unit}</strong>,
                        <div className="table-actions" key="actions">
                          {canWrite && batch.container_item ? <button className="icon-btn" onClick={() => { const source = items.find((item) => item.id === batch.container_item); if (source) onEditItem(source); }} aria-label={`Edit source for ${part.part_name}`}><Pencil size={16} /></button> : <span className="muted">Source locked</span>}
                        </div>,
                      ])}
                    />
                  ) : null}
                </article>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="inventory-pane" role="tabpanel">
          <div className="section-head pane-head">
            <div>
              <h3>Container inventory</h3>
              <p className="muted">Original received manifest. Changes here intentionally apply a delta to parts inventory.</p>
            </div>
            {canWrite ? <button className="btn primary" onClick={onAdd}><Plus size={18} /> Container</button> : null}
          </div>
          <SearchField label="Search containers by reference, location, supplier, or status" value={containerSearch} onChange={setContainerSearch} />
          <div className="container-grid">
            {filteredContainers.length === 0 ? <div className="empty-state"><Search size={22} /> No matching containers.</div> : null}
            {filteredContainers.map((container) => {
              const containerItems = itemsByContainer.get(container.id) ?? [];
              const itemQuery = (containerItemSearch[container.id] || '').trim().toLowerCase();
              const childItemsByParent = new Map<UUID, ContainerItem[]>();
              containerItems.filter((item) => item.parent_item).forEach((item) => {
                const parentId = item.parent_item as UUID;
                childItemsByParent.set(parentId, [...(childItemsByParent.get(parentId) ?? []), item]);
              });
              const parentItems = containerItems.filter((item) => !item.parent_item);
              const visibleParentItems = parentItems.filter((item) => {
                if (!itemQuery) return true;
                const childMatches = (childItemsByParent.get(item.id) ?? []).some((child) => itemSearchText(child).includes(itemQuery));
                return itemSearchText(item).includes(itemQuery) || childMatches;
              });
              const itemRows = visibleParentItems.flatMap((item) => {
                const childItems = childItemsByParent.get(item.id) ?? [];
                const visibleChildItems = itemQuery
                  ? childItems.filter((child) => itemSearchText(child).includes(itemQuery) || itemSearchText(item).includes(itemQuery))
                  : childItems;
                const parentRow: DataRow = {
                  className: item.has_subparts ? 'parent-with-subparts' : undefined,
                  cells: [
                    <div key="part"><strong>{item.part_name}</strong>{item.has_subparts ? <span className="cell-note">{item.subpart_count} child part{item.subpart_count === 1 ? '' : 's'} created from this item</span> : null}</div>,
                    item.part_number || '-',
                    item.category || '-',
                    `${item.quantity} ${item.unit}`,
                    money(item.raw_unit_cost),
                    money(item.raw_total_cost),
                    money(item.added_cost_share),
                    money(item.net_unit_cost),
                    money(item.net_total_cost),
                    <div className="table-actions" key="actions">
                      {canWrite ? <button className="icon-btn" onClick={() => onEditItem(item)} aria-label={`Edit ${item.part_name}`}><Pencil size={16} /></button> : null}
                      {canWrite ? <button className="icon-btn" onClick={() => onAddSubparts(item)} aria-label={`Create subparts from ${item.part_name}`} title={item.quantity > 0 ? 'Create subparts' : 'No quantity left to split'} disabled={item.quantity <= 0}><Boxes size={16} /></button> : null}
                      {canWrite ? <button className="icon-btn danger" onClick={() => onDeleteItem(item)} aria-label={`Delete ${item.part_name}`}><Trash2 size={16} /></button> : <span className="muted">View only</span>}
                    </div>,
                  ],
                };
                const subpartRows: DataRow[] = visibleChildItems.map((child) => ({
                  className: 'subpart-row',
                  cells: [
                    <div className="subpart-cell" key="part"><span className="subpart-rail" aria-hidden="true" /><div><strong>{child.part_name}</strong><span className="cell-note">Child part from {item.part_name}</span></div></div>,
                    child.part_number || '-',
                    child.category || '-',
                    `${child.quantity} ${child.unit}`,
                    money(child.raw_unit_cost),
                    money(child.raw_total_cost),
                    money(child.added_cost_share),
                    money(child.net_unit_cost),
                    money(child.net_total_cost),
                    <div className="table-actions" key="actions">
                      {canWrite ? <button className="icon-btn" onClick={() => onEditItem(child)} aria-label={`Edit ${child.part_name}`}><Pencil size={16} /></button> : null}
                      {canWrite ? <button className="icon-btn danger" onClick={() => onDeleteItem(child)} aria-label={`Delete ${child.part_name}`}><Trash2 size={16} /></button> : <span className="muted">View only</span>}
                    </div>,
                  ],
                }));
                return [parentRow, ...subpartRows];
              });
              const expanded = expandedContainers.has(container.id);
              return (
                <article className="container-card" key={container.id}>
                  <div className="container-top">
                    <button className="record-main compact-main" onClick={() => onToggleContainer(container.id)}>
                      {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                      <div><strong>{container.reference}</strong><span>{container.origin_country || 'Origin not set'} · {container.supplier_name || 'Supplier not set'}</span></div>
                    </button>
                    <span className={statusClass(container.status)}>{statusLabel(container.status)}</span>
                  </div>
                  <div className="container-meta cost-meta">
                    <span>{container.arrival_date || 'No arrival date'}</span>
                    <span>{parentItems.length} manifest items</span>
                    <span>{containerItems.length - parentItems.length} child parts</span>
                    <span>Raw parts: <strong>{money(container.raw_parts_cost)}</strong></span>
                    <span>Added cost: <strong>{money(container.added_cost)}</strong></span>
                    <span>Total cost: <strong>{money(container.total_container_cost)}</strong></span>
                  </div>
                  {canWrite ? (
                    <div className="record-actions">
                      <button className="btn small" onClick={() => onAddItem(container.id)}><Plus size={16} /> Add manifest item</button>
                      <button className="icon-btn" onClick={() => onEdit(container)} aria-label={`Edit ${container.reference}`}><Pencil size={16} /></button>
                      <button className="icon-btn danger" onClick={() => onDelete(container)} aria-label={`Delete ${container.reference}`} title={`Delete ${container.reference}`}><Trash2 size={16} /></button>
                    </div>
                  ) : null}
                  {expanded ? (
                    <>
                    <SearchField compact label={`Search parts inside ${container.reference}`} value={containerItemSearch[container.id] || ''} onChange={(value) => setContainerItemSearch((previous) => ({ ...previous, [container.id]: value }))} />
                    <DataTable
                      headers={['Part', 'Part number', 'Category', 'Qty', 'Raw unit', 'Raw total', 'Added share', 'Net unit', 'Net total', 'Actions']}
                      rows={itemRows}
                    />
                    </>
                  ) : null}
                </article>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function SalesPanel({ sales, canWrite, onAdd, onEdit, onPrint }: { sales: AuctionSale[]; canWrite: boolean; onAdd: () => void; onEdit: (sale: AuctionSale) => void; onPrint: (sale: AuctionSale) => void }) {
  return (
    <section className="panel">
      <div className="section-head">
        <div>
          <h2>Auction sale ledger</h2>
          <p className="muted">Each sale can contain multiple items, creates the gate pass automatically, and prints from this row.</p>
        </div>
        {canWrite ? <button className="btn primary" onClick={onAdd}><Gavel size={18} /> Record sale</button> : null}
      </div>
      <DataTable
        headers={['Sale', 'Date', 'Customer', 'Payment', 'Total', 'Items', 'Gate pass', 'Actions']}
        rows={sales.map((sale) => [
          sale.sale_number,
          sale.sale_date,
          sale.customer_name || 'Cash sale',
          sale.payment_type,
          money(sale.total_amount),
          <div className="line-stack" key="items">
            {sale.lines.map((line) => (
              <span key={line.id}>
                {line.quantity} x {line.item.part_name}
                <small>{line.inventory_batch_label || 'Legacy batch'} · audit net {money(line.net_unit_cost_snapshot)} · current net {money(line.current_net_unit_cost)} · sold {money(line.sold_price)}</small>
              </span>
            ))}
          </div>,
          sale.gate_pass ? <span key="print" className={statusClass(sale.gate_pass.print_status)}>{statusLabel(sale.gate_pass.print_status)}</span> : <span key="missing" className="badge bad">missing</span>,
          <div className="table-actions" key="actions">
            {canWrite ? <button className="icon-btn" onClick={() => onEdit(sale)} aria-label={`Edit ${sale.sale_number}`}><Pencil size={16} /></button> : null}
            {canWrite ? <button className="icon-btn" onClick={() => onPrint(sale)} aria-label={`Print gate pass for ${sale.sale_number}`} disabled={!sale.gate_pass}><Printer size={16} /></button> : <span className="muted">View only</span>}
          </div>,
        ])}
      />
    </section>
  );
}

function ChequesPanel({ cheques, statuses, canWrite, onAdd, onEdit, onStatus, onAddStatus }: { cheques: Cheque[]; statuses: ChequeStatus[]; canWrite: boolean; onAdd: () => void; onEdit: (cheque: Cheque) => void; onStatus: (cheque: Cheque, statusId: UUID) => void; onAddStatus: () => void }) {
  const statusOptions: [string, string][] = statuses.map((status) => [status.id, status.name]);
  return <section className="panel"><div className="section-head"><div><h2>Cheque control</h2><p className="muted">Receivables reduce only when a cheque reaches a settlement status.</p></div>{canWrite ? <div className="head-actions"><button className="btn" onClick={onAddStatus}><Plus size={18} /> Status</button><button className="btn primary" onClick={onAdd}><Plus size={18} /> Cheque</button></div> : null}</div><DataTable headers={['Cheque', 'Customer', 'Name on cheque', 'Bank', 'Amount', 'Dates', 'Status', 'Actions']} rows={cheques.map((cheque) => ({ className: chequeRowClass(cheque), cells: [cheque.cheque_number, cheque.customer_name, cheque.name_on_cheque || '-', cheque.bank_name, money(cheque.amount), <div key="dates">Cheque: {cheque.cheque_date}<span className="cell-note">Expiry: {cheque.expiry_date}</span></div>, canWrite ? <Select key="status" compact name={`cheque-status-${cheque.id}`} label="Status" value={cheque.status} onChange={(value) => onStatus(cheque, value)} options={statusOptions} /> : <span key="status" className={statusClass(cheque.status_name)}>{cheque.status_name}</span>, canWrite ? <button className="icon-btn" key="edit" onClick={() => onEdit(cheque)} aria-label={`Edit ${cheque.cheque_number}`}><Pencil size={16} /></button> : <span className="muted" key="view">View only</span>] }))} /></section>;
}

function SettingsPanel({ options, chequeStatuses, canWrite, onAdd, onAddChequeStatus }: { options: DropdownOption[]; chequeStatuses: ChequeStatus[]; canWrite: boolean; onAdd: (group?: DropdownOption['group']) => void; onAddChequeStatus: () => void }) {
  const groups: DropdownOption['group'][] = ['bank', 'part_name', 'item_category', 'item_unit'];
  return <section className="panel"><div className="section-head"><div><h2>Dropdown settings</h2><p className="muted">Persisted values here appear in future entry dialogs for all users.</p></div>{canWrite ? <button className="btn primary" onClick={() => onAdd()}><Plus size={18} /> Dropdown value</button> : null}</div><div className="settings-grid">{groups.map((group) => <article className="option-card" key={group}><div className="section-head slim"><h3>{group.replace('_', ' ')}</h3>{canWrite ? <button className="icon-btn" onClick={() => onAdd(group)} aria-label={`Add ${group}`}><Plus size={16} /></button> : null}</div><div className="chips">{options.filter((option) => option.group === group && option.is_active).map((option) => <span className="chip" key={option.id}>{option.label}</span>)}</div></article>)}<article className="option-card"><div className="section-head slim"><h3>cheque statuses</h3>{canWrite ? <button className="icon-btn" onClick={onAddChequeStatus} aria-label="Add cheque status"><Plus size={16} /></button> : null}</div><div className="chips">{chequeStatuses.filter((status) => status.is_active).map((status) => <span className="chip" key={status.id}>{status.name}<small>{status.balance_effect.replaceAll('_', ' ')}</small></span>)}</div></article></div></section>;
}

function CustomerForm({ customer, onSave, isSaving }: { customer?: Customer; onSave: SaveHandler; isSaving: boolean }) {
  const [phone, setPhone] = useState(customer?.phone || '+92');
  return (
    <FormFrame
      title={customer ? 'Edit customer' : 'Add customer'}
      isSaving={isSaving}
      onSubmit={(form) => {
        const payload = {
          ...form,
          phone,
          customer_type: form.customer_type || 'individual',
          is_active: form.is_active === 'true',
        };
        onSave(customer ? `/operations/customers/${customer.id}/` : '/operations/customers/', payload, customer ? 'patch' : 'post');
      }}
    >
      <Field name="name" label="Customer name" defaultValue={customer?.name} required />
      <PhoneField value={phone} onChange={(value) => setPhone(value || '')} />
      <Select name="customer_type" label="Customer type" defaultValue={customer?.customer_type || 'individual'} options={[['individual', 'Individual'], ['business', 'Business']]} />
      {!customer ? (
        <>
          <Field name="opening_balance" label="Opening balance" type="number" defaultValue="0.00" min="0" step="0.01" />
          <Select name="opening_balance_direction" label="Opening balance direction" defaultValue="receivable" options={[['receivable', 'Customer owes ZSP'], ['credit', 'Customer has advance/credit']]} />
        </>
      ) : null}
      <Field name="email" label="Email" type="email" defaultValue={customer?.email} />
      <Field name="cnic_or_tax_id" label="CNIC / tax ID" defaultValue={customer?.cnic_or_tax_id} />
      <Select name="is_active" label="Status" defaultValue={String(customer?.is_active ?? true)} options={[['true', 'Active'], ['false', 'Inactive']]} required />
      <Field name="address" label="Address" defaultValue={customer?.address} textarea />
    </FormFrame>
  );
}

function ContainerForm({ container, onSave, isSaving }: { container?: Container; onSave: SaveHandler; isSaving: boolean }) {
  return <FormFrame title={container ? 'Edit container' : 'Add container'} isSaving={isSaving} onSubmit={(form) => onSave(container ? `/operations/containers/${container.id}/` : '/operations/containers/', { ...form, added_cost: form.added_cost || '0.00' }, container ? 'patch' : 'post')}><Field name="reference" label="Container reference" defaultValue={container?.reference} required /><Field name="origin_country" label="Origin country" defaultValue={container?.origin_country} /><Field name="supplier_name" label="Supplier" defaultValue={container?.supplier_name} /><Field name="arrival_date" label="Arrival date" type="date" defaultValue={container?.arrival_date || ''} /><Field name="added_cost" label="Added container cost" type="number" defaultValue={container?.added_cost || '0.00'} min="0" step="0.01" /><Select name="status" label="Status" defaultValue={container?.status || 'container_bought'} options={containerStatusOptions} required /><Field name="manifest_notes" label="Manifest notes" defaultValue={container?.manifest_notes} textarea /></FormFrame>;
}

function PartIdentityFields({ parts, options, defaults, prefix = '', onChange }: { parts: PartInventory[]; options: DropdownOption[]; defaults?: Partial<Pick<PartInventory, 'part_name' | 'part_number' | 'category'>>; prefix?: string; onChange?: (updates: Partial<SubpartDraft>) => void }) {
  const [partName, setPartName] = useState(defaults?.part_name || '');
  const [partNumber, setPartNumber] = useState(defaults?.part_number || '');
  const [category, setCategory] = useState(defaults?.category || '');
  const matchingNameParts = parts.filter((part) => part.part_name.toLowerCase() === partName.toLowerCase());
  const matchingNumberParts = matchingNameParts.filter((part) => (part.part_number || '').toLowerCase() === partNumber.toLowerCase());
  const partNameOptions = Array.from(new Set([...optionLabels(options, 'part_name'), ...parts.map((part) => part.part_name)].filter(Boolean))).sort();
  const partNumberOptions = Array.from(new Set(matchingNameParts.map((part) => part.part_number).filter(Boolean))).sort();
  const preferredCategories = Array.from(new Set(matchingNumberParts.map((part) => part.category).filter(Boolean))).sort();
  const relatedCategories = Array.from(new Set(matchingNameParts.map((part) => part.category).filter(Boolean))).filter((value) => !preferredCategories.includes(value)).sort();
  const categoryOptions = Array.from(new Set([...preferredCategories, ...relatedCategories, ...optionLabels(options, 'item_category')].filter(Boolean))).sort();
  const fieldName = (suffix: string) => prefix ? `${suffix}_${prefix}` : suffix;

  function setIdentityValue(key: 'part_name' | 'part_number' | 'category', value: string) {
    if (key === 'part_name') {
      setPartName(value);
      if (!value) {
        setPartNumber('');
        onChange?.({ part_name: value, part_number: '' });
        return;
      }
    }
    if (key === 'part_number') setPartNumber(value);
    if (key === 'category') setCategory(value);
    onChange?.({ [key]: value });
  }

  return (
    <div className="identity-picker full-span">
      <OptionText name={fieldName('part_name')} label="Part name" value={partName} onChange={(value) => setIdentityValue('part_name', value)} options={partNameOptions} required />
      <OptionText name={fieldName('part_number')} label="Part number" value={partNumber} onChange={(value) => setIdentityValue('part_number', value)} options={partNumberOptions} disabled={!partName.trim()} />
      <OptionText name={fieldName('category')} label="Category" value={category} onChange={(value) => setIdentityValue('category', value)} options={categoryOptions} featuredOptions={preferredCategories} relatedOptions={relatedCategories} />
      {prefix ? null : (
        <>
          <input type="hidden" name="part_name" value={partName} />
          <input type="hidden" name="part_number" value={partNumber} />
          <input type="hidden" name="category" value={category} />
        </>
      )}
    </div>
  );
}

function ItemForm({ item, containerId, containers, items, parts, options, onSave, isSaving }: { item?: ContainerItem; containerId?: UUID; containers: Container[]; items: ContainerItem[]; parts: PartInventory[]; options: DropdownOption[]; onSave: SaveHandler; isSaving: boolean }) {
  return <FormFrame title={item ? 'Edit container manifest item' : 'Add container manifest item'} isSaving={isSaving} onSubmit={(form) => {
    const selectedContainer = String(form.container || '');
    const duplicate = !item && items.find((candidate) => candidate.container === selectedContainer && !candidate.parent_item && partIdentity(candidate.part_name, candidate.part_number, candidate.category, candidate.unit) === partIdentity(String(form.part_name || ''), String(form.part_number || ''), String(form.category || ''), String(form.unit || 'piece')));
    if (duplicate && !window.confirm('This part already exists in this container. Confirming will accumulate the quantity into the existing manifest item instead of creating a duplicate row.')) return;
    onSave(item ? `/operations/items/${item.id}/` : '/operations/items/', { ...form, lot_number: '', quantity: Number(form.quantity || 1), raw_unit_cost: form.raw_unit_cost || '0.00' }, item ? 'patch' : 'post');
  }}><Select name="container" label="Container" defaultValue={item?.container || containerId} options={containers.map((container) => [container.id, container.reference])} required /><PartIdentityFields parts={parts} options={options} defaults={item} /><Field name="quantity" label="Quantity" type="number" defaultValue={String(item?.quantity ?? 1)} min="1" required /><OptionText name="unit" label="Unit" defaultValue={item?.unit || 'piece'} options={optionLabels(options, 'item_unit')} required /><Field name="raw_unit_cost" label="Raw unit cost" type="number" defaultValue={item?.raw_unit_cost || '0.00'} min="0" step="0.01" required /><Field name="description" label="Description" defaultValue={item?.description} textarea /></FormFrame>;
}

function PartForm({ part, containers, parts, options, onSave, isSaving }: { part?: PartInventory; containers: Container[]; parts: PartInventory[]; options: DropdownOption[]; onSave: SaveHandler; isSaving: boolean }) {
  const [sourceRows, setSourceRows] = useState<PartSourceDraft[]>([{ key: crypto.randomUUID(), container: '', quantity: 1, raw_unit_cost: '0.00', description: '' }]);
  const updateSource = (key: string, updates: Partial<PartSourceDraft>) => setSourceRows((rows) => rows.map((row) => row.key === key ? { ...row, ...updates } : row));
  const addSource = () => setSourceRows((rows) => [...rows, { key: crypto.randomUUID(), container: '', quantity: 1, raw_unit_cost: '0.00', description: '' }]);
  const removeSource = (key: string) => setSourceRows((rows) => rows.length === 1 ? rows : rows.filter((row) => row.key !== key));
  return <FormFrame title={part ? 'Edit parts inventory' : 'Add parts inventory'} isSaving={isSaving} onSubmit={(form, raw) => {
    const payload: Record<string, unknown> = { ...form };
    if (!part) {
      payload.sources = sourceRows.map((source) => ({
        container: source.container,
        quantity: Number(raw.get(`source_quantity_${source.key}`) || 1),
        raw_unit_cost: String(raw.get(`source_raw_${source.key}`) || '0.00'),
        description: String(raw.get(`source_description_${source.key}`) || ''),
      }));
      payload.quantity = sourceRows.reduce((total, source) => total + Number(raw.get(`source_quantity_${source.key}`) || 0), 0);
    }
    onSave(part ? `/operations/parts/${part.id}/` : '/operations/parts/', payload, part ? 'patch' : 'post');
  }}><PartIdentityFields parts={parts} options={options} defaults={part} /><OptionText name="unit" label="Unit" defaultValue={part?.unit || 'piece'} options={optionLabels(options, 'item_unit')} required />{part ? <div className="locked-row">Stock quantity is controlled from individual source rows.</div> : <div className="subform full-span"><div className="inline-between"><h3>Source containers</h3><button type="button" className="btn small" onClick={addSource}><Plus size={16} /> Source</button></div>{sourceRows.map((source) => <div className="source-line-grid" key={source.key}><Select name={`source_container_${source.key}`} label="Container" value={source.container} onChange={(value) => updateSource(source.key, { container: value })} options={containers.map((container) => [container.id, container.reference])} required /><Field name={`source_quantity_${source.key}`} label="Quantity" type="number" defaultValue={source.quantity} min="1" /><Field name={`source_raw_${source.key}`} label="Raw unit cost" type="number" defaultValue={source.raw_unit_cost} min="0" step="0.01" /><Field name={`source_description_${source.key}`} label="Source note" defaultValue={source.description} /><button type="button" className="icon-btn danger" onClick={() => removeSource(source.key)} aria-label="Remove source"><Trash2 size={16} /></button></div>)}</div>}<Field name="description" label="Description" defaultValue={part?.description} textarea /></FormFrame>;
}

function SubpartForm({ parentItem, parts, options, onSave, isSaving }: { parentItem: ContainerItem; parts: PartInventory[]; options: DropdownOption[]; onSave: SaveHandler; isSaving: boolean }) {
  const [subparts, setSubparts] = useState<SubpartDraft[]>([{ key: crypto.randomUUID(), part_name: '', part_number: '', category: '', quantity: 1, unit: parentItem.unit || 'piece', raw_unit_cost: '0.00', description: '' }]);
  const updateSubpart = (key: string, updates: Partial<SubpartDraft>) => setSubparts((rows) => rows.map((row) => row.key === key ? { ...row, ...updates } : row));
  const addSubpart = () => setSubparts((rows) => [...rows, { key: crypto.randomUUID(), part_name: '', part_number: '', category: '', quantity: 1, unit: parentItem.unit || 'piece', raw_unit_cost: '0.00', description: '' }]);
  const removeSubpart = (key: string) => setSubparts((rows) => rows.length === 1 ? rows : rows.filter((row) => row.key !== key));
  return <FormFrame title={`Create subparts from ${parentItem.part_name}`} isSaving={isSaving} onSubmit={(form, raw) => onSave(`/operations/items/${parentItem.id}/subparts/`, { split_quantity: Number(form.split_quantity || 1), subparts: subparts.map((subpart) => ({ part_name: subpart.part_name, part_number: subpart.part_number, category: subpart.category, unit: subpart.unit, quantity: Number(raw.get(`quantity_${subpart.key}`) || 1), raw_unit_cost: String(raw.get(`raw_${subpart.key}`) || '0.00'), description: String(raw.get(`description_${subpart.key}`) || '') })) })}><div className="locked-row">This reduces the parent part quantity and creates sellable subparts under the same container source.</div><Field name="split_quantity" label="Parent quantity to split" type="number" defaultValue={1} min="1" max={String(parentItem.quantity)} /><div className="subform full-span"><div className="inline-between"><h3>Subparts</h3><button type="button" className="btn small" onClick={addSubpart}><Plus size={16} /> Subpart</button></div>{subparts.map((subpart) => <div className="subpart-line-grid" key={subpart.key}><PartIdentityFields parts={parts} options={options} defaults={subpart} prefix={subpart.key} onChange={(updates) => updateSubpart(subpart.key, updates)} /><OptionText name={`unit_${subpart.key}`} label="Unit" value={subpart.unit} onChange={(value) => updateSubpart(subpart.key, { unit: value })} options={optionLabels(options, 'item_unit')} required /><Field name={`quantity_${subpart.key}`} label="Qty" type="number" defaultValue={subpart.quantity} min="1" /><Field name={`raw_${subpart.key}`} label="Raw unit cost" type="number" defaultValue={subpart.raw_unit_cost} min="0" step="0.01" /><Field name={`description_${subpart.key}`} label="Description" defaultValue={subpart.description} /><button type="button" className="icon-btn danger" onClick={() => removeSubpart(subpart.key)} aria-label="Remove subpart"><Trash2 size={16} /></button></div>)}</div></FormFrame>;
}

function SaleForm({
  sale,
  customers,
  availableBatches,
  banks,
  onSave,
  isSaving,
  selectedCustomer,
  onAddCustomer,
}: {
  sale?: AuctionSale;
  customers: Customer[];
  availableBatches: BatchWithPart[];
  banks: string[];
  onSave: SaveHandler;
  isSaving: boolean;
  selectedCustomer?: Customer | null;
  onAddCustomer: () => void;
}) {
  const [paymentType, setPaymentType] = useState(sale?.payment_type || 'cash');
  const [mixedCashAmount, setMixedCashAmount] = useState(sale?.cash_amount || '0.00');
  const [mixedChequeAmount, setMixedChequeAmount] = useState(sale?.cheque_amount || '0.00');
  const [customerId, setCustomerId] = useState(sale?.customer || '');
  const [issuedToOverride, setIssuedToOverride] = useState<string | null>(sale?.gate_pass?.issued_to_name ?? null);
  const saleBatches: BatchWithPart[] = sale?.lines.map((line) => ({
    id: line.inventory_batch || `legacy-${line.id}`,
    item: line.item.id,
    item_detail: line.item,
    part_name: line.item.part_name,
    part_number: line.item.part_number,
    category: line.item.category,
    unit: line.item.unit,
    container: null,
    container_reference: null,
    container_item: null,
    source_label: line.inventory_batch_label || 'Legacy batch',
    quantity: line.quantity,
    sold_quantity: 0,
    available_quantity: line.quantity,
    raw_unit_cost: line.current_raw_unit_cost || line.raw_unit_cost_snapshot,
    net_unit_cost: line.current_net_unit_cost || line.net_unit_cost_snapshot,
    notes: '',
  })) ?? [];
  const selectableBatches = [...saleBatches, ...availableBatches].filter((batch, index, all) => all.findIndex((candidate) => candidate.id === batch.id) === index);
  const [lineRows, setLineRows] = useState<SaleLineDraft[]>(() => sale?.lines.map((line) => ({ key: line.id, id: line.id, inventory_batch: line.inventory_batch || '', quantity: line.quantity, sold_price: line.sold_price, notes: line.notes })) ?? [{ key: crypto.randomUUID(), inventory_batch: '', quantity: 1, sold_price: '', notes: '' }]);
  const selectedCustomerName = customers.find((customer) => customer.id === customerId)?.name || '';
  const issuedToName = issuedToOverride ?? selectedCustomerName;
  const saleTotal = lineRows.reduce((total, line) => total + (Number(line.quantity || 0) * Number(line.sold_price || 0)), 0);
  const cashPortion = paymentType === 'cash' ? saleTotal : paymentType === 'mixed' ? Number(mixedCashAmount || 0) : 0;
  const chequePortion = paymentType === 'cheque' ? saleTotal : paymentType === 'mixed' ? Number(mixedChequeAmount || 0) : 0;
  const creditPortion = paymentType === 'credit' ? saleTotal : paymentType === 'mixed' ? Math.max(saleTotal - cashPortion - chequePortion, 0) : 0;
  const mixedSplitValid = paymentType !== 'mixed' || (cashPortion + chequePortion <= saleTotal && [cashPortion, chequePortion, creditPortion].filter((amount) => amount > 0).length >= 2);
  const updateLine = (key: string, updates: Partial<(typeof lineRows)[number]>) => setLineRows((rows) => rows.map((row) => row.key === key ? { ...row, ...updates } : row));
  const addLine = () => setLineRows((rows) => [...rows, { key: crypto.randomUUID(), inventory_batch: '', quantity: 1, sold_price: '', notes: '' }]);
  const removeLine = (key: string) => setLineRows((rows) => rows.length === 1 ? rows : rows.filter((row) => row.key !== key));

  useEffect(() => {
    if (!selectedCustomer) return;
    const handle = window.setTimeout(() => {
      setCustomerId(selectedCustomer.id);
      setIssuedToOverride(null);
    }, 0);
    return () => window.clearTimeout(handle);
  }, [selectedCustomer]);

  return (
    <FormFrame
      title={sale ? 'Edit sale' : 'Record auction sale'}
      isSaving={isSaving}
      onSubmit={(form) => {
        const lines = lineRows.map((line) => ({
          ...(line.id ? { id: line.id } : {}),
          inventory_batch: line.inventory_batch,
          quantity: Number(line.quantity),
          sold_price: line.sold_price,
          notes: line.notes || '',
        }));
        const payload: Record<string, unknown> = {
          sale_date: form.sale_date,
          customer: customerId || null,
          notes: form.notes || '',
          lines,
          gate_pass: {
            issued_to_name: issuedToName || '',
            issued_to_phone: form.issued_to_phone || '',
            vehicle_number: form.vehicle_number || '',
            driver_name: form.driver_name || '',
            notes: form.gate_pass_notes || '',
          },
        };
        if (!sale) payload.payment_type = paymentType;
        if (!sale && paymentType === 'mixed') {
          payload.payment_breakdown = {
            cash_amount: cashPortion.toFixed(2),
            cheque_amount: chequePortion.toFixed(2),
            credit_amount: creditPortion.toFixed(2),
          };
        }
        if ((paymentType === 'cheque' || (paymentType === 'mixed' && chequePortion > 0)) && !sale) {
          payload.cheque = {
            cheque_number: form.cheque_number,
            name_on_cheque: form.name_on_cheque,
            bank_name: form.bank_name,
            branch_name: form.branch_name || '',
            account_title: form.account_title || '',
            cheque_date: form.cheque_date,
            expiry_date: form.expiry_date,
            received_date: form.received_date || null,
            notes: form.cheque_notes || '',
          };
        }
        onSave(sale ? `/operations/auction-sales/${sale.id}/` : '/operations/auction-sales/', payload, sale ? 'patch' : 'post');
      }}
    >
      <div className="inline-between">
        <span className="form-note">Customer is mandatory unless payment type is cash. Cash sales do not enter customer balances.</span>
        <button type="button" className="btn small" onClick={onAddCustomer}><Plus size={16} /> New customer</button>
      </div>
      <Field name="sale_date" label="Sale date" type="date" defaultValue={sale?.sale_date || pakistanLocalDate()} required />
      {!sale ? <Select name="payment_type" label="Payment type" value={paymentType} onChange={setPaymentType} options={[['cash', 'Cash'], ['credit', 'Credit'], ['cheque', 'Cheque'], ['mixed', 'Mixed']]} required /> : <div className="locked-row">Payment type: {sale.payment_type}</div>}
      <Select name="customer" label="Customer" value={customerId} onChange={setCustomerId} options={customers.map((customer) => [customer.id, customer.name])} required={paymentType !== 'cash' || Boolean(sale?.customer)} />
      <div className="subform full-span">
        <div className="inline-between">
          <h3>Sale items</h3>
          <button type="button" className="btn small" onClick={addLine}><Plus size={16} /> Item</button>
        </div>
        {lineRows.map((line, index) => {
          const selected = selectableBatches.find((batch) => batch.id === line.inventory_batch);
          const batchOptions: [string, string][] = selectableBatches.map((batch) => [
            batch.id,
            `${batch.part_name}${batch.part_number ? ` / ${batch.part_number}` : ''}${batch.category ? ` / ${batch.category}` : ''} - ${batch.container_reference || batch.source_label || 'Manual'} - ${batch.available_quantity} ${batch.unit} available - net ${money(batch.net_unit_cost)}`,
          ]);
          return (
            <div className="sale-line-grid" key={line.key}>
              <div>
                <Select name={`item-${line.key}`} label={`Item ${index + 1}`} required value={line.inventory_batch} onChange={(value) => updateLine(line.key, { inventory_batch: value })} options={batchOptions} />
                {selected ? <span className="help-text">Raw {money(selected.raw_unit_cost)} · Net {money(selected.net_unit_cost)} · Source {selected.container_reference || selected.source_label || 'Manual'}</span> : null}
              </div>
              <div className="field">
                <label htmlFor={`qty-${line.key}`}>Qty</label>
                <input id={`qty-${line.key}`} type="number" min="1" max={selected ? Math.max(selected.available_quantity, line.quantity) : undefined} required value={line.quantity} onChange={(event) => updateLine(line.key, { quantity: Number(event.currentTarget.value) })} />
              </div>
              <div className="field">
                <label htmlFor={`price-${line.key}`}>Unit price</label>
                <input id={`price-${line.key}`} type="number" min="1" required value={line.sold_price} onChange={(event) => updateLine(line.key, { sold_price: event.currentTarget.value })} />
              </div>
              <div className="field">
                <label htmlFor={`notes-${line.key}`}>Notes</label>
                <input id={`notes-${line.key}`} value={line.notes} onChange={(event) => updateLine(line.key, { notes: event.currentTarget.value })} />
              </div>
              <button type="button" className="icon-btn danger" onClick={() => removeLine(line.key)} aria-label="Remove sale line"><Trash2 size={16} /></button>
            </div>
          );
        })}
        <div className="total-bar"><span>Sale total</span><strong>{money(saleTotal)}</strong></div>
      </div>
      {paymentType === 'mixed' && !sale ? (
        <div className="subform full-span mixed-payment-panel">
          <div className="inline-between">
            <h3>Mixed payment split</h3>
            <span className={mixedSplitValid ? 'badge good' : 'badge bad'}>{mixedSplitValid ? 'Balanced' : 'Needs adjustment'}</span>
          </div>
          <div className="payment-split-grid">
            <label className="payment-tile" htmlFor="mixed_cash_amount">
              <span>Cash received now</span>
              <strong>{money(cashPortion)}</strong>
              <input id="mixed_cash_amount" type="number" min="0" max={saleTotal} step="0.01" value={mixedCashAmount} onChange={(event) => setMixedCashAmount(event.currentTarget.value)} />
            </label>
            <label className="payment-tile" htmlFor="mixed_cheque_amount">
              <span>Cheque amount</span>
              <strong>{money(chequePortion)}</strong>
              <input id="mixed_cheque_amount" type="number" min="0" max={saleTotal} step="0.01" value={mixedChequeAmount} onChange={(event) => setMixedChequeAmount(event.currentTarget.value)} />
            </label>
            <div className="payment-tile readonly">
              <span>Credit balance</span>
              <strong>{money(creditPortion)}</strong>
              <small>Auto-calculated from sale total</small>
            </div>
          </div>
          <div className="payment-explainer">
            <span>Immediate cash will not enter receivables.</span>
            <span>Cheque and credit portions remain outstanding until settled.</span>
          </div>
        </div>
      ) : null}
      {((paymentType === 'cheque') || (paymentType === 'mixed' && chequePortion > 0)) && !sale ? <ChequeFields banks={banks} showAmount={paymentType === 'mixed'} amount={chequePortion} /> : null}
      {sale ? <div className="subform full-span"><h3>Payment split</h3><div className="payment-summary-grid"><span>Cash: <strong>{money(sale.cash_amount)}</strong></span><span>Cheque: <strong>{money(sale.cheque_amount)}</strong></span><span>Credit: <strong>{money(sale.credit_amount)}</strong></span><span>Receivable: <strong>{money(sale.receivable_amount)}</strong></span></div></div> : null}
      <div className="subform full-span">
        <h3>Gate pass details</h3>
        <div className="field"><label htmlFor="issued_to_name">Issued to</label><input id="issued_to_name" name="issued_to_name" value={issuedToName} onChange={(event) => { setIssuedToOverride(event.currentTarget.value); }} /></div>
        <Field name="issued_to_phone" label="Phone" />
        <Field name="vehicle_number" label="Vehicle number" defaultValue={sale?.gate_pass?.vehicle_number || ''} />
        <Field name="driver_name" label="Driver name" defaultValue={sale?.gate_pass?.driver_name || ''} />
        <Field name="gate_pass_notes" label="Gate pass notes" textarea />
      </div>
      <Field name="notes" label="Sale notes" defaultValue={sale?.notes} textarea />
    </FormFrame>
  );
}

function ChequeForm({ cheque, customers, statuses, banks, onSave, isSaving }: { cheque?: Cheque; customers: Customer[]; statuses: ChequeStatus[]; banks: string[]; onSave: SaveHandler; isSaving: boolean }) {
  return <FormFrame title={cheque ? 'Edit cheque' : 'Add cheque'} isSaving={isSaving} onSubmit={(form) => onSave(cheque ? `/finance/cheques/${cheque.id}/` : '/finance/cheques/', { ...form, received_date: form.received_date || null }, cheque ? 'patch' : 'post')}><Field name="cheque_number" label="Cheque number" defaultValue={cheque?.cheque_number} required /><Select name="customer" label="Customer" defaultValue={cheque?.customer} options={customers.map((customer) => [customer.id, customer.name])} required /><Field name="name_on_cheque" label="Name on cheque" defaultValue={cheque?.name_on_cheque} required /><OptionText name="bank_name" label="Bank" defaultValue={cheque?.bank_name} options={banks} required /><Field name="branch_name" label="Branch" defaultValue={cheque?.branch_name} /><Field name="account_title" label="Account title" defaultValue={cheque?.account_title} /><Field name="amount" label="Amount" type="number" defaultValue={cheque?.amount} required /><Field name="cheque_date" label="Cheque date" type="date" defaultValue={cheque?.cheque_date} required /><Field name="expiry_date" label="Expiry date" type="date" defaultValue={cheque?.expiry_date} required /><Field name="received_date" label="Received date" type="date" defaultValue={cheque?.received_date || ''} />{!cheque ? <Select name="status" label="Status" defaultValue={statuses.find((status) => status.name === 'Pending')?.id} options={statuses.map((status) => [status.id, status.name])} required /> : null}<Field name="notes" label="Notes" defaultValue={cheque?.notes} textarea /></FormFrame>;
}

function ChequeStatusForm({ onSave, isSaving }: { onSave: SaveHandler; isSaving: boolean }) {
  return <FormFrame title="Add cheque status" isSaving={isSaving} onSubmit={(form) => onSave('/finance/cheque-statuses/', form)}><Field name="name" label="Status name" required /><Select name="balance_effect" label="Balance effect" options={[['none', 'No automatic balance effect'], ['settles_balance', 'Settles customer balance'], ['reverses_settlement', 'Reverses settlement']]} required /></FormFrame>;
}

function DropdownOptionForm({ group, onSave, isSaving }: { group?: DropdownOption['group']; onSave: SaveHandler; isSaving: boolean }) {
  return <FormFrame title="Add dropdown value" isSaving={isSaving} onSubmit={(form) => onSave('/catalog/dropdown-options/', { ...form, sort_order: Number(form.sort_order || 100) })}><Select name="group" label="Dropdown" defaultValue={group} options={[['bank', 'Bank'], ['part_name', 'Part name'], ['item_category', 'Item category'], ['item_unit', 'Item unit']]} required /><Field name="label" label="Value" required /><Field name="sort_order" label="Sort order" type="number" defaultValue="100" /></FormFrame>;
}

function UserForm({ user, onSave, isSaving }: { user?: ManagedUser; onSave: SaveHandler; isSaving: boolean }) {
  const defaultPermissions = user?.effective_tab_permissions ?? user?.tab_permissions ?? { dashboard: 'view' as AccessLevel };
  return <FormFrame title={user ? 'Edit user account' : 'Create user account'} isSaving={isSaving} onSubmit={(form, raw) => { const tabPermissions = Object.fromEntries(tabOptions.map((tab) => [tab.id, raw.get(`tab_permission_${tab.id}`) || 'none'])); const payload: Record<string, unknown> = { username: form.username, first_name: form.first_name || '', last_name: form.last_name || '', is_active: form.is_active === 'true', tab_permissions: tabPermissions }; if (form.password) payload.password = form.password; onSave(user ? `/auth/users/${user.id}/` : '/auth/users/', payload, user ? 'patch' : 'post'); }}><Field name="username" label="Username" defaultValue={user?.username || ''} autoComplete="off" required /><Field name="first_name" label="First name" defaultValue={user?.first_name || ''} autoComplete="off" required /><Field name="last_name" label="Last name" defaultValue={user?.last_name || ''} autoComplete="off" /><Field name="password" label={user ? 'New password' : 'Password'} type="password" defaultValue="" autoComplete="new-password" required={!user} /><Select name="is_active" label="Status" defaultValue={String(user?.is_active ?? true)} options={[['true', 'Active'], ['false', 'Inactive']]} required /><PermissionMatrix defaults={defaultPermissions} /></FormFrame>;
}

function ChequeFields({ banks, showAmount = false, amount = 0 }: { banks: string[]; showAmount?: boolean; amount?: number }) {
  return (
    <div className="subform">
      <div className="inline-between">
        <h3>Cheque details</h3>
        {showAmount ? <span className="badge warn">Cheque {money(amount)}</span> : null}
      </div>
      <Field name="cheque_number" label="Cheque number" required />
      <Field name="name_on_cheque" label="Name on cheque" required />
      <OptionText name="bank_name" label="Bank" options={banks} required />
      <Field name="branch_name" label="Branch" />
      <Field name="account_title" label="Account title" />
      <Field name="cheque_date" label="Cheque date" type="date" required />
      <Field name="expiry_date" label="Expiry date" type="date" required />
      <Field name="received_date" label="Received date" type="date" />
      <Field name="cheque_notes" label="Cheque notes" textarea />
    </div>
  );
}

function FormFrame({ title, onSubmit, children, isSaving = false }: { title: string; onSubmit: (payload: Record<string, FormDataEntryValue>, raw: FormData) => void; children: ReactNode; isSaving?: boolean }) {
  return <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (isSaving) return; const raw = new FormData(event.currentTarget); onSubmit(Object.fromEntries(raw.entries()), raw); }}><h2>{title}</h2><div className="form-grid">{children}</div><button className="btn primary wide" type="submit" disabled={isSaving}>{isSaving ? <ProcessingLoader /> : <BadgeCheck size={18} />} {isSaving ? 'Saving...' : 'Save'}</button></form>;
}

function ProcessingLoader() {
  return <span className="processing-loader-shell" aria-hidden="true"><span className="processing-loader" /></span>;
}

function LoadingState({ label }: { label: string }) {
  return <div className="empty-state loading-state"><ProcessingLoader /><span>{label}</span></div>;
}

function ModalShell({ modal, onClose, children }: { modal: ModalState; onClose: () => void; children: ReactNode }) {
  if (!modal) return null;
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}><section className="modal-panel" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><button className="modal-close" onClick={onClose} aria-label="Close dialog"><X size={18} /></button>{children}</section></div>;
}

function Field({ name, label, type = 'text', required = false, textarea = false, defaultValue = '', autoComplete, min, max, step }: { name: string; label: string; type?: string; required?: boolean; textarea?: boolean; defaultValue?: string | number | null; autoComplete?: string; min?: string; max?: string; step?: string }) {
  return <div className="field"><label htmlFor={name}>{label}</label>{textarea ? <textarea id={name} name={name} required={required} defaultValue={String(defaultValue ?? '')} autoComplete={autoComplete} /> : <input id={name} name={name} type={type} required={required} defaultValue={String(defaultValue ?? '')} autoComplete={autoComplete} min={min} max={max} step={step} />}</div>;
}

function PhoneField({ value, onChange }: { value: string; onChange: (value?: string) => void }) {
  return <div className="field"><label htmlFor="phone">Phone number</label><PhoneInput id="phone" name="phone" international defaultCountry="PK" value={value} onChange={onChange} required /></div>;
}

function Select({ name, label, options, required = false, defaultValue, value, onChange, disabled = false, compact = false }: { name: string; label: string; options: [string, string][]; required?: boolean; defaultValue?: string | string[] | null; value?: string; onChange?: (value: string) => void; disabled?: boolean; compact?: boolean }) {
  return <ComboBox name={name} label={label} options={options.map(([optionValue, optionLabel]) => ({ value: optionValue, label: optionLabel }))} required={required} defaultValue={Array.isArray(defaultValue) ? defaultValue[0] : defaultValue} value={value} onChange={onChange} disabled={disabled} compact={compact} />;
}

function PermissionSummary({ permissions }: { permissions?: Record<string, AccessLevel | string> }) {
  const effective = permissions ?? {};
  return <div className="permission-summary">{tabOptions.map((tab) => <span className={accessClass(effective[tab.id])} key={tab.id}>{tab.label}: {accessLabel(effective[tab.id])}</span>)}</div>;
}

function PermissionMatrix({ defaults }: { defaults: Record<string, AccessLevel | string> }) {
  return <fieldset className="permission-grid"><legend>Module permissions</legend>{tabOptions.map((tab) => <div className="permission-row" key={tab.id}><span>{tab.label}</span><div className="permission-options">{accessOptions.map((option) => <label key={option.id} className={defaults[tab.id] === option.id ? 'selected' : ''}><input type="radio" name={`tab_permission_${tab.id}`} value={option.id} defaultChecked={(defaults[tab.id] || 'none') === option.id} />{option.label}</label>)}</div></div>)}</fieldset>;
}

function OptionText({ name, label, options, required = false, defaultValue = '', value, onChange, disabled = false, featuredOptions = [], relatedOptions = [] }: { name: string; label: string; options: string[]; required?: boolean; defaultValue?: string | null; value?: string; onChange?: (value: string) => void; disabled?: boolean; featuredOptions?: string[]; relatedOptions?: string[] }) {
  const featured = new Set(featuredOptions.map((option) => option.toLowerCase()));
  const related = new Set(relatedOptions.map((option) => option.toLowerCase()));
  const comboOptions = options.map((option) => {
    const key = option.toLowerCase();
    return {
      value: option,
      label: option,
      featured: featured.has(key),
      meta: featured.has(key) ? undefined : related.has(key) ? 'Used with this part name' : undefined,
    };
  }).sort((first, second) => {
    if (first.featured !== second.featured) return first.featured ? -1 : 1;
    const firstRelated = Boolean(first.meta);
    const secondRelated = Boolean(second.meta);
    if (firstRelated !== secondRelated) return firstRelated ? -1 : 1;
    return first.label.localeCompare(second.label);
  });
  return <ComboBox name={name} label={label} options={comboOptions} required={required} defaultValue={defaultValue} value={value} onChange={onChange} allowCustom disabled={disabled} helper="Type a new value here and it will be saved for future entries." />;
}

function ComboBox({
  name,
  label,
  options,
  required = false,
  defaultValue = '',
  value,
  onChange,
  allowCustom = false,
  disabled = false,
  helper,
  compact = false,
}: {
  name: string;
  label: string;
  options: ComboOption[];
  required?: boolean;
  defaultValue?: string | null;
  value?: string;
  onChange?: (value: string) => void;
  allowCustom?: boolean;
  disabled?: boolean;
  helper?: string;
  compact?: boolean;
}) {
  const normalizedOptions = useMemo(() => {
    const byValue = new Map<string, ComboOption>();
    options.filter((option) => option.value !== undefined && option.value !== null).forEach((option) => {
      if (!byValue.has(option.value)) byValue.set(option.value, option);
    });
    return Array.from(byValue.values());
  }, [options]);
  const [internalValue, setInternalValue] = useState(String(defaultValue ?? ''));
  const selectedValue = value ?? internalValue;
  const selectedLabel = normalizedOptions.find((option) => option.value === selectedValue)?.label ?? selectedValue;
  const [query, setQuery] = useState(selectedLabel);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const fieldRef = useRef<HTMLDivElement>(null);
  const displayQuery = !allowCustom && value !== undefined && !open ? selectedLabel : query;
  const filtered = normalizedOptions.filter((option) => `${option.label} ${option.meta ?? ''}`.toLowerCase().includes(displayQuery.toLowerCase()));
  const exactCustomMatch = normalizedOptions.some((option) => option.label.toLowerCase() === displayQuery.trim().toLowerCase());
  const hiddenValue = allowCustom ? displayQuery.trim() : selectedValue;

  useEffect(() => {
    function handleDocumentClick(event: MouseEvent) {
      if (!fieldRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleDocumentClick);
    return () => document.removeEventListener('mousedown', handleDocumentClick);
  }, []);

  function commit(nextValue: string, nextLabel: string) {
    setInternalValue(nextValue);
    setQuery(nextLabel);
    setOpen(false);
    onChange?.(nextValue);
  }

  return (
    <div className={compact ? 'field combobox-field compact' : 'field combobox-field'} ref={fieldRef}>
      <label htmlFor={`${name}-combo`}>{label}</label>
      <div className={disabled ? 'combobox disabled' : 'combobox'}>
        <input
          id={`${name}-combo`}
          type="text"
          value={displayQuery}
          disabled={disabled}
          required={required}
          placeholder={allowCustom ? '+ Add new or select existing' : 'Search and select...'}
          role="combobox"
          aria-expanded={open}
          aria-controls={`${name}-options`}
          aria-autocomplete="list"
          onFocus={() => {
            if (disabled) return;
            setQuery(selectedLabel);
            setOpen(true);
          }}
          onChange={(event) => {
            const next = event.currentTarget.value;
            setQuery(next);
            setOpen(true);
            setActiveIndex(0);
            if (allowCustom) onChange?.(next);
            if (allowCustom) setInternalValue(next);
            if (!allowCustom && !next) {
              setInternalValue('');
              onChange?.('');
            }
          }}
          onKeyDown={(event) => {
            if (disabled) return;
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              setOpen(true);
              setActiveIndex((index) => Math.min(index + 1, Math.max(filtered.length - 1, 0)));
            }
            if (event.key === 'ArrowUp') {
              event.preventDefault();
              setActiveIndex((index) => Math.max(index - 1, 0));
            }
            if (event.key === 'Enter' && open && filtered[activeIndex]) {
              event.preventDefault();
              commit(filtered[activeIndex].value, filtered[activeIndex].label);
            }
            if (event.key === 'Escape') setOpen(false);
          }}
        />
        <ChevronDown size={16} />
        <input type="hidden" name={name} value={hiddenValue} />
      </div>
      {open ? (
        <div className="combobox-menu" id={`${name}-options`} role="listbox">
          {filtered.map((option, index) => (
            <button
              type="button"
              key={option.value}
              className={[index === activeIndex ? 'active' : '', option.featured ? 'featured' : '', option.meta && !option.featured ? 'related' : ''].filter(Boolean).join(' ')}
              role="option"
              aria-selected={selectedValue === option.value}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => commit(option.value, option.label)}
            >
              <span>{option.label}</span>
              {option.meta ? <small>{option.meta}</small> : null}
            </button>
          ))}
          {allowCustom && displayQuery.trim() && !exactCustomMatch ? (
            <button type="button" className="add-new" onMouseDown={(event) => event.preventDefault()} onClick={() => commit(displayQuery.trim(), displayQuery.trim())}>+ Add &quot;{displayQuery.trim()}&quot;</button>
          ) : null}
          {filtered.length === 0 && (!allowCustom || !displayQuery.trim()) ? <span className="combobox-empty">No matching options</span> : null}
        </div>
      ) : null}
      {helper ? <span className="help-text">{helper}</span> : null}
    </div>
  );
}

type DataRow = React.ReactNode[] | { cells: React.ReactNode[]; className?: string };

function DataTable({ headers, rows }: { headers: string[]; rows: DataRow[] }) {
  if (rows.length === 0) return <div className="empty-state"><Search size={22} /> No records yet.</div>;
  return <div className="table-wrap"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => { const cells = Array.isArray(row) ? row : row.cells; const className = Array.isArray(row) ? undefined : row.className; return <tr key={index} className={className}>{cells.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>; })}</tbody></table></div>;
}

function gatePassPrintHtml(gatePass: GatePass) {
  const copies = [1, 2].map((copy) => `<section class="copy"><header><div><h1>ZSP Gate Pass</h1><p>Digi7 controlled inventory release</p></div><strong>${gatePass.gate_pass_number}</strong></header><div class="grid"><p><b>Issued to</b><span>${gatePass.issued_to_name}</span></p><p><b>Phone</b><span>${gatePass.issued_to_phone || '-'}</span></p><p><b>Vehicle</b><span>${gatePass.vehicle_number || '-'}</span></p><p><b>Driver</b><span>${gatePass.driver_name || '-'}</span></p><p><b>Copy</b><span>${copy} of 2</span></p><p><b>Issued at</b><span>${new Date(gatePass.issued_at).toLocaleString()}</span></p></div><table><thead><tr><th>Part</th><th>Part number</th><th>Category</th><th>Qty</th><th>Unit price</th><th>Total</th></tr></thead><tbody>${gatePass.lines.map((line) => `<tr><td>${line.sale_line.item.part_name}</td><td>${line.sale_line.item.part_number || '-'}</td><td>${line.sale_line.item.category || '-'}</td><td>${line.sale_line.quantity} ${line.sale_line.item.unit}</td><td>${money(line.sale_line.sold_price)}</td><td>${money(line.sale_line.line_total)}</td></tr>`).join('')}</tbody></table><footer><div><span></span><b>Issued by</b></div><div class="stamp"><span></span><b>Authorisation stamp</b></div><div><span></span><b>Gatekeeper</b></div></footer></section>`).join('');
  return `<!doctype html><html><head><title>${gatePass.gate_pass_number}</title><style>body{font-family:Arial,sans-serif;margin:0;color:#111827;background:#fff}.copy{page-break-after:always;padding:28px;min-height:92vh;border:2px solid #111827;margin:18px}header{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #111827;padding-bottom:16px}h1{margin:0;font-size:28px}p{margin:0}header p{color:#4b5563;margin-top:4px}header strong{font-size:20px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}.grid p{border:1px solid #d1d5db;padding:10px}.grid b{display:block;font-size:11px;text-transform:uppercase;color:#4b5563}.grid span{display:block;margin-top:5px;font-size:15px}table{width:100%;border-collapse:collapse;margin-top:16px}th,td{border:1px solid #111827;padding:10px;text-align:left}th{background:#f3f4f6}footer{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-top:60px}footer span{display:block;height:72px;border:1px dashed #6b7280;margin-bottom:8px}.stamp span{height:96px}footer b{font-size:12px;text-transform:uppercase;color:#374151}@media print{.copy{margin:0;border:2px solid #111827}.copy:last-child{page-break-after:auto}}</style></head><body>${copies}</body></html>`;
}
