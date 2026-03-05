import streamlit as st
import requests
from bs4 import BeautifulSoup
from gtts import gTTS
from datetime import datetime
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 1. 初始化與網頁設定
# ==========================================
st.set_page_config(page_title="專屬 TOEIC 單字庫", page_icon="📖", layout="centered")

# ==========================================
# 2. 資料庫連線 (Google Sheets)
# ==========================================
# 使用 st.cache_resource 確保每次重整網頁不會重複連線，節省資源
@st.cache_resource
def init_connection():
    # 定義授權範圍
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # 從 Streamlit 雲端的 Secrets 讀取你的 GCP 服務帳戶金鑰
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # 開啟名為 "MyVocab" 的試算表中的第一張表
    # ⚠️ 注意：你雲端硬碟裡的試算表名稱必須完全符合 "MyVocab"
    sheet = client.open("MyVocab").sheet1 
    return sheet

# 嘗試連線，若尚未設定 Secrets 會在此報錯，可利用 try-except 捕捉
try:
    sheet = init_connection()
    db_connected = True
except Exception as e:
    db_connected = False
    st.error("無法連線至 Google Sheets，請確認 Streamlit Secrets 憑證是否設定正確。")

# ==========================================
# 3. 核心功能模組 (爬蟲與語音)
# ==========================================
def get_dict_info(word):
    """爬取 Yahoo 字典的詞性與中文解釋"""
    url = f"https://tw.dictionary.search.yahoo.com/search?p={word}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 抓取詞性 (如 n., v., adj.)
        pos_element = soup.find('div', class_='pos_button')
        pos = pos_element.text.strip() if pos_element else "未知"
        
        # 抓取主要中文解釋
        meaning_element = soup.find('div', class_='dictionaryWordCard')
        if meaning_element:
            meaning_list = meaning_element.find('div', class_='compList')
            meaning = meaning_list.text.strip() if meaning_list else "找不到解釋"
        else:
            meaning = "找不到解釋"
            
        return pos, meaning
    except Exception as e:
        return "N/A", f"查詢失敗 ({str(e)})"

def play_audio(word):
    """即時產生 MP3 音檔流 (不存實體檔案，適合雲端環境)"""
    tts = gTTS(text=word, lang='en')
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    fp.seek(0)
    return fp

# ==========================================
# 4. Streamlit 前端介面設計
# ==========================================
st.title("📖 TOEIC 專屬單字記憶庫")

# 若資料庫未連線，停止渲染下方介面
if not db_connected:
    st.stop()

# 使用 Tabs 分離「新增」與「複習」情境
tab1, tab2 = st.tabs(["➕ 新增單字", "🌙 夜晚複習"])

# --- 分頁 1：新增單字 ---
with tab1:
    st.markdown("### 快速紀錄")
    # 使用表單 (form) 包裝，讓使用者可以在手機上按 Enter 直接送出
    with st.form(key="add_word_form", clear_on_submit=True):
        new_word = st.text_input("輸入不熟的英文單字：").strip().lower()
        submit_button = st.form_submit_button(label="新增並自動查字典")
        
    if submit_button and new_word:
        with st.spinner("正在自動爬取字典並寫入雲端..."):
            # 取得現有單字清單 (抓取第二欄)，跳過標題列
            existing_words = sheet.col_values(2)[1:] 
            
            if new_word in existing_words:
                st.warning(f"「**{new_word}**」已經在你的單字庫裡囉！去複習區看看吧。")
            else:
                # 執行爬蟲
                pos, meaning = get_dict_info(new_word)
                today = datetime.now().strftime("%Y-%m-%d")
                
                # 寫入 Google Sheets 的最下方
                sheet.append_row([today, new_word, pos, meaning])
                st.success(f"✅ 成功寫入：**{new_word}** ({pos}) {meaning}")

# --- 分頁 2：夜晚複習 ---
with tab2:
    st.markdown("### 複習清單")
    # 點擊按鈕才向 Google Sheets 要資料，避免無謂的 API 消耗
    if st.button("🔄 重新載入最新單字"):
        # 抓取整張表的所有資料，回傳為 Dictionary 列表
        data = sheet.get_all_records()
        
        if not data:
            st.info("目前還沒有單字，趕快去隔壁新增吧！")
        else:
            # 將資料反轉，讓最新加入的排在最上方
            for row in reversed(data):
                # 利用 columns 排版：單字 | 解釋 | 發音按鈕
                col1, col2, col3 = st.columns([1.5, 3, 1])
                with col1:
                    st.subheader(row["單字"])
                with col2:
                    st.write(f"**{row.get('詞性', '')}** {row.get('中文解釋', '')}")
                    st.caption(f"加入日期: {row.get('日期', '')}")
                with col3:
                    # 點擊才即時產生並播放發音
                    if st.button("🔊 播放", key=f"btn_{row['單字']}"):
                        audio_fp = play_audio(row["單字"])
                        st.audio(audio_fp, format="audio/mp3", autoplay=True)
                st.divider() # 加上底線分隔
