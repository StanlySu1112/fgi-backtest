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
    """載入 FGI 與 0050, SPY 股價數據"""
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

def compare_dca_vs_fgi(df, asset_name, monthly_pay=3000):
    """比較每月定期定額 vs FGI 混合策略"""
    print("=" * 60)
    print(f">> 分析標的：{asset_name} (每月定期定額 ${monthly_pay})")
    print("=" * 60)
    
    stock_df = df[['Date', 'FGI', asset_name, 'Month']].copy()
    stock_df.rename(columns={asset_name: 'Close'}, inplace=True)
    
    # 1. 定期定額 (DCA)
    res_dca = run_backtest_logic(stock_df, asset_name, 'DCA', initial_capital=0, monthly_add=monthly_pay, discount=True)
    
    # 2. FGI 混合戰法
    res_fgi = optimize_fgi(stock_df, asset_name, initial_capital=0, monthly_add=monthly_pay, discount=True)
    
    print("[策略 1] 定期定額 (DCA):")
    print(f"  • 總投入成本: ${res_dca['total_cost']:,.0f}")
    print(f"  • 最終總資產: ${res_dca['final_value']:,.0f}")
    print(f"  • 累積總報酬率: {res_dca['total_return_pct']:.2f}% (CAGR: {res_dca['cagr']:.2f}%)")
    print(f"  • 最大回撤 (MDD): {res_dca['mdd']:.2f}%")
    print("-" * 50)
    
    print("[策略 2] FGI 擇時混合戰法 (最佳化參數):")
    print(f"  • 最佳門檻: 恐慌 < {res_fgi['buy_th']} 買進，貪婪 > {res_fgi['sell_th']} 賣出")
    print(f"  • 最終總資產: ${res_fgi['final_value']:,.0f}")
    print(f"  • 累積總報酬率: {res_fgi['total_return_pct']:.2f}% (CAGR: {res_fgi['cagr']:.2f}%)")
    print(f"  • 最大回撤 (MDD): {res_fgi['mdd']:.2f}%")
    print(f"  • 交易總次數: {res_fgi['trades_count']} 次")
    print("-" * 50)
    
    diff = res_fgi['final_value'] - res_dca['final_value']
    if diff > 0:
        print(f"🏆 【FGI 策略獲勝】！比定期定額多賺了 ${diff:,.0f} (+{(diff/res_dca['total_cost']*100):.1f}%)")
    else:
        print(f"📊 【定期定額 (DCA) 獲勝】！FGI 策略少賺了 ${abs(diff):,.0f}")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    df = get_merged_data()
    if not df.empty:
        compare_dca_vs_fgi(df, "0050", monthly_pay=3000)
        compare_dca_vs_fgi(df, "SPY", monthly_pay=3000)
