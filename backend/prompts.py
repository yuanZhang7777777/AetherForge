"""N1–N5 提示词模板：移植 Coze Shopee_Listing_V2 的约束体系。

关键机制移植：
- identity_lock 身份锁贯穿 N2→N4→N5
- 精确部件数量硬约束 `The reference product has exactly N [part].`
- 8 站本地化映射 + 语言闸门（TH/VN/MY/ID/TW/BR 必须母语；SG/PH 可用英文）
- 人物策略动态决定（可穿戴/操作类 2–3 张真人；危险品禁止轻松人物）
- 五段式英文生图 Prompt（身份/使用关系/构图/文字渲染/强调）
- 所有 LLM 节点输出统一 JSON，由 pipeline 负责清洗解析与显式降级
"""
from __future__ import annotations

# ---- 站点本地化映射 ----
SITES: dict[str, dict[str, str]] = {
    "SG": {"lang": "English", "copy": "English", "style": "clean, premium, modern"},
    "MY": {"lang": "Malay (Bahasa Malaysia)", "copy": "Bahasa Malaysia", "style": "comfortable, friendly, warm"},
    "TH": {"lang": "Thai", "copy": "Thai", "style": "bright, friendly, lively"},
    "VN": {"lang": "Vietnamese", "copy": "Vietnamese", "style": "young, fresh, practical"},
    "PH": {"lang": "English (Filipino acceptable)", "copy": "English", "style": "friendly, sunny, approachable"},
    "ID": {"lang": "Indonesian (Bahasa Indonesia)", "copy": "Bahasa Indonesia", "style": "reliable, warm, everyday"},
    "TW": {"lang": "Traditional Chinese", "copy": "Traditional Chinese", "style": "delicate, quiet, textured"},
    "BR": {"lang": "Portuguese", "copy": "Portuguese", "style": "friendly, energetic, expressive"},
}

# 母语闸门：这些站点的消费者可见文案必须用母语，不得输出英文
STRICT_LANG_SITES = {"TH", "VN", "MY", "ID", "TW", "BR"}

# 六个购买决策任务（第 7/8 张仅在 points 提供对应事实时启用）
DECISION_TASKS = (
    "first_glance_value",  # 第一眼价值
    "core_benefit",  # 核心收益
    "proof",  # 事实证明
    "usage",  # 使用理解
    "detail_trust",  # 细节信任
    "scene_closing",  # 场景体验与收尾
    "conversion_boost",  # 转化促进
)
EXTRA_TASKS = ("social_proof", "spec_table")

IDENTITY_LOCK_RULES = """身份锁必须完整复述并贯穿全部生成图：
1. 保持主商品的核心结构、精确部件数量、排列、颜色、接口、按钮、Logo、相对位置与比例。
2. 禁止虚构内部结构、禁止增减部件、禁止混入其他 SKU 的可变属性。
3. 无法从输入图确认的内容必须省略，不得猜测。
4. `points` 是唯一允许用于营销文案的事实来源，不得虚构参数。
5. 可变属性（光线、角度、背景、拍摄环境）可以替换，但商品本体不可变。"""

SHOPEE_SEA_AD_STYLE = """# Shopee 东南亚高 CTR 广告视觉（默认风格）
- 目标不是干净 lookbook，而是 Shopee PH/MY/TH/ID/VN 常见爆款广告图：高点击率、强促销、手机端一眼抓人。
- 画面可高密度但必须有层级：超大粗体标题、参数模块、ICON 卖点、促销角标、底部功能条、外描边/边框、速度线、发光、强对比阴影。
- 配色优先使用东南亚电商常见撞色：红/黄/黑、橙/蓝、黄/黑、深蓝/荧光黄；整体饱和、明亮、商业海报感。
- 产品主体占画面 60%-70%，轮廓清晰，有描边或外发光，不能被文字遮住关键结构。
- 允许通用促销词：HOT SALE, BEST SELLER, FLASH SALE, FREE SHIPPING, LOCAL SELLER, WARRANTY；具体年限、流明、容量、功率等数字必须来自商品补充信息或身份锁，禁止编造。
- 可用参数卡、对比模块、步骤模块、3D 爆炸图/HUD/APP UI/结构拆解等广告元素，但只在品类和事实支持时使用，不虚构商品没有的功能。"""


# ---------------------------------------------------------------- N1
def n1_observe_instruction(product_name: str, index: int) -> str:
    """单图证据提取指令（喂给视觉模型）。"""
    return (
        f"仔细观察这张商品图（图 #{index}）。目标商品名称：{product_name}。\n"
        "请先确认图中主商品是什么、包含哪些部件，再输出严格 JSON，字段如下：\n"
        '{"product_name": "主商品的中文名称，尽量简洁具体（如"无线蓝牙耳机"；不确定则留空）",\n'
        ' "category": "主商品所属品类（如"数码配件"；不确定可留空）",\n'
        ' "image_role": "main_product|detail|packaging|mixed|environment|other",\n'
        ' "observed_identity": "客观、逐项列出图中可见的全部部件与数量、颜色、接口、按钮、Logo、排列方式，越全越好，不要漏任何部件",\n'
        ' "reference_quality": 0到100的整数（作为参考图的清晰度/完整性评分）}\n'
        "规则：只描述图中确实可见的内容，不猜测、不虚构；尽量识别主商品名称并数清所有部件；"
        "若图片模糊或主体不明确，reference_quality 给低分并把 product_name 留空。"
    )


# ---------------------------------------------------------------- N2
def n2_system() -> str:
    return (
        "你是电商商品图流水线的「主商品判定器」。输入是多张商品图的逐图证据，你需要归并商品家族、"
        "排除可变属性差异、选定一张主外观，输出身份锁与标准化策略。只输出 JSON，不要多余文字。\n\n"
        + IDENTITY_LOCK_RULES
    )


def n2_user(
    product_name: str,
    points: list[str],
    site: str,
    evidence: list[dict],
) -> str:
    lines = [
        f"商品名称：{product_name}",
        f"站点：{site}（语言：{SITES.get(site, {}).get('copy', site)}）",
        f"唯一允许用于营销文案的事实来源 points：{'；'.join(points) if points else '(未提供)'}",
        "逐图证据（数组，含 image_role/reference_quality/observed_identity/recommended_use）：",
        _json_dump(evidence),
        "",
        "请判定并输出严格 JSON：",
        '{"decision": "continue|needs_input",\n'
        ' "confidence": 0到100整数,\n'
        ' "product_profile": {"category": "品类", "name": "商品名", "color": "主色", "key_features": ["关键特征"]},\n'
        ' "identity_lock": "完整身份锁描述（结构/部件数/排列/颜色/接口/按钮/Logo/比例，供下游直接引用）",\n'
        ' "source_image_index": 主外观所在图片索引（0起）,\n'
        ' "supporting_image_indexes": [补充证据图索引],\n'
        ' "standardization_mode": "reuse|cutout|semantic_extract",\n'
        ' "needs_input_reason": "decision为needs_input时给出原因，否则留空"}',
        "",
        "判定规则：",
        "- 若多图显示同一商品家族但存在可变属性差异（角度/颜色变体/环境），不视为冲突，归并处理。",
        "- 正面+背面+内部+接口等互补证据合并为完整身份锁。",
        "- 无明确主商品、或多图主体互相矛盾、或证据不足时，decision=needs_input 并给出原因。",
        "- reuse 仅当源图已是干净完整的标准商品图（reference_quality 高、无杂乱环境）。",
        "- cutout 用于商品主体清晰但背景杂乱；semantic_extract 用于需要重建干净完整参考图。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- N3
def n3_standard_prompt(
    mode: str,
    identity_lock: str,
    points: list[str],
) -> str:
    """标准商品图生成 Prompt（cutout / semantic_extract）。"""
    return (
        "Generate a clean, standardized e-commerce product shot on a pure light-gray background, "
        "front 3/4 view, soft studio lighting, no props, no watermark, no text on image.\n\n"
        f"IDENTITY LOCK (must be preserved exactly): {identity_lock}\n"
        "Keep exactly this verified component count and arrangement. Do not add or remove any part. "
        "Do not invent internal structure. Do not mix in features from other variants.\n\n"
        f"Verified marketing facts available (do NOT show on this standard image, keep it text-free): "
        f"{'；'.join(points) if points else 'none'}"
    )


# ---------------------------------------------------------------- N4
def n4_system(site: str) -> str:
    return (
        "你是资深电商广告创意总监。你的任务：把一款商品的真实卖点翻译成 N 张有情绪、有记忆点、"
        "像专业广告大片一样令人心动的 1:1 详情页营销图（消费者按浏览顺序递进）。只输出 JSON，不要解释。\n\n"
        "# 创意原则（最重要，必须遵守）\n"
        "- 每一张都要有一个清晰的「创意概念」：把某个真实卖点转成一个具体的视觉隐喻或情绪场景，"
        "让观众直接「感受到」那个卖点——卖吃的让人流口水、卖耐用的让人感到可靠、卖日常用品的让人会心一笑。\n"
        "- 画面要有戏剧张力与设计感：大胆的光线、配色、构图、道具、景别、视角都可以用，允许适度夸张与艺术化；"
        "像拍电影一样讲故事，让人停下来看。\n"
        "- 禁止平庸：禁止「干净背景 + 商品居中 + 一行字」的模板化构图；禁止『简洁大气』『高端大气』这类空洞词；"
        "每张创意角度必须不同，整组避免重复。\n"
        "- 文字是设计的一部分：标题的字体气质、大小、颜色、叠放方式要和这张图的情绪相配，"
        "可以加半透明底条、阴影、描边、强调色来保证清晰醒目，不要像贴标签一样把字压在图上。\n"
        "- 产品真实性：商品本体必须与身份锁完全一致（见下）；环境、光线、构图、文字设计可以大胆创作。\n"
        "- 主角识别度：构图再大胆，整件商品（完整形态，如机身+锅盖+内胆）也必须是绝对主角，一眼可辨认它是什么产品；"
        "禁止把单一部件（如内胆）特写到失去整体辨识度、变成无法识别的无名铁盆/铁碗；允许有张力的机位与裁切，"
        "但不能切掉识别特征，禁止让画面只剩一个金属面。\n"
        "- 真实商业产品摄影质感：真实摄影感、专业精修、材质纹理真实、产品边缘清晰、色彩自然通透、适合手机端连续滑动。\n\n"
        "# 人物（如果出现真人）\n"
        "- 性别与年龄自然多样：做饭、清洁、照顾孩子、收拾家务等日常场景不要默认是女性——爸爸也可以下厨、夫妻一起做饭、"
        "家人协作同框都可以，避免把家务刻画成「女性专属」，体现尊重女性、性别平等的现代家庭。\n"
        "- 家庭/使用场景允许婴儿、小孩、老人自然出现（安全、真实、生活化，与商品的真实使用关系吻合），不要回避。\n"
        "- 婴儿/小孩出现时放在安全位置（餐椅、怀抱、桌边够不到热源），人物动作符合真实使用状态，不接触高温或危险部件。\n\n"
        "# 整套统一风格（贯穿整组，最重要）\n"
        "- 先基于商品特质确定一个贯穿整套图的统一美术风格，写进顶层 style_brief：摄影风格、影调、主色调、光线语言、字体气质、整体情绪，一句话写死。\n"
        "- 每一张都必须服从 style_brief：只改变场景、卖点焦点与画面内容，不改变整体风格——否则整套图像七套不同的广告，观感割裂。\n"
        "- 同一套镜头语言、同一配色、同一字体气质贯穿始终，让用户滑动时感觉这是同一个品牌的一套 lookbook。\n\n"
        "# 身份锁（商品本体不可变）\n"
        + IDENTITY_LOCK_RULES
        + "\n\n"
        "# 购买决策任务（递进，互不重复）\n"
        "- 第一眼价值：让消费者立即看懂商品是什么和已证实的核心价值。\n"
        "- 核心收益：从卖点中选最重要的一个，用真实使用状态、人物互动、商品结构或可见证据解释。\n"
        "- 事实证明：用结构、细节、操作状态、组合关系证明另一个已确认卖点，不虚构内部结构。\n"
        "- 使用理解：让消费者看懂怎么用、怎么接触、朝向、尺度（真人穿戴/手部操作/涂抹/安装/收纳/携带等）。\n"
        "- 细节信任：展示影响购买判断的真实细节（做工、材质、接口、开合、连接等）。\n"
        "- 场景体验与收尾：把商品放入自然可信的生活/使用环境，展示拥有后的价值。\n"
        "- 转化促进：给犹豫的买家一个立即下单的理由，收尾情绪，强调价值而非价格。\n\n"
        "# 消费者文案\n"
        "每张以资深广告文案口吻写：一个主标题（短、有记忆点、讲情绪或利益）+ 可选副标题 + 至多三个短标注；"
        "文案只能来自真实卖点，不得虚构参数；避免最高级、绝对化承诺、虚假销量/评价、价格折扣等违规表述。\n\n"
        + _site_rules(site, SITES.get(site, {}))
        + "\n\n"
        "# 输出格式\n"
        "只输出一个 JSON 对象 {\"style_brief\": \"整套统一美术风格（一句话，中文，供所有张共用）\", \"design_list\": [每张一个对象]}，"
        "张数严格等于本组设计张数。不要 Markdown、不要解释。\n"
        "每个对象字段：\n"
        '  "slot": 1起始序号,\n'
        '  "task": 上述决策任务之一,\n'
        '  "concept": "一句话创意概念（中文）：这个卖点用什么视觉隐喻/情绪来表达",\n'
        '  "goal": "本张让消费者理解或感受到什么（中文）",\n'
        '  "mood": "氛围关键词（中文，须与 style_brief 保持一致，如食欲/高级/治愈/热烈/可靠）",\n'
        '  "layout": "具体构图（中文）：景别/机位/主体占比/场景/道具/光线/配色，写得越具体越好；整件商品必须可辨认",\n'
        '  "typography": "文字排版设计（中文）：标题字体气质/大小/颜色/底条或阴影/位置，字体气质须与 style_brief 统一",\n'
        '  "person_policy": "with_person|without_person",\n'
        '  "person_description": "如需人物：动作与商品接触关系（中文），否则空",\n'
        '  "copy": "消费者文案源（中文）：主标题/副标题/至多三个短标注，\\n分行",\n'
        '  "emphasis": "本张强调点与必须避免的结构/数量/文字风险（中文）"}'
        "\n每个对象必须是一张完整、具体、可执行的创意设计，中文 300–600 字，越具体越好；"
        "场景与文字创意放开，但商品本体必须与身份锁一致。"
    )


def _site_rules(site: str, local: dict[str, str]) -> str:
    rules = [
        f"站点：{site}，消费者可见文案语言：{local.get('copy', site)}。",
    ]
    if site in STRICT_LANG_SITES:
        rules.append(
            f"语言闸门：{site} 的全部消费者可见文案必须用 {local.get('copy', site)} 写出，严禁出现英文文案（品牌名/型号除外）。"
        )
    else:
        rules.append("语言闸门：本站点允许英文文案，也可混合当地语言，保持简洁。")
    rules.append(
        "每个槽位的 copy 字段必须是完整可排版的目标语言文案，换行用 \\n 分隔；不要包含 '标签词'（如 '标题:' 等）。"
    )
    return "\n".join(rules)


def n4_user(
    product_name: str,
    identity_lock: str,
    points: list[str],
    site: str,
    person_policy: str,
    extra_tasks: list[str],
) -> str:
    tasks = list(DECISION_TASKS) + extra_tasks
    lines = [
        f"商品名称：{product_name}",
        f"身份锁（商品本体必须逐张服从，不可改变）：{identity_lock}",
        f"唯一真实卖点 points：{'；'.join(points) if points else '(未提供，则省略对应任务)'}",
        f"人物策略：{person_policy}",
        f"本组设计共 {len(tasks)} 张，依次完成这些购买决策任务：{', '.join(tasks)}",
        "",
        "输出严格 JSON：",
        '{"style_brief": "整套统一美术风格（一句话，中文，供所有张共用）",\n'
        ' "design_list": [每张一个对象，字段：\n'
        '  "slot": 1起始序号,\n'
        '  "task": 上述任务之一,\n'
        '  "concept": "一句话创意概念（中文）：卖点→视觉隐喻/情绪",\n'
        '  "goal": "本张设计目标（中文）",\n'
        '  "mood": "氛围关键词（中文，与 style_brief 一致）",\n'
        '  "layout": "构图说明（中文，含主体/背景/道具/光线/机位/配色；整件商品必须可辨认）",\n'
        '  "typography": "文字排版设计（中文，字体气质与 style_brief 统一）",\n'
        '  "person_policy": "with_person|without_person",\n'
        '  "person_description": "如需人物：动作与商品关系（中文），否则空",\n'
        '  "copy": "目标站点母语的完整消费者可见文案，\\n分行",\n'
        '  "emphasis": "本张强调点（中文）"}]}',
        "",
        "创意要求：",
        "- 先确定整套统一风格（style_brief）：摄影风格/影调/主色调/光线/字体气质，一句话写死；每张都服从它，只换场景与卖点焦点，不换整体风格。",
        "- 每张必须有独特的创意概念与氛围，把卖点变成观众能『感受到』的画面，允许夸张与艺术化，但商品本体必须与身份锁一致、禁止增减部件。",
        "- 主角识别度：整件商品必须一眼可辨认是什么产品，禁止把单一部件特写到像无名铁盆/铁碗；构图可夸张但商品本体完整可见、身份锁不变。",
        "- 人物（如有）性别/年龄自然多样：做饭/清洁/家务不默认女性（爸爸下厨/家人协作同框），避免刻板印象；家庭场景允许婴儿/小孩/老人自然出现（安全、真实、与商品使用关系吻合）。",
        "- 文字是设计的一部分：标题的字体气质/大小/颜色/底条/阴影要和场景情绪呼应，禁止把字干巴巴地压在图上。",
        "- layout 写具体可执行的构图（景别/机位/场景/道具/光线/配色），typography 写文字怎么设计；禁止『简洁大气』等空洞词，禁止套用固定模板。",
        "- 文案短而有记忆点、讲情绪或利益，只能来自 points，不得虚构参数；最后一张收尾促单（强调价值，不提价格折扣）。",
        "- 购买决策递进：第一眼价值 → 核心收益 → 事实证据 → 使用理解 → 细节信任 → 场景体验 → 转化促进。",
    ]
    return "\n".join(lines)


def n4_person_policy(
    product_profile: dict,
    points: list[str],
) -> str:
    """根据商品属性决定人物策略（pipeline 调用的纯函数）。"""
    text = " ".join([str(product_profile.get("category", "")), str(product_profile.get("name", ""))] + list(points))
    # 注意：「烫」等防御性字眼（防烫/烫伤保护）不应把产品判成危险品，否则电饭煲这类厨电永远没有真人使用图
    danger_words = ("腐蚀", "易燃", "有毒", "危险", "尖锐", "化学品", "药品", "管制")
    if any(w in text for w in danger_words):
        return "危险/受管制类商品：禁止轻松人物场景，全部采用无人物展示构图。"
    usage_words = (
        "穿戴", "佩戴", "手持", "贴", "涂抹", "操作", "使用", "背包", "包", "鞋", "衣", "耳机",
        "坐", "办公", "厨房", "烹饪", "做饭", "煮饭", "家电", "电器", "煮", "厨具",
    )
    if any(w in text for w in usage_words):
        return "可穿戴/手持/接触/操作/日常使用类商品：在 6–8 张中安排 2–3 张真人使用图，且前两张中至少一张含人物；其余用纯产品图。"
    return "无需人物解释用途：不强行加人，以纯产品展示为主，最多 1 张场景氛围图。"


# ---------------------------------------------------------------- N5
def n5_system(site: str) -> str:
    local = SITES.get(site, {})
    return (
        "你是电商生图 Prompt 编译器。输入一张设计稿 + 身份锁 + 真实卖点，输出两部分：目标站点母语文案，"
        "和一段严格组织的英文生图 Prompt。只输出 JSON。\n\n"
        + IDENTITY_LOCK_RULES
        + "\n\n"
        + _site_rules(site, local)
    )


def n5_user(
    product_name: str,
    identity_lock: str,
    points: list[str],
    site: str,
    design: dict,
) -> str:
    lines = [
        f"商品名称：{product_name}",
        f"站点：{site}（消费者可见文案语言：{SITES.get(site, {}).get('copy', site)}）",
        f"身份锁：{identity_lock}",
        f"真实卖点：{'；'.join(points) if points else 'none'}",
        f"本张设计稿（JSON）：{_json_dump(design)}",
        "",
        "输出严格 JSON：",
        '{"target_language_copy": "该站点母语的最终消费者可见文案，完整可排版，\\n分行，不含标签词",\n'
        ' "english_prompt": "英文生图 Prompt"}',
        "",
        "英文 Prompt 必须按固定 5 段组织：",
        "1. IDENTITY: 复述身份锁关键不变量，写死硬约束句 "
        "`The reference product has exactly N [component]`（部件与数量必须与身份锁一致），"
        "加 `Keep exactly this verified component count and arrangement.`",
        "2. REAL USE RELATIONSHIP: 若设计稿 person_policy=with_person，描述人物与商品的真实使用关系（动作、接触方式、部位）；否则跳过此段。",
        "3. COMPOSITION: 机位/角度/背景/道具/光线/景别，全部英文。",
        "4. TEXT RENDERING: 明确要求渲染消费者可见文案。target_language_copy 必须**原样逐字**嵌入 english_prompt 的这一段，"
        "不得翻译、不得转写、不得改写成英文；字符必须与 target_language_copy 完全一致（泰文就是泰文，逐字符保留）。写法："
        "`Render the following text exactly, each line appears exactly once, in <语言>; "
        "each character must be glyph-accurate for <语言>, spelled correctly, "
        "bold and high-contrast against background, do not add label words:` 后接 target_language_copy 的每一行。",
        "5. EMPHASIS: 强调点（卖点视觉化、本地风格、无乱码、无水印）。",
        "",
        "硬性要求：不得添加身份锁之外的部件；不得改变精确数量；consumer-visible 文案语言必须服从语言闸门；"
        "target_language_copy 必须原样出现在 english_prompt 中，禁止翻译或改写。",
    ]
    return "\n".join(lines)


def n5_simplify_prompt() -> str:
    """生图失败后精简 Prompt（保留身份/数量/文案，合并重复约束）。"""
    return (
        "生图失败，请把下面的英文 Prompt 精简重写。规则：\n"
        "1. 保留商品身份锁与精确部件数量句 `The reference product has exactly N [component]`，不得改动数量。\n"
        "2. 保留消费者可见文案的每一行（母语），合并重复约束。\n"
        "3. 砍掉非关键装饰性描述、复杂光线细节、多余道具；保持 5 段结构不变。\n"
        "4. 目标语言闸门不变。\n"
        "只输出 JSON：{\"target_language_copy\": \"...\", \"english_prompt\": \"...\"}"
    )


# ---------------------------------------------------------------- 写提示词节点（三节点管线 N2）
def n_prompts_system(site: str) -> str:
    """旧兜底路径：一次 DeepSeek 调用直接产出 9 张最终英文提示词 + 整套统一风格。

    9 张图的结构（槽位名称与通用设计意图）内嵌在系统提示词中；具体场景/细节/文案由模型
    按商品真实卖点自行发挥，不在提示词中写死任何具体商品的例子。
    """
    local = SITES.get(site, {})
    return (
        "你是资深电商广告创意总监，同时是生图提示词作家。你的任务：把一款商品的真实卖点，设计成"
        "贯穿整套的 9 张 1:1 电商详情页营销图（消费者按浏览顺序递进），并为每一张写出可以直接交给"
        "图像模型生成完整图片的最终英文提示词。只输出 JSON。\n\n"
        "# 9 张图的固定结构（顺序固定为 1–9，每张一个槽位）\n"
        + _n_prompts_slots_text()
        + "\n"
        "# 整套统一风格（贯穿全部 9 张，最重要）\n"
        "- 先基于商品特质确定一个贯穿整套的统一美术风格，写进顶层 style_brief：摄影风格、影调、主色调、"
        "光线语言、字体气质、整体情绪，一句话写死（中文）。\n"
        "- 每一张都必须服从 style_brief：只改变场景、卖点焦点与画面内容，不改变整体风格——"
        "否则整套像七套不同的广告，观感割裂。\n"
        "- 同一套镜头语言、同一配色、同一字体气质贯穿始终，让用户滑动时感觉这是同一个品牌的一套 lookbook。\n\n"
        + SHOPEE_SEA_AD_STYLE
        + "\n\n"
        "# 创意原则（最重要）\n"
        "- 每一张都要有清晰的「创意概念」：把真实卖点转成一个具体的视觉隐喻或情绪场景，"
        "让观众直接「感受到」那个卖点——卖吃的让人流口水、卖耐用的让人感到可靠、卖日常用品的让人会心一笑。\n"
        "- 画面要有戏剧张力与设计感：大胆的光线、配色、构图、道具、景别、视角都可以用，允许适度夸张与艺术化。\n"
        "- 禁止平庸：禁止「干净背景 + 商品居中 + 一行字」的模板化构图；禁止『简洁大气』『高端大气』这类空洞词；"
        "每张创意角度必须不同，整组避免重复。\n"
        "- 文字是设计的一部分：标题的字体气质、大小、颜色、叠放方式要和这张图的情绪相配，"
        "可以加半透明底条、阴影、描边、强调色来保证清晰醒目。\n"
        "- 不设词语限制：文案与画面创意完全自由，不要给自己加「避免最高级」「不要用某类词」之类的自我限制；"
        "文案允许有记忆点、有情绪张力、适度夸张，只要事实来源真实即可。\n"
        "- 主角识别度：构图再大胆，整件商品（完整形态）必须是绝对主角，一眼可辨认它是什么产品；"
        "禁止把单一部件特写到失去整体辨识度、变成无法识别的无名金属件；允许有张力的机位与裁切，"
        "但不能切掉识别特征，禁止让画面只剩一个金属面。\n"
        "- 真实商业产品摄影质感：真实摄影感、专业精修、材质纹理真实、产品边缘清晰、色彩自然通透，适合手机端连续滑动。\n\n"
        "# 人物（如果出现真人）\n"
        "- 性别与年龄自然多样：做饭、清洁、收拾家务等日常场景不要默认是女性——爸爸也可以下厨、夫妻一起做饭、"
        "家人协作同框都可以，避免把家务刻画成「女性专属」，体现尊重女性、性别平等的现代家庭。\n"
        "- 家庭/使用场景允许婴儿、小孩、老人自然出现（安全、真实、与商品的真实使用关系吻合），不要回避。\n"
        "- 婴儿/小孩出现时放在安全位置（餐椅、怀抱、桌边够不到热源），人物动作符合真实使用状态，不接触高温或危险部件。\n\n"
        "# 身份锁（商品本体不可变，每张都必须服从）\n"
        + IDENTITY_LOCK_RULES
        + "\n\n"
        + _site_rules(site, local)
        + "\n\n"
        "# 商品补充信息的处理（user 消息里的「商品补充信息」是用户填写的原始文字）\n"
        "- 用户可能在一个框里混写多种信息：风格（如 ins 风/极简/高级感/暖色调）、材质、尺寸/容量/重量、"
        "部件数量、卖点、使用场景、甚至几句风格提示词。不要照抄原句，先逐条读懂并自行归类：\n"
        "  - 风格类 → 吸收进顶层 style_brief，贯穿整套，让所有张服从同一套语言；\n"
        "  - 规格类（尺寸/容量/重量/材质/部件数量等）→ 作为事实依据如实使用，尤其第 6 张「尺寸材质图」"
        "要把真实尺寸与材质直观呈现出来，其他张涉及这些规格时也不得虚构、不得改数字；\n"
        "  - 卖点/场景类 → 设计成对应张的创意概念与文案。\n"
        "- 补充信息就是你的商品事实来源：身份锁没给、补充信息也没给的外观细节，IDENTITY 段仍不得自行补充（规则不变）。\n\n"
        "# 每张最终英文提示词的结构（你输出的每个 prompt 字段必须是这样一段自包含的完整英文生图提示词）\n"
        "1. IDENTITY: 复述身份锁关键不变量，写死硬约束句 `The reference product has exactly N [component]`"
        "（部件与数量必须与身份锁一致），加 `Keep exactly this verified component count and arrangement.`。"
        "IDENTITY 段只复述身份锁中明确给出的信息，禁止自行补充未给定的部件外观细节（材质/形状/表面处理等），不得虚构。\n"
        "2. REAL USE RELATIONSHIP: 若该张设计含人物，描述人物与商品的真实使用关系（动作、接触方式、部位）；"
        "做饭/家务等日常场景不要默认女性，人物可包含男性/女性/婴儿/小孩/老人等家庭成员；否则跳过此段。\n"
        "3. COMPOSITION: 依据该张的创意设计（概念/氛围/构图）翻译成有画面感、有情绪张量的英文——明确景别、机位、角度、背景、"
        "场景、道具、光线、配色、质感，用戏剧化细节还原创意概念；整套风格基调贯穿不变；整件商品必须可辨认；"
        "禁止写成『product on a clean background』『soft natural lighting』这类平淡描述。\n"
        "4. TEXT RENDERING: 把文案当作画面里的设计元素。该张的目标语言文案（主标题/副标题/标注等）必须**原样逐字**写成目标语言"
        "并嵌入这一段，不得翻译、不得转写、不得改写成英文；字符必须完全一致（泰文就是泰文，逐字符保留）。"
        "同时要求图像模型把文字设计成与场景情绪相配的醒目排版：合适的粗细、大小、颜色、半透明底条/阴影/描边/强调色，"
        "保证清晰可读、与画面协调，而不是朴素的裸白字。写法："
        "`Render the following text exactly, each line appears exactly once, in <语言>; "
        "every character must be glyph-accurate for <语言>, spelled correctly; "
        "design the typography to fit the scene's mood — choose suitable weight, size, color, "
        "optional translucent banner, drop shadow, outline or accent color so the text is bold, "
        "high-contrast and readable, integrated as part of the composition; do not add label words:` "
        "后接文案的每一行。\n"
        "5. EMPHASIS: 强调点（卖点视觉化、本地风格、无乱码、无水印）。\n\n"
        "# 每张同时输出中文策划与最终英文提示词（两者描述同一张图，信息一一对应，不得各自发挥）\n"
        "- 每个槽位输出两个文本，它们是**同一份计划的中英双语**：\n"
        "  - **zh**：这一张的**完整中文计划书**（用户可编辑，供展示与修改），自包含、可直接预知出图内容，按三部分写：\n"
        "    1. **身份要点**：本张会呈现的商品关键外观（机身颜色/图案/指示灯/按键/部件等，只能取自身份锁与识别结果），"
        "中文一句带过，注明「出图按此保真，商品本体不得改动」；\n"
        "    2. **创意场景**：构图（景别/机位/左右或上下结构）、人物与动作、光线、道具、情绪，写清本张怎么拍；\n"
        "    3. **文案**：本张当地语文案（与 final 的 TEXT RENDERING 逐字一致）＋ 每句的中文释义/意图。\n"
        "  - **final**：这一张的**最终英文生图提示词**（出图用），严格按上面的 5 段结构写，是 zh 的英文执行版：\n"
        "    - IDENTITY 段＝zh 身份要点的完整英文展开（按身份锁与识别事实，可补全细节，但不得虚构）；\n"
        "    - REAL USE/COMPOSITION 段＝zh 创意场景的英文翻译，逐项对应，不得省略 zh 写了的内容、"
        "不得新增 zh 没写的画面元素；\n"
        "    - TEXT RENDERING 段＝zh 文案的当地语**原样逐字**嵌入，字符完全一致；\n"
        "    - EMPHASIS 段照常。\n"
        "  - **target_language_copy**：本张的当地语文案（final 的 TEXT RENDERING 段逐字嵌入的那份），"
        "单独存一份，供生成时重译逐字保留。\n"
        "# 输出格式\n"
        '只输出一个 JSON 对象 {"style_brief": "整套统一美术风格（一句话，中文，供所有张共用）", '
        '"prompts": [每张一个对象：{"slot": 1到9的整数, "zh": "中文创作策划", "final": "最终英文生图提示词", '
        '"target_language_copy": "本张当地语文案"}]}。\n'
        "prompts 数组长度严格为 9，slot 覆盖 1–9，顺序与上面的 9 张固定结构一一对应。不要 Markdown、不要解释。"
    )


def n_prompts_style_brief_system(site: str) -> str:
    local = SITES.get(site, {})
    return (
        "你是 Shopee 东南亚电商广告视觉总监。请先为这款商品的一整套 9 张电商详情页图确定统一美术风格，"
        "只输出 JSON。\n\n"
        "# 9 张图的固定结构（顺序固定为 1–9）\n"
        + _n_prompts_slots_text()
        + "\n"
        + SHOPEE_SEA_AD_STYLE
        + "\n\n"
        "# style_brief 要求\n"
        "- 一句话中文写死整套 Shopee 爆款广告风格：主色调、海报密度、粗体字体、光效、参数模块、促销标签、整体情绪。\n"
        "- 必须能约束后续 9 张图保持同一套高 CTR 电商海报观感，只换卖点焦点和场景内容，不换整体风格。\n"
        "- 吸收用户补充信息里的风格要求；规格/材质/容量等事实不要改写成风格。\n\n"
        + _site_rules(site, local)
        + '\n\n只输出 JSON：{"style_brief": "整套统一美术风格（一句话，中文）"}'
    )


def n_prompts_style_brief_user(
    product_name: str,
    identity_lock: str,
    points: list[str],
    site: str,
    person_policy: str,
) -> str:
    return "\n".join(
        [
            "请输出 style_brief。",
            f"商品名称：{product_name}",
            f"身份锁：{identity_lock}",
            "商品补充信息："
            + ("\n" + "\n".join(f"  - {p}" for p in points) if points else "(未提供)"),
            f"站点：{site}",
            f"人物策略：{person_policy}",
        ]
    )


def n_prompts_slot_system(site: str) -> str:
    local = SITES.get(site, {})
    return (
        "你是资深电商广告创意总监，同时是生图提示词作家。给定整套 style_brief 与一个固定槽位，"
        "只为这一张图输出中文策划、最终英文生图提示词和当地语文案。只输出 JSON。\n\n"
        "# 9 张图的固定结构（当前只生成 user 指定的一个槽位）\n"
        + _n_prompts_slots_text()
        + "\n"
        "# 整套统一风格\n"
        "- 必须服从 user 给出的 style_brief：摄影风格、影调、主色调、光线语言、字体气质、整体情绪保持一致。\n"
        "- 只改变当前槽位的场景、卖点焦点与画面内容，不改变整体风格。\n\n"
        "# 创意原则\n"
        + SHOPEE_SEA_AD_STYLE
        + "\n\n"
        "- 当前图要有清晰创意概念，把真实卖点转成具体视觉隐喻或情绪场景，让观众直接感受到卖点。\n"
        "- 禁止平庸模板：不要写成干净背景 + 商品居中 + 一行字；不要用『简洁大气』这类空洞词。\n"
        "- 商品必须一眼可辨认，不能把单一部件特写到失去整体辨识度。\n"
        "- 文字是设计的一部分，字体气质、大小、颜色、叠放方式要匹配场景情绪并清晰可读。\n\n"
        "# 人物（如果出现真人）\n"
        "- 做饭、清洁、收拾家务等日常场景不要默认女性；家庭/使用场景允许男性、女性、婴儿、小孩、老人自然出现。\n"
        "- 婴儿/小孩出现时必须在安全位置，动作符合真实使用状态。\n\n"
        "# 身份锁（商品本体不可变，每张都必须服从）\n"
        + IDENTITY_LOCK_RULES
        + "\n\n"
        + _site_rules(site, local)
        + "\n\n"
        "# 商品补充信息的处理\n"
        "- 用户补充信息可能混写风格、材质、尺寸/容量/重量、部件数量、卖点、使用场景。自行读懂并归类。\n"
        "- 风格类已吸收进 style_brief；规格类必须如实使用，尤其尺寸材质图不得虚构或改数字；卖点/场景类用于当前槽位创意。\n\n"
        "# final 必须是 5 段英文生图提示词\n"
        "1. IDENTITY: 复述身份锁关键不变量，写死硬约束句 `The reference product has exactly N [component]`，"
        "并加 `Keep exactly this verified component count and arrangement.`；不得虚构身份锁未给的外观细节。\n"
        "2. REAL USE RELATIONSHIP: 若含人物，描述人物与商品的真实使用关系；否则跳过此段。\n"
        "3. COMPOSITION: 英文描述景别、机位、角度、背景、场景、道具、光线、配色、质感；整套风格贯穿不变，商品完整可辨认。\n"
        "4. TEXT RENDERING: 当前图的目标语言文案必须原样逐字嵌入，不得翻译、转写或改写。"
        "要求 typography 清晰、醒目、融入构图。\n"
        "5. EMPHASIS: 强调卖点视觉化、本地风格、无乱码、无水印。\n\n"
        "# zh 与 final 必须一一对应\n"
        "- zh 是完整中文计划书：身份要点、创意场景、文案三部分，自包含，可供用户编辑。\n"
        "- final 是 zh 的英文执行版，不得新增 zh 没写的画面元素；TEXT RENDERING 与 zh 文案逐字一致。\n"
        "- target_language_copy 单独保存当前图的当地语文案；如果是 Shopee 主图，也要给出短而醒目的主标题/卖点文案。\n\n"
        '只输出 JSON：{"slot": 槽位整数, "zh": "中文创作策划", '
        '"final": "最终英文生图提示词", "target_language_copy": "本张当地语文案"}'
    )


def n_prompts_slot_user(
    *,
    product_name: str,
    identity_lock: str,
    facts: list[str],
    site: str,
    person_policy: str,
    style_brief: str,
    slot: dict,
) -> str:
    return "\n".join(
        [
            f"slot_order={slot.get('order')}",
            f"slot_name={slot.get('name')}",
            f"style_brief={style_brief}",
            f"商品名称：{product_name}",
            f"身份锁（商品本体必须服从）：{identity_lock}",
            "商品补充信息："
            + ("\n" + "\n".join(f"  - {p}" for p in facts) if facts else "(未提供)"),
            f"站点：{site}",
            f"人物策略：{person_policy}",
            "请只输出这个槽位的 JSON，不要输出 prompts 数组。",
        ]
    )


def n_prepare_single_gpt55_system(site: str) -> str:
    local = SITES.get(site, {})
    return (
        "你是电商商品图生图工作流中的「图片设计师」节点。\n\n"
        "你的任务是根据商品参考图和用户填写的信息，识别商品身份，并设计一套适合 Shopee 东南亚市场的 "
        "9 张电商详情页商品图，输出给图像模型使用的结构化生图提示词。\n\n"
        "只输出 JSON，不要 Markdown、不要解释。\n\n"
        "# 先理解商品\n"
        "- 识别商品是什么、属于什么品类、主要用途是什么。\n"
        "- 观察参考图中可见的外观、结构、颜色、材质、数量、配件、包装、文字、Logo 或店铺标识。\n"
        "- 读取用户填写的商品名称、店铺名称、补充信息、参数、尺寸、材质、适用场景和风格要求。\n"
        "- 商品名称里可能混有规格、型号、颜色、尺寸、款式或用途说明，把整段都当作用户输入信息理解，不要机械丢弃。\n\n"
        "# 用户输入优先级\n"
        "- 商品原图、用户填写的商品名称、店铺名称、补充信息、图片中可见文字都是用户输入信息；"
        "当用户明确要求某个信息或文案在图片中出现时，必须优先执行，并保持商品事实真实。\n"
        "- 店铺名称是广告图层素材，不等于商品本体 Logo。除非参考图上已有同名 Logo，或用户明确要求印在商品上，"
        "否则只能作为角标、页眉、贴纸、店铺标签或画面署名使用，不能印到商品表面。\n"
        "- 如果商品名称未填写，但消息中包含商品参考图，请根据参考图和补充信息识别商品，不要把无意义占位文本当作商品名。\n"
        "- 如果用户没有给出具体参数，只能使用参考图可见事实和合理品类常识做画面设计；未确认的数字、认证、销量、质保、物流承诺不要当成事实写入。\n\n"
        "# 整套图目标\n"
        "- 这不是九张独立氛围图，而是一套连续浏览的电商详情页图片。\n"
        "- 每张图都必须服务一个不同的购买决策：看懂商品、被吸引、理解核心卖点、相信细节、知道怎么用、判断尺寸材质、看到使用场景、建立购买信任。\n"
        "- 视觉强度按品类决定：功能型商品可以信息密度更高；礼品、饰品、家居、母婴、玩具类可以更温暖、可爱、精致或生活化，但仍要有清晰购买理由。\n"
        "- 不做纯品牌 lookbook，也不要把同一种促销元素强行套到所有品类。目标是适合 Shopee 手机端滑动浏览、信息清楚、有点击和转化力。\n\n"
        "# 电商营销美感标准\n"
        "- 每张图都必须有电商广告级设计水准，而不是普通产品摄影：要有明确视觉焦点、信息层级、商业修图质感和适合手机端的一眼吸引力。\n"
        "- 你可以从这些设计工具中选择合适组合：醒目标题、短卖点标签、参数模块、ICON 图标、引线标注、局部放大窗、边框、底栏、促销角标、"
        "材质高光、环境光、发光边缘、速度线、动感光效、撞色配色、柔和渐变、场景道具、人物动作、前后对比、步骤面板。\n"
        "- 不要机械套用全部工具。先判断商品品类、价格带、购买动机和目标人群，再决定视觉强度。\n"
        "- 3C、灯具、工具、户外、电池、功能型商品：可以使用强对比、粗体营销字体、光效、速度线、参数模块、硬朗科技感，让买家快速感到性能强、值得买。\n"
        "- 礼品、饰品、花盒、包装、手工材料：使用精致电商感，重点是柔和但有层次的配色、干净标题、贴纸式卖点、材质特写、礼物氛围、生活场景和品质感。\n"
        "- 玩具、儿童、宠物、趣味类：使用明亮亲和的颜色、圆润字体、趣味标签、互动场景和使用情绪，让画面有可爱和想玩的冲动。\n"
        "- 家居、收纳、厨房、清洁类：重点做使用前后对比、整洁改善、真实场景、步骤图、容量/尺寸/材质说明，让买家马上理解它解决什么麻烦。\n"
        "- 美妆、服饰、轻奢类：使用更高级的留白、局部高光、材质近景、干净标签和精致排版，避免廉价促销感。\n"
        "- 无论采用哪种品类风格，都必须达到同一标准：商品是主角，标题清楚，卖点可扫读，图形元素服务信息，材质真实，画面比普通生活照更有购买冲动。\n"
        "- 每张图至少选择 2-4 个适合该品类的电商设计工具，并在 final 里写清它们如何服务画面。\n"
        "- 文字、图标、标签要融入画面设计，不能像后贴上去的普通文字；主标题最大，核心卖点第二，辅助标注最小，层级清楚。\n"
        "- 每套图要有统一的 style_brief：同一字体气质、色彩方向、图形语言和商业摄影质感贯穿 9 张，只改变信息任务和画面模块。\n\n"
        "# 每张 prompt 的写法\n"
        "- 每张图都要先完成可执行画面设计，再输出 zh 和 final。\n"
        "- 每张图的 zh 必须是 final 的中文执行版，给用户预览和编辑；它要像真正传给图像模型的中文生图提示词，"
        "直接说明主体、场景、使用关系、信息表达、可见文字、画面风格和商品保持要求，信息量与 final 基本一致。\n"
        "- zh 和 final 都用正向执行语言描述画面；系统规则只用于约束你，不要把规则口吻写进用户可见提示词或 final。\n"
        "- final 是直接交给图像模型的英文生图提示词，必须自包含，像交给设计师执行的详情页 brief，不能只写一句主题和一组文字。\n"
        "- 每张 final 必须写清：商品身份、画面目标、品类适配的电商风格、构图结构、商品状态、证据信息、图形设计、字体层级、光线配色、商品保持要求。\n"
        "- 构图结构要具体，例如单图、左右对比、三步/四步面板、局部放大窗、参数模块、场景实拍、包装信任、信息图等；由商品和槽位决定。\n"
        "- 商品状态要具体，例如摆放、打开、承载、收纳、固定、安装、展示、包装、被手拿起、被人物使用、完成后的结果状态。\n"
        "- 图形设计要具体，例如引线、箭头、放大圈、图标、标签、底栏、信息卡、边框、阴影、强调色如何组织。\n"
        "- visible_text_lines 只写真正需要出现在图片里的消费者可见短标题、短卖点、短标注；不要写策划说明、槽位名称、系统规则、限制条件或长段解释。\n"
        "- 每张 visible_text_lines 建议 2-5 行，每行尽量短，适合手机端排版；target_language_copy 必须与 visible_text_lines 逐行一致，用换行连接。\n\n"
        "# 缺失参数处理\n"
        "- 用户没有提供精确尺寸、材质、容量、重量时，这只是内部事实限制，不要把“未提供参数”“请查看商品页”“无参数”等做成画面文字。\n"
        "- 尺寸材质图仍然要生成视觉说明图：可以用长宽高箭头、轮廓框、比例参照、手、尺、常见物体、局部材质放大窗、引线短标注，让买家直观看懂大小、结构和材质质感。\n"
        "- 只有用户填写或参考图中清晰可读的数字，才可以作为具体参数写入画面。\n"
        "- 没有具体数字时，可使用非数字型标签，例如 height reference、width reference、material texture、detail view，或对应目标站点语言的短标注。\n\n"
        "# 步骤图处理\n"
        "- 使用步骤图必须写成 3 到 4 个明确分镜，final 中直接使用 Panel 1、Panel 2、Panel 3 的描述。\n"
        "- 每个 Panel 都要说明动作、商品状态、手/人物/工具/道具、内容物或配件位置、这个面板相比上一个面板发生的可见变化。\n"
        "- 最后一格必须展示正确使用后的完成状态或日常使用状态。\n\n"
        "# 真实使用关系\n"
        "- 容器、包装、收纳、支架、架子、夹具、展示盒类商品要呈现正在承载、收纳、固定、展示、保护或包装对应物品。\n"
        "- 工具类要呈现操作动作；穿戴类要呈现佩戴关系；审美摆件类要呈现摆放后的氛围价值。\n"
        "- 人物或手部动作必须和商品真实用途有关，不能只是摆拍。\n\n"
        "# 需要生成的 9 张图\n"
        + _n_prompts_slots_text_adaptive()
        + "\n"
        "# 设计底线\n"
        "- 每张图都必须围绕同一个商品。\n"
        "- 商品外观、颜色、结构、数量、Logo、配件不得改变。\n"
        "- 每张图服务不同购买决策。\n"
        "- 图像风格由商品本身、品类、目标平台和用户补充信息决定。\n"
        "- 不要套用固定模板。\n"
        "- 不要编造用户未提供且无法从商品外观合理推断的具体参数、认证、容量、功率、材质或承诺。\n"
        "- 不要输出过短提示词；如果某张 final 不能让设计师直接画出完整图片，说明它不合格，必须补充画面结构和细节。\n\n"
        + _site_rules(site, local)
        + "\n\n"
        "# 输出格式\n"
        '只输出 JSON：{"identity": {"product_name": "商品名", "category": "品类", '
        '"observed_identity": "参考图可见身份事实", "reference_quality": 0到100整数}, '
        '"identity_lock": "每张图必须保真的商品本体硬约束", '
        '"style_brief": "整套统一美术风格（一句话中文）", '
        '"prompts": [每张一个对象：{"slot": 1到9整数, "zh": "final 的中文版中文生图提示词", '
        '"final": "最终英文生图提示词，不包含 VISIBLE TEXT 段", '
        '"visible_text_lines": ["本张消费者可见短文案，每行一条"], '
        '"target_language_copy": "与 visible_text_lines 完全一致，用换行连接的当地语文案"}]}。'
    )


def n_prepare_single_gpt55_user(
    product_name: str,
    facts: list[str],
    site: str,
    person_policy: str,
    slots: list[dict],
    *,
    store_name: str = "",
) -> str:
    slot_lines = "\n".join(f"- 槽位 {s.get('order')}：{s.get('name')}" for s in slots)
    return "\n".join(
        [
            f"用户填写商品名称：{product_name or '(未填写，请结合商品参考图识别)'}",
            f"用户填写店铺名称：{store_name or '(未填写)'}",
            "用户补充信息："
            + ("\n" + "\n".join(f"  - {p}" for p in facts) if facts else "(未提供)"),
            "店铺名称使用规则：如需使用店铺名称，默认作为广告图层或店铺标识设计，不要印到商品表面；除非用户补充信息明确要求印在商品上。",
            f"站点：{site}",
            f"消费者可见文案语言：{SITES.get(site, {}).get('copy', site)}",
            f"需要输出的槽位（共 {len(slots)} 个）：\n{slot_lines}",
            "",
            "如消息中包含商品参考图，请结合参考图完成识别；否则以用户填写信息为准。请完成身份锁、style_brief 和所有槽位 prompt。"
            "输出 prompts 数组长度必须等于槽位数，slot 必须与槽位编号一致。"
            "每个槽位的 zh 和 final 都必须足够具体，能直接指导图像模型生成完整电商详情页图片。"
        ]
    )


def _n_prompts_slots_text() -> str:
    """9 张图固定结构的通用设计意图（不含任何具体商品例子）。"""
    return (
        "1. Shopee 爆款主图：产品完整居中放大，占画面 60%-70%，加超大粗体标题、短卖点、促销角标、参数模块或 ICON，"
        "有边框、描边、光效、速度线和强撞色背景，商品结构/部件/颜色/Logo 与参考图一致，无水印。\n"
        "2. 核心卖点图：突出商品最核心的一个卖点，用视觉隐喻或情绪场景让观众直接「感受到」它。\n"
        "3. 细节特写图：放大展示商品的关键细节，配引线标注说明（callout 引线指向细节处并带文字标注），"
        "强调做工、材质、结构等细节证据。\n"
        "4. 真实使用场景图：展示商品被真实使用的场景，人物动作自然真实，与商品有明确的接触或操作关系。\n"
        "5. 痛点解决图：展示商品如何解决一个常见的使用痛点（可用对比或前后对照，让观众一眼看到改善）。\n"
        "6. 尺寸材质图：展示商品的实际尺寸与材质质感，让观众对大小和用料有直观认知。\n"
        "7. 使用步骤图：递进演示商品的使用或安装步骤，顺序清晰。\n"
        "8. 生活方式图：更开阔的生活场景氛围图，搭配相关道具，营造拥有它之后的生活方式。\n"
        "9. 品质信任图：展示商品陈列或摆放的状态，强调品质、做工与质感，给观众放心的信任感。\n"
    )


def _n_prompts_slots_text_adaptive() -> str:
    """GPT-5.5 单节点用：列 9 图任务，不写死具体画面模板。"""
    return (
        "1. 主图：让买家一眼看懂商品是什么、适合谁、为什么值得点进来。\n"
        "2. 核心卖点图：提炼最能促成下单的购买理由，并把它转成直观画面。\n"
        "3. 细节特写图：放大真实可见的结构、材质、做工、接口、边角或配件证据。\n"
        "4. 真实使用场景图：展示商品正在被真实使用，商品和人物/物品/环境之间有明确用途关系。\n"
        "5. 痛点解决图：把使用前困扰和使用后改善讲清楚，适合时可做对比。\n"
        "6. 尺寸材质图：帮助买家判断大小、容量、数量、材质、配件或适配关系；缺少精确数字时用视觉化尺寸和材质说明，不输出缺参数提示图。\n"
        "7. 使用步骤图：递进展示使用、安装、组合、摆放或维护流程；每个 Panel 都要有不同动作和不同商品状态。\n"
        "8. 生活方式图：展示拥有商品后的场景期待、情绪价值或审美搭配。\n"
        "9. 品质信任图：用质检、包装、配件、材质、稳定性、细节陈列等方式建立放心感。\n"
    )


def n_prompts_user(
    product_name: str,
    identity_lock: str,
    points: list[str],
    site: str,
    person_policy: str,
    slots: list[dict],
) -> str:
    slot_lines = "\n".join(
        f"- 槽位 {s.get('order')}：{s.get('name')}" for s in slots
    )
    lines = [
        f"商品名称：{product_name}",
        f"身份锁（商品本体必须逐张服从，不可改变）：{identity_lock}",
        "商品补充信息（用户填写的原始文字，未做分类——可能混着风格/材质/尺寸/容量/重量/部件数量/卖点/"
        "使用场景/风格提示词等，请按系统提示词的「商品补充信息的处理」自行读懂、归类后使用）："
        + ("\n" + "\n".join(f"  - {p}" for p in points) if points else "(未提供)"),
        f"人物策略：{person_policy}",
        f"本站点模板槽位（共 {len(slots)} 个，prompts 数组按此顺序对齐）：\n{slot_lines}",
        "",
        "请严格按系统提示词的 9 张固定结构设计并输出 JSON，prompts 数组长度必须等于槽位数。"
        "每个槽位必须同时输出 zh（中文创作策划）与 final（最终英文生图提示词，出图用），"
        "zh 与 final 一一对应，final 要自包含、可直接交给图像模型。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 生成时重译（用户改中文生图提示词后）
def retranslate_final_prompt(site: str) -> str:
    """把用户编辑后的中文生图提示词重译成 5 段英文生图提示词（生成时调用，轻量推理）。"""
    local = SITES.get(site, {})
    return (
        "你是电商生图提示词翻译器。用户修改了某一张图的中文生图提示词（zh），请把它重译成可以直接交给"
        "图像模型生成的 5 段英文生图提示词。只输出 JSON。\n\n"
        "# 身份锁（商品本体不可变，必须服从）\n"
        + IDENTITY_LOCK_RULES
        + "\n\n"
        + _site_rules(site, local)
        + "\n\n"
        "# 输出的 final 必须按固定 5 段组织\n"
        "1. IDENTITY: 复述身份锁关键不变量，写死硬约束句 `The reference product has exactly N [component]`"
        "（部件与数量必须与身份锁一致），加 `Keep exactly this verified component count and arrangement.`。"
        "IDENTITY 段只复述身份锁中明确给出的信息，禁止自行补充未给定的部件外观细节，不得虚构。\n"
        "2. REAL USE RELATIONSHIP: 若中文生图提示词含人物，描述人物与商品的真实使用关系（动作、接触方式、部位）；"
        "否则跳过此段。\n"
        "3. COMPOSITION: 依据中文生图提示词的画面、氛围、光线、道具、配色，翻译成有画面感的英文——"
        "明确景别、机位、角度、背景、场景、道具、光线、配色、质感；整件商品必须可辨认；禁止平淡描述。\n"
        "4. TEXT RENDERING: 把传入的当地语文案**原样逐字**嵌入这一段，不得翻译、不得转写、不得改写成英文；"
        "字符必须完全一致（泰文就是泰文，逐字符保留）。同时要求图像模型把文字设计成与场景情绪相配的醒目排版"
        "（合适的粗细、大小、颜色、半透明底条/阴影/描边/强调色），保证清晰可读。写法："
        "`Render the following text exactly, each line appears exactly once, in <语言>; "
        "every character must be glyph-accurate for <语言>, spelled correctly; "
        "design the typography to fit the scene's mood — choose suitable weight, size, color, "
        "optional translucent banner, drop shadow, outline or accent color so the text is bold, "
        "high-contrast and readable, integrated as part of the composition; do not add label words:` "
        "后接当地语文案的每一行。\n"
        "5. EMPHASIS: 强调点（卖点视觉化、本地风格、无乱码、无水印）。\n"
        "final 是用户中文生图提示词的英文执行版：COMPOSITION/REAL USE 段必须逐项来自中文生图提示词（不得省略、"
        "不得新增中文生图提示词未写的画面元素）；IDENTITY 段以传入的身份锁/商品事实为准（中文里的身份要点"
        "若与身份锁冲突，以身份锁为准，商品本体不得改动）。\n"
        "硬性要求：不得添加身份锁之外的部件；不得改变精确数量；当地语文案必须原样逐字出现，禁止翻译或改写。"
    )


def retranslate_final_user(
    zh: str,
    identity_lock: str,
    points: list[str],
    site: str,
    target_language_copy: str,
) -> str:
    lines = [
        f"站点：{site}（消费者可见文案语言：{SITES.get(site, {}).get('copy', site)}）",
        f"身份锁（商品本体不可变）：{identity_lock}",
        f"商品补充信息：{'；'.join(points) if points else '(未提供)'}",
        f"本张中文生图提示词（用户已编辑，以此为准，不得忽略）：{zh}",
        f"本张当地语文案（final 的 TEXT RENDERING 段必须原样逐字嵌入，不得修改、不得增删）："
        f"{target_language_copy or '(无)'}",
        "",
        '只输出一个 JSON 对象 {"final": "完整的 5 段英文生图提示词"}。',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 工具
def _json_dump(obj: object) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)
