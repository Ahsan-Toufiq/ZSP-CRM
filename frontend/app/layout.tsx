import type { Metadata } from 'next';
import 'react-phone-number-input/style.css';
import './globals.css';

export const metadata: Metadata = {
  title: 'Digi7 ZSP Operations',
  description: 'Container inventory, auction sales, gate passes, cheques, and customer balances.',
  icons: {
    icon: '/favicon.ico',
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
