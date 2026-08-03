"""冒烟测试：覆盖 CRUD 全流程 + 边界条件（回归用）。运行：PYTHONPATH=. python scripts/smoke_test.py"""


from datetime import datetime, timedelta
import uuid

from app.db import SessionLocal
from app.crud import users, templates, tasks, agent_logs
from app.models import TaskStatus, LogLevel

db = SessionLocal()
ok = 0


def check(name: str, cond: bool) -> None:
    global ok
    assert cond, f"FAIL: {name}"
    ok += 1
    print(f"  [PASS] {name}")


# 1) 匿名用户：创建 + 幂等
u1 = users.get_or_create_anonymous(db)
u2 = users.get_or_create_anonymous(db)
check("匿名用户 id=1", u1.id == 1 and u2.id == 1 and u1.credits_balance == 999)

# 2) DSN 特殊字符转义
from app.config import Settings

s = Settings(mysql_password="p@ss:w0rd/")
check("DSN 密码转义", "p%40ss%3Aw0rd%2F" in s.mysql_dsn)

# 3) 模板
tpl = templates.create_template(db, name="审查测试模板", description="d", config={"version": "1.0"})
check("模板创建", tpl.id is not None and templates.get_template(db, tpl.id) is not None)
templates.increment_usage_count(db, tpl.id)
check("模板计数", templates.get_template(db, tpl.id).usage_count == 1)
check("get_template(None) 返回 None", templates.get_template(db, None) is None)

# 4) 任务创建 + 默认 expires
tid = str(uuid.uuid4())
t = tasks.create_task(
    db, task_id=tid, prompt_text="p", input_file_name="a.docx",
    input_file_hash="h", input_file_path="minio://i/a.docx", template_id=tpl.id,
)
check("任务初始 pending", t.status == TaskStatus.PENDING and t.progress == 0)
check(
    "expires_at 默认 24h",
    timedelta(hours=23.9) < (t.expires_at - datetime.now()) < timedelta(hours=24.1),
)

# 5) 状态机流转
tasks.set_running(db, tid, TaskStatus.RETRIEVING, 15, "检索中")
tasks.set_running(db, tid, TaskStatus.PLANNING, 45, "规划中")
tasks.set_running(db, tid, TaskStatus.EXECUTING, 75, "执行中")
tasks.set_running(db, tid, TaskStatus.VALIDATING, 92, "校验中")
t = tasks.get_task(db, tid)
check("状态流转到 validating", t.status == TaskStatus.VALIDATING and t.progress == 92 and t.current_step == "校验中")

# 6) update_task 白名单：传非列字段（logs）应被忽略
tasks.update_task(db, tid, logs="hack", current_step="真实步骤")
t = tasks.get_task(db, tid)
check("白名单忽略非列字段", t.current_step == "真实步骤" and t.logs == [])

# 7) 重试态
tasks.set_running(db, tid, TaskStatus.RETRYING, 30, "重试第1次")
t = tasks.get_task(db, tid)
check("重试态", t.status == TaskStatus.RETRYING and t.progress == 30)

# 8) 成功收尾
tasks.mark_success(db, tid, output_file_path="minio://o/mod.docx", processing_time_ms=1000, llm_total_tokens=500, cost_usd=0.05)
t = tasks.get_task(db, tid)
check("成功收尾", t.status == TaskStatus.SUCCESS and t.progress == 100 and float(t.cost_usd) == 0.05 and t.completed_at is not None)

# 9) 日志
agent_logs.add_log(db, task_id=tid, agent_node="executor", message="执行完成", level=LogLevel.INFO)
agent_logs.add_log(db, task_id=tid, agent_node="validator", message="覆盖率不足", level=LogLevel.WARNING)
logs = agent_logs.list_logs(db, tid)
check("日志顺序（旧->新）", [l.log_message for l in logs] == ["执行完成", "覆盖率不足"])

# 10) 不存在任务边界
check("get_task 不存在->None", tasks.get_task(db, str(uuid.uuid4())) is None)
check("update_task 不存在->None", tasks.update_task(db, str(uuid.uuid4()), status=TaskStatus.FAILED) is None)

# 11) 失败态 + 过期查询
tid2 = str(uuid.uuid4())
tasks.create_task(
    db, task_id=tid2, prompt_text="p2", input_file_name="b.docx",
    input_file_hash="h2", input_file_path="minio://i/b.docx", expires_at=datetime.now() - timedelta(hours=1),
)
tasks.mark_failed(db, tid2)
check("失败态", tasks.get_task(db, tid2).status == TaskStatus.FAILED)
tid3 = str(uuid.uuid4())
tasks.create_task(
    db, task_id=tid3, prompt_text="p3", input_file_name="c.docx",
    input_file_hash="h3", input_file_path="minio://i/c.docx", expires_at=datetime.now() - timedelta(hours=1),
)
expired = [x.id for x in tasks.list_expired_tasks(db)]
check("过期清理只命中未终态任务", tid3 in expired and tid not in expired and tid2 not in expired)

# 12) 关系导航 + 级联
t = tasks.get_task(db, tid)
check("关系导航 template", t.template is not None and t.template.name == "审查测试模板")
check("关系导航 logs", len(t.logs) == 2)
check("关系导航 user", t.user is not None and t.user.id == 1)

# 清理（保留匿名用户）
for x in (tid, tid2, tid3):
    db.delete(tasks.get_task(db, x))
db.delete(tpl)
db.commit()
print(f"=== 综合审查测试全部通过（{ok} 组断言） ===")
db.close()
