'use client';

import { useCallback, useEffect, useRef, useState, type ComponentProps } from 'react';
import { addMonths, format, isSameDay, startOfMonth, subMonths } from 'date-fns';
import { id } from 'date-fns/locale';
import { CalendarDays } from 'lucide-react';
import { Calendar } from '@/components/ui/calendar';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { useIsMobile } from '@/hooks/use-mobile';
import type { DayButtonProps } from 'react-day-picker';

export type DateFilterValue = { from: string; to: string; startTime: string; endTime: string };
const empty: DateFilterValue = { from: '', to: '', startTime: '00:00', endTime: '23:59' };
const parseDate = (value: string) => new Date(`${value}T12:00:00`);
const dayKey = (date: Date) => format(date, 'yyyy-MM-dd');
function ordered(a: Date, b: Date) { return a < b ? { from: a, to: b } : { from: b, to: a }; }

function FocusableDay({ focused, ...props }: ComponentProps<'button'> & { focused: boolean }) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (focused) ref.current?.focus({ preventScroll: true }); }, [focused]);
  return <button ref={ref} {...props} />;
}

export default function DateFilter({ value, onChange, direction }: { value: DateFilterValue; onChange: (value: DateFilterValue) => void; direction: 'buyer' | 'property' }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const [anchor, setAnchor] = useState<Date | null>(null);
  const anchorRef = useRef<Date | null>(null);
  const [hover, setHover] = useState<Date | null>(null);
  const [month, setMonth] = useState(startOfMonth(subMonths(new Date(), 1)));
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [latest, setLatest] = useState<string | null>(null);
  const [loadingDates, setLoadingDates] = useState(true);
  const [dateError, setDateError] = useState(false);
  const initialMonth = useRef(true);
  const mobile = useIsMobile();
  const countMonths = mobile ? 1 : 2;
  const from = draft.from ? parseDate(draft.from) : undefined;
  const to = draft.to ? parseDate(draft.to) : from;
  const selected = anchor && hover ? ordered(anchor, hover) : from ? { from, to } : undefined;
  const invalidTimes = Boolean(draft.from && draft.from === draft.to && draft.startTime > draft.endTime);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const query = new URLSearchParams({ direction, date_from: dayKey(month), date_to: dayKey(addMonths(month, countMonths)) });
    setCounts({}); setLoadingDates(true); setDateError(false);
    void fetch(`/api/workspace/dates?${query}`, { signal: controller.signal }).then(async r => {
      if (!r.ok) throw new Error('dates');
      const data = await r.json() as { counts: Record<string, number>; latest_date: string | null };
      if (controller.signal.aborted) return;
      setCounts(data.counts); setLatest(data.latest_date); setLoadingDates(false);
      if (initialMonth.current) {
        initialMonth.current = false;
        if (data.latest_date && !value.from) setMonth(startOfMonth(countMonths === 1 ? parseDate(data.latest_date) : subMonths(parseDate(data.latest_date), 1)));
      }
    }).catch(() => { if (!controller.signal.aborted) { setLoadingDates(false); setDateError(true); } });
    return () => controller.abort();
  }, [open, month, direction, countMonths]);

  function changeOpen(next: boolean) {
    if (next) {
      initialMonth.current = true; setLoadingDates(true); setLatest(null);
      setDraft(value); setAnchor(null); anchorRef.current = null; setHover(null);
      const reference = value.from ? parseDate(value.from) : new Date();
      setMonth(startOfMonth(value.from || mobile ? reference : subMonths(reference,1)));
    }
    setOpen(next);
  }

  function click(date: Date) {
    if (loadingDates || dateError || !latest || dayKey(date) > latest) return;
    if (!anchor) {
      setDraft(v => ({ ...v, from: dayKey(date), to: dayKey(date) }));
      setAnchor(date); anchorRef.current = date; setHover(null);
    } else {
      const range = ordered(anchor,date);
      setDraft(v => ({ ...v, from: dayKey(range.from), to: dayKey(range.to) }));
      setAnchor(null); anchorRef.current = null; setHover(null);
    }
  }

  const CountDay = useCallback((props: DayButtonProps) => {
    const count = counts[dayKey(props.day.date)];
    const { day, modifiers, ...buttonProps } = props;
    const single = modifiers.range_start && modifiers.range_end;
    const endpoint = modifiers.range_start || modifiers.range_end;
    return <FocusableDay focused={Boolean(modifiers.focused)} {...buttonProps} onPointerEnter={() => { if (anchorRef.current && !modifiers.disabled) setHover(day.date); }}
      className={`relative flex h-12 w-full flex-col items-center justify-center gap-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:text-slate-300 ${endpoint ? `bg-blue-600 text-white ${single ? 'rounded-xl' : modifiers.range_start ? 'rounded-l-xl' : 'rounded-r-xl'}` : modifiers.range_middle ? 'bg-blue-50 text-slate-800' : 'rounded-xl enabled:hover:bg-slate-50'}`}
      aria-label={`${format(day.date,'d MMMM yyyy',{locale:id})}${count ? `, ${count} posting ${direction === 'buyer' ? 'buyer' : 'listing'} unik` : ''}`}>
      {day.date.getDate()}
      {count ? <span title={`${count} posting unik; teks identik dihitung satu`} className="flex h-5 min-w-5 items-center justify-center rounded-full bg-emerald-100 px-1 text-[10px] font-semibold leading-none text-emerald-800">{new Intl.NumberFormat('id-ID',{notation:'compact'}).format(count)}</span> : <span className="h-5" />}
    </FocusableDay>;
  }, [counts, direction]);

  const label = value.from ? `${format(parseDate(value.from),'d MMM yyyy',{locale:id})}${value.to && value.to !== value.from ? ` – ${format(parseDate(value.to),'d MMM yyyy',{locale:id})}` : ''}` : 'Semua tanggal';
  return <div className="text-[13px] font-medium text-slate-600"><span className="block pb-1">Tanggal posting</span><Popover open={open} onOpenChange={changeOpen}>
    <PopoverTrigger render={<Button variant="outline" className="h-10 rounded-xl bg-white" aria-label={`Filter tanggal: ${label}`} />}><CalendarDays className="size-4" />{label}</PopoverTrigger>
    <PopoverContent align="end" className="w-[min(680px,calc(100vw-24px))] max-h-[90vh] overflow-y-auto rounded-2xl p-4 sm:p-5">
      <PopoverTitle className="sr-only">Pilih tanggal atau rentang tanggal</PopoverTitle>
      <div><Calendar locale={id} mode="range" month={month} onMonthChange={setMonth} numberOfMonths={countMonths} selected={selected} disabled={loadingDates || dateError || !latest ? true : { after: parseDate(latest) }} endMonth={latest ? parseDate(latest) : undefined} onSelect={() => {}} onDayClick={click} showOutsideDays={false} weekStartsOn={0} fixedWeeks
        className="w-full [--cell-size:2.5rem]"
        classNames={{ months: 'relative flex w-full flex-col gap-8 md:flex-row', month: 'flex min-w-0 flex-1 flex-col gap-2', week: 'mt-1 flex w-full', caption_label: 'text-lg font-semibold text-slate-950', weekday: 'flex-1 py-2 text-sm font-semibold text-slate-500', day: 'relative w-full p-0 text-center', today: 'font-semibold', range_middle: 'bg-blue-50', range_start: '', range_end: '', disabled: 'text-slate-300' }} components={{ DayButton: CountDay }} />
      </div>
      <p className="text-xs text-slate-500">Badge hijau = jumlah posting {direction === 'buyer' ? 'buyer' : 'listing'} unik per hari. Teks identik dihitung satu, sebelum filter lain.</p>
      <p className="mt-1 text-xs text-slate-500">{loadingDates ? 'Memuat ketersediaan tanggal…' : dateError ? 'Tanggal belum berhasil dimuat. Tutup lalu buka kembali kalender.' : latest ? `Data tersedia hingga ${format(parseDate(latest),'d MMM yyyy',{locale:id})}.` : 'Belum ada data untuk dipilih.'}</p>
      <div onPointerEnter={() => setHover(null)} className="mt-2 grid grid-cols-2 gap-4 border-t border-slate-200 pt-4"><label className="text-sm font-semibold">Mulai (WIB)<input aria-label="Jam mulai" type="time" value={draft.startTime} onChange={e => setDraft(v => ({...v,startTime:e.target.value || '00:00'}))} className="mt-1 h-10 w-full rounded-lg border border-slate-200 px-3" /></label><label className="text-sm font-semibold">Sampai (WIB)<input aria-label="Jam akhir" type="time" value={draft.endTime} onChange={e => setDraft(v => ({...v,endTime:e.target.value || '23:59'}))} className="mt-1 h-10 w-full rounded-lg border border-slate-200 px-3" /></label></div>
      {invalidTimes && <p role="alert" className="text-sm text-red-600">Jam akhir tidak boleh lebih awal dari jam mulai untuk tanggal yang sama.</p>}
      <p role="status" className="mt-2 text-sm text-slate-600">{anchor && hover && !isSameDay(anchor,hover) ? `Pratinjau ${format(selected!.from!,'d MMM',{locale:id})} – ${format(selected!.to!,'d MMM yyyy',{locale:id})}. Klik untuk menetapkan rentang.` : draft.from ? `${format(parseDate(draft.from),'d MMM yyyy',{locale:id})}${draft.to !== draft.from ? ` – ${format(parseDate(draft.to),'d MMM yyyy',{locale:id})}` : ' · satu hari'}` : 'Klik satu tanggal, atau klik awal lalu akhir rentang.'}</p>
      <div className="mt-2 flex items-center justify-between gap-2"><Button variant="ghost" onClick={() => { onChange(empty); setOpen(false); }}>Semua tanggal</Button><div className="flex gap-2"><Button variant="outline" onClick={() => setOpen(false)}>Batal</Button><Button disabled={!draft.from || invalidTimes || loadingDates || dateError || !latest || draft.to > latest} onClick={() => { onChange(draft); setOpen(false); }}>Terapkan</Button></div></div>
    </PopoverContent>
  </Popover></div>;
}
