import os
import sys
import time
import traceback
import datetime
import pandas as pd
import yfinance as yf
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from backtest_logic import (
    get_ticker_code,
    run_backtest_logic,
    optimize_fgi,
    NAME_TO_TICKER
)

# 解決 Windows 控制台編碼問題
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=BASE_DIR)
CORS(app)

# 股票歷史數據記憶體快取 (避免短時間內重複向 Yahoo Finance 請求)
STOCK_CACHE = {}
CACHE_TTL_SECONDS = 3600  # 1 小時快取

def load_fgi_data():
    """載入本地完整恐懼貪婪指數 CSV 數據"""
    possible_names = ["FGI_all.csv", "FGI_Final_Complete.csv", "FGI_Final.csv"]
    for name in possible_names:
        full_path = os.path.join(BASE_DIR, name)
        if os.path.exists(full_path):
            try:
                df = pd.read_csv(full_path)
                df.columns = df.columns.str.strip()
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.sort_values(by='Date').drop_duplicates(subset='Date', keep='last').reset_index(drop=True)
                return df
            except Exception as e:
                print(f"[錯誤] 讀取 {name} 失敗: {e}")
    return pd.DataFrame()

def fetch_stock_data_cached(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """下載股價數據，帶有智慧快取與時間切片"""
    now = time.time()
    cache_key = f"{code}_2010"
    
    # 檢查快取
    if cache_key in STOCK_CACHE:
        cached_df, cached_time = STOCK_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_df
            
    # 向 yfinance 請求數據 (從 2010 年起一次抓足，供後續任意切片使用)
    # 稍微延後一天以確保包含 end_date
    end_date_yf = (pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    raw = yf.download(code, start="2010-01-01", end=end_date_yf, progress=False)['Close']
    
    if isinstance(raw, pd.DataFrame):
        if raw.shape[1] > 0:
            raw = raw.iloc[:, 0]
        else:
            return pd.DataFrame()
            
    raw = raw.ffill().dropna()
    stock_df = raw.reset_index()
    stock_df.columns = ['Date', 'Close']
    stock_df['Date'] = pd.to_datetime(stock_df['Date']).dt.tz_localize(None)
    
    # 存入快取
    STOCK_CACHE[cache_key] = (stock_df, now)
    return stock_df

@app.route('/')
def index():
    """首頁：直接提供 index.html 視覺化戰情室"""
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    """健康檢查與數據狀態"""
    df_fgi = load_fgi_data()
    return jsonify({
        "status": "online",
        "fgi_days": len(df_fgi),
        "fgi_start": df_fgi.iloc[0]['Date'].strftime('%Y-%m-%d') if not df_fgi.empty else None,
        "fgi_end": df_fgi.iloc[-1]['Date'].strftime('%Y-%m-%d') if not df_fgi.empty else None
    })

@app.route('/api/fgi/latest', methods=['GET'])
def fgi_latest():
    """回傳最新恐懼貪婪指數數值與市場狀態"""
    df_fgi = load_fgi_data()
    if df_fgi.empty:
        return jsonify({"error": "找不到 FGI 數據"}), 404
        
    last_row = df_fgi.iloc[-1]
    val = int(last_row['FGI'])
    dt = last_row['Date'].strftime('%Y-%m-%d')
    
    if val <= 25:
        category, sentiment = "極度恐慌", "Extreme Fear"
    elif val <= 45:
        category, sentiment = "恐慌", "Fear"
    elif val <= 55:
        category, sentiment = "中性", "Neutral"
    elif val <= 75:
        category, sentiment = "貪婪", "Greed"
    else:
        category, sentiment = "極度貪婪", "Extreme Greed"
        
    return jsonify({
        "date": dt,
        "value": val,
        "category": category,
        "sentiment": sentiment
    })

@app.route('/api/backtest', methods=['POST'])
def backtest():
    """
    回測 API 接口：
    接收使用者投資參數，執行 DCA 與 FGI 回測並回傳豐富報表
    """
    try:
        data = request.json or {}
        tickers_input = data.get('tickers', ["台積電", "0050"])
        strategies = data.get('strategies', ["DCA", "FGI"])
        init_cap = float(data.get('initial', 100000))
        month_add = float(data.get('monthly', 10000))
        start_date = data.get('startDate', '2011-01-03')
        end_date = data.get('endDate', '2026-12-31')
        discount = data.get('discount', True)
        
        is_auto_fgi = data.get('isAutoFgi', True)
        manual_buy = int(data.get('manualBuy', 20))
        manual_sell = int(data.get('manualSell', 80))

        df_fgi = load_fgi_data()
        if df_fgi.empty:
            return jsonify({"error": "找不到 FGI 歷史數據檔案 (FGI_all.csv 或 FGI_Final.csv)"}), 500

        results = []
        for name in tickers_input:
            clean_name = name.strip()
            if not clean_name:
                continue
            code = get_ticker_code(clean_name)
            
            try:
                stock_df = fetch_stock_data_cached(code, start_date, end_date)
                if stock_df.empty:
                    print(f"[提示] 無法取得 {name} ({code}) 的股價數據")
                    continue

                # 關鍵：以股票交易日為基準進行合併 (how='right')
                df = pd.merge(df_fgi, stock_df, on='Date', how='right')
                
                # FGI 空值自動沿用前一天數值 (ffill)
                df['FGI'] = df['FGI'].ffill()
                df = df.dropna(subset=['FGI', 'Close'])

                # 依照使用者選取之日期精準裁切
                df = df[(df['Date'] >= pd.to_datetime(start_date)) & (df['Date'] <= pd.to_datetime(end_date))]
                if df.empty:
                    continue
                    
                df = df.reset_index(drop=True)
                df['Month'] = df['Date'].dt.to_period('M')

                stock_result = {
                    "name": clean_name,
                    "code": code,
                    "date_range": {
                        "start": df.iloc[0]['Date'].strftime('%Y-%m-%d'),
                        "end": df.iloc[-1]['Date'].strftime('%Y-%m-%d'),
                        "trading_days": len(df)
                    },
                    "strategies": []
                }
                
                # 1. 定期定額 (DCA)
                if 'DCA' in strategies:
                    res_dca = run_backtest_logic(df, code, 'DCA', init_cap, month_add, discount, return_trades=True)
                    res_dca['type'] = '定期定額 (DCA)'
                    stock_result['strategies'].append(res_dca)
                    
                # 2. FGI 混合戰法
                if 'FGI' in strategies:
                    if is_auto_fgi:
                        res_fgi = optimize_fgi(df, code, init_cap, month_add, discount)
                        if res_fgi:
                            res_fgi['type'] = f"FGI 最佳策略 (自動: 買<{res_fgi['buy_th']}/賣>{res_fgi['sell_th']})"
                            stock_result['strategies'].append(res_fgi)
                    else:
                        res_fgi = run_backtest_logic(
                            df, code, 'FGI', init_cap, month_add, discount,
                            manual_buy, manual_sell, return_trades=True
                        )
                        res_fgi['type'] = f"FGI 自訂策略 (買<{manual_buy}/賣>{manual_sell})"
                        stock_result['strategies'].append(res_fgi)
                
                if stock_result['strategies']:
                    results.append(stock_result)
                    
            except Exception as e:
                print(f"[錯誤] 處理 {name} ({code}) 失敗: {traceback.format_exc()}")
                continue

        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

if __name__ == '__main__':
    print("=" * 65)
    print("🚀 恐懼貪婪指數 (FGI) 智慧回測伺服器啟動！")
    print("🌐 伺服器網址: http://127.0.0.1:5000")
    print("📊 具備極速純數值最佳化引擎、交易稅費精算與斷層自動修復機制")
    print("💡 請在瀏覽器中開啟 http://127.0.0.1:5000 或雙擊 index.html")
    print("=" * 65)
    app.run(host='0.0.0.0', port=5000, debug=False)
