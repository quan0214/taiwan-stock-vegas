import os
import asyncio
import pandas as pd
import yfinance as yf
import discord
from discord.ext import commands

# 🔒 您的專屬 Discord 機器人 Token (已直接寫入)
TOKEN = "MTQxMzM2ODE0MTI5MTA2MTI3OA.Gmo2gs.sw7jKw_hUYO3Rc0ZG-yQh-z7bsxR8rThX6AGRE"
CACHE_FILE = "vegas_base_cache.csv"

# 初始化 Discord Bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def get_complete_taiwan_stock_list():
    """內建全台股清單 (上市+上櫃共 1800+ 檔)"""
    # 這裡放你原本完整的 tse_ids 與 tpex_ids 清單
    tse_ids = ["1101", "1102", "2330", "2317", "2454"] # 範例，請自行補齊原本的長清單
    tpex_ids = ["5483", "6488", "8069"]
    return [f"{sid}.TW" for sid in tse_ids] + [f"{sid}.TWO" for sid in tpex_ids]

def calculate_ema(series, length):
    """使用原生 pandas 計算 EMA，完美避開 pandas_ta 的編譯錯誤"""
    return series.ewm(span=length, adjust=False).mean()

def build_vegas_cache(all_stocks):
    print(f"⏳ 正在重新整理全台股維加斯基底...")
    batch_size = 40 
    cache_data = []
    for i in range(0, len(all_stocks), batch_size):
        batch = all_stocks[i:i+batch_size]
        try:
            group_df = yf.download(batch, period="3y", progress=False, group_by='ticker')
            for stock_id in batch:
                try:
                    df = group_df if len(batch) == 1 else group_df[stock_id].copy()
                    df = df.dropna(subset=['Close'])
                    if len(df) < 676: continue
                    
                    # 確保取到單一維度的 Series (相容 yfinance 新舊版本)
                    close_series = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
                    
                    df['EMA144'] = calculate_ema(close_series, 144)
                    df['EMA169'] = calculate_ema(close_series, 169)
                    df['EMA576'] = calculate_ema(close_series, 576)
                    df['EMA676'] = calculate_ema(close_series, 676)
                    
                    latest = df.dropna(subset=['EMA676']).iloc[-1]
                    cache_data.append({
                        "stock_id": stock_id,
                        "EMA144": float(latest['EMA144']), "EMA169": float(latest['EMA169']),
                        "EMA576": float(latest['EMA576']), "EMA676": float(latest['EMA676'])
                    })
                except: continue
        except: continue
    cache_df = pd.DataFrame(cache_data)
    cache_df.to_csv(CACHE_FILE, index=False)
    return cache_df

async def scan_market(ctx_or_channel, scan_mode):
    mode_text = "🟢【多頭回踩】" if scan_mode == "long" else "🔴【空頭反彈遇阻】"
    await ctx_or_channel.send(f"⚡ **正在發動全台股 {mode_text} 即時精準狙擊，請稍候...**")
    
    if not os.path.exists(CACHE_FILE):
        all_stocks = get_complete_taiwan_stock_list()
        cache_df = build_vegas_cache(all_stocks)
    else:
        cache_df = pd.read_csv(CACHE_FILE)
        
    triggered_targets = []
    active_list = cache_df['stock_id'].tolist()
    
    loop = asyncio.get_event_loop()
    realtime_data = await loop.run_in_executor(
        None, lambda: yf.download(active_list, period="1d", progress=False, group_by='ticker')
    )
    
    for _, row in cache_df.iterrows():
        try:
            stock_id = row['stock_id']
            today_df = realtime_data[stock_id]
            if today_df.empty: continue
            
            # 安全取出今日股價數據
            c_price = float(today_df['Close'].iloc[-1])
            h_price = float(today_df['High'].iloc[-1])
            l_price = float(today_df['Low'].iloc[-1])
            
            small_max, small_min = max(row['EMA144'], row['EMA169']), min(row['EMA144'], row['EMA169'])
            big_max, big_min = max(row['EMA576'], row['EMA676']), min(row['EMA576'], row['EMA676'])
            stock_name = stock_id.split('.')[0]
            
            # 篩選邏輯
            if scan_mode == "long" and (small_min > big_max) and (l_price <= (small_max * 1.002) and c_price >= small_min):
                triggered_targets.append(f"**{stock_name}** | 現價: `{c_price:.1f}` | 支撐區: `{small_min:.1f} ~ {small_max:.1f}`")
            elif scan_mode == "short" and (small_max < big_min) and (h_price >= (big_min * 0.998) and c_price <= big_max):
                triggered_targets.append(f"**{stock_name}** | 現價: `{c_price:.1f}` | 壓力區: `{big_max:.1f} ~ {big_min:.1f}`")
        except: continue

    if triggered_targets:
        chunks = [triggered_targets[i:i + 15] for i in range(0, len(triggered_targets), 15)]
        for chunk in chunks:
            title = "🏹 多頭回踩即時標的報告" if scan_mode == "long" else "💥 空頭反彈遇阻即時標的報告"
            color = 3066993 if scan_mode == "long" else 15158332
            embed = discord.Embed(title=title, description="\n".join(chunk), color=color)
            await ctx_or_channel.send(embed=embed)
        await ctx_or_channel.send(f"🏁 狙擊完畢！共抓出符合條件標的 {len(triggered_targets)} 檔。")
    else:
        await ctx_or_channel.send(f"🏁 掃描完畢，目前沒有任何台股符合該維加斯條件。")

@bot.event
async def on_ready():
    print(f"📊 機器人已成功連線！登入身份：{bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    user_input = message.content.strip()
    if user_input == "1":
        await scan_market(message.channel, scan_mode="long")
    elif user_input == "2":
        await scan_market(message.channel, scan_mode="short")
    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(TOKEN)
