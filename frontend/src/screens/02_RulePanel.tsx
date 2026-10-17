import React, { useState, useEffect } from 'react';
import { Sliders, Save, Sparkles, Plus, Code, CheckCircle, AlertTriangle, ShieldCheck } from 'lucide-react';
import { API } from '../api';

interface RulePanelProps {
  onRulesChanged: () => void;
}

export const ScreenRulePanel: React.FC<RulePanelProps> = ({ onRulesChanged }) => {
  const [rules, setRules] = useState<any | null>(null);
  const [yamlText, setYamlText] = useState<string>('');
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);
  const [saveErrors, setSaveErrors] = useState<string[]>([]);
  const [schemaErrors, setSchemaErrors] = useState<string[]>([]);
  const [yamlValid, setYamlValid] = useState<boolean | null>(null);
  // Which editor the user touched last: the YAML box or the rule cards/form.
  const [activeEditor, setActiveEditor] = useState<'yaml' | 'form'>('form');

  // Natural Language Rule Assistant State
  const [nlInput, setNlInput] = useState<string>('');
  const [nlResult, setNlResult] = useState<any | null>(null);
  const [isParsingNL, setIsParsingNL] = useState<boolean>(false);
  const [useLlm, setUseLlm] = useState<boolean>(false);

  // Generic Rule Form State
  const [newRuleRel, setNewRuleRel] = useState<string>('same');
  const [newRuleAttr, setNewRuleAttr] = useState<string>('group');
  const [newRuleLevel, setNewRuleLevel] = useState<string>('cabinet');
  const [newRuleK, setNewRuleK] = useState<number>(1);
  const [newRuleClasses, setNewRuleClasses] = useState<string>('');

  useEffect(() => {
    fetchRules();
  }, []);

  // Live schema validation of the YAML box (P3): every rule document is checked
  // against the same JSON Schema the backend enforces.
  useEffect(() => {
    if (!yamlText.trim()) return;
    const handle = setTimeout(async () => {
      try {
        const res = await API.validateRules({ yaml: yamlText });
        setYamlValid(res.ok);
        setSchemaErrors(res.errors || []);
      } catch {
        setYamlValid(null);
      }
    }, 400);
    return () => clearTimeout(handle);
  }, [yamlText]);

  const fetchRules = async () => {
    try {
      const data = await API.getRules();
      setRules(data.rules);
      setYamlText(data.yaml);
    } catch (err) {
      console.error(err);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setSaveErrors([]);
    try {
      // The editor the user last touched is the source of truth on save.
      const payload = activeEditor === 'yaml' ? { yaml: yamlText } : { rules };
      const res = await API.updateRules(payload);
      setRules(res.rules);
      setYamlText(res.yaml);
      setYamlValid(true);
      setSchemaErrors([]);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
      onRulesChanged();
    } catch (err: any) {
      setSaveErrors(err?.schemaErrors || [err?.message || 'Save failed']);
    } finally {
      setIsSaving(false);
    }
  };

  const applyFormRules = (updated: any) => {
    setRules(updated);
    setActiveEditor('form');
    API.validateRules({ rules: updated })
      .then((res) => {
        setYamlValid(res.ok);
        setSchemaErrors(res.errors || []);
      })
      .catch(() => {});
  };

  const handleParseNL = async () => {
    if (!nlInput.trim()) return;
    setIsParsingNL(true);
    try {
      const res = await API.parseNLRule(nlInput, useLlm);
      setNlResult(res);
      if (res.draft && rules) {
        const updated = { ...rules };
        updated.custom_rules = [...(updated.custom_rules || []), res.draft];
        applyFormRules(updated);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsParsingNL(false);
    }
  };

  const handleAddCustomRule = () => {
    if (!rules) return;
    const classes = newRuleClasses
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const newRule: any = {
      id: `RULE-CUSTOM-${(rules.custom_rules?.length || 0) + 1}`,
      name: `Custom: ${newRuleRel} ${newRuleAttr} per ${newRuleLevel}`,
      enabled: true,
      relation: newRuleRel,
      attribute: newRuleAttr,
      level: newRuleLevel,
      description: `Enforces that all signals with matching ${newRuleAttr} must share the ${newRuleRel} ${newRuleLevel}.`,
    };
    if (newRuleRel === 'at_most_k') newRule.k_value = newRuleK;
    if (newRuleRel === 'different' && classes.length) newRule.classes = classes;
    const updated = { ...rules, custom_rules: [...(rules.custom_rules || []), newRule] };
    applyFormRules(updated);
  };

  if (!rules) {
    return <div className="text-xs font-mono text-[#6B8E78]">Loading Rule Set Configuration...</div>;
  }

  return (
    <div className="space-y-6">
      {/* Top Banner & Save Button */}
      <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-5 shadow-lg flex items-center justify-between">
        <div>
          <h3 className="text-base font-display font-bold text-white tracking-wide flex items-center gap-2">
            <Sliders className="w-5 h-5 text-[#4ADE80]" />
            RULE COMPILATION PANEL & AMBIGUITY RESOLVER
          </h3>
          <p className="text-xs font-mono text-[#6B8E78] mt-1">
            Rules compile directly from YAML into CP-SAT constraints. Ambiguities are exposed as parameters, not silently hardcoded.
          </p>
        </div>

        <button
          onClick={handleSave}
          disabled={isSaving}
          className="px-5 py-2.5 rounded-lg bg-[#143B22] hover:bg-[#1C5230] border border-[#4ADE80] text-xs font-mono font-bold text-[#5CFF7A] shadow-neon flex items-center gap-2 transition-all"
        >
          {saveSuccess ? (
            <>
              <CheckCircle className="w-4 h-4 text-[#5CFF7A]" />
              <span>SAVED & RE-COMPILED!</span>
            </>
          ) : (
            <>
              <Save className="w-4 h-4 text-[#5CFF7A]" />
              <span>SAVE RULE SET</span>
            </>
          )}
        </button>
      </div>

      {saveErrors.length > 0 && (
        <div className="bg-[#2A1210] border border-[#7F1D1D] rounded-xl p-3 text-[11px] font-mono text-[#FCA5A5]">
          <div className="font-bold flex items-center gap-1.5 mb-1">
            <AlertTriangle className="w-4 h-4" />
            RULE SET REJECTED BY SCHEMA — nothing was applied
          </div>
          <ul className="list-disc list-inside space-y-0.5">
            {saveErrors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Main Grid: Rule Cards & Live YAML */}
      <div className="grid grid-cols-3 gap-6">
        {/* Left Column: Core Rule Cards (2 Cols) */}
        <div className="col-span-2 space-y-4" onClickCapture={() => setActiveEditor('form')}>
          {/* Rule 1: A/B Segregation */}
          <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-4 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#102E1B] text-[#4ADE80] border border-[#1E4D2C]">
                  RULE-01
                </span>
                <span className="text-sm font-mono font-bold text-white">A/B Train Segregation</span>
              </div>
              <input
                type="checkbox"
                checked={rules.ab_segregation.enabled}
                onChange={(e) =>
                  setRules({
                    ...rules,
                    ab_segregation: { ...rules.ab_segregation, enabled: e.target.checked },
                  })
                }
                className="accent-[#4ADE80] w-4 h-4 rounded cursor-pointer"
              />
            </div>
            <p className="text-xs font-mono text-[#6B8E78]">{rules.ab_segregation.description}</p>
            <div className="flex items-center gap-3 pt-2 border-t border-[#163120] text-xs font-mono">
              <span className="text-[#A7C7B3]">Segregation Hardware Level:</span>
              <select
                value={rules.ab_segregation.level}
                onChange={(e) =>
                  setRules({
                    ...rules,
                    ab_segregation: { ...rules.ab_segregation, level: e.target.value },
                  })
                }
                className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2.5 py-1 text-white text-xs focus:border-[#4ADE80]"
              >
                <option value="cioc">CIOC Level (Default DeltaV)</option>
                <option value="cabinet">Cabinet Level</option>
                <option value="baseplate">Baseplate Level</option>
              </select>
            </div>
          </div>

          {/* Rule 2: Cable Contiguity & Baseplate Straddling */}
          <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-4 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#102E1B] text-[#4ADE80] border border-[#1E4D2C]">
                  RULE-02
                </span>
                <span className="text-sm font-mono font-bold text-white">Cable Contiguity & Boundary Straddling</span>
              </div>
              <input
                type="checkbox"
                checked={rules.cable_contiguity.enabled}
                onChange={(e) =>
                  setRules({
                    ...rules,
                    cable_contiguity: { ...rules.cable_contiguity, enabled: e.target.checked },
                  })
                }
                className="accent-[#4ADE80] w-4 h-4 rounded cursor-pointer"
              />
            </div>
            <p className="text-xs font-mono text-[#6B8E78]">{rules.cable_contiguity.description}</p>
            <div className="grid grid-cols-2 gap-3 pt-2 border-t border-[#163120] text-xs font-mono">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={rules.cable_contiguity.allow_boundary_crossing_small}
                  onChange={(e) =>
                    setRules({
                      ...rules,
                      cable_contiguity: {
                        ...rules.cable_contiguity,
                        allow_boundary_crossing_small: e.target.checked,
                      },
                    })
                  }
                  className="accent-[#4ADE80] w-4 h-4 rounded"
                />
                <span className="text-[#A7C7B3]">Allow Small Cable Straddling (6/2 Pairs)</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={rules.cable_contiguity.strict_pair_ordering}
                  onChange={(e) =>
                    setRules({
                      ...rules,
                      cable_contiguity: {
                        ...rules.cable_contiguity,
                        strict_pair_ordering: e.target.checked,
                      },
                    })
                  }
                  className="accent-[#4ADE80] w-4 h-4 rounded"
                />
                <span className="text-[#A7C7B3]">Strict Sequential Pair Order</span>
              </label>
            </div>
          </div>

          {/* Rule 3: Group Cohesion */}
          <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-4 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#102E1B] text-[#4ADE80] border border-[#1E4D2C]">
                  RULE-03
                </span>
                <span className="text-sm font-mono font-bold text-white">Group Cabinet Cohesion</span>
              </div>
              <input
                type="checkbox"
                checked={rules.group_cohesion.enabled}
                onChange={(e) =>
                  setRules({
                    ...rules,
                    group_cohesion: { ...rules.group_cohesion, enabled: e.target.checked },
                  })
                }
                className="accent-[#4ADE80] w-4 h-4 rounded cursor-pointer"
              />
            </div>
            <p className="text-xs font-mono text-[#6B8E78]">{rules.group_cohesion.description}</p>
            <div className="flex items-center justify-between pt-2 border-t border-[#163120] text-xs font-mono">
              <div className="flex items-center gap-2">
                <span className="text-[#A7C7B3]">Cohesion Level:</span>
                <span className="text-white font-bold">Cabinet Unit</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[#A7C7B3]">Sequence Penalty Weight:</span>
                <input
                  type="number"
                  value={rules.group_cohesion.soft_sequence_weight}
                  onChange={(e) =>
                    setRules({
                      ...rules,
                      group_cohesion: {
                        ...rules.group_cohesion,
                        soft_sequence_weight: Number(e.target.value),
                      },
                    })
                  }
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2 py-0.5 w-16 text-white text-xs"
                />
              </div>
            </div>
          </div>

          {/* Rule 4: Spare Capacity Margin */}
          <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-4 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#102E1B] text-[#4ADE80] border border-[#1E4D2C]">
                  RULE-04
                </span>
                <span className="text-sm font-mono font-bold text-white">Cabinet Spare Capacity Margin</span>
              </div>
              <input
                type="checkbox"
                checked={rules.spare_capacity.enabled}
                onChange={(e) =>
                  setRules({
                    ...rules,
                    spare_capacity: { ...rules.spare_capacity, enabled: e.target.checked },
                  })
                }
                className="accent-[#4ADE80] w-4 h-4 rounded cursor-pointer"
              />
            </div>
            <p className="text-xs font-mono text-[#6B8E78]">{rules.spare_capacity.description}</p>
            <div className="flex items-center gap-4 pt-2 border-t border-[#163120] text-xs font-mono">
              <span className="text-[#A7C7B3]">Spare Percentage:</span>
              <input
                type="range"
                min="0"
                max="30"
                step="5"
                value={rules.spare_capacity.spare_percentage}
                onChange={(e) =>
                  setRules({
                    ...rules,
                    spare_capacity: {
                      ...rules.spare_capacity,
                      spare_percentage: Number(e.target.value),
                    },
                  })
                }
                className="accent-[#4ADE80] w-48"
              />
              <span className="text-white font-bold text-sm bg-[#122A1C] px-2 py-0.5 rounded border border-[#1F4A2D]">
                {rules.spare_capacity.spare_percentage}%
              </span>
              <span className="text-[10px] text-[#587B64]">
                (Max used slots: {Math.floor(384 * (1 - rules.spare_capacity.spare_percentage / 100))} / 384)
              </span>
            </div>
          </div>

          {/* Rule 7: Asset Naming Convention */}
          <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-4 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#102E1B] text-[#4ADE80] border border-[#1E4D2C]">
                  RULE-07
                </span>
                <span className="text-sm font-mono font-bold text-white">Hardware Naming Templates</span>
              </div>
            </div>
            <p className="text-xs font-mono text-[#6B8E78]">{rules.naming_patterns.description}</p>
            <div className="grid grid-cols-3 gap-3 pt-2 border-t border-[#163120] text-xs font-mono">
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">Cabinet Pattern</label>
                <input
                  type="text"
                  value={rules.naming_patterns.cabinet}
                  onChange={(e) =>
                    setRules({
                      ...rules,
                      naming_patterns: { ...rules.naming_patterns, cabinet: e.target.value },
                    })
                  }
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2.5 py-1 text-white text-xs w-full"
                />
              </div>
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">CIOC Pattern</label>
                <input
                  type="text"
                  value={rules.naming_patterns.cioc}
                  onChange={(e) =>
                    setRules({
                      ...rules,
                      naming_patterns: { ...rules.naming_patterns, cioc: e.target.value },
                    })
                  }
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2.5 py-1 text-white text-xs w-full"
                />
              </div>
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">Baseplate Pattern</label>
                <input
                  type="text"
                  value={rules.naming_patterns.baseplate}
                  onChange={(e) =>
                    setRules({
                      ...rules,
                      naming_patterns: { ...rules.naming_patterns, baseplate: e.target.value },
                    })
                  }
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2.5 py-1 text-white text-xs w-full"
                />
              </div>
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">CHARM Pattern</label>
                <input
                  type="text"
                  value={rules.naming_patterns.charm}
                  onChange={(e) =>
                    setRules({
                      ...rules,
                      naming_patterns: { ...rules.naming_patterns, charm: e.target.value },
                    })
                  }
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2.5 py-1 text-white text-xs w-full"
                />
              </div>
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">Area</label>
                <input
                  type="text"
                  value={rules.naming_patterns.area}
                  onChange={(e) =>
                    setRules({
                      ...rules,
                      naming_patterns: { ...rules.naming_patterns, area: e.target.value },
                    })
                  }
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2.5 py-1 text-white text-xs w-full"
                />
              </div>
              <div className="text-[10px] text-[#6B8E78] self-end">
                Tokens: area, cab, cioc, cioc_global, bp, bp_global, slot, cab_name, cioc_name, baseplate_name
              </div>
            </div>
          </div>

          {/* Generic Add Rule Form */}
          <div className="bg-[#09150E] border border-[#1E3A2B] rounded-xl p-4 shadow-sm space-y-3">
            <h4 className="text-xs font-mono font-bold text-white flex items-center gap-2">
              <Plus className="w-4 h-4 text-[#4ADE80]" />
              ADD NEW RULE (GENERIC TEMPLATE)
            </h4>
            <div className="grid grid-cols-4 gap-3 text-xs font-mono">
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">Relation</label>
                <select
                  value={newRuleRel}
                  onChange={(e) => setNewRuleRel(e.target.value)}
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2 py-1 text-white w-full"
                >
                  <option value="same">SAME</option>
                  <option value="different">DIFFERENT</option>
                  <option value="at_most_k">AT MOST K</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">Attribute</label>
                <select
                  value={newRuleAttr}
                  onChange={(e) => setNewRuleAttr(e.target.value)}
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2 py-1 text-white w-full"
                >
                  <option value="group">Group / Unit Area</option>
                  <option value="seg">Train A / B</option>
                  <option value="io_type">IO Signal Type</option>
                  <option value="subtype">DO Subtype</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">Hardware Level</label>
                <select
                  value={newRuleLevel}
                  onChange={(e) => setNewRuleLevel(e.target.value)}
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2 py-1 text-white w-full"
                >
                  <option value="cabinet">Cabinet</option>
                  <option value="cioc">CIOC</option>
                  <option value="baseplate">Baseplate</option>
                </select>
              </div>
              <div className="flex items-end">
                <button
                  onClick={handleAddCustomRule}
                  className="w-full py-1.5 rounded bg-[#122E1A] hover:bg-[#1A4226] border border-[#4ADE80] text-[#5CFF7A] text-xs font-bold transition-all"
                >
                  + ADD TO COMPILE
                </button>
              </div>
            </div>
            <div className="grid grid-cols-4 gap-3 text-xs font-mono">
              <div>
                <label className="text-[10px] text-[#6B8E78] block mb-1">
                  K (for AT MOST K)
                </label>
                <input
                  type="number"
                  min={1}
                  value={newRuleK}
                  disabled={newRuleRel !== 'at_most_k'}
                  onChange={(e) => setNewRuleK(Number(e.target.value))}
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2 py-1 text-white w-full disabled:opacity-40"
                />
              </div>
              <div className="col-span-3">
                <label className="text-[10px] text-[#6B8E78] block mb-1">
                  Classes for DIFFERENT (comma-separated; blank = every value must differ)
                </label>
                <input
                  type="text"
                  value={newRuleClasses}
                  disabled={newRuleRel !== 'different'}
                  placeholder="e.g. A,B"
                  onChange={(e) => setNewRuleClasses(e.target.value)}
                  className="bg-[#0C1A11] border border-[#1E3E2B] rounded px-2 py-1 text-white w-full disabled:opacity-40"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Natural Language Rule Assistant & Live YAML Preview (1 Col) */}
        <div className="space-y-4">
          {/* Natural Language Rule Assistant Card */}
          <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-4 shadow-sm space-y-3">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-[#38BDF8]" />
              <h4 className="text-xs font-mono font-bold text-white">NATURAL LANGUAGE RULE ASSISTANT</h4>
            </div>
            <div className="p-2 rounded bg-[#09150E] border border-[#193323] text-[10px] font-mono text-[#4ADE80] flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
              <span>ASSISTANT BANNER: Wording compiler only. AI NEVER places signals.</span>
            </div>
            <p className="text-[11px] font-mono text-[#6B8E78]">
              Type an industrial requirement in plain English. The assistant drafts a typed rule configuration.
            </p>
            <label className="flex items-start gap-2 cursor-pointer text-[10px] font-mono">
              <input
                type="checkbox"
                checked={useLlm}
                onChange={(e) => setUseLlm(e.target.checked)}
                className="accent-[#38BDF8] w-3.5 h-3.5 rounded mt-0.5"
              />
              <span className="text-[#A7C7B3]">
                Use optional LLM drafter for messy/ambiguous sentences
                <span className="block text-[#587B64]">
                  Off by default. Needs an API key; sends only this sentence, never IO data. Drafts are
                  schema-checked and confirmed by you.
                </span>
              </span>
            </label>
            <div className="space-y-2">
              <textarea
                value={nlInput}
                onChange={(e) => setNlInput(e.target.value)}
                placeholder="e.g. Segregate Train A and Train B signals at CIOC level..."
                className="w-full h-20 bg-[#07100A] border border-[#1E3E2B] rounded-lg p-2.5 text-xs font-mono text-white placeholder-[#547560] focus:border-[#4ADE80] focus:outline-none"
              />
              <button
                onClick={handleParseNL}
                disabled={isParsingNL || !nlInput.trim()}
                className="w-full py-1.5 rounded bg-[#102919] hover:bg-[#183E26] border border-[#38BDF8] text-[#38BDF8] text-xs font-mono font-bold transition-all disabled:opacity-40"
              >
                {isParsingNL ? 'COMPILING DRAFT...' : 'COMPILE TO RULE DRAFT'}
              </button>
            </div>
            {nlResult && (
              <div className="p-2.5 rounded bg-[#0A1810] border border-[#1E4D2C] text-[10px] font-mono text-[#A7C7B3] space-y-1">
                <div className={nlResult.schema_ok ? 'text-[#5CFF7A] font-bold' : 'text-[#FCA5A5] font-bold'}>
                  {nlResult.schema_ok ? '✓ Draft added — schema-valid' : '✗ Draft failed schema validation'}
                </div>
                <div className="flex items-center gap-2 text-[9px]">
                  <span className={`px-1.5 py-0.5 rounded border ${
                    nlResult.source === 'llm'
                      ? 'bg-[#0E2A18] text-[#7DD3FC] border-[#2A5A6B]'
                      : 'bg-[#102B19] text-[#4ADE80] border-[#1E4D2C]'
                  }`}>
                    {nlResult.source === 'llm' ? 'LLM DRAFT (non-reproducible)' : 'OFFLINE PARSER'}
                  </span>
                  {typeof nlResult.confidence === 'number' && (
                    <span className="text-[#587B64]">confidence {Math.round(nlResult.confidence * 100)}%</span>
                  )}
                </div>
                <div>{nlResult.message}</div>
                {nlResult.schema_errors?.length > 0 && (
                  <ul className="list-disc list-inside text-[#FCA5A5]">
                    {nlResult.schema_errors.map((e: string, i: number) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                )}
                <div className="text-[#587B64]">
                  Review on the left, then SAVE to apply. The assistant never places signals.
                </div>
              </div>
            )}
          </div>

          {/* Live YAML Preview */}
          <div className="bg-[#0B1710] border border-[#1E3A2B] rounded-xl p-4 shadow-sm space-y-2 flex flex-col h-[400px]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-bold text-white flex items-center gap-2">
                <Code className="w-3.5 h-3.5 text-[#4ADE80]" />
                LIVE YAML RULE SPEC
              </span>
              <span className="text-[10px] font-mono text-[#587B64]">JSON Schema enforced</span>
            </div>
            <div
              className={`p-1.5 rounded border text-[10px] font-mono flex items-center gap-1.5 ${
                yamlValid === false
                  ? 'bg-[#2A1210] border-[#7F1D1D] text-[#FCA5A5]'
                  : 'bg-[#0A1810] border-[#1E4D2C] text-[#5CFF7A]'
              }`}
            >
              {yamlValid === false ? (
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              ) : (
                <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
              )}
              <span>
                {yamlValid === false
                  ? `SCHEMA REJECTED — ${schemaErrors.length} error(s)`
                  : yamlValid === true
                  ? 'SCHEMA VALID — compiles to CP-SAT constraints'
                  : 'SCHEMA STATUS — awaiting validation'}
              </span>
            </div>
            {yamlValid === false && (
              <ul className="max-h-24 overflow-y-auto text-[10px] font-mono text-[#FCA5A5] space-y-0.5 list-disc list-inside">
                {schemaErrors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            )}
            <textarea
              value={yamlText}
              onChange={(e) => {
                setYamlText(e.target.value);
                setActiveEditor('yaml');
              }}
              className="flex-1 w-full bg-[#060D08] border border-[#163120] rounded-lg p-2.5 text-[10px] font-mono text-[#5CFF7A] focus:outline-none focus:border-[#4ADE80] resize-none"
            />
          </div>
        </div>
      </div>
    </div>
  );
};
