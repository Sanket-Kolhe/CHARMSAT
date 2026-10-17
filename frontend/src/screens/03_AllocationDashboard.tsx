import React from 'react';
import { KPIHeader } from '../components/KPIHeader';
import { CabinetGrid } from '../components/CabinetGrid';
import { WhatIfPanel } from '../components/WhatIfPanel';
import { AllocResult } from '../api';
import { Grid, Sparkles, RefreshCw } from 'lucide-react';

interface AllocationDashboardProps {
  allocResult: AllocResult | null;
  onReSolve: () => void;
  isSolving: boolean;
}

export const ScreenAllocationDashboard: React.FC<AllocationDashboardProps> = ({
  allocResult,
  onReSolve,
  isSolving
}) => {
  if (!allocResult || !allocResult.allocations || allocResult.allocations.length === 0) {
    return (
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-12 text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-[#0F2618] border border-[#235332] flex items-center justify-center mx-auto shadow-neon">
          <Grid className="w-8 h-8 text-[#4ADE80]" />
        </div>
        <h3 className="text-base font-display font-bold text-white">
          NO ACTIVE ALLOCATION LOADED
        </h3>
        <p className="text-xs font-mono text-[#6B8E78] max-w-md mx-auto">
          Ingest a customer IO list from the Upload screen or click below to run a 1,000-signal CP-SAT allocation solve.
        </p>
        <button
          onClick={onReSolve}
          disabled={isSolving}
          className="px-5 py-2.5 rounded-lg bg-[#143B22] hover:bg-[#1C5230] border border-[#4ADE80] text-xs font-mono font-bold text-[#5CFF7A] shadow-neon inline-flex items-center gap-2"
        >
          <Sparkles className="w-4 h-4 text-[#5CFF7A]" />
          <span>RUN 1,000-SIGNAL CP-SAT SOLVE</span>
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* KPI Cards Header */}
      <KPIHeader allocResult={allocResult} />

      {/* What-if scoring (W1) */}
      <WhatIfPanel />

      {/* Main Cabinet Visualizer Grid */}
      <CabinetGrid allocations={allocResult.allocations} />
    </div>
  );
};
