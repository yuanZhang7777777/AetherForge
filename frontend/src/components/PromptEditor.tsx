import { useEffect, useRef, useState } from "react";
import { slotLabel } from "../labels";
import type { ClusterUpdateInput, ClusterUpdateResult, ProductPrompt, ProductSku, PromptFact, RuleGateMessage } from "../types";

const defaultPrompts = [
  "标准白底产品图",
  "核心卖点图",
  "细节特写图",
  "真实使用场景图",
  "痛点解决图",
  "尺寸材质图",
  "使用步骤图",
  "生活方式图",
  "品质信任图",
].map((slot, index) => ({ slotOrder: index + 1, slot, text: "" }));

// 阶段加权进度：N1=10% N2=80%(=10+70) N3=100%，当前阶段显示其累计百分比下限
const stagePercent: Record<string, number> = {
  N1: 10,
  N2: 80,
  N3: 100,
};

type PromptDraftItem = {
  slotOrder: number;
  slot: string;
  text: string; // 可编辑内容：双语=中文策划，legacy=最终英文
  finalText: string; // 出图用最终英文（双语模式只读展示）
  hasDisplay: boolean; // 是否为双语（服务器有 displayPrompt）
  readOnly: boolean;
};

type PromptDraft = {
  prompts: PromptDraftItem[];
};

function visiblePromptText(prompt: ProductPrompt) {
  const displayPrompt = prompt.displayPrompt?.trim() ?? "";
  return displayPrompt || prompt.text.trim();
}

function fallbackChinesePrompt(order: number) {
  return [
    "突出完整商品，干净白底，方便上架。",
    "把最容易打动买家的核心好处讲清楚。",
    "放大关键细节并加引线标注，让买家看到做工品质。",
    "展示商品被真实使用的场景，动作自然。",
    "用对比或前后对照展示商品如何解决一个使用痛点。",
    "展示商品尺寸与材质质感。",
    "分 1–4 步展示使用或操作流程。",
    "营造拥有它之后的生活方式氛围。",
    "展示商品陈列状态，强调品质与做工。",
  ][order - 1] ?? `第 ${order} 张图的提示词策划。`;
}

function promptsFromSku(sku: ProductSku) {
  if (sku.prompts?.length) return sku.prompts;
  const promptsByOrder = new Map((sku.prompts ?? []).map((prompt) => [prompt.slotOrder, prompt]));
  return defaultPrompts.map((fallback) => ({ ...fallback, ...promptsByOrder.get(fallback.slotOrder) }));
}

function draftFromSku(sku: ProductSku): PromptDraft {
  return {
    prompts: promptsFromSku(sku).map((prompt) => ({
      slotOrder: prompt.slotOrder,
      slot: prompt.slot,
      text: visiblePromptText(prompt),
      finalText: prompt.text ?? "",
      hasDisplay: Boolean(prompt.displayPrompt?.trim()),
      readOnly: Boolean(prompt.readOnly),
    })),
  };
}

function ruleMessage(value: RuleGateMessage) {
  const raw = typeof value === "string" ? value : value.message ?? value.reason ?? value.statement ?? value.rule_id ?? "需人工复核";
  const labels: Record<string, string> = {
    "copy.high_risk_claim": "图片文案包含医疗、认证、价格折扣或 100% 承诺，生成后请人工确认",
    "semantic_n7_review_warning": "系统建议人工复核，但不会阻止出图",
    "copy.literal_lock": "图片文案可能没有逐字匹配，生成后请重点审核文字",
    "copy.unknown_fact_ref": "图片文案引用了未确认信息，生成后请重点审核",
    "prompt.visible_text_max_three_lines": "图片文案超过 3 行，生成后请重点审核",
    "hero.no_added_text": "白底图建议不加文字，生成后请重点审核",
  };
  if (raw.startsWith("n7.soft_block:")) return `系统建议人工复核：${labels[raw.slice("n7.soft_block:".length)] ?? raw.slice("n7.soft_block:".length)}`;
  if (/no_added_text|no_digital_rendering/i.test(raw)) return "平台规则提示：生成后请人工确认是否适合上架";
  if (/image_role|visible product identity|observed_identity|N2|evidence_refs|fact_refs|reference_plan|schema|JSON|must be/i.test(raw)) return "系统结构化识别提示：已继续出图，结果需人工复核";
  if (/price|discount/i.test(raw)) return "价格/折扣";
  if (/certification|certified/i.test(raw)) return "认证/奖项";
  if (/medical|efficacy|cure/i.test(raw)) return "医疗/疗效";
  if (/100/.test(raw)) return "100% 或绝对承诺";
  if (labels[raw]) return labels[raw];
  if (typeof value === "string") return raw;
  return value.message ?? value.reason ?? value.statement ?? value.rule_id ?? "需人工复核";
}

function quietGateMessage(value: RuleGateMessage) {
  const raw = typeof value === "string" ? value : value.message ?? value.reason ?? value.statement ?? value.rule_id ?? "";
  const combined = `${raw} ${ruleMessage(value)}`;
  return /copy\.high_risk_claim|copy\.literal_lock|semantic_n7_review_warning|price|certification|medical|discount|high.?risk|结构化识别|人工复核|复核|高风险|未确认|缺少确认|推断|消费者文案|发布前|价格|折扣|认证|奖项|医疗|疗效|材质/i.test(combined);
}

function evidenceLabel(value: string) {
  if (value.startsWith("asset:")) return "上传图片";
  if (value.startsWith("observation:")) return "图片识别";
  if (value.startsWith("erp:")) return "ERP资料";
  if (value === "confirmed_points") return "确认点";
  return value;
}

function recognitionText(value: string) {
  const raw = String(value || "").trim();
  if (!raw || raw === "confirmed_points") return "";
  const translated = raw
    .replace(/Yellow plush toy/gi, "黄色毛绒玩偶")
    .replace(/large round head/gi, "圆形头部")
    .replace(/two big round eyes/gi, "两只大圆眼睛")
    .replace(/round black eyes/gi, "圆形黑眼睛")
    .replace(/short arms/gi, "短小手臂")
    .replace(/short legs/gi, "短小腿部")
    .replace(/plush texture/gi, "毛绒质感")
    .replace(/yellow plush/gi, "黄色毛绒")
    .replace(/plush toy/gi, "毛绒玩偶")
    .replace(/visible wooden-handled spoons with tray/gi, "木柄餐具套装")
    .replace(/wooden[- ]handled cutlery/gi, "木柄餐具")
    .replace(/wooden[- ]handled spoons?/gi, "木柄勺")
    .replace(/tray material resembles pressed pulp\/cardboard/gi, "托盘材质像纸浆或纸板")
    .trim();
  return /[\u3400-\u9fff]/.test(translated) ? translated : "";
}

export function PromptEditor({
  sku,
  onSave,
  disabled,
}: {
  sku: ProductSku;
  onSave: (payload: ClusterUpdateInput) => Promise<ClusterUpdateResult> | void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(() => draftFromSku(sku));
  const [savedDraft, setSavedDraft] = useState(() => draftFromSku(sku));
  const currentSkuId = useRef(sku.id);
  const pendingVersion = useRef<number | null>(null);
  const draftRef = useRef(draft);
  const savedDraftRef = useRef(savedDraft);
  const saveInFlight = useRef(false);
  const saveAgain = useRef(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(savedDraft);

  useEffect(() => {
    const next = draftFromSku(sku);
    const skuChanged = currentSkuId.current !== sku.id;
    currentSkuId.current = sku.id;
    if (skuChanged) {
      pendingVersion.current = null;
      draftRef.current = next;
      savedDraftRef.current = next;
      setDraft(next);
      setSavedDraft(next);
      return;
    }
    if (pendingVersion.current !== null) {
      if (sku.version < pendingVersion.current) return;
      pendingVersion.current = null;
    }
    if (!dirty) {
      draftRef.current = next;
      savedDraftRef.current = next;
      setDraft(next);
      setSavedDraft(next);
    }
  }, [sku.id, sku.version, sku.prompts, dirty]);

  const updatePrompt = (slotOrder: number, text: string) => {
    setDraft((current) => {
      const next = { ...current, prompts: current.prompts.map((prompt) => prompt.slotOrder === slotOrder ? { ...prompt, text } : prompt) };
      draftRef.current = next;
      return next;
    });
  };
  const save = async () => {
    if (disabled) return;
    if (saveInFlight.current) {
      saveAgain.current = true;
      return;
    }
    const next = draftRef.current;
    const baseline = savedDraftRef.current;
    const prompts = next.prompts
      .filter((prompt) => !prompt.readOnly && prompt.text.trim() && prompt.text !== baseline.prompts.find((item) => item.slotOrder === prompt.slotOrder)?.text)
      .map((prompt) => prompt.hasDisplay
        ? { slot_order: prompt.slotOrder, display_prompt: prompt.text }
        : { slot_order: prompt.slotOrder, prompt: prompt.text });
    if (!prompts.length) return;
    saveInFlight.current = true;
    try {
      const result = await onSave({
        prompts,
      });
      pendingVersion.current = result?.version ?? null;
      savedDraftRef.current = next;
      setSavedDraft(next);
    } catch {
      // ProductCard shows the save error and keeps this local draft dirty for retry.
    } finally {
      saveInFlight.current = false;
      if (saveAgain.current) {
        saveAgain.current = false;
        void save();
      }
    }
  };
  useEffect(() => {
    if (!dirty || disabled) return;
    const timer = window.setTimeout(() => void save(), 700);
    return () => window.clearTimeout(timer);
  }, [dirty, draft, disabled]);
  const ledger = sku.analysisSnapshot?.fact_ledger;
  const gate = sku.analysisSnapshot?.rule_gate;
  const facts = ledger?.facts ?? [];
  const displayFacts = facts
    .map((fact) => ({ ...fact, statement: recognitionText(fact.statement) }))
    .filter((fact) => fact.statement);
  const hardBlocks = (gate?.hard_blocks ?? []).filter((item) => !quietGateMessage(item));
  const semanticRisks = (gate?.semantic_risks ?? []).filter((item) => !quietGateMessage(item));
  const warnings = (gate?.warnings ?? []).filter((item) => !quietGateMessage(item));
  const hasGateSummary = hardBlocks.length + semanticRisks.length + warnings.length > 0;
  const preparation = sku.preparation;
  const preparationStatus = preparation?.status ?? sku.preparationStatus ?? "";
  const preparing = ["pending", "preparing"].includes(preparationStatus);
  const prepared = preparationStatus === "ready";
  const progressTotal = preparation?.total || 3;
  const progressCurrent = Math.min(preparation?.current ?? 0, progressTotal);
  const stage = preparation?.stage ?? "";
  const progressPercent = stagePercent[stage];
  const promptStage = ["N2"].includes(stage);
  const editablePrompts = draft.prompts.filter((prompt) => !prompt.readOnly);
  const hasSourcePassthrough = editablePrompts.length < draft.prompts.length;
  const promptSectionTitle = `${editablePrompts.length} 张生成提示词`;
  const progressLabel = promptStage ? `正在生成 ${editablePrompts.length} 张提示词` : "正在读取并理解商品图片";
  const promptPlaceholder = (displayOrder: number) => preparing && !promptStage
    ? "商品图片识别完成后，会自动生成提示词"
    : preparing
      ? "正在生成这个槽位的提示词"
      : prepared
        ? "此槽位提示词缺失，请重新预备生成"
      : `预备生成后显示：${fallbackChinesePrompt(displayOrder)}`;

  return (
    <section className="mt-4 space-y-4">
      {ledger && (
        <section className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-800">商品识别信息</h3>
            {ledger.review_summary && (
              <p className="text-xs text-slate-500">
                确认 {ledger.review_summary.confirmed_count} · 图片观察 {ledger.review_summary.observed_count} · 辅助判断 {ledger.review_summary.inferred_count}
              </p>
            )}
          </div>
          {displayFacts.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {displayFacts.slice(0, 8).map((fact) => (
                <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-200" key={fact.fact_id}>{fact.statement}</span>
              ))}
            </div>
          )}
          {displayFacts.length <= 4 ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {displayFacts.map((fact) => <FactEvidence key={fact.fact_id} fact={fact} />)}
            </div>
          ) : (
            <details className="mt-3 rounded-md bg-white px-3 py-2 text-xs text-slate-600">
              <summary className="cursor-pointer font-semibold text-slate-700">查看全部识别证据（{displayFacts.length}）</summary>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {displayFacts.map((fact) => <FactEvidence key={fact.fact_id} fact={fact} />)}
              </div>
            </details>
          )}
        </section>
      )}
      {hasGateSummary && (
        <section className="rounded-lg border border-rose-200 bg-rose-50 p-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-rose-800">{hardBlocks.length ? "规则 / 合规阻断" : "人工复核提示"}</h3>
            {gate?.decision === "block" && <span className="text-xs font-semibold text-rose-700">已阻断</span>}
          </div>
          {hardBlocks.map((item, index) => <p className="mt-2 text-sm text-rose-800" key={`hard-${index}`}>硬阻断：{ruleMessage(item)}</p>)}
          {semanticRisks.map((item, index) => <p className="mt-2 text-sm text-amber-800" key={`risk-${index}`}>语义风险：{ruleMessage(item)}</p>)}
          {warnings.map((item, index) => <p className="mt-2 text-sm text-slate-600" key={`warning-${index}`}>提示：{ruleMessage(item)}</p>)}
        </section>
      )}
      <section className="rounded-lg bg-slate-50 p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-slate-700">{promptSectionTitle}</h3>
          {preparing && <span className="text-xs font-semibold text-blue-700">{progressLabel}{progressPercent != null ? ` · ${progressPercent}%` : ` ${progressCurrent}/${progressTotal}`}</span>}
        </div>
        {preparing && <ProgressBar current={progressCurrent} total={progressTotal} percent={progressPercent ?? undefined} />}
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {editablePrompts.map((prompt, index) => {
            const displayOrder = hasSourcePassthrough ? index + 1 : prompt.slotOrder;
            const label = `${String(displayOrder).padStart(2, "0")} ${slotLabel(prompt.slot, prompt.slotOrder)}提示词`;
            return (
            <div className="space-y-2" key={prompt.slotOrder}>
              <label className="block text-sm font-medium text-slate-700">
                <span className="mb-2 block">{label}{prompt.hasDisplay ? " · 中文策划" : ""}</span>
                <textarea
                  aria-label={`${label}${prompt.hasDisplay ? "中文策划" : ""}`}
                  disabled={prompt.readOnly}
                  placeholder={prompt.text.trim() ? "" : promptPlaceholder(displayOrder)}
                  value={prompt.text}
                  onChange={(event) => updatePrompt(prompt.slotOrder, event.target.value)}
                  onBlur={() => void save()}
                />
                {prepared && !prompt.text.trim() && <p className="mt-1 text-xs text-rose-700">此槽位提示词缺失，请重新预备生成</p>}
              </label>
              {prompt.hasDisplay && (
                <label className="block text-sm font-medium text-slate-700">
                  <span className="mb-2 block text-slate-500">出图用英文（生成时按中文重新翻译）</span>
                  <textarea aria-label={`${label}出图用英文`} className="bg-slate-100 text-slate-500" readOnly value={prompt.finalText} />
                </label>
              )}
            </div>
          );
          })}
        </div>
      </section>
    </section>
  );
}

function ProgressBar({ current, total, percent }: { current: number; total: number; percent?: number }) {
  const value = percent ?? (total ? Math.round((Math.min(current, total) / total) * 100) : 12);
  const width = Math.max(12, Math.min(100, value));
  return <div className="progress-track mt-3" aria-label="预备生成进度" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}><span className="progress-fill progress-fill-active" style={{ width: `${width}%` }} /></div>;
}

function FactEvidence({ fact }: { fact: PromptFact }) {
  return (
    <article className="rounded-md bg-slate-50 px-2 py-1.5">
      <p className="font-medium text-slate-800">{fact.statement}</p>
      <p className="mt-0.5 text-slate-500">
        {{ confirmed: "已确认", observed: "图片观察", inferred: "辅助判断" }[fact.fact_class]} · {Math.round(fact.confidence * 100)}%
      </p>
      {fact.evidence_refs.length > 0 && <p className="mt-0.5 text-slate-400">来源：{Array.from(new Set(fact.evidence_refs.map(evidenceLabel))).join("、")}</p>}
      {fact.review_note && !/结构化|异常|price|certification|medical/i.test(fact.review_note) && <p className="mt-0.5 text-amber-700">{fact.review_note}</p>}
    </article>
  );
}
