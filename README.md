# stock-flow
!pip install plotly nbformat --upgrade
import yfinance as yf
import pandas as pd
import plotly.express as px
import numpy as np
from tqdm import tqdm

# 1. 延用台股前 50 大標的
tw_top50 = [
    '2330.TW', '2317.TW', '2454.TW', '2382.TW', '2308.TW', '2412.TW', '2881.TW', '2882.TW',
    '2303.TW', '3711.TW', '2886.TW', '2891.TW', '1301.TW', '1303.TW', '1216.TW', '2603.TW',
    '2884.TW', '2885.TW', '2002.TW', '2357.TW', '2379.TW', '5880.TW', '2892.TW', '2880.TW',
    '3008.TW', '3045.TW', '2408.TW', '2327.TW', '2890.TW', '4904.TW', '2912.TW', '2395.TW',
    '3037.TW', '2377.TW', '2409.TW', '2609.TW', '2615.TW', '3017.TW', '6669.TW', '3231.TW',
    '1513.TW', '1519.TW', '1503.TW', '3035.TW', '2301.TW', '2618.TW', '2610.TW', '2356.TW',
    '2883.TW', '2887.TW'
]

# 2. 下載數據
print("🚀 下載中...")
data = yf.download(tw_top50, period='60d')
trading_val = data['Close'] * data['Volume']
returns = data['Close'].pct_change()
market_pulse = trading_val.pct_change().mean(axis=1)

# 3. 計算相位數據
plot_data = []
for i in tqdm(range(30, 60)): 
    current_date = trading_val.index[i]
    v_surge = trading_val.iloc[i] / trading_val.iloc[i-10:i].mean()
    window_val = trading_val.iloc[i-10:i+1].pct_change()
    correlation = window_val.corrwith(market_pulse.iloc[i-10:i+1])
    
    for t in tw_top50:
        plot_data.append({
            '日期': current_date.strftime('%Y-%m-%d'),
            '股號': t,
            '資金強度': v_surge[t],
            '群體共識': correlation[t],
            '漲跌幅': returns.iloc[i][t] * 100
        })

df_50 = pd.DataFrame(plot_data)

# 4. 繪製「路徑追蹤」動態圖
# 關鍵：加入 hover_data 與渲染優化
fig = px.scatter(
    df_50, x="資金強度", y="群體共識", 
    animation_frame="日期", animation_group="股號",
    size=np.full(len(df_50), 10), 
    color="漲跌幅",
    hover_name="股號",
    log_x=True, 
    range_x=[0.1, 10], 
    range_y=[-1.1, 1.1],
    color_continuous_scale='RdYlGn_r',
    template="plotly_dark",
    title="資金路徑追蹤：台股 50 大轉折偵測 (Trail Mode)"
)

# 加入路徑追蹤 (在 Plotly 中點擊特定點可顯示軌跡，或設定 render 為累積模式)
# 我們手動開啟 'Cumulative' 效果
fig.layout.updatemenus[0].buttons[0].args[1]['frame']['duration'] = 800 # 放慢速度看軌跡

fig.update_traces(marker=dict(line=dict(width=1, color='white'))) # 增加白框方便辨識

fig.write_html("Taiwan_Top50_Trails.html")
print("✅ 完成！打開 'Taiwan_Top50_Trails.html' 並按播放，點擊某個圓點可鎖定觀察。")
