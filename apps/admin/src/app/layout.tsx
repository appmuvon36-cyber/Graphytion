import type { Metadata } from 'next';
export const metadata: Metadata = { title: 'Graphytion Admin', description: 'Graphytion operations control plane' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="id"><body style={{margin:0,fontFamily:'Arial,sans-serif',background:'#f7f9fc',color:'#142033'}}>{children}</body></html>; }
