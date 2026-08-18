"""修改 n8n 工作流的回饋迴圈，輸出到新檔案（不覆蓋原檔）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

SRC = Path("data/n8n_workflow.json")
DST = Path("data/n8n_workflow_modified.json")
CHECK_DIR = Path("data/js_check")

data = json.loads(SRC.read_text(encoding="utf-8"))
orig_node_ids = {n["id"] for n in data["nodes"]}
orig_node_names = {n["name"] for n in data["nodes"]}


def find(name: str) -> dict:
    for n in data["nodes"]:
        if n.get("name") == name:
            return n
    raise SystemExit(f"找不到節點: {name}")


def set_code(name: str, code: str) -> None:
    find(name).setdefault("parameters", {})["jsCode"] = code


def set_param(name: str, key: str, value) -> None:
    find(name).setdefault("parameters", {})[key] = value


# ============ 1) Transform & Label ============
TRANSFORM_LABEL_CODE = r"""const items = $input.all();
const labelledPosts = [];

const WEEK_ANCHOR = new Date('2026-07-01T00:00:00+08:00'); // 第一週起點（W1 = 7/1–7/7）

function getWeekNumber(dateHKT) {
  const t = dateHKT.getTime() - WEEK_ANCHOR.getTime();
  if (t < 0) return null; // anchor 之前的帖文不歸週
  return Math.floor(t / (7 * 24 * 60 * 60 * 1000)) + 1;
}

function latestCompleteWeek(nowHKT) {
  const anchor = WEEK_ANCHOR.getTime();
  let n = 1;
  while (anchor + n * 7 * 24 * 60 * 60 * 1000 - 1 < nowHKT) n += 1;
  return n - 1;
}

for (const item of items) {
  const post = item.json;

  // === Field mapping from Xiaohongshu scraper ===
  const caption = (post.title || post.content || '').trim();
  const likes = post.likes || 0;
  const comments = post.comments || 0;
  const saves = post.saves || 0;
  const shares = post.shares || 0;
  const timestampUTC = post.publishedAt || post.scrapedAt || '';
  const permalink = post.postUrl || '';
  const postId = post.postId || '';
  const hashtags = Array.isArray(post.tags) ? post.tags.join(' ') : '';
  const mentions = ''; // Xiaohongshu scraper rarely returns mentions

  // Media / type
  const isVideo = post.type === 'video';
  const isCarousel = Array.isArray(post.images) && post.images.length > 1;
  const imageCount = Array.isArray(post.images) ? post.images.length : 0;

  // === Time handling → UTC+8 ===
  let postHourHKT = null;
  let postDayHKT = null;
  let isEveningHKT = false;
  let timestampHKT = '';
  let weekNumber = null;

  if (timestampUTC) {
    const dateUTC = new Date(timestampUTC);
    if (!isNaN(dateUTC.getTime())) {
      const dateHKT = new Date(dateUTC.getTime() + 8 * 60 * 60 * 1000);
      postHourHKT = dateHKT.getHours();
      postDayHKT = dateHKT.getDay();
      isEveningHKT = postHourHKT >= 17;
      timestampHKT = dateHKT.toISOString();
      weekNumber = getWeekNumber(dateHKT);
    }
  }

  // 資料成熟度：最新完整週以前的週次 = 完整（已隔週補抓）；本週 = 初步（第一次被抓）
  const nowHKT = new Date(Date.now() + 8 * 60 * 60 * 1000);
  const latestWeek = latestCompleteWeek(nowHKT);
  const maturity = (weekNumber !== null && weekNumber < latestWeek) ? 'complete' : 'preliminary';

  // === Content features ===
  const captionLength = caption.length;
  const hasQuestion = /[？?]/.test(caption) || /吗|呢|怎么|哪里|你/.test(caption);
  const hasNumber = /\d+/.test(caption);
  const hasEmoji = /[\u{1F300}-\u{1F9FF}]|🍃|💚|🌱/u.test(caption);
  const hasCallToAction = /请|欢迎|试试|来|一起|你呢|怎么样|关注|收藏/.test(caption);

  labelledPosts.push({
    post_id: postId,
    caption: caption,
    likes: likes,
    comments: comments,
    saves: saves,
    shares: shares,
    engagement: likes + comments * 3,          // same formula you used
    timestamp_utc: timestampUTC,
    timestamp_hkt: timestampHKT,
    post_hour_hkt: postHourHKT,
    post_day_hkt: postDayHKT,
    is_evening_hkt: isEveningHKT,
    permalink: permalink,
    is_video: isVideo,
    is_carousel: isCarousel,
    image_count: imageCount,
    caption_length: captionLength,
    has_question: hasQuestion,
    has_number: hasNumber,
    has_emoji: hasEmoji,
    has_cta: hasCallToAction,
    hashtags: hashtags,
    week_number: weekNumber,
    maturity: maturity,
    author: post.authorName || post.author?.nickname || '',
    author_id: post.author?.userId || ''
  });
}

// Sort by engagement (highest first)
labelledPosts.sort((a, b) => b.engagement - a.engagement);

return labelledPosts.map(p => ({ json: p }));
"""
set_code("Transform & Label", TRANSFORM_LABEL_CODE)


# ============ 2) Prepare for AI analysis ============
PREPARE_CODE = r"""const rows = $input.all();
const postStats = [];

for (const row of rows) {
  const post = row.json || row;

  postStats.push({
    post_id: post.post_id || '',
    caption: post.caption || '',
    likes: post.likes || 0,
    comments_count: post.comments || 0,
    saves: post.saves || 0,
    shares: post.shares || 0,
    engagement: post.engagement || ((post.likes || 0) + (post.comments || 0) * 3),
    timestamp_utc: post.timestamp_utc || '',
    timestamp_hkt: post.timestamp_hkt || '',
    post_hour_hkt: post.post_hour_hkt,
    post_day_hkt: post.post_day_hkt,
    is_evening_hkt: post.is_evening_hkt || false,
    permalink: post.permalink || '',
    caption_length: post.caption_length || (post.caption || '').length,
    has_question: post.has_question || false,
    has_number: post.has_number || false,
    has_emoji: post.has_emoji || false,
    has_cta: post.has_cta || false,
    is_carousel: post.is_carousel || false,
    is_video: post.is_video || false,
    image_count: post.image_count || 0,
    hashtags: post.hashtags || '',
    week_number: (post.week_number === undefined || post.week_number === null) ? null : post.week_number,
    maturity: post.maturity || 'preliminary',
    author: post.author || ''
  });
}

// Sort by engagement
postStats.sort((a, b) => b.engagement - a.engagement);

// === 週次分組（本週 = 最新完整週且為初步；基準週 = 前一週）===
const weekNumbers = postStats.map(p => p.week_number).filter(n => n !== null);
const targetWeek = weekNumbers.length ? Math.max(...weekNumbers) : null;
const currentWeek = targetWeek === null ? [] : postStats.filter(p => p.week_number === targetWeek);
const referenceWeek = targetWeek === null ? [] : postStats.filter(p => p.week_number === targetWeek - 1);

function statsOf(list) {
  if (!list.length) return null;
  const avg = (arr) => arr.length ? Math.round(arr.reduce((s, x) => s + x, 0) / arr.length) : 0;
  const med = (arr) => {
    if (!arr.length) return 0;
    const s = [...arr].sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
  };
  const hours = {};
  list.forEach(p => {
    if (p.post_hour_hkt !== null && p.post_hour_hkt !== undefined) {
      hours[p.post_hour_hkt] = (hours[p.post_hour_hkt] || 0) + 1;
    }
  });
  const bestHour = Object.entries(hours).sort((a, b) => b[1] - a[1]);
  return {
    n: list.length,
    avgLikes: avg(list.map(p => p.likes)),
    avgSaves: avg(list.map(p => p.saves)),
    avgShares: avg(list.map(p => p.shares)),
    avgComments: avg(list.map(p => p.comments_count)),
    medLikes: med(list.map(p => p.likes)),
    medSaves: med(list.map(p => p.saves)),
    medShares: med(list.map(p => p.shares)),
    bestHour: bestHour.length ? Number(bestHour[0][0]) : null
  };
}

const totalPosts = postStats.length;
const prelimCount = postStats.filter(p => p.maturity === 'preliminary').length;
const completeCount = totalPosts - prelimCount;
const cur = statsOf(currentWeek);
const ref = statsOf(referenceWeek);

function pct(a, b) {
  if (!b) return '—';
  return `${a >= b ? '+' : ''}${Math.round((a - b) / b * 100)}%`;
}

// === 週對週比較（新週 vs 舊週）===
let comparisonText = '（無基準週數據可比較）';
if (cur && ref) {
  comparisonText = [
    `本週(W${targetWeek}) ${cur.n} 篇 vs 基準週(W${targetWeek - 1}) ${ref.n} 篇`,
    `平均讚：${cur.avgLikes} vs ${ref.avgLikes}（${pct(cur.avgLikes, ref.avgLikes)}）`,
    `平均收藏：${cur.avgSaves} vs ${ref.avgSaves}（${pct(cur.avgSaves, ref.avgSaves)}）`,
    `平均分享：${cur.avgShares} vs ${ref.avgShares}（${pct(cur.avgShares, ref.avgShares)}）`,
    `平均留言：${cur.avgComments} vs ${ref.avgComments}（${pct(cur.avgComments, ref.avgComments)}）`
  ].join('\n');
} else if (cur && !ref) {
  comparisonText = `本週(W${targetWeek}) ${cur.n} 篇，無基準週(W${targetWeek - 1})數據，僅能做本週內部相對比較`;
}

// === Build summary for AI ===
let summary = `小紅書內容表現數據（HKT）\n\n`;
summary += `【資料概況】共 ${totalPosts} 篇（初步 ${prelimCount} 篇、完整 ${completeCount} 篇）；小紅書無瀏覽量，忽略 views，主要比較點讚/收藏/分享（留言為輔）\n\n`;

if (cur) {
  const curPrelim = currentWeek.filter(p => p.maturity === 'preliminary').length;
  summary += `【本週 W${targetWeek}】${cur.n} 篇（初步 ${curPrelim}、完整 ${cur.n - curPrelim}）\n`;
  summary += `平均 讚 ${cur.avgLikes}｜收藏 ${cur.avgSaves}｜分享 ${cur.avgShares}｜留言 ${cur.avgComments}\n`;
  summary += `中位數 讚 ${cur.medLikes}｜收藏 ${cur.medSaves}｜分享 ${cur.medShares}\n`;
  if (cur.bestHour !== null) summary += `本週高頻發布時段：${cur.bestHour}:00 HKT\n`;
  summary += `高表現前 3 名：\n`;
  currentWeek.slice(0, 3).forEach((p, i) => {
    const timeStr = p.post_hour_hkt !== null ? `${p.post_hour_hkt}:00 HKT` : 'N/A';
    summary += `${i + 1}. 讚 ${p.likes}｜藏 ${p.saves}｜享 ${p.shares}｜評 ${p.comments_count}｜${timeStr}｜${p.caption.substring(0, 100)}\n`;
  });
  summary += `低表現後 3 名：\n`;
  currentWeek.slice(-3).forEach((p, i) => {
    const timeStr = p.post_hour_hkt !== null ? `${p.post_hour_hkt}:00 HKT` : 'N/A';
    summary += `${i + 1}. 讚 ${p.likes}｜藏 ${p.saves}｜享 ${p.shares}｜評 ${p.comments_count}｜${timeStr}｜${p.caption.substring(0, 100)}\n`;
  });
}

if (ref) {
  const refPrelim = referenceWeek.filter(p => p.maturity === 'preliminary').length;
  summary += `\n【基準週 W${targetWeek - 1}】${ref.n} 篇（初步 ${refPrelim}、完整 ${ref.n - refPrelim}）\n`;
  summary += `平均 讚 ${ref.avgLikes}｜收藏 ${ref.avgSaves}｜分享 ${ref.avgShares}｜留言 ${ref.avgComments}\n`;
}

summary += `\n【週對週比較】\n${comparisonText}\n`;

return [{
  json: {
    analysisSummary: summary,
    posts: postStats,
    currentWeek,
    referenceWeek,
    targetWeek
  }
}];
"""
set_code("Prepare for AI analysis", PREPARE_CODE)


# ============ 3) AI Analysis：提示詞 ============
AI_TEXT = (
    "=以下是近期帖子表现数据（含本週初步 / 基準週完整分組與週對週比較）：\n"
    "{{ $json.analysisSummary }}\n\n"
    "==== 上一週的策略結論（Strategy Hypotheses，本週發布策略的依據，請判斷本週是否照做）====\n"
    '{{ $json.existing_claims_text || "（尚無既有 claims）" }}\n\n'
    "规则：\n"
    "1) 先判斷本週帖文是否遵循了上一週的策略結論；若有，評估調整後的效果（本週 vs 基準週）\n"
    "2) 若本輪觀察到的策略與既有 claim **語意相同**，必須重用同一個 claim_key（不要改寫 key）\n"
    "3) 只有真正新的策略才可新建 claim_key\n"
    "4) claim 中文表述可以不同，但 claim_key / dimension / direction / bucket 必須穩定\n\n"
    "请根据以上数据，生成内容策略优化反馈。必须严格按系统要求输出 JSON（含 summary + report + claims）。"
)

AI_SYSTEM = (
    "你是一位專業的 Xiaohongshu 內容策略分析師，專注於產出高可執行性的優化報告、結構化執行摘要，以及可追蹤的策略假設（claims）。\n\n"
    "你會收到：\n"
    "A) 內容表現數據（含 資料概況、本週(初步) 與 基準週(完整) 分組、週對週比較）\n"
    "B) 上一週的策略結論（existing claims，本週發布策略的依據）\n\n"
    "即使數據有限，也要給出深入且實操性強的分析。\n\n"
    "核心任務：\n"
    "1) 判斷本週帖文是否遵循了上一週的策略結論；若有，評估調整後的效果（本週 vs 基準週）\n"
    "2) 對比高表現組與低表現組，並參考整體趨勢，找出成功因素\n"
    "3) 產出結構化「執行摘要 summary」（最重要，會被交給下週的 AI 作為發布策略依據）\n"
    "4) 產出可讀的策略報告（report）\n"
    "5) 產出結構化 claims（候選策略假設，供多輪驗證，不是最終規則）\n\n"
    "執行摘要 summary 必須包含四個部分並全部條列：\n"
    "①資料基礎：本次分析的週次、各週篇數、初步/完整狀態各多少、比較哪些指標、樣本限制\n"
    "②本週關鍵發現：3-5 個有具體數字依據的重點（附實際數據）\n"
    "③下週行動建議：可執行的發布策略（時間/長度/標題/語氣/標籤）\n"
    "④下週驗證重點：數據成熟後要確認什麼、哪些初步結論可能改變\n"
    "注意：這份摘要會被交給下週的 AI 當策略依據，因此必須自足、具體、客觀、不模稜兩可，"
    "避免『可能』『或許』等含糊措辭，每個建議都要寫明依據。\n\n"
    "分析維度：\n"
    "- 目標受眾\n"
    "- 最佳發帖時間（UTC+8 / HKT）\n"
    "- 標題/開頭結構\n"
    "- 帖子長度\n"
    "- 語氣風格\n"
    "- 標籤策略\n\n"
    "嚴格規則：\n"
    "- 小紅書無瀏覽量，完全忽略 views；主要比較「點讚、收藏、分享」（留言為輔）\n"
    "- 標記為 preliminary 的帖文（本週）是第一次被抓，數據未成熟，不得僅憑初步數據下結論\n"
    "- 標記為 complete 的帖文（基準週）已隔週補抓，數據成熟，是比較基準\n"
    "- 所有分析與建議必須基於整體多數模式與統計趨勢\n"
    "- 絕對禁止只依據單一或極少數貼文就提出強改變建議\n"
    "- 趨勢不明顯時要保守；樣本少時要明確標註信心限制\n"
    "- claims 只代表「本輪觀察到的候選假設」，不是最終記憶\n\n"
    "==== claim 身份穩定規則（最重要）====\n"
    "禁止用自由發揮的長句當 claim_key。\n"
    "每個 claim 必須提供：\n"
    "- dimension: posting_time | caption_length | tone | structure | image_type | hashtags | audience | other\n"
    "- direction: prefer | avoid | test\n"
    "- bucket: 短英文 snake_case 槽位（穩定、可跨輪重用）\n"
    "- claim_key: 必須等於 dimension__direction__bucket（全小寫，底線分隔）\n\n"
    "bucket 規則：\n"
    "- posting_time: 小時區間，如 10_14、18_21、12_13\n"
    "- caption_length: 字數區間，如 80_120、130_180、200_plus\n"
    "- tone: data_driven | storytelling | casual | professional | question_led\n"
    "- structure: question_hook | number_hook | story_hook | cta_end | list_format\n"
    "- image_type: real_photo | ai_image | carousel | single_image\n"
    "- hashtags: few_tags | many_tags | branded_tags | no_tags\n"
    "- audience: fans | beginners | collectors | general\n"
    "- other: 最多 3 個英文詞，如 engagement_cta\n\n"
    "strength:\n"
    "- low：弱信號 / 樣本少\n"
    "- medium：有集群但不夠穩\n"
    "- high：高表現群中明顯集中且樣本足夠\n"
    "- sample_support：支持該 claim 的帖子數量（整數）\n\n"
    "既有 claims 重用規則：\n"
    "- 若輸入中已有 existing claims，且本輪策略語意相同 → 必須輸出完全相同的 claim_key / dimension / direction / bucket\n"
    "- claim 與 evidence_summary 可用不同中文表述\n"
    "- 只有策略本質不同時才新建 key\n\n"
    "重要：\n"
    "- 不要因為單次分析就要求系統立刻改策略\n"
    "- 弱信號可以進 claims，但 strength 必須標 low\n"
    "- 若沒有足夠證據，claims 可為空陣列\n\n"
    "輸出必須是嚴格 JSON（不要 markdown 代碼塊，不要多餘說明）：\n"
    "{\n"
    '  "summary": "執行摘要（四部分，見上：資料基礎/關鍵發現/下週行動建議/下週驗證重點）",\n'
    '  "report": "完整中文策略分析報告（分段清晰，含可執行建議與A/B測試計劃）",\n'
    '  "claims": [\n'
    "    {\n"
    '      "claim_key": "posting_time__prefer__10_14",\n'
    '      "dimension": "posting_time",\n'
    '      "direction": "prefer",\n'
    '      "bucket": "10_14",\n'
    '      "claim": "建議發文時段 10:00-14:00 HKT",\n'
    '      "evidence_summary": "高表現貼文中約X%落在此時段",\n'
    '      "strength": "medium",\n'
    '      "sample_support": 6\n'
    "    }\n"
    "  ]\n"
    "}"
)

node = find("AI Analysis")
node.setdefault("parameters", {})["text"] = AI_TEXT
node["parameters"].setdefault("options", {})["systemMessage"] = AI_SYSTEM


# ============ 4) Extract analysis result：解析 summary ============
node = find("Extract analysis result")
code = node["parameters"]["jsCode"]

assert "let report = cleaned;" in code, "找不到 report 宣告"
assert "let claims = [];" in code, "找不到 claims 宣告"
code = code.replace(
    "let report = cleaned;\nlet claims = [];",
    "let report = cleaned;\nlet summary = '';\nlet claims = [];",
    1,
)

assert "if (parsed && typeof parsed === 'object') {" in code, "找不到 parsed 區塊"
code = code.replace(
    "if (parsed && typeof parsed === 'object') {\n    if (typeof parsed.report === 'string'",
    "if (parsed && typeof parsed === 'object') {\n"
    "    if (typeof parsed.summary === 'string' && parsed.summary.trim()) {\n"
    "      summary = parsed.summary.trim();\n"
    "    }\n"
    "    if (typeof parsed.report === 'string'",
    1,
)

assert "feedback: report," in code, "找不到 feedback 輸出"
code = code.replace(
    "feedback: report,",
    "feedback: summary || report,\n    summary,\n    report,",
    1,
)
node["parameters"]["jsCode"] = code


# ============ 5) Prepare Third AI Input：把反饋當「上一週執行摘要」====
node = find("Prepare Third AI Input")
code = node["parameters"]["jsCode"]
OLD_PROMPT = r"let enhanced_prompt = `【最新策略反馈】\n${latest_feedback}\n\n【当前记忆库】\n${current_memory}\n\n请严格参考以上生成高质量帖子。`;"
NEW_PROMPT = (
    r"let enhanced_prompt = `【上一週執行摘要（本週發布策略依據，必須遵守）】\n"
    r"${latest_feedback}\n\n"
    r"【当前记忆库】\n"
    r"${current_memory}\n\n"
    r"请严格参考以上内容：\n"
    r"1) 遵循上一週摘要的「下週行動建議」\n"
    r"2) 參考「下週驗證重點」修正發布策略\n"
    r"3) 摘要中標記為「初步/尚待驗證」的結論要保持保守\n"
    r"4) 生成高質量帖子。`;"
)
assert OLD_PROMPT in code, "找不到 enhanced_prompt 原始內容"
code = code.replace(OLD_PROMPT, NEW_PROMPT, 1)
node["parameters"]["jsCode"] = code


# ============ 儲存 + 驗證 ============
DST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# 1) 結構驗證
new_data = json.loads(DST.read_text(encoding="utf-8"))
new_ids = {n["id"] for n in new_data["nodes"]}
new_names = {n["name"] for n in new_data["nodes"]}
assert new_ids == orig_node_ids, "節點集合不一致！"
for src, targets in new_data.get("connections", {}).items():
    assert src in new_names, f"連線來源不存在: {src}"
    for conn in targets.get("main", []):
        for t in conn:
            assert t.get("node") in new_names, f"連線目標不存在: {t.get('node')}"
print(f"已輸出（結構驗證通過）：{DST}")

# 2) JS 語法檢查
CHECK_DIR.mkdir(exist_ok=True)
node_bin = Path(r"C:\Users\DanielHau\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
for name in [
    "Transform & Label",
    "Prepare for AI analysis",
    "Extract analysis result",
    "Prepare Third AI Input",
]:
    js = find(name)["parameters"]["jsCode"]
    tmp = CHECK_DIR / (name.replace(" ", "_").replace("&", "and") + ".js")
    tmp.write_text(js, encoding="utf-8")
    r = subprocess.run([str(node_bin), "--check", str(tmp)], capture_output=True, text=True)
    status = "OK" if r.returncode == 0 else f"FAIL: {r.stderr.strip()[:300]}"
    print(f"JS 語法 [{name}]: {status}")
