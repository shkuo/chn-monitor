import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
from datetime import datetime
import json
import random
from bs4 import BeautifulSoup # 新增 BeautifulSoup 用於解析網頁

# --- 設定頁面 ---
st.set_page_config(
    page_title="CNH 爆貶戰情監控室",
    page_icon="🇨🇳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 數據抓取模組 ---

@st.cache_data(ttl=60)  # 設定緩存 60 秒
def get_yahoo_data():
    """從 Yahoo Finance 獲取基礎匯率與金價 (修正 NaN 問題)"""
    tickers = ["CNY=X", "CNH=X", "HKD=X", "GC=F"]
    try:
        # 改用 5天 數據確保一定有資料，interval 改為 15m 或 5m 稍微穩定一點，避免 1m 的空缺
        data = yf.download(tickers, period="5d", interval="5m", progress=False)
        
        result = {}
        # 處理 yfinance 格式 (Close 欄位)
        df_close = data['Close']

        # 針對每一個 ticker 抓取「最後一個非空值」 (Last valid value)
        for t in tickers:
            try:
                # dropna() 確保我們不會抓到最新一分鐘的 NaN
                if t in df_close.columns:
                    last_valid = df_close[t].dropna().iloc[-1]
                    result[t] = float(last_valid) # 轉為 float 確保計算正常
                else:
                    # 有時候 yfinance 欄位名稱不會帶 =X (視版本而定)
                    # 這裡做一個簡單的 fallback 搜尋
                    col_name = [c for c in df_close.columns if t.replace('=X','') in c]
                    if col_name:
                         last_valid = df_close[col_name[0]].dropna().iloc[-1]
                         result[t] = float(last_valid)
            except Exception as e:
                print(f"Error extracting {t}: {e}")
                result[t] = None

        # 映射回我們需要的 key 名稱
        final_data = {
            'cny': result.get("CNY=X"),
            'cnh': result.get("CNH=X"),
            'hkd': result.get("HKD=X"),
            'gold_intl': result.get("GC=F")
        }
        
        # 檢查是否有 None，如果有則回傳 None 讓 UI 顯示錯誤
        if None in final_data.values():
            return None
            
        return final_data

    except Exception as e:
        st.error(f"Yahoo Finance 數據獲取失敗: {e}")
        return None

def get_shanghai_gold():
    """
    爬取上海金價
    策略: 爬取 jinjia.vip (金價VIP) 的上海金價表格
    目標 URL: https://www.jinjia.vip/Shanghai/
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 嘗試: jinjia.vip
    try:
        url = "https://www.jinjia.vip/Shanghai/"
        resp = requests.get(url, headers=headers, timeout=5)
        
        if resp.status_code == 200:
            # 使用 BeautifulSoup 解析 HTML
            soup = BeautifulSoup(resp.text, 'lxml')
            
            # 尋找頁面中的表格行 (tr)
            rows = soup.find_all('tr')
            
            for row in rows:
                text = row.get_text()
                # 尋找包含目標品種名稱的行
                if "Au99.99" in text or "Au9999" in text:
                    # 找到該行的所有儲存格 (td)
                    cols = row.find_all('td')
                    
                    # 遍歷欄位，尋找像價格的數字
                    # 通常表格結構是: 品種 | 最新價 | 開盤 | ...
                    for col in cols:
                        try:
                            val_str = col.get_text().strip()
                            # 嘗試轉換為浮點數
                            val = float(val_str)
                            # 簡單過濾：目前的金價(人民幣/克)大約在 400~900 之間
                            if 400 < val < 1000:
                                return val
                        except ValueError:
                            continue
    except Exception as e:
        print(f"Jinjia scrape error: {e}")
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

    # 1. 價差 (Spread in pips)
    if cnh and cny:
        spread = (cnh - cny) * 10000
    else:
        spread = 0

    # 2. 黃金溢價
    gold_premium = 0
    gold_intl_cny_g = 0
    if gold_intl_usd and cny:
        gold_intl_cny_g = (gold_intl_usd / 31.1035) * cny
        if sh_gold:
            # 顯示每盎司美元價差
            gold_premium = (sh_gold / cny * 31.1035) - gold_intl_usd 

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
    
    if not metrics:
        return risk_report

    # 邏輯判斷
    is_spread_high = metrics['spread'] > 500
    is_spread_critical = metrics['spread'] > 1000
    is_cnh_breakout = metrics['cnh'] > 7.35
    is_capital_flight = metrics['gold_premium'] > 30 or metrics['usdt_premium'] > 2.0
    is_hibor_squeeze = hibor_val is not None and hibor_val > 10

    if is_hibor_squeeze:
        risk_report = {
            "level": "critical", 
            "msg": "⚠️ 緊急撤退 (Emergency Exit)：偵測到流動性夾殺 (HIBOR 飆高)，央行暴力干預中。停止做空，保留現金。",
            "color": "purple"
        }
    elif is_cnh_breakout and is_spread_critical:
        risk_report = {
            "level": "critical", 
            "msg": "🔥 全力行動 (Full Action)：匯率突破 7.35 且價差失控 (>1000點)。趨勢確立，分批轉移資產。",
            "color": "red"
        }
    elif is_spread_high or is_capital_flight:
        risk_report = {
            "level": "warning", 
            "msg": "🛡️ 高度警戒 (High Alert)：偵測到聰明錢外逃或做空壓力增加。密切監控 7.35 關卡。",
            "color": "orange"
        }

    return risk_report

# --- UI 渲染 ---

def main():
    # Header
    st.title("🇨🇳 CNH 爆貶戰情監控室 (Python Live Ver.)")
    st.markdown("數據來源：Yahoo Finance (API), jinjia.vip (爬蟲), Binance P2P (爬蟲)")
    
    if st.button('🔄 立即更新數據'):
        st.cache_data.clear()
        st.rerun()

    # 獲取數據
    with st.spinner('正在連線全球金融市場...'):
        yahoo_data = get_yahoo_data()
        sh_gold = get_shanghai_gold()
        usdt_cny = get_binance_usdt_cny()
        hibor = get_cnh_hibor() 
        
        hibor_display = hibor if hibor else "N/A (需手動查詢)"
        hibor_val_for_logic = hibor if hibor else 2.5 

    if not yahoo_data:
        st.error("無法連接 Yahoo Finance，數據源暫時無法使用。")
        return

    # 計算指標
    metrics = calculate_metrics(yahoo_data, sh_gold, usdt_cny)
    risk = analyze_risk(metrics, hibor_val_for_logic)

    # --- 戰情總結 ---
    st.markdown("---")
    st.subheader(f"當前戰略建議：{risk['msg']}")
    if risk['color'] == "red":
        st.error(risk['msg'])
    elif risk['color'] == "orange":
        st.warning(risk['msg'])
    elif risk['color'] == "purple":
        st.info(risk['msg'])
    else:
        st.success(risk['msg'])
    st.markdown("---")

    # --- 三大階段儀表板 ---
    col1, col2, col3 = st.columns(3)

    # 第一階段：潛伏期
    with col1:
        st.markdown("### 1. 潛伏期 (資金外逃)")
        
        # 黃金
        premium_val = metrics['gold_premium']
        p_color = "normal"
        if premium_val > 50: p_color = "inverse"
        
        st.metric(
            label="上海金價溢價 (USD/oz)",
            value=f"${premium_val:.2f}" if sh_gold else "N/A",
            delta="警戒值 > $30",
            delta_color="inverse" if premium_val > 30 else "normal",
            help="正值代表中國國內金價高於國際，資金搶購實物。"
        )
        if sh_gold:
            st.caption(f"SGE金價: ¥{metrics['sh_gold']}/g | 國際折算: ¥{(metrics['gold_intl_usd']/31.1035*metrics['cny']):.2f}/g")

        # USDT
        usdt_p = metrics['usdt_premium']
        st.metric(
            label="USDT 溢價 (Crypto)",
            value=f"{usdt_p:.2f}%" if usdt_cny else "N/A",
            delta="警戒值 > 2%",
            delta_color="inverse" if usdt_p > 2 else "normal",
            help="地下資金通道擁擠程度。"
        )
        if usdt_cny:
            st.caption(f"Binance P2P: ¥{metrics['usdt_cny']} | 基準匯率: ¥{metrics['cnh']:.4f}")

        # 港幣
        st.metric(
            label="港幣匯率 (USD/HKD)",
            value=f"{metrics['hkd']:.4f}",
            delta="弱方保證 7.85",
            delta_color="off" if metrics['hkd'] < 7.84 else "inverse"
        )

    # 第二階段：防守期
    with col2:
        st.markdown("### 2. 防守期 (央行博弈)")
        
        # CNH
        st.metric(
            label="離岸人民幣 (CNH)",
            value=f"{metrics['cnh']:.4f}",
            delta="關鍵位 7.35",
            delta_color="inverse" if metrics['cnh'] > 7.30 else "normal"
        )

        # Spread
        spr = metrics['spread']
        st.metric(
            label="在離岸價差 (Spread)",
            value=f"{spr:.0f} pips",
            delta="警戒值 > 500",
            delta_color="inverse" if spr > 500 else "normal",
            help="正值越大，代表海外做空力量越強。"
        )
        st.caption(f"CNY (在岸): {metrics['cny']:.4f}")

        # HIBOR
        st.metric(
            label="離岸資金成本 (HIBOR O/N)",
            value=hibor_display,
            delta="警戒值 > 5%",
            delta_color="off",
            help="若飆升代表央行抽銀根夾殺空頭。"
        )

    # 第三階段：操作期
    with col3:
        st.markdown("### 3. 操作期 (扣板機)")
        
        check_1 = metrics['cnh'] > 7.30
        check_2 = metrics['spread'] > 500
        check_3 = metrics['gold_premium'] > 30
        
        st.markdown("**操作檢核表：**")
        st.checkbox("CNH 突破 7.30", value=check_1, disabled=True)
        st.checkbox("價差擴大 > 500點", value=check_2, disabled=True)
        st.checkbox("黃金/USDT 異常溢價", value=check_3, disabled=True)
        
        if check_1 and check_2:
            st.error("🚨 趨勢確立：建議執行資產美元化")
        else:
            st.info("✋ 條件未滿足：保持觀望")

    st.markdown("---")
    st.caption(f"最後更新時間: {metrics['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
    st.caption("免責聲明：數據源可能會有延遲或 N/A，請以專業平台為準。")

if __name__ == "__main__":
    main()
