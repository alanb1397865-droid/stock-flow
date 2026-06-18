#!/usr/bin/env python3
"""
Vault 分析助理 — Streamlit App
台股投資研究資料庫，自然語言查詢介面
"""

import re
import json
import sqlite3
import streamlit as st
from groq import Groq
from pathlib import Path

# ── 頁面設定 ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="台股研究助理",
    page_icon="📊",
    layout="wide",
)

# ── 資料庫 ──────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent / "vault_index.db"


@st.cache_resource
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def run_sql(sql: str) -> tuple[list[dict], str | None]:
    try:
        cur = get_conn().execute(sql)
        return [dict(r) for r in cur.fetchall()], None
    except Exception as e:
        return [], str(e)


def db_stats() -> dict:
    stats = {}
    for tbl in ["companies", "patents", "financials", "prices", "observations"]:
        try:
            n = get_conn().execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            stats[tbl] = n
        except Exception:
            stats[tbl] = 0
    return stats


# ── Claude ──────────────────────────────────────────────────────────────────

@st.cache_resource
def get_client():
    key = st.secrets.get("GROQ_API_KEY", "")
    if not key:
        st.error("請在 Streamlit secrets 設定 GROQ_API_KEY")
        st.stop()
    return Groq(api_key=key)


@st.cache_resource
def get_all_themes() -> str:
    """從資料庫讀取所有技術主題，注入 system prompt"""
    rows = get_conn().execute(
        "SELECT DISTINCT theme FROM observations ORDER BY theme"
    ).fetchall()
    return "、".join(r[0] for r in rows if r[0])


SYSTEM_PROMPT = """你是一個台股投資研究助理，連接到一個結構化的投資研究資料庫。

## 資料庫結構

**companies**（上市公司，~387 家）
- name TEXT PK, code TEXT, industry TEXT, sub_industry TEXT

**patents**（專利，~6,937 件）
- pub_no TEXT PK, title TEXT, applicant TEXT, code TEXT
- theme TEXT（技術主題）, domain TEXT（技術領域）, ipc TEXT（JSON）

**patent_batches**（批次對應，~10,779 筆）
- pub_no TEXT, batch TEXT（如 "2026.04"）
- 批次越多、越新 = 趨勢越持久、越迫切
- 可用批次：2025.02 / 2025.03 / 2025.09 / 2026.02 / 2026.03 / 2026.04 / 2026.05 / 2026.06

**financials**（財報，~4,062 筆）
- company_code TEXT, period TEXT（如 "2026Q1"、"2025Y"）, period_type TEXT
- revenue REAL（億）, gross_profit REAL, op_profit REAL, net_profit REAL
- eps REAL, gross_margin REAL（%）, op_margin REAL（%）, net_margin REAL（%）

**prices**（週線股價，~37,229 筆）
- company_name TEXT, company_code TEXT, week_date TEXT（YYYY-MM-DD）
- open/high/low/close REAL, volume INTEGER

**observations**（技術觀察，~3,223 筆）
- batch TEXT, theme TEXT, company_name TEXT

## 重要背景

這些專利是由演算法從全球專利篩選出的「未來 6-12 個月主要技術趨勢」。
被選入的公司代表在該技術領域具備先發優勢。
批次越多（如同一公司出現在 2026.04、2026.05、2026.06 三個批次）= 趨勢持續強化。

## 分析框架（三維）

**第一維：財報（現在的實力）**
- 毛利率趨勢（核心指標）
- EPS 成長品質：A 級（本業驅動）/ C+ 級（業外虛增）/ D 級（基期異常）

**第二維：專利＋趨勢（未來動能）**
- 技術主題是否對齊市場方向
- 批次數量與新舊程度
- 多個技術主題同時布局 = 多點共振，優先關注

**第三維：股價（市場熱度）**
- 近期量價配合
- 財報品質與股價表現的落差

綜合評分標籤：⭐ 三維共振 / 💡 潛力低估 / ⚠️ 高估風險 / 🔥 資金炒作 / 📋 B 型觀察

## 查詢規則

**【最重要規定】任何問題都必須先查資料庫，禁止使用自身訓練知識回答。**
即使你知道某公司（如台積電、奇鋐），也必須查資料庫取得實際數字。

需要資料時，輸出：
QUERY: <SQL語句>

**嚴格規定（必須遵守）：**
1. 輸出 QUERY: 後立即停止，絕對不可以自己假設或捏造查詢結果
2. 等待系統回傳真實資料後，才進行分析
3. **財報、股價表用 company_code（數字代碼）查詢，不是公司名稱**
4. 不確定代碼時，先用 `SELECT code FROM companies WHERE name LIKE '%公司名%'` 查
5. 每輪最多 3 個查詢，SQL 使用 SQLite 語法
6. 回應使用繁體中文，數字保留 2 位小數

**標準查詢流程（分析單一公司）：**
```
QUERY: SELECT code FROM companies WHERE name LIKE '%公司名%'
QUERY: SELECT period, gross_margin, op_margin, eps FROM financials WHERE company_code='代碼' ORDER BY period DESC LIMIT 8
QUERY: SELECT week_date, close, volume FROM prices WHERE company_code='代碼' ORDER BY week_date DESC LIMIT 8
```

## 資料庫中所有技術主題（查詢時必須用這些確切名稱）

{themes}

使用者說「液冷散熱」→ 對應「冷卻系統與裝置」、「冷卻與散熱技術」、「散熱器技術」、「散熱管理」
使用者說「AI」→ 對應「人工智慧技術」、「中央運算處理與AI技術」
使用者說「伺服器」→ 對應「伺服器及其組件」
使用者說「半導體」→ 對應所有「半導體」開頭的主題"""


def extract_queries(text: str) -> list[str]:
    return re.findall(r"QUERY:\s*(.+?)(?=QUERY:|$)", text, re.DOTALL)


def strip_queries(text: str) -> str:
    return re.sub(r"QUERY:\s*.+?(?=QUERY:|$)", "", text, flags=re.DOTALL).strip()


def chat(messages: list[dict]) -> str:
    """兩輪對話：第一輪生成 SQL，第二輪分析結果"""
    client = get_client()

    system = SYSTEM_PROMPT.replace("{themes}", get_all_themes())

    def call(msgs):
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + msgs,
            max_tokens=2048,
            temperature=0.3,
        )
        return r.choices[0].message.content

    # 第一輪：讓模型決定查什麼
    first = call(messages)
    queries = extract_queries(first)

    if not queries:
        return strip_queries(first) or first

    # 執行查詢
    result_parts = []
    for sql in queries[:3]:
        rows, err = run_sql(sql.strip())
        if err:
            result_parts.append(f"查詢錯誤：{err}\nSQL：{sql.strip()}")
        else:
            preview = rows[:50]
            result_parts.append(
                f"查詢到 {len(rows)} 筆（顯示前 50 筆）：\n"
                + json.dumps(preview, ensure_ascii=False)
            )

    # 第二輪：帶資料分析
    final = call(
        messages
        + [{"role": "assistant", "content": first},
           {"role": "user", "content":
               "查詢結果：\n\n"
               + "\n\n---\n\n".join(result_parts)
               + "\n\n請根據以上資料，用三維分析框架給出完整分析與結論。不要再輸出 QUERY:，直接輸出分析文字。"}]
    )
    return strip_queries(final) or final


# ── UI ──────────────────────────────────────────────────────────────────────

def main():
    # 側邊欄
    with st.sidebar:
        st.title("📊 台股研究助理")
        st.caption("Vault 資料庫 · 自然語言查詢")

        st.divider()

        stats = db_stats()
        st.markdown("**資料庫現況**")
        st.markdown(f"- 公司：{stats['companies']:,} 家")
        st.markdown(f"- 專利：{stats['patents']:,} 件")
        st.markdown(f"- 財報：{stats['financials']:,} 筆")
        st.markdown(f"- 股價：{stats['prices']:,} 筆")
        st.markdown(f"- 技術觀察：{stats['observations']:,} 筆")

        st.divider()

        st.markdown("**問題範例**")
        examples = [
            "液冷散熱題材有哪些公司？",
            "奇鋐最近幾季財報表現",
            "毛利率超過 30% 且有 AI 相關專利",
            "2026 年新批次哪些技術最熱？",
            "哪些公司在多個技術主題都有布局？",
        ]
        for ex in examples:
            if st.button(ex, use_container_width=True, key=ex):
                st.session_state.pending_input = ex

        st.divider()
        if st.button("🗑️ 清除對話", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    # 主畫面
    st.header("台股研究助理")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_input" not in st.session_state:
        st.session_state.pending_input = None

    # 歷史對話
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 輸入（側邊欄快捷鍵或手動輸入）
    user_input = st.chat_input("問我關於台股的任何問題…")
    if st.session_state.pending_input:
        user_input = st.session_state.pending_input
        st.session_state.pending_input = None

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("查詢資料庫、分析中…"):
                try:
                    answer = chat(
                        [{"role": m["role"], "content": m["content"]}
                         for m in st.session_state.messages]
                    )
                except Exception as e:
                    answer = f"⚠️ 發生錯誤：{e}"
            st.markdown(answer)

        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.rerun()


if __name__ == "__main__":
    main()
