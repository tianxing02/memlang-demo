import json

# 统一综合场景（学习 + 办公）System Prompt
SYSTEM_PROMPT_UNIFIED = (
    "你是一名具备记忆驱动能力的综合规划助手。"
    "需要同时考虑个人学习目标与办公承诺/约束，遵循：承诺优先，避免时间冲突，偏好与效率兼顾。"
    "先输出中文分析（承接/冲突化解/今日计划/引用与裁决），随后仅输出一个被 BEGIN_PLAN_UPDATE/END_PLAN_UPDATE 包裹的 JSON 更新指令。"
)

def build_unified_demo_prompt(goal_text: str, memory_context_json: str) -> str:
    """综合场景 Prompt：将学习目标与办公场景统一为一步式提示。

    - A. 承接：识别未完成事项（学习/办公）并承接；
    - B. 冲突化解：当日承诺优先，避免重叠；给出调整依据与替代时段；
    - C. 今日可执行计划：列出时间段（24h）、任务/学科、优先级与简短理由；
    - D. 引用与裁决：标注引用的记忆来源（偏好/承诺/失败记录等），解释“承诺>显式偏好>隐式偏好>事实”；
    - E. 计划更新指令：仅输出一次合法 JSON，用 BEGIN_PLAN_UPDATE/END_PLAN_UPDATE 包裹。
    """
    lines = [
        f"学习目标：{goal_text}",
        "请按以下步骤进行综合规划并输出结果：",
        "步骤A. 承接未完成事项（学习/办公）；",
        "步骤B. 检查当日承诺冲突并化解，给出调整与裁决依据；",
        "步骤C. 生成今日可执行计划（含具体时段与优先级）；",
        "步骤D. 为每项标注引用的记忆来源与裁决规则（承诺>显式偏好>隐式偏好>事实）；",
        "步骤E. 输出计划更新指令（JSON）。",
        "输出要求：先中文分析与计划；然后仅输出一个纯 JSON，使用如下标记：",
        "BEGIN_PLAN_UPDATE",
        "{...合法的计划更新 JSON...}",
        "END_PLAN_UPDATE",
        "",
        "🧠 记忆上下文：",
        memory_context_json or "",
    ]
    return "\n".join(lines)