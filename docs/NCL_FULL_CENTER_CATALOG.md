# 國圖 OPEN LAB｜全中心類別盤點與實機驗收缺口

基準：`26ad492cdfa7737cd12aac5a049dc6c73c9ea80b`；目標分支：`feat/ncl-openlab-booking`。

## 14 類別（使用者網站截圖，非 DOM 完整驗證）

| 類別 | 目前編入的實際單位 | 線上預約狀態 |
|---|---|---|
| 討論室 | 房號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 團練室 | 房號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 星際直播攝影棚 | 房號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 親子直播室 | 房號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 音樂創作室 | music（1） | 時段 DOM 曾觀察；最終提交 NOT_VERIFIED |
| 影音欣賞區 | 不提供線上選擇 | **ONSITE_ONLY** |
| 創藝手作坊縫紉機 | 縫紉機01–08、刺繡機01（共 9 個） | 01 時段曾觀察；其餘時段與提交 NOT_VERIFIED |
| 個人直播室 | P03（1） | **LIVE_VERIFIED**：保留既有單筆成功證據 |
| 動漫創作坊電腦 | 設備編號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 電神工作室 | 房號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 影印掃描用電腦 | 設備編號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 創藝手作坊電腦 | 設備編號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 數位科技實作區電腦 | 設備編號未知 | ONLINE_CANDIDATE / NOT_VERIFIED |
| 語言學習區 | 不提供線上選擇 | **ONSITE_ONLY** |

**已列入 JSON：11 個實際單位（1 個 LIVE_VERIFIED；10 個 NOT_VERIFIED）。** 另有 9 個候選類別尚未確認任何房號／設備；不能把「9 類」誤報成「9 台待驗證設備」。兩個現場借用類別永遠沒有正式預約選項。

## 已有時段證據與邊界

- P03：09:00–20:00 共 11 個一小時時段；單筆實機成功（證據見 `NCL_RC_CLOSEOUT.md`）。
- 音樂創作室：09:00–12:00、13:00–16:00、17:00–20:00；觀察到 `.time-box2[data-param1]`，但可預約正向流程／最終提交未驗證。
- 縫紉機01：觀察到 09:00–20:00 的 11 個一小時時段（`.time-box[data-param1]`）；最終確認頁未驗證。
- 縫紉機02–08、刺繡機01：**各自的時段尚未觀察**；舊模板一小時資料只是歷史草稿，`slots_verified=false`，前端不呈現。不得沿用01的時段當成其他設備事實。
- 其餘類別：房號、設備識別、入口 selector、時段與最終確認頁皆 **NOT_VERIFIED**，不得猜測或啟用正式提交。

## 使用方式

Mac（已 `git pull`、安裝 `zendriver` 的本機專案目錄）：

```bash
python3 src/ncl_openlab_inventory.py --guided
```

依序顯示 12 個線上候選類別；**使用者手動登入、手動切換類別／日期頁，按 Enter** 擷取目前可見 DOM。輸入 `s` 略過、`q` 結束。無 click、refresh、預約 API 或提交。匿名報告輸出至 `ncl_reports/ncl_inventory_*.json`，包含 `operator_category`（僅人工標籤，`OPERATOR_SELECTED_NOT_VERIFIED`）、房間方塊名稱、時段 selector、時長及草稿。私人資料／含帳號或驗證碼的畫面勿上傳公開 GitHub。

## 未完成實機證據（逐個類別核實）

1. 九個未建立單位的候選類別：完整房號／設備清單與可否線上預約。
2. 所有未驗證單位：入口實際 `data-zh`，房間 tile 選擇器、唯一性／相鄰單位對照、時段清單和時長；不可假設都是一小時。
3. 最後確認頁的房間／日期／時段比對文字與單次送出結果；每單位各自取得證據後才能從 `NOT_VERIFIED` 更新。
4. Mac、Windows 介面切換、人工 CAPTCHA／登入 Session、排程、二時段與單次提交的實機回歸。P03 既有實機成功紀錄不因新增分類而改寫。
5. 目前 GitHub-only 修改無可執行的本機 Python／Chromium：完整 unittest、整合、假瀏覽器及 Windows/macOS GUI 結果一律仍為 **NOT_RUN**，不可宣稱 PASS。

安全設計：`ncl_openlab_rooms.json` 為唯一清單來源；前端兩層類別→單位，後端沿用同一個 profile 驅動引擎；GUI 與 CLI 的 `--auto-submit` 對 `NOT_VERIFIED` 一律拒絕，舊 `--ack-room-unverified` 也不能解鎖。未修改登入、CAPTCHA、憑證庫、Session 監控、排程、單次提交守衛；不修改 `main`，不使用 Docker 或 GitHub Actions。
