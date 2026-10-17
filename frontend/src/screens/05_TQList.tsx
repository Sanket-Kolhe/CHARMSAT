import React, { useState } from 'react';
import { AlertCircle, ChevronDown, ChevronRight, AlertTriangle, Database, Zap, Sparkles, CheckCircle } from 'lucide-react';
import { TQ, API, AllocResult } from '../api';

interface TQListProps {
  tqs: TQ[];
  onLoadAdversarial: () => void;
  isLoading: boolean;
}

export const ScreenTQList: React.FC<TQListProps> = ({
  tqs,
  onLoadAdversarial,
  isLoading
}) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  const getKindBadge = (kind: string) => {
    switch (kind) {
      case 'rule_conflict':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-950 text-purple-300 border border-purple-700">
            RULE CONFLICT (MUS)
          </span>
        );
      case 'capacity':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-950 text-amber-300 border border-amber-700">
            CAPACITY DEFICIT
          </span>
        );
      case 'data':
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-700">
            DATA DEFECT
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner & Adversarial Trigger */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg flex items-center justify-between">
        <div>
          <h3 className="text-base font-display font-bold text-white tracking-wide flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-amber-400" />
            TECHNICAL QUERIES (TQ) & UNSAT-CORE EXPLAINER
          </h3>
          <p className="text-xs font-mono text-[#6B8E78] mt-1">
            Instead of guessing or crashing on infeasible inputs, CHARMSAT isolates Minimal Unsatisfiable Subsets (MUS) and raises plain-English TQs for customer engineering review.
          </p>
        </div>

        {/* Load Adversarial Conflict Preset Button */}
        <button
          onClick={onLoadAdversarial}
          disabled={isLoading}
          className="px-4 py-2.5 rounded-lg bg-[#26150F] hover:bg-[#3B1F16] border border-amber-500 text-xs font-mono font-bold text-amber-300 shadow-amberGlow flex items-center gap-2 transition-all"
        >
          <Zap className="w-4 h-4 text-amber-400" />
          <span>LOAD ADVERSARIAL CONFLICT FILE</span>
        </button>
      </div>

      {/* TQ Summary KPI bar */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between">
          <span className="text-[10px] font-mono text-[#6B8E78]">TOTAL ACTIVE TQs</span>
          <span className="text-xl font-mono font-bold text-white mt-1">{tqs.length}</span>
          <span className="text-[10px] font-mono text-[#4ADE80]">Zero Unexplained Drops</span>
        </div>
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between">
          <span className="text-[10px] font-mono text-[#6B8E78]">RULE CONFLICT TQs</span>
          <span className="text-xl font-mono font-bold text-purple-400 mt-1">
            {tqs.filter((t) => t.kind === 'rule_conflict').length}
          </span>
          <span className="text-[10px] font-mono text-[#6B8E78]">Unsat Cores Isolated</span>
        </div>
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between">
          <span className="text-[10px] font-mono text-[#6B8E78]">DATA DEFECT TQs</span>
          <span className="text-xl font-mono font-bold text-cyan-400 mt-1">
            {tqs.filter((t) => t.kind === 'data').length}
          </span>
          <span className="text-[10px] font-mono text-[#6B8E78]">Incomplete Customer Data</span>
        </div>
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between">
          <span className="text-[10px] font-mono text-[#6B8E78]">CAPACITY TQs</span>
          <span className="text-xl font-mono font-bold text-amber-400 mt-1">
            {tqs.filter((t) => t.kind === 'capacity').length}
          </span>
          <span className="text-[10px] font-mono text-[#6B8E78]">Group / Cabinet Overflow</span>
        </div>
      </div>

      {/* Main TQ Table */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg space-y-4">
        <h4 className="text-xs font-mono font-bold text-white flex items-center justify-between">
          <span>ACTIVE TECHNICAL QUERY LOG</span>
          <span className="text-[10px] font-mono text-[#6B8E78]">
            Click row to view minimal conflicting rule set
          </span>
        </h4>

        {tqs.length === 0 ? (
          <div className="p-8 text-center bg-[#07120A] rounded-lg border border-[#163120] text-xs font-mono text-[#6B8E78]">
            <CheckCircle className="w-6 h-6 text-[#4ADE80] mx-auto mb-2" />
            No technical queries active. All signals and constraints are 100% clean and satisfiable.
          </div>
        ) : (
          <div className="space-y-2">
            {tqs.map((tq) => {
              const isExpanded = expandedId === tq.id;
              return (
                <div
                  key={tq.id}
                  className="bg-[#08150E] border border-[#1A3824] hover:border-[#4ADE80] rounded-lg transition-all overflow-hidden"
                >
                  {/* Row Header */}
                  <div
                    onClick={() => toggleExpand(tq.id)}
                    className="p-3.5 flex items-center justify-between cursor-pointer select-none"
                  >
                    <div className="flex items-center gap-3">
                      <button className="text-[#6B8E78]">
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4 text-[#4ADE80]" />
                        ) : (
                          <ChevronRight className="w-4 h-4" />
                        )}
                      </button>
                      <span className="font-mono font-bold text-xs text-white">{tq.id}</span>
                      {getKindBadge(tq.kind)}
                      <span className="text-xs font-mono text-[#C4D9CC] ml-2">{tq.message}</span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-[#6B8E78]">
                        {tq.items.length} Affected Item(s)
                      </span>
                    </div>
                  </div>

                  {/* Expanded Minimal Conflicting Rule Set Detail */}
                  {isExpanded && (
                    <div className="bg-[#060D08] border-t border-[#163120] p-4 space-y-3 text-xs font-mono">
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <div className="text-[10px] text-[#6B8E78] font-bold mb-1">
                            AFFECTED INSTRUMENTS / CABLES:
                          </div>
                          <div className="p-2.5 rounded bg-[#09150E] border border-[#163120] text-white">
                            {tq.items.join(', ') || 'Global'}
                            {tq.rows && tq.rows.length > 0 && (
                              <div className="text-[10px] text-[#6B8E78] mt-1">
                                Excel rows: {tq.rows.join(', ')}
                              </div>
                            )}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-[#6B8E78] font-bold mb-1">
                            MINIMAL CONFLICTING RULE SET (MUS):
                          </div>
                          <div className="p-2.5 rounded bg-[#09150E] border border-[#163120] text-amber-300 font-bold">
                            {((tq.mus && tq.mus.length ? tq.mus : tq.rule_ids) || []).join('  ⚡  ') ||
                              'RULE-01 vs RULE-02'}
                          </div>
                        </div>
                      </div>

                      <div className="p-3 rounded bg-[#0D2114] border border-[#1E4D2C] text-[#A7C7B3] text-[11px] leading-relaxed">
                        <span className="text-[#5CFF7A] font-bold mr-1">Engineering Action:</span>
                        {tq.options && tq.options.length > 0
                          ? tq.options.join(' ')
                          : tq.kind === 'rule_conflict'
                          ? "Customer clarification required: split the affected pairs into separate single-train multicores or relax the segregation level."
                          : tq.kind === 'capacity'
                          ? "Cabinet margin breached: group signal count exceeds single-cabinet spare capacity. Allocate an additional cabinet or subdivide the process group."
                          : "Engineering input needed: tag records contain invalid or missing IO module specs. Update the customer instrument list before physical marshalling."}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
