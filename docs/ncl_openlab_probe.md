# 國圖 OPEN LAB 音樂創作室：使用時段預約輔助（唯讀）

此工具在 `feat/ncl-openlab-booking` 支線，**不接入 Tickets Hunter 主迴圈**，也不修改其他售票平台。

## 已實作

- 以台灣 UTC+8 計算預設目標日期（今天 +7 日）
- 限定國圖官方主機 `spms.ncl.edu.tw`
- 只讀取目前網頁中的目標日期、音樂創作室、三個時段的可見 DOM 候選元素
- 使用者自行登入；不紀錄密碼、Cookie、會員資料
- 不點擊、不送出、不刷新、不輪詢；沒有自動預約功能

**重要：** 截圖只證明一般預約流程；音樂創作室當時已滿，尚未驗證該空間的真實可預約 DOM、00:00 釋位秒數及網站自動化規則。偵測到文字不等於確認有空位。

## 安裝與執行（Windows PowerShell）

從儲存庫根目錄：

```powershell
pip install -r requirement.txt
python src/ncl_openlab_probe.py --date 2026-11-11 --slot 09:00-12:00
```

啟動後在新瀏覽器手動登入國圖，進入「多媒體創意實驗中心」，回終端按 Enter。程式只會輸出目標候選節點的標籤、可否點擊及可見文字摘要，**不包含預約成功的保證**。

不帶 `--date` 時，預設使用台灣當日 +7 天；不帶 `--slot` 時檢查所有標準時段。

## 離線驗證

```powershell
python -m unittest discover -s tests -p "test_ncl_openlab_probe.py"
python -m py_compile src/ncl_openlab_probe.py src/ncl_openlab_guard.py
```

## 第二刀：防誤選檢查（已加入）

- 新增 `src/ncl_openlab_guard.py`：只接受正確國圖網域、指定日期、**音樂創作室**、指定時段
- 每個目標必須唯一、文字吻合、顯示未禁用、可互動或已選取；缺少、重複、禁用皆 `BLOCKED`
- 即使三項全部吻合，只能得到 `OBSERVED_ONLY`，不能據此判定空位、點擊或送出
- 原偵測器會輸出 `dry_run_assessment`；不產生任何預約操作
- 新增十個防誤選離線案例：`python -m unittest discover -s tests -p "test_ncl_openlab_*.py"`

## 後續開發的進入條件

取得實際 DOM 偵測結果後，才能建立精準且 fail-closed 的日期/空間/時段選擇邏輯。未確認網站服務條款及 DOM 前，不做自動送出、CAPTCHA 繞過或高頻重試。

## 第三刀：改為「時段」優先，不是座位

固定空間為「音樂創作室」，只對預約 **使用時段** 排序（不涉及座位、座號或房間內位置）。

```powershell
# 第一優先晚間，其次下午；逗號後不加空白也可以
python src/ncl_openlab_probe.py --slots 17:00-20:00,13:00-16:00

# 僅查看上午時段（與原 --slot 相容）
python src/ncl_openlab_probe.py --slot 09:00-12:00
```

輸出 `time_slot_priority_plan`，包含依使用者指定優先序排列的三小時使用時段，
`first_observed` 只代表目前頁面找到的第一個候選時段，**不表示已滿/可預約狀態已獲官方確認**。
若時間文字重複、被禁用或空間不符，該時段不會成為候選。
程式仍不會點選、預約、輪詢，也不儲存登入資料。

離線測試：`python -m unittest discover -s tests -p "test_ncl_openlab_*.py"`

**尚未完成：** 需從國圖音樂創作室實際預約畫面的 DOM 確認「已滿 / 可預約」的欄位，
才能安全地轉為可執行的時段選取器。

## 第四刀：時段介面狀態證據（唯讀）

時段報告新增 `time_states`，每個時段皆附 `state`、`evidence`，而且
`availability_verified=false`、`can_book=false`。分類：

| state | 意義 |
|---|---|
| `DISABLED_UI_HINT` | 目標時段的 DOM 候選元素呈禁用訊號，**不等於正式額滿** |
| `CANDIDATE_UNVERIFIED` | 找到單一可互動候選元素，**不等於可預約** |
| `NOT_DISPLAYED` | 沒找到目標時段 |
| `AMBIGUOUS` | 同一時段有多個候選，禁止猜測 |
| `UNKNOWN` | 空間、日期、網域、控制狀態等不足以判讀 |

這些都是使用者目前開啟頁面的**視覺介面證據**，不是國圖後端的真實剩餘名額。
不可將畫面出現時間、可點擊、禁用樣式直接當作成功率或開放名額。
不會自動點選、送出、重試或搶佔時段。

此刀的離線測試：`python -m unittest discover -s tests -p "test_ncl_openlab_*.py"`；
真實可預約狀態需要從官方頁面元素進一步驗證。

## 第五刀：擷取真實時段 DOM 證據（唯讀）

執行原本的 `python src/ncl_openlab_probe.py --slots 09:00-12:00,13:00-16:00`，手動登入、進入
音樂創作室的時段畫面後按 Enter，程式會額外列出 `sanitized_time_dom_evidence`。

這份資料只包含固定時段字串、候選數、控制項標籤、禁用/選取訊號，以及白名單
狀態詞（例如「額滿」「可預約」）是否出現在同一時段附近。混入其他時段文字的容器不
使用狀態詞，以免把別的時段的狀態誤認為自己的狀態。

**隱私與安全**：不輸出網頁 HTML、任意使用者文字、帳號、密碼、Cookie、會員資料；
未通過 `validate_evidence` 會停止，不提交預約、不自動刷新、不連續輪詢。
這是「取證工具」，不宣稱已確認網站的滿位/可預約語意；仍需實機輸出與畫面對照。

離線測試：`python -m unittest discover -s tests -p "test_ncl_openlab_*.py"`；
另外執行 `python -m py_compile src/ncl_openlab_probe.py src/ncl_openlab_evidence.py`。

## 第六刀：可選擇輸出匿名診斷 JSON

要實際核對國圖音樂創作室的時段畫面，在 Windows PowerShell 於專案根目錄執行：

```powershell
python src/ncl_openlab_probe.py --save-evidence
```

程式會打開瀏覽器。請**手動登入**並進入國圖「音樂創作室」的時段選擇畫面，
回到終端按 Enter，工具才會做一次唯讀擷取。

成功輸出固定檔名 `ncl_openlab_evidence.json`（專案根目錄）：
只包含白名單的日期/空間/時段、控制項標籤、禁用訊號與固定狀態詞。
檔案已加入 `.gitignore`，不會被一般 `git add .` 收錄。
使用排他建立模式，檔案已存在時不覆蓋，避免不同日期證據混在一起。

- 原本不加 `--save-evidence` 的行為完全保留，不寫入任何檔案。
- 仍不自動選時段、不提交預約、不繞過驗證、不重試或輪詢。
- `UNVERIFIED_DOM_ONLY` 表示**只是畫面證據，並非國圖後端認證的剩餘名額**。
- 分享輸出前仍請自行核對，勿上傳含個資的完整網頁或開發者工具紀錄。

離線單元測試：
`python -m unittest discover -s tests -p "test_ncl_openlab_export.py"`。

## 第七刀：依實際國圖 HTML 變更唯讀辨識器

使用者在國圖畫面的 DevTools 確認（僅供 DOM 契約比對）：

- 空間選項：\`div.space-box1\`；已選為 \`selected\`。側邊「音樂創作室」標題不算空間選項。
- 時段選項：\`div.time-box[data-param1="HH:MM-HH:MM"]\`；\`data-param1\` 是實際時段文字。
- 觀察到已被占用的時段包含 \`class="time-box disabled reserving"\`。
- 觀察到仍可選的另一房間時段只有 \`class="time-box"\`，但這不是後端確認的空位。
- 日期、空間必須在結構化掃描中呈 \`selected\`，否則拒絕計入有效目標。
- 不使用背景色或 \`data-param3="true"\` 作為可預約判據。

\`ncl_openlab_probe.py\` 現在用結構化 DOM 選擇器找目標日期、\`space-box1\`
與精確 \`data-param1\` 時段；\`ncl_openlab_evidence.py\` 擷取固定白名單
\`class_hints\`（time-box、disabled、reserving 等），不記錄整頁文字與私人資料。
另加 \`tests/test_ncl_openlab_real_dom_contract.py\` 離線回歸案例。

**注意**：音樂創作室的三小時時段仍是唯一正式目標；「個人直播室」的一小時時段
僅作為外觀與 HTML 契約對照。禁用、可點選與預約成功是不同概念。
整個工具仍為單次唯讀檢查，不會點時段、不會送出、不會查驗證碼或輪詢。

更新本機開發分支後，用
\`.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_ncl_openlab_*.py"\`
離線複驗。需再到國圖相同選時畫面完成一次真實 DOM 驗證，才能宣稱實機通過。

## 第八刀：修正音樂創作室 time-box2 的真實 DOM

依據 **音樂創作室 2026-11-11** 的使用者提供 HTML，
三個三小時時段屬於 `div.time-box2[data-param1]`，
不同於個人直播室的一小時 `div.time-box[data-param1]`。

- 兩種時段類別均用精確 `data-param1` 查詢；正式目標仍只有音樂創作室的三小時時段。
- `disabled reserving` 是 **介面禁用訊號**；三個時段都禁用時不可推薦、不可預約。
- `data-param2="216"`、`data-param3="false"` 不用作判斷是否有名額，也不輸出到匿名證據。
- `ncl_openlab_evidence.py` 的 `class_hints` 允許 `time-box2`，同時保留既有白名單與隱私限制。
- 新增兩個回歸測試，涵蓋真實三小時 HTML 契約與全禁用 fail-closed 行為。

本刀不啟用自動點擊、登入、CAPTCHA 處理、提交或輪詢。

Windows 手動確認：在專案資料夾先 `git pull --ff-only`，再執行
` .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_ncl_openlab_*.py" -v `。
離線測試通過後，再於國圖已選日期／音樂創作室／三個時段畫面執行單次唯讀探測。

## 第九刀：日期方塊 `date-box selected` 實機契約

使用者於 2026-11-11 音樂創作室畫面的開發者工具中確認：

```html
<div class="date-box selected" id="date7">
  11/11<br><span class="weekWords">(三,Wed)</span>
</div>
```

上一版已能找到日期 1 筆、音樂創作室 1 筆與三個 `time-box2` 時段，
但曾回報 `DATE_NOT_SELECTED`。日期辨識因此改為只搜尋
`.date-box` 元素本身，以其開頭日期文字精確比對；
仍要求 **同一元素本身具有 selected**，而非誤用星期的 `span` 或其他祖先。
保留原 `DATE_NOT_SELECTED` fail-closed 防護；不會自動選日期、點時段或提交。

更新後需執行全部 `test_ncl_openlab_*.py`，再做一次國圖唯讀實機複驗，
確認禁用時段回報 `SLOT_DISABLED_OR_UNKNOWN` 而不是 `DATE_NOT_SELECTED`。

## 第十刀：保留 `book` 為唯讀 UI 提示

2026-11-11 其他空間（**個人直播室 P03**）真實可選外觀 DOM：

```html
<div class="time-box book" id="timebox0" data-param1="09:00-10:00" data-param2="1" data-param3="true">09:00-10:00</div>
```

與音樂創作室三小時時段 `time-box2 disabled reserving` 不同。
新增 `book` 至 `sanitized_time_dom_evidence.times[].nodes[].class_hints`
固定白名單（及對應驗證器），**僅供診斷**：
不代表 `availability_verified=true`，也不保證音樂創作室使用相同正向狀態。
不保存 `data-param2` 或 `data-param3`，不新增其他房間的一小時時段至目標清單。

新增回歸案例：允許 `book` 診斷 token 但仍不預約；`book` 與
`disabled reserving` 同時存在時，禁用訊號優先，始終 `BLOCKED`。
`main` 未變、無自動選取、提交、重新整理、輪詢或驗證碼操作。

更新本機後執行 `python -m unittest discover -s tests -p "test_ncl_openlab_*.py" -v`，
再到國圖音樂創作室確認三個禁用時段仍輸出 `disabled/reserving/time-box2`。

## 第十一刀：最後「預約」頁面唯讀驗收入口

國圖流程有「選日期／空間／時段 → 下一步 → 預約」兩個不同階段。
目前**只由使用者手動前往最後頁面**，新增單次唯讀檢查，不會點擊最後的「預約」。

```powershell
.\.venv\Scripts\python.exe src\ncl_openlab_checkout_probe.py --date 2026-11-11 --slot 09:00-12:00
```

啟動後在新瀏覽器手動登入並走到最後「預約」畫面，停下，不按最終預約。
回終端按 Enter，程式只輸出 `checkout_readonly_assessment`，包含：

- 固定白名單的「下一步」「預約」「確認預約」「送出預約」「完成預約」可見數量與禁用數量
- 本頁面仍可觀察到的已選日期、房間、三小時時段是否各唯一
- `OBSERVED_ONLY` / `BLOCKED` 診斷，不包含任何預約成功的推論

**跨頁不假設上下文會保留**：如果最後頁面已移除 `date-box`、`space-box1`
或 `time-box2`，即使出現「預約」按鈕也回報 `BLOCKED`
(`FINAL_CTA_VISIBLE_CONTEXT_UNVERIFIED`)；不能從 P03 的測試推論音樂創作室成功。
輸出不讀取姓名、手機、帳號、欄位值、驗證碼、表單資料或完整網頁 HTML；
永遠 `can_click=false`、`can_submit=false`、`booking_verified=false`。

`tests/test_ncl_openlab_checkout.py` 新增 13 項獨立測試，核對網域、
日期格式、時段白名單、CTA 缺失／禁用、個人直播室參考情境、
不信任的輸入及無私密欄位外洩。

**重要**：尚未有音樂創作室正向可預約頁面的真實 DOM 證據，也未取得最後
「預約」按鈕的 outerHTML；因此這是一個可驗收的安全診斷入口，
不是已實作自動預約或送出。若網站服務條款禁止自動化，仍須遵守。

## 第十二刀：本人登入後的單次自動預約（明確選擇啟用）

新增 `src/ncl_openlab_autobook.py`，完全使用站上可見 Chrome UI，
不是呼叫未公開的後端預約 API。僅限 **音樂創作室**、指定日期及三小時
`09:00-12:00`、`13:00-16:00`、`17:00-20:00`。
使用者自行登入並進入多媒體創意實驗中心的日期畫面，之後依序自動：

1. 台北目標時間到點後**最多刷新一次**（非高頻輪詢）；
2. 找到且只點唯一、未禁用的 `.date-box` 目標日期；
3. 找到且只點唯一、未禁用的 `.space-box1` 音樂創作室；
4. 依指定時段優先順序尋找唯一 `.time-box2[data-param1]`，
   僅接受 `book` 正向 UI 標記且不含 `disabled`、`reserving`；
5. 確認所選日期、空間、時段均為 `selected`，才點一次「下一步」；
6. 最終頁需同時呈現完整日期、音樂創作室、確切時段，且有唯一
   未禁用的「預約」按鈕，才會在**明確傳入 `--auto-submit`** 時按一下；
7. 最後檢查畫面是否顯示「預約成功」及相同日期、空間、時段；
   未確認時回報 `SUBMITTED_SUCCESS_UNVERIFIED`，**絕不補點第二次**。

**使用例（以下日期只是示例，不代表必有名額）：**

```powershell
# 當日測試完整流程：不加 --auto-submit 時停在最終按鈕前
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --date 2026-11-11 --now

# 真正單次自動預約，預設在目標使用日往前七日的台北午夜嘗試：
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --date 2026-11-12 --slots 09:00-12:00,13:00-16:00,17:00-20:00 --auto-submit
```

以 `2026-11-12` 為例，排程時間為 **2026-11-05 00:00 台北時間**。
必須**提前 15 分鐘內**啟動且保持程式與 Chrome 開啟，登入後進到日期畫面按 Enter。
因網站只官方公布「使用前七日開放」，**確切午夜秒數尚非官方驗證規則**；
腳本採先前使用者觀察的 00:00 作預設，若官網調整應停止而非高速嘗試。

想立刻嘗試（非開放當下）可加 `--now --auto-submit`，但這將**真的提交**
任何符合防護條件的時段。沒有 `--auto-submit` 不按最後預約。

**邊界**：不得使用別人的借閱證；不得超出官方每人每週／每日限制；
沒有 CAPTCHA 解題或繞過驗證、沒有高速輪詢或重試提交、
沒有多帳號操作、沒有儲存帳密、姓名、電子郵件或證號。
如果最後頁面的房名、日期、時段不一致，停止。
目前只有個人直播室的可選 DOM 作為正向類別參考，
音樂創作室正向可用的 `time-box2.book` 與最終按鈕尚**未實機通過**，
因此不保證搶位成功。網站若禁止自動化，應停用此模式。

新增 `tests/test_ncl_openlab_autobook.py` 17 個離線安全測試，
執行全部 `test_ncl_openlab_*.py` 進行驗收。

## 第十三刀：P03 個人直播室「真實送出」測試模式

此模式與原「音樂創作室」共用 **單次** 實機預約引擎，
但使用互不混用的目標清單及 DOM 選擇器：

- `--room music`（預設）只找「音樂創作室」、三小時 `time-box2`。
- `--room p03` 只找 **個人直播室 P03**（以 `space-box1` 起始完整 P03 房號辨識）
  與指定的一小時 `.time-box[data-param1]`。
- P03 **必須**指定單一 `--slot`，不能選別間直播室、不能使用三小時時段。
- 唯有 `book` 正向 UI 訊號且沒有 `disabled/reserving` 才會嘗試。
  這不代表官方確認名額，真正以預約結果頁驗證。
- 程式須看到目標日期與 P03 已選、目標時段已選，才按「下一步」；
  最終頁須同時包含 **完整日期、P03、個人直播室、時段** 才能按一次「預約」。
  頁面使用直排中文字時，僅將空白正規化來比對，不讀取／儲存表單個資。
- `--auto-submit` 明確授權**真的送出一次**。送出後**不重送**；
  保持瀏覽器開啟供確認，手動按 Enter 才結束。

**範例（如已使用過該時段或無實際需求，勿重複預約）：**

```powershell
# 11/11 P03 下午 13:00–14:00，立刻嘗試真正送出一次
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --room p03 --date 2026-11-11 --slot 13:00-14:00 --now --auto-submit
```

開啟瀏覽器後手動登入、進入多媒體創意實驗中心日期畫面，按 Enter
即可開始流程，無需人工點選 P03 或「預約」。如日期未開放、被禁用、
房號不符、時段未開放、最終頁資訊不符則自動停止。
**尚未實機驗證 P03 這條真實自動送出路徑。**
此模式不繞過驗證碼、不儲存個資、不高速刷站。

截至 2026-11-04 官方規定：7 日內其他同一空間最多 4 個時段、
每天最多 2 個時段、同一時段僅供預約一個空間或設備；
執行前請自行確認未超過限制：
https://www.ncl.edu.tw/regulations/0Q090387295603483412

P03 新增 `tests/test_ncl_openlab_p03_autobook.py` 回歸測試，
整批執行 `python -m unittest discover -s tests -p "test_ncl_openlab_*.py" -q`。
