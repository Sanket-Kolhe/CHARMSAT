import React, { useState, useEffect } from 'react';
import { BarChart3, Play, Clock, ShieldCheck, Zap, AlertTriangle } from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  LineChart,
  Line,
  CartesianGrid,
} from 'recharts';
import { API } from '../api';

export const ScreenBenchmark: React.FC = () => {
  const [signalCount, setSignalCount] = useState<number>(1000);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [benchmarkData, setBenchmarkData] = useState<any[] | null>(null);
  // No typed-in numbers: charts stay empty until a real run returns.
  const [lineChartData, setLineChartData] = useState<any[]>([]);

  const handleRunBenchmark = async () => {
    setIsRunning(true);
    try {
      const res = await API.runBenchmark(signalCount, 42);
      setBenchmarkData(res.benchmark_table);
      if (res.runtime_line_chart) {
        setLineChartData(res.runtime_line_chart);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsRunning(false);
    }
  };

  // Honest empty state: nothing is shown before a real run.
  const activeTable = benchmarkData || [];
  const hasRun = benchmarkData !== null;
  const [benchMeta, setBenchMeta] = useState<string | null>(null);

  // Load the measured table written by `make bench` (P5-1).
  useEffect(() => {
    API.benchLatest()
      .then((latest: any) => {
        if (latest && latest.table && latest.table.length > 0) {
          setBenchmarkData(
            latest.table.map((r: any) => ({
              ...r,
              cabinets_vs_lb: r.cabinets_vs_lb || `${r.cabinets} / ${r.lb}`,
            }))
          );
          if (latest.chart && latest.chart.length > 0) setLineChartData(latest.chart);
          if (latest.meta) {
            setBenchMeta(
              `measured ${latest.meta.date?.slice(0, 10)} · ${latest.meta.cpu_count} CPUs · commit ${latest.meta.commit}`
            );
          }
        }
      })
      .catch(() => {});
  }, []);

  // Bar chart data for Violations & Rev B Moves
  const barData = activeTable.map((row) => ({
    name: row.engine.split(' ')[0],
    Violations: row.violations,
    'Rev B Moves': row.rev_b_moves,
    Cabinets: row.cabinets,
  }));

  return (
    <div className="space-y-6">
      {/* Top Banner & Control Bar */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg flex items-center justify-between">
        <div>
          <h3 className="text-base font-display font-bold text-white tracking-wide flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-[#4ADE80]" />
            RIGOROUS EVALUATION BENCHMARK SUITE
          </h3>
          <p className="text-xs font-mono text-[#6B8E78] mt-1">
            Empirical comparison: B0 Greedy in file order vs B1 Greedy Grouped & A/B-aware vs CHARMSAT CP-SAT. All runs verified by the independent checker.
          </p>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-3">
          <select
            value={signalCount}
            onChange={(e) => setSignalCount(Number(e.target.value))}
            className="bg-[#0E1E14] border border-[#1E3E2B] text-white text-xs font-mono rounded-lg px-3 py-2 focus:outline-none focus:border-[#4ADE80]"
          >
            <option value={500}>500 Signals</option>
            <option value={1000}>1,000 Signals (Standard)</option>
            <option value={2500}>2,500 Signals</option>
            <option value={5000}>5,000 Signals (Scale Stress)</option>
          </select>

          <button
            onClick={handleRunBenchmark}
            disabled={isRunning}
            className="px-5 py-2 rounded-lg bg-[#143B22] hover:bg-[#1C5230] border border-[#4ADE80] text-xs font-mono font-bold text-[#5CFF7A] shadow-neon flex items-center gap-2 transition-all"
          >
            <Play className={`w-3.5 h-3.5 ${isRunning ? 'animate-spin' : ''}`} />
            <span>{isRunning ? 'MEASURING ENGINE...' : 'RUN BENCHMARK'}</span>
          </button>
        </div>
      </div>

      {/* Main Comparative Benchmark Table */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg space-y-4">
          <h4 className="text-xs font-mono font-bold text-white flex items-center justify-between">
            <span>LIVE EXPERIMENTAL MEASUREMENTS ({signalCount.toLocaleString()} SIGNALS)</span>
            <span className="text-[10px] font-mono text-[#587B64]">
              {benchMeta || 'Independent Checker Re-derived'}
            </span>
          </h4>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-[#1A3624] text-[#6B8E78] text-[11px]">
                <th className="py-2.5 px-3">ALGORITHM</th>
                <th className="py-2.5 px-3">RULE VIOLATIONS</th>
                <th className="py-2.5 px-3">CABINETS / LOWER BOUND</th>
                <th className="py-2.5 px-3">REV B MOVES</th>
                <th className="py-2.5 px-3">SOLVER RUNTIME</th>
                <th className="py-2.5 px-3">VERDICT</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#132A1C]">
              {!hasRun && (
                <tr>
                  <td colSpan={6} className="py-8 px-3 text-center text-xs font-mono text-[#6B8E78]">
                    No benchmark run yet — click RUN BENCHMARK or run `make bench`. No numbers are shown until code measures them.
                  </td>
                </tr>
              )}
              {activeTable.map((row, idx) => {
                const isCharmsat = row.engine.includes('CHARMSAT');
                return (
                  <tr
                    key={idx}
                    className={`transition-all ${
                      isCharmsat
                        ? 'bg-[#0E2618]/60 font-semibold border-l-4 border-l-[#4ADE80]'
                        : 'hover:bg-[#0D1F14]'
                    }`}
                  >
                    <td className="py-3 px-3 text-white flex items-center gap-2">
                      {isCharmsat && <span className="w-2 h-2 rounded-full bg-[#4ADE80]"></span>}
                      {row.engine}
                    </td>
                    <td className="py-3 px-3">
                      <span
                        className={`font-bold ${
                          row.violations === 0 ? 'text-[#4ADE80]' : 'text-red-400'
                        }`}
                      >
                        {row.violations}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-[#A7C7B3]">{row.cabinets_vs_lb}</td>
                    <td className="py-3 px-3">
                      <span
                        className={`font-bold ${
                          row.rev_b_moves < 100 ? 'text-[#5CFF7A]' : 'text-amber-400'
                        }`}
                      >
                        {row.rev_b_moves}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-[#38BDF8]">{row.runtime_s} s</td>
                    <td className="py-3 px-3">
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded border ${
                          isCharmsat
                            ? 'bg-emerald-950 text-emerald-400 border-emerald-700 font-bold'
                            : row.violations > 0
                            ? 'bg-red-950 text-red-400 border-red-800'
                            : 'bg-amber-950 text-amber-400 border-amber-800'
                        }`}
                      >
                        {row.verdict}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Two Comparative Charts */}
      <div className="grid grid-cols-2 gap-6">
        {/* Chart 1: Churn & Moves Comparison Bar Chart */}
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-mono font-bold text-white">
              REVISION B CHURN: RELOCATED SIGNALS (FEWER IS BETTER)
            </h4>
            <span className="text-[10px] font-mono text-[#4ADE80]">Min-Move Advantage</span>
          </div>

          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData} margin={{ top: 20, right: 20, left: 0, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#163120" />
                <XAxis dataKey="name" stroke="#6B8E78" tick={{ fill: '#6B8E78', fontSize: 11 }} />
                <YAxis stroke="#6B8E78" tick={{ fill: '#6B8E78', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#09150E',
                    borderColor: '#1E4D2C',
                    borderRadius: '8px',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace' }} />
                <Bar dataKey="Rev B Moves" fill="#4ADE80" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Violations" fill="#EF4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 2: Runtime vs N Scale Line Chart */}
        <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-mono font-bold text-white">
              RUNTIME SCALABILITY: WALL-CLOCK (S) VS SIGNAL COUNT N
            </h4>
            <span className="text-[10px] font-mono text-[#38BDF8]">Scale Target &lt; 60 s</span>
          </div>

          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={lineChartData} margin={{ top: 20, right: 20, left: 0, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#163120" />
                <XAxis
                  dataKey="signals"
                  stroke="#6B8E78"
                  tick={{ fill: '#6B8E78', fontSize: 11 }}
                  unit=" sig"
                />
                <YAxis
                  stroke="#6B8E78"
                  tick={{ fill: '#6B8E78', fontSize: 11 }}
                  unit="s"
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#09150E',
                    borderColor: '#1E4D2C',
                    borderRadius: '8px',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace' }} />
                <Line
                  type="monotone"
                  dataKey="charmsat"
                  name="CHARMSAT CP-SAT"
                  stroke="#4ADE80"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: '#4ADE80' }}
                />
                <Line
                  type="monotone"
                  dataKey="b1"
                  name="B1 Greedy"
                  stroke="#38BDF8"
                  strokeWidth={1.5}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
};
