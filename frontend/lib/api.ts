import type { Paginated } from './types';

const API_BASE_URL = '/api';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function fieldLabel(value: string): string {
  if (value === 'currency_input') return 'Currency';
  return value.replaceAll('_', ' ').replace(/^./, (character) => character.toUpperCase());
}

function errorMessages(value: unknown, field = ''): string[] {
  if (typeof value === 'string') return [field ? `${fieldLabel(field)}: ${value}` : value];
  if (Array.isArray(value)) return value.flatMap((entry) => errorMessages(entry, field));
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, entry]) => (
      key === 'detail' || key === 'non_field_errors'
        ? errorMessages(entry)
        : errorMessages(entry, key)
    ));
  }
  return [];
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const csrfToken = typeof document === 'undefined'
    ? ''
    : document.cookie.split('; ').find((row) => row.startsWith('csrftoken='))?.split('=')[1] ?? '';
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(csrfToken ? { 'X-CSRFToken': decodeURIComponent(csrfToken) } : {}),
      ...(init.headers ?? {}),
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      const messages = errorMessages(body);
      if (messages.length > 0) message = messages.join(' ');
    } catch {
      // Keep the generic message when the response is not JSON.
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export function list<T>(path: string): Promise<Paginated<T>> {
  return request<Paginated<T>>(path);
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export function destroy<T>(path: string): Promise<T> {
  return request<T>(path, {
    method: 'DELETE',
  });
}
