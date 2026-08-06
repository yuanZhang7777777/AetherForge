export const platforms = [
  ["generic", "通用电商"],
  ["shopee", "Shopee 虾皮"],
  ["tiktok", "TikTok Shop"],
] as const;

export const commonMarkets = [
  ["SEA", "东南亚通用"],
  ["VN", "越南"],
  ["TH", "泰国"],
  ["PH", "菲律宾"],
  ["MY", "马来西亚"],
  ["SG", "新加坡"],
  ["ID", "印度尼西亚"],
] as const;

export const extraMarkets = [
  ["US", "美国"],
  ["CA", "加拿大"],
  ["AU", "澳大利亚"],
  ["IN", "印度"],
  ["AE", "阿联酋"],
  ["SA", "沙特阿拉伯"],
  ["BR", "巴西"],
  ["MX", "墨西哥"],
  ["GB", "英国"],
  ["DE", "德国"],
  ["FR", "法国"],
  ["JP", "日本"],
  ["KR", "韩国"],
] as const;

export function platformLabel(value: string | null | undefined) {
  return platforms.find(([code]) => code === value?.toLowerCase())?.[1] ?? value ?? "通用电商";
}

export function marketLabel(value: string | null | undefined) {
  return [...commonMarkets, ...extraMarkets].find(([code]) => code === value?.toUpperCase())?.[1] ?? value ?? "";
}

export function marketValue(value: string) {
  const trimmed = value.trim();
  const known = [...commonMarkets, ...extraMarkets].find(([code, label]) => code === trimmed.toUpperCase() || label === trimmed);
  return known?.[0] ?? trimmed;
}

const slotLabels: Record<string, string> = {
  hero: "标准白底产品图",
  main: "标准白底产品图",
  white_background: "标准白底产品图",
  standard_white_background_product_hero: "标准白底产品图",
  seller_original_product_photo: "原始商品图",
  source_product_photo: "原始商品图",
  angle: "核心卖点图",
  key_benefit: "核心卖点图",
  selling_point: "核心卖点图",
  detail: "细节特写图",
  product_detail: "细节特写图",
  detail_close_up: "细节特写图",
  product_structure: "商品结构图",
  function: "功能说明图",
  scene: "真实使用场景图",
  usage: "真实使用场景图",
  real_life_use: "真实使用场景图",
  pain_point_solution: "痛点解决图",
  size_and_material: "尺寸材质图",
  usage_steps: "使用步骤图",
  lifestyle: "生活方式图",
  quality_and_trust: "品质信任图",
  scale: "模特/比例图",
  model_or_scale: "模特/比例图",
  user_or_scale: "模特/比例图",
  package: "尺寸/包装/包含物图",
  size_packaging_or_contents: "尺寸/包装/包含物图",
  packaging_or_contents: "包装/包含物图",
  conversion: "平台转化营销图",
  marketplace_conversion: "平台转化营销图",
  local_lifestyle: "本地生活方式图",
  extra: "补充转化图",
  supplemental_conversion: "补充转化图",
};

const orderSlotLabels = [
  "标准白底产品图",
  "核心卖点图",
  "细节特写图",
  "真实使用场景图",
  "痛点解决图",
  "尺寸材质图",
  "使用步骤图",
  "生活方式图",
  "品质信任图",
];

export function slotLabel(value: string, order: number) {
  const normalized = value.trim().toLowerCase().replace(/[\s/-]+/g, "_");
  return slotLabels[normalized] ?? (/[\u3400-\u9fff]/.test(value) ? value : orderSlotLabels[order - 1] ?? `输出图 ${order}`);
}

export const stageLabels: Record<string, string> = {
  N1: "识别商品",
  N2: "写提示词",
  N3: "整理出图请求",
};
