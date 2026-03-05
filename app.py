import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io
from github import Github
import base64
from deep_translator import GoogleTranslator

# ==========================================
# 1. 初始化與網頁設定
# ==========================================
st.set_page_config(page_title="專屬 TOEIC 單字庫", page_icon="📖", layout="centered")

# --- 手機版專屬 CSS 樣式優化 ---
st.markdown("""
<style>
/* 減少手機版左右兩側的空白邊距，最大化閱讀範圍 */
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
    padding-left: 1rem;
    padding-right: 1rem;
}
/* 讓音檔播放器自動填滿寬度，在手機上更好點擊 */
audio {
    width: 100%;
    height: 40px;
}
/* 微調 Tabs 的字體大小，更適合手機觸控 */
button[data-baseweb="tab"] {
    font-size: 16px !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 資料庫連線 (GitHub)
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
    try:
        file_content = repo.get_contents(FILE_PATH)
        decoded_content = base64.b64decode(file_content.content).decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_content))
        return df, file_content.sha
    except Exception:
        df = pd.DataFrame(columns=["日期", "單字", "詞性", "中文解釋"])
        return df, None

def save_vocab_data(df, sha):
    csv_content = df.to_csv(index=False)
    if sha:
        repo.update_file(FILE_PATH, "Update vocab list", csv_content, sha)
    else:
        repo.create_file(FILE_PATH, "Create vocab list", csv_content)

# ==========================================
# 3. 雙重翻譯引擎
# ==========================================
def get_dict_info(word):
    url = f"https://tw.dictionary.search.yahoo.com/search?p={word}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        pos_element = soup.find('div', class_='pos_button')
        pos = pos_element.text.strip() if pos_element else "未知"
        
        meaning_element = soup.find('div', class_='dictionaryWordCard')
        if meaning_element:
            meaning_list = meaning_element.find('div', class_='compList')
            meaning = meaning_list.text.strip() if meaning_list else ""
        else:
            meaning = ""
            
        if not meaning:
            raise ValueError("查無解釋")
        return pos, meaning
    except Exception:
        try:
            translated = GoogleTranslator(source='en', target='zh-TW').translate(word)
            return "未知", translated
        except Exception:
            return "未知", "請至管理區手動輸入"

# ==========================================
# 4. Streamlit 介面設計 (三大分頁)
# ==========================================
st.title("📖 TOEIC 專屬記憶庫")

df, file_sha = get_vocab_data()

tab1, tab2, tab3 = st.tabs(["➕ 新增", "🌙 複習", "✏️ 管理"])

# --- 分頁 1：新增單字 ---
with tab1:
    with st.form(key="add_word_form", clear_on_submit=True):
        new_word = st.text_input("輸入不熟的英文單字：", autocomplete="off").strip().lower()
        submit_button = st.form_submit_button(label="新增並自動查字典", use_container_width=True)
        
    if submit_button and new_word:
        if new_word in df['單字'].values:
            st.warning(f"「**{new_word}**」已經在你的單字庫裡囉！")
        else:
            with st.spinner("正在抓取中文解釋..."):
                pos, meaning = get_dict_info(new_word)
                today = datetime.now().strftime("%Y-%m-%d")
                
                new_row = pd.DataFrame([[today, new_word, pos, meaning]], columns=df.columns)
                df = pd.concat([df, new_row], ignore_index=True)
                
                save_vocab_data(df, file_sha)
                st.success(f"✅ 已加入：**{new_word}**")
                st.rerun()

# --- 分頁 2：夜晚複習 (iPhone 卡片式優化排版) ---
with tab2:
    if df.empty:
        st.info("目前還沒有單字喔！")
    else:
        df_reversed = df.iloc[::-1].reset_index(drop=True)
        
        for index, row in df_reversed.iterrows():
            # 使用 container(border=True) 打造像 iOS 原生的卡片視覺效果
            with st.container(border=True):
                st.subheader(row["單字"])
                st.markdown(f"**{row.get('詞性', '')}** {row.get('中文解釋', '')}")
                
                audio_url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={row['單字']}&tl=en&client=tw-ob"
                st.audio(audio_url, format="audio/mp3")

# --- 分頁 3：管理與修改 (表格手機版優化) ---
with tab3:
    st.info("💡 直接點擊表格修改，或勾選左側框框按刪除。")
    
    edited_df = st.data_editor(
        df, 
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True, # 隱藏多餘的數字序號，為手機螢幕省空間
        key="vocab_editor"
    )
    
    if st.button("💾 儲存修改", use_container_width=True):
        with st.spinner("同步中..."):
            save_vocab_data(edited_df, file_sha)
            st.success("✅ 修改已成功儲存！")
            st.rerun()
