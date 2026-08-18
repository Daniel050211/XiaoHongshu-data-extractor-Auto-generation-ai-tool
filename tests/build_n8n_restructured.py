"""完整重構：把 n8n 工作流拆成 3 個子工作流（不覆蓋原檔）。"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from copy import deepcopy
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

ORIG = json.loads(Path("data/n8n_workflow.json").read_text(encoding="utf-8"))
MOD = json.loads(Path("data/n8n_workflow_modified.json").read_text(encoding="utf-8"))
OUT_DIR = Path("data/restructured")
OUT_DIR.mkdir(exist_ok=True)


def nid() -> str:
    return uuid.uuid4().hex[:24]


def by_name(wf: dict, name: str) -> dict:
    for n in wf["nodes"]:
        if n.get("name") == name:
            return n
    raise KeyError(name)


def copy_node(wf: dict, name: str, rename: str | None = None) -> dict:
    n = deepcopy(by_name(wf, name))
    n["id"] = nid()
    if rename:
        n["name"] = rename
    return n


def code_node(name: str, code: str, pos=None) -> dict:
    return {"parameters": {"jsCode": code}, "id": nid(), "name": name,
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": pos or [0, 0]}


def sticky(name: str, content: str, pos=None) -> dict:
    return {"parameters": {"content": content, "height": 300, "width": 400, "color": 4},
            "id": nid(), "name": name, "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1, "position": pos or [0, 0]}


def if_node(wf: dict, name: str, left: str, right: str) -> dict:
    """以 Scraper Done? 為模板建立 IF 節點。"""
    base = deepcopy(by_name(wf, "Scraper Done?"))
    base["id"] = nid()
    base["name"] = name
    cond = base["parameters"]["conditions"]["conditions"][0]
    cond["id"] = nid()
    cond["leftValue"] = left
    cond["rightValue"] = right
    return base


def workflow(name: str, nodes: list[dict], connections: dict) -> dict:
    return {
        "name": name,
        "nodes": nodes,
        "pinData": {},
        "connections": connections,
        "active": False,
        "settings": {"executionOrder": "v1"},
        "versionId": str(uuid.uuid4()),
        "meta": {},
        "id": str(uuid.uuid4()),
        "tags": [],
    }


def save(wf: dict, filename: str):
    path = OUT_DIR / filename
    path.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def validate(wf: dict, label: str):
    names = {n["name"] for n in wf["nodes"]}
    assert len(names) == len(wf["nodes"]), f"{label}: 節點名稱重複"
    for src, targets in wf.get("connections", {}).items():
        assert src in names, f"{label}: 連線來源不存在 {src}"
        for ctype, arr in targets.items():
            for conn in arr:
                for t in conn:
                    assert t.get("node") in names, f"{label}: 連線目標不存在 {t.get('node')}"
    print(f"OK {label}: {len(wf['nodes'])} 節點, 連線完整")


def js_check(nodes: list[dict], label: str):
    node_bin = Path(r"C:\Users\DanielHau\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
    check_dir = OUT_DIR / "js_check"
    check_dir.mkdir(exist_ok=True)
    for n in nodes:
        if n.get("type") == "n8n-nodes-base.code":
            tmp = check_dir / f"{label}_{n['name'].replace(' ', '_')}.js"
            tmp.write_text(n["parameters"]["jsCode"], encoding="utf-8")
            r = subprocess.run([str(node_bin), "--check", str(tmp)], capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f"{label} JS 語法錯誤 [{n['name']}]: {r.stderr.strip()[:300]}")
    print(f"OK {label}: 全部 code 節點語法檢查通過")


# =====================================================================
# WF1 數據分析
# =====================================================================
WF1_NODES = []
WF1_CONN = {}

schedule1 = copy_node(MOD, "Schedule Trigger1")
get_urls = copy_node(MOD, "Get Post URLs")
extract_urls = copy_node(MOD, "Code in JavaScript")
read_raw = copy_node(MOD, "Read Existing Claims for Prompt", rename="Read RawData")
read_raw["parameters"]["sheetName"] = {
    "__rl": True,
    "value": 222603192,
    "mode": "list",
    "cachedResultName": "RawData",
    "cachedResultUrl": "https://docs.google.com/spreadsheets/d/1S1wEubVTlxNklgQT4ncz76D8g_zU9h1X_vXWsZvcRRU/edit#gid=222603192",
}

FILTER_LINKS_CODE = r"""const rawRows = $input.all().map(i => i.json);
const urlsNode = $('Code in JavaScript');
const urls = Array.isArray(urlsNode.first().json.URLs) ? urlsNode.first().json.URLs : [];

function idFromUrl(u) {
  const m = String(u || '').match(/\/(?:explore|item|note)\/([0-9a-fA-F]{24})/);
  return m ? m[1] : null;
}

// 統計每個 post_id 在 RawData 出現次數（已抓 ≥2 次 = 完整，不再抓）
const countByPostId = {};
rawRows.forEach(r => {
  const pid = r.post_id || idFromUrl(r.permalink) || idFromUrl(r.postUrl) || '';
  if (pid) countByPostId[pid] = (countByPostId[pid] || 0) + 1;
});

const toScrape = urls.filter(u => {
  const pid = idFromUrl(u);
  return !pid || (countByPostId[pid] || 0) < 2;
});

return [{
  json: {
    URLs: toScrape,
    skipped_count: urls.length - toScrape.length,
    total_count: urls.length
  }
}];
"""
filter_links = code_node("Filter Complete Links", FILTER_LINKS_CODE)

start_actor = copy_node(MOD, "Start Actor")
check_status = copy_node(MOD, "Check Run Status")
if_done = if_node(MOD, "IF 抓取完成?", "={{ $json.data.status }}", "SUCCEEDED")
if_failed = if_node(MOD, "IF 抓取失敗?", "={{ $json.data.status }}", "FAILED")
wait = copy_node(MOD, "Wait")
fetch = copy_node(MOD, "Fetch Dataset")
transform = copy_node(MOD, "Transform & Label")
append_raw = copy_node(MOD, "Append row in sheet1")
prepare = copy_node(MOD, "Prepare for AI analysis")
read_claims = copy_node(MOD, "Read Existing Claims for Prompt")
attach = copy_node(MOD, "Attach Existing Claims")
ai_analysis = copy_node(MOD, "AI Analysis")
model_analysis = copy_node(MOD, "OpenRouter Chat Model Analysis2")
extract = copy_node(MOD, "Extract analysis result")
feedback_gen = copy_node(MOD, "Feedback generation")
read_hypo = copy_node(MOD, "Read Strategy Hypotheses")
match_claims = copy_node(MOD, "Match & Update Claims")
filter_claims = copy_node(MOD, "Filter Claims for Upsert")
upsert_hypo = copy_node(MOD, "Upsert Strategy Hypotheses")
collapse = copy_node(MOD, "Collapse Claims for Memory")
read_memory = copy_node(MOD, "Read Continuous Memory")
prep_memory = copy_node(MOD, "Prepare Memory Agent Input1")
ai_memory = copy_node(MOD, "AI current memory")
model_memory = copy_node(MOD, "OpenRouter Chat Model Analysis4")
format_memory = copy_node(MOD, "Format Memory Row1")
update_memory = copy_node(MOD, "update continuous memory")

send_fail = copy_node(MOD, "Send a message", rename="Send 抓取失敗通知")
send_fail["parameters"] = {
    "toRecipients": "jenniferyu@k11byac.com",
    "subject": "XHS 抓取失敗通知",
    "bodyContent": "={{ 'XHS 抓取失敗，請檢查 Apify run：' + ($json.data.id || '') + ' 狀態: ' + ($json.data.status || '') }}",
    "additionalFields": {},
}

WF1_NODES = [
    schedule1, get_urls, extract_urls, read_raw, filter_links, start_actor,
    check_status, if_done, if_failed, wait, fetch, transform, append_raw,
    prepare, read_claims, attach, ai_analysis, model_analysis, extract,
    feedback_gen, read_hypo, match_claims, filter_claims, upsert_hypo,
    collapse, read_memory, prep_memory, ai_memory, model_memory,
    format_memory, update_memory, send_fail,
    sticky("說明", "WF1 數據分析（09:00）\n抓取 → 標籤(週次/初步完整) → AI 分析(GLM-5.2) → 執行摘要 → 回饋/記憶。\n"
                   "● 週次起點：2026-07-01（Transform & Label）\n"
                   "● 已抓 ≥2 次的連結會自動跳過（省 Apify 費用）\n"
                   "● 抓取失敗會寄信通知，不會無限迴圈\n"
                   "● 安全建議：Apify token 目前寫在 Start Actor / Check Run Status 的 URL，建議改到 HTTP Request Credentials"),
]

def conn(src, targets):
    WF1_CONN[src] = {"main": [[{"node": t, "type": "main", "index": 0}] for t in targets]}

conn(schedule1["name"], [get_urls["name"]])
conn(get_urls["name"], [extract_urls["name"]])
conn(extract_urls["name"], [read_raw["name"]])
conn(read_raw["name"], [filter_links["name"]])
conn(filter_links["name"], [start_actor["name"]])
conn(start_actor["name"], [check_status["name"]])
conn(check_status["name"], [if_done["name"]])
WF1_CONN[if_done["name"]] = {"main": [
    [{"node": fetch["name"], "type": "main", "index": 0}],   # true → 完成
    [{"node": if_failed["name"], "type": "main", "index": 0}],  # false → 檢查是否失敗
]}
WF1_CONN[if_failed["name"]] = {"main": [
    [{"node": send_fail["name"], "type": "main", "index": 0}],  # true → 失敗通知
    [{"node": wait["name"], "type": "main", "index": 0}],       # false → 重試
]}
conn(wait["name"], [check_status["name"]])
conn(fetch["name"], [transform["name"]])
conn(transform["name"], [append_raw["name"]])
conn(append_raw["name"], [prepare["name"]])
conn(prepare["name"], [read_claims["name"]])
conn(read_claims["name"], [attach["name"]])
conn(attach["name"], [ai_analysis["name"]])
WF1_CONN[model_analysis["name"]] = {"ai_languageModel": [[{"node": ai_analysis["name"], "type": "ai_languageModel", "index": 0}]]}
conn(ai_analysis["name"], [extract["name"]])
conn(extract["name"], [feedback_gen["name"]])
conn(feedback_gen["name"], [read_hypo["name"]])
conn(read_hypo["name"], [match_claims["name"]])
WF1_CONN[match_claims["name"]] = {"main": [
    [{"node": filter_claims["name"], "type": "main", "index": 0}],
    [{"node": collapse["name"], "type": "main", "index": 0}],
]}
conn(filter_claims["name"], [upsert_hypo["name"]])
conn(collapse["name"], [read_memory["name"]])
conn(read_memory["name"], [prep_memory["name"]])
conn(prep_memory["name"], [ai_memory["name"]])
WF1_CONN[model_memory["name"]] = {"ai_languageModel": [[{"node": ai_memory["name"], "type": "ai_languageModel", "index": 0}]]}
conn(ai_memory["name"], [format_memory["name"]])
conn(format_memory["name"], [update_memory["name"]])

WF1 = workflow("佛山_WF1_数据分析", WF1_NODES, WF1_CONN)
validate(WF1, "WF1")
js_check([n for n in WF1_NODES if n["name"] in ("Filter Complete Links",)], "WF1-new")


# =====================================================================
# WF3 人工審核（先做，WF2 需要它的 ID）
# =====================================================================
manual = {
    "parameters": {},
    "id": nid(),
    "name": "Manual Trigger",
    "type": "n8n-nodes-base.manualTrigger",
    "typeVersion": 1,
    "position": [0, 0],
}

RETURN_DECISION_CODE = r"""const resp = $input.first().json;
const data = resp.data || resp;
const decision = data.decision ?? data["选择分析方向"] ?? data["审核决定"] ?? "";
const comment = data["修改意见（拒绝时填写）"] || data.comment || "";
return [{
  json: {
    data: {
      decision,
      "选择分析方向": decision,
      "审核决定": decision,
      "修改意见（拒绝时填写）": comment
    },
    decision,
    comment
  }
}];
"""
return_decision = code_node("Return Decision", RETURN_DECISION_CODE)

approval_outlook = {
    "parameters": {
        "operation": "sendAndWait",
        "toRecipients": "={{ $json.toRecipients }}",
        "subject": "={{ $json.subject }}",
        "message": "={{ $json.message }}",
        "responseType": "customForm",
        "defineForm": "json",
        "jsonOutput": "={{ $json.formJson }}",
        "options": {},
    },
    "id": nid(),
    "name": "Send 審核郵件 (等待回覆)",
    "type": "n8n-nodes-base.microsoftOutlook",
    "typeVersion": 2,
    "position": [0, 0],
    "credentials": {"microsoftOutlookOAuth2Api": {"id": "ANNgjFo28zJsUkO2", "name": "Microsoft Outlook account"}},
}

WF3_NODES = [
    manual,
    approval_outlook,
    return_decision,
    sticky("說明", "WF3 人工審核（子工作流，由 WF2 呼叫）\n"
                   "輸入：{ toRecipients, subject, message, formJson }\n"
                   "輸出：{ data: { 选择分析方向 / 审核决定 / 修改意见（拒绝时填写） }, decision, comment }"),
]
WF3_CONN = {
    manual["name"]: {"main": [[{"node": approval_outlook["name"], "type": "main", "index": 0}]]},
    approval_outlook["name"]: {"main": [[{"node": return_decision["name"], "type": "main", "index": 0}]]},
}
WF3 = workflow("佛山_WF3_人工审核", WF3_NODES, WF3_CONN)
validate(WF3, "WF3")
js_check([return_decision], "WF3")


# =====================================================================
# WF2 內容生成
# =====================================================================
WF2_NODES = []
WF2_CONN = {}

schedule2 = copy_node(ORIG, "Schedule Trigger")
serper = copy_node(ORIG, "HTTP Request1")
merge = copy_node(ORIG, "Merge Articles")
append_articles = copy_node(ORIG, "Append row in sheet")
prep_articles = copy_node(ORIG, "Prepare Articles for AI")
first_input = copy_node(ORIG, "First AI Input")
select_agent = copy_node(ORIG, "Select Articles Agent")
model_select = copy_node(ORIG, "OpenRouter Chat Model")
parse_response = copy_node(ORIG, "Parse AI Response")
format_email = copy_node(ORIG, "Format Email Message")

PREP_APPROVAL1_CODE = r"""const email = $('Format Email Message').first().json;
const formJson = JSON.stringify([
  { fieldName: "decision", fieldLabel: "选择分析方向", fieldType: "dropdown", requiredField: true,
    fieldOptions: { values: [{ option: "方向1" }, { option: "方向2" }, { option: "方向3" }, { option: "❌ 拒绝全部" }] } },
  { fieldName: "comment", fieldLabel: "修改意见（拒绝时填写）", fieldType: "textarea", requiredField: false }
]);
return [{ json: {
  toRecipients: "jenniferyu@k11byac.com",
  subject: "AI分析方向选择 - " + new Date().toISOString().slice(0, 10),
  message: (email.emailBody || "") + "<p><strong>请选择要生成的分析方向（可多选）:</strong></p>",
  formJson
} }];
"""
prep_approval1 = code_node("Prepare Approval1 Input", PREP_APPROVAL1_CODE)

exec_approval1 = {
    "parameters": {
        "workflowId": {"__rl": True, "value": "REPLACE_WITH_WF3_ID", "mode": "list", "cachedResultName": "佛山_WF3_人工审核"},
        "options": {"passInputData": True},
    },
    "id": nid(),
    "name": "Execute WF3 審核1",
    "type": "n8n-nodes-base.executeWorkflow",
    "typeVersion": 1.2,
    "position": [0, 0],
}

switch1 = copy_node(ORIG, "Switch1")
extract_dir_ok = copy_node(ORIG, "Extract Select Directions approve case")
extract_dir_retry = copy_node(ORIG, "Extract Select Directions approve case1")
gen_full = copy_node(ORIG, "Generate Full Analysis Agent")
model_full = copy_node(ORIG, "OpenRouter Chat Model Analysis")
save_analysis = copy_node(ORIG, "Save Analysis to Sheet")
read_latest_analysis = copy_node(ORIG, "Read Latest Analysis")
read_memory1 = copy_node(ORIG, "Read Current Memory1")
read_feedback = copy_node(ORIG, "Read Latest Feedback1")
prep_third = copy_node(MOD, "Prepare Third AI Input")
gen_script = copy_node(ORIG, "Generate Social Script")
model_script = copy_node(ORIG, "OpenRouter Chat Model Analysis1")
save_analysis1 = copy_node(ORIG, "Save Analysis to Sheet1")
parse_scripts = copy_node(ORIG, "Parse Scripts")
format_script_email = copy_node(ORIG, "Format Script Email")
split_versions = copy_node(ORIG, "Split Versions")

PREP_APPROVAL2_CODE = r"""const script = $('Format Script Email').first().json;
const formJson = JSON.stringify([
  { fieldLabel: "审核决定", fieldType: "dropdown", requiredField: true,
    fieldOptions: { values: [{ option: "✅ 批准：反差型" }, { option: "✅ 批准：数据型" }, { option: "✅ 批准：判断型" }, { option: "❌ 拒绝全部" }] } },
  { fieldLabel: "修改意见（拒绝时填写）", fieldType: "textarea", requiredField: false }
]);
return [{ json: {
  toRecipients: "jenniferyu@k11byac.com",
  subject: "内容审核 - " + new Date().toISOString().slice(0, 16).replace('T', ' '),
  message: "<h2>📱 小红书帖子草稿审核</h2>\n" + (script.script_display || "") + "\n<p>请点击下方按钮打开表单，选择版本并提交。</p>",
  formJson
} }];
"""
prep_approval2 = code_node("Prepare Approval2 Input", PREP_APPROVAL2_CODE)

exec_approval2 = deepcopy(exec_approval1)
exec_approval2["id"] = nid()
exec_approval2["name"] = "Execute WF3 審核2"

branch_id = copy_node(ORIG, "Branch identifier")
switch2 = copy_node(ORIG, "Switch")
extract_script_ok = copy_node(ORIG, "Extract Selected Scripts for approve case")
extract_script_retry = copy_node(ORIG, "Extract Selected scripts for reject case")
save_scripts = copy_node(ORIG, "Save Scripts to Sheet")
ai_agent = copy_node(ORIG, "AI Agent")
model_agent = copy_node(ORIG, "OpenRouter Chat Model Analysis3")
code_final = copy_node(ORIG, "Code in JavaScript1")
send_final = copy_node(ORIG, "Send a message")

WF2_NODES = [
    schedule2, serper, merge, append_articles, prep_articles, first_input,
    select_agent, model_select, parse_response, format_email, prep_approval1,
    exec_approval1, switch1, extract_dir_ok, extract_dir_retry, gen_full,
    model_full, save_analysis, read_latest_analysis, read_memory1,
    read_feedback, prep_third, gen_script, model_script, save_analysis1,
    parse_scripts, format_script_email, split_versions, prep_approval2,
    exec_approval2, branch_id, switch2, extract_script_ok, extract_script_retry,
    save_scripts, ai_agent, model_agent, code_final, send_final,
    sticky("說明", "WF2 內容生成（14:00）\n搜尋 → 選方向（審核1）→ 全分析 → 依上週執行摘要生成腳本 → 版本審核（審核2）→ 儲存/寄出。\n"
                   "● 兩段審核透過 Execute Workflow 呼叫 WF3\n"
                   "● 匯入後請把兩個「Execute WF3」節點的 workflowId 改成 WF3 的工作流 ID"),
]


def conn2(src, targets):
    WF2_CONN[src] = {"main": [[{"node": t, "type": "main", "index": 0}] for t in targets]}


conn2(schedule2["name"], [serper["name"]])
conn2(serper["name"], [merge["name"]])
conn2(merge["name"], [append_articles["name"]])
conn2(append_articles["name"], [prep_articles["name"]])
conn2(prep_articles["name"], [first_input["name"]])
conn2(first_input["name"], [select_agent["name"]])
WF2_CONN[model_select["name"]] = {"ai_languageModel": [[{"node": select_agent["name"], "type": "ai_languageModel", "index": 0}]]}
conn2(select_agent["name"], [parse_response["name"]])
conn2(parse_response["name"], [format_email["name"]])
conn2(format_email["name"], [prep_approval1["name"]])
conn2(prep_approval1["name"], [exec_approval1["name"]])
conn2(exec_approval1["name"], [switch1["name"]])
WF2_CONN[switch1["name"]] = {"main": [
    [{"node": extract_dir_ok["name"], "type": "main", "index": 0}],
    [{"node": extract_dir_ok["name"], "type": "main", "index": 0}],
    [{"node": extract_dir_ok["name"], "type": "main", "index": 0}],
    [{"node": extract_dir_retry["name"], "type": "main", "index": 0}],
]}
conn2(extract_dir_ok["name"], [gen_full["name"]])
WF2_CONN[model_full["name"]] = {"ai_languageModel": [[{"node": gen_full["name"], "type": "ai_languageModel", "index": 0}]]}
conn2(gen_full["name"], [save_analysis["name"]])
conn2(extract_dir_retry["name"], [first_input["name"]])
conn2(save_analysis["name"], [read_latest_analysis["name"]])
conn2(read_latest_analysis["name"], [read_memory1["name"]])
conn2(read_memory1["name"], [read_feedback["name"]])
conn2(read_feedback["name"], [prep_third["name"]])
conn2(prep_third["name"], [gen_script["name"]])
WF2_CONN[model_script["name"]] = {"ai_languageModel": [[{"node": gen_script["name"], "type": "ai_languageModel", "index": 0}]]}
conn2(gen_script["name"], [save_analysis1["name"]])
conn2(save_analysis1["name"], [parse_scripts["name"]])
conn2(parse_scripts["name"], [format_script_email["name"]])
conn2(format_script_email["name"], [split_versions["name"]])
conn2(split_versions["name"], [prep_approval2["name"]])
conn2(prep_approval2["name"], [exec_approval2["name"]])
conn2(exec_approval2["name"], [branch_id["name"]])
conn2(branch_id["name"], [switch2["name"]])
WF2_CONN[switch2["name"]] = {"main": [
    [{"node": extract_script_ok["name"], "type": "main", "index": 0}],
    [{"node": extract_script_ok["name"], "type": "main", "index": 0}],
    [{"node": extract_script_ok["name"], "type": "main", "index": 0}],
    [{"node": extract_script_retry["name"], "type": "main", "index": 0}],
]}
conn2(extract_script_ok["name"], [save_scripts["name"]])
conn2(extract_script_retry["name"], [prep_third["name"]])
conn2(save_scripts["name"], [ai_agent["name"]])
WF2_CONN[model_agent["name"]] = {"ai_languageModel": [[{"node": ai_agent["name"], "type": "ai_languageModel", "index": 0}]]}
conn2(ai_agent["name"], [code_final["name"]])
conn2(code_final["name"], [send_final["name"]])

WF2 = workflow("佛山_WF2_内容生成", WF2_NODES, WF2_CONN)
validate(WF2, "WF2")
js_check([n for n in WF2_NODES if n["name"] in ("Prepare Approval1 Input", "Prepare Approval2 Input")], "WF2-new")


# =====================================================================
# 儲存
# =====================================================================
wf1_path = save(WF1, "佛山_WF1_数据分析.json")
wf2_path = save(WF2, "佛山_WF2_内容生成.json")
wf3_path = save(WF3, "佛山_WF3_人工审核.json")

print("\n已輸出：")
for p in (wf1_path, wf2_path, wf3_path):
    print(f"  {p} ({p.stat().st_size} bytes)")
print(f"\nWF3 workflow id: {WF3['id']}")
