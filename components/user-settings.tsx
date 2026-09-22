'use client';

import { useWorkspaceFetch } from '@/lib/workspace-context';

import { useEffect, useState } from 'react';
import { Eye, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';

const labels: Record<string, string> = { land_tolerance_pct: 'Toleransi luas tanah', building_tolerance_pct: 'Toleransi luas bangunan', price_tolerance_pct: 'Toleransi harga', location_weight_pct: 'Bobot lokasi', land_weight_pct: 'Bobot luas tanah', building_weight_pct: 'Bobot luas bangunan', price_weight_pct: 'Bobot harga', semantic_weight_pct: 'Bobot kemiripan teks', data_quality_weight_pct: 'Bobot kualitas data' };

export default function UserSettings({ email, onLogout, search }: { email: string; onLogout: () => void; search: string | null }) {
  const workspaceFetch = useWorkspaceFetch();
  const [settings, setSettings] = useState<Record<string, number>>({});
  const [error, setError] = useState('');
  useEffect(() => { void workspaceFetch('/settings').then(async r => { if (!r.ok) throw new Error('Pengaturan belum dapat dimuat.'); return r.json() as Promise<Record<string, number>>; }).then(setSettings).catch((e: Error) => setError(e.message)); }, [workspaceFetch]);
  return <Sheet><SheetTrigger render={<Button variant="outline" size="icon" aria-label="Lihat pengaturan" />}><Eye className="size-4" /></SheetTrigger><SheetContent className="w-full sm:max-w-[440px]"><SheetHeader><SheetTitle>Informasi pengaturan</SheetTitle><SheetDescription>Hanya lihat · Pengaturan khusus akun Anda</SheetDescription></SheetHeader><div className="flex-1 space-y-5 overflow-y-auto px-5 pb-6"><div className="rounded-xl bg-blue-50 p-4"><p className="text-sm font-semibold">Default pencarian</p><div className="mt-2 flex flex-wrap gap-2">{search?.split('\n').map(term => <span key={term} className="rounded-lg bg-white px-2 py-1 text-sm text-blue-700">{term}</span>)}</div></div>{error && <p role="alert" className="text-sm text-red-700">{error}</p>}<dl className="divide-y divide-slate-100">{Object.entries(labels).map(([key, label]) => <div key={key} className="flex justify-between gap-3 py-3 text-sm"><dt className="text-slate-600">{label}</dt><dd className="font-semibold">{settings[key] ?? '—'}%</dd></div>)}</dl><p className="break-all text-sm text-slate-500">{email}</p><Button variant="outline" className="w-full" onClick={onLogout}><LogOut className="size-4" />Keluar</Button></div></SheetContent></Sheet>;
}
