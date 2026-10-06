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
Harness-Engineering/
├── harness/
│   ├── agent.py              # 入口：模型選擇（OpenAI / Kimi）、system prompt、
│   │                         #   session 迴圈 + ReAct loop、step budget、tool trace
│   ├── memory/
│   │   └── agents_md.py      # AGENTS.md 模板建立與載入（session 開始時注入 context）
│   └── tools/
│       ├── __init__.py       # import 各工具模組以觸發登記，對外提供 registry
│       ├── registry.py       # Tool、ToolRegistry（register / get_schemas / dispatch）、@tool
│       ├── filesystem.py     # read_file、write_file、list_dir、make_dir、delete_file
│       │                     #   + _resolve_path：限制在 .workspace/
│       ├── git.py            # git_status、git_diff、git_log、git_commit、git_checkout、git_branch
│       │                     #   + workspace 自動 git init
│       └── bash.py           # bash meta tool：在 workspace 執行 shell 指令（Git Bash on Windows）
│                             #   + allow / deny list policy（預設 deny: rm, sudo, dd）
├── .workspace/               # agent 的工作區與獨立 git repo（自動建立，gitignored）
├── .env.example              # OPENAI_API_KEY / KIMI_API_KEY 範本
├── requirements.txt          # openai、python-dotenv、httpx<0.28
└── CLAUDE.md                 # Claude Code 專案指示
```

**目前的工具（12 個）**：檔案 5 + git 6 + bash 1。

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

### 03-05 Layer 驗證：跨 session 任務

用一個 open-ended 任務驗證 file system layer：「研究並撰寫一頁 Git 歷史文件，研究筆記放 `notes/`，最終成品為 `git-history.md`」。

- **驗證三件事**：
  1. **保存中間產物**：筆記、草稿等在回合之間持續存在的檔案。
  2. **更新記憶**：AGENTS.md 記錄專案背景與進度。
  3. **正確續作**：第二個 session 只靠磁碟上的內容，第一句回應就要連貫。
- **選這個任務的原因**：open-ended（agent 自己拆解步驟）；有自然的中間產物（筆記 ≠ 成品）；有自然的暫停點（寫完筆記就能退出）；不需要程式執行或網路搜尋；而且主題是 Git，正好用 git 工具 commit 進度。
- **結果**：
  | 項目 | 結果 |
  |---|---|
  | 檔案工具（建目錄、寫筆記、整合成品） | 穩定 |
  | Git（commit、log） | 正常 |
  | AGENTS.md 讀取（harness 負責） | 可靠；新 session 第一句就能回答「上次做到哪」 |
  | AGENTS.md 寫入（模型負責） | 會更新，但品質不穩定 |
  | 多步驟指令 | 常需拆成單步，受單輪工具上限限制 |
- **Soft constraint 的實際失效**：
  - 更新 AGENTS.md 時只記了已完成的部分，漏了**尚未完成的段落**，需要額外指示補上。
  - 「成品放在 `git-history.md`」這個關鍵決定沒被寫進 AGENTS.md，續作時需重新告知。
  - 要求清空 Active Tasks 後，「Current task」仍保留舊描述 — 模型沒有嚴格遵守模板結構。
  - 結論：讀取必須是 hard（由 harness 保證）；寫入目前是 soft，品質取決於模型，之後 Memory layer 需要強化。
- **操作技巧**：任務失敗或回 `(no text response - used tools only)` 時，找出沒完成的部分，拆成單一步驟重新下指令。
- **File System Layer 目前具備的能力**：
  - 在磁碟上讀、寫、整理檔案（限制在 workspace 內）。
  - 用 git commit 進度、rollback 錯誤、開 branch 實驗。
  - workspace 與 git repo、AGENTS.md 都自動初始化。
  - Context 分兩層：harness 設計者提供的 system prompt + 使用者/agent 維護的 AGENTS.md。
  - 能完成跨 session 的多階段任務。

## Chapter 4：Code Execution Layer

### 04-01 預定義工具的天花板

- **問題不只是「不能跑程式」，而是預定義工具永遠不夠用。** 工具只涵蓋 harness 設計者預想到的需求，遇到沒想到的任務就卡住：
  | 使用者需求 | 只有現有工具時 | 有 shell 時 |
  |---|---|---|
  | `notes/git-origins.md` 有幾行？ | 整份讀進 context 再手動數 | `wc -l` |
  | 哪些檔案提到 BitKeeper？ | list → 逐一 read → 手動搜尋 | `grep -rl BitKeeper` |
  | 系統的 Python 版本？ | 只能猜 | `python --version` |
  | 抓 GitHub 上 Git 專案的 README | 做不到（沒有網路） | `curl` |
  | 執行剛寫好的 script | 做不到，無法驗證輸出 | `python script.py` |
- 對 coding agent 來說，不能執行程式碼是根本缺陷。
- **「缺什麼補什麼」是跑步機**：每個新任務都會暴露新缺口（解壓縮、JSON 轉 CSV、編譯 TypeScript…），永遠追不完。而且工具越多，schema 越佔 context、越分散模型注意力 — context 是有限資源。
- **業界兩種解法**（都成功，不是誰比較好）：
  | | 許多專用工具（Cursor） | 少數通用 primitive（Claude Code） |
  |---|---|---|
  | 工具 | code indexing、semantic search、symbol lookup、file editing… | Read、Edit、Bash、Glob、Grep 等少數幾個 |
  | 優點 | **Precision**：每個工具針對常見 workflow 最佳化 | **Completeness**：天花板就是 shell 的天花板 |
  | 缺點 | 天花板持續升高，靠 terminal access 補洞 | agent 得自己想出解法 |
- Cursor 也提供 terminal access — 專用工具處理常見 workflow，shell 當作逃生口。
- **本專案走 Claude Code 路線**：coding agent 需要高度自主，bash 直接移除工具天花板。**Code 是 meta tool** — agent 能用它組出任何需要的工具。
- 選型取決於產品：workflow 固定、需要保守受控的產品，專用工具 + 受控 shell 仍是好選擇。

### 04-02 Code as a meta tool

- **Meta tool**：讓 agent 在 runtime **自己建構其他工具**的工具。需要時當場產生程式碼 → 執行 → 取得結果 → 丟棄，不寫入檔案、不持久化。
- 設計問題從「agent 該有哪些工具？」（答案趨近無限）轉成「**最小的一組通用 primitive，能讓 agent 建構出任何東西**是什麼？」
- **為什麼選 Bash**（候選還有 Python runner、跨語言 code runner）：
  1. **Universality**：Mac、Linux VM、Docker container、CI runner 都有 bash 或相容 shell，不需逐環境設定。
  2. **系統工具**：`grep`、`find`、`curl`、`awk`、`sed`、`sort`、`uniq`、`wc`、`tar`… 經過數十年打磨、快且可靠，免費取得；系統新裝的工具也自動可用。
  3. **語言直譯器**：裝了 Python 就能跑 Python，裝了 Node 就能跑 Node。Python runner 只是 bash 能力的子集。
  4. **Composability**：pipe、redirect、command substitution、背景執行、指令串接 — 少量工具組合出近乎無限的能力。
  5. **模型本來就精通**：訓練資料含大量 shell（Stack Overflow、README、man page、CI 設定）。自訂語法的 meta tool 反而要模型每次從文件學。
- **Runtime tool synthesis 範例**：「`Linus` 在所有筆記中出現幾次？」
  - 沒有 meta tool：`list_dir` → 逐檔 `read_file` → 模型自己數 → 加總。工具呼叫多、context 被檔案內容塞滿，而且**模型數數不可靠**（同 strawberry 問題）。
  - 有 bash：一行 `grep -c Linus notes/*.md | awk -F: '{s+=$2} END {print s}'`，只回傳一個數字。
  - 沒有「跨檔計數」工具，以後也不會有 — agent 當場用 bash primitive 組出來。
- **加上 bash 後 agent 行為的改變**：
  1. **開始探索**：寫 script → 執行 → 觀察輸出 → 修 bug → 重複，形成 propose → execute → observe → adjust 循環。
  2. **失敗模式改變**：錯誤（stderr、exit code、`No such file or directory`）變得**可觀察**，agent 能依回饋換方法。
  3. **回饋迴圈閉合**：action → observation → reasoning → next action。真正重複執行需要 ReAct loop，bash 提供的是讓迴圈有意義的回饋。
- 環境備註（Windows）：`PATH` 上的 `bash` 是 WSL 啟動器（`C:\Windows\System32\bash.exe`），本機 WSL 只有 `docker-desktop` distro，不能用；實作時應指定 Git Bash（`C:\Program Files\Git\bin\bash.exe`，內含 GNU grep/awk/wc）。

### 04-03 Bash tool

- **設計決策**：
  | 項目 | 決策 | 理由 |
  |---|---|---|
  | 執行方式 | 把模型產生的指令字串交給 shell 直接執行（`bash -c "<command>"`） | pipe、redirect、chaining 原生可用。git 工具用 argument list 是因為只需要 git 本身，不需要 shell |
  | 工作目錄 | `.workspace/` | 和檔案、git 工具一致 |
  | Timeout | 60 秒（git 為 10 秒） | 要容納 `pip install`、`curl`、`git clone` |
  | 輸出 | stdout 為主，stderr 非空時附加在後（`--- stderr ---`） | 程式常在兩個 stream 都輸出有用資訊；git 只取其一 |
  | 錯誤標示 | `[bash exited with code N]`、`[command timed out after 60s and was killed]` | 方括號標示 **harness 產生的資訊**，和 shell 輸出區分；否則模型只看 stdout 可能誤判成功 |
  | 工具名稱 | `bash` | 符合模型對 shell 的既有認知 |
- 安全性：直接執行任意 shell 字串是風險，之後以 allow list / deny list 處理。目前只有工作目錄在 workspace，**路徑並未被限制**（`cd ..` 可離開）— 和 `_resolve_path` 的 hard constraint 不同。
- **System prompt 規則**：
  - 專用工具優先：讀檔用 `read_file` 不用 `cat`，commit 用 `git_commit` — 更安全、更快、更容易追蹤。
  - 專用工具不涵蓋時才用 bash：執行 script、系統工具（`grep`/`curl`/`wc`）、`pip install`、探索環境（`ls`/`pwd`/`which python`）。
  - 每次 bash 呼叫都是新 shell，`cd` 不會延續到下一次呼叫。
- 實測行為：`write_file` 寫 script → `bash` 執行 — 模型會遵守「專用工具優先、bash 補位」。但「寫完再執行」仍需兩句指令（單輪工具上限）；action → observation 的循環還是由使用者推動，要靠 ReAct loop 交給 agent。
- 實作細節（Windows）：
  - `subprocess.run(..., shell=True)` 在 Windows 用的是 `cmd.exe` 而不是 bash，所以改為明確呼叫 `[BASH, "-c", command]`。
  - `PATH` 上的 `bash` 是 WSL 啟動器，因此 `_find_bash()` 從 `git.exe` 位置推導 Git Bash（`<Git>\bin\bash.exe`）；非 Windows 用 `shutil.which("bash")`。
  - bash 中的 `python` 取決於 `PATH`。未啟用 venv 時會打到 Windows Store 的 python 捷徑（exit code 49），因此把 harness 自己的 Python（`sys.executable` 所在目錄）放在 bash `PATH` 最前面。
- **Tool trace**：每次工具呼叫在終端機印出 `[tool] name(args)` 與原始結果（最多 20 行）。原本工具結果只進 `messages`，使用者只看得到**模型的轉述** — 轉述可能出錯或編造（例如宣稱更新了 AGENTS.md 實際沒有）。trace 讓實際執行內容可驗證，也是 observability 的雛形。

### 04-04 ReAct loop

- 單輪工具呼叫改成 **ReAct loop**：reason（呼叫模型）→ act（執行工具）→ observe（結果寫回歷史）→ 重複，直到模型回傳純文字。兩層迴圈：外層是使用者 session，內層是單一 turn 的 ReAct loop。
- **離開 ReAct loop 只有兩種方式**：
  1. 模型回應沒有 `tool_calls` → 已有最終答案。
  2. 達到 **step budget** → 強制收尾。
- **Step budget（`STEP_BUDGET = 25`）**：每個 user turn 最多 25 輪工具呼叫，避免無限迴圈與 API 費用失控。
  - 達到上限時注入一則 **synthetic system message**，要求模型不再呼叫工具，改為回報：(1) 這輪完成了什麼 (2) 還剩什麼 (3) 使用者下一步該問什麼 — 讓工作能延續。
  - 實作細節：budget 檢查放在執行工具**之前**，被擋下的 tool call 不寫入歷史（否則會留下沒有對應結果的 tool call）；收尾呼叫帶 `tool_choice="none"`，保證回傳文字；budget 數字由常數帶入，不寫死在訊息裡。
- **移除 `(no text response - used tools only)` 佔位字串**：loop 結束後 `content` 應該一定有文字；若為空代表異常（API edge case、loop 終止邏輯 bug、額度用完），直接 `raise` — **silent fallback 會掩蓋真正的問題**。
- **效果**：
  - 「寫 `fib.py` → 執行 → 顯示輸出」一句指令完成。
  - 缺少資訊時（例如 `config.json` 不存在），agent 會在探索後主動詢問使用者，而不是卡住或亂做。
  - 「建立含 `pyproject.toml`、`src/`、模組的專案 → 執行驗證 → commit」一次完成，混用 file system、bash、git 工具。
  - 使用者不再需要一步步牽著 agent 走到終點 — action → observation 循環由 agent 自己推動。
- 之前筆記中「單輪工具上限」相關的限制（03-02 ~ 04-03）至此解除。

### 04-05 Bash policy：allow list / deny list

- bash 能做任何 shell 做得到的事，所以在它之上加一層**指令政策**，在執行前檢查。
- **三個常數**（[bash.py](harness/tools/bash.py)）：
  | 常數 | 意義 | 空集合時 |
  |---|---|---|
  | `ALLOW_LIST` | 只允許這些指令 | 不限制（不在 deny list 的都允許） |
  | `DENY_LIST` | 禁止這些指令 | 不禁止任何指令 |
  | `CHAIN_SEPARATORS` | `&&`、`\|\|`、`;`、`\|`、`&`、換行 | — |
- **比對方式**：用分隔符號把指令切成 segment，取每段的**第一個 token**（指令名稱）比對。所以 `cd notes && rm -rf x` 會檢查 `cd` 和 `rm`，不會因為開頭是安全指令就放行整串。
- **Deny 優先（fail closed）**：同一個指令同時在兩個 list 時拒絕執行，和 AWS IAM、防火牆、Linux 權限的慣例一致。
- **檢查在 `subprocess` 之前**：被拒絕時完全不啟動 shell、沒有副作用，直接回傳 `[policy: 'dd' is on the deny list; refusing to run]` 給模型（方括號 = harness 訊息），讓它改用別的做法或告訴使用者自己執行。
- 使用情境：
  - **寬鬆模式**：allow 空、deny 列危險指令（目前預設 `{"rm", "sudo", "dd"}`；刪檔改用受 workspace 限制的 `delete_file`）。
  - **鎖定模式**：allow 只列已知工具（如 `ls`、`cat`、`wc`、`grep`、`python`），其他一律拒絕。
- 實作細節：`_first_token` 會跳過 `(`、`{` 與 `VAR=value` 前綴、去掉路徑，所以 `(rm x)`、`FOO=1 rm x`、`/bin/rm x` 都會被認成 `rm`。
- **已知限制 — 這是字串比對，不是真正的隔離**：
  - 擋不到包在其他指令裡的動作：`echo $(rm x)`、`` `rm x` ``、`bash -c "rm x"`、`xargs rm`、`python -c "import shutil; shutil.rmtree('x')"`。
  - 允許 `python` 就等於允許任意程式碼。
  - 真正的防護要靠 OS 層隔離 → Sandbox layer（Docker）。policy 是第一道防線，不是最後一道。

