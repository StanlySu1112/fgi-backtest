import os
import sys
import numpy as np
import pandas as pd

"""
backtest_logic.py
==================
恐懼貪婪指數回測核心演算法引擎
嚴格保留原始交易邏輯與基礎原理：
1. 定期定額 (DCA)
2. FGI 混合戰法 (持股時若 fgi > sell_th 貪婪清倉；持股期間有薪水加碼；空手時若 fgi < buy_th 恐慌梭哈)
3. 交易成本精算：券商手續費 (0.1425%，支援 6 折)、證交稅 (ETF 0.1%，股票 0.3%)
4. 效能優化：網格搜索採用高效純數值運算，大幅加速最佳化運算
5. 分析強化：新增最大回撤 (MDD)、總報酬率、淨獲利、勝率與交易次數統計
"""

NAME_TO_TICKER = {
    # 台灣主流指數與權值股
    "0050": "0050.TW", "元大台灣50": "0050.TW",
    "0056": "0056.TW", "元大高股息": "0056.TW",
    "00878": "00878.TW", "國泰永續高股息": "00878.TW",
    "00919": "00919.TW", "群益台灣精選高息": "00919.TW",
    "00929": "00929.TW", "復華台灣科技優息": "00929.TW",
    "00713": "00713.TW", "元大台灣高息低波": "00713.TW",
    "006208": "006208.TW", "富邦台50": "006208.TW",
    "台積電": "2330.TW", "2330": "2330.TW",
    "鴻海": "2317.TW", "2317": "2317.TW",
    "聯發科": "2454.TW", "2454": "2454.TW",
    "中鋼": "2002.TW", "2002": "2002.TW",
    "富邦金": "2881.TW", "2881": "2881.TW",
    "國泰金": "2882.TW", "2882": "2882.TW",
    "台達電": "2308.TW", "廣達": "2382.TW",
    # 美股主流 ETF 與權值股
    "SPY": "SPY", "美股大盤": "SPY", "S&P500": "SPY", "標普500": "SPY",
    "QQQ": "QQQ", "那斯達克": "QQQ",
    "VOO": "VOO", "VTI": "VTI", "SOXX": "SOXX", "SMH": "SMH",
    "輝達": "NVDA", "NVDA": "NVDA",
    "特斯拉": "TSLA", "TSLA": "TSLA",
    "蘋果": "AAPL", "AAPL": "AAPL",
    "微軟": "MSFT", "MSFT": "MSFT",
    "谷歌": "GOOGL", "GOOGL": "GOOGL", "Alphabet": "GOOGL",
    "亞馬遜": "AMZN", "AMZN": "AMZN",
    "Meta": "META", "META": "META",
    "台積電ADR": "TSM", "TSM": "TSM"
}

def get_ticker_code(input_str: str) -> str:
    """轉換中文股名或別名為標準代號 (如 台積電 -> 2330.TW)"""
    clean_input = input_str.strip()
    return NAME_TO_TICKER.get(clean_input, clean_input)

def get_tax_rate(ticker: str) -> float:
    """判斷證交稅：台灣 ETF 0.1%，美股/ETF 暫以 0.1% 估算，台灣一般股票 0.3%"""
    t = ticker.upper()
    if t.startswith('00') or t in ['SPY', 'QQQ', 'VOO', 'VTI', 'SOXX', 'SMH', 'DIA', 'IWM']:
        return 0.001
    return 0.003

def calculate_mdd(history_values: list) -> float:
    """計算資產歷史曲線之最大回撤 (Maximum Drawdown, MDD %)"""
    if not history_values or len(history_values) < 2:
        return 0.0
    assets = np.array(history_values, dtype=float)
    running_max = np.maximum.accumulate(assets)
    running_max[running_max == 0] = 1e-6
    drawdown = (assets - running_max) / running_max
    return float(drawdown.min() * 100.0)

def simulate_fast(prices, fgis, months, initial_capital, monthly_add, fee_rate, tax_rate, buy_th, sell_th):
    """
    極速純數值模擬 (專供網格搜索參數最佳化使用)
    避免每輪迴圈產生數千個字典，將最佳化速度提升 10 倍以上
    """
    cash = float(initial_capital)
    shares = 0.0
    total_cost = float(initial_capital)
    last_month = None
    n = len(prices)
    
    for i in range(n):
        price = prices[i]
        month = months[i]
        
        # 每月薪水投入
        if month != last_month:
            if last_month is not None:
                cash += monthly_add
                total_cost += monthly_add
            elif initial_capital == 0:
                cash += monthly_add
                total_cost += monthly_add
            last_month = month
            
        fgi = fgis[i]
        
        if shares > 0.0:
            if fgi > sell_th and price > 0.0:
                revenue = shares * price
                fee = revenue * fee_rate
                tax = revenue * tax_rate
                cash += (revenue - fee - tax)
                shares = 0.0
            elif cash > 0.0 and price > 0.0:
                buy_shares = cash / (price * (1.0 + fee_rate))
                shares += buy_shares
                cash = 0.0
        else:
            if fgi < buy_th and cash > 0.0 and price > 0.0:
                buy_shares = cash / (price * (1.0 + fee_rate))
                shares += buy_shares
                cash = 0.0
                
    final_val = cash + (shares * prices[-1]) if n > 0 else 0.0
    return final_val, total_cost

def run_backtest_logic(df, ticker, strategy, initial_capital, monthly_add, discount=True, buy_th=0, sell_th=0, return_trades=True):
    """
    完整回測運算邏輯：
    精準回傳每日資產曲線、詳細交易紀錄、CAGR、MDD、總報酬與交易手續費/稅金明細
    """
    cash = float(initial_capital)
    shares = 0.0
    total_cost = float(initial_capital)
    last_month = None
    
    prices = df['Close'].values
    months = df['Month'].values
    dates = df['Date'].dt.strftime('%Y-%m-%d').values
    fgis = df['FGI'].values if strategy == 'FGI' else None
    
    fee_rate = 0.001425 * (0.6 if discount else 1.0)
    tax_rate = get_tax_rate(ticker)
    
    history = []
    trade_log = []
    equity_curve = []
    
    total_fees_paid = 0.0
    total_taxes_paid = 0.0
    
    # 統計賣出勝率
    last_buy_avg_cost = 0.0
    sell_wins = 0
    sell_total = 0
    
    for i in range(len(df)):
        price = float(prices[i])
        date = dates[i]
        month = months[i]
        
        # 1. 發薪水投入
        if month != last_month:
            if last_month is not None:
                cash += float(monthly_add)
                total_cost += float(monthly_add)
            elif initial_capital == 0:
                cash += float(monthly_add)
                total_cost += float(monthly_add)
            last_month = month
            
        # 2. 交易邏輯
        if strategy == 'DCA':
            if cash > 0 and price > 0:
                buy_shares = cash / (price * (1.0 + fee_rate))
                fee = buy_shares * price * fee_rate
                total_fees_paid += fee
                
                shares += buy_shares
                cash = 0.0
                
                if return_trades:
                    trade_log.append({
                        "date": date, "action": "定期買進", "price": round(price, 2),
                        "shares": round(buy_shares, 4), "amount": round(buy_shares * price, 2),
                        "fee": round(fee, 2), "tax": 0.0
                    })
                    
        elif strategy == 'FGI':
            fgi = float(fgis[i])
            
            # 狀態 A: 持有股票中
            if shares > 0:
                # 賣出信號：全部清倉
                if fgi > sell_th and price > 0:
                    revenue = shares * price
                    fee = revenue * fee_rate
                    tax = revenue * tax_rate
                    total_fees_paid += fee
                    total_taxes_paid += tax
                    
                    cash += (revenue - fee - tax)
                    
                    # 統計賣出勝率
                    sell_total += 1
                    if price > last_buy_avg_cost:
                        sell_wins += 1
                        
                    if return_trades:
                        trade_log.append({
                            "date": date, "action": "🔴 貪婪清倉", "price": round(price, 2),
                            "shares": round(shares, 4), "amount": round(revenue, 2),
                            "fee": round(fee, 2), "tax": round(tax, 2)
                        })
                    shares = 0.0
                    
                # 持有期間，如果有新薪水進來，直接持股加碼
                elif cash > 0 and price > 0:
                    buy_shares = cash / (price * (1.0 + fee_rate))
                    fee = buy_shares * price * fee_rate
                    total_fees_paid += fee
                    
                    # 更新平均成本估算
                    last_buy_avg_cost = price
                    shares += buy_shares
                    cash = 0.0
                    
                    if return_trades:
                        trade_log.append({
                            "date": date, "action": "🟢 持股加碼", "price": round(price, 2),
                            "shares": round(buy_shares, 4), "amount": round(buy_shares * price, 2),
                            "fee": round(fee, 2), "tax": 0.0
                        })
                        
            # 狀態 B: 空手中 (等待恐慌買點)
            else:
                if fgi < buy_th and cash > 0 and price > 0:
                    buy_shares = cash / (price * (1.0 + fee_rate))
                    fee = buy_shares * price * fee_rate
                    total_fees_paid += fee
                    
                    last_buy_avg_cost = price
                    shares += buy_shares
                    cash = 0.0
                    
                    if return_trades:
                        trade_log.append({
                            "date": date, "action": "🔥 恐慌梭哈", "price": round(price, 2),
                            "shares": round(buy_shares, 4), "amount": round(buy_shares * price, 2),
                            "fee": round(fee, 2), "tax": 0.0
                        })
                        
        # 3. 記錄當日總資產
        total_asset = cash + (shares * price)
        equity_curve.append(total_asset)
        history.append({'date': date, 'value': round(total_asset, 2), 'cost': round(total_cost, 2)})
        
    final_val = history[-1]['value'] if history else 0.0
    net_profit = final_val - total_cost
    total_return_pct = (net_profit / total_cost * 100.0) if total_cost > 0 else 0.0
    
    # 年化報酬率 (CAGR)
    days_count = (pd.to_datetime(dates[-1]) - pd.to_datetime(dates[0])).days if len(dates) > 0 else 0
    years = days_count / 365.25 if days_count > 0 else 1.0
    cagr = ((final_val / total_cost) ** (1.0 / years) - 1.0) * 100.0 if total_cost > 0 and final_val > 0 else 0.0
    
    # 最大回撤 (MDD)
    mdd = calculate_mdd(equity_curve)
    
    # 勝率計算
    win_rate = (sell_wins / sell_total * 100.0) if sell_total > 0 else (100.0 if net_profit > 0 else 0.0)
    
    return {
        "final_value": final_val,
        "total_cost": total_cost,
        "net_profit": net_profit,
        "total_return_pct": total_return_pct,
        "cagr": cagr,
        "mdd": mdd,
        "win_rate": win_rate,
        "trades_count": len(trade_log),
        "total_fees": round(total_fees_paid, 2),
        "total_taxes": round(total_taxes_paid, 2),
        "history": history,
        "trades": trade_log,
        "params": f"買<{buy_th} 賣>{sell_th}" if strategy == 'FGI' else "每月定期定額",
        "buy_th": buy_th,
        "sell_th": sell_th
    }

def optimize_fgi(df, ticker, initial_capital, monthly_add, discount=True):
    """
    尋找歷史最佳 FGI 買入與賣出參數 (網格搜索)：
    買點範圍: 5 ~ 45 (間隔 5)
    賣點範圍: 55 ~ 95 (間隔 5)
    以極速純數值運算進行最佳化，最後產生完整報表
    """
    prices = df['Close'].values
    fgis = df['FGI'].values
    months = df['Month'].values
    
    fee_rate = 0.001425 * (0.6 if discount else 1.0)
    tax_rate = get_tax_rate(ticker)
    
    best_val = -1.0
    best_b, best_s = 20, 80
    
    buy_range = range(5, 50, 5)
    sell_range = range(95, 50, -5)
    
    for b in buy_range:
        for s in sell_range:
            if s > b:
                val, _ = simulate_fast(
                    prices, fgis, months,
                    initial_capital, monthly_add,
                    fee_rate, tax_rate, b, s
                )
                if val > best_val:
                    best_val = val
                    best_b, best_s = b, s
                    
    # 找到最佳參數後，生成完整交易日誌與走勢圖
    best_result = run_backtest_logic(
        df, ticker, 'FGI',
        initial_capital, monthly_add,
        discount=discount,
        buy_th=best_b, sell_th=best_s,
        return_trades=True
    )
    return best_result
