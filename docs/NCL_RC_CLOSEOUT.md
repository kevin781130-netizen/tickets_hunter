# NCL OPEN LAB — Release Candidate Closeout

範圍：`tickets_hunter` 的 `feat/ncl-openlab-booking` 分支。這是**支線 RC 封版**；
不更動 `main`、不啟用 GitHub Actions、不自動合併 PR。

## 正式使用（Windows 11）

專案根目錄雙擊 `launch_ncl_picker.cmd`。這是唯一建議的日常入口。

1. 在 GUI 選 **音樂創作室**或 **P03 個人直播室**，於月曆點日期。
2. 勾選 **一或兩個時段**；標為「第1筆／第2筆」的順序就是正式預約順序。
3. 若日期已開放，勾選「**立即正式預約（會真的送出）**」；否則在預估
   放位前 15 分鐘內啟動午夜模式。
4. 確認實際送出授權，按「確認設定並開啟預約瀏覽器」；
   正式操作只在明確確認後啟動。
5. 手動登入、完成網站必要條款及參與者資料，再於**登入階段**按 Enter。
6. 預約結果頁**持續保留**，不要求事後按 Enter；自己關閉 Chrome 後
   控制程式自然結束。

注意：GUI 上的可選日期與時段是操作選項，**不代表網站即時有空位**。

## 預約規則

- 開放日按使用日期減 7 日、台北時間 00:00 **預估**；未經官方
  精確到秒的保證。午夜 23:59:50 預刷新，00:00 正式刷新。
- 若日期或指定時段尚未開放，最多 **90 秒、每次相隔 3 秒**
  再刷頁（可用 CLI 在安全邊界內更改）；非無限迴圈。
- 一個時段：嘗試預約一筆。兩個時段：依選取順序嘗試**兩筆**。
  每筆各走完整 UI；第二筆必須等第一筆出現官方成功頁才開始。
- 只會透過可見網頁 UI 點一次最後確認；若預約結果不明，
  **絕不自動補送**。必須自行到官網「我的紀錄」核對。
- 使用者自行登入；不儲存帳密、不破解驗證碼、不繞過網站權限。
- 預約前請確認既有預約數、網站人數限制及當天實際開放時間；
  不會從「我的紀錄」自動扣除既有名額。

## 目前證據／不能誇大

| 能力 | 驗收證據 |
|---|---|
| P03 單筆（日期→房號→時段→最後確認） | **實機成功**，國圖成功畫面及 `SUCCESS_PAGE_MATCHED` |
| GUI 月曆／時段複選／底部按鈕 | Windows 端使用者確認可以正常選擇及搶位；離線測試通過 |
| 自動留存結果頁、用戶關閉才退出 | **實機兩次** `BROWSER_OPEN_PASS` → `BROWSER_CLOSE_PASS` |
| 午夜 T-10／T=0 刷新、3 秒限時重試 | **離線測試通過；正式午夜搶位尚無實機正向證據** |
| 同一天連續預約兩筆（音樂室／P03） | **離線模擬通過；尚無兩筆實際成交驗證** |

之前使用者在本機已確認 **160 項離線測試通過**，其後封版新增
「立即預約警示」及兩項回歸測試，**尚待本機最後重跑**。
請勿把 mock 中的 `TWO_BOOKINGS_CONFIRMED` 視為真正已訂房。

## 多房型引擎

房型差異已集中到 `src/ncl_openlab_rooms.json`，詳見
[NCL_MULTI_ROOM.md](NCL_MULTI_ROOM.md)：支援矩陣、新增房型流程、
`--dry-run`／報告／截圖，以及尚待實機驗證的項目。P03 實機驗證範圍不變。

## 一次性本機離線 Gate

在專案根目錄 PowerShell 執行：

```powershell
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify_ncl_release.ps1
```

成功會顯示 `NCL_RELEASE_GATE_PASS`；只驗證支線、
Python 編譯與離線單元測試，**不開瀏覽器、不預約**。
如需單獨檢查瀏覽器生命週期，可執行：

```powershell
.\.venv\Scripts\python.exe src\ncl_browser_lifecycle_smoke.py
```

這只開啟空白頁，手動關閉後輸出 `BROWSER_CLOSE_PASS`，
絕不進入國圖預約流程。

## 封版原則

- `main` 保持原狀，所有改動只在 `feat/ncl-openlab-booking`。
- 完成離線 Gate 與下一次**自然發生的**午夜雙時段實機驗收前，
  正式狀態為 **RC_READY / MIDNIGHT_TWO_SLOT_PENDING**，
  不宣稱整體 Production PASS。
- 遇到重複預約、不明結果、跨日或官方規則異動，停止自動化並人工核對。
