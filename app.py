import os
import sys
import datetime
import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from backtest_logic import (
    get_ticker_code,
    run_backtest_logic,
    optimize_fgi,
    NAME_TO_TICKER
)

# 解決 Windows 終端機編碼
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(
    page_title="FGI 恐懼貪婪智慧回測實驗室",
    page_icon="📈",
    layout="wide"
)

st.title("📈 恐懼與貪婪指數 (FGI) 智慧回測系統")
st.markdown("結合市場情緒指標週期 × 定期定額 (DCA) × 真實交易手續費與稅率精算")

# 側邊欄設定
with st.sidebar:
    st.header("⚙️ 參數設定")
    
    st.subheader("💰 資金計畫")
    initial_capital = st.number_input("初始本金 (元)", value=100000, step=10000)
    monthly_add = st.number_input("每月投入薪水 (元)", value=10000, step=1000)
    
    st.subheader("📅 回測時間範圍")
    start_date = st.date_input("開始日期", datetime.date(2011, 1, 3))
    end_date = st.date_input("結束日期", datetime.date.today())
    
    st.subheader("🎯 投資標的")
    default_tickers = "0050, 台積電, SPY"
    tickers_input = st.text_area("輸入代號或名稱 (逗號隔開)", value=default_tickers)
    tickers = [t.strip() for t in tickers_input.split(",") if t.strip()]
    
    st.subheader("⚖️ 交易成本")
    discount = st.checkbox("啟用券商手續費 6 折 (0.0855%)", value=True)
    
    st.subheader("🧠 策略設定")
    run_dca = st.checkbox("定期定額 (DCA)", value=True)
    run_fgi = st.checkbox("FGI 混合戰法", value=True)
    
    fgi_mode = st.radio("FGI 參數模式", ["🤖 自動尋找最佳參數", "✍️ 自訂固定門檻"])
    manual_buy = 20
    manual_sell = 80
    if fgi_mode == "✍️ 自訂固定門檻":
        manual_buy = st.slider("恐慌買入點 (小於)", 5, 50, 20, 5)
        manual_sell = st.slider("貪婪賣出點 (大於)", 50, 95, 80, 5)
        
    run_btn = st.button("🚀 開始回測", type="primary", use_container_width=True)

@st.cache_data(ttl=3600)
def load_all_data(ticker_list, s_date, e_date):
    """載入 FGI 與股價數據，並進行合併"""
    fgi_file = os.path.join(BASE_DIR, "FGI_all.csv")
    if not os.path.exists(fgi_file):
        fgi_file = os.path.join(BASE_DIR, "FGI_Final_Complete.csv")
    if not os.path.exists(fgi_file):
        fgi_file = os.path.join(BASE_DIR, "FGI_Final.csv")
        
    if not os.path.exists(fgi_file):
        return None, "找不到 FGI 歷史數據檔案！"
        
    df_fgi = pd.read_csv(fgi_file)
    df_fgi.columns = df_fgi.columns.str.strip()
    df_fgi['Date'] = pd.to_datetime(df_fgi['Date'])
    
    merged_dict = {}
    errors = []
    
    for t_name in ticker_list:
        code = get_ticker_code(t_name)
        try:
            e_str = (pd.to_datetime(e_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            raw = yf.download(code, start="2010-01-01", end=e_str, progress=False)['Close']
            if isinstance(raw, pd.DataFrame):
                if raw.shape[1] > 0: raw = raw.iloc[:, 0]
                else: continue
            raw = raw.ffill().dropna()
            stock_df = raw.reset_index()
            stock_df.columns = ['Date', 'Close']
            stock_df['Date'] = pd.to_datetime(stock_df['Date']).dt.tz_localize(None)
            
            df = pd.merge(df_fgi, stock_df, on='Date', how='right')
            df['FGI'] = df['FGI'].ffill()
            df = df.dropna(subset=['FGI', 'Close'])
            df = df[(df['Date'] >= pd.to_datetime(s_date)) & (df['Date'] <= pd.to_datetime(e_date))]
            df = df.reset_index(drop=True)
            df['Month'] = df['Date'].dt.to_period('M')
            
            if not df.empty:
                merged_dict[t_name] = (code, df)
            else:
                errors.append(f"{t_name} 資料在指定區間為空")
        except Exception as e:
            errors.append(f"抓取 {t_name} 失敗: {e}")
            
    return merged_dict, "; ".join(errors)

if run_btn:
    if not tickers:
        st.warning("請至少輸入一個標的！")
    else:
        with st.spinner("正在下載行情數據並運算中..."):
            stock_data_map, err_msg = load_all_data(tickers, start_date, end_date)
            if not stock_data_map:
                st.error(f"數據載入失敗: {err_msg}")
            else:
                summary_data = []
                tabs = st.tabs(list(stock_data_map.keys()))
                
                for idx, (t_name, (code, df)) in enumerate(stock_data_map.items()):
                    with tabs[idx]:
                        st.subheader(f"📊 {t_name} ({code}) 策略成果")
                        
                        strategies_res = []
                        if run_dca:
                            res_dca = run_backtest_logic(df, code, 'DCA', initial_capital, monthly_add, discount)
                            res_dca['type'] = '定期定額 (DCA)'
                            strategies_res.append(res_dca)
                            
                        if run_fgi:
                            if "自動" in fgi_mode:
                                res_fgi = optimize_fgi(df, code, initial_capital, monthly_add, discount)
                                res_fgi['type'] = f"FGI 最佳策略 (買<{res_fgi['buy_th']}/賣>{res_fgi['sell_th']})"
                            else:
                                res_fgi = run_backtest_logic(df, code, 'FGI', initial_capital, monthly_add, discount, manual_buy, manual_sell)
                                res_fgi['type'] = f"FGI 自訂策略 (買<{manual_buy}/賣>{manual_sell})"
                            strategies_res.append(res_fgi)
                            
                        # 指標卡片
                        cols = st.columns(len(strategies_res))
                        for c_i, s in enumerate(strategies_res):
                            with cols[c_i]:
                                st.metric(
                                    label=s['type'],
                                    value=f"${s['final_value']:,.0f}",
                                    delta=f"報酬率 {s['total_return_pct']:+.1f}% (CAGR {s['cagr']:.1f}%)"
                                )
                                st.caption(f"總成本: ${s['total_cost']:,.0f} | MDD: {s['mdd']:.1f}% | 交易: {s['trades_count']} 次")
                                
                        # 走勢圖
                        fig = go.Figure()
                        for s in strategies_res:
                            dates = [h['date'] for h in s['history']]
                            vals = [h['value'] for h in s['history']]
                            fig.add_trace(go.Scatter(x=dates, y=vals, mode='lines', name=s['type']))
                            
                        # 加入成本線
                        cost_vals = [h['cost'] for h in strategies_res[0]['history']]
                        dates_0 = [h['date'] for h in strategies_res[0]['history']]
                        fig.add_trace(go.Scatter(x=dates_0, y=cost_vals, mode='lines', name='投入成本線', line=dict(dash='dash', color='gray')))
                        
                        fig.update_layout(
                            title=f"{t_name} 資產累積與策略對決走勢圖",
                            xaxis_title="日期",
                            yaxis_title="總資產 (元)",
                            template="plotly_dark",
                            hovermode="x unified"
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        
                        # 交易明細
                        for s in strategies_res:
                            with st.expander(f"📜 檢視 {s['type']} 交易流水帳 ({len(s['trades'])} 筆)"):
                                if s['trades']:
                                    st.dataframe(pd.DataFrame(s['trades']), use_container_width=True)
                                else:
                                    st.write("無交易紀錄")
                                    
                        # 整理天梯榜數據
                        dca_strat = next((s for s in strategies_res if 'DCA' in s['type']), None)
                        fgi_strat = next((s for s in strategies_res if 'FGI' in s['type']), None)
                        if dca_strat and fgi_strat:
                            winner = "🏆 FGI" if fgi_strat['final_value'] > dca_strat['final_value'] else "📊 DCA"
                            diff = fgi_strat['final_value'] - dca_strat['final_value']
                            summary_data.append({
                                "標的": t_name,
                                "贏家": winner,
                                "超額獲利差": f"${diff:+,.0f}",
                                "DCA 最終資產": f"${dca_strat['final_value']:,.0f}",
                                "DCA 總報酬": f"{dca_strat['total_return_pct']:.1f}%",
                                "FGI 最終資產": f"${fgi_strat['final_value']:,.0f}",
                                "FGI 總報酬": f"{fgi_strat['total_return_pct']:.1f}%",
                                "FGI 最佳參數": fgi_strat['params']
                            })
                            
                # 總天梯排行榜
                if summary_data:
                    st.divider()
                    st.subheader("🏆 綜合回測天梯榜")
                    st.dataframe(pd.DataFrame(summary_data), use_container_width=True)
