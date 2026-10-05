# Agent Harness

A from-scratch coding-agent harness, built layer by layer: loop, tools, execution, memory, observability.

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
├── memory/
│   └── agents_md.py    # AGENTS.md：跨 session 記憶的載入與模板
└── tools/
    ├── registry.py     # 工具登記處：Tool、ToolRegistry、@tool
    ├── filesystem.py   # 檔案工具，限制在 .workspace/ 內
    └── git.py          # git 工具，.workspace/ 自動初始化為 repo
```

---

# AI Engineering Notes

## Chapter 2：Bare Loop

### 02-01 Project scaffold

- 依賴刻意保持最小：`openai`、`python-dotenv`。
- Gotcha：`openai==1.50.0` 與 `httpx>=0.28` 不相容（`proxies` 參數被移除），需 pin `httpx<0.28`。

### 02-02 Bare loop

- **Agent = 包在無狀態模型外面的 while loop。**
- 模型本身沒有記憶；「記憶」來自每次呼叫都**重送整段對話歷史**（`messages` list）。
- 迴圈步驟：讀輸入 → append user 訊息 → 帶完整歷史呼叫模型 → append assistant 回覆 → 印出 → 回到開頭。
- user 訊息和 assistant 回覆**都要** append，少一個歷史就不完整。

### 02-03 Kimi backend

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

| 缺口 | 現象 | 對應的 layer |
|---|---|---|
| 讀寫檔案 | 只能請使用者貼內容 | File System Layer |
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
  - `delete_file` 暫時不能刪資料夾（之後放寬）。
  - 工具一律回傳訊息字串，讓模型知道結果並繼續。
- **接進 agent 迴圈**：
  1. 呼叫模型時帶 `tools=registry.get_schemas()`。
  2. 若回應有 `tool_calls`：先 append 該則訊息 → 逐一 `dispatch` → 結果以 `role: "tool"`（帶 `tool_call_id`）append。
  3. 再呼叫一次模型，取得最終文字回答。
- **模型如何選工具**：由模型自己根據工具的 `name`、`description`、system prompt 和對話內容決定（`tool_choice` 預設 `"auto"`）。所以 **docstring 本身就是 prompt**，寫得清楚模型才選得準。
- **專用工具 vs 通用工具**：拿掉 `write_file` 後模型寫不了檔（它只能輸出文字）；給它 bash 這類通用工具就能做到，但會繞過 `_resolve_path` 的保護，所以後面需要 Sandbox。
- 目前限制：每輪只處理一次工具呼叫，待 ReAct loop 解決。

### 03-03 Git versioning

- **版本控制是 harness primitive，不是 prompt 建議。** 只有檔案工具時寫入無法復原，每個錯誤都是永久的 → agent 變得保守、緩慢。有了 git：先 commit 穩定狀態 → 開 branch 嘗試 → 錯了就 rollback。版本控制擴大了 agent 敢嘗試的範圍。
- **三種能力、六個工具**（[git.py](harness/tools/git.py)）：
  | 能力 | 工具 |
  |---|---|
  | Commit（存檔點） | `git_status`、`git_diff`、`git_commit` |
  | Rollback（回到過去） | `git_log`、`git_checkout` |
  | Branching（實驗） | `git_branch`、`git_checkout` |
- **刻意不做的**：push/pull/fetch（遠端）、merge（衝突需要和使用者雙向溝通）、stash、rebase。等真的需要再加。
- **直接呼叫 git binary（`subprocess`），不用 GitPython**：
  1. 行為和開發者在終端機用的一樣。
  2. 不增加依賴，harness 保持輕量。
  3. 模型對 git 原始輸出的熟悉度遠高於 GitPython 物件。
- `_run_git`：在 `.workspace/` 執行、10 秒 timeout（避免卡死）、非 0 exit code 不 raise，而是把輸出回傳給模型。
- **自動 `git init`**（import 時的 side effect），設定 user 為 `agent`、預設分支 `main`。和自動建立 workspace 同理：做成 hard constraint，不靠模型記得。
- System prompt 加入 git 習慣（soft）：常做小 commit、危險操作前先 commit、commit 訊息寫 what + why、嘗試替代方案先開 branch。
- 專案根目錄的 `.gitignore` 要排除 `.workspace/`，避免 workspace 的 `.git` 和外層 repo 衝突。
- **限制：一輪只能一次工具呼叫。** 「寫檔然後 commit」需要多次來回（write → 看結果 → commit），目前做不到；第二次回應若又是 tool call，`content` 為 `None`，暫時以 `(no text response - used tools only)` 代替。ReAct 迴圈會解決。（同一次回應裡的多個平行 tool call 已由 for loop 處理。）
- 實作細節：`git_diff` 的 path 也經過 `_resolve_path` 檢查；`git_checkout`/`git_branch` 拒絕 `-` 開頭的名稱，防止被當成 git 選項（如 `--orphan`）。

### 03-04 Cross-session memory：AGENTS.md

- **AGENTS.md**：給 coding agent 的標準靜態指令檔，記錄某個專案中需要跨 session 保留的資訊。session 開始時讀入，過程中/結束時由 agent 更新。
- **The harness reads, the model writes**：
  | 動作 | 誰負責 | 性質 | 原因 |
  |---|---|---|---|
  | 讀取 | harness，每個 session 開始時自動載入 | Hard | 必須保證發生，不能靠模型記得去讀 |
  | 寫入 | 模型，用 `write_file` 更新 | Soft | 「什麼值得記住」需要模型判斷，難以寫成規則 |
- [agents_md.py](harness/memory/agents_md.py)：檔案放在 `.workspace/AGENTS.md`；不存在時以模板建立（import 時的 side effect）。
- **模板結構**：Project Context / Conventions / Decisions / Gotchas / Active Tasks。每段以括號提示說明該寫什麼，由模型替換成真實內容；Active Tasks 完成後要清掉，避免模型以為工作仍在進行。
- **注入方式**：在 `messages` 開頭放**兩則 system message** — system prompt 在前、AGENTS.md 內容在後。模型會當作一份連續的 context 讀；分開放是為了在 observability 工具中能分辨不同層，方便 debug。
- System prompt 加入 AGENTS.md 維護規則：保留既有段落結構、更新相關段落而非整份覆蓋、把括號提示換成實際內容。
- **觀察到的 soft constraint 失效**：要求「更新記憶檔」時，模型可能另建一個檔案（如 `project_memory`）而不是寫入 AGENTS.md — prompt 指示不保證被遵守。
- **再次撞上單輪工具上限**：更新 AGENTS.md 需要先 `read_file`（看現有結構）再 `write_file`，一輪只做得到第一步，回覆變成 `(no text response - used tools only)`；需要拆成兩句指令。ReAct loop 會解決。
- **為什麼 `load_agents_md` 不是 tool**：tool 由模型決定要不要呼叫，不保證發生；讀記憶必須保證發生，所以由 harness 直接呼叫並注入 context。寫入則不需要新工具，AGENTS.md 只是 workspace 裡的普通檔案，模型用 `read_file`/`write_file` 即可。原則同自動建立 workspace、自動 `git init`：**一定要發生的事寫在程式碼裡**。
- **預先載入的取捨**：
  - 好處：模型回答第一句前就有專案背景；不消耗工具呼叫（在單輪工具上限下尤其重要）；放在 `messages` 中，整個 session 每一輪都有效。
  - 代價：每次呼叫都重送，檔案越大 token 成本越高；只在 session 開始讀一次，中途更新要到下個 session 才重新載入（但對話歷史已包含該次寫入）；檔案會持續成長，因此只適合放精簡、長期有效的資訊，大量記憶交給之後的 RAG。
- 效果：退出後重開 session，agent 能直接回答「在做什麼專案」「用什麼命名慣例」— bare loop 的長期記憶缺口開始被補上。完整的記憶系統（RAG、記憶工具）留給 Memory & Search layer。
