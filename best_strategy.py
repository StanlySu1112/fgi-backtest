import os
import sys
import pandas as pd
import yfinance as yf
from backtest_logic import (
    get_ticker_code,
    run_backtest_logic,
    optimize_fgi
)

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_merged_data():
    """載入 FGI 數據並與 SPY、0050 股價對齊合併"""
    fgi_file = os.path.join(BASE_DIR, "FGI_all.csv")
    if not os.path.exists(fgi_file):
        fgi_file = os.path.join(BASE_DIR, "FGI_Final_Complete.csv")
        
    df_fgi = pd.read_csv(fgi_file)
    df_fgi.columns = df_fgi.columns.str.strip()
    df_fgi['Date'] = pd.to_datetime(df_fgi['Date'])
    
    tickers = ["SPY", "0050.TW"]
    raw = yf.download(tickers, start="2011-01-01", progress=False)['Close']
    raw = raw.ffill().dropna().reset_index()
    if '0050.TW' in raw.columns:
        raw = raw.rename(columns={'0050.TW': '0050'})
    raw['Date'] = pd.to_datetime(raw['Date']).dt.tz_localize(None)
    
    df_merged = pd.merge(df_fgi, raw, on='Date', how='inner')
    df_merged['Month'] = df_merged['Date'].dt.to_period('M')
    return df_merged

def analyze_asset_lump_sum(df, asset_name):
    """單筆本金 10 萬元回測與 Buy & Hold 基準比較"""
    print(f"\n>> 正在搜尋 [{asset_name}] 單筆本金的最佳 FGI 門檻...")
    
    stock_df = df[['Date', 'FGI', asset_name, 'Month']].copy()
    stock_df.rename(columns={asset_name: 'Close'}, inplace=True)
    
    # 執行暴力搜尋最佳參數 (初始 10 萬，每月 0 元)
    res_fgi = optimize_fgi(stock_df, asset_name, initial_capital=100000, monthly_add=0, discount=True)
    
    # 計算買入持有 (Buy & Hold)
    start_p = stock_df.iloc[0]['Close']
    end_p = stock_df.iloc[-1]['Close']
    bh_ret = (end_p - start_p) / start_p * 100.0
    
    print("-" * 50)
    print(f"🏆 [{asset_name}] 最佳策略分析：")
    print(f"  • 最佳恐慌買點: FGI < {res_fgi['buy_th']}")
    print(f"  • 最佳貪婪賣點: FGI > {res_fgi['sell_th']}")
    print(f"  • FGI 策略總報酬率: {res_fgi['total_return_pct']:.2f}% (CAGR: {res_fgi['cagr']:.2f}%)")
    print(f"  • FGI 最大回撤 (MDD): {res_fgi['mdd']:.2f}%")
    print(f"  • 傻傻買入持有 (Buy & Hold) 報酬率: {bh_ret:.2f}%")
    
    if res_fgi['total_return_pct'] > bh_ret:
        print("  ✓ 結論：FGI 擇時策略戰勝買入持有！")
    else:
        print("  ! 結論：買入持有 (Buy & Hold) 績效更優。")
    print("-" * 50)

if __name__ == "__main__":
    df = get_merged_data()
    if not df.empty:
        analyze_asset_lump_sum(df, "SPY")
        analyze_asset_lump_sum(df, "0050")
