export interface Signal {
  tag: string;
  io_type: string;
  subtype?: string | null;
  cable: string;
  pair: number;
  group?: string | null;
  seg?: string | null;
}

export interface AllocatedSlot {
  tag?: string | null;
  cable: string;
  pair: number;
  cabinet: number;
  cioc: number;
  baseplate: number;
  slot: number;
  global_slot: number;
  cabinet_name: string;
  cioc_name: string;
  baseplate_name: string;
  charm: string;
  terminal_block: string;
  io_type?: string | null;
  subtype?: string | null;
  group?: string | null;
  seg?: string | null;
  is_spare: boolean;
}

export interface Violation {
  rule_id: string;
  rule_name: string;
  tag?: string | null;
  cable?: string | null;
  cabinet?: number | null;
  cioc?: number | null;
  baseplate?: number | null;
  slot?: number | null;
  message: string;
}

export interface TQ {
  id: string;
  kind: 'data' | 'rule_conflict' | 'capacity' | 'hardware';
  items: string[];
  rule_ids: string[];
  message: string;
  tags?: string[];
  rows?: number[];
  options?: string[];
  mus?: string[];
}

export interface RevisionMoveDetail {
  tag: string;
  cable: string;
  io_type: string;
  group?: string | null;
  old_location: string;
  new_location: string;
  forcing_rule: string;
  reason: string;
}

export interface RevisionSummary {
  added_count: number;
  deleted_count: number;
  changed_count: number;
  moved_count: number;
  unchanged_count: number;
  affected_cabinets: number[];
  moves_ours: number;
  moves_from_scratch: number;
  moves_detail: RevisionMoveDetail[];
}

export interface AllocResult {
  success: boolean;
  allocations: AllocatedSlot[];
  violations: Violation[];
  tqs: TQ[];
  cabinets_used: number;
  slots_used: number;
  total_slots_available: number;
  coverage_pct: number;
  spare_pct_actual: number;
  runtime_s: number;
  lower_bound_cabinets: number;
  solver_status: string;
  rev_summary?: RevisionSummary | null;
}

export const API = {
  async getHealth() {
    const res = await fetch('/api/health');
    return res.json();
  },

  async getRules() {
    const res = await fetch('/api/rules');
    return res.json();
  },

  async getRulesSchema() {
    const res = await fetch('/api/rules/schema');
    return res.json();
  },

  async validateRules(payload: { rules?: any; yaml?: string }): Promise<{ ok: boolean; errors: string[] }> {
    const res = await fetch('/api/rules/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return res.json();
  },

  async updateRules(payload: { rules?: any; yaml?: string }) {
    const res = await fetch('/api/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) {
      const detail = body.detail;
      const errors: string[] =
        detail && detail.schema_errors ? detail.schema_errors
          : typeof detail === 'string' ? [detail] : ['Rule document rejected by schema'];
      const err: any = new Error('Rule set rejected by schema');
      err.schemaErrors = errors;
      throw err;
    }
    return body;
  },

  async parseNLRule(text: string, allowLlm: boolean = false) {
    const res = await fetch('/api/rules/parse-nl', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, allow_llm: allowLlm }),
    });
    return res.json();
  },

  async explainSignal(tag: string) {
    const res = await fetch(`/api/explain/${encodeURIComponent(tag)}`);
    if (!res.ok) throw new Error((await res.json()).detail || 'Explain failed');
    return res.json();
  },

  async whatIf(payload: {
    kind: string;
    signals_extra?: any[];
    rules?: any;
    spare_percentage?: number;
  }) {
    const res = await fetch('/api/what-if', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'What-if failed');
    return body;
  },

  async generateDataset(params: {
    n_signals?: number;
    seed?: number;
    fuzz_headers?: boolean;
    inject_defects?: boolean;
    defect_types?: string[];
  }) {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    return res.json();
  },

  async mapColumns(columns: string[]) {
    const res = await fetch('/api/map-columns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ columns }),
    });
    return res.json();
  },

  async uploadIOList(file: File) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    if (!res.ok) throw new Error((await res.json()).detail || 'Upload failed');
    return res.json();
  },

  async confirmMapping(payload: {
    upload_id: string;
    sheet?: string;
    header_row?: number;
    overrides?: Record<string, string | null>;
    profile_name?: string;
  }) {
    const res = await fetch('/api/mapping/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error((await res.json()).detail || 'Confirm failed');
    return res.json();
  },

  async listMappingProfiles() {
    const res = await fetch('/api/mapping/profiles');
    return res.json();
  },

  async allocate(params: {
    signals?: Signal[];
    cable_sizes?: Record<string, number>;
    rules?: any;
    use_rev_a_as_hints?: boolean;
  }): Promise<AllocResult> {
    const res = await fetch('/api/allocate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    return res.json();
  },

  async plantViolation(plant_type: string) {
    const res = await fetch('/api/checker/plant-violation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plant_type }),
    });
    return res.json();
  },

  async reviseRevB(file: File) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/revise', { method: 'POST', body: form });
    if (!res.ok) {
      const body = await res.json();
      throw new Error(typeof body.detail === 'string' ? body.detail : 'Revise failed');
    }
    return res.json();
  },

  async generateRevB(params: {
    add_pct?: number;
    del_pct?: number;
    type_pct?: number;
    recable_pct?: number;
  }) {
    const query = new URLSearchParams({
      add_pct: String(params.add_pct ?? 0.05),
      del_pct: String(params.del_pct ?? 0.02),
      type_pct: String(params.type_pct ?? 0.015),
      recable_pct: String(params.recable_pct ?? 0.01),
    });
    const res = await fetch(`/api/revision/generate-b?${query.toString()}`, {
      method: 'POST',
    });
    return res.json();
  },

  async runBenchmark(signal_count: number = 1000, seed: number = 42) {
    const res = await fetch('/api/benchmark/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ signal_count, seed }),
    });
    return res.json();
  },

  async benchLatest() {
    const res = await fetch('/api/bench/latest');
    return res.json();
  },

  async initDemo() {
    const res = await fetch('/api/demo-init');
    return res.json();
  },

  async downloadExcel() {
    const res = await fetch('/api/export/excel', {
      method: 'POST',
    });
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'CHARMSAT_DeltaV_IO_Allocation.xlsx';
    document.body.appendChild(a);
    a.click();
    a.remove();
  },
};
