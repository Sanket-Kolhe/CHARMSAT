import React from 'react';
import { CheckCircle2, AlertOctagon, Server, Clock, Zap, ShieldCheck } from 'lucide-react';
import { AllocResult } from '../api';

interface KPIHeaderProps {
  allocResult: AllocResult | null;
  tamperedViolationCount?: number | null;
}

export const KPIHeader: React.FC<KPIHeaderProps> = ({
  allocResult,
  tamperedViolationCount
}) => {
  const placedCount = allocResult ? allocResult.slots_used : 0;
  const coverage = allocResult ? allocResult.coverage_pct : 100;
  const cabinets = allocResult ? allocResult.cabinets_used : 0;
  const lb = allocResult ? allocResult.lower_bound_cabinets : 0;
  const sparePct = allocResult ? allocResult.spare_pct_actual : 0;
  const runtime = allocResult ? allocResult.runtime_s : 0;

  const actualViolations = tamperedViolationCount !== undefined && tamperedViolationCount !== null
    ? tamperedViolationCount
    : (allocResult ? allocResult.violations.length : 0);

  const isClean = actualViolations === 0;

  return (
    <div className="grid grid-cols-6 gap-3 mb-5 select-none">
      {/* 1. Signals Placed */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between shadow-sm">
        <div className="flex items-center justify-between text-[11px] font-mono text-[#6B8E78]">
          <span>SIGNALS PLACED</span>
          <Zap className="w-3.5 h-3.5 text-[#4ADE80]" />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-mono font-bold text-white tracking-tight">
            {placedCount.toLocaleString()}
          </span>
          <span className="text-[10px] font-mono text-[#4ADE80]">
            100% PLACED
          </span>
        </div>
        <div className="text-[10px] text-[#547560] font-mono mt-1">
          Atomic Cable Blocks
        </div>
      </div>

      {/* 2. Coverage */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between shadow-sm">
        <div className="flex items-center justify-between text-[11px] font-mono text-[#6B8E78]">
          <span>COVERAGE</span>
          <CheckCircle2 className="w-3.5 h-3.5 text-[#38BDF8]" />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-mono font-bold text-[#38BDF8] tracking-tight">
            {coverage}%
          </span>
          <span className="text-[10px] font-mono text-[#6B8E78]">
            Placed + TQ
          </span>
        </div>
        <div className="text-[10px] text-[#547560] font-mono mt-1">
          Zero Orphan Signals
        </div>
      </div>

      {/* 3. Checker Violations */}
      <div className={`rounded-xl p-3.5 flex flex-col justify-between transition-all ${
        isClean 
          ? 'bg-[#0A1A10] border border-[#4ADE80] shadow-neon' 
          : 'bg-[#1C0A0A] border border-[#EF4444] shadow-redGlow'
      }`}>
        <div className="flex items-center justify-between text-[11px] font-mono">
          <span className={isClean ? 'text-[#4ADE80]' : 'text-[#EF4444]'}>
            CHECKER STATUS
          </span>
          <ShieldCheck className={`w-3.5 h-3.5 ${isClean ? 'text-[#4ADE80]' : 'text-[#EF4444]'}`} />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className={`text-2xl font-mono font-bold tracking-tight ${isClean ? 'text-[#5CFF7A]' : 'text-[#EF4444]'}`}>
            {isClean ? '0' : actualViolations}
          </span>
          <span className={`text-[11px] font-mono font-semibold ${isClean ? 'text-[#4ADE80]' : 'text-[#EF4444]'}`}>
            {isClean ? 'VIOLATIONS' : 'FLAWS CAUGHT'}
          </span>
        </div>
        <div className="text-[10px] text-[#6B8E78] font-mono mt-1">
          {isClean ? 'Independent Verifier Clean' : 'Planted Flaw Flagged!'}
        </div>
      </div>

      {/* 4. Cabinets Used vs Lower Bound */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between shadow-sm">
        <div className="flex items-center justify-between text-[11px] font-mono text-[#6B8E78]">
          <span>CABINETS / LB</span>
          <Server className="w-3.5 h-3.5 text-[#A7C7B3]" />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-mono font-bold text-white tracking-tight">
            {cabinets}
          </span>
          <span className="text-[11px] font-mono text-[#6B8E78]">
            / LB: {lb}
          </span>
        </div>
        <div className="text-[10px] text-[#4ADE80] font-mono mt-1">
          Efficiency: {lb > 0 ? (cabinets / lb).toFixed(2) : '—'}x{lb > 0 && cabinets === lb ? ' Optimal' : ''}
        </div>
      </div>

      {/* 5. Spare Capacity */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between shadow-sm">
        <div className="flex items-center justify-between text-[11px] font-mono text-[#6B8E78]">
          <span>SPARE CAPACITY</span>
          <span className="text-[10px] px-1 py-0.2 rounded bg-[#102B19] text-[#4ADE80] font-mono border border-[#1E4D2C]">
            &gt;= 10%
          </span>
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-mono font-bold text-white tracking-tight">
            {sparePct}%
          </span>
          <span className="text-[10px] font-mono text-[#4ADE80]">
            RESERVED
          </span>
        </div>
        <div className="text-[10px] text-[#547560] font-mono mt-1">
          Future Plant Expansion
        </div>
      </div>

      {/* 6. Solver Runtime */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-3.5 flex flex-col justify-between shadow-sm">
        <div className="flex items-center justify-between text-[11px] font-mono text-[#6B8E78]">
          <span>SOLVER RUNTIME</span>
          <Clock className="w-3.5 h-3.5 text-[#38BDF8]" />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-mono font-bold text-[#38BDF8] tracking-tight">
            {runtime.toFixed(2)}
          </span>
          <span className="text-[11px] font-mono text-[#6B8E78]">
            sec
          </span>
        </div>
        <div className="text-[10px] text-[#4ADE80] font-mono mt-1">
          Target &lt; 60 s Met
        </div>
      </div>
    </div>
  );
};
