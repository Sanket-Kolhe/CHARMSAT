import React, { useState } from 'react';
import { Wand2, Plus, Gauge, RefreshCw, Info } from 'lucide-react';
import { API } from '../api';

export const WhatIfPanel: React.FC = () => {
  const [ioType, setIoType] = useState('AI');
  const [cable, setCable] = useState('WI-CABLE-1');
  const [pair, setPair] = useState(1);
  const [group, setGroup] = useState('WI-GROUP');
  const [seg, setSeg] = useState('A');
  const [spare, setSpare] = useState(10);
  const [result, setResult] = useState<any | null>(null);
  const [label, setLabel] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<any>, what: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fn();
      setResult(res);
      setLabel(what);
    } catch (e: any) {
      setError(e.message || 'What-if failed');
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const addSignal = () =>
    run(
      () =>
        API.whatIf({
          kind: 'add_signal',
          signals_extra: [
            { tag: `WI-${Date.now() % 100000}`, io_type: ioType, subtype: '', cable, pair, group, seg },
          ],
        }),
      `Add one ${ioType} signal on cable ${cable}`,
    );

  const changeSpare = () =>
    run(() => API.whatIf({ kind: 'spare_change', spare_percentage: spare }), `Set spare margin to ${spare}%`);

  const deltaColor = (d: number | null | undefined) =>
    d == null ? 'text-[#A7C7B3]' : d > 0 ? 'text-red-400' : d < 0 ? 'text-[#4ADE80]' : 'text-[#A7C7B3]';

  return (
    <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-mono font-bold text-white flex items-center gap-2">
          <Wand2 className="w-4 h-4 text-[#38BDF8]" />
          WHAT-IF ANALYSIS — SCORE BEFORE YOU COMMIT
        </h4>
        <span className="text-[10px] font-mono text-[#6B8E78] flex items-center gap-1">
          <Info className="w-3 h-3" />
          Recomputed live; never changes the committed plan
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4 text-xs font-mono">
        {/* Add signal card */}
        <div className="bg-[#09150E] border border-[#1E3A2B] rounded-lg p-3 space-y-2">
          <div className="text-[10px] text-[#6B8E78] font-bold">ADD A SIGNAL</div>
          <div className="flex items-center gap-1.5">
            <select
              value={ioType}
              onChange={(e) => setIoType(e.target.value)}
              className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-1.5 py-1 text-white text-[11px]"
            >
              {['AI', 'AO', 'DI', 'DO'].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
            <input
              value={cable}
              onChange={(e) => setCable(e.target.value)}
              placeholder="cable"
              className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-1.5 py-1 text-white text-[11px] w-24"
            />
            <input
              type="number"
              value={pair}
              onChange={(e) => setPair(Number(e.target.value))}
              className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-1.5 py-1 text-white text-[11px] w-14"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <input
              value={group}
              onChange={(e) => setGroup(e.target.value)}
              placeholder="group"
              className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-1.5 py-1 text-white text-[11px] w-24"
            />
            <select
              value={seg}
              onChange={(e) => setSeg(e.target.value)}
              className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-1.5 py-1 text-white text-[11px]"
            >
              <option value="">—</option>
              <option value="A">A</option>
              <option value="B">B</option>
            </select>
            <button
              onClick={addSignal}
              disabled={busy}
              className="ml-auto px-2 py-1 rounded bg-[#122E1A] hover:bg-[#1A4226] border border-[#4ADE80] text-[#5CFF7A] text-[10px] font-bold flex items-center gap-1 disabled:opacity-40"
            >
              <Plus className="w-3 h-3" />
              SCORE
            </button>
          </div>
        </div>

        {/* Spare margin card */}
        <div className="bg-[#09150E] border border-[#1E3A2B] rounded-lg p-3 space-y-2">
          <div className="text-[10px] text-[#6B8E78] font-bold">CHANGE SPARE MARGIN</div>
          <div className="flex items-center gap-2">
            <Gauge className="w-4 h-4 text-[#4ADE80]" />
            <input
              type="range"
              min={0}
              max={30}
              step={5}
              value={spare}
              onChange={(e) => setSpare(Number(e.target.value))}
              className="accent-[#4ADE80] flex-1"
            />
            <span className="text-white font-bold text-[11px] w-9 text-right">{spare}%</span>
          </div>
          <button
            onClick={changeSpare}
            disabled={busy}
            className="w-full px-2 py-1 rounded bg-[#0E2A18] hover:bg-[#153825] border border-[#38BDF8] text-[#7DD3FC] text-[10px] font-bold flex items-center justify-center gap-1 disabled:opacity-40"
          >
            <RefreshCw className="w-3 h-3" />
            SCORE RE-SOLVE
          </button>
        </div>

        {/* Result card */}
        <div className="bg-[#0A1810] border border-[#1E4D2C] rounded-lg p-3 space-y-1.5">
          <div className="text-[10px] text-[#6B8E78] font-bold">HYPOTHETICAL IMPACT</div>
          {busy && <div className="text-[11px] text-[#6B8E78]">Solving...</div>}
          {error && <div className="text-[11px] text-red-400">{error}</div>}
          {!busy && !error && !result && (
            <div className="text-[11px] text-[#587B64]">Run a what-if to preview cabinets, coverage and spare.</div>
          )}
          {result && !busy && (
            <>
              <div className="text-[10px] text-[#7DD3FC]">{label}</div>
              <div className="grid grid-cols-3 gap-1 text-[10px]">
                <div>
                  <div className="text-[#6B8E78]">CABS</div>
                  <div className="text-white font-bold">{result.hypothetical.cabinets_used}</div>
                </div>
                <div>
                  <div className="text-[#6B8E78]">COVERAGE</div>
                  <div className="text-white font-bold">{result.hypothetical.coverage_pct}%</div>
                </div>
                <div>
                  <div className="text-[#6B8E78]">Δ CABS</div>
                  <div className={`font-bold ${deltaColor(result.delta.cabinets)}`}>
                    {result.delta.cabinets == null ? '—' : (result.delta.cabinets > 0 ? '+' : '') + result.delta.cabinets}
                  </div>
                </div>
              </div>
              {result.added_locations?.length > 0 && (
                <div className="text-[10px] text-[#A7C7B3]">
                  New signal lands at{' '}
                  <span className="text-amber-300 font-bold">{result.added_locations[0].location}</span>
                </div>
              )}
              <div className="text-[9px] text-[#587B64] pt-1 border-t border-[#163120]">{result.note}</div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
