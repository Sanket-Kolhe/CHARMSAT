import React, { useState, useRef } from 'react';
import { GitCompare, RefreshCw, AlertTriangle, ArrowRight, CheckCircle2, ShieldCheck, UploadCloud } from 'lucide-react';
import { API, AllocResult, RevisionSummary } from '../api';
import { CabinetGrid } from '../components/CabinetGrid';

interface RevisionDiffProps {
  allocResultB: AllocResult | null;
  onGenerateRevB: () => void;
  onUploadRevB: (file: File) => Promise<void>;
  isLoading: boolean;
}

export const ScreenRevisionDiff: React.FC<RevisionDiffProps> = ({
  allocResultB,
  onGenerateRevB,
  onUploadRevB,
  isLoading
}) => {
  const revSummary: RevisionSummary | null = allocResultB?.rev_summary || null;
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Moved tags set for highlighting in CabinetGrid
  const movedTagsSet = React.useMemo(() => {
    if (!revSummary) return new Set<string>();
    return new Set(revSummary.moves_detail.map((m) => m.tag));
  }, [revSummary]);

  return (
    <div className="space-y-6">
      {/* Top Action Banner */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg flex items-center justify-between">
        <div>
          <h3 className="text-base font-display font-bold text-white tracking-wide flex items-center gap-2">
            <GitCompare className="w-5 h-5 text-[#4ADE80]" />
            REVISION B MINIMUM-MOVE RE-ALLOCATION
          </h3>
          <p className="text-xs font-mono text-[#6B8E78] mt-1">
            Customer engineering changes arrive late in the project. CHARMSAT re-allocates Rev B using Rev A positions as CP-SAT soft hints with heavy move penalties.
          </p>
        </div>

        <div className="flex items-center gap-3">
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.xls,.xlsm,.csv"
          className="hidden"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = '';
            if (!f) return;
            setUploadError(null);
            try {
              await onUploadRevB(f);
            } catch (err: any) {
              setUploadError(err.message || 'Revise failed');
            }
          }}
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={isLoading}
          className="px-5 py-2.5 rounded-lg bg-[#0E2A18] hover:bg-[#153825] border border-[#38BDF8] text-xs font-mono font-bold text-[#7DD3FC] flex items-center gap-2 transition-all"
        >
          <UploadCloud className="w-3.5 h-3.5" />
          <span>UPLOAD REV B & REVISE</span>
        </button>

        <button
          onClick={onGenerateRevB}
          disabled={isLoading}
          className="px-5 py-2.5 rounded-lg bg-[#143B22] hover:bg-[#1C5230] border border-[#4ADE80] text-xs font-mono font-bold text-[#5CFF7A] shadow-neon flex items-center gap-2 transition-all"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>GENERATE & SOLVE REV B</span>
        </button>
        </div>
        {uploadError && (
          <div className="text-[11px] font-mono text-red-400 mt-2">{uploadError}</div>
        )}
      </div>

      {/* Diff Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between">
          <span className="text-[10px] font-mono text-[#6B8E78]">ADDED SIGNALS</span>
          <span className="text-2xl font-mono font-bold text-[#4ADE80] mt-1">
            +{revSummary ? revSummary.added_count : '—'}
          </span>
          <span className="text-[10px] font-mono text-[#6B8E78]">New Field Loops</span>
        </div>
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between">
          <span className="text-[10px] font-mono text-[#6B8E78]">DELETED SIGNALS</span>
          <span className="text-2xl font-mono font-bold text-red-400 mt-1">
            -{revSummary ? revSummary.deleted_count : '—'}
          </span>
          <span className="text-[10px] font-mono text-[#6B8E78]">Decommissioned</span>
        </div>
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between">
          <span className="text-[10px] font-mono text-[#6B8E78]">TYPE MODIFICATIONS</span>
          <span className="text-2xl font-mono font-bold text-[#38BDF8] mt-1">
            {revSummary ? revSummary.changed_count : '—'}
          </span>
          <span className="text-[10px] font-mono text-[#6B8E78]">e.g. AI ↔ AO</span>
        </div>
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between">
          <span className="text-[10px] font-mono text-[#6B8E78]">UNCHANGED PINNED</span>
          <span className="text-2xl font-mono font-bold text-white mt-1">
            {revSummary ? revSummary.unchanged_count.toLocaleString() : '—'}
          </span>
          <span className="text-[10px] font-mono text-[#4ADE80]">Exact Slot Retained</span>
        </div>
      </div>

      {/* Side-by-Side Comparison: Ours (Min-Move) vs From-Scratch Re-Solve */}
      <div className="grid grid-cols-2 gap-6">
        {/* Ours (Min-Move) */}
        <div className="bg-[#0B1C12] border-2 border-[#4ADE80] rounded-xl p-6 shadow-neon space-y-3 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold text-[#4ADE80] tracking-wider uppercase flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-[#4ADE80]" />
              OURS (MINIMUM-MOVE ENGINE)
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#102B19] text-[#4ADE80] border border-[#1E4D2C]">
              CP-SAT LEXICOGRAPHIC
            </span>
          </div>

          <div className="py-4">
            <div className="text-[11px] font-mono text-[#6B8E78]">MOVED SIGNALS IN HARDWARE</div>
            <div className="text-5xl font-mono font-bold text-[#5CFF7A] tracking-tight mt-1">
              {revSummary ? revSummary.moves_ours : '—'}
            </div>
            <div className="text-xs font-mono text-[#A7C7B3] mt-2">
              {revSummary
                ? 'Only moved signals where adjacent cable expansions strictly forced relocations.'
                : 'No revision run yet — upload Rev B and click GENERATE & SOLVE REV B.'}
            </div>
          </div>

          <div className="p-3 rounded bg-[#09170E] border border-[#183B23] text-[11px] font-mono text-[#5CFF7A]">
            {revSummary
              ? `Field termination drawings stay ${(100 * revSummary.unchanged_count / Math.max(1, revSummary.unchanged_count + revSummary.moves_ours)).toFixed(1)}% valid across project revision.`
              : 'Move statistics appear here after a revision run.'}
          </div>
        </div>

        {/* Rival / From-Scratch Re-Solve */}
        <div className="bg-[#1C0E0E] border border-red-500/50 rounded-xl p-6 shadow-redGlow space-y-3 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold text-red-400 tracking-wider uppercase flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-red-400" />
              FROM-SCRATCH RE-SOLVE (CHURN)
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-red-950 text-red-400 border border-red-800">
              NAIVE RE-ALLOCATION
            </span>
          </div>

          <div className="py-4">
            <div className="text-[11px] font-mono text-[#8F6B6B]">MOVED SIGNALS IN HARDWARE</div>
            <div className="text-5xl font-mono font-bold text-red-400 tracking-tight mt-1">
              {revSummary ? revSummary.moves_from_scratch : '—'}
            </div>
            <div className="text-xs font-mono text-[#CCA5A5] mt-2">
              {revSummary
                ? 'Arbitrary symmetry breaking churns untouched field signals!'
                : 'The from-scratch baseline is computed live alongside the revision.'}
            </div>
          </div>

          <div className="p-3 rounded bg-[#261010] border border-[#4D1B1B] text-[11px] font-mono text-red-300">
            {revSummary && revSummary.moves_ours > 0
              ? `Engineering rework: ${(revSummary.moves_from_scratch / revSummary.moves_ours).toFixed(1)}x more wiring modifications required on site.`
              : 'Rework comparison appears here after a revision run.'}
          </div>
        </div>
      </div>

      {/* Forcing Rule Attribution Table */}
      {revSummary && revSummary.moves_detail.length > 0 && (
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg space-y-4">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-mono font-bold text-white flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400"></span>
              REVISION MOVED SIGNALS & FORCING RULE AUDIT LOG ({revSummary.moves_detail.length})
            </h4>
            <span className="text-[10px] font-mono text-[#6B8E78]">
              Every relocated slot carries a mathematical justification
            </span>
          </div>

          <div className="overflow-x-auto max-h-64">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-[#1A3624] text-[#6B8E78] text-[10px]">
                  <th className="py-2 px-2.5">TAG</th>
                  <th className="py-2 px-2.5">CABLE</th>
                  <th className="py-2 px-2.5">TYPE</th>
                  <th className="py-2 px-2.5">REV A SLOT</th>
                  <th className="py-2 px-2.5">REV B SLOT</th>
                  <th className="py-2 px-2.5">FORCING RULE</th>
                  <th className="py-2 px-2.5">JUSTIFICATION</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#132A1C]">
                {revSummary.moves_detail.map((m, idx) => (
                  <tr key={idx} className="hover:bg-[#0D1F14]">
                    <td className="py-2 px-2.5 font-bold text-white">{m.tag}</td>
                    <td className="py-2 px-2.5 text-[#38BDF8]">{m.cable}</td>
                    <td className="py-2 px-2.5 text-[#4ADE80]">{m.io_type}</td>
                    <td className="py-2 px-2.5 text-[#6B8E78]">{m.old_location}</td>
                    <td className="py-2 px-2.5 text-amber-300 font-bold">{m.new_location}</td>
                    <td className="py-2 px-2.5">
                      {m.forcing_rule ? (
                        <span className="px-1.5 py-0.5 rounded bg-[#102B19] text-[#5CFF7A] border border-[#1E4D2C]">
                          {m.forcing_rule}
                        </span>
                      ) : (
                        <span className="text-[#6B8E78]">rebalance</span>
                      )}
                    </td>
                    <td className="py-2 px-2.5 text-[#C4D9CC]">{m.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Interactive Cabinet Visualizer with Moved Slots Highlighted */}
      {allocResultB && (
        <div className="space-y-2">
          <h4 className="text-xs font-mono font-bold text-white flex items-center justify-between">
            <span>REVISION B CABINET GRID (MOVED SLOTS HIGHLIGHTED IN NEON AMBER)</span>
            <span className="text-[10px] font-mono text-amber-400">
              Pulsing amber cells = relocated by CP-SAT solver
            </span>
          </h4>
          <CabinetGrid
            allocations={allocResultB.allocations}
            highlightMovedTags={movedTagsSet}
          />
        </div>
      )}
    </div>
  );
};
