'use client';

import { FileJson, FileSpreadsheet, LogOut, RefreshCw, Settings2, UploadCloud } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

type Settings = {
  land_tolerance_pct: number; building_tolerance_pct: number; price_tolerance_pct: number;
  location_weight_pct: number; land_weight_pct: number; building_weight_pct: number;
  price_weight_pct: number; semantic_weight_pct: number; data_quality_weight_pct: number;
};
type ImportRow = { id: string; agent_name: string; file_name: string; status: string; created_at: string };
type CsvPreview = { fileName: string; rows: [string, string][]; invalid: number; duplicates: number };

const fieldClass = 'h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500 focus:ring-3 focus:ring-blue-100';
const labels: Array<[keyof Settings, string]> = [
  ['location_weight_pct', 'Lokasi'], ['land_weight_pct', 'Luas tanah'], ['building_weight_pct', 'Luas bangunan'],
  ['price_weight_pct', 'Harga'], ['semantic_weight_pct', 'Kemiripan teks'], ['data_quality_weight_pct', 'Kualitas data'],
];

async function api(path: string, init?: RequestInit) {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || 'Permintaan gagal. Silakan coba lagi.');
  }
  return response;
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let value = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') { value += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === ',' && !quoted) {
      row.push(value.trim()); value = '';
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && text[index + 1] === '\n') index += 1;
      row.push(value.trim());
      if (row.some(Boolean)) rows.push(row);
      row = []; value = '';
    } else value += char;
  }
  row.push(value.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}

function prepareCsv(fileName: string, text: string): CsvPreview {
  let grid = parseCsv(text);
  const headerWords = new Set(['alias', 'istilah', 'sinonim', 'kolom a', 'asal', 'from']);
  if (grid[0] && headerWords.has((grid[0][0] || '').toLowerCase())) grid = grid.slice(1);
  const entries: [string, string][] = [];
  const seen = new Set<string>();
  let invalid = 0;
  let duplicates = 0;
  for (const cells of grid) {
    const alias = (cells[0] || '').trim();
    const canonical = (cells[1] || '').trim();
    if (!alias || !canonical || alias.length > 100 || canonical.length > 100) { invalid += 1; continue; }
    const key = alias.toLowerCase();
    if (seen.has(key)) { duplicates += 1; continue; }
    seen.add(key);
    entries.push([alias, canonical]);
  }
  return { fileName, rows: entries, invalid, duplicates };
}

export default function SettingsDrawer({ email, onLogout, onDataChanged }: { email: string; onLogout: () => void; onDataChanged: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [glossary, setGlossary] = useState<[string, string][]>([]);
  const [imports, setImports] = useState<ImportRow[]>([]);
  const [agentName, setAgentName] = useState('Caesar');
  const [csvPreview, setCsvPreview] = useState<CsvPreview | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [job, setJob] = useState<{ status: string; error?: string; result?: { documents: number; matches: number } } | null>(null);
  const jsonInput = useRef<HTMLInputElement>(null);
  const csvInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    Promise.all([
      api('/settings').then((response) => response.json() as Promise<Settings>),
      api('/glossary').then((response) => response.json() as Promise<Record<string, string>>),
      api('/imports').then((response) => response.json() as Promise<ImportRow[]>),
    ]).then(([nextSettings, entries, nextImports]) => {
      setSettings(Object.fromEntries(Object.entries(nextSettings).map(([key, value]) => [key, Number(value)])) as Settings);
      setGlossary(Object.entries(entries));
      setImports(nextImports);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    let stopped = false;
    const poll = () => api('/index/status').then((response) => response.json() as Promise<typeof job>).then((next) => {
      if (stopped) return;
      setJob((previous) => {
        if (previous?.status === 'processing' && next?.status === 'completed') {
          setNotice(`Selesai: ${next.result?.documents ?? 0} bubble dan ${next.result?.matches ?? 0} kecocokan diperbarui.`);
          onDataChanged();
        }
        return next;
      });
    }).catch(() => {});
    void poll();
    const timer = window.setInterval(poll, 5000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [onDataChanged]);

  const processing = job?.status === 'queued' || job?.status === 'processing';
  const weightTotal = settings ? labels.reduce((sum, [key]) => sum + Number(settings[key]), 0) : 0;

  async function uploadJson(file?: File) {
    if (!file) return;
    setBusy('Mengunggah data…'); setError(''); setNotice('');
    try {
      const form = new FormData(); form.append('file', file); form.append('agent_name', agentName.trim());
      const response = await api('/imports', { method: 'POST', body: form });
      const result = (await response.json()) as { duplicate?: boolean; agent_name?: string };
      setNotice(result.duplicate ? 'File ini sudah pernah diproses.' : `Data ${result.agent_name || agentName} masuk antrean.`);
      setImports(await (await api('/imports')).json() as ImportRow[]);
      onDataChanged();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Upload gagal'); }
    finally { setBusy(''); if (jsonInput.current) jsonInput.current.value = ''; }
  }

  async function chooseCsv(file?: File) {
    if (!file) return;
    setError('');
    try {
      const preview = prepareCsv(file.name, await file.text());
      if (!preview.rows.length) throw new Error('CSV tidak memiliki pasangan valid pada kolom A dan B.');
      setCsvPreview(preview);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'CSV tidak dapat dibaca'); }
    finally { if (csvInput.current) csvInput.current.value = ''; }
  }

  function confirmCsv() {
    if (!csvPreview) return;
    const merged = new Map(glossary.map(([alias, canonical]) => [alias.toLowerCase(), [alias, canonical] as [string, string]]));
    csvPreview.rows.forEach(([alias, canonical]) => merged.set(alias.toLowerCase(), [alias, canonical]));
    setGlossary([...merged.values()]);
    setDirty(true);
    setNotice(`${csvPreview.rows.length} istilah dari ${csvPreview.fileName} masuk ke formulir glosarium.`);
    setCsvPreview(null);
  }

  async function saveAndRecompute() {
    if (!settings) return;
    setError(''); setNotice('');
    if (Math.abs(weightTotal - 100) > 0.001) { setError('Total bobot pencocokan harus tepat 100%.'); return; }
    const entries: Record<string, string> = {};
    for (const [alias, canonical] of glossary) {
      const key = alias.trim().toLowerCase();
      if (!key || !canonical.trim()) { setError('Lengkapi setiap pasangan glosarium sebelum menyimpan.'); return; }
      if (entries[key]) { setError(`Istilah duplikat: ${alias}`); return; }
      entries[key] = canonical.trim();
    }
    setBusy('Menyimpan…');
    try {
      await api('/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) });
      await api('/glossary', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ entries }) });
      const nextJob = await (await api('/index/recompute', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).json() as typeof job;
      setJob(nextJob); setDirty(false); setNotice('Pengaturan tersimpan. Proses ulang berjalan di latar belakang.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Pengaturan gagal disimpan'); }
    finally { setBusy(''); }
  }

  return <>
    <Sheet>
      <SheetTrigger render={<Button variant="outline" size="icon" aria-label="Buka pengaturan" />}><Settings2 className="size-4" /></SheetTrigger>
      <SheetContent className="w-full sm:max-w-[520px]">
        <SheetHeader className="border-b border-slate-200 px-5 py-4"><SheetTitle>Pengaturan</SheetTitle><SheetDescription>Tersimpan untuk akun {email}</SheetDescription></SheetHeader>
        <Tabs defaultValue="matching" className="min-h-0 flex-1 overflow-hidden px-5 pb-5">
          <TabsList className="mt-1 grid w-full grid-cols-3"><TabsTrigger value="matching">Pencocokan</TabsTrigger><TabsTrigger value="source">Sumber data</TabsTrigger><TabsTrigger value="account">Akun</TabsTrigger></TabsList>
          <TabsContent value="matching" className="mt-5 max-h-[calc(100vh-150px)] space-y-6 overflow-y-auto pr-1">
            {!settings ? <p className="text-sm text-slate-500">Memuat pengaturan…</p> : <>
              <section><h3 className="text-sm font-semibold">Toleransi requirement</h3><p className="mt-1 text-[13px] leading-5 text-slate-500">Rentang yang masih dianggap mendekati kebutuhan buyer.</p><div className="mt-3 grid grid-cols-3 gap-3">{([['land_tolerance_pct', 'LT'], ['building_tolerance_pct', 'LB'], ['price_tolerance_pct', 'Harga']] as const).map(([key, label]) => <label key={key} className="text-[13px] font-medium text-slate-600">{label} (%)<input type="number" min="0" max="100" className={`${fieldClass} mt-1`} value={settings[key]} disabled={processing} onChange={(event) => { setSettings({ ...settings, [key]: Number(event.target.value) }); setDirty(true); }} /></label>)}</div></section>
              <section><div className="flex items-end justify-between"><div><h3 className="text-sm font-semibold">Bobot score</h3><p className="mt-1 text-[13px] text-slate-500">Atur pengaruh tiap faktor.</p></div><Badge className={weightTotal === 100 ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}>Total {weightTotal}%</Badge></div><div className="mt-3 grid grid-cols-2 gap-3">{labels.map(([key, label]) => <label key={key} className="text-[13px] font-medium text-slate-600">{label} (%)<input type="number" min="0" max="100" className={`${fieldClass} mt-1`} value={settings[key]} disabled={processing} onChange={(event) => { setSettings({ ...settings, [key]: Number(event.target.value) }); setDirty(true); }} /></label>)}</div></section>
              <section><div className="flex items-center justify-between"><div><h3 className="text-sm font-semibold">Glosarium</h3><p className="mt-1 text-[13px] text-slate-500">Kolom kiri dibakukan menjadi istilah di kanan.</p></div><input ref={csvInput} type="file" accept=".csv,text/csv" className="hidden" onChange={(event) => void chooseCsv(event.target.files?.[0])} /><Button variant="outline" size="sm" disabled={processing} onClick={() => csvInput.current?.click()}><FileSpreadsheet className="size-4" />Upload CSV</Button></div>
                <div className="mt-3 max-h-72 space-y-2 overflow-y-auto rounded-xl bg-slate-50 p-2">{glossary.map(([alias, canonical], index) => <div key={`${index}-${alias}`} className="grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2"><input aria-label={`Istilah ${index + 1}`} className={fieldClass} value={alias} onChange={(event) => { setGlossary(glossary.map((entry, current) => current === index ? [event.target.value, entry[1]] : entry)); setDirty(true); }} /><span className="text-slate-400">→</span><input aria-label={`Nama baku ${index + 1}`} className={fieldClass} value={canonical} onChange={(event) => { setGlossary(glossary.map((entry, current) => current === index ? [entry[0], event.target.value] : entry)); setDirty(true); }} /><Button variant="ghost" size="sm" onClick={() => { setGlossary(glossary.filter((_, current) => current !== index)); setDirty(true); }}>Hapus</Button></div>)}</div>
                <Button className="mt-2" variant="outline" size="sm" onClick={() => { setGlossary([...glossary, ['', '']]); setDirty(true); }}>Tambah istilah</Button>
              </section>
              {processing && <output className="block rounded-xl bg-blue-50 p-3 text-[13px] text-blue-700"><RefreshCw className="mr-2 inline size-3.5 animate-spin" />{job?.status === 'queued' ? 'Menunggu antrean' : 'Memproses ulang seluruh data'}…</output>}
              {job?.status === 'failed' && <p className="rounded-xl bg-red-50 p-3 text-[13px] text-red-700">Proses ulang gagal: {job.error}</p>}
              {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-[13px] text-red-700">{error}</p>}
              {notice && <output className="block rounded-xl bg-emerald-50 p-3 text-[13px] text-emerald-700">{notice}</output>}
              <Button className="w-full" disabled={!dirty || !!busy || processing} onClick={saveAndRecompute}>{busy || (dirty ? 'Simpan & proses ulang pencocokan' : 'Pengaturan sudah tersimpan')}</Button>
            </>}
          </TabsContent>
          <TabsContent value="source" className="mt-5 space-y-5">
            <section className="rounded-xl border border-slate-200 p-4"><h3 className="text-sm font-semibold">Upload percakapan</h3><p className="mt-1 text-[13px] leading-5 text-slate-500">Tambahkan cleaned.json atas nama agent pemilik data.</p><label className="mt-4 block text-[13px] font-medium text-slate-600">Nama agent<input className={`${fieldClass} mt-1`} value={agentName} onChange={(event) => setAgentName(event.target.value)} /></label><input ref={jsonInput} type="file" accept=".json,application/json" className="hidden" onChange={(event) => void uploadJson(event.target.files?.[0])} /><Button className="mt-3 w-full" disabled={!agentName.trim() || !!busy} onClick={() => jsonInput.current?.click()}>{busy ? <RefreshCw className="size-4 animate-spin" /> : <UploadCloud className="size-4" />}{busy || 'Pilih cleaned.json'}</Button></section>
            <section><h3 className="text-sm font-semibold">Upload terakhir</h3><div className="mt-2 space-y-2">{imports.slice(0, 6).map((item) => <div key={item.id} className="flex items-center gap-3 rounded-xl border border-slate-200 p-3"><FileJson className="size-4 text-blue-700" /><div className="min-w-0 flex-1"><p className="truncate text-[13px] font-semibold">{item.file_name}</p><p className="text-xs text-slate-500">{item.agent_name} · {new Date(item.created_at).toLocaleDateString('id-ID')}</p></div><Badge variant="outline">{item.status}</Badge></div>)}</div></section>
            {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-[13px] text-red-700">{error}</p>}{notice && <output className="block rounded-xl bg-emerald-50 p-3 text-[13px] text-emerald-700">{notice}</output>}
          </TabsContent>
          <TabsContent value="account" className="mt-5"><div className="rounded-xl border border-slate-200 p-4"><p className="text-sm font-semibold">{email}</p><p className="mt-1 text-[13px] text-slate-500">Sesi login berlaku selama 7 hari pada perangkat ini.</p><Button variant="outline" className="mt-5 w-full text-red-700" onClick={onLogout}><LogOut className="size-4" />Keluar</Button></div></TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>

    <Dialog open={Boolean(csvPreview)} onOpenChange={(open) => { if (!open) setCsvPreview(null); }}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader><DialogTitle>Preview glosarium CSV</DialogTitle><DialogDescription>Kolom A akan menjadi istilah asal dan kolom B menjadi nama baku. Konfirmasi untuk memasukkannya ke formulir.</DialogDescription></DialogHeader>
        {csvPreview && <><div className="flex flex-wrap gap-2 text-xs"><Badge variant="outline">{csvPreview.fileName}</Badge><Badge className="bg-emerald-50 text-emerald-700">{csvPreview.rows.length} valid</Badge>{csvPreview.invalid > 0 && <Badge className="bg-red-50 text-red-700">{csvPreview.invalid} dilewati</Badge>}{csvPreview.duplicates > 0 && <Badge className="bg-amber-50 text-amber-700">{csvPreview.duplicates} duplikat</Badge>}</div><div className="max-h-80 overflow-y-auto rounded-xl border border-slate-200"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-slate-50 text-xs text-slate-500"><tr><th className="px-3 py-2">Kolom A · Istilah</th><th className="px-3 py-2">Kolom B · Nama baku</th></tr></thead><tbody>{csvPreview.rows.map(([alias, canonical], index) => <tr key={`${alias}-${index}`} className="border-t border-slate-100"><td className="px-3 py-2">{alias}</td><td className="px-3 py-2 font-medium">{canonical}</td></tr>)}</tbody></table></div></>}
        <DialogFooter><Button variant="outline" onClick={() => setCsvPreview(null)}>Batal</Button><Button onClick={confirmCsv}><FileSpreadsheet className="size-4" />Masukkan ke glosarium</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
