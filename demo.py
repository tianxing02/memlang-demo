import os
import sys
import json
import re
import uuid
from datetime import datetime

from memos_client import MemOSClient
from llm_client import get_openai_client, get_openai_model
from prompts import SYSTEM_PROMPT_UNIFIED, build_unified_demo_prompt

def _parse_plan_update_json_from_content(content: str):
    try:
        tag_start = content.find('BEGIN_PLAN_UPDATE')
        tag_end = content.find('END_PLAN_UPDATE')
        if tag_start != -1 and tag_end != -1 and tag_end > tag_start:
            block = content[tag_start + len('BEGIN_PLAN_UPDATE'):tag_end]
            return json.loads(block.strip())
        tag_start_old = content.find('BEGIN_MEMORY_WRITE')
        tag_end_old = content.find('END_MEMORY_WRITE')
        if tag_start_old != -1 and tag_end_old != -1 and tag_end_old > tag_start_old:
            block = content[tag_start_old + len('BEGIN_MEMORY_WRITE'):tag_end_old]
            return json.loads(block.strip())
        start = content.rfind('{')
        end = content.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(content[start:end+1])
    except Exception:
        return None


def _extract_analysis_text(content: str) -> str:
    idx = content.find('BEGIN_PLAN_UPDATE')
    if idx == -1:
        idx = content.find('BEGIN_MEMORY_WRITE')
    return content[:idx] if idx != -1 else content


def _print_plan_update_json(plan_json: dict, title: str = None):
    if title:
        print(title)
    print("BEGIN_PLAN_UPDATE")
    print(json.dumps(plan_json, ensure_ascii=False, indent=2))
    print("END_PLAN_UPDATE")


def _print_conflict_check(plan_text: str, plan_json: dict):
    def _to_minutes(hm: str) -> int:
        try:
            h, m = hm.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return -1

    def _parse_plan_slots(text: str):
        slots = []
        pattern = re.compile(r"\*?\*?(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})\*?\*?\s*(?:[:：]\s*)?(.*)")
        for line in text.splitlines():
            m = pattern.search(line)
            if m:
                start_hm, end_hm, title = m.groups()
                start = _to_minutes(start_hm)
                end = _to_minutes(end_hm)
                if start != -1 and end != -1 and end > start:
                    slots.append({"start": start, "end": end, "title": title.strip()})
        return slots

    def _parse_commitments_today(pj: dict, today_date: str):
        commits = pj.get("commitments") or []
        out = []
        for cm in commits:
            tr = cm.get("time_range") or ""
            if today_date in tr and "T" in tr:
                try:
                    _, hm = tr.split("T", 1)
                    start_hm, end_hm = hm.split("-")
                    out.append({
                        "start": _to_minutes(start_hm),
                        "end": _to_minutes(end_hm),
                        "title": cm.get("title") or "承诺"
                    })
                except Exception:
                    pass
        return out

    def _overlaps(a, b) -> bool:
        return a["start"] < b["end"] and b["start"] < a["end"]

    today_date = datetime.now().strftime("%Y-%m-%d")
    plan_slots = _parse_plan_slots(plan_text)
    commits_today = _parse_commitments_today(plan_json, today_date)

    print("🧪 校验：时间重叠冲突检测（综合场景）")
    if not commits_today:
        print("- 未发现当日承诺或承诺未提供具体时段；跳过真实重叠检测。")
    elif not plan_slots:
        print("- 计划中未解析到时段；跳过真实重叠检测。")
    else:
        conflicts = []
        for slot in plan_slots:
            for cm in commits_today:
                if _overlaps(slot, cm):
                    conflicts.append((slot, cm))
        if not conflicts:
            print("- ✅ 未发现今日真实重叠冲突（计划时段与承诺时段无重叠）。")
        else:
            print(f"- ⚠️ 发现 {len(conflicts)} 个真实重叠冲突：")
            for (slot, cm) in conflicts:
                print(f"  · 计划『{slot['title']}』与承诺『{cm['title']}』重叠。建议前移或后移并保留缓冲。")


def _print_memory_references(memory_context_json: str):
    try:
        obj = json.loads(memory_context_json or "{}")
    except Exception:
        # 当传入的是逐行文本而非 JSON 时，直接输出逐行内容
        print("📚 参考记忆条目（逐行）：")
        if memory_context_json:
            print(memory_context_json)
        else:
            print("(空)")
        return

    def collect(key: str):
        results = []
        def rec(x):
            if isinstance(x, dict):
                if key in x and isinstance(x[key], list):
                    results.extend(x[key])
                for v in x.values():
                    rec(v)
            elif isinstance(x, list):
                for it in x:
                    rec(it)
        rec(obj)
        return results

    prefs = collect("preferences")
    commits = collect("commitments")
    constraints = collect("constraints")
    facts = collect("facts")
    tasks = collect("tasks")

    print("📚 参考记忆条目：")
    explicit = [p for p in prefs if (p.get("preference_type") or "").startswith("explicit")]
    implicit = [p for p in prefs if (p.get("preference_type") or "").startswith("implicit")]
    if explicit:
        print("- 显式偏好：")
        for p in explicit[:4]:
            print(f"  · {p.get('preference')}")
    if implicit:
        print("- 隐式偏好：")
        for p in implicit[:4]:
            print(f"  · {p.get('preference')}")

    if commits:
        print("- 当日/近期承诺：")
        for c in commits[:4]:
            tr = c.get("time_range") or ""
            title = c.get("title") or "承诺"
            if tr:
                print(f"  · {title}（时间：{tr}）")
            else:
                print(f"  · {title}")


def _format_mem_ctx_lines(mem_result: dict) -> str:
    container = mem_result if isinstance(mem_result, dict) else {}
    data = container.get("data") if isinstance(container.get("data"), dict) else container
    lines = []

    def emit_list(name: str):
        items = data.get(name)
        if isinstance(items, list):
            lines.append(f"{name}:")
            for it in items:
                if isinstance(it, (dict, list)):
                    lines.append(json.dumps(it, ensure_ascii=False))
                else:
                    lines.append(str(it))
            lines.append("")

    emit_list("memory_detail_list")
    emit_list("preference_detail_list")
    return "\n".join(lines).strip()


def seed_unified_scenario(memos: MemOSClient):
    seed_msgs = [
        {"role": "user", "content": "目标：每天学习 2 小时，准备政治和英语。"},
        {"role": "user", "content": "工作日可能加班，晚间开始学习易疲劳，但一开始更偏好晚上学习。"},
        {"role": "user", "content": json.dumps({
            "commitments": [
                {"title": "晨会", "status": "activated", "time_range": f"{datetime.now().strftime('%Y-%m-%d')}T09:30-10:00"},
                {"title": "午间客户电话", "status": "activated", "time_range": f"{datetime.now().strftime('%Y-%m-%d')}T12:00-12:30"},
                {"title": "晚间家庭聚餐", "status": "activated", "time_range": f"{datetime.now().strftime('%Y-%m-%d')}T20:30-21:30"}
            ]
        }, ensure_ascii=False)},
        {"role": "user", "content": "团队例会每周三 10:00-11:00。客户季度汇报本周五 14:00-16:00。"},
        {"role": "user", "content": "合规培训需本周内完成（强制性约束）。周四 15:00 牙医；健身偏好 07:00。"},
        {"role": "user", "content": "待办：项目代码评审、准备客户汇报 PPT、撰写本周工作周报。"},
    ]
    memos.add_conversation(seed_msgs)

    fail_log = {"user_pattern": {"active_hours": "20:00-22:00", "actual_execution_rate": "45%"}, "failure_cause": "加班后开始学习易疲劳，执行率下降"}
    memos.add_conversation([{"role": "user", "content": json.dumps(fail_log, ensure_ascii=False)}])
    print("✅ 场景种子写入完成\n")


def run():
    memos = MemOSClient()
    client = get_openai_client()
    model = get_openai_model()
    # 仅按 user_id 隔离，不再使用 conversation_id

    print("🚀 统一综合示例")
    print("👤 user_id：", memos.user_id)

    seed_unified_scenario(memos)

    # 初始化记忆上下文占位；实际检索在每轮依据用户 query 进行
    mem_ctx = ""

    goal_text = "每天学习 2 小时，准备政治和英语"
    history_messages = []

    print("goal_text: ", goal_text)
    def run_round(round_title: str, extra_instruction: str):
        nonlocal mem_ctx
        print(f"\n🔁 {round_title}")
        # 使用用户当轮的 query 进行记忆检索，并将记忆按“每元素一行”格式化
        mem_obj_round_q = memos.search_memory(extra_instruction)
        mem_ctx = _format_mem_ctx_lines(mem_obj_round_q)
        user_prompt = build_unified_demo_prompt(goal_text, mem_ctx)
        # _print_memory_references(mem_ctx)
        print("🗣️ 用户指令：", extra_instruction)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_UNIFIED},
            *history_messages,
            {"role": "user", "content": user_prompt},
            {"role": "user", "content": extra_instruction},
        ]
        response = client.chat.completions.create(model=model, messages=messages)
        content = response.choices[0].message.content
        print("🤖 系统输出：\n" + content)
        analysis = _extract_analysis_text(content)

        plan_json = _parse_plan_update_json_from_content(content)
        # if plan_json is None:
        #     print("⚠️ 本轮未解析到计划更新 JSON。")
        # else:
        #     _print_plan_update_json(plan_json, title="🔧 计划更新 JSON（解析渲染）")

        pj = plan_json or {}
        _print_conflict_check(analysis, pj)

        write_messages = [
            {"role": "user", "content": user_prompt},
            {"role": "user", "content": extra_instruction},
            {"role": "assistant", "content": content},
        ]
        if plan_json is not None:
            write_messages.append({"role": "assistant", "content": json.dumps({"PlanUpdate": plan_json}, ensure_ascii=False)})
        memos.add_conversation(write_messages)

        history_messages.extend(write_messages)
        # 再次基于用户 query 检索最新记忆摘要，便于下一轮使用（按行格式化）
        mem_obj_round = memos.search_memory(extra_instruction)
        mem_ctx = _format_mem_ctx_lines(mem_obj_round)

    run_round(
        "第 1 轮：基础规划并避冲突",
        (
            "避免与晨会(09:30-10:00)、午间客户电话(12:00-12:30)、家庭聚餐(20:30-21:30)冲突。"
            "晚间学习效率低，优先早晨/午间轻任务；周末集中英语 3h。若有承接任务请注明理由与来源。"
        ),
    )

    run_round(
        "第 2 轮：复杂变更与偏好裁决",
        (
            "本周三(07:00-22:00)出差不可用；周四牙医 15:00；合规培训本周必须完成；健身改到 19:00。"
            "若周五客户汇报临时改档至 11:00-12:00，请整体调整；政治与英语冲突时优先英语，并说明裁决。"
        ),
    )

    run_round(
        "第 3 轮：复盘承接与偏好更新",
        (
            "根据前两轮执行，将低完成率任务 rollover；识别周末最高效学习时段并记为隐式偏好(如 Saturday 9:00-12:00)。"
            "若家庭活动提前到 18:30-20:00，请适配；给出改进策略，但仍仅输出一个更新 JSON。"
        ),
    )

    run_round(
        "第 4 轮：别名混淆与互斥偏好裁决",
        (
            "‘客户汇报’又称‘季度回顾会’，保持周五改档；新增家长会 18:00-19:00。"
            "将健身从 19:00 改回 07:00，但早晨深度工作偏好需保留；如冲突，以承诺优先并解释裁决。"
        ),
    )

    run_round(
        "第 5 轮：跨周承接与去重",
        (
            "下周保留周三团队例会(10:00-11:00)与季度回顾会；若出现重复或重叠会议请去重与改期。"
            "政治与英语安排需分时段交替，优先在午间安排政治，晚间避免高强度任务。"
        ),
    )


def main():
    run()


if __name__ == "__main__":
    main()