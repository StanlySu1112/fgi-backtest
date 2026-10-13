import os
import sys
import warnings
import pandas as pd
import yfinance as yf
from backtest_logic import (
    get_ticker_code,
    run_backtest_logic,
    optimize_fgi,
    NAME_TO_TICKER
)

# 終端機安全編碼
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

warnings.simplefilter(action='ignore', category=FutureWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# 使用者設定區
# ==========================================
MONTHLY_INVESTMENT = 10000
INITIAL_CAPITAL = 100000

TARGET_STOCKS = [
    "0050.TW",  # 元大台灣50
    "2330.TW",  # 台積電
    "0056.TW",  # 元大高股息
    "2317.TW",  # 鴻海
    "2454.TW",  # 聯發科
    "2002.TW",  # 中鋼
    "SPY"       # 美股大盤
]

def load_fgi_master():
    candidate_files = ["FGI_all.csv", "FGI_Final_Complete.csv", "FGI_Final.csv"]
    for fname in candidate_files:
        p = os.path.join(BASE_DIR, fname)
        if os.path.exists(p):
            df = pd.read_csv(p)
            df.columns = df.columns.str.strip()
            df['Date'] = pd.to_datetime(df['Date'])
            return df
    return pd.DataFrame()

def main():
    print("=" * 110)
    print(f">> 啟動台美股跨標的戰鬥回測：初始本金 ${INITIAL_CAPITAL:,}，每月投入 ${MONTHLY_INVESTMENT:,}")
    print("=" * 110)

    df_fgi = load_fgi_master()
    if df_fgi.empty:
        print("[錯誤] 找不到 FGI 歷史資料！請先執行 create_fgi_dataset.py")
        return

    print("下載最新行情數據中...")
    try:
        raw_data = yf.download(TARGET_STOCKS, start="2011-01-01", progress=False)['Close']
        raw_data = raw_data.ffill().dropna()
    except Exception as e:
        print(f"行情下載失敗: {e}")
        return

    header = f"{'標的代號':<10} | {'總投入本金':<10} | {'獲勝策略':<8} | {'DCA 淨獲利':<12} | {'FGI 淨獲利':<12} | {'DCA (CAGR/MDD)':<18} | {'FGI (CAGR/MDD)':<18} | {'最佳門檻'}"
    print("-" * 110)
    print(header)
    print("-" * 110)

    for ticker in TARGET_STOCKS:
        if ticker not in raw_data.columns:
            continue

        stock_df = raw_data[[ticker]].reset_index()
        stock_df.columns = ['Date', 'Close']
        stock_df['Date'] = pd.to_datetime(stock_df['Date']).dt.tz_localize(None)

        df = pd.merge(df_fgi, stock_df, on='Date', how='right')
        df['FGI'] = df['FGI'].ffill().dropna()
        df = df.dropna(subset=['FGI', 'Close']).reset_index(drop=True)
        df['Month'] = df['Date'].dt.to_period('M')

        if df.empty:
            continue

        # 1. 定期定額 (DCA)
        res_dca = run_backtest_logic(df, ticker, 'DCA', INITIAL_CAPITAL, MONTHLY_INVESTMENT, discount=True, return_trades=False)
        
        # 2. FGI 混合策略 (暴力最佳化)
        res_fgi = optimize_fgi(df, ticker, INITIAL_CAPITAL, MONTHLY_INVESTMENT, discount=True)

        winner = "🏆 FGI" if res_fgi['final_value'] > res_dca['final_value'] else "📊 DCA"
        cost_str = f"${res_dca['total_cost']/10000:.0f}萬"
        dca_profit_str = f"${res_dca['net_profit']/10000:+.1f}萬"
        fgi_profit_str = f"${res_fgi['net_profit']/10000:+.1f}萬"
        dca_metrics = f"{res_dca['cagr']:4.1f}% / {res_dca['mdd']:4.1f}%"
        fgi_metrics = f"{res_fgi['cagr']:4.1f}% / {res_fgi['mdd']:4.1f}%"
        param_str = f"買<{res_fgi['buy_th']}/賣>{res_fgi['sell_th']}"

        print(f"{ticker:<10} | {cost_str:<10} | {winner:<8} | {dca_profit_str:<12} | {fgi_profit_str:<12} | {dca_metrics:<18} | {fgi_metrics:<18} | {param_str}")

    print("-" * 110)
    print("[指標說明]")
    print("1. 金額單位皆為『新台幣/美金 萬元』。")
    print("2. 淨獲利 = 最終總資產 - 累積投入總成本。")
    print("3. MDD (最大回撤) 代表過程中資產自歷史高點跌幅幅度。")
    print("=" * 110)

if __name__ == "__main__":
    main()
