import os
import io
import sys
import datetime
import requests
import pandas as pd

# 解決 Windows 終端機預設編碼 (如 CP950) 無法顯示 UTF-8 / Emoji 的問題
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

"""
create_fgi_dataset.py
======================
恐懼與貪婪指數 (Fear & Greed Index, FGI) 數據下載與更新模組
支援：
1. 本地既有資料讀取 (確保歷史資料不丟失)
2. GitHub 歷史歸檔數據備份 (2011 - 2023)
3. CNN 官方即時 API 更新 (最新近一年數據，包含今天)
4. 智慧縫合、去重、排序與多檔名同步相容 (FGI_all.csv, FGI_Final_Complete.csv, FGI_Final.csv)
"""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_local_existing_data():
    """優先嘗試載入本地已有的完整數據，避免網路異常時丟失資料"""
    candidate_files = ["FGI_all.csv", "FGI_Final_Complete.csv", "FGI_Final.csv"]
    for fname in candidate_files:
        fpath = os.path.join(BASE_DIR, fname)
        if os.path.exists(fpath):
            try:
                df = pd.read_csv(fpath)
                df.columns = df.columns.str.strip()
                if 'Date' in df.columns and 'FGI' in df.columns:
                    df['Date'] = pd.to_datetime(df['Date'])
                    if len(df) > 500:
                        print(f"[本地檔案] 已載入歷史基底 [{fname}]，共 {len(df)} 筆 ({df['Date'].min().date()} ~ {df['Date'].max().date()})")
                        return df[['Date', 'FGI']]
            except Exception as e:
                print(f"[警告] 讀取本地 {fname} 失敗: {e}")
    return pd.DataFrame()

def get_fgi_history_github():
    """從 GitHub 下載歷史歸檔數據 (2011-2023)"""
    print("[步驟 1] 正在檢查 GitHub 歷史數據 (2011-2023)...")
    github_url = "https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/data/fear-greed-2011-2023.csv"
    try:
        resp = requests.get(github_url, timeout=10)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.rename(columns={'date': 'Date', 'value': 'FGI'}, inplace=True)
        df['Date'] = pd.to_datetime(df['Date'])
        df = df[['Date', 'FGI']].dropna()
        print(f"[成功] GitHub 歷史數據連線成功！共 {len(df)} 筆 ({df['Date'].min().date()} ~ {df['Date'].max().date()})")
        return df
    except Exception as e:
        print(f"[提示] GitHub 歷史數據下載失敗 (將使用本地歷史): {e}")
        return pd.DataFrame()

def get_fgi_recent_cnn():
    """從 CNN 官方 API 抓取最新即時數據 (近一年，包含今天)"""
    print("[步驟 2] 連線 CNN 官方 API 抓取最新即時數據...")
    cnn_url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(cnn_url, headers=headers, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        fgi_items = data.get('fear_and_greed_historical', {}).get('data', [])
        
        rows = []
        for item in fgi_items:
            dt = datetime.datetime.fromtimestamp(item['x'] / 1000).date()
            val = int(item['y'])
            rows.append({'Date': pd.to_datetime(dt), 'FGI': val})
            
        df_recent = pd.DataFrame(rows)
        if not df_recent.empty:
            print(f"[成功] CNN 即時數據抓取成功！共 {len(df_recent)} 筆 ({df_recent['Date'].min().date()} ~ {df_recent['Date'].max().date()})")
            return df_recent
        else:
            print("[警告] CNN 回傳資料為空")
            return pd.DataFrame()
    except Exception as e:
        print(f"[警告] CNN API 抓取失敗: {e}")
        return pd.DataFrame()

def update_dataset():
    print("=" * 60)
    print(">> 開始執行恐懼與貪婪指數 (FGI) 數據更新程序")
    print("=" * 60)
    
    # 1. 取得歷史數據 (本地優先，若無則連線 GitHub)
    df_local = get_local_existing_data()
    if df_local.empty:
        df_history = get_fgi_history_github()
    else:
        df_history = df_local
        
    # 2. 取得 CNN 最新即時數據
    df_recent = get_fgi_recent_cnn()
    
    # 3. 數據縫合與驗證
    dfs_to_merge = []
    if not df_history.empty:
        dfs_to_merge.append(df_history)
    if not df_recent.empty:
        dfs_to_merge.append(df_recent)
        
    if not dfs_to_merge:
        print("[錯誤] 無法取得任何 FGI 數據，程式終止。")
        return False
        
    df_final = pd.concat(dfs_to_merge, axis=0)
    
    # 去除重複 (重複日期以最新 CNN 數據為準)
    df_final = df_final.drop_duplicates(subset='Date', keep='last')
    
    # 日期排序與格式化為標準 YYYY-MM-DD
    df_final = df_final.sort_values(by='Date').reset_index(drop=True)
    df_final['Date'] = df_final['Date'].dt.strftime('%Y-%m-%d')
    df_final['FGI'] = df_final['FGI'].astype(int)
    
    # 4. 同步儲存到所有相容檔名
    out_files = ["FGI_all.csv", "FGI_Final_Complete.csv", "FGI_Final.csv"]
    for fname in out_files:
        fpath = os.path.join(BASE_DIR, fname)
        df_final.to_csv(fpath, index=False)
        
    latest_val = df_final.iloc[-1]['FGI']
    latest_date = df_final.iloc[-1]['Date']
    
    def get_fgi_sentiment(v):
        if v <= 25: return "極度恐慌 (Extreme Fear)"
        if v <= 45: return "恐慌 (Fear)"
        if v <= 55: return "中性 (Neutral)"
        if v <= 75: return "貪婪 (Greed)"
        return "極度貪婪 (Extreme Greed)"

    print("-" * 60)
    print("✓ FGI 數據更新完畢！")
    print(f"• 總資料筆數: {len(df_final)} 筆交易日")
    print(f"• 涵蓋時間跨度: {df_final.iloc[0]['Date']} 至 {latest_date}")
    print(f"• 最新市場指數: {latest_val} 分 ({get_fgi_sentiment(latest_val)})")
    print(f"• 同步儲存至相容檔案: {', '.join(out_files)}")
    print("=" * 60)
    return True

if __name__ == "__main__":
    update_dataset()
