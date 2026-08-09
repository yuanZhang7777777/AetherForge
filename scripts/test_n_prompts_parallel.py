"""Deterministic check for the N2 split-slot prompt writer.

No network calls: a fake DeepSeek client proves the service calls one style
brief request plus one low-effort request per slot and normalizes the result.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.services.prepare as prepare_module
from backend.prompts import n_prepare_single_gpt55_system, n_prepare_single_gpt55_user, retranslate_final_prompt
from backend.services.prepare import _generate_n_prompts_parallel, _gpt55_single_node, _merge_single_node_identity, _n_prompts
from backend.services.prepare import _prompt_item
from backend.services.serialize import _prompt_slot_metadata


class FakeDeepSeek:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_json(self, system: str, user: str, **kwargs):
        self.calls.append({"system": system, "user": user, "kwargs": kwargs})
        if user.startswith("请输出 style_brief"):
            return {"json": {"style_brief": "统一奶油白摄影风格"}}
        slot = int(user.split("slot_order=")[1].splitlines()[0])
        return {
            "json": {
                "slot": slot,
                "zh": f"槽位 {slot} 中文生图提示词",
                "final": f"Slot {slot} final prompt. The reference product has exactly one body.",
                "target_language_copy": f"文案 {slot}",
            }
        }


def rich_final(subject: str = "the reference product") -> str:
    return (
        f"Create a complete ecommerce detail image for {subject}. "
        "Composition: place the product as the clear hero with a designed information hierarchy, clean commercial lighting, "
        "supporting props that explain the use case, and enough empty space for readable sales copy. "
        "Show the product state, visible structure, material texture, and practical benefit with callout labels, icons, "
        "arrows, small inset detail windows, and a clear headline area. "
        "Keep the reference product appearance, color, quantity, structure, and key identity unchanged. "
        "Use polished marketplace typography and high-resolution product photography styling."
    )


def rich_zh(subject: str = "参考商品") -> str:
    return (
        f"为{subject}生成完整电商详情图，商品作为清晰主角，画面包含商业摄影光线、使用场景道具、"
        "卖点标题、图标标签、引线、局部放大窗和信息层级，清楚展示商品状态、材质质感和购买理由，"
        "并保持参考图中的外观、颜色、结构、数量和关键识别点不变。"
    )


def main() -> None:
    test_parallel_slot_generation()
    test_parallel_failure_falls_back_to_single_call()
    test_prompt_item_front_loads_shopee_ad_style_and_visible_copy()
    test_prompt_item_can_skip_legacy_front_load()
    test_prompt_item_normalizes_literal_newlines()
    test_prompt_item_prefers_short_visible_text_lines_and_strips_long_block()
    test_prompt_item_recovers_visible_text_from_zh()
    test_gpt55_system_prompt_is_neutral_designer_node()
    test_gpt55_system_treats_store_name_as_ad_layer()
    test_retranslate_uses_edited_zh_as_complete_source()
    test_legacy_display_prompt_includes_saved_visible_text()
    test_gpt55_single_node_uses_one_apimart_call()
    test_gpt55_single_node_always_sends_image_input_when_product_name_is_filled()
    test_gpt55_single_node_ignores_import_filename_placeholder_when_ai_recognition_enabled()
    test_gpt55_single_node_does_not_write_back_identity_when_ai_recognition_is_disabled()
    test_gpt55_single_node_does_not_block_short_prompts()
    print("PASS: split-slot N2 prompt writer")


def test_parallel_slot_generation() -> None:
    slots = [
        {"order": 1, "name": "Shopee high-CTR main poster"},
        {"order": 2, "name": "Key benefit"},
        {"order": 3, "name": "Detail close-up"},
    ]
    client = FakeDeepSeek()
    style_brief, prompts = _generate_n_prompts_parallel(
        client,
        product_name="智能电饭煲",
        identity_lock="主商品 智能电饭煲：部件、数量、颜色、布局与参考图一致。",
        facts=["3.5L 大容量"],
        site="TH",
        person_policy="日常使用类，可出现真实家庭人物",
        slots=slots,
    )

    assert style_brief == "统一奶油白摄影风格"
    assert sorted(prompts) == [1, 2, 3]
    assert prompts[2]["zh"].startswith("槽位 2 中文生图提示词")
    assert prompts[2]["zh"].endswith("画面可见文字：\n文案 2")
    assert prompts[3]["target_language_copy"] == "文案 3"
    assert len(client.calls) == 4, client.calls
    slot_calls = client.calls[1:]
    assert all(call["kwargs"]["reasoning_effort"] == "low" for call in slot_calls)
    assert all(call["kwargs"]["thinking"] is True for call in slot_calls)


def test_parallel_failure_falls_back_to_single_call() -> None:
    class FallbackClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def complete_json(self, system: str, user: str, **kwargs):
            self.calls.append(system)
            if "请先为这款商品的一整套" in system:
                raise RuntimeError("parallel style failed")
            return {
                "json": {
                    "style_brief": "旧路径统一风格",
                    "prompts": [
                        {
                            "slot": 1,
                            "zh": "旧路径中文生图提示词",
                            "final": "Fallback final prompt. The reference product has exactly one body.",
                            "target_language_copy": "旧路径文案",
                        }
                    ],
                }
            }

    fake_client = FallbackClient()
    original_client = prepare_module.DeepSeekClient
    prepare_module.DeepSeekClient = lambda: fake_client
    try:
        slot = SimpleNamespace(order=1, name="Shopee high-CTR main poster", id="slot-1")
        cluster = SimpleNamespace(
            name="智能电饭煲",
            product_name="智能电饭煲",
            identity_lock="主商品 智能电饭煲：部件、数量、颜色、布局与参考图一致。",
            product_facts="3.5L 大容量",
            analysis_snapshot={},
            batch=SimpleNamespace(output_template=SimpleNamespace(slots=[slot]), global_prompt=""),
        )
        style_brief, prompts = _n_prompts(None, cluster, "TH")
    finally:
        prepare_module.DeepSeekClient = original_client

    assert style_brief == "旧路径统一风格"
    assert prompts[1]["zh"].startswith("旧路径中文生图提示词")
    assert len(fake_client.calls) == 2


def test_prompt_item_front_loads_shopee_ad_style_and_visible_copy() -> None:
    parsed = _prompt_item({
        "slot": 1,
        "zh": "Shopee 主图：红黄撞色，大标题，促销角标。",
        "target_language_copy": "HOT SALE\nส่งฟรี",
        "final": (
            "IDENTITY: The reference product has exactly one rice cooker. "
            "TEXT RENDERING: Embed the Thai copy exactly as provided in the target_language_copy field."
        ),
    })
    assert parsed is not None
    _, prompt = parsed
    assert prompt["final"].startswith("Create a high-CTR Shopee Southeast Asia marketplace advertising poster")
    assert "target_language_copy field" not in prompt["final"]
    assert "HOT SALE" in prompt["final"]
    assert "ส่งฟรี" in prompt["final"]
    assert "画面可见文字：" in prompt["zh"]
    assert prompt["zh"].endswith("HOT SALE\nส่งฟรี")


def test_prompt_item_can_skip_legacy_front_load() -> None:
    parsed = _prompt_item(
        {
            "slot": 1,
            "zh": "按玩具品类做柔和可爱风。",
            "target_language_copy": "นุ่มน่ากอด",
            "final": "IDENTITY: plush toy. TEXT RENDERING: target_language_copy field.",
        },
        front_load=False,
    )
    assert parsed is not None
    _, prompt = parsed
    assert not prompt["final"].startswith("Create a high-CTR Shopee Southeast Asia marketplace advertising poster")
    assert "red/yellow/black" not in prompt["final"]
    assert "นุ่มน่ากอด" in prompt["final"]


def test_prompt_item_normalizes_literal_newlines() -> None:
    parsed = _prompt_item(
        {
            "slot": 1,
            "zh": "第一行\\n第二行/n第三行",
            "target_language_copy": "标题\\n卖点",
            "final": "Line one.\\nLine two./nLine three.",
        },
        front_load=False,
    )
    assert parsed is not None
    _, prompt = parsed
    assert "\\n" not in prompt["zh"]
    assert "/n" not in prompt["zh"]
    assert "\\n" not in prompt["final"]
    assert "/n" not in prompt["final"]
    assert prompt["zh"] == "第一行\n第二行\n第三行\n画面可见文字：\n标题\n卖点"
    assert "Line one.\nLine two.\nLine three." in prompt["final"]
    assert prompt["target_language_copy"] == "标题\n卖点"


def test_prompt_item_prefers_short_visible_text_lines_and_strips_long_block() -> None:
    parsed = _prompt_item(
        {
            "slot": 9,
            "zh": rich_zh("品质信任图"),
            "visible_text_lines": ["พร้อมส่งมั่นใจ", "วัสดุเรียบร้อย", "แพ็กอย่างดี"],
            "target_language_copy": (
                "คุณภาพและความน่าเชื่อถือ: แสดงตราคุณภาพ ตรวจสอบคุณภาพ "
                "บรรจุภัณฑ์ที่มั่นคง เนื้อวัสดุและโครงสร้างที่แข็งแรง"
            ),
            "final": (
                "Quality and trust ecommerce image for the same reference product. "
                "Use packaging-table composition, close-up material insets, callout lines, clean commercial lighting, "
                "and a small corner store badge only as an overlay. "
                "VISIBLE TEXT: Render exactly these lines, each line once, with readable typography:\n"
                "คุณภาพและความน่าเชื่อถือ: แสดงตราคุณภาพ ตรวจสอบคุณภาพ บรรจุภัณฑ์ที่มั่นคง"
            ),
        },
        front_load=False,
    )
    assert parsed is not None
    _, prompt = parsed
    assert "คุณภาพและความน่าเชื่อถือ" not in prompt["final"]
    assert "Render exactly" not in prompt["final"]
    assert prompt["final"].endswith("พร้อมส่งมั่นใจ\nวัสดุเรียบร้อย\nแพ็กอย่างดี")
    assert prompt["target_language_copy"] == "พร้อมส่งมั่นใจ\nวัสดุเรียบร้อย\nแพ็กอย่างดี"
    assert prompt["zh"].endswith("画面可见文字：\nพร้อมส่งมั่นใจ\nวัสดุเรียบร้อย\nแพ็กอย่างดี")


def test_prompt_item_recovers_visible_text_from_zh() -> None:
    parsed = _prompt_item(
        {
            "slot": 4,
            "zh": "真实使用场景图，展示商品完成实际用途。\n画面可见文字：\nใช้งานจริง\nพร้อมทุกวัน",
            "final": "Real-life ecommerce use scene with the reference product completing its intended use.",
        },
        front_load=False,
    )
    assert parsed is not None
    _, prompt = parsed
    assert prompt["visible_text_lines"] == ["ใช้งานจริง", "พร้อมทุกวัน"]
    assert prompt["target_language_copy"] == "ใช้งานจริง\nพร้อมทุกวัน"
    assert prompt["final"].endswith("ใช้งานจริง\nพร้อมทุกวัน")


def test_gpt55_system_prompt_is_neutral_designer_node() -> None:
    text = n_prepare_single_gpt55_system("TH")
    assert "图片设计师" in text
    assert "先理解商品" in text
    assert "用户输入优先级" in text
    assert "用户输入信息" in text
    assert "必须优先执行" in text
    assert "整套图目标" in text
    assert "购买决策" in text
    assert "跨品类商业质量标准" in text
    assert "每张图至少选择 2-4 个适合该品类的电商设计工具" not in text
    assert "3C、灯具、工具、户外、电池" not in text
    assert "产品主体占画面 60%-70%" not in text
    assert "visible_text_lines" in text
    assert "让买家立即看懂商品是什么" in text
    assert "每张图都必须服务一个不同的购买决策" in text
    assert "电商详情页图片" in text
    assert "每张 prompt 的写法" in text
    assert "zh 必须是 final 的中文执行版" in text
    assert "真实使用关系" in text
    assert "英文生图提示词，必须自包含" in text
    assert "卖点证据" in text
    assert "可见文字" in text
    assert "给用户预览和编辑" in text
    assert "精确尺寸、容量、功率、认证和性能数字只使用用户或参考图明确提供的信息" in text
    assert "固定九槽" in text
    assert "使用步骤图" in text
    assert "不同动作和不同商品状态" in text
    assert "Panel 1、Panel 2、Panel 3" not in text
    assert "1–4" not in text
    assert "1-4" not in text
    for phrase in (
        "不要套用固定红黄大促模板",
        "不要复制任何示例图配色",
        "高大促",
        "强红黄背景",
        "递进演示使用或安装步骤，顺序清晰",
        "主图左上角默认",
        "左上角默认放店铺名",
        "产品名称是高优先级事实源",
        "尺寸/规格可能藏在产品名称",
        "A3/A4",
        "pcs/pack",
        "store_name",
        "variant_specs",
        "晾衣杆",
        "阳台",
        "蓝白",
        "橙色",
        "800x800",
        "文字使用英语",
    ):
        assert phrase not in text


def test_gpt55_system_treats_store_name_as_ad_layer() -> None:
    text = n_prepare_single_gpt55_system("TH")
    assert "店铺名称是广告图层素材，不等于商品本体 Logo" in text
    assert "不能印到商品表面" in text
    assert "角标、页眉、贴纸、店铺标签或画面署名" in text


def test_retranslate_uses_edited_zh_as_complete_source() -> None:
    text = retranslate_final_prompt("TH")
    assert "用户编辑后的 zh 是本张画面的唯一创意来源" in text
    assert "画面可见文字" in text
    assert "当地语言字符原样保留" in text
    assert "固定 5 段" not in text
    assert "The reference product has exactly N" not in text


def test_legacy_display_prompt_includes_saved_visible_text() -> None:
    prompt_version = SimpleNamespace(
        structured_output={
            "display_prompt": "完整中文生图提示词。",
            "visible_text_lines": ["ข้อความหลัก", "จุดขาย"],
            "node_output": {"display_prompt": "完整中文生图提示词。"},
        }
    )

    metadata = _prompt_slot_metadata(prompt_version)

    assert metadata["displayPrompt"] == "完整中文生图提示词。\n画面可见文字：\nข้อความหลัก\nจุดขาย"


def test_gpt55_user_prompt_passes_product_name_without_classifying() -> None:
    text = n_prepare_single_gpt55_user(
        "直接梯形马卡5号-黑色 菱格鲜花包装袋",
        ["店铺名称：Example Store", "尺寸：12cm x 8cm"],
        "PH",
        "",
        [{"order": 1, "name": "Shopee high-CTR main poster"}],
        store_name="Example Store",
    )
    assert "用户填写商品名称：直接梯形马卡5号-黑色 菱格鲜花包装袋" in text
    assert "用户填写店铺名称：Example Store" in text
    assert "默认作为广告图层或店铺标识设计，不要印到商品表面" in text
    assert "直接梯形马卡5号-黑色 菱格鲜花包装袋" in text
    assert "可能混含" not in text
    assert "都必须作为事实解析" not in text


def test_gpt55_single_node_uses_one_apimart_call() -> None:
    class FakeAPIMart:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def complete_json(self, system: str, user: str, **kwargs):
            self.calls.append({"system": system, "user": user, "kwargs": kwargs})
            return {
                "json": {
                    "identity": {
                        "product_name": "黄色毛绒玩具",
                        "category": "玩具",
                        "observed_identity": "黄色毛绒材质，圆形黑眼睛",
                        "reference_quality": 90,
                    },
                    "identity_lock": "主商品 黄色毛绒玩具：黄色毛绒材质、圆形黑眼睛与参考图一致。",
                    "style_brief": "柔和明亮的可爱玩具广告风格",
                    "prompts": [
                        {
                            "slot": 1,
                            "zh": rich_zh("黄色毛绒玩具主图"),
                            "final": rich_final("the yellow plush toy main poster"),
                            "target_language_copy": "ของเล่นนุ่ม",
                        },
                        {
                            "slot": 2,
                            "zh": rich_zh("黄色毛绒玩具核心卖点图"),
                            "final": rich_final("the yellow plush toy key benefit image"),
                            "target_language_copy": "สัมผัสนุ่ม",
                        },
                    ],
                }
            }

    fake_client = FakeAPIMart()
    original_client = prepare_module.APIMartClient
    prepare_module.APIMartClient = lambda: fake_client
    try:
        slots = [
            SimpleNamespace(order=1, name="Shopee high-CTR main poster", id="slot-1"),
            SimpleNamespace(order=2, name="Key benefit", id="slot-2"),
        ]
        cluster = SimpleNamespace(
            name="",
            product_name="",
            store_name="Toy Store",
            product_facts="",
            identity_lock="",
            analysis_snapshot={},
            cluster_assets=[],
            batch=SimpleNamespace(
                ai_recognition_enabled=True,
                output_template=SimpleNamespace(slots=slots),
                global_prompt="",
            ),
        )
        style_brief, prompts, node = _gpt55_single_node(None, cluster, "TH")
        _merge_single_node_identity(cluster, node)
    finally:
        prepare_module.APIMartClient = original_client

    assert len(fake_client.calls) == 1
    assert "用户填写店铺名称：Toy Store" in fake_client.calls[0]["user"]
    assert style_brief == "柔和明亮的可爱玩具广告风格"
    assert sorted(prompts) == [1, 2]
    assert "red/yellow/black" not in prompts[1]["final"]
    assert cluster.product_name == "黄色毛绒玩具"
    assert cluster.product_facts.startswith("黄色毛绒材质")
    assert cluster.identity_lock.startswith("主商品 黄色毛绒玩具")


def test_gpt55_single_node_always_sends_image_input_when_product_name_is_filled() -> None:
    class FakeAPIMart:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def complete_json(self, system: str, user: str, **kwargs):
            self.calls.append({"system": system, "user": user, "kwargs": kwargs})
            return {
                "json": {
                    "identity": {},
                    "identity_lock": "",
                    "style_brief": "按用户填写商品名设计",
                    "prompts": [{
                        "slot": 1,
                        "zh": rich_zh("用户填写商品名对应商品"),
                        "final": rich_final("the user-provided product"),
                        "target_language_copy": "สินค้า",
                    }],
                }
            }

    class FakeStorage:
        def local_path(self, storage_path: str):
            class Context:
                def __enter__(self):
                    return "local-product-image.png"

                def __exit__(self, exc_type, exc, tb):
                    return False

            return Context()

    fake_client = FakeAPIMart()
    original_client = prepare_module.APIMartClient
    original_storage = prepare_module.get_storage
    prepare_module.APIMartClient = lambda: fake_client
    prepare_module.get_storage = lambda: FakeStorage()
    try:
        cluster = SimpleNamespace(
            name="",
            product_name="手填商品名",
            store_name="",
            product_facts="",
            identity_lock="",
            analysis_snapshot={},
            cluster_assets=[SimpleNamespace(asset=SimpleNamespace(kind="image", storage_path="assets/front.png"))],
            batch=SimpleNamespace(
                ai_recognition_enabled=True,
                output_template=SimpleNamespace(slots=[SimpleNamespace(order=1, name="Shopee high-CTR main poster", id="slot-1")]),
                global_prompt="",
            ),
        )
        _gpt55_single_node(None, cluster, "TH")
    finally:
        prepare_module.APIMartClient = original_client
        prepare_module.get_storage = original_storage

    assert fake_client.calls[0]["kwargs"]["image_sources"] == ["local-product-image.png"]


def test_gpt55_single_node_ignores_import_filename_placeholder_when_ai_recognition_enabled() -> None:
    class FakeAPIMart:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def complete_json(self, system: str, user: str, **kwargs):
            self.calls.append({"system": system, "user": user, "kwargs": kwargs})
            return {
                "json": {
                    "identity": {},
                    "identity_lock": "",
                    "style_brief": "按图片识别商品后设计",
                    "prompts": [{
                        "slot": 1,
                        "zh": rich_zh("参考图识别商品"),
                        "final": rich_final("the product recognized from the reference photo"),
                        "target_language_copy": "สินค้า",
                    }],
                }
            }

    class FakeStorage:
        def local_path(self, storage_path: str):
            class Context:
                def __enter__(self):
                    return "local-product-image.png"

                def __exit__(self, exc_type, exc, tb):
                    return False

            return Context()

    fake_client = FakeAPIMart()
    original_client = prepare_module.APIMartClient
    original_storage = prepare_module.get_storage
    prepare_module.APIMartClient = lambda: fake_client
    prepare_module.get_storage = lambda: FakeStorage()
    try:
        filename = "048cfa0fe33135b550c94ed37223d04c.jpg"
        cluster = SimpleNamespace(
            name=filename,
            product_name="",
            store_name="xuecheng",
            product_facts="",
            identity_lock="",
            analysis_snapshot={},
            cluster_assets=[SimpleNamespace(asset=SimpleNamespace(kind="image", storage_path="assets/front.png"))],
            batch=SimpleNamespace(
                ai_recognition_enabled=True,
                output_template=SimpleNamespace(slots=[SimpleNamespace(order=1, name="Shopee high-CTR main poster", id="slot-1")]),
                global_prompt="",
            ),
        )
        _gpt55_single_node(None, cluster, "TH")
    finally:
        prepare_module.APIMartClient = original_client
        prepare_module.get_storage = original_storage

    assert "用户填写商品名称：(未填写，请结合商品参考图识别)" in fake_client.calls[0]["user"]
    assert fake_client.calls[0]["kwargs"]["image_sources"] == ["local-product-image.png"]


def test_gpt55_single_node_does_not_write_back_identity_when_ai_recognition_is_disabled() -> None:
    cluster = SimpleNamespace(
        product_name="用户填写商品名",
        product_facts="用户填写材质",
        identity_lock="",
        analysis_snapshot={},
        batch=SimpleNamespace(ai_recognition_enabled=False),
    )
    node = {
        "identity": {
            "product_name": "模型识别商品名",
            "category": "模型识别品类",
            "observed_identity": "模型识别补充信息",
            "reference_quality": 90,
        },
        "identity_lock": "保持参考图中的商品结构、颜色与部件。",
    }

    _merge_single_node_identity(cluster, node)

    assert cluster.product_name == "用户填写商品名"
    assert cluster.product_facts == "用户填写材质"
    assert cluster.identity_lock == "保持参考图中的商品结构、颜色与部件。"
    assert cluster.analysis_snapshot["identity"]["observed_identity"] == "模型识别补充信息"


def test_gpt55_single_node_does_not_block_short_prompts() -> None:
    class FakeAPIMart:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def complete_json(self, system: str, user: str, **kwargs):
            self.calls.append({"system": system, "user": user, "kwargs": kwargs})
            return {
                "json": {
                    "identity": {},
                    "identity_lock": "主商品保持参考图一致。",
                    "style_brief": "清晰电商信息图风格",
                    "prompts": [
                        {
                            "slot": 6,
                            "zh": "尺寸材质图。",
                            "final": "Size and material image.",
                            "target_language_copy": "ดูขนาด",
                        },
                        {
                            "slot": 7,
                            "zh": "使用步骤图。",
                            "final": "Usage steps image.",
                            "target_language_copy": "ใช้งานง่าย",
                        },
                    ],
                }
            }

    fake_client = FakeAPIMart()
    original_client = prepare_module.APIMartClient
    prepare_module.APIMartClient = lambda: fake_client
    try:
        slots = [
            SimpleNamespace(order=6, name="尺寸材质图", id="slot-6"),
            SimpleNamespace(order=7, name="使用步骤图", id="slot-7"),
        ]
        cluster = SimpleNamespace(
            name="展示盒",
            product_name="展示盒",
            store_name="",
            product_facts="",
            identity_lock="",
            analysis_snapshot={},
            cluster_assets=[],
            batch=SimpleNamespace(output_template=SimpleNamespace(slots=slots), global_prompt=""),
        )
        style_brief, prompts, _node = _gpt55_single_node(None, cluster, "TH")
    finally:
        prepare_module.APIMartClient = original_client

    assert style_brief == "清晰电商信息图风格"
    assert len(fake_client.calls) == 1
    assert prompts[6]["final"] == "Size and material image.\nVISIBLE TEXT:\nดูขนาด"
    assert prompts[7]["final"] == "Usage steps image.\nVISIBLE TEXT:\nใช้งานง่าย"


if __name__ == "__main__":
    main()
