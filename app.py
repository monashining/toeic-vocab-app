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
    """從 GitHub 讀取單字庫"""
    try:
        file_content = repo.get_contents(FILE_PATH)
        decoded_content = base64.b64decode(file_content.content).decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_content))
        return df, file_content.sha
    except Exception:
        df = pd.DataFrame(columns=["日期", "單字", "詞性", "中文解釋"])
        return df, None

def save_vocab_data(df, sha):
    """將資料寫回 GitHub"""
    csv_content = df.to_csv(index=False)
    if sha:
        repo.update_file(FILE_PATH, "Update vocab list", csv_content, sha)
    else:
        repo.create_file(FILE_PATH, "Create vocab list", csv_content)

# ==========================================
# 3. 核心功能模組 (雙重翻譯引擎)
# ==========================================
def get_dict_info(word):
    """先嘗試 Yahoo 字典，若被雲端阻擋則使用 Google 翻譯備援"""
    url = f"https://tw.dictionary.search.yahoo.com/search?p={word}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
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
            
        # 如果爬蟲抓不到東西，故意觸發錯誤進入備援機制
        if not meaning:
            raise ValueError("查無解釋")
            
        return pos, meaning
        
    except Exception:
        # 備援機制：呼叫 deep-translator 進行 Google 翻譯
        try:
            translated = GoogleTranslator(source='en', target='zh-TW').translate(word)
            return "未知", translated
        except Exception:
            return "未知", "請至管理區手動輸入"

# ==========================================
# 4. Streamlit 介面設計 (包含三大分頁)
# ==========================================
st.title("📖 TOEIC 專屬單字記憶庫")

# 讀取現有單字庫資料
df, file_sha = get_vocab_data()

# 新增了第三個「管理」分頁
tab1, tab2, tab3 = st.tabs(["➕ 新增單字", "🌙 夜晚複習", "✏️ 管理與修改"])

# --- 分頁 1：新增單字 ---
with tab1:
    st.markdown("### 快速紀錄")
    # 加入 autocomplete="off" 防止瀏覽器自動填入股票代碼
    with st.form(key="add_word_form", clear_on_submit=True):
        new_word = st.text_input("輸入不熟的英文單字：", autocomplete="off").strip().lower()
        submit_button = st.form_submit_button(label="新增並自動查字典")
        
    if submit_button and new_word:
        if new_word in df['單字'].values:
            st.warning(f"「**{new_word}**」已經在你的單字庫裡囉！")
        else:
            with st.spinner("正在抓取中文解釋並存入雲端..."):
                pos, meaning = get_dict_info(new_word)
                today = datetime.now().strftime("%Y-%m-%d")
                
                new_row = pd.DataFrame([[today, new_word, pos, meaning]], columns=df.columns)
                df = pd.concat([df, new_row], ignore_index=True)
                
                save_vocab_data(df, file_sha)
                st.success(f"✅ 成功寫入：**{new_word}** ({pos}) {meaning}")
                st.rerun()

# --- 分頁 2：夜晚複習 ---
with tab2:
    st.markdown("### 複習清單")
    if df.empty:
        st.info("目前還沒有單字，趕快去隔壁新增吧！")
    else:
        df_reversed = df.iloc[::-1].reset_index(drop=True)
        
        for index, row in df_reversed.iterrows():
            col1, col2, col3 = st.columns([1.5, 3, 1])
            with col1:
                st.subheader(row["單字"])
            with col2:
                st.write(f"**{row.get('詞性', '')}** {row.get('中文解釋', '')}")
                st.caption(f"加入日期: {row.get('日期', '')}")
            with col3:
                # 終極解法：直接使用 Google TTS 串流網址，解決 Apple 裝置的播放限制
                audio_url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={row['單字']}&tl=en&client=tw-ob"
                st.audio(audio_url, format="audio/mp3")
            st.divider()

# --- 分頁 3：管理與修改 (新功能) ---
with tab3:
    st.markdown("### 管理單字庫")
    st.info("💡 **如何操作：**\n- **修改：** 直接點擊表格內的文字即可修改。\n- **刪除：** 點擊表格最左側的核取方塊選取該列，然後按鍵盤的 `Delete` 鍵 (手機版可以直接點擊右上角的垃圾桶圖示)。\n- **完成後，請務必點擊下方的「儲存」按鈕！**")
    
    # st.data_editor 會渲染出一個類似 Excel 的互動式表格
    edited_df = st.data_editor(
        df, 
        num_rows="dynamic",  # 允許使用者刪除列
        use_container_width=True,
        key="vocab_editor"
    )
    
    if st.button("💾 儲存修改至 GitHub"):
        with st.spinner("正在將修改同步至雲端..."):
            save_vocab_data(edited_df, file_sha)
            st.success("✅ 修改與刪除已成功儲存！")
            st.rerun()
