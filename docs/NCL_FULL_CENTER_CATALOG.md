# 國圖 OPEN LAB｜全中心類別盤點與實機驗收缺口

基準：`3760c7214a6f1037b2877c8d6c4cc4396d2b9aea`；分支：`feat/ncl-openlab-booking`。

## 2026-11-04 唯讀盤點（操作員切換，未經 DOM 類別關聯核實）

依本機 `ncl_reports/ncl_inventory_20261104_180300.json` 的終端機輸出整理：所有 `operator_category` 均為 `OPERATOR_SELECTED_NOT_VERIFIED`。辨識到的名稱**不等於**時段、流程或可提交證據。

| 類別 | 二層選單已盤點的單位 | 狀態 |
|---|---|---|
| 討論室 | 尚未取得房號 | 待盤點 |
| 團練室 | 團練室 2 ~ 8 人（1） | NOT_VERIFIED |
| 星際直播攝影棚 | 星際直播攝影棚 2 ~ 5 人（1） | NOT_VERIFIED |
| 親子直播室 | 本次略過，單位未知 | 待盤點 |
| 音樂創作室 | music（1） | 舊時段 DOM，提交 NOT_VERIFIED |
| 影音欣賞區 | 無可預約單位 | ONSITE_ONLY |
| 創藝手作坊縫紉機 | 縫紉機01–08、刺繡機01（9） | 只有縫紉機01曾觀察時段，提交 NOT_VERIFIED |
| 個人直播室 | P03、P01、P02（3） | **僅 P03 LIVE_VERIFIED**；P01、P02 NOT_VERIFIED |
| 動漫創作坊電腦 | AN01（1） | NOT_VERIFIED |
| 雷神工作室 | 雷雕機 LASER（1） | NOT_VERIFIED |
| 影印掃描用電腦 | SCAN01（1） | NOT_VERIFIED |
| 創藝手作坊電腦 | DIY01（1） | NOT_VERIFIED |
| 數位科技實作區電腦 | IT01–IT10（10，IT09 是 3D Scanner） | NOT_VERIFIED |
| 語言學習區 | 無可預約單位 | ONSITE_ONLY |

**合計 14 個類別、29 個已知單位名稱**，包含 11 個既有引擎 profile（1 個 LIVE_VERIFIED）與 **18 個僅有名稱的唯讀 `categories[].catalog_units`**。現場借用的 2 類不可預約。

## 安全與技術邊界

- 新增 18 個單位僅提供兩層選單顯示，`live=NOT_VERIFIED`。**不建立 engine room**；不填寫猜測的 slot、flow、selector 或最後確認文字。
- 新單位選擇後沒有時段；GUI「啟動」停用；GUI bridge 即使有手動時段與 ack 仍拒絕 `NOT_VERIFIED`；CLI 只能接受真正已設定的 engine room。
- 本輪所有 `slot_groups=[]`；不足以確認任何新單位的時段或可選狀態。舊 P03 實機成功及音樂／縫紉機01時段證據不受修改。
- `categories[].room_keys` = 現有完整 engine profile；`categories[].catalog_units` = 只有辨識名稱的非預約條目。未來核實一個單位，要從 catalog 移除該鍵並建立對應 profile，避免重複。
- `NOT_VERIFIED` 的正式提交仍 fail-closed，`--ack-room-unverified` 不得解鎖。登入、CAPTCHA、金鑰庫、排程不變。

## 待補與驗證

1. 討論室、親子直播室單位與各類別清單是否完整。
2. 各單位獨立入口 DOM、時段長度／可用態／選取行為及最後確認頁比對。
3. 各自單筆實機成功證據，確認前不得標 LIVE_VERIFIED。
4. Windows／Mac GUI、登入／人工驗證碼／排程／二時段及防重複提交驗收。
5. GitHub 修改只做靜態檢查；完整 unittest、GUI、整合與假瀏覽器 **NOT_RUN**。

Mac 唯讀盤點：`cd ~/ncl-openlab && .venv/bin/python src/ncl_openlab_inventory.py --guided`。

僅修改 `feat/ncl-openlab-booking`；不更動 main、Docker 或 GitHub Actions。
