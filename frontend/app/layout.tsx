import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Digi7 ZSP Operations',
  description: 'Container inventory, auction sales, gate passes, cheques, and customer balances.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
