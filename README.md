# Agent Harness

A from-scratch agent harness, built over the course of nine chapters.

## Setup

```bash
git clone https://github.com/Poyuchao/Harness-Engineering.git
cd Harness-Engineering
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENAI_API_KEY
```

## Run

```bash
python -m harness.agent
```

## Project structure

```
harness/
├── agent.py            # 入口：對話迴圈、system prompt、模型選擇
└── tools/
    ├── registry.py     # 工具登記處：Tool、ToolRegistry、@tool
    └── filesystem.py   # 檔案工具，限制在 .workspace/ 內
```

---

# 學習紀錄

## Chapter 2：Bare Loop

### 02-01 Project scaffold

- 建立 venv、`requirements.txt`（`openai`、`python-dotenv`）、`.env.example`、`.gitignore`、`harness/` 套件。
- 用 `smoke.py` 確認能連上 OpenAI API（之後已刪除）。
- 坑：`openai==1.50.0` 與 `httpx>=0.28` 不相容（`proxies` 參數被移除），需 pin `httpx<0.28`。

### 02-02 Bare loop

- **Agent = 包在無狀態模型外面的 while loop。**
- 模型本身沒有記憶；「記憶」來自每次呼叫都**重送整段對話歷史**（`messages` list）。
- 迴圈步驟：讀輸入 → append user 訊息 → 帶完整歷史呼叫模型 → append assistant 回覆 → 印出 → 回到開頭。
- user 訊息和 assistant 回覆**都要** append，少一個歷史就不完整。

### 02-03 Kimi backend（選用）

- Kimi（Moonshot AI）相容 OpenAI API，只需換 `api_key` 和 `base_url`。
- `.env` 有 `KIMI_API_KEY` 就用 `kimi-k2.6`，否則預設 `gpt-4o-mini`。
- Kimi K2.6+ 預設開 thinking，用 `extra_body={"thinking": {"type": "disabled"}}` 關掉以省 token。
- `extra_body` 用來傳 provider 專屬參數；OpenAI 時為 `None`。

### 02-04 System prompt

- System prompt 是 `role: "system"` 的訊息，放在 `messages` **第一個**，每次呼叫模型都會看到。
- 是 context engineering 的第一步，也是槓桿最大的一段文字：一句好話影響每一輪，一句壞話造成難以 debug 的問題。
- **四種職責**（按需要加，不必全有）：
  1. **Identity**：角色與所處環境（「在終端機裡的 coding assistant」）。
  2. **Capabilities**：有哪些工具/資源，避免模型幻想能力。
  3. **Constraints**：能做/不能做什麼。
  4. **Output conventions**：輸出格式（簡潔、fenced code block 加語言標籤）。
- **Soft constraint vs Hard constraint**：
  - Soft：寫在 prompt 裡，模型可能忽略、新模型可能解讀不同、使用者可能用話術繞過。
  - Hard：寫在 harness 程式碼裡（例如不提供刪除工具），怎麼說都繞不過。關鍵操作要用 hard constraint。

### 02-05 Gaps：bare loop 做不到什麼

| 缺口 | 現象 | 解決的章節 |
|---|---|---|
| 讀寫檔案 | 只能請你貼內容 | File System Layer |
| 執行程式/指令 | 只能描述怎麼做 | Code Execution Layer、Sandbox Layer |
| 長期記憶 | `quit` 後全部忘記（`messages` 只存在記憶體） | File System（agents.md）、Memory & Search（RAG） |
| 可觀測性 | 不知道用了哪個模型、多少 token | Observability & Evaluation（LangSmith / Langfuse） |
| 長時間任務 | 約 25 輪後開始遺忘、重複、矛盾 | Long-running tasks（Ralph loop、plan.md） |

> 模型只能**描述**動作；要**執行**動作必須透過工具。

## Chapter 3：File System Layer

### 03-02 Tool registry + 檔案工具

- **Tool registry**（[registry.py](harness/tools/registry.py)）：通用的工具基礎設施。
  - `Tool`（class）：每個工具的資料格式 — `name`、`description`、`fn`、`schema`。
  - `ToolRegistry`：`register` 登記、`get_schemas` 產生 OpenAI 格式 schema、`dispatch` 執行工具。
  - `dispatch` 會接住所有例外並回傳 `"Error: ..."` 文字，讓模型能看到錯誤並向使用者解釋，而不是讓程式崩潰。
- **`@tool` 裝飾器**：
  - `@tool def f(...)` 等同 `f = tool(f)`，在 **import 時**執行。
  - 自動取函式名當工具名、docstring 當說明、用 pydantic `TypeAdapter` 從型別標註產生參數 schema，然後登記進 registry。
  - `return fn` 讓原函式仍可正常呼叫。
  - 依賴是單向的：filesystem 用 registry，registry 不知道 filesystem。新增工具不必改 registry。
- **檔案工具**（[filesystem.py](harness/tools/filesystem.py)）：`read_file`、`write_file`、`list_dir`、`make_dir`、`delete_file`。
  - 全部限制在 `.workspace/`；`_resolve_path` 擋掉 `../`、絕對路徑等逃逸。這是第一個 **hard constraint**。
  - `delete_file` 暫時不能刪資料夾（Chapter 5 放寬）。
  - 工具一律回傳訊息字串，讓模型知道結果並繼續。
- **接進 agent 迴圈**：
  1. 呼叫模型時帶 `tools=registry.get_schemas()`。
  2. 若回應有 `tool_calls`：先 append 該則訊息 → 逐一 `dispatch` → 結果以 `role: "tool"`（帶 `tool_call_id`）append。
  3. 再呼叫一次模型，取得最終文字回答。
- **模型如何選工具**：由模型自己根據工具的 `name`、`description`、system prompt 和對話內容決定（`tool_choice` 預設 `"auto"`）。所以 **docstring 本身就是 prompt**，寫得清楚模型才選得準。
- **專用工具 vs 通用工具**：拿掉 `write_file` 後模型寫不了檔（它只能輸出文字）；給它 bash 這類通用工具就能做到，但會繞過 `_resolve_path` 的保護，所以後面需要 Sandbox。
- 目前限制：每輪只處理一次工具呼叫（ReAct 迴圈在後面章節）。
