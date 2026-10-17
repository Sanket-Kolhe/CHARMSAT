import React, { useState, useEffect } from 'react';
import { Sidebar, ScreenId } from './components/Sidebar';
import { Navbar } from './components/Navbar';
import { ScreenUploadMapping } from './screens/01_UploadMapping';
import { ScreenRulePanel } from './screens/02_RulePanel';
import { ScreenAllocationDashboard } from './screens/03_AllocationDashboard';
import { ScreenCheckerReport } from './screens/04_CheckerReport';
import { ScreenTQList } from './screens/05_TQList';
import { ScreenRevisionDiff } from './screens/06_RevisionDiff';
import { ScreenBenchmark } from './screens/07_Benchmark';
import { ScreenExport } from './screens/08_Export';
import { API, AllocResult, Violation, TQ } from './api';
import { ChevronRight, ChevronLeft, Sparkles, CheckCircle2 } from 'lucide-react';

export const App: React.FC = () => {
  const [currentScreen, setCurrentScreen] = useState<ScreenId>('mapping');
  const [allocResultA, setAllocResultA] = useState<AllocResult | null>(null);
  const [allocResultB, setAllocResultB] = useState<AllocResult | null>(null);
  const [tqs, setTqs] = useState<TQ[]>([]);
  const [tamperedViolations, setTamperedViolations] = useState<Violation[] | null>(null);
  const [isSolving, setIsSolving] = useState<boolean>(false);
  const [isDemoActive, setIsDemoActive] = useState<boolean>(false);

  // Auto-initialize demo data on mount
  useEffect(() => {
    initDemoRun();
  }, []);

  const initDemoRun = async () => {
    setIsSolving(true);
    try {
      await API.initDemo();
      // Fetch Rev A allocation
      const resA = await API.allocate({ use_rev_a_as_hints: false });
      setAllocResultA(resA);
      setTqs(resA.tqs || []);
      setTamperedViolations(null);

      // Fetch Rev B
      const resB = await API.generateRevB({});
      setAllocResultB(resB.rev_b_result);
    } catch (err) {
      console.error(err);
    } finally {
      setIsSolving(false);
    }
  };

  const handleReSolve = async () => {
    setIsSolving(true);
    try {
      const res = await API.allocate({ use_rev_a_as_hints: false });
      setAllocResultA(res);
      setTqs(res.tqs || []);
      setTamperedViolations(null);
    } catch (err) {
      console.error(err);
    } finally {
      setIsSolving(false);
    }
  };

  const handleGenerateRevB = async () => {
    setIsSolving(true);
    try {
      const res = await API.generateRevB({});
      setAllocResultB(res.rev_b_result);
    } catch (err) {
      console.error(err);
    } finally {
      setIsSolving(false);
    }
  };

  const handleUploadRevB = async (file: File) => {
    setIsSolving(true);
    try {
      const res = await API.reviseRevB(file);
      setAllocResultB(res.rev_b_result);
    } finally {
      setIsSolving(false);
    }
  };

  const handleLoadAdversarial = async () => {
    setIsSolving(true);
    try {
      // Injects conflicting A/B cable
      const genData = await API.generateDataset({
        n_signals: 300,
        inject_defects: true,
        defect_types: ['ab_mixed_cable', 'blank_type', 'pair_overflow'],
      });
      const res = await API.allocate({
        signals: genData.raw_signals,
        cable_sizes: genData.cable_sizes,
      });
      setAllocResultA(res);
      setTqs(res.tqs || []);
      setCurrentScreen('tqs');
    } catch (err) {
      console.error(err);
    } finally {
      setIsSolving(false);
    }
  };

  const screenOrder: ScreenId[] = [
    'mapping',
    'rules',
    'dashboard',
    'checker',
    'tqs',
    'revision',
    'benchmark',
    'export',
  ];

  const currentScreenIndex = screenOrder.indexOf(currentScreen);

  const goToNextScreen = () => {
    if (currentScreenIndex < screenOrder.length - 1) {
      setCurrentScreen(screenOrder[currentScreenIndex + 1]);
    }
  };

  const goToPrevScreen = () => {
    if (currentScreenIndex > 0) {
      setCurrentScreen(screenOrder[currentScreenIndex - 1]);
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#060D08] text-[#E2ECE5]">
      {/* Left Sidebar */}
      <Sidebar
        currentScreen={currentScreen}
        onSelectScreen={(s) => setCurrentScreen(s)}
        violationsCount={
          tamperedViolations !== null
            ? tamperedViolations.length
            : (allocResultA?.violations.length || 0)
        }
        tqCount={tqs.length}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        {/* Top Navbar */}
        <Navbar
          currentScreen={currentScreen}
          onRunDemo={initDemoRun}
          onReSolve={handleReSolve}
          isSolving={isSolving}
          isDemoActive={isDemoActive}
        />

        {/* Screen Scrollable Body */}
        <main className="flex-1 overflow-y-auto p-6">
          <div className="max-w-[1600px] mx-auto">
            {currentScreen === 'mapping' && (
              <ScreenUploadMapping
                onProceedToAllocation={() => setCurrentScreen('dashboard')}
                onDataLoaded={() => handleReSolve()}
              />
            )}

            {currentScreen === 'rules' && (
              <ScreenRulePanel onRulesChanged={handleReSolve} />
            )}

            {currentScreen === 'dashboard' && (
              <ScreenAllocationDashboard
                allocResult={allocResultA}
                onReSolve={handleReSolve}
                isSolving={isSolving}
              />
            )}

            {currentScreen === 'checker' && (
              <ScreenCheckerReport
                allocResult={allocResultA}
                onRefreshClean={handleReSolve}
                onPlantTampered={(viols) => setTamperedViolations(viols)}
              />
            )}

            {currentScreen === 'tqs' && (
              <ScreenTQList
                tqs={tqs}
                onLoadAdversarial={handleLoadAdversarial}
                isLoading={isSolving}
              />
            )}

            {currentScreen === 'revision' && (
              <ScreenRevisionDiff
                allocResultB={allocResultB}
                onGenerateRevB={handleGenerateRevB}
                onUploadRevB={handleUploadRevB}
                isLoading={isSolving}
              />
            )}

            {currentScreen === 'benchmark' && <ScreenBenchmark />}

            {currentScreen === 'export' && (
              <ScreenExport allocResult={allocResultA} />
            )}
          </div>
        </main>

        {/* Bottom Navigation Walkthrough Bar (Screenshot & Demo Helper) */}
        <footer className="h-12 bg-[#07110A] border-t border-[#183622] px-6 flex items-center justify-between text-xs font-mono shrink-0 select-none">
          <div className="flex items-center gap-3">
            <span className="text-[#6B8E78]">SCREEN {currentScreenIndex + 1} OF 8:</span>
            <span className="font-bold text-white tracking-wide uppercase">
              {currentScreen.replace('_', ' ')}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={goToPrevScreen}
              disabled={currentScreenIndex === 0}
              className="px-3 py-1 rounded bg-[#0E1E14] hover:bg-[#153120] border border-[#1A3D25] text-[#A7C7B3] hover:text-white flex items-center gap-1 disabled:opacity-30 disabled:pointer-events-none transition-all"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>PREVIOUS</span>
            </button>

            <button
              onClick={goToNextScreen}
              disabled={currentScreenIndex === screenOrder.length - 1}
              className="px-3 py-1 rounded bg-[#122E1A] hover:bg-[#1A4226] border border-[#4ADE80] text-[#5CFF7A] font-semibold flex items-center gap-1 shadow-neon disabled:opacity-30 disabled:pointer-events-none transition-all"
            >
              <span>NEXT SCREEN</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
};
