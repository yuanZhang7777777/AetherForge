# Shopee_Listing_V2 出图工作流拆解

> 来源：Coze 导出的草稿工作流
> 文件：`E:\download\Chrome下载\Workflow-Shopee_Listing_V2-draft-4050\Workflow-Shopee_Listing_V2-draft-4050\workflow\Shopee_Listing_V2-draft.yaml`（3601 行，26 个顶层节点，draft 版）
> 存档日期：2026-08-05

## 工作流定位

**Shopee Listing 通用出图 V2**：输入"商品图 + 商品名 + 真实卖点资料 + 站点"，自动产出**一张 1:1 标准商品图** + **一套 6–8 张 1:1 详情页营销图**。

## 输入 / 输出

| | 字段 |
|---|---|
| 输入 | `product_images`(图片列表,必填)、`product_name`、`points`(唯一营销事实来源)、`zhandian`(站点)、`platform`(默认Shopee)、`competitor_images`(竞品图,未用) |
| 输出 | `status`、`standard_product_image_url`、`result_image_urls`、`competitor_summary`、`message` |

站点支持：SG / MY / TH / VN / PH / ID / TW / BR（8 个 Shopee 买家市场）。

## 整体流程图

```
start ──► [批1] 逐图证据提取 ──► [AI] 多图汇总/主商品判定 ──► [代码] 解析JSON
        (对每张图跑视觉理解)      (豆包1.8深度思考)               │
                                          │ 条件:判定可信?            │
                                  否──► 返回 needs_input（请补资料）
                                  是──► [代码] 选标准图源(按索引取URL)
                                          │
                                          ▼
                                  条件: standardization_mode == reuse ?
                                  ├─是──► 直接用源图URL
                                  └─否──► [AI]组装标准图Prompt ──► [GT2生图]
                                          │
                                          ▼
                              [变量合并] 标准商品图URL
                                          │
                                          ▼
                         [AI] Shopee详情页设计V2 (豆包2.0 pro)
                         输出6-8张设计稿JSON数组 ──► [代码]解析
                                          │
                                          ▼
                           [代码]组装参考图数组(标准图URL)
                                          │
                                          ▼
                              [批2] 逐张详情图生成 (并发1)
                    ┌─────────────────────┼─────────────────────┐
                  [AI]本地化+编译英文Prompt    失败 → [AI]精简Prompt
                          │                 │        └─►[GT2]重试生成
                  [GT2] 生成详情图 ─────────┘ 取成功URL
                                          │
                                          ▼
                  [代码]组装结果 ─► 合并 ─► [代码]拆分 ─► end
```

## 节点清单

| 节点ID | 类型 | 标题 | 作用 |
|---|---|---|---|
| 100001 | start | 开始 | 接收输入变量 |
| 900001 | end | 结束 | 返回 status/standard_product_image_url/result_image_urls/competitor_summary/message |
| 105251 | batch | 逐图商品证据提取 | 对每张商品图跑一次"单图商品理解"(100上限/并发1) |
| 107452 | llm | 单图商品理解 | 豆包2.0 lite 视觉模型，输出每张图的证据 JSON（嵌套于105251） |
| 151076 | llm | AI：多图汇总与主商品判定 | 豆包1.8深度思考，归并商品家族/选主外观/输出身份锁 |
| 136571 | code | 代码：解析商品判定 JSON | 清洗解析LLM输出为类型化字段 |
| 173035 | condition | 条件：主商品是否明确 | 要求 decision=continue 且 confidence≥80 且索引≥0 且身份锁非空 |
| 152788 | code | 代码：选择标准图源 | 按 source_image_index 从 product_images 取 URL |
| 183194 | condition | 条件：标准图策略 | 判断 standardization_mode==reuse |
| 128405 | code | 复用标准图 URL | reuse 时直接透传源图 URL |
| 162643 | code | 组装标准商品图 Prompt | cutout/semantic_extract 时按模式组装英文 Prompt |
| 108877 | plugin | 标准商品图生成 | GT2_图片生成(g2_generate_image)，1:1/1K/异步，源图为参考 |
| 107993 | variable_merge | 标准商品图 URL | 合并 复用/生成 两个分支的输出 |
| 111955 | llm | Shopee 详情页设计 V2 | 豆包2.0 pro，输出 6–8 张设计稿 JSON 数组 |
| 183337 | code | 代码解析设计数组 | 校验并清洗为 design_list |
| 174684 | code | 组装详情图参考图数组 | 标准图 URL 打包为生图参考图 |
| 184039 | batch | 批处理节点：逐张详情图生成 | 每张设计稿跑一轮生成(8上限/并发1) |
| 180300 | llm | 本地化与生图 Prompt 编译 | 豆包2.0 lite，文案改写目标站点母语+编译英文 Prompt（嵌套于184039） |
| 104951 | plugin | 生成详情图 | GT2 生图，1:1/1K（嵌套于184039） |
| 175048 | llm | 失败后精简 Prompt | 豆包1.8深度思考，失败时精简重试 Prompt（嵌套于184039） |
| 122439 | plugin | 重试生成详情图 | 失败后重试生图（嵌套于184039） |
| 172754 | variable_merge | 变量聚合 | 取首次/重试成功 URL（嵌套于184039） |
| 164323 | code | 组装生成完成结果 | status=completed/partial |
| 177089 | code | 组装待补资料结果 | 判定失败时 status=needs_input 兜底返回 |
| 186420 | variable_merge | 最终结果对象 | 合并成功/兜底两个分支 |
| 157190 | code | 拆分最终结果 | 拆分字段送 end 节点 |
| 194814 | llm | AI：标准商品图身份检查 | 审核生成图是否满足身份锁（豆包2.0 lite） |
| 153173 | code | 代码：解析标准图检查 JSON | 解析 passed/severity/issues |
| 149650 | condition | 标准商品图是否合格 | 审核标准商品图是否合格 |
| 153579 | condition | 条件：是否有竞品图 | 判断是否提供竞品图 |
| 178564 | batch | 按索引抠图 | 智能抠图插件 cutout 批处理 |
| 193360 | plugin | cutout | 智能抠图插件（嵌套于178564） |
| 1652632 | code | 组装抠图 Prompt | 抠图 prompt（嵌套于178564） |

## 核心机制

### 1. 两段式证据处理
- **逐图证据提取**：先逐张图片做视觉理解，标注 image_role、是否含目标商品、质量评分(0-100)、可见特征、recommended_use（reuse/cutout_source/semantic_extract_source/evidence_only/reject）
- **多图汇总判定**：归并商品家族（用"身份不变量"判断，颜色/花纹/角度等可变属性不算冲突）、合并互补证据（正面/背面/内部/接口）、选定主外观，输出**身份锁(identity_lock)**

### 2. 身份锁贯穿全程
`identity_lock` 是核心约束，所有下游节点（标准图生成、详情页设计、Prompt 编译）都必须服从：
- 保持核心结构、精确部件数量、排列、颜色、接口、按钮、Logo、相对位置、比例
- 禁止虚构内部结构、增减部件、混入其他 SKU 的可变属性
- 无法确认的内容必须省略，不得猜测
- `points` 是唯一允许用于营销文案的事实来源

### 3. 标准商品图三策略
- **reuse**：直接复用源图 URL
- **cutout**：GT2 生图模型重绘，prompt 指导隔离商品主体（以源图为参考）
- **semantic_extract**：GT2 生图模型按身份约束重建干净完整参考图

### 4. 详情页设计（6–8 张递进结构）
必须包含六个购买决策任务：第一眼价值 / 核心收益 / 事实证明 / 使用理解 / 细节信任 / 场景体验与收尾；第 7、8 张仅在 points 提供对应事实时启用。8 个站点各有本地化视觉映射（配色/环境/人物状态）。

### 5. 人物策略动态决定
- 需要穿戴/手持/接触/涂抹/操作类商品 → 6-8 张中安排 2–3 张真人使用图，前两张至少一张
- 危险/受管制/刺激性商品 → 禁止轻松人物场景，改无人展示
- 无需人物解释用途时不强行加人

### 6. 本地化 + 英文 Prompt 编译
每张设计稿 → 豆包 lite 编译：
- 消费者可见文案改写为目标站点母语（TH/VN/MY/ID/TW/BR 不得输出英文；SG/PH 可用英文）
- 画面指令编译为英文 Prompt，按固定 5 段组织（身份/使用关系/构图/文字渲染/强调）
- 精确部件数量写为硬约束句 `The reference product has exactly [number] [component].`
- 文案渲染强制指令：每行必须出现且只出现一次，禁止标签词

### 7. 失败重试
详情图生成失败 → LLM 精简 Prompt（保留商品身份/数量/文案，合并重复约束）→ 重试一次 → 聚合取成功 URL。全部失败时 status=partial 仍保留成功图片。

## 模型选型

| 用途 | 模型 |
|---|---|
| 单图视觉理解 / 身份检查 / Prompt 编译 | 豆包·2.0·lite |
| 多图汇总判定 / 失败 Prompt 精简 | 豆包·1.8·深度思考 |
| 详情页设计 | 豆包·2.0·pro（maxTokens 94K） |
| 生图 | GT2_图片生成（g2_generate_image，1:1、1K、异步） |
| 抠图 | 智能抠图插件（cutout） |

## 复刻要点（如迁出 Coze 需保留）

- 两段式批处理 + 身份锁机制是全流程质量关键
- 所有 LLM 输出统一 `responseFormat=2`(JSON)，由代码节点清洗解析、异常兜底
- 生图统一异步 + 参考图 + 失败重试（先精简 Prompt 再重试）
