import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
from datetime import datetime
import json
import random
from bs4 import BeautifulSoup 
import re # 新增正則表達式處理

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
        data = yf.download(tickers, period="5d", interval="5m", progress=False)
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
        st.error(f"Yahoo Finance 數據獲取失敗: {e}")
        return None

def get_shanghai_gold():
    """
    爬取上海金價 (多源備援策略)
    1. jinjia.vip
    2. dyhjw.com (第一黃金網)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # --- Source 1: jinjia.vip ---
    try:
        url = "https://www.jinjia.vip/Shanghai/"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'lxml')
            # 策略：尋找所有包含 Au99.99 的元件，然後找它附近的數字
            # 有時候 Au99.99 寫法可能是 Au9999
            targets = soup.find_all(string=re.compile(r"Au99\.?99"))
            
            for target in targets:
                # 往上找父節點 td 或 tr
                parent_td = target.find_parent('td')
                if parent_td:
                    # 找下一個 td (通常是價格)
                    next_td = parent_td.find_next_sibling('td')
                    if next_td:
                        try:
                            price_text = next_td.get_text().strip()
                            price = float(price_text)
                            if 400 < price < 1000:
                                return price
                        except ValueError:
                            # 如果下一個不是，再下一個 (有時候中間有開盤價)
                            continue
    except Exception as e:
        print(f"Jinjia failed: {e}")

    # --- Source 2: 第一黃金網 (dyhjw.com) ---
    try:
        url2 = "http://www.dyhjw.com/gold/shanghai.html"
        resp2 = requests.get(url2, headers=headers, timeout=5)
        resp2.encoding = "utf-8" # 強制編碼
        if resp2.status_code == 200:
            soup2 = BeautifulSoup(resp2.text, 'lxml')
            # 尋找表格行
            rows = soup2.find_all('tr')
            for row in rows:
                text = row.get_text()
                if "Au99.99" in text or "Au9999" in text:
                    cols = row.find_all('td')
                    for col in cols:
                        try:
                            # 尋找像價格的欄位
                            val_str = col.get_text().strip()
                            val = float(val_str)
                            if 400 < val < 1000:
                                return val
                        except ValueError:
                            continue
    except Exception as e:
        print(f"Dyhjw failed: {e}")

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

def get_cnh_hibor():
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
            diff_per_gram_cny = sh_gold - gold_intl_cny_g
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
    st.markdown("數據來源：Yahoo Finance, jinjia.vip/dyhjw (爬蟲), Binance P2P")
    
    if st.button('🔄 立即更新數據'):
        st.cache_data.clear()
        st.rerun()

    with st.spinner('正在掃描全球市場...'):
        yahoo_data = get_yahoo_data()
        sh_gold = get_shanghai_gold()
        usdt_cny = get_binance_usdt_cny()
        hibor = None 
        
        hibor_display = "N/A"
        hibor_val = 2.5

    if not yahoo_data:
        st.error("Yahoo Finance 連線失敗")
        return

    metrics = calculate_metrics(yahoo_data, sh_gold, usdt_cny)
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
            value=f"${premium_val:.2f}" if sh_gold else "N/A",
            delta="警戒 > $30",
            delta_color="inverse" if premium_val > 30 else "normal"
        )
        if sh_gold:
            st.caption(f"上海金: ¥{metrics['sh_gold']}/g")
        else:
            st.caption("⚠️ 爬蟲未能獲取上海金價，可能是網站反爬或連線問題")

        usdt_p = metrics['usdt_premium']
        st.metric(
            label="USDT 溢價",
            value=f"{usdt_p:.2f}%" if usdt_cny else "N/A",
            delta="警戒 > 2%",
            delta_color="inverse" if usdt_p > 2 else "normal"
        )
        st.metric(label="港幣 (HKD)", value=f"{metrics['hkd']:.4f}", delta="弱方 7.85", delta_color="inverse" if metrics['hkd'] > 7.84 else "off")

    # 2. 防守期
    with col2:
        st.markdown("### 2. 防守期")
        st.metric(label="離岸人民幣 (CNH)", value=f"{metrics['cnh']:.4f}", delta="關鍵 7.35", delta_color="inverse" if metrics['cnh'] > 7.30 else "normal")
        spr = metrics['spread']
        st.metric(label="價差 (Spread)", value=f"{spr:.0f} pips", delta="警戒 > 500", delta_color="inverse" if spr > 500 else "normal")
        st.metric(label="HIBOR O/N", value=hibor_display, delta="警戒 > 5%", help="需手動查詢")

    # 3. 操作期
    with col3:
        st.markdown("### 3. 操作期")
        check_1 = metrics['cnh'] > 7.30
        check_2 = metrics['spread'] > 500
        check_3 = metrics['gold_premium'] > 30
        st.checkbox("CNH > 7.30", value=check_1, disabled=True)
        st.checkbox("Spread > 500", value=check_2, disabled=True)
        st.checkbox("資金外逃跡象", value=check_3, disabled=True)
        if check_1 and check_2: st.error("🚨 趨勢確立")
        else: st.info("✋ 觀望中")

    st.markdown("---")
    st.caption(f"更新時間: {metrics['timestamp'].strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()
