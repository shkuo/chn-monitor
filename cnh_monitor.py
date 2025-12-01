import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
from datetime import datetime
import json
import random
import re 

# --- 設定頁面 ---
st.set_page_config(
    page_title="CNH 爆貶戰情監控室",
    page_icon="🇨🇳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 數據抓取模組 ---

@st.cache_data(ttl=60)
def get_yahoo_data():
    """從 Yahoo Finance 獲取基礎匯率與金價"""
    tickers = ["CNY=X", "CNH=X", "HKD=X", "GC=F"]
    try:
        # 增加 timeout 防止卡死
        data = yf.download(tickers, period="5d", interval="5m", progress=False, timeout=10)
        result = {}
        df_close = data['Close']
        for t in tickers:
            try:
                if t in df_close.columns:
                    last_valid = df_close[t].dropna().iloc[-1]
                    result[t] = float(last_valid)
                else:
                    col_name = [c for c in df_close.columns if t.replace('=X','') in c]
                    if col_name:
                         last_valid = df_close[col_name[0]].dropna().iloc[-1]
                         result[t] = float(last_valid)
            except Exception as e:
                result[t] = None

        final_data = {
            'cny': result.get("CNY=X"),
            'cnh': result.get("CNH=X"),
            'hkd': result.get("HKD=X"),
            'gold_intl': result.get("GC=F")
        }
        if None in final_data.values():
            return None
        return final_data
    except Exception as e:
        # st.error(f"Yahoo Finance 數據獲取失敗: {e}")
        return None

def get_shanghai_gold():
    """
    爬取上海金價 (三層備援策略)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/"
    }
    
    # --- Source 1: 新浪財經 API (Sina) ---
    try:
        url_sina = "https://hq.sinajs.cn/list=gds_Au99_99"
        resp = requests.get(url_sina, headers=headers, timeout=2)
        if resp.status_code == 200 and '="' in resp.text:
            data_str = resp.text.split('="')[1].split('"')[0]
            data_parts = data_str.split(',')
            price = float(data_parts[0])
            if price == 0 and len(data_parts) > 7: price = float(data_parts[7])
            if price > 0: return price
    except Exception:
        pass

    # --- Source 2: 騰訊財經 API (Tencent) ---
    try:
        url_tencent = "https://qt.gtimg.cn/q=SGE_AU9999"
        resp = requests.get(url_tencent, headers=headers, timeout=2)
        if resp.status_code == 200 and '="' in resp.text:
            data_str = resp.text.split('="')[1].split('"')[0]
            data_parts = data_str.split('~')
            if len(data_parts) > 3:
                price = float(data_parts[3])
                if price > 0: return price
    except Exception:
        pass

    # --- Source 3: 東方財富 API (Eastmoney) ---
    try:
        url_east = "https://push2.eastmoney.com/api/qt/stock/get?secid=113.Au99.99&fields=f43"
        resp = requests.get(url_east, headers=headers, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data and data.get("data"):
                price = data["data"].get("f43")
                if price != "-":
                    return float(price)
    except Exception:
        pass

    return None

def get_binance_usdt_cny():
    """
    嘗試從幣安 P2P API 獲取 USDT/CNY 買單價格
    """
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    payload = {
        "page": 1, "rows": 5,
        "payTypes": [], "asset": "USDT", "tradeType": "BUY",
        "fiat": "CNY", "publisherType": None
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data['data']:
                price = float(data['data'][0]['adv']['price'])
                return price
    except Exception as e:
        pass
    return None

# --- 核心邏輯 ---

def calculate_metrics(yahoo_data, sh_gold, usdt_cny):
    if not yahoo_data:
        return None

    cny = yahoo_data['cny']
    cnh = yahoo_data['cnh']
    hkd = yahoo_data['hkd']
    gold_intl_usd = yahoo_data['gold_intl']

    # 1. 價差
    spread = (cnh - cny) * 10000 if cnh and cny else 0

    # 2. 黃金溢價
    gold_premium = 0
    gold_intl_cny_g = 0
    if gold_intl_usd and cny:
        # 換算公式: 國際金價(USD/oz) / 31.1035 * 匯率(CNY) = 國際金價(CNY/g)
        gold_intl_cny_g = (gold_intl_usd / 31.1035) * cny
        
        if sh_gold:
            # 溢價(USD/oz) = (上海金價(CNY/g) - 國際金價(CNY/g)) / 匯率 * 31.1035
            # 計算每克的人民幣價差
            diff_per_gram_cny = sh_gold - gold_intl_cny_g
            # 換算回每盎司美元
            gold_premium = (diff_per_gram_cny / cny) * 31.1035

    # 3. USDT 溢價
    usdt_premium_pct = 0
    if usdt_cny and cnh:
        usdt_premium_pct = ((usdt_cny - cnh) / cnh) * 100

    return {
        "cny": cny,
        "cnh": cnh,
        "hkd": hkd,
        "spread": spread,
        "gold_intl_usd": gold_intl_usd,
        "sh_gold": sh_gold,
        "gold_premium": gold_premium,
        "usdt_cny": usdt_cny,
        "usdt_premium": usdt_premium_pct,
        "timestamp": datetime.now()
    }

def analyze_risk(metrics, hibor_val):
    risk_report = {"level": "normal", "msg": "目前指標平穩，維持觀望。", "color": "green"}
    if not metrics: return risk_report

    is_spread_high = metrics['spread'] > 500
    is_spread_critical = metrics['spread'] > 1000
    is_cnh_breakout = metrics['cnh'] > 7.35
    is_capital_flight = metrics['gold_premium'] > 30 or metrics['usdt_premium'] > 2.0
    is_hibor_squeeze = hibor_val is not None and hibor_val > 10

    if is_hibor_squeeze:
        risk_report = {"level": "critical", "msg": "⚠️ 緊急撤退 (Emergency Exit)：流動性夾殺中", "color": "purple"}
    elif is_cnh_breakout and is_spread_critical:
        risk_report = {"level": "critical", "msg": "🔥 全力行動 (Full Action)：防線潰決", "color": "red"}
    elif is_spread_high or is_capital_flight:
        risk_report = {"level": "warning", "msg": "🛡️ 高度警戒 (High Alert)：資金外逃跡象", "color": "orange"}
    return risk_report

# --- UI 渲染 ---

def main():
    st.title("🇨🇳 CNH 爆貶戰情監控室 (Python Live Ver.)")
    st.markdown("數據來源：Yahoo Finance, (API) 新浪/騰訊/東方財富, Binance P2P")
    
    # --- 側邊欄手動輸入區 ---
    with st.sidebar:
        st.header("🔧 手動數據輸入")
        st.caption("若 API 抓取失敗，請在此輸入數據以啟用計算。")
        
        manual_sh_gold = st.number_input(
            "上海金價 (Au99.99, CNY/g)", 
            min_value=0.0, 
            value=0.0, 
            step=0.1, 
            format="%.2f",
            help="輸入人民幣/克，例如 620.50"
        )
        
        manual_hibor = st.number_input(
            "CNH HIBOR (%)", 
            min_value=0.0, 
            value=0.0, 
            step=0.1, 
            format="%.2f",
            help="離岸人民幣隔夜拆息"
        )
        
        st.markdown("---")
        if st.button('🔄 立即更新數據'):
            st.cache_data.clear()
            st.rerun()

    # --- 數據獲取 ---
    with st.spinner('正在掃描全球市場...'):
        yahoo_data = get_yahoo_data()
        sh_gold_scraped = get_shanghai_gold()
        usdt_cny = get_binance_usdt_cny()
        
        # --- 黃金價格邏輯：手動 > 爬蟲 ---
        if manual_sh_gold > 0:
            final_sh_gold = manual_sh_gold
            gold_source = "(手動)"
        else:
            final_sh_gold = sh_gold_scraped
            gold_source = "(API)"
            
        # --- HIBOR 邏輯：手動 > 預設 ---
        if manual_hibor > 0:
            hibor_val = manual_hibor
            hibor_display = f"{manual_hibor}% (手動)"
        else:
            hibor_val = 2.5 # 預設值
            hibor_display = "N/A (API 無數據)"

    if not yahoo_data:
        st.error("Yahoo Finance 連線失敗")
        if not final_sh_gold:
             return

    metrics = calculate_metrics(yahoo_data, final_sh_gold, usdt_cny)
    risk = analyze_risk(metrics, hibor_val)

    st.markdown("---")
    st.subheader(f"戰略建議：{risk['msg']}")
    if risk['color'] == "red": st.error(risk['msg'])
    elif risk['color'] == "orange": st.warning(risk['msg'])
    else: st.success(risk['msg'])
    st.markdown("---")

    col1, col2, col3 = st.columns(3)

    # 1. 潛伏期
    with col1:
        st.markdown("### 1. 潛伏期")
        premium_val = metrics['gold_premium']
        
        st.metric(
            label="上海金價溢價 (USD/oz)",
            value=f"${premium_val:.2f}" if final_sh_gold and yahoo_data else "N/A",
            delta="警戒 > $30",
            delta_color="inverse" if premium_val > 30 else "normal"
        )
        
        if final_sh_gold:
            st.caption(f"上海金: ¥{final_sh_gold:.2f}/g {gold_source}")
            if yahoo_data:
                intl_g = (metrics['gold_intl_usd']/31.1035*metrics['cny'])
                st.caption(f"國際折算: ¥{intl_g:.2f}/g")
        else:
            st.warning("⚠️ 無法獲取上海金價，請在側邊欄手動輸入")

        usdt_p = metrics['usdt_premium']
        st.metric(
            label="USDT 溢價",
            value=f"{usdt_p:.2f}%" if usdt_cny and yahoo_data else "N/A",
            delta="警戒 > 2%",
            delta_color="inverse" if usdt_p > 2 else "normal"
        )
        if yahoo_data:
             st.metric(label="港幣 (HKD)", value=f"{metrics['hkd']:.4f}", delta="弱方 7.85", delta_color="inverse" if metrics['hkd'] > 7.84 else "off")

    # 2. 防守期
    with col2:
        st.markdown("### 2. 防守期")
        if yahoo_data:
            st.metric(label="離岸人民幣 (CNH)", value=f"{metrics['cnh']:.4f}", delta="關鍵 7.35", delta_color="inverse" if metrics['cnh'] > 7.30 else "normal")
            spr = metrics['spread']
            st.metric(label="價差 (Spread)", value=f"{spr:.0f} pips", delta="警戒 > 500", delta_color="inverse" if spr > 500 else "normal")
        st.metric(label="HIBOR O/N", value=hibor_display, delta="警戒 > 5%", help="需手動查詢")

    # 3. 操作期
    with col3:
        st.markdown("### 3. 操作期")
        check_1 = metrics['cnh'] > 7.30 if metrics else False
        check_2 = metrics['spread'] > 500 if metrics else False
        check_3 = metrics['gold_premium'] > 30 if metrics else False
        
        st.checkbox("CNH > 7.30", value=check_1, disabled=True)
        st.checkbox("Spread > 500", value=check_2, disabled=True)
        st.checkbox("資金外逃跡象", value=check_3, disabled=True)
        if check_1 and check_2: st.error("🚨 趨勢確立")
        else: st.info("✋ 觀望中")

    st.markdown("---")
    if metrics:
        st.caption(f"更新時間: {metrics['timestamp'].strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()
