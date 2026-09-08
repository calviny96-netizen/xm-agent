import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'XM Auto Audit · Property Matchmaker',
  description: 'Audit percakapan WhatsApp dan pencocokan otomatis buyer dengan listing property.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="id">
      <body className="antialiased">{children}</body>
    </html>
  );
}
