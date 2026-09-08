'use client';

import { ArrowLeft, ArrowRight, CalendarDays, ChevronDown, Download, ExternalLink, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';

type Direction = 'buyer' | 'property';
type Status = 'hot' | 'warm' | 'unmatched';
type Row = {
  id: string; raw_text: string; normalized_text: string; contact_name?: string; contact_phone?: string;
  locations: string[]; categories: string[]; land_area_min?: number; land_area_max?: number;
  building_area_min?: number; building_area_max?: number; price_min?: number; price_max?: number;
  sent_at?: string; hot_count?: number; warm_count?: number; match_count?: number; score?: number;
  explanation?: string[];
};
type Group = { source: Row; recommendations: Row[] };

const pageSize = 200;
const fieldClass = 'h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none transition focus:border-blue-500 focus:ring-3 focus:ring-blue-100';

async function api(path: string, init?: RequestInit) {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || 'Permintaan gagal. Silakan coba lagi.');
  }
  return response;
}

function money(value?: number) {
  return value ? new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0, notation: 'compact' }).format(value) : null;
}

function area(min?: number, max?: number) {
  if (!min && !max) return null;
  const low = min ?? max;
  return `${low}${max && low !== max ? `–${max}` : ''} m²`;
}

function relativeDate(value?: string) {
  if (!value) return 'tanggal tidak tersedia';
  const days = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000));
  if (days === 0) return 'hari ini';
  if (days === 1) return 'kemarin';
  if (days < 7) return `${days} hari lalu`;
  if (days < 30) return `${Math.floor(days / 7)} minggu lalu`;
  return `${Math.floor(days / 30)} bulan lalu`;
}

function structuredSummary(row: Row) {
  return [
    row.categories?.join(', '), row.locations?.join(' / '),
    area(row.land_area_min, row.land_area_max) && `LT ${area(row.land_area_min, row.land_area_max)}`,
    area(row.building_area_min, row.building_area_max) && `LB ${area(row.building_area_min, row.building_area_max)}`,
    money(row.price_max ?? row.price_min),
  ].filter(Boolean).join(' · ');
}

function RawChat({ text }: { text: string }) {
  return <details className="group/chat mt-2">
    <summary className="flex cursor-pointer list-none items-center gap-1 text-[13px] font-semibold text-blue-700">
      Baca selengkapnya <ChevronDown className="size-3.5 transition group-open/chat:rotate-180" />
    </summary>
    <p className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-[13px] leading-5 text-slate-600">{text}</p>
  </details>;
}

function ContactButton({ row, label }: { row: Row; label: string }) {
  const phone = (row.contact_phone || '').replace(/\D/g, '').replace(/^0/, '62');
  if (!phone) return null;
  return <a href={`https://wa.me/${phone}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-emerald-700 hover:underline">
    {label} <ExternalLink className="size-3.5" />
  </a>;
}

export default function MatchWorkspace() {
  const [direction, setDirection] = useState<Direction>('buyer');
  const [statuses, setStatuses] = useState<Status[]>(['hot', 'warm', 'unmatched']);
  const [search, setSearch] = useState('');
  const [phones, setPhones] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [rows, setRows] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [exports, setExports] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [matching, setMatching] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const preferencesReady = useRef(false);
  const sourceLabel = direction === 'buyer' ? 'buyer' : 'property';
  const targetLabel = direction === 'buyer' ? 'property' : 'buyer';

  useEffect(() => {
    void api('/preferences')
      .then((response) => response.json() as Promise<{ direction: Direction; statuses: Status[] }>)
      .then((preferences) => {
        setDirection(preferences.direction);
        setStatuses(preferences.statuses.length ? preferences.statuses : ['hot', 'warm', 'unmatched']);
      })
      .finally(() => { preferencesReady.current = true; });
  }, []);

  useEffect(() => {
    if (!preferencesReady.current) return;
    const timer = window.setTimeout(() => {
      void api('/preferences', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ direction, statuses }) }).catch(() => {});
    }, 400);
    return () => window.clearTimeout(timer);
  }, [direction, statuses]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      const params = new URLSearchParams({ direction, search, phones, statuses: statuses.join(','), date_from: from, date_to: to, offset: String(offset) });
      api(`/workspace?${params}`, { signal: controller.signal })
        .then((response) => response.json() as Promise<{ rows: Row[]; has_more: boolean }>)
        .then((data) => { setRows(data.rows); setMore(data.has_more); setError(''); })
        .catch((reason: Error) => { if (reason.name !== 'AbortError') setError(reason.message); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [direction, search, phones, statuses, from, to, offset]);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) { setGroups([]); setExports([]); setMatching(selected.length > 0); }
    });
    if (!selected.length) return () => controller.abort();
    api('/workspace/recommendations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction, ids: selected }), signal: controller.signal,
    })
      .then((response) => response.json() as Promise<{ groups: Group[] }>)
      .then((data) => setGroups(data.groups))
      .catch((reason: Error) => { if (reason.name !== 'AbortError') setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setMatching(false); });
    return () => controller.abort();
  }, [direction, selected]);

  const visibleGroups = useMemo(() => groups.map((group) => ({
    ...group,
    unmatched: group.recommendations.length === 0,
    recommendations: group.recommendations.filter((row) => statuses.includes(Number(row.score) >= 80 ? 'hot' : 'warm')),
  })).filter((group) => group.recommendations.length || (group.unmatched && statuses.includes('unmatched'))), [groups, statuses]);
  const keyFor = (source: Row, target?: Row) => `${source.id}:${target?.id || ''}`;
  const visibleKeys = visibleGroups.flatMap((group) => group.unmatched ? [keyFor(group.source)] : group.recommendations.map((target) => keyFor(group.source, target)));
  const exportCount = exports.filter((key) => visibleKeys.includes(key)).length;

  function resetSelection() { setOffset(0); setSelected([]); setGroups([]); setExports([]); }
  function changeDirection(next: Direction) { resetSelection(); setSearch(''); setPhones(''); setDirection(next); }
  function toggleStatus(status: Status) {
    resetSelection();
    setStatuses((current) => current.includes(status) ? current.filter((item) => item !== status) : [...current, status]);
  }

  async function exportPdf() {
    setExporting(true);
    try {
      const pairs = exports.filter((key) => visibleKeys.includes(key)).map((key) => {
        const [source_id, target_id] = key.split(':');
        return { source_id, target_id: target_id || null };
      });
      const response = await api('/export/pdf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ direction, pairs }) });
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'XM-Matching-Report.pdf'; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Export PDF gagal');
    } finally { setExporting(false); }
  }

  return <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_12px_34px_rgba(15,23,42,.05)]">
    <div className="flex flex-col gap-4 border-b border-slate-200 p-4 lg:flex-row lg:items-center lg:justify-between">
      <div><h1 className="text-xl font-semibold tracking-[-.025em]">Pencocokan buyer & property</h1><p className="mt-1 text-sm text-slate-500">Pilih {sourceLabel} di kiri, lalu bandingkan hasilnya di kanan.</p></div>
      <div className="flex w-full rounded-xl bg-slate-100 p-1 lg:w-auto">
        <Button className="flex-1 lg:flex-none" variant={direction === 'buyer' ? 'default' : 'ghost'} onClick={() => changeDirection('buyer')}>Buyer → Property</Button>
        <Button className="flex-1 lg:flex-none" variant={direction === 'property' ? 'default' : 'ghost'} onClick={() => changeDirection('property')}>Property → Buyer</Button>
      </div>
    </div>

    <div className="flex flex-wrap items-end gap-3 border-b border-slate-200 bg-slate-50/60 p-4">
      <label className="min-w-56 flex-1 text-[13px] font-medium text-slate-600">Cari {sourceLabel}
        <span className="relative mt-1 block"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" /><input className={`${fieldClass} w-full pl-9`} value={search} onChange={(event) => { resetSelection(); setSearch(event.target.value); }} placeholder="Nama, lokasi, atau kategori…" /></span>
      </label>
      {direction === 'property' && <label className="min-w-64 flex-1 text-[13px] font-medium text-slate-600">Nomor kontak listing<input className={`${fieldClass} mt-1 w-full`} value={phones} onChange={(event) => { resetSelection(); setPhones(event.target.value); }} placeholder="Pisahkan beberapa nomor dengan koma" /></label>}
      <div className="flex items-end gap-2"><CalendarDays className="mb-3 size-4 text-slate-400" />
        <label className="text-[13px] font-medium text-slate-600">Dari<input type="date" className={`${fieldClass} mt-1 block`} value={from} max={to || undefined} onChange={(event) => { resetSelection(); setFrom(event.target.value); }} /></label>
        <label className="text-[13px] font-medium text-slate-600">Sampai<input type="date" className={`${fieldClass} mt-1 block`} value={to} min={from || undefined} onChange={(event) => { resetSelection(); setTo(event.target.value); }} /></label>
      </div>
      <div className="flex flex-wrap gap-2">
        {([['hot', 'Hot', 'bg-rose-500'], ['warm', 'Warm', 'bg-amber-500'], ['unmatched', 'Belum cocok', 'bg-slate-400']] as const).map(([status, label, dot]) => <button key={status} type="button" aria-pressed={statuses.includes(status)} className={`inline-flex h-10 items-center gap-2 rounded-xl border px-3 text-[13px] font-semibold transition ${statuses.includes(status) ? 'border-blue-200 bg-blue-50 text-blue-800' : 'border-slate-200 bg-white text-slate-500'}`} onClick={() => toggleStatus(status)}><span className={`size-2 rounded-full ${dot}`} />{label}</button>)}
      </div>
      <Button className="ml-auto" disabled={!exportCount || exporting} onClick={exportPdf}><Download className="size-4" />{exporting ? 'Menyiapkan…' : `Export PDF (${exportCount})`}</Button>
    </div>
    {error && <div role="alert" className="border-b border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

    <div className="grid min-h-[640px] xl:grid-cols-[minmax(340px,42%)_1fr]">
      <div className="border-b border-slate-200 xl:border-r xl:border-b-0">
        <div className="flex h-14 items-center justify-between border-b border-slate-200 px-4"><p className="text-sm font-semibold capitalize">{sourceLabel} <span className="font-normal text-slate-400">· {selected.length} dipilih · maks. 50</span></p><button className="text-[13px] font-semibold text-blue-700" onClick={() => setSelected(selected.length ? [] : rows.slice(0, 50).map((row) => row.id))}>{selected.length ? 'Bersihkan' : 'Pilih semua'}</button></div>
        <div className="max-h-[640px] overflow-y-auto p-2">
          {loading && <p className="p-6 text-sm text-slate-500">Memuat data…</p>}
          {!loading && rows.map((row) => {
            const checked = selected.includes(row.id);
            return <article key={row.id} className={`mb-1.5 rounded-xl border p-3.5 transition ${checked ? 'border-blue-300 bg-blue-50/70' : 'border-transparent hover:border-slate-200 hover:bg-slate-50'}`}>
              <div className="flex items-start gap-3"><Checkbox id={`source-${row.id}`} checked={checked} onCheckedChange={() => setSelected((current) => current.includes(row.id) ? current.filter((id) => id !== row.id) : current.length < 50 ? [...current, row.id] : current)} />
                <div className="min-w-0 flex-1"><label htmlFor={`source-${row.id}`} className="flex cursor-pointer items-start justify-between gap-3"><span className="break-words text-sm font-semibold text-slate-900">{row.contact_name || `${sourceLabel} tanpa nama`}</span><span className="shrink-0 text-[11px] text-slate-400">{relativeDate(row.sent_at)}</span></label>
                  <p className="mt-1 line-clamp-2 text-[13px] leading-5 text-slate-600">{structuredSummary(row) || row.raw_text}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">{Number(row.hot_count) > 0 && <Badge className="bg-rose-50 text-rose-700 hover:bg-rose-50">{row.hot_count} Hot</Badge>}{Number(row.warm_count) > 0 && <Badge className="bg-amber-50 text-amber-700 hover:bg-amber-50">{row.warm_count} Warm</Badge>}{Number(row.match_count) === 0 && <Badge className="bg-slate-100 text-slate-600 hover:bg-slate-100">Belum cocok</Badge>}</div>
                  <RawChat text={row.raw_text || row.normalized_text} />
                </div>
              </div>
            </article>;
          })}
          {!loading && !rows.length && <p className="p-8 text-center text-sm text-slate-500">Tidak ada data untuk filter ini.</p>}
        </div>
        <div className="flex h-14 items-center justify-between border-t border-slate-200 px-4 text-[13px] text-slate-500"><span>Menampilkan {rows.length ? offset + 1 : 0}–{offset + rows.length}</span><div className="flex gap-1"><Button size="icon-sm" variant="outline" aria-label="Halaman sebelumnya" disabled={!offset || loading} onClick={() => setOffset(Math.max(0, offset - pageSize))}><ArrowLeft className="size-4" /></Button><Button size="icon-sm" variant="outline" aria-label="Halaman berikutnya" disabled={!more || loading} onClick={() => setOffset(offset + pageSize)}><ArrowRight className="size-4" /></Button></div></div>
      </div>

      <div>
        <div className="flex h-14 items-center justify-between border-b border-slate-200 px-4"><p className="text-sm font-semibold capitalize">Rekomendasi {targetLabel}</p>{!!visibleKeys.length && <button className="text-[13px] font-semibold text-blue-700" onClick={() => setExports(exportCount === visibleKeys.length ? [] : visibleKeys.slice(0, 200))}>{exportCount === visibleKeys.length ? 'Batal tandai' : 'Tandai semua hasil'}</button>}</div>
        <div className="max-h-[694px] overflow-y-auto p-3 sm:p-4">
          {matching && <p className="p-8 text-center text-sm text-slate-500">Mencocokkan data…</p>}
          {!matching && !selected.length && <div className="flex min-h-80 flex-col items-center justify-center text-center"><div className="mb-3 flex size-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-700"><ArrowRight className="size-5" /></div><p className="font-semibold">Pilih {sourceLabel} di sebelah kiri</p><p className="mt-1 max-w-sm text-sm leading-6 text-slate-500">Hasil Hot, Warm, atau Belum cocok akan langsung muncul di sini.</p></div>}
          {!matching && selected.length > 0 && !visibleGroups.length && <p className="p-8 text-center text-sm text-slate-500">Tidak ada hasil untuk status yang dipilih.</p>}
          <div className="space-y-4">{visibleGroups.map((group) => <section key={group.source.id} className="rounded-xl border border-slate-200">
            <div className="border-b border-slate-200 bg-slate-50 px-4 py-3"><p className="text-[13px] text-slate-500">Untuk</p><p className="text-sm font-semibold">{group.source.contact_name || structuredSummary(group.source)}</p></div>
            <div className="space-y-2 p-3">{group.unmatched ? <div className="flex items-center gap-3 rounded-lg bg-slate-50 p-4 text-sm text-slate-600"><Checkbox aria-label="Tandai status belum cocok untuk PDF" checked={exports.includes(keyFor(group.source))} onCheckedChange={() => setExports((current) => current.includes(keyFor(group.source)) ? current.filter((key) => key !== keyFor(group.source)) : [...current, keyFor(group.source)])} />Belum ada pasangan yang lolos batas pencocokan</div> : group.recommendations.map((target) => {
              const key = keyFor(group.source, target); const hot = Number(target.score) >= 80;
              return <article key={target.id} className="rounded-xl border border-slate-200 p-3.5"><div className="flex items-start gap-3"><Checkbox checked={exports.includes(key)} onCheckedChange={() => setExports((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])} />
                <div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold">{target.contact_name || structuredSummary(target)}</p><p className="mt-1 text-[13px] leading-5 text-slate-600">{structuredSummary(target)}</p></div><Badge className={hot ? 'bg-rose-50 text-rose-700 hover:bg-rose-50' : 'bg-amber-50 text-amber-700 hover:bg-amber-50'}>{hot ? 'Hot' : 'Warm'} · {Math.round(Number(target.score))}%</Badge></div>
                  <div className="mt-2 flex flex-wrap gap-1.5">{target.explanation?.slice(0, 4).map((reason) => <span key={reason} className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">{reason}</span>)}</div><RawChat text={target.raw_text || target.normalized_text} /><div className="mt-3 flex flex-wrap gap-4"><ContactButton row={group.source} label={`WhatsApp ${sourceLabel}`} /><ContactButton row={target} label={`WhatsApp ${targetLabel}`} /></div>
                </div>
              </div></article>;
            })}</div>
          </section>)}</div>
        </div>
      </div>
    </div>
  </section>;
}
