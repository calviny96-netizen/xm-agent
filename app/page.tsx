'use client';

import { Building2, Eye, EyeOff, LoaderCircle, MessageSquareText, Users } from 'lucide-react';
import Image from 'next/image';
import { SyntheticEvent, useCallback, useEffect, useState } from 'react';

import MatchWorkspace from '@/components/match-workspace';
import SettingsDrawer from '@/components/settings-drawer';
import { Button } from '@/components/ui/button';

type User = { id: string; email: string; display_name: string };
type Stats = { raw_messages: number; buyer_requests: number; listings: number };

const compact = new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 1 });

async function getUser() {
  const response = await fetch('/api/auth/me');
  if (response.status === 401) return null;
  if (!response.ok) throw new Error('Aplikasi belum siap');
  return response.json() as Promise<User>;
}

function LoginScreen({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState('admin@autoaudit.id');
  const [password, setPassword] = useState('admin');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true); setError('');
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const body = (await response.json().catch(() => ({}))) as User & { detail?: string };
      if (!response.ok) throw new Error(body.detail || 'Login gagal');
      onLogin(body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Login gagal');
    } finally { setLoading(false); }
  }

  return <main className="grid min-h-screen bg-[#f4f7fb] lg:grid-cols-[1.05fr_.95fr]">
    <section className="relative hidden overflow-hidden bg-[#081735] p-12 text-white lg:flex lg:flex-col lg:justify-between">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_15%,rgba(41,121,255,.28),transparent_35%),radial-gradient(circle_at_85%_85%,rgba(12,192,216,.16),transparent_32%)]" />
      <Image src="/brand-auto-audit.png" alt="Xavier Marks Auto Audit" width={1024} height={418} className="relative h-14 w-auto self-start rounded-xl bg-white px-3 py-2 object-contain" />
      <div className="relative max-w-xl"><p className="text-sm font-semibold uppercase tracking-[.16em] text-cyan-300">Property Matchmaker</p><h1 className="mt-4 text-4xl font-semibold leading-tight tracking-[-.04em]">Temukan pasangan buyer dan property dalam satu ruang kerja.</h1><p className="mt-5 max-w-lg text-base leading-7 text-blue-100/80">Data percakapan, toleransi, bobot, dan glosarium tersimpan agar tim bekerja dengan aturan yang konsisten.</p></div>
      <p className="relative text-sm text-blue-200/70">XM Darmo · Internal workspace</p>
    </section>
    <section className="flex items-center justify-center p-6 sm:p-10">
      <form onSubmit={submit} className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-7 shadow-[0_24px_70px_rgba(15,23,42,.10)] sm:p-9">
        <Image src="/brand-auto-audit.png" alt="Xavier Marks Auto Audit" width={1024} height={418} className="mb-8 h-12 w-auto object-contain lg:hidden" />
        <p className="text-sm font-semibold text-blue-700">XM Audit Properti</p><h2 className="mt-2 text-3xl font-semibold tracking-[-.035em] text-slate-950">Masuk ke workspace</h2><p className="mt-2 text-sm leading-6 text-slate-500">Gunakan akun yang terdaftar untuk membuka data dan pengaturan pencocokan.</p>
        <div className="mt-7 space-y-4">
          <label className="block text-sm font-medium text-slate-700">Email<input required type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-1.5 h-11 w-full rounded-xl border border-slate-200 px-3 outline-none focus:border-blue-500 focus:ring-3 focus:ring-blue-100" /></label>
          <label className="block text-sm font-medium text-slate-700">Password<span className="relative mt-1.5 block"><input required type={showPassword ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className="h-11 w-full rounded-xl border border-slate-200 px-3 pr-11 outline-none focus:border-blue-500 focus:ring-3 focus:ring-blue-100" /><button type="button" aria-label={showPassword ? 'Sembunyikan password' : 'Tampilkan password'} onClick={() => setShowPassword(!showPassword)} className="absolute top-1/2 right-3 -translate-y-1/2 text-slate-400">{showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}</button></span></label>
        </div>
        {error && <p role="alert" className="mt-4 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-700">{error}</p>}
        <Button type="submit" className="mt-6 h-11 w-full" disabled={loading}>{loading && <LoaderCircle className="size-4 animate-spin" />}{loading ? 'Memeriksa akun…' : 'Masuk'}</Button>
      </form>
    </section>
  </main>;
}

function Dashboard({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [stats, setStats] = useState<Stats>({ raw_messages: 0, buyer_requests: 0, listings: 0 });
  const refresh = useCallback(() => {
    void fetch('/api/stats').then((response) => response.ok ? response.json() as Promise<Stats> : null).then((data) => { if (data) setStats(data); });
  }, []);
  useEffect(() => { refresh(); const timer = window.setInterval(refresh, 10_000); return () => window.clearInterval(timer); }, [refresh]);

  return <main className="min-h-screen bg-[#f4f7fb] text-slate-950">
    <header className="sticky top-0 z-40 border-b border-slate-200/90 bg-white/95 backdrop-blur-xl">
      <div className="mx-auto flex h-[68px] max-w-[1540px] items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-4"><Image src="/brand-auto-audit.png" alt="Xavier Marks Auto Audit" width={1024} height={418} className="h-10 w-auto max-w-[220px] object-contain" /><span className="hidden h-7 w-px bg-slate-200 sm:block" /><div className="hidden sm:block"><p className="text-sm font-semibold">Audit Properti</p><p className="text-xs text-slate-500">Property Matchmaker</p></div></div>
        <div className="flex items-center gap-3"><div className="hidden text-right sm:block"><p className="text-[13px] font-semibold">{user.display_name}</p><p className="text-xs text-slate-500">{user.email}</p></div><SettingsDrawer email={user.email} onLogout={onLogout} onDataChanged={refresh} /></div>
      </div>
    </header>
    <div className="mx-auto max-w-[1540px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <p className="mb-4 text-[13px] text-slate-500">Audit Properti <span className="mx-1 text-slate-300">›</span> <span className="font-semibold text-slate-700">Pencocokan buyer & property</span></p>
      <section className="mb-5 grid gap-3 sm:grid-cols-3">
        <Metric icon={MessageSquareText} label="Pesan chat dianalisis" value={stats.raw_messages} tone="blue" />
        <Metric icon={Users} label="Permintaan buyer" value={stats.buyer_requests} tone="indigo" />
        <Metric icon={Building2} label="Listing property" value={stats.listings} tone="cyan" />
      </section>
      <MatchWorkspace />
    </div>
  </main>;
}

function Metric({ icon: Icon, label, value, tone }: { icon: typeof Building2; label: string; value: number; tone: 'blue' | 'indigo' | 'cyan' }) {
  const colors = { blue: 'bg-blue-50 text-blue-700', indigo: 'bg-indigo-50 text-indigo-700', cyan: 'bg-cyan-50 text-cyan-700' };
  return <article className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm shadow-slate-100"><div className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${colors[tone]}`}><Icon className="size-4" /></div><div><p className="text-2xl font-semibold tracking-[-.03em]">{compact.format(value)}</p><p className="text-sm text-slate-500">{label}</p></div></article>;
}

export default function Home() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => { void getUser().then(setUser).catch(() => setUser(null)); }, []);
  if (user === undefined) return <main className="flex min-h-screen items-center justify-center bg-[#f4f7fb]"><LoaderCircle className="size-6 animate-spin text-blue-700" /><span className="sr-only">Memuat aplikasi</span></main>;
  if (!user) return <LoginScreen onLogin={setUser} />;
  return <Dashboard user={user} onLogout={() => { void fetch('/api/auth/logout', { method: 'POST' }).finally(() => setUser(null)); }} />;
}
