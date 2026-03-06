import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io
import re
from urllib.parse import quote_plus
from github import Github
from github.GithubException import GithubException
import base64
from deep_translator import GoogleTranslator
from gtts import gTTS

# ==========================================
# 1. 初始化與網頁設定
# ==========================================
st.set_page_config(page_title="專屬 TOEIC 單字庫", page_icon="📖", layout="centered", initial_sidebar_state="collapsed")

st.markdown("""
<style>
/* iPhone / 手機版優化 */
:root {
    --safe-top: env(safe-area-inset-top, 0px);
    --safe-bottom: env(safe-area-inset-bottom, 0px);
    --safe-left: env(safe-area-inset-left, 0px);
    --safe-right: env(safe-area-inset-right, 0px);
}
.block-container {
    padding-top: max(1rem, var(--safe-top)) !important;
    padding-bottom: max(2rem, var(--safe-bottom)) !important;
    padding-left: max(1rem, var(--safe-left)) !important;
    padding-right: max(1rem, var(--safe-right)) !important;
    max-width: 100% !important;
}
/* 防止 iOS 輸入時自動縮放（字體 < 16px 會觸發） */
input, textarea, select, [data-baseweb="select"] {
    font-size: 16px !important;
}
/* 選單、單選在手機上易點 */
[role="listbox"] li, [role="radio"] { min-height: 44px !important; padding: 8px !important; }
/* 按鈕加大，符合 Apple 44pt 觸控建議 */
button {
    min-height: 44px !important;
    padding: 10px 16px !important;
}
/* 分頁標籤在手機上較小、可橫滑 */
button[data-baseweb="tab"] {
    font-size: 14px !important;
    padding: 8px 12px !important;
    min-height: 44px !important;
}
/* 音訊播放器加大觸控區 */
audio {
    width: 100% !important;
    height: 48px !important;
    min-height: 48px !important;
}
/* 標題與內文在手機上易讀 */
h1 { font-size: 1.5rem !important; }
h2, h3 { font-size: 1.2rem !important; }
/* 手機橫向時避免內容過寬 */
@media (max-width: 640px) {
    .block-container { padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
    [data-testid="column"] { min-width: 0 !important; }
}
/* 避免表格在手機上溢出 */
[data-testid="stDataFrame"] { overflow-x: auto !important; }
/* iOS 觸控優化 */
button, [role="button"] { -webkit-tap-highlight-color: rgba(0,0,0,0.1); }
/* 複習卡片按鈕區在窄螢幕加大觸控區 */
@media (max-width: 640px) {
    .stButton > button { width: 100% !important; }
}
/* iOS 平滑捲動 */
.stApp { -webkit-overflow-scrolling: touch; }
/* 避免橫向溢出（iPhone 常見） */
html, body, .stApp { overflow-x: hidden !important; max-width: 100vw !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 資料庫連線與記憶體管理 (解決同步延遲)
# ==========================================
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_NAME = st.secrets["REPO_NAME"]
except Exception:
    st.error("⚠️ 請在 Streamlit Secrets 設定 GITHUB_TOKEN 和 REPO_NAME")
    st.stop()

FILE_PATH = "vocab.csv"

@st.cache_resource
def init_github():
    g = Github(GITHUB_TOKEN)
    return g.get_repo(REPO_NAME)

try:
    repo = init_github()
except Exception as e:
    st.error(f"⚠️ 無法連線 GitHub：{e}")
    st.stop()

DEFAULT_COLUMNS = ["日期", "單字", "詞性", "中文解釋", "音標", "已記住"]

def get_vocab_data():
    try:
        file_content = repo.get_contents(FILE_PATH)
        decoded_content = base64.b64decode(file_content.content).decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_content))
        if "已記住" not in df.columns:
            df["已記住"] = ""
        if "音標" not in df.columns:
            df["音標"] = ""
        return df, file_content.sha
    except Exception:
        return pd.DataFrame(columns=DEFAULT_COLUMNS), None

def _toggle_mastered(df, word, mastered):
    """切換單字的已記住狀態"""
    if "已記住" not in df.columns:
        df["已記住"] = ""
    mask = df["單字"] == word
    df.loc[mask, "已記住"] = "✓" if mastered else ""
    new_sha = save_vocab_data(df, file_sha)
    st.session_state.vocab_df = df
    st.session_state.file_sha = new_sha

def save_vocab_data(df, sha=None):
    """終極儲存方案：忽略舊 SHA，每次寫入前即時抓取最新 SHA，徹底杜絕衝突"""
    csv_content = df.to_csv(index=False)
    try:
        # 1. 每次存檔前，強制去 GitHub 查現在最新的 SHA
        current_file = repo.get_contents(FILE_PATH)
        latest_sha = current_file.sha
        # 2. 用最新的 SHA 進行安全覆蓋
        res = repo.update_file(FILE_PATH, "Update vocab list", csv_content, latest_sha)
        return res['content'].sha
    except GithubException as e:
        # 3. 404 = 檔案不存在，直接建立新檔案
        if getattr(e, 'status', 0) == 404:
            res = repo.create_file(FILE_PATH, "Create vocab list", csv_content)
            return res['content'].sha
        raise

# ★ 核心修正：為 App 加入記憶體，避免 GitHub 快取延遲 ★
if 'vocab_df' not in st.session_state:
    df, sha = get_vocab_data()
    st.session_state.vocab_df = df
    st.session_state.file_sha = sha

# 從記憶體讀取最新狀態
df = st.session_state.vocab_df
file_sha = st.session_state.file_sha

# ==========================================
# 3. 雙重翻譯與後端語音引擎 (解決 iOS 沒聲音)
# ==========================================
def get_dict_info(word):
    """
    雙引擎架構：
    1. 詞性與音標：Free Dictionary API（穩定、不阻擋）
    2. 中文解釋：Yahoo 字典優先，被擋則 Google 翻譯
    """
    pos = "未知"
    meaning = ""
    phonetic = ""
    clean_word = str(word).strip().lower()
    
    # --- 引擎 1：Free Dictionary API 抓取音標與詞性 ---
    try:
        api_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote_plus(clean_word)}"
        api_res = requests.get(api_url, timeout=5)
        if api_res.status_code == 200:
            data = api_res.json()[0]
            if data.get("phonetic"):
                phonetic = data["phonetic"]
            else:
                for p in data.get("phonetics", []):
                    if p.get("text"):
                        phonetic = p["text"]
                        break
            if data.get("meanings") and len(data["meanings"]) > 0:
                raw_pos = data["meanings"][0].get("partOfSpeech", "")
                pos_map = {
                    "noun": "n.", "verb": "v.", "adjective": "adj.",
                    "adverb": "adv.", "pronoun": "pron.", "preposition": "prep.",
                    "conjunction": "conj.", "interjection": "int.", "exclamation": "int.",
                    "transitive verb": "vt.", "intransitive verb": "vi.",
                    "phrase": "ph.", "phrasal verb": "ph."
                }
                pos = pos_map.get(raw_pos.lower(), raw_pos) if raw_pos else "未知"
    except Exception:
        pass
    
    # --- 引擎 2：Yahoo 字典抓取中文解釋 + 音標備援 ---
    EXCLUDE = ("牛津中文字典", "PyDict", "美式", "英式", "網頁搜尋", "查詢詞", "字典", "更多解釋")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Referer': 'https://tw.dictionary.yahoo.com/'}
        res = requests.get(
            f"https://tw.dictionary.search.yahoo.com/search?p={quote_plus(clean_word)}",
            headers=headers, timeout=5
        )
        res.encoding = res.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        # 音標備援：Free Dictionary 無音標時，從 Yahoo 擷取
        if not phonetic:
            phonetic_match = re.search(r'(?:IPA|KK)\s*\[([^\]]+)\]', res.text)
            if phonetic_match:
                phonetic = phonetic_match.group(0).strip()
            # Yahoo 也無時，嘗試 Wiktionary 頁面中的 IPA
            if not phonetic:
                try:
                    wk_res = requests.get(
                        f"https://en.wiktionary.org/wiki/{quote_plus(clean_word)}",
                        headers={'User-Agent': 'Mozilla/5.0'}, timeout=5
                    )
                    # 匹配 /.../ 格式的 IPA
                    wk_match = re.search(r'/([ˈˌəɪʊʌæɒɔɑɛθðʃʒŋɡː\-\s\.a-zA-Z]{4,})/', wk_res.text)
                    if wk_match:
                        p = wk_match.group(1).strip()
                        phonetic = f"/{p}/" if not p.startswith('/') else p
                except Exception:
                    pass
        card = soup.find('div', class_='dictionaryWordCard')
        if card:
            candidates = []
            for item in card.find_all(['li', 'div', 'span']):
                text = item.get_text(separator=' ', strip=True)
                if not re.search(r'[\u4e00-\u9fff]', text) or len(text) < 2:
                    continue
                if any(x in text for x in EXCLUDE) or text in EXCLUDE:
                    continue
                # 跳過純音標、純詞性（含片語 ph.）
                if re.match(r'^(IPA|KK)?\s*\[.*\]\s*$', text) or text in ('vt.', 'vi.', 'n.', 'adj.', 'adv.', 'ph.'):
                    continue
                candidates.append(text)
            # 優先選含「；」或「,」的（典型解釋格式如「改正; 修復」）
            for c in candidates:
                if ';' in c or '；' in c or '，' in c or ',' in c:
                    meaning = c
                    break
            if not meaning and candidates:
                meaning = candidates[0]
    except Exception:
        pass
    
    # 備援 2：舊版 Yahoo 字典
    if not meaning:
        try:
            res = requests.get(
                f"https://tw.dictionary.yahoo.com/dictionary?p={quote_plus(clean_word)}",
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://tw.dictionary.yahoo.com/'},
                timeout=5
            )
            soup = BeautifulSoup(res.text, 'html.parser')
            ul = soup.find('ul', class_='explanations')
            if ul:
                parts = [li.get_text(strip=True) for li in ul.find_all('li', class_='exp-item')]
                meaning = '；'.join(p for p in parts if re.search(r'[\u4e00-\u9fff]', p) and p not in EXCLUDE)
        except Exception:
            pass
    
    # 備援 3：Google 翻譯
    if not meaning:
        try:
            meaning = GoogleTranslator(source='en', target='zh-TW').translate(clean_word)
        except Exception:
            meaning = "請至管理區手動輸入"
    
    # 正規化：全形→半形、多種空白→單一空格（解決 Yahoo 回傳格式不一致）
    meaning = re.sub(r'[\u3000\u00A0\s]+', ' ', meaning).strip()
    meaning = meaning.replace('．', '.').replace('，', ',')
    # 移除中文解釋開頭的詞性（如 "n. 陽臺"、"ph. 盡管..." → 純中文），並將詞性填入 pos
    pos_match = re.match(r'^(ph\s*\.|vt\.|vi\.|n\.|adj\.|adv\.|prep\.|conj\.|v\.|pron\.|int\.)\s*', meaning, re.I)
    if pos_match and pos == "未知":
        pos = re.sub(r'\s+', '', pos_match.group(1))  # "ph ." → "ph."
    meaning = re.sub(r'^(ph\s*\.|vt\.|vi\.|n\.|adj\.|adv\.|prep\.|conj\.|v\.|pron\.|int\.)\s*', '', meaning, flags=re.I).strip()
    # 移除開頭的英文單字（如 "silverware 銀製品" → "銀製品"）
    meaning = re.sub(r'^([a-zA-Z\-]+\s+)+', '', meaning).strip()
    
    return pos, meaning, phonetic

def get_audio_url(word):
    """取得發音 URL（有道字典，iOS Safari 相容性較佳）"""
    clean = str(word).strip().lower()
    if not clean:
        return None
    return f"https://dict.youdao.com/dictvoice?type=0&audio={quote_plus(clean)}"

@st.cache_data(show_spinner=False)
def get_audio_bytes(word):
    """備援：gTTS 產生發音（當 URL 無法使用時）"""
    try:
        tts = gTTS(text=word, lang='en')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp.getvalue()
    except Exception:
        return None

def render_audio_player(word, key_suffix=""):
    """渲染發音播放器（優先有道 URL，iOS Safari 相容性較佳）"""
    url = get_audio_url(word)
    if url:
        st.audio(url, format="audio/mpeg")
        # iOS 備援：若內嵌無法播放，點連結用系統播放器
        st.markdown(f'<a href="{url}" target="_blank" rel="noopener" style="font-size:12px">📱 新分頁播放</a>', unsafe_allow_html=True)
    else:
        data = get_audio_bytes(word)
        if data:
            st.audio(data, format="audio/mpeg")
        else:
            st.caption("無法取得語音")

# ==========================================
# 4. Streamlit 介面設計
# ==========================================
st.title("📖 TOEIC 專屬記憶庫")

# 單字總數與重新載入
col_title, col_reload = st.columns([3, 1])
with col_reload:
    if st.button("🔄 同步", help="從 GitHub 重新載入最新單字", use_container_width=True):
        try:
            df_new, sha_new = get_vocab_data()
            st.session_state.vocab_df = df_new
            st.session_state.file_sha = sha_new
            st.success("已同步最新資料")
            st.rerun()
        except Exception as e:
            st.error(f"同步失敗：{e}")
if not df.empty:
    mastered = 0
    if "已記住" in df.columns:
        mastered = df["已記住"].apply(lambda v: str(v or "").strip() in ("✓", "是", "1")).sum()
    st.caption(f"📊 共 {len(df)} 個單字／片語" + (f"（已記住 {int(mastered)}）" if mastered > 0 else ""))

tab1, tab2, tab3, tab4 = st.tabs(["➕ 新增", "🌙 複習", "🃏 記憶卡考試", "✏️ 管理"])

# --- 分頁 1：新增單字 ---
with tab1:
    with st.form(key="add_word_form", clear_on_submit=True):
        new_word = st.text_input("輸入不熟的英文單字或片語：", placeholder="例如：abandon、give up、break down", autocomplete="off").strip().lower()
        submit_button = st.form_submit_button(label="新增並自動查字典", use_container_width=True)
        
    if submit_button and new_word:
        new_word = ' '.join(new_word.split())  # 正規化多餘空白（片語用）
        if new_word in df['單字'].values:
            st.warning(f"「**{new_word}**」已經在你的單字庫裡囉！")
        else:
            with st.spinner("正在抓取中文解釋與音標..."):
                pos, meaning, phonetic = get_dict_info(new_word)
                today = datetime.now().strftime("%Y-%m-%d")
                df_add = df.copy()
                for c in DEFAULT_COLUMNS:
                    if c not in df_add.columns:
                        df_add[c] = ""
                df_add = df_add[DEFAULT_COLUMNS]
                new_row = pd.DataFrame([[today, new_word, pos, meaning, phonetic, ""]], columns=DEFAULT_COLUMNS)
                new_df = pd.concat([df_add, new_row], ignore_index=True)
                
                # ★ 存檔並同步更新記憶體 ★
                new_sha = save_vocab_data(new_df, file_sha)
                st.session_state.vocab_df = new_df
                st.session_state.file_sha = new_sha
                
                st.success(f"✅ 已加入：**{new_word}**")
                st.rerun()

# --- 分頁 2：夜晚複習 ---
with tab2:
    if df.empty:
        st.info("目前還沒有單字喔！")
    else:
        # 搜尋、熟練度篩選與排序
        col_search, col_master, col_sort, _ = st.columns([2, 1, 1, 1])
        with col_search:
            search = st.text_input("🔍 搜尋單字或解釋", placeholder="輸入關鍵字篩選...", key="review_search")
        with col_master:
            master_filter = st.selectbox("熟練度", ["全部", "未記住", "已記住"], key="review_master")
        with col_sort:
            sort_order = st.selectbox("排序", ["最新優先", "最舊優先", "隨機"], key="review_sort")
        
        df_review = df.copy()
        if "已記住" not in df_review.columns:
            df_review["已記住"] = ""
        def _is_mastered(val):
            return str(val or "").strip() in ("✓", "是", "1")
        if master_filter == "已記住":
            df_review = df_review[df_review["已記住"].apply(_is_mastered)]
        elif master_filter == "未記住":
            df_review = df_review[~df_review["已記住"].apply(_is_mastered)]
        if search:
            mask = df_review["單字"].str.contains(search, case=False, na=False) | \
                   df_review["中文解釋"].str.contains(search, case=False, na=False)
            if "音標" in df_review.columns:
                mask = mask | df_review["音標"].fillna("").astype(str).str.contains(search, case=False, na=False)
            df_review = df_review[mask]
        if sort_order == "最新優先":
            df_review = df_review.iloc[::-1].reset_index(drop=True)
        elif sort_order == "隨機":
            df_review = df_review.sample(frac=1).reset_index(drop=True)
        
        if df_review.empty:
            st.info("沒有符合的單字")
        else:
            for i, (_, row) in enumerate(df_review.iterrows()):
                row_mastered = _is_mastered(row.get("已記住", ""))
                with st.container(border=True):
                    col_word, col_mark, col_audio = st.columns([3, 1, 1])
                    with col_word:
                        st.subheader(row["單字"])
                        phonetic_str = str(row.get("音標", "")).strip()
                        meaning_str = str(row.get("中文解釋", "")).strip()
                        st.markdown(f"**{row.get('詞性', '')}** {meaning_str}" + (f"  _{phonetic_str}_" if phonetic_str else ""))
                        st.caption(f"加入日期：{row.get('日期', '')}" + (" ✓ 已記住" if row_mastered else ""))
                    with col_mark:
                        if row_mastered:
                            if st.button("↩️ 取消", key=f"unmark_{row['單字']}_{i}", help="標記為未記住", use_container_width=True):
                                _toggle_mastered(df, row["單字"], False)
                                st.rerun()
                        else:
                            if st.button("✓ 已記住", key=f"mark_{row['單字']}_{i}", help="標記為已記住", use_container_width=True):
                                _toggle_mastered(df, row["單字"], True)
                                st.rerun()
                    with col_audio:
                        render_audio_player(row["單字"], key_suffix=f"_{i}")

# --- 分頁 3：記憶卡考試 ---
with tab3:
    if df.empty:
        st.info("目前還沒有單字喔！先去新增一些單字再來考試吧。")
    else:
        # 初始化考試狀態
        if 'quiz_index' not in st.session_state:
            st.session_state.quiz_index = 0
        if 'quiz_pool' not in st.session_state:
            st.session_state.quiz_pool = []
        if 'quiz_flipped' not in st.session_state:
            st.session_state.quiz_flipped = False
        
        # 設定區（僅支援：看英文 → 猜中文）
        with st.expander("⚙️ 考試設定", expanded=len(st.session_state.quiz_pool) == 0):
            quiz_df = df.copy()
            if "已記住" in quiz_df.columns:
                quiz_scope = st.radio("出題範圍", ["全部單字", "僅未記住"], horizontal=True)
                if "未記住" in quiz_scope:
                    quiz_df = quiz_df[~quiz_df["已記住"].apply(lambda v: str(v or "").strip() in ("✓", "是", "1"))]
            
            num_options = [5, 10, 20, 50, "全部"]
            num_choice = st.selectbox("題數", num_options, format_func=lambda x: str(x) if x != "全部" else "全部")
            num = len(quiz_df) if num_choice == "全部" else min(num_choice, len(quiz_df))
            
            if st.button("🔄 開始 / 重新開始", use_container_width=True):
                n = min(num, len(quiz_df))
                if n == 0:
                    st.warning("沒有可考的單字（可能已全部標記為已記住）")
                else:
                    pool = quiz_df.sample(n=n, replace=False).reset_index(drop=True)
                    st.session_state.quiz_pool = pool.to_dict('records')
                    st.session_state.quiz_index = 0
                    st.session_state.quiz_flipped = False
                    st.rerun()
        
        # 考試區
        if st.session_state.quiz_pool:
            quiz_list = st.session_state.quiz_pool
            idx = st.session_state.quiz_index
            current = quiz_list[idx]
            total = len(quiz_list)
            
            # 進度
            st.progress((idx + 1) / total, text=f"第 {idx + 1} / {total} 題")
            
            # 題目：英文單字 + 詞性
            question = current["單字"]
            ans_meaning = str(current.get("中文解釋", "")).strip()
            ans_phonetic = str(current.get("音標", "")).strip()
            answer = f"{ans_meaning}" + (f"  _{ans_phonetic}_" if ans_phonetic else "")
            hint = f"({current['詞性']})"
            
            st.markdown("### 題目")
            st.markdown(f"""
            <div style="
                padding: 1.5rem; border-radius: 12px; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; text-align: center; font-size: clamp(1.1rem, 4vw, 1.5rem);
                margin: 1rem 0; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                word-break: break-word; max-width: 100%;
            ">
                {question} {hint}
            </div>
            """, unsafe_allow_html=True)
            
            # 發音
            render_audio_player(current["單字"], key_suffix="_q")
            
            # 翻面 / 顯示答案
            if not st.session_state.quiz_flipped:
                if st.button("🔄 翻面看答案", use_container_width=True):
                    st.session_state.quiz_flipped = True
                    st.rerun()
            else:
                st.markdown("### 答案")
                st.success(answer)
                
                col_prev, col_next, _ = st.columns([1, 1, 2])
                with col_prev:
                    if st.button("⬅️ 上一題", use_container_width=True) and idx > 0:
                        st.session_state.quiz_index = idx - 1
                        st.session_state.quiz_flipped = False
                        st.rerun()
                with col_next:
                    if st.button("➡️ 下一題", use_container_width=True):
                        if idx < total - 1:
                            st.session_state.quiz_index = idx + 1
                            st.session_state.quiz_flipped = False
                            st.rerun()
                        else:
                            st.balloons()
                            st.success("🎉 恭喜！全部完成！")
                            st.session_state.quiz_pool = []
                            st.rerun()

# --- 分頁 4：管理與修改 ---
with tab4:
    st.info("💡 直接點擊表格修改，勾選要刪除的單字後按「刪除所選」。")
    
    # 使用 editor_version 強制在儲存後重新載入，確保複習頁同步
    if 'editor_version' not in st.session_state:
        st.session_state.editor_version = 0
    
    if "已記住" not in df.columns:
        df["已記住"] = ""
    # ★ 預防當機：把所有空值變成空字串，強制全體轉為文字格式 ★
    safe_df = df.fillna("").astype(str)
    edited_df = st.data_editor(
        safe_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"vocab_editor_{st.session_state.editor_version}",
    )
    
    col_save, col_del, _ = st.columns([1, 1, 2])
    
    with col_save:
        if st.button("💾 儲存修改", use_container_width=True):
            if edited_df.empty:
                st.warning("無法儲存空清單，請至少保留一筆單字。")
            else:
                with st.spinner("同步中..."):
                    new_sha = save_vocab_data(edited_df, file_sha)
                    st.session_state.vocab_df = edited_df.reset_index(drop=True)
                    st.session_state.file_sha = new_sha
                    st.session_state.editor_version += 1  # 強制 data_editor 重新載入
                    st.success("✅ 修改已成功儲存！複習頁已同步更新。")
                    st.rerun()
    
    with col_del:
        # 刪除功能：勾選要刪除的列
        st.markdown("**刪除單字**")
        to_delete = st.multiselect(
            "勾選要刪除的單字",
            options=edited_df["單字"].tolist() if not edited_df.empty else [],
            default=[],
            key="delete_select"
        )
        if st.button("🗑️ 刪除所選", use_container_width=True) and to_delete:
            remaining_df = edited_df[~edited_df["單字"].isin(to_delete)].reset_index(drop=True)
            with st.spinner("刪除中..."):
                new_sha = save_vocab_data(remaining_df, file_sha)
                st.session_state.vocab_df = remaining_df
                st.session_state.file_sha = new_sha
                st.session_state.editor_version += 1
                st.success(f"✅ 已刪除 {len(to_delete)} 個單字")
                st.rerun()
