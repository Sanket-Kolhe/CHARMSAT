import React, { useState, useMemo } from 'react';
import { AllocatedSlot, API } from '../api';
import { Filter, Layers, Info, Check, Search, HelpCircle, X, ShieldCheck } from 'lucide-react';

interface CabinetGridProps {
  allocations: AllocatedSlot[];
  highlightMovedTags?: Set<string>;
}

export const CabinetGrid: React.FC<CabinetGridProps> = ({
  allocations,
  highlightMovedTags
}) => {
  const [selectedCab, setSelectedCab] = useState<number>(0);
  const [selectedIOType, setSelectedIOType] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [hoveredSlot, setHoveredSlot] = useState<AllocatedSlot | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [explain, setExplain] = useState<any | null>(null);
  const [isExplaining, setIsExplaining] = useState<boolean>(false);

  const handleExplain = async (t: string) => {
    setIsExplaining(true);
    try {
      setExplain(await API.explainSignal(t));
    } catch {
      setExplain(null);
    } finally {
      setIsExplaining(false);
    }
  };

  // Compute available cabinets
  const cabinetsAvailable = useMemo(() => {
    const cabs = new Set(allocations.map((a) => a.cabinet));
    return Array.from(cabs).sort((a, b) => a - b);
  }, [allocations]);

  // Active cabinet allocations
  const cabAllocations = useMemo(() => {
    return allocations.filter((a) => a.cabinet === selectedCab);
  }, [allocations, selectedCab]);

  // Organize by CIOC (0..3) -> Baseplate (0..7) -> Slot (0..11)
  const ciocMatrix = useMemo(() => {
    const matrix: Record<number, Record<number, Record<number, AllocatedSlot | null>>> = {};
    for (let c = 0; c < 4; c++) {
      matrix[c] = {};
      for (let bp = 0; bp < 8; bp++) {
        matrix[c][bp] = {};
        for (let s = 0; s < 12; s++) {
          matrix[c][bp][s] = null;
        }
      }
    }

    cabAllocations.forEach((slot) => {
      if (matrix[slot.cioc]?.[slot.baseplate]) {
        matrix[slot.cioc][slot.baseplate][slot.slot] = slot;
      }
    });

    return matrix;
  }, [cabAllocations]);

  // Determine CIOC trains (A or B)
  const ciocTrains = useMemo(() => {
    const trains: Record<number, string | null> = { 0: null, 1: null, 2: null, 3: null };
    cabAllocations.forEach((s) => {
      if (s.seg) {
        trains[s.cioc] = s.seg;
      }
    });
    return trains;
  }, [cabAllocations]);

  // Slot styling helper
  const getSlotStyle = (slot: AllocatedSlot | null) => {
    if (!slot) {
      return 'border border-dashed border-[#14261B] bg-[#07100A] text-[#243E2E]';
    }

    const isMoved = highlightMovedTags && slot.tag && highlightMovedTags.has(slot.tag);

    if (slot.is_spare) {
      return `border border-[#183622] bg-[#09150E] text-[#42664E] ${
        isMoved ? 'ring-2 ring-amber-400' : ''
      }`;
    }

    // Filter match check
    if (selectedIOType !== 'ALL' && slot.io_type !== selectedIOType) {
      return 'opacity-20 border border-[#183622] bg-[#09150E] text-[#42664E]';
    }

    if (
      searchTerm &&
      !(
        slot.tag?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        slot.cable?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        slot.group?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    ) {
      return 'opacity-20 border border-[#183622] bg-[#09150E] text-[#42664E]';
    }

    if (isMoved) {
      return 'border-2 border-amber-400 bg-amber-950/40 text-amber-300 font-bold shadow-amberGlow animate-pulse';
    }

    // Colors by IO Type
    if (slot.io_type === 'AI') {
      return 'border border-cyan-500/50 bg-cyan-950/40 text-cyan-300 hover:border-cyan-400 hover:bg-cyan-900/60';
    }
    if (slot.io_type === 'AO') {
      return 'border border-blue-500/50 bg-blue-950/40 text-blue-300 hover:border-blue-400 hover:bg-blue-900/60';
    }
    if (slot.io_type === 'DI') {
      return 'border border-emerald-500/50 bg-emerald-950/40 text-emerald-300 hover:border-emerald-400 hover:bg-emerald-900/60';
    }
    if (slot.io_type === 'DO') {
      if (slot.charm.includes('Isolated')) {
        return 'border border-amber-500/60 bg-amber-950/50 text-amber-300 hover:border-amber-400 hover:bg-amber-900/70 font-semibold';
      }
      return 'border border-purple-500/50 bg-purple-950/40 text-purple-300 hover:border-purple-400 hover:bg-purple-900/60';
    }

    return 'border border-[#285739] bg-[#0F2819] text-[#7AC994]';
  };

  return (
    <div className="bg-[#09140D] border border-[#1B3826] rounded-xl p-4 shadow-lg select-none relative">
      {/* Top Controls Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 mb-4 border-b border-[#1B3826]">
        {/* Cabinet Selector Tabs */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-mono text-[#6B8E78] mr-2">CABINET:</span>
          {cabinetsAvailable.map((c) => (
            <button
              key={c}
              onClick={() => setSelectedCab(c)}
              className={`px-3 py-1 rounded text-xs font-mono font-semibold transition-all ${
                selectedCab === c
                  ? 'bg-[#184227] text-[#5CFF7A] border border-[#4ADE80] shadow-neon'
                  : 'bg-[#0E1E14] text-[#86A893] hover:bg-[#142B1D] border border-[#193623]'
              }`}
            >
              CAB-{(c + 1).toString().padStart(2, '0')}
            </button>
          ))}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3">
          {/* Search box */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-[#547560] absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Filter Tag / Cable / Group..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2.5 pl-8 py-1 text-xs font-mono text-white placeholder-[#547560] focus:outline-none focus:border-[#4ADE80] w-48"
            />
          </div>

          {/* IO Type Buttons */}
          <div className="flex items-center gap-1 bg-[#0C1A11] p-0.5 rounded border border-[#1E3E2B]">
            {['ALL', 'AI', 'AO', 'DI', 'DO'].map((t) => (
              <button
                key={t}
                onClick={() => setSelectedIOType(t)}
                className={`px-2 py-0.5 rounded text-[10px] font-mono font-semibold transition-all ${
                  selectedIOType === t
                    ? 'bg-[#1E4D2C] text-white'
                    : 'text-[#6B8E78] hover:text-white'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] font-mono text-[#7CA089] mb-4 bg-[#0B1810] p-2 rounded border border-[#173020]">
        <span className="text-[#547560] font-bold">LEGEND:</span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-cyan-500/40 border border-cyan-400"></span>
          AI (HART)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-blue-500/40 border border-blue-400"></span>
          AO (HART)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500/40 border border-emerald-400"></span>
          DI (Dry Contact)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-purple-500/40 border border-purple-400"></span>
          DO (High-Side)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-amber-500/40 border border-amber-400"></span>
          DO Isolated (Relay)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-[#09150E] border border-dashed border-[#244C32]"></span>
          Spare Pair
        </span>
        {highlightMovedTags && highlightMovedTags.size > 0 && (
          <span className="flex items-center gap-1.5 text-amber-300 font-bold">
            <span className="w-2.5 h-2.5 rounded-sm bg-amber-500 border border-amber-300 animate-pulse"></span>
            Moved in Rev B
          </span>
        )}
      </div>

      {/* CIOC Grid (4 CIOCs) */}
      <div className="grid grid-cols-2 gap-4">
        {[0, 1, 2, 3].map((ciocIdx) => {
          const train = ciocTrains[ciocIdx];
          return (
            <div
              key={ciocIdx}
              className="bg-[#0B1910] border border-[#193824] rounded-lg p-3 relative flex flex-col justify-between"
            >
              {/* CIOC Header */}
              <div className="flex items-center justify-between pb-2 mb-2 border-b border-[#163120]">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono font-bold text-white tracking-wide">
                    CIOC-{(ciocIdx + 1).toString().padStart(2, '0')}
                  </span>
                  <span className="text-[10px] font-mono text-[#587B64]">
                    (8 Baseplates × 12 CHARMs = 96 Slots)
                  </span>
                </div>
                {/* Segregation Badge */}
                {train === 'A' && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-600 shadow-cyanGlow">
                    TRAIN A
                  </span>
                )}
                {train === 'B' && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-950 text-amber-300 border border-amber-600 shadow-amberGlow">
                    TRAIN B
                  </span>
                )}
                {!train && (
                  <span className="px-1.5 py-0.5 rounded text-[9px] font-mono text-[#587B64] bg-[#08130C] border border-[#152B1C]">
                    UNSEGREGATED
                  </span>
                )}
              </div>

              {/* 8 Baseplates */}
              <div className="space-y-1.5">
                {[0, 1, 2, 3, 4, 5, 6, 7].map((bpIdx) => (
                  <div key={bpIdx} className="flex items-center gap-1.5">
                    {/* BP Label */}
                    <span className="w-12 text-[9px] font-mono text-[#587B64] text-right shrink-0">
                      BP-{bpIdx + 1}
                    </span>
                    {/* 12 CHARM Slots */}
                    <div className="grid grid-cols-12 gap-1 flex-1">
                      {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((sIdx) => {
                        const slot = ciocMatrix[ciocIdx]?.[bpIdx]?.[sIdx];
                        return (
                          <div
                            key={sIdx}
                            onMouseEnter={(e) => {
                              if (slot) {
                                setHoveredSlot(slot);
                                setMousePos({ x: e.clientX, y: e.clientY });
                              }
                            }}
                            onMouseLeave={() => setHoveredSlot(null)}
                            onClick={() => slot && slot.tag && handleExplain(slot.tag)}
                            title={slot && slot.tag ? `${slot.tag} — click for "why here?"` : undefined}
                            className={`h-6 rounded text-[8px] font-mono flex items-center justify-center transition-all ${
                              slot && slot.tag ? 'cursor-help' : 'cursor-default'
                            } ${getSlotStyle(
                              slot
                            )}`}
                          >
                            {slot ? (
                              slot.is_spare ? (
                                'SP'
                              ) : (
                                slot.io_type
                              )
                            ) : (
                              '·'
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* W2: "Why is this signal here?" panel */}
      {(explain || isExplaining) && (
        <div className="mt-4 bg-[#08140D] border border-[#4ADE80] rounded-xl p-4 shadow-neon">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono font-bold text-[#5CFF7A] flex items-center gap-2">
              <HelpCircle className="w-4 h-4" />
              WHY IS THIS SIGNAL HERE?
            </span>
            <button onClick={() => setExplain(null)} className="text-[#6B8E78] hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
          {isExplaining && <div className="text-[11px] font-mono text-[#6B8E78]">Re-deriving rules...</div>}
          {explain && explain.found && (
            <div className="space-y-2 text-[11px] font-mono">
              <div className="text-white">
                <span className="font-bold text-[#5CFF7A]">{explain.tag}</span>
                {explain.placed ? (
                  <>
                    {' '}is at <span className="text-amber-300">{explain.location}</span>
                    {' '}as <span className="text-[#38BDF8]">{explain.charm}</span>
                  </>
                ) : (
                  <> is not placed: {explain.reason}</>
                )}
              </div>
              {explain.placed && (
                <>
                  <div className="text-[#A7C7B3]">{explain.why_here}</div>
                  <div className="grid grid-cols-2 gap-1.5 pt-1">
                    {explain.checks.map((c: any, i: number) => (
                      <div key={i} className="flex items-start gap-1.5 text-[10px]">
                        <span className={c.satisfied ? 'text-[#4ADE80]' : 'text-red-400'}>
                          {c.satisfied ? '✓' : '✗'}
                        </span>
                        <span className="text-[#C4D9CC]">
                          <span className="text-[#5CFF7A] font-bold">{c.rule}</span> {c.detail}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center gap-1.5 text-[10px] text-[#6B8E78] pt-1 border-t border-[#163120]">
                    <ShieldCheck className="w-3.5 h-3.5 text-[#4ADE80]" />
                    Pinned by: {(explain.pinned_by || []).join(', ') || 'optimiser packing only'}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Floating Interactive Tooltip */}
      {hoveredSlot && (
        <div
          className="fixed z-50 pointer-events-none bg-[#091710] border border-[#4ADE80] text-white p-3 rounded-lg shadow-neon text-xs font-mono space-y-1 w-64"
          style={{
            top: Math.min(window.innerHeight - 200, mousePos.y + 15),
            left: Math.min(window.innerWidth - 270, mousePos.x + 15),
          }}
        >
          <div className="flex items-center justify-between border-b border-[#1E4D2C] pb-1 font-bold text-[#5CFF7A]">
            <span>{hoveredSlot.tag || `SPARE (PAIR ${hoveredSlot.pair})`}</span>
            <span className="text-[10px] px-1 py-0.2 rounded bg-[#102B19] border border-[#1E4D2C]">
              {hoveredSlot.io_type || 'SPARE'}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-2 text-[10px] text-[#A6C4B1] pt-0.5">
            <div>CABLE: <span className="text-white font-semibold">{hoveredSlot.cable}</span></div>
            <div>PAIR: <span className="text-white font-semibold">#{hoveredSlot.pair}</span></div>
            <div>GROUP: <span className="text-white">{hoveredSlot.group || 'N/A'}</span></div>
            <div>TRAIN: <span className="text-white font-bold">{hoveredSlot.seg || 'NONE'}</span></div>
            <div className="col-span-2">LOCATION: <span className="text-white">{hoveredSlot.cabinet_name} CIOC-{hoveredSlot.cioc+1} BP-{hoveredSlot.baseplate+1} Slot-{hoveredSlot.slot+1}</span></div>
            <div className="col-span-2">CHARM: <span className="text-[#38BDF8]">{hoveredSlot.charm}</span></div>
            <div className="col-span-2">TB: <span className="text-[#A6C4B1]">{hoveredSlot.terminal_block}</span></div>
            <div className="col-span-2 text-[9px] text-[#4ADE80] pt-1 border-t border-[#1E4D2C]">
              Click for "why is this here?"
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
