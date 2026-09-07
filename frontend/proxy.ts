import { NextRequest, NextResponse } from 'next/server';

const appRoutes = new Set(['/login', '/dashboard', '/customers', '/containers', '/sales', '/cheques', '/settings', '/users']);

export function proxy(request: NextRequest) {
  if (appRoutes.has(request.nextUrl.pathname)) {
    return NextResponse.rewrite(new URL('/', request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/login', '/dashboard', '/customers', '/containers', '/sales', '/cheques', '/settings', '/users'],
};
