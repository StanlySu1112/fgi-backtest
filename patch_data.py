import os
import sys
from create_fgi_dataset import update_dataset

"""
patch_data.py
==============
恐懼貪婪指數數據補丁工具
直接調用 create_fgi_dataset.py 進行最新 CNN 官方 API 與本地歷史縫合
"""

if __name__ == "__main__":
    print(">> 啟動 FGI 數據自動更新與補丁程序...")
    success = update_dataset()
    if success:
        print("✓ 補丁更新完成！")
    else:
        print("! 更新過程中遇到問題，請檢查網路連線。")
