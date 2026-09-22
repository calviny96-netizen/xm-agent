'use client';

import { useWorkspaceFetch } from '@/lib/workspace-context';

import { ArrowLeft, ArrowRight, ChevronDown, Download, ExternalLink, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import DateFilter, { type DateFilterValue } from '@/components/date-filter';
import { Checkbox } from '@/components/ui/checkbox';

type Direction = 'buyer' | 'property';
type Status = 'hot' | 'warm' | 'unmatched';
type Row = {
  id: string; raw_text: string; normalized_text: string; contact_name?: string; contact_phone?: string;
  locations: string[]; categories: string[]; land_area_min?: number; land_area_max?: number;
  building_area_min?: number; building_area_max?: number; price_min?: number; price_max?: number;
  sent_at?: string; last_seen_at?: string; price_basis?: string; hot_count?: number; warm_count?: number; match_count?: number; score?: number;
  explanation?: string[]; duplicate_count?: number;
};
type Group = { source: Row; recommendations: Row[] };

const pageSize = 200;
const fieldClass = 'h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none transition focus:border-blue-500 focus:ring-3 focus:ring-blue-100';


function money(value?: number) {
  return value ? new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 3, notation: 'compact' }).format(value) : null;
}

function area(min?: number, max?: number) {
  if (!min && !max) return null;
  const low = min ?? max;
  return `${low}${max && low !== max ? `–${max}` : ''} m²`;
}

function relativeDate(value?: string) {
  if (!value) return 'tanggal tidak tersedia';
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}+07:00`;
  const timestamp = new Date(zoned).getTime();
  if (Number.isNaN(timestamp)) return 'tanggal tidak tersedia';
  const wibDay = (time: number) => Math.floor((time + 7 * 3_600_000) / 86_400_000);
  const days = wibDay(Date.now()) - wibDay(timestamp);
  if (days < 0) return 'tanggal mendatang';
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
    (row.price_max ?? row.price_min) ? `${money(row.price_max ?? row.price_min)}${row.price_basis === 'per_m2' ? '/m²' : row.price_basis === 'per_year' ? '/tahun' : ''}` : null,
  ].filter(Boolean).join(' · ');
}

function LastSeen({ row }: { row: Row }) {
  const value = row.last_seen_at || row.sent_at;
  if (!value) return <p className="mt-1 text-xs text-slate-500">Waktu posting belum tersedia</p>;
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}+07:00`;
  const date = new Date(zoned);
  if (Number.isNaN(date.getTime())) return <p className="mt-1 text-xs text-slate-500">Waktu posting belum tersedia</p>;
  const full = new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Jakarta' }).format(date);
  return <p className="mt-1 text-xs text-slate-500">Terakhir diposting <time dateTime={date.toISOString()} title={`${full} WIB`}>{relativeDate(zoned)} · {full} WIB</time></p>;
}

function DuplicateBadge({ row }: { row: Row }) {
  return Number(row.duplicate_count) > 1 ? <Badge className="bg-blue-50 text-blue-700">Teks identik · {row.duplicate_count} kemunculan</Badge> : null;
}

function RawChat({ text }: { text: string }) {
  const [open,setOpen] = useState(false);
  return <details className="group/chat mt-2" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="flex cursor-pointer list-none items-center gap-1 text-[13px] font-semibold text-blue-700">
      Baca selengkapnya <ChevronDown className="size-3.5 transition group-open/chat:rotate-180" />
    </summary>
    {open && <p className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-[13px] leading-5 text-slate-600">{text}</p>}
  </details>;
}

function ContactButton({ row, label }: { row: Row; label: string }) {
  const phone = (row.contact_phone || '').replace(/\D/g, '').replace(/^0/, '62');
  if (!phone) return null;
  const message = `Halo ${row.contact_name || 'Bapak/Ibu'}, saya ingin menindaklanjuti ${label.toLowerCase().includes('buyer') ? 'kebutuhan properti' : 'listing properti'} yang Anda bagikan:\n\n${structuredSummary(row) || (row.raw_text || row.normalized_text).slice(0, 500)}\n\nApakah masih tersedia? Saya memiliki calon pasangan yang sesuai. Boleh saya meminta informasi lebih lanjut? Terima kasih.`;
  return <a href={`https://wa.me/${phone.startsWith('8') ? '62' + phone : phone}?text=${encodeURIComponent(message)}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-emerald-700 hover:underline">
    {label} <ExternalLink className="size-3.5" />
  </a>;
}

export default function MatchWorkspace({ defaultSearch }: { defaultSearch: string }) {
  const workspaceFetch = useWorkspaceFetch();
  const api = useCallback(async (path: string, init?: RequestInit) => {
    const response = await workspaceFetch(path, init);
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: string };
      throw new Error(body.detail || 'Permintaan gagal. Silakan coba lagi.');
    }
    return response;
  }, [workspaceFetch]);
  const [step, setStep] = useState<1 | 2>(1);
  const [mobileDetail, setMobileDetail] = useState(false);
  const workspaceRef = useRef<HTMLElement>(null);
  const listScroll = useRef(0);
  useEffect(() => {
    if (mobileDetail && window.matchMedia('(max-width: 1279px)').matches) {
      workspaceRef.current?.scrollIntoView({ block: 'start' });
    }
  }, [mobileDetail]);
  const [methodChosen, setMethodChosen] = useState(false);
  const [direction, setDirection] = useState<Direction>('buyer');
  const [statuses, setStatuses] = useState<Status[]>(['hot', 'warm', 'unmatched']);
  const search = defaultSearch;
  const [phones, setPhones] = useState('');
  const [dates, setDates] = useState<DateFilterValue>({ from: '', to: '', startTime: '00:00', endTime: '23:59' });
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
  const [preferencesLoaded,setPreferencesLoaded] = useState(false);
  const sourceLabel = direction === 'buyer' ? 'buyer' : 'property';
  const targetLabel = direction === 'buyer' ? 'property' : 'buyer';

  useEffect(() => {
    void api('/preferences')
      .then((response) => response.json() as Promise<{ direction: Direction; statuses: Status[] }>)
      .then((preferences) => {
        setDirection(preferences.direction);
        setStatuses(preferences.statuses.length ? preferences.statuses : ['hot', 'warm', 'unmatched']);
      })
      .catch(() => {})
      .finally(() => { preferencesReady.current = true; setPreferencesLoaded(true); });
  }, [api]);

  useEffect(() => {
    if (!preferencesReady.current) return;
    const timer = window.setTimeout(() => {
      void api('/preferences', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ direction, statuses }) }).catch(() => {});
    }, 400);
    return () => window.clearTimeout(timer);
  }, [direction, statuses, api]);

  useEffect(() => {
    if (!preferencesLoaded || step !== 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      const params = new URLSearchParams({ direction, search, phones, statuses: statuses.join(','), date_from: dates.from, date_to: dates.to, time_from: dates.startTime, time_to: dates.endTime, offset: String(offset) });
      api(`/workspace?${params}`, { signal: controller.signal })
        .then((response) => response.json() as Promise<{ rows: Row[]; has_more: boolean }>)
        .then((data) => { if (!controller.signal.aborted) { setRows(data.rows); setMore(data.has_more); setError(''); } })
        .catch((reason: Error) => { if (reason.name !== 'AbortError') setError(reason.message); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [direction, search, phones, statuses, dates, offset, preferencesLoaded, step, api]);

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
      .then((data) => { if (!controller.signal.aborted) setGroups(data.groups); })
      .catch((reason: Error) => { if (reason.name !== 'AbortError') setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setMatching(false); });
    return () => controller.abort();
  }, [direction, selected, api]);

  const visibleGroups = useMemo(() => groups.map((group) => ({
    ...group,
    unmatched: group.recommendations.length === 0,
    recommendations: group.recommendations.filter((row) => statuses.includes(Number(row.score) >= 80 ? 'hot' : 'warm')),
  })).filter((group) => group.recommendations.length || (group.unmatched && statuses.includes('unmatched'))), [groups, statuses]);
  const keyFor = (source: Row, target?: Row) => `${source.id}:${target?.id || ''}`;
  const visibleKeys = visibleGroups.flatMap((group) => group.unmatched ? [keyFor(group.source)] : group.recommendations.map((target) => keyFor(group.source, target)));
  const exportCount = exports.filter((key) => visibleKeys.includes(key)).length;

  function resetSelection() { setMobileDetail(false); setOffset(0); setSelected([]); setGroups([]); setExports([]); }
  useEffect(() => { queueMicrotask(() => { setMobileDetail(false); setOffset(0); setSelected([]); setGroups([]); setExports([]); }); }, [defaultSearch]);

  function changeDirection(next: Direction) { setMethodChosen(true); resetSelection(); setPhones(''); setDirection(next); }
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

  if (step === 1) return <section className="mx-auto max-w-3xl overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_20px_60px_rgba(15,23,42,.07)]">
    <div className="bg-[#081735] p-6 text-white sm:p-8"><p className="text-xs font-semibold uppercase tracking-[.18em] text-cyan-300">Langkah 1 dari 2 · Persiapan</p><h1 className="mt-3 text-3xl font-semibold tracking-tight">Mulai pencocokan Anda</h1><p className="mt-3 text-sm leading-6 text-blue-100">Tentukan periode posting dan arah pencocokan untuk menemukan pasangan yang relevan.</p></div>
    <div className="space-y-7 p-6 sm:p-8"><fieldset><legend className="text-base font-semibold">1. Pilih metode pencocokan</legend><div className="mt-3 grid gap-3 sm:grid-cols-2">{(['buyer', 'property'] as const).map(method => <button type="button" disabled={!preferencesLoaded} key={method} aria-pressed={methodChosen && direction === method} onClick={() => changeDirection(method)} className={`rounded-2xl border p-5 text-left transition ${methodChosen && direction === method ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-100' : 'border-slate-200 hover:border-blue-300'}`}><span className="block font-semibold">{method === 'buyer' ? 'Buyer → Property' : 'Property → Buyer'}</span><span className="mt-2 block text-sm leading-6 text-slate-500">{method === 'buyer' ? 'Cari listing yang sesuai kebutuhan buyer.' : 'Temukan buyer untuk listing property.'}</span></button>)}</div></fieldset>
    <div><h2 className="mb-3 text-base font-semibold">2. Pilih periode posting</h2><DateFilter value={dates} direction={direction} onChange={setDates} /></div>
    <div className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-100 pt-5"><p className="text-sm text-slate-500">Pencarian default: <strong className="text-slate-700">{defaultSearch.split('\n').join(' · ')}</strong></p><Button className="h-11" disabled={!preferencesLoaded || !methodChosen || Boolean(dates.from && (!dates.to || `${dates.from}T${dates.startTime}` > `${dates.to}T${dates.endTime}`))} onClick={() => setStep(2)}>Lanjut ke pencocokan<ArrowRight className="size-4" /></Button></div></div>
  </section>;

  return <section ref={workspaceRef} className="scroll-mt-20 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_12px_34px_rgba(15,23,42,.05)]">
    <div className="flex flex-col gap-4 border-b border-slate-200 p-4 lg:flex-row lg:items-center lg:justify-between">
      <div><h1 className="text-xl font-semibold tracking-[-.025em]">Pencocokan buyer & property</h1><p className="mt-1 text-xs font-semibold text-blue-700">Langkah 2 dari 2 · {direction === 'buyer' ? 'Buyer → Property' : 'Property → Buyer'} · {dates.from ? `${dates.from} — ${dates.to}` : 'Semua tanggal'}</p><p className="mt-1 text-sm text-slate-500">Pilih satu {sourceLabel} untuk membuka rekomendasi yang cocok.</p></div>
      <Button variant="outline" onClick={() => { resetSelection(); setStep(1); }}><ArrowLeft className="size-4" />Ubah tanggal & metode</Button>
    </div>

    <div className={`flex-wrap items-end gap-3 border-b border-slate-200 bg-slate-50/60 p-4 ${mobileDetail ? 'hidden xl:flex' : 'flex'}`}>
      <label className="min-w-0 basis-full sm:basis-auto sm:min-w-56 flex-1 text-[13px] font-medium text-slate-600">Cari {sourceLabel}
        <span className="relative mt-1 block"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" /><input className={`${fieldClass} w-full pl-9`} value={search.split('\n').join(' · ')} readOnly aria-label={`Cari ${sourceLabel}`} title="Default pencarian dikelola oleh admin" /></span>
      </label>
      {direction === 'property' && <label className="min-w-0 basis-full sm:basis-auto sm:min-w-64 flex-1 text-[13px] font-medium text-slate-600">Nomor kontak listing<input className={`${fieldClass} mt-1 w-full`} value={phones} onChange={(event) => { resetSelection(); setPhones(event.target.value); }} placeholder="Pisahkan beberapa nomor dengan koma" /></label>}
      <span className="text-xs text-slate-500">Pencarian diatur oleh admin.</span>
      <div className="flex flex-wrap gap-2">
        {([['hot', '🔥 Hot', 'bg-rose-500'], ['warm', '🌡️ Warm', 'bg-amber-500'], ['unmatched', 'Belum cocok', 'bg-slate-400']] as const).map(([status, label, dot]) => <button key={status} type="button" aria-pressed={statuses.includes(status)} className={`inline-flex h-10 items-center gap-2 rounded-xl border px-3 text-[13px] font-semibold transition ${statuses.includes(status) ? 'border-blue-200 bg-blue-50 text-blue-800' : 'border-slate-200 bg-white text-slate-500'}`} onClick={() => toggleStatus(status)}><span className={`size-2 rounded-full ${dot}`} />{label}</button>)}
      </div>
      <Button className="ml-auto" disabled={!exportCount || exporting} onClick={exportPdf}><Download className="size-4" />{exporting ? 'Menyiapkan…' : `Export PDF (${exportCount})`}</Button>
    </div>
    {error && <div role="alert" className="border-b border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

    <div className="grid min-h-[480px] xl:min-h-[640px] xl:grid-cols-[minmax(340px,42%)_1fr]">
      <div className={`min-w-0 border-b border-slate-200 xl:border-r xl:border-b-0 ${mobileDetail ? 'hidden xl:block' : 'block'}`}>
        <div className="flex h-14 items-center justify-between border-b border-slate-200 px-4"><p className="text-sm font-semibold capitalize">{sourceLabel} <span className="font-normal text-slate-400">· {selected.length} aktif · pilih satu</span></p><button className="text-[13px] font-semibold text-blue-700" disabled={!selected.length} onClick={() => { setSelected([]); setMobileDetail(false); }}>Nonaktifkan</button></div>
        <div className="space-y-2 p-2 xl:max-h-[640px] xl:overflow-y-auto">
          {loading && <p className="p-6 text-sm text-slate-500">Memuat data…</p>}
          {!loading && rows.map((row) => {
            const checked = selected.includes(row.id);
            return <article key={row.id} style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 180px' }} className={`relative mb-1.5 rounded-xl border p-3.5 transition ${Number(row.hot_count) > 0 ? 'hot-match' : ''} ${checked ? 'border-blue-300 bg-blue-50/70' : 'border-transparent hover:border-slate-200 hover:bg-slate-50'}`}>
              <div className="flex items-start gap-3"><div aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-full bg-blue-100 font-semibold text-blue-700">{(row.contact_name || sourceLabel).slice(0, 1).toUpperCase()}</div>
                <div className="min-w-0 flex-1"><button type="button" aria-pressed={checked} aria-label={`Lihat rekomendasi ${row.contact_name || sourceLabel}`} onClick={() => { listScroll.current = window.scrollY; setSelected([row.id]); setMobileDetail(true); }} className="block w-full text-left after:absolute after:inset-0 after:rounded-xl"><span className="flex items-start justify-between gap-3"><span className="break-words text-sm font-semibold text-slate-900">{row.contact_name || `${sourceLabel} tanpa nama`}</span><span className="shrink-0 text-[11px] text-slate-400">{relativeDate(row.sent_at)}</span></span></button>
                  <p className="mt-1 line-clamp-2 text-[13px] leading-5 text-slate-600">{structuredSummary(row) || row.raw_text}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">{Number(row.hot_count) > 0 && <Badge className="bg-rose-50 text-rose-700 hover:bg-rose-50">🔥 Hot · {row.hot_count}</Badge>}{Number(row.warm_count) > 0 && <Badge className="bg-amber-50 text-amber-700 hover:bg-amber-50">🌡️ Warm · {row.warm_count}</Badge>}{Number(row.match_count) === 0 && <Badge className="bg-slate-100 text-slate-600 hover:bg-slate-100">Belum cocok</Badge>}</div>
                  <DuplicateBadge row={row} /><div className="relative z-10 w-fit"><RawChat text={row.raw_text || row.normalized_text} /></div>
                </div>
              </div>
            </article>;
          })}
          {!loading && !rows.length && <p className="p-8 text-center text-sm text-slate-500">Tidak ada data untuk filter ini.</p>}
        </div>
        <div className="flex h-14 items-center justify-between border-t border-slate-200 px-4 text-[13px] text-slate-500"><span>Menampilkan {rows.length ? offset + 1 : 0}–{offset + rows.length}</span><div className="flex gap-1"><Button size="icon-sm" variant="outline" aria-label="Halaman sebelumnya" disabled={!offset || loading} onClick={() => { setSelected([]); setGroups([]); setOffset(Math.max(0, offset - pageSize)); }}><ArrowLeft className="size-4" /></Button><Button size="icon-sm" variant="outline" aria-label="Halaman berikutnya" disabled={!more || loading} onClick={() => { setSelected([]); setGroups([]); setOffset(offset + pageSize); }}><ArrowRight className="size-4" /></Button></div></div>
      </div>

      <div className={`min-w-0 bg-[#f0f5f4] ${mobileDetail ? 'block' : 'hidden xl:block'}`}>
        <div className="sticky top-[68px] z-20 flex min-h-16 flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-3"><div className="flex items-center gap-2"><Button variant="ghost" size="icon" className="xl:hidden" aria-label="Kembali ke daftar" onClick={() => { setMobileDetail(false); window.requestAnimationFrame(() => window.scrollTo({ top: listScroll.current })); }}><ArrowLeft className="size-5" /></Button><p className="text-sm font-semibold capitalize">Rekomendasi {targetLabel}</p></div>{!!visibleKeys.length && <button className="text-[13px] font-semibold text-blue-700" onClick={() => setExports(exportCount === visibleKeys.length ? [] : visibleKeys.slice(0, 200))}>{exportCount === visibleKeys.length ? 'Batal tandai' : 'Tandai semua hasil'}</button>}</div>
        {mobileDetail && <div className="flex justify-end px-4 pt-3 xl:hidden"><Button size="sm" disabled={!exportCount || exporting} onClick={exportPdf}><Download className="size-4" />{exporting ? 'Menyiapkan…' : `Export PDF (${exportCount})`}</Button></div>}
        <div className="p-3 sm:p-4 xl:max-h-[694px] xl:overflow-y-auto">
          {matching && <p className="p-8 text-center text-sm text-slate-500">Mencocokkan data…</p>}
          {!matching && !selected.length && <div className="flex min-h-80 flex-col items-center justify-center text-center"><div className="mb-3 flex size-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-700"><ArrowRight className="size-5" /></div><p className="font-semibold">Pilih {sourceLabel} di sebelah kiri</p><p className="mt-1 max-w-sm text-sm leading-6 text-slate-500">Hasil Hot, Warm, atau Belum cocok akan langsung muncul di sini.</p></div>}
          {!matching && selected.length > 0 && !visibleGroups.length && <p className="p-8 text-center text-sm text-slate-500">Tidak ada hasil untuk status yang dipilih.</p>}
          <div className="space-y-4">{visibleGroups.map((group) => <section key={group.source.id} className="rounded-xl border border-slate-200 bg-white">
            <div className="border-b border-slate-200 bg-slate-50 px-4 py-3"><p className="text-[13px] text-slate-500">Untuk</p><p className="text-sm font-semibold">{group.source.contact_name || structuredSummary(group.source)}</p></div>
            <div className="space-y-2 p-3">{group.unmatched ? <div className="flex items-center gap-3 rounded-lg bg-slate-50 p-4 text-sm text-slate-600"><Checkbox aria-label="Tandai status belum cocok untuk PDF" checked={exports.includes(keyFor(group.source))} onCheckedChange={() => setExports((current) => current.includes(keyFor(group.source)) ? current.filter((key) => key !== keyFor(group.source)) : [...current, keyFor(group.source)])} />Belum ada pasangan yang lolos batas pencocokan</div> : group.recommendations.map((target) => {
              const key = keyFor(group.source, target); const hot = Number(target.score) >= 80;
              return <article key={target.id} style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 240px' }} className={`rounded-xl border p-3.5 ${hot ? 'hot-match bg-red-50/30' : 'border-slate-200 bg-white'}`}><div className="flex items-start gap-3"><Checkbox aria-label={`Tandai rekomendasi ${target.contact_name || targetLabel} untuk PDF`} checked={exports.includes(key)} onCheckedChange={() => setExports((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])} />
                <div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-3"><div className="min-w-0 break-words"><p className="text-sm font-semibold">{target.contact_name || structuredSummary(target)}</p><LastSeen row={target} /><p className="mt-1 text-[13px] leading-5 text-slate-600">{structuredSummary(target)}</p></div><Badge className={hot ? 'bg-rose-50 text-rose-700 hover:bg-rose-50' : 'bg-amber-50 text-amber-700 hover:bg-amber-50'}><span aria-label={hot ? 'Hot' : 'Warm'} title={hot ? 'Hot' : 'Warm'} className="whitespace-nowrap text-xs">{hot ? '🔥 Hot' : '🌡️ Warm'}</span></Badge></div>
                  <div className="mt-2 flex flex-wrap gap-1.5">{target.explanation?.map((reason) => <span key={reason} className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">{reason}</span>)}</div><DuplicateBadge row={target} /><RawChat text={target.raw_text || target.normalized_text} /><div className="mt-3 flex flex-wrap gap-4"><ContactButton row={group.source} label={`WhatsApp ${sourceLabel}`} /><ContactButton row={target} label={`WhatsApp ${targetLabel}`} /></div>
                </div>
              </div></article>;
            })}</div>
          </section>)}</div>
        </div>
      </div>
    </div>
  </section>;
}
