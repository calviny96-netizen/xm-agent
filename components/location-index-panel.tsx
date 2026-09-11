'use client';

import { useEffect, useRef, useState } from 'react';
import { MapPin, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

type Cluster = { id: string; name: string; aliases: string[]; area: string; neighbor_count?: number; distance_km?: number };
type Catalog = { clusters: Cluster[]; total: number; pairs: number; has_more: boolean; filtered_total: number; sources: string[] };
type Preview = { clusters: number; pairs: number; new_clusters: number; new_pairs: number; new_aliases: number; revision: string };
const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100';
async function api<T = unknown>(path: string, body?: unknown, signal?: AbortSignal) {
  const response = await fetch(`/api/location-index${path}`, { signal, ...(body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  const data = await response.json() as T & { detail?: string };
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Indeks lokasi tidak dapat diproses.');
  return data;
}

export default function LocationIndexPanel({ processing, jobStatus, onImported }: { processing: boolean; jobStatus?: string; onImported: () => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [selection, setSelection] = useState<{ cluster: Cluster; neighbors: Cluster[] } | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [importing, setImporting] = useState(false);
  const [text, setText] = useState('');
  const [sourceName, setSourceName] = useState('Tempelan Excel');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      void api<Catalog>(`?${new URLSearchParams({ search, offset: String(offset) })}`, undefined, controller.signal)
        .then((data: Catalog) => setCatalog(data))
        .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [search, offset, version]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    setSelection(null);
    void api<{ cluster: Cluster; neighbors: Cluster[] }>(`/neighbors?${new URLSearchParams({ cluster: selectedId })}`, undefined, controller.signal)
      .then(setSelection).catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [selectedId, version]);

  async function chooseFile(input?: File) {
    if (!input) return;
    if (input.size > 3_000_000) { setError('Ukuran file maksimal 3 MB.'); return; }
    setText(await input.text()); setSourceName(input.name); setPreview(null); setError('');
    if (file.current) file.current.value = '';
  }

  async function inspect() {
    setBusy(true); setError(''); setNotice('');
    try { setPreview(await api('/preview', { text, source_name: sourceName }) as Preview); }
    catch (e) { setPreview(null); setError(e instanceof Error ? e.message : 'Preview gagal'); }
    finally { setBusy(false); }
  }

  async function save() {
    if (!preview) return;
    setBusy(true); setError('');
    try {
      const result = await api('/import', { text, source_name: sourceName, revision: preview.revision }) as { unchanged: boolean };
      setNotice(result.unchanged ? 'Semua data ini sudah ada. Tidak ada duplikat yang ditambahkan.' : 'Indeks ditambahkan. Pencocokan masuk antrean proses ulang.');
      setPreview(null); setText(''); setImporting(false); setVersion(v => v + 1); onImported();
    } catch (e) { setPreview(null); setError(e instanceof Error ? e.message : 'Penyimpanan gagal'); }
    finally { setBusy(false); }
  }

  return <div className="space-y-4 pb-3">
    <div><h3 className="flex items-center gap-2 text-base font-semibold"><MapPin className="size-4 text-blue-600" />Indeks kedekatan lokasi</h3><p className="mt-2 text-sm leading-6 text-slate-600">Nama lain dikenali sebagai cluster yang sama. Cluster berbeda dapat ditawarkan sebagai alternatif sampai 4 km, selama syarat properti tetap sesuai.</p></div>
    <div className="flex flex-wrap gap-2"><Badge variant="outline">{catalog?.total ?? 0} cluster</Badge><Badge variant="outline">{catalog?.pairs ?? 0} pasangan jarak</Badge><Badge className="bg-blue-50 text-blue-700">Batas 4 km</Badge></div>
    <p className="rounded-xl bg-slate-50 p-3 text-sm leading-5 text-slate-600">Jarak mengikuti angka antarcluster pada data impor. Ini bukan jarak perjalanan atau pengukuran dari alamat unit. Alternatif lokasi maksimal Warm; permintaan lokasi khusus tetap dihormati.</p>
    <Button variant="outline" className="w-full" disabled={busy || processing} onClick={() => setImporting(v => !v)}><Upload className="size-4" />{importing ? 'Tutup penambahan' : 'Tambah indeks dari CSV / Excel'}</Button>
    {importing && <section className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/40 p-3">
      <p className="text-sm text-slate-600">Upload CSV/TSV atau tempel tabel dari Excel. Kolom: Cluster, Alias, Area/Development, Cluster Terdekat (dalam radius 4 km). Pisahkan tetangga dengan titik koma, misalnya Nama Cluster (1.1).</p>
      <input ref={file} aria-label="File CSV indeks lokasi" type="file" accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values" disabled={busy} className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border file:border-slate-200 file:bg-white file:px-3 file:py-2" onChange={e => void chooseFile(e.target.files?.[0])} />
      <p className="break-all text-sm text-slate-500">{sourceName}</p>
      <label className="block text-sm font-medium">Tabel lokasi<textarea aria-label="Tabel lokasi" className={`${field} mt-1 h-36`} value={text} disabled={busy} onChange={e => { setText(e.target.value); setSourceName('Tempelan Excel'); setPreview(null); }} /></label>
      <Button variant="outline" disabled={!text.trim() || busy} onClick={() => void inspect()}>{busy ? 'Memeriksa…' : 'Periksa penambahan'}</Button>
      {preview && <div className="space-y-2 rounded-lg bg-white p-3 text-sm"><p className="font-semibold">Siap ditambahkan</p><p>{preview.new_clusters} cluster baru · {preview.new_pairs} pasangan jarak baru · {preview.new_aliases} alias baru</p><p className="text-slate-500">Total setelah digabung: {preview.clusters} cluster dan {preview.pairs} pasangan. Data yang sama tidak digandakan. Konflik jarak ditolak.</p><Button className="w-full" disabled={busy || processing} onClick={() => void save()}>Tambahkan & proses ulang</Button></div>}
    </section>}
    {processing && <p role="status" className="text-sm text-blue-700">Pencocokan sedang diproses ulang…</p>}
    {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-700">{notice.includes('antrean') && jobStatus === 'completed' ? 'Indeks tersimpan. Pencocokan selesai diperbarui.' : notice}</p>}
    <label className="block text-sm font-medium">Cari cluster, alias, atau area<input className={`${field} mt-1`} value={search} onChange={e => { setSearch(e.target.value); setOffset(0); }} /></label>
    {loading ? <p className="text-sm text-slate-500">Memuat indeks…</p> : <div className="max-h-56 overflow-y-auto rounded-xl border border-slate-200">{catalog?.clusters.map(c => <button type="button" key={c.id} aria-pressed={selectedId === c.id} className={`block w-full border-b border-slate-100 px-3 py-2.5 text-left text-sm last:border-0 ${selectedId === c.id ? 'bg-blue-50' : 'hover:bg-slate-50'}`} onClick={() => setSelectedId(c.id)}><span className="block font-semibold">{c.name}</span><span className="text-slate-500">{c.area ? `${c.area} · ` : ''}{c.neighbor_count} lokasi terdekat{c.aliases.length ? ` · Alias: ${c.aliases.join(', ')}` : ''}</span></button>)}{!catalog?.clusters.length && <p className="p-4 text-sm text-slate-500">Belum ada cluster untuk pencarian ini.</p>}</div>}
    <div className="flex items-center justify-between gap-2 text-sm text-slate-500"><span>{catalog?.filtered_total ?? 0} hasil</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={!offset || loading} onClick={() => setOffset(v => Math.max(0,v-30))}>Sebelumnya</Button><Button size="sm" variant="outline" disabled={!catalog?.has_more || loading} onClick={() => setOffset(v => v+30)}>Berikutnya</Button></div></div>
    {selection && <section className="rounded-xl border border-slate-200 p-3"><h4 className="text-sm font-semibold">Dekat {selection.cluster.name}</h4><p className="mt-1 text-sm text-slate-500">Jarak menurut data impor, diurutkan dari terdekat.</p><div className="mt-3 max-h-64 overflow-y-auto divide-y divide-slate-100">{selection.neighbors.map(c => <div key={c.id} className="flex items-start justify-between gap-3 py-2 text-sm"><span>{c.name}</span><Badge variant="outline" className="shrink-0">{new Intl.NumberFormat('id-ID',{maximumFractionDigits:2}).format(c.distance_km ?? 0)} km</Badge></div>)}{!selection.neighbors.length && <p className="text-sm text-slate-500">Belum ada jarak tercatat.</p>}</div></section>}
  </div>;
}
