import React, { useState, useRef } from 'react';
import { UploadCloud, CheckCircle, RefreshCw, ArrowRight, Shuffle, FileSpreadsheet, AlertCircle } from 'lucide-react';
import { API } from '../api';

interface UploadMappingProps {
  onProceedToAllocation: () => void;
  onDataLoaded: (signals: any[], cableSizes: any) => void;
}

export const ScreenUploadMapping: React.FC<UploadMappingProps> = ({
  onProceedToAllocation,
  onDataLoaded
}) => {
  const [fuzzHeaders, setFuzzHeaders] = useState<boolean>(false);
  const [signalCount, setSignalCount] = useState<number>(1000);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [detectedColumns, setDetectedColumns] = useState<string[]>([]);
  const [mappingResults, setMappingResults] = useState<any[]>([]);
  const [previewRows, setPreviewRows] = useState<any[]>([]);
  const [loadedSummary, setLoadedSummary] = useState<any | null>(null);
  // Real-upload state (P1-1)
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [sheets, setSheets] = useState<any[]>([]);
  const [sheetIdx, setSheetIdx] = useState<number>(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [profileName, setProfileName] = useState<string>('');
  const [profileMatch, setProfileMatch] = useState<any | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const CANONICAL_FIELDS = [
    'Tag',
    'IO Type',
    'Subtype',
    'Cable',
    'Pair',
    'Cable Size',
    'Group',
    'Segregation',
    'IGNORE'
  ];

  const handleGenerate = async () => {
    setIsLoading(true);
    try {
      const data = await API.generateDataset({
        n_signals: signalCount,
        seed: 42,
        fuzz_headers: fuzzHeaders,
      });

      setDetectedColumns(data.columns);
      setPreviewRows(data.sample_rows);
      setUploadId(null);
      setSheets([]);
      setLoadedSummary({
        signals: data.signal_count,
        cables: data.cable_count,
        fuzzed: fuzzHeaders,
      });

      // Auto-map columns with rapidfuzz API
      const mapRes = await API.mapColumns(data.columns);
      setMappingResults(mapRes.matches);
      setProfileMatch(mapRes.profile_match || null);

      onDataLoaded(data.raw_signals, data.cable_sizes);
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  // Real file upload (P1-1): xlsx/xls/csv -> header detection + mapping proposal
  const showSheet = (allSheets: any[], idx: number) => {
    const sh = allSheets[idx];
    if (!sh || sh.error) {
      setDetectedColumns([]);
      setMappingResults([]);
      setPreviewRows([]);
      setLoadedSummary(sh ? { signals: 0, cables: 0, error: sh.error, source: sh.name } : null);
      return;
    }
    setDetectedColumns(sh.header_cells);
    setMappingResults(sh.mapping.matches);
    setPreviewRows(sh.preview_rows);
    setLoadedSummary({ signals: sh.n_rows, cables: null, source: sh.name });
  };

  const handleFile = async (file: File) => {
    setIsLoading(true);
    setUploadError(null);
    try {
      const up = await API.uploadIOList(file);
      setUploadId(up.upload_id);
      setSheets(up.sheets);
      setSheetIdx(0);
      showSheet(up.sheets, 0);
    } catch (err: any) {
      setUploadError(err.message || 'Upload failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirm = async () => {
    // Upload path: apply the (possibly overridden) mapping to the real data.
    if (uploadId) {
      setIsLoading(true);
      try {
        const overrides: Record<string, string | null> = {};
        mappingResults.forEach((m: any) => {
          overrides[m.detected_column] = m.mapped_canonical || null;
        });
        const confirmed = await API.confirmMapping({
          upload_id: uploadId,
          sheet: sheets[sheetIdx]?.name,
          overrides,
          profile_name: profileName.trim() || undefined,
        });
        onDataLoaded(confirmed.raw_signals, confirmed.cable_sizes);
        setLoadedSummary((s: any) => ({ ...s, signals: confirmed.signal_count, cables: confirmed.cable_count }));
      } catch (err: any) {
        setUploadError(err.message || 'Confirm failed');
        return;
      } finally {
        setIsLoading(false);
      }
    }
    onProceedToAllocation();
  };

  const handleOverrideMapping = (colIdx: number, newCanonical: string) => {
    const updated = [...mappingResults];
    updated[colIdx].mapped_canonical = newCanonical === 'IGNORE' ? null : newCanonical;
    updated[colIdx].confidence_pct = 100.0;
    setMappingResults(updated);
  };

  return (
    <div className="space-y-6">
      {/* Action Header Card */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg flex items-center justify-between">
        <div>
          <h3 className="text-base font-display font-bold text-white tracking-wide flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-[#4ADE80]" />
            CUSTOMER IO LIST INGESTION & AUTO-MAPPER
          </h3>
          <p className="text-xs font-mono text-[#6B8E78] mt-1">
            Accepts raw customer instrument schedules with non-standard headers. Rapidfuzz matches against Emerson synonym taxonomy.
          </p>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-3">
          {/* Fuzz Headers Toggle */}
          <label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#0E1E14] border border-[#1E3E2B] cursor-pointer hover:border-[#4ADE80] transition-all">
            <input
              type="checkbox"
              checked={fuzzHeaders}
              onChange={(e) => setFuzzHeaders(e.target.checked)}
              className="accent-[#4ADE80] w-4 h-4 rounded"
            />
            <span className="text-xs font-mono text-[#A7C7B3] flex items-center gap-1.5">
              <Shuffle className="w-3.5 h-3.5 text-[#38BDF8]" />
              FUZZ HEADERS ({fuzzHeaders ? 'ON' : 'OFF'})
            </span>
          </label>

          {/* Signal Count Selector */}
          <select
            value={signalCount}
            onChange={(e) => setSignalCount(Number(e.target.value))}
            className="bg-[#0E1E14] border border-[#1E3E2B] text-white text-xs font-mono rounded-lg px-3 py-2 focus:outline-none focus:border-[#4ADE80]"
          >
            <option value={300}>300 Signals (Prototype)</option>
            <option value={1000}>1,000 Signals (Seeded Demo)</option>
            <option value={2500}>2,500 Signals (Plant Area)</option>
            <option value={5000}>5,000 Signals (Mega Project)</option>
          </select>

          {/* Load Synthetic Demo File Button */}
          <button
            onClick={handleGenerate}
            disabled={isLoading}
            className="px-4 py-2 rounded-lg bg-[#143B22] hover:bg-[#1C5230] border border-[#4ADE80] text-xs font-mono font-bold text-[#5CFF7A] shadow-neon flex items-center gap-2 transition-all"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>LOAD DEMO FILE</span>
          </button>
        </div>
      </div>

      {/* Drag & Drop Upload Zone + Stats */}
      <div className="grid grid-cols-3 gap-5">
        <div
          className={`col-span-1 bg-[#09150E] border-2 border-dashed ${isDragging ? 'border-[#4ADE80]' : 'border-[#1E3A2B]'} hover:border-[#4ADE80] rounded-xl p-6 flex flex-col items-center justify-center text-center transition-all cursor-pointer group`}
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => { e.preventDefault(); setIsDragging(false); const f = e.dataTransfer.files?.[0]; if (f) handleFile(f); }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.xlsm,.csv"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ''; }}
          />
          <div className="w-12 h-12 rounded-full bg-[#0F2618] border border-[#235332] group-hover:border-[#4ADE80] flex items-center justify-center mb-3 shadow-sm transition-all">
            <UploadCloud className="w-6 h-6 text-[#4ADE80]" />
          </div>
          <span className="text-xs font-mono font-bold text-white mb-1">
            DRAG & DROP CUSTOMER IO LIST
          </span>
          <span className="text-[10px] font-mono text-[#6B8E78]">
            Supports .xlsx, .xls, .csv files (up to 12,000 signals)
          </span>
          <span className="text-[9px] font-mono text-[#38BDF8] mt-2 underline">
            Or browse local file
          </span>
          {uploadError && (
            <span className="text-[10px] font-mono text-red-400 mt-2 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" /> {uploadError}
            </span>
          )}
        </div>

        {/* Load Summary Stats */}
        <div className="col-span-2 bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between border-b border-[#1A3624] pb-2">
            <span className="text-xs font-mono font-bold text-white flex items-center gap-2">
              <CheckCircle className="w-4 h-4 text-[#4ADE80]" />
              FILE INGESTION PROFILE
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#102B19] text-[#4ADE80] border border-[#1E4D2C]">
              {loadedSummary ? 'FILE LOADED & PROFILED' : 'AWAITING FILE'}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-4 py-3">
            <div>
              <div className="text-[10px] font-mono text-[#6B8E78]">TOTAL SIGNALS</div>
              <div className="text-xl font-mono font-bold text-white mt-0.5">
                {loadedSummary ? loadedSummary.signals.toLocaleString() : '—'}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono text-[#6B8E78]">CABLE BLOCKS</div>
              <div className="text-xl font-mono font-bold text-[#38BDF8] mt-0.5">
                {loadedSummary ? (loadedSummary.cables ?? '—') : '—'}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono text-[#6B8E78]">DETECTED COLS</div>
              <div className="text-xl font-mono font-bold text-white mt-0.5">
                {detectedColumns.length || '—'}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono text-[#6B8E78]">SOURCE</div>
              <div className="text-xl font-mono font-bold text-[#4ADE80] mt-0.5">
                {loadedSummary ? (loadedSummary.source || (loadedSummary.fuzzed ? 'ACTIVE' : 'STANDARD')) : '—'}
              </div>
            </div>
          </div>

          {sheets.length > 1 && (
            <div className="flex items-center gap-2 py-2">
              <span className="text-[10px] font-mono text-[#6B8E78]">SHEET:</span>
              <select
                value={sheetIdx}
                onChange={(e) => { const i = Number(e.target.value); setSheetIdx(i); showSheet(sheets, i); }}
                className="bg-[#0E1E14] border border-[#1E3E2B] text-white text-xs font-mono rounded-lg px-3 py-1.5 focus:outline-none focus:border-[#4ADE80]"
              >
                {sheets.map((sh: any, i: number) => (
                  <option key={i} value={i}>{sh.name} ({sh.n_rows} rows)</option>
                ))}
              </select>
            </div>
          )}

          <div className="flex items-center justify-between gap-3 pt-2 border-t border-[#1A3624]">
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="text-[#6B8E78]">SAVE AS PROFILE:</span>
              <input
                type="text"
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                placeholder="e.g. CUSTOMER_ACME"
                className="bg-[#0E1E14] border border-[#1E3E2B] text-white text-xs font-mono rounded-lg px-3 py-1.5 focus:outline-none focus:border-[#4ADE80] w-44"
              />
              {profileMatch && (
                <span className="text-[10px] text-[#38BDF8]">
                  saved profile "{profileMatch.name}" matches these headers
                </span>
              )}
            </div>
            <button
              onClick={handleConfirm}
              disabled={!loadedSummary || isLoading}
              className="px-5 py-2 rounded-lg bg-[#143B22] hover:bg-[#1C5230] border border-[#4ADE80] text-xs font-mono font-bold text-[#5CFF7A] shadow-neon flex items-center gap-2 disabled:opacity-30 disabled:pointer-events-none transition-all"
            >
              <span>CONFIRM MAPPING & PROCEED TO SOLVE</span>
              <ArrowRight className="w-4 h-4 text-[#5CFF7A]" />
            </button>
          </div>
        </div>
      </div>

      {/* Column Auto-Mapping Table */}
      {mappingResults.length > 0 && (
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg space-y-4">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-mono font-bold text-white flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#4ADE80]"></span>
              DETECTED COLUMN MAPPING & CONFIDENCE PROFILE
            </h4>
            <span className="text-[10px] font-mono text-[#6B8E78]">
              Rapidfuzz Token-Sort Ratio & Synonym Dictionary
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-[#1A3624] text-[#6B8E78] text-[11px]">
                  <th className="py-2 px-3">DETECTED COLUMN</th>
                  <th className="py-2 px-3">RAPIDFUZZ MATCH</th>
                  <th className="py-2 px-3">CONFIDENCE</th>
                  <th className="py-2 px-3">CANONICAL ASSIGNMENT</th>
                  <th className="py-2 px-3">STATUS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#132A1C]">
                {mappingResults.map((m, idx) => {
                  const conf = m.confidence_pct;
                  const isHigh = conf >= 80;
                  const isMed = conf >= 50 && conf < 80;
                  return (
                    <tr key={idx} className="hover:bg-[#0D1F14] transition-all">
                      <td className="py-2.5 px-3 font-semibold text-white">
                        {m.detected_column}
                      </td>
                      <td className="py-2.5 px-3 text-[#38BDF8]">
                        {m.mapped_canonical || 'Unmapped'}
                        {m.evidence && (
                          <div className="text-[10px] text-[#6B8E78] mt-0.5">{m.evidence}</div>
                        )}
                      </td>
                      <td className="py-2.5 px-3">
                        <div className="flex items-center gap-2 w-36">
                          <div className="flex-1 h-2 rounded-full bg-[#08140D] border border-[#1B3826] overflow-hidden">
                            <div
                              className={`h-full ${
                                isHigh ? 'bg-[#4ADE80]' : isMed ? 'bg-amber-400' : 'bg-red-400'
                              }`}
                              style={{ width: `${conf}%` }}
                            />
                          </div>
                          <span className="text-[10px] font-bold text-white">{conf}%</span>
                        </div>
                      </td>
                      <td className="py-2.5 px-3">
                        <select
                          value={m.mapped_canonical || 'IGNORE'}
                          onChange={(e) => handleOverrideMapping(idx, e.target.value)}
                          className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2 py-1 text-xs font-mono text-[#A7C7B3] focus:outline-none focus:border-[#4ADE80]"
                        >
                          {CANONICAL_FIELDS.map((cf) => (
                            <option key={cf} value={cf}>
                              {cf}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2.5 px-3">
                        {isHigh ? (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800">
                            AUTO-CONFIRMED
                          </span>
                        ) : isMed ? (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-amber-950 text-amber-400 border border-amber-800">
                            FUZZY OVERRIDE
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-red-950 text-red-400 border border-red-800">
                            UNMAPPED
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Data Preview Table */}
      {previewRows.length > 0 && (
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg space-y-3">
          <h4 className="text-xs font-mono font-bold text-white flex items-center justify-between">
            <span>RAW DATA PREVIEW (FIRST 10 SIGNALS)</span>
            <span className="text-[10px] text-[#547560]">Sample View</span>
          </h4>
          <div className="overflow-x-auto max-h-48">
            <table className="w-full text-left text-[11px] font-mono">
              <thead>
                <tr className="border-b border-[#1A3624] text-[#6B8E78]">
                  {detectedColumns.map((col, i) => (
                    <th key={i} className="py-1.5 px-2 bg-[#08120B]">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#132A1C]">
                {previewRows.slice(0, 10).map((row, rIdx) => (
                  <tr key={rIdx} className="hover:bg-[#0D1F14]">
                    {detectedColumns.map((col, cIdx) => (
                      <td key={cIdx} className="py-1 px-2 text-[#C4D9CC]">
                        {row[col]?.toString() || ''}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
