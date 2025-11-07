import os
import sys
import json
import re
from datetime import datetime

from memos_client import MemOSClient
from llm_client import get_openai_client, get_openai_model
from prompts import SYSTEM_PROMPT_UNIFIED, build_unified_demo_prompt


# ----------------------------
# 工具函数
# ----------------------------

def _parse_plan_update_json_from_content(content: str):
    """从模型输出中提取 BEGIN_PLAN_UPDATE 到 END_PLAN_UPDATE 之间的 JSON"""
    try:
        tag_start = content.find('BEGIN_PLAN_UPDATE')
        tag_end = content.find('END_PLAN_UPDATE')
        if tag_start != -1 and tag_end != -1 and tag_end > tag_start:
            block = content[tag_start + len('BEGIN_PLAN_UPDATE'):tag_end]
            return json.loads(block.strip())
        start = content.rfind('{')
        end = content.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(content[start:end + 1])
    except Exception:
        return None


def _extract_analysis_text(content: str) -> str:
    """提取自由文本部分，用于正则分析"""
    idx = content.find('BEGIN_PLAN_UPDATE')
    return content[:idx] if idx != -1 else content


def _print_conflict_check(plan_text: str, plan_json: dict):
    """检测时间冲突"""
    def _to_minutes(hm: str) -> int:
        try:
            h, m = hm.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return -1

    def _parse_slots(text: str):
        pattern = re.compile(r"(\d{2}:\d{2})\s*[-–—]\s*(\d{2}:\d{2}).*")
        slots = []
        for line in text.splitlines():
            m = pattern.search(line)
            if m:
                start, end = m.groups()
                slots.append({
                    "start": _to_minutes(start),
                    "end": _to_minutes(end),
                    "title": line[m.end():].strip() or "未命名任务"
                })
        return slots

    def _parse_commitments(pj: dict):
        out = []
        for cm in pj.get("commitments", []):
            tr = cm.get("time_range", "")
            if "T" in tr:
                try:
                    _, hm = tr.split("T", 1)
                    start, end = hm.split("-")
                    out.append({
                        "start": _to_minutes(start),
                        "end": _to_minutes(end),
                        "title": cm.get("title") or "固定安排"
                    })
                except Exception:
                    pass
        return out

    plan_slots = _parse_slots(plan_text)
    commitments = _parse_commitments(plan_json)
    print("🧪 校验：时间冲突检测")
    if not plan_slots or not commitments:
        print("ℹ️ 无完整时段信息，跳过检测。")
        return

    def overlaps(a, b):
        return a["start"] < b["end"] and b["start"] < a["end"]

    conflicts = []
    for s in plan_slots:
        for c in commitments:
            if overlaps(s, c):
                conflicts.append((s, c))

    if conflicts:
        print(f"⚠️ 检测到 {len(conflicts)} 个冲突：")
        for s, c in conflicts:
            print(f"  ·『{s['title']}』与固定安排『{c['title']}』重叠。")
    else:
        print("✅ 未发现时间重叠，一切安排合理。")


def _extract_tasks_from_text(text: str):
    """回退：从自由文本中抽取时段和持续时间"""
    tasks = []
    pattern = re.compile(r"(\d{2}:\d{2})\s*[-–—]\s*(\d{2}:\d{2})\s*[:：]?\s*(.*)")
    for line in text.splitlines():
        m = pattern.search(line)
        if m:
            start, end, title = m.groups()
            title = title.strip() or "未命名任务"
            # 计算持续时间
            sh, sm = map(int, start.split(":"))
            eh, em = map(int, end.split(":"))
            duration = (eh * 60 + em) - (sh * 60 + sm)
            tasks.append({
                "time": f"{start}-{end}",
                "activity": title,
                "duration": f"{duration} 分钟",
                "priority": "中"
            })
    return tasks


# ----------------------------
# 初始化用户先验记忆
# ----------------------------

def seed_unified_scenario(memos: MemOSClient):
    """初始化用户长期记忆（纯自然语言形式，系统自动抽取结构化信息）"""
    seed_msgs = [
        # 🎯 长期目标
        {"role": "user", "content": "我的长期目标是每天学习2小时，准备政治和英语。"},

        # 💡 明确偏好
        {"role": "user", "content": "我更喜欢早上学习政治，周末集中学习英语。"},
        {"role": "user", "content": "晚上学习效率较低，适合做复盘或轻松阅读。"},
        {"role": "user", "content": "健身时间偏好早上7点，习惯晨练后开始一天的学习。"},

        # 📆 固定会议与承诺
        {"role": "user", "content": f"每个工作日早上9:30到10:00有晨会。"},
        {"role": "user", "content": f"每天12:00到12:30有客户电话沟通。"},
        {"role": "user", "content": f"晚上20:00到21:00一般是家庭聚餐时间，不安排学习。"},
        {"role": "user", "content": f"每周三10:00到11:00有团队例会。"},
        {"role": "user", "content": f"每周五14:00到16:00要参加季度汇报。"},
        {"role": "user", "content": f"周四15:00到15:30要去看牙医。"},

        # 📋 约束任务
        {"role": "user", "content": "本周必须完成一次合规培训任务，请在合适时间安排。"},

        # 🧠 待办事项
        {"role": "user", "content": "我的待办任务包括：项目代码评审、准备客户汇报PPT、撰写本周工作周报。"},
    ]
    print("🧠 初始用户记忆：")
    for msg in seed_msgs:
        print(msg)
    memos.add_conversation(seed_msgs)
    print("✅ 已写入长期记忆（自然语言形式）：包含目标、偏好、会议与任务。\n")


# ----------------------------
# 主执行逻辑
# ----------------------------

def run():
    memos = MemOSClient()
    client = get_openai_client()
    model = get_openai_model()

    print("🚀 启动一周日程规划模拟")
    print(f"👤 user_id: {memos.user_id}")
    seed_unified_scenario(memos)

    goal_text = "每天学习2小时，准备政治和英语"
    history_messages, mem_ctx = [], ""

    # 一周输入模拟（含具体上下文）
    weekdays = [
        (
            "周一",
            "📅 今天是周一。\n"
            "状态一般，可能需要一点时间进入学习节奏。早上还是老习惯，晨练后做点轻学习就好。"
            "政治那本笔记有些地方想复查，但不一定非今天。"
            "这周打算重新整理一下英语听力素材，估计周三前能开始试试。"
        ),
        (
            "周二",
            "📅 今天是周二。\n"
            "昨晚睡得晚，上午注意力可能分散一点。"
            "汇报资料进度不错，不过细节部分还没打磨完，可能得提前留时间。"
            "最近发现午饭后容易犯困，也许适合做点轻内容。"
            "周四的那件事要记得，不想那天太赶。"
        ),
        (
            "周三",
            "📅 今天是周三。\n"
            "早上健身完感觉状态比昨天好很多，应该能处理一些需要专注的内容。"
            "昨天提到的汇报细节今天可以推进一部分。"
            "另外，那份英语材料好像也可以开始动手听一听。"
            "晚上别太紧凑，想留出一点时间看看新闻。"
        ),
        (
            "周四",
            "📅 今天是周四。\n"
            "下午的事别忘了，可能要提前一点出门。"
            "上午比较清闲，可以处理一些平时没空做的事情。"
            "昨天的复盘笔记还没补完，有时间可以接着写。"
            "听力那部分感觉还得多练几次，也许午饭后试试看。"
        ),
        (
            "周五",
            "📅 今天是周五。\n"
            "今天比较关键，那份汇报终于到了。"
            "早上尽量保持轻松的节奏，别太压自己。"
            "如果这周有没收尾的事，别忘了留点时间整理。"
            "周末可能会想多练英语，到时候再看看整体安排。"
        )
    ]




    def run_day(day_name: str, user_instruction: str):
        nonlocal mem_ctx
        print(f"\n📅 {day_name} 日程规划中...")
        mem_obj = memos.search_memory(user_instruction)
        # mem_ctx = json.dumps(mem_obj, ensure_ascii=False)
        print("👤 用户指令：", user_instruction)
        mem_ctx = ""
        count = 1
        for detail in mem_obj["data"]["memory_detail_list"]:
            if detail["memory_value"].strip():
                mem_ctx += str(count) + ": " + detail["memory_value"].replace("\n", "")[:300] + "\n"
                count += 1

        print("🧠 记忆上下文：\n", mem_ctx)
        user_prompt = build_unified_demo_prompt(goal_text, mem_ctx)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_UNIFIED},
            *history_messages,
            {"role": "user", "content": user_prompt},
            {"role": "user", "content": user_instruction},
        ]
        response = client.chat.completions.create(model=model, messages=messages)
        content = response.choices[0].message.content

        # print("\n🤖 系统输出：")
        # print(content)

        plan_json = _parse_plan_update_json_from_content(content) or {}
        pj = plan_json or {}
        analysis = _extract_analysis_text(content)

        _print_conflict_check(analysis, pj)

        write_messages = [
            {"role": "user", "content": user_instruction},
            {"role": "assistant", "content": content},
        ]
        memos.add_conversation(write_messages)
        history_messages.extend(write_messages)

        print("\n📘 今日计划简表：")

        tasks = []

        # --- 新版 JSON 结构解析 ---
        try:
            if isinstance(plan_json, dict):
                # 优先匹配标准格式 {"today": {"tasks": [...]}}
                if "today" in plan_json and isinstance(plan_json["today"], dict):
                    tasks = plan_json["today"].get("tasks", [])
                # 兼容 fallback 格式 {"tasks": [...]}
                elif "tasks" in plan_json and isinstance(plan_json["tasks"], list):
                    tasks = plan_json["tasks"]
                # 兼容异常格式 {"schedule": [...]}
                elif "schedule" in plan_json and isinstance(plan_json["schedule"], list):
                    tasks = plan_json["schedule"]
        except Exception as e:
            print(f"⚠️ 解析 JSON 出错：{e}")

        # --- 打印输出 ---
        if tasks:
            for t in tasks:
                time = t.get("time", "未指定时间")
                activity = t.get("activity", t.get("title", "未命名任务"))
                priority = t.get("priority", "中")
                source = t.get("source", "")
                print(f"  ⏰ {time:<15} | {activity:<20} | 优先级：{priority:<2} | 来源：{source}")
        else:
            print("⚠️ 未检测到任务时间安排，请检查模型输出。")

    # 循环一周
    for day, instruction in weekdays:
        run_day(day, instruction)


def main():
    run()


if __name__ == "__main__":
    main()
