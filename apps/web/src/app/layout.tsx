import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'Graphytion', description: 'AI motion graphic and video production studio' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="id"><body>{children}</body></html>; }
