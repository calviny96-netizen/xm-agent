'use client';

import { useEffect, useState, type SyntheticEvent } from 'react';
import { Database, LockKeyhole, Pencil, Plus, ShieldCheck, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';

export type Account = { id: string; email: string; display_name: string; role: string; is_locked: boolean };
const blank = { email: '', display_name: '', password: '', is_locked: false };
const field = 'mt-1 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 outline-none focus:border-blue-500';

async function request<T = Account>(path: string, init?: RequestInit) {
  const response = await fetch(`/api/auth/users${path}`, init);
  const data = await response.json() as T & { detail?: string };
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Periksa data akun yang diisi.');
  return data;
}

export default function AdminUsers({ onManageWorkspace }: { onManageWorkspace: (account: Account) => void }) {
  const [users, setUsers] = useState<Account[]>([]);
  const [editing, setEditing] = useState<Account | null>(null);
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => { void request<Account[]>('').then(setUsers).catch((e: Error) => setError(e.message)); }, []);

  async function save(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      await request(editing ? `/${editing.id}` : '', {
        method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, password: form.password || undefined }),
      });
      setUsers(await request<Account[]>('')); setNotice(editing ? 'Perubahan akun tersimpan.' : 'User baru berhasil ditambahkan dengan workspace kosong dan terisolasi.');
      setEditing(null); setForm(blank);
    } catch (e) { setError(e instanceof Error ? e.message : 'Gagal menyimpan akun'); }
    finally { setBusy(false); }
  }

  return <section className="space-y-5">
    <div className="rounded-2xl bg-[#081735] p-6 text-white"><p className="flex items-center gap-2 text-sm font-semibold text-cyan-300"><ShieldCheck className="size-4" />Panel Admin</p><h1 className="mt-2 text-2xl font-semibold">Kelola akses tim</h1><p className="mt-2 text-sm text-blue-100">Tambah user, ubah email dan password, atau kunci akses akun. Pilih Data & setting untuk mengelola JSON, glosarium, lokasi, dan pencocokan khusus setiap akun.</p></div>
    {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    {notice && <output className="block rounded-xl bg-emerald-50 p-4 text-sm text-emerald-700">{notice}</output>}
    <div className="grid items-start gap-5 lg:grid-cols-[1fr_380px]">
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white"><h2 className="flex items-center gap-2 border-b p-4 font-semibold"><Users className="size-4" />Daftar akun ({users.length})</h2><div className="divide-y divide-slate-100">{users.map(user => <article key={user.id} className="flex flex-wrap items-center gap-3 p-4"><div className={`flex size-10 shrink-0 items-center justify-center rounded-full ${user.is_locked ? 'bg-red-50 text-red-600' : 'bg-blue-50 text-blue-700'}`}>{user.is_locked ? <LockKeyhole className="size-4" /> : user.display_name.slice(0, 1).toUpperCase()}</div><div className="min-w-0 flex-1"><p className="font-semibold">{user.display_name}</p><p className="break-all text-sm text-slate-500">{user.email}</p><p className={`mt-1 text-xs font-semibold ${user.is_locked ? 'text-red-600' : 'text-emerald-700'}`}>{user.role === 'admin' ? 'Administrator' : user.is_locked ? 'Terkunci' : 'Aktif'}</p></div><Button variant="outline" size="sm" disabled={busy} onClick={() => onManageWorkspace(user)}><Database className="size-3.5" />Data & setting</Button>{user.role !== 'admin' && <Button variant="outline" size="sm" disabled={busy} onClick={() => { setEditing(user); setForm({ email: user.email, display_name: user.display_name, is_locked: user.is_locked, password: '' }); setError(''); setNotice(''); }}><Pencil className="size-3.5" />Kelola</Button>}</article>)}</div></div>
      <form onSubmit={save} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5"><h2 className="flex items-center gap-2 font-semibold"><Plus className="size-4" />{editing ? 'Kelola user' : 'Tambah user'}</h2><label className="block text-sm font-medium">Nama<input required maxLength={100} className={field} value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} /></label><label className="block text-sm font-medium">Email<input required type="email" autoComplete="off" className={field} value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></label><label className="block text-sm font-medium">{editing ? 'Password baru (opsional)' : 'Password'}<input required={!editing} type="password" minLength={8} maxLength={200} autoComplete="new-password" className={field} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /><span className="mt-1 block text-xs font-normal text-slate-500">Minimal 8 karakter{editing ? '; kosongkan untuk mempertahankan password.' : '.'}</span></label>{editing && <label className="flex items-center gap-3 rounded-xl bg-red-50 p-3 text-sm text-red-800"><input type="checkbox" checked={form.is_locked} onChange={e => setForm({ ...form, is_locked: e.target.checked })} />Kunci / nonaktifkan akun ini</label>}<Button type="submit" className="w-full" disabled={busy}>{busy ? 'Menyimpan…' : editing ? 'Simpan perubahan' : 'Tambahkan user'}</Button>{editing && <Button type="button" variant="outline" className="w-full" disabled={busy} onClick={() => { setEditing(null); setForm(blank); }}>Batal edit</Button>}</form>
    </div>
  </section>;
}
