import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from gtts import gTTS
from datetime import datetime
import io
from github import Github
import base64

# ==========================================
# 1. 初始化與網頁設定
# ==========================================
st.set_page_config(page_title="專屬 TOEIC 單字庫", page_icon="📖", layout="centered")

# ==========================================
# 2. 資料庫連線 (使用 GitHub 作為後台)
# ==========================================
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
REPO_NAME = st.secrets["REPO_NAME"]
FILE_PATH = "vocab.csv"

@st.cache_resource
def init_github():
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    return repo

repo = init_github()

def get_vocab_data():
    """從 GitHub 讀取 vocab.csv，若無則建立空的 DataFrame"""
    try:
        file_content = repo.get_contents(FILE_PATH)
        decoded_content = base64.b64decode(file_content.content).decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_content))
        return df, file_content.sha
    except Exception:
        # 如果檔案還不存在，回傳空的結構
        df = pd.DataFrame(columns=["日期", "單字", "詞性", "中文解釋"])
        return df, None

def save_vocab_data(df, sha):
    """將更新後的 DataFrame 寫回 GitHub"""
    csv_content = df.to_csv(index=False)
    if sha:
        repo.update_file(FILE_PATH, "Update vocab list", csv_content, sha)
    else:
        repo.create_file(FILE_PATH, "Create vocab list", csv_content)

# ==========================================
# 3. 核心功能模組 (爬蟲與語音)
# ==========================================
def get_dict_info(word):
    url = f"https://tw.dictionary.search.yahoo.com/search?p={word}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        pos_element = soup.find('div', class_='pos_button')
        pos = pos_element.text.strip() if pos_element else "未知"
        
        meaning_element = soup.find('div', class_='dictionaryWordCard')
        if meaning_element:
            meaning_list = meaning_element.find('div', class_='compList')
            meaning = meaning_list.text.strip() if meaning_list else "找不到解釋"
        else:
            meaning = "找不到解釋"
        return pos, meaning
    except Exception as e:
        return "N/A", "查詢失敗"

def play_audio(word):
    tts = gTTS(text=word, lang='en')
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    fp.seek(0)
    return fp

# ==========================================
# 4. Streamlit 前端介面設計
# ==========================================
st.title("📖 TOEIC 專屬單字記憶庫")

# 讀取現有單字庫資料
df, file_sha = get_vocab_data()

tab1, tab2 = st.tabs(["➕ 新增單字", "🌙 夜晚複習"])

with tab1:
    st.markdown("### 快速紀錄")
    with st.form(key="add_word_form", clear_on_submit=True):
        new_word = st.text_input("輸入不熟的英文單字：").strip().lower()
        submit_button = st.form_submit_button(label="新增並自動查字典")
        
    if submit_button and new_word:
        if new_word in df['單字'].values:
            st.warning(f"「**{new_word}**」已經在你的單字庫裡囉！")
        else:
            with st.spinner("正在自動爬取字典並存入 GitHub..."):
                pos, meaning = get_dict_info(new_word)
                today = datetime.now().strftime("%Y-%m-%d")
                
                # 將新單字加入 DataFrame
                new_row = pd.DataFrame([[today, new_word, pos, meaning]], columns=df.columns)
                df = pd.concat([df, new_row], ignore_index=True)
                
                # 存檔回 GitHub
                save_vocab_data(df, file_sha)
                
                st.success(f"✅ 成功寫入：**{new_word}** ({pos}) {meaning}")
                # 重新整理畫面以更新資料
                st.rerun()

with tab2:
    st.markdown("### 複習清單")
    if df.empty:
        st.info("目前還沒有單字，趕快去隔壁新增吧！")
    else:
        # 將資料反轉，最新加入的在最上方
        df_reversed = df.iloc[::-1].reset_index(drop=True)
        
        for index, row in df_reversed.iterrows():
            col1, col2, col3 = st.columns([1.5, 3, 1])
            with col1:
                st.subheader(row["單字"])
            with col2:
                st.write(f"**{row.get('詞性', '')}** {row.get('中文解釋', '')}")
                st.caption(f"加入日期: {row.get('日期', '')}")
            with col3:
                if st.button("🔊 播放", key=f"btn_{row['單字']}"):
                    audio_fp = play_audio(row["單字"])
                    st.audio(audio_fp, format="audio/mp3", autoplay=True)
            st.divider()
