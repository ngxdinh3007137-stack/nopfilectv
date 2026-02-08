import streamlit as st
import pandas as pd
import requests
import re
import time
import sqlite3
import hashlib
import concurrent.futures
import threading
import random
from io import BytesIO
from datetime import datetime
from urllib.parse import unquote, urlparse, parse_qs
from streamlit.web.server.websocket_headers import _get_websocket_headers

# ==========================================
# 1. CẤU HÌNH & HÀM HỖ TRỢ
# ==========================================
st.set_page_config(
    page_title="Hệ Thống Admin V12.1",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Khóa luồng
db_lock = threading.Lock()

# --- TRACKING ---
def get_remote_ip():
    try:
        try: headers = st.context.headers
        except: headers = _get_websocket_headers()
        if "X-Forwarded-For" in headers: return headers["X-Forwarded-For"].split(",")[0]
        return headers.get("Remote-Addr", "Unknown")
    except: return "Unknown"

def get_user_agent():
    try:
        try: headers = st.context.headers
        except: headers = _get_websocket_headers()
        ua = headers.get("User-Agent", "Unknown")
        return ua if ua else "Unknown Device"
    except: return "Unknown Device"

def get_location_from_ip(ip):
    if ip in ["127.0.0.1", "::1", "Unknown"]: return "Localhost", "VN"
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=2).json()
        if r['status'] == 'success': return r.get('city', 'Unknown'), r.get('country', 'Unknown')
    except: pass
    return "Unknown", "Unknown"

# ==========================================
# 2. DATABASE (RETRY MODE - CHỐNG LOCK)
# ==========================================
DB_NAME = 'data_v12_retry_final.db'

def run_query_safe(query, params=(), is_write=False):
    max_retries = 10
    for i in range(max_retries):
        conn = None
        try:
            conn = sqlite3.connect(DB_NAME, timeout=15, check_same_thread=False)
            # Bật WAL mode để ghi nhanh hơn
            try: conn.execute("PRAGMA journal_mode=WAL")
            except: pass
            
            c = conn.cursor()
            c.execute(query, params)
            
            if is_write:
                conn.commit()
                result = True
            else:
                result = c.fetchall()
            
            conn.close()
            return result
            
        except sqlite3.OperationalError as e:
            if "locked" in str(e):
                time.sleep(random.uniform(0.1, 0.5)) # Đợi một chút rồi thử lại
                if i == max_retries - 1: return None
            else:
                if conn: conn.close()
                return None
        except Exception as e:
            if conn: conn.close()
            return None

def init_db():
    run_query_safe('CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, password TEXT, role TEXT)', is_write=True)
    run_query_safe('''CREATE TABLE IF NOT EXISTS submissions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, report_link TEXT, note TEXT, timestamp TEXT,
        ip TEXT, device TEXT, location TEXT, status TEXT)''', is_write=True)
    run_query_safe('''CREATE TABLE IF NOT EXISTS history(
        username TEXT, action TEXT, count INTEGER, timestamp TEXT, 
        ip TEXT, device TEXT, city TEXT, country TEXT, lat REAL, lon REAL)''', is_write=True)

# --- WRAPPER FUNCTIONS ---
def add_user(u, p, r):
    check = run_query_safe('SELECT * FROM users WHERE username=?', (u,))
    if check: return False, "Tài khoản đã tồn tại!"
    res = run_query_safe('INSERT INTO users VALUES (?,?,?)', (u, p, r), is_write=True)
    if res: return True, "Thành công"
    return False, "Lỗi ghi dữ liệu"

def login(u, p):
    return run_query_safe('SELECT * FROM users WHERE username=? AND password=?', (u, p))

def submit_report(u, l, n):
    ip = get_remote_ip(); ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dev = get_user_agent(); city, country = get_location_from_ip(ip)
    run_query_safe('INSERT INTO submissions (username, report_link, note, timestamp, ip, device, location, status) VALUES (?,?,?,?,?,?,?,?)',
                   (u, l, n, ts, ip, dev, f"{city}-{country}", "Active"), is_write=True)

def log_history(u, act, count):
    ip = get_remote_ip(); dev = get_user_agent(); city, country = get_location_from_ip(ip)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_query_safe('INSERT INTO history (username, action, count, timestamp, ip, device, city, country, lat, lon) VALUES (?,?,?,?,?,?,?,?,?,?)', 
                   (u, act, count, ts, ip, dev, city, country, 0, 0), is_write=True)

def get_submissions(u=None):
    q = "SELECT * FROM submissions WHERE status='Active'"
    p = []
    if u and u != "Tất cả": q += " AND username=?"; p.append(u)
    q += " ORDER BY id DESC"
    return run_query_safe(q, tuple(p))

def delete_submission(sid): 
    run_query_safe("UPDATE submissions SET status='Deleted' WHERE id=?", (sid,), is_write=True)

def get_all_users(): 
    return run_query_safe('SELECT username, role FROM users')

def delete_user_db(u): 
    run_query_safe('DELETE FROM users WHERE username=?', (u,), is_write=True)

def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()

# Init
init_db()
if not run_query_safe("SELECT * FROM users WHERE username='admin'"):
    add_user("admin", make_hashes("admin123"), "admin")

# ==========================================
# 3. CSS GIAO DIỆN
# ==========================================
st.markdown("""
<style>
    .stButton>button { width: 100%; background-color: #1877f2; color: white; border-radius: 6px; font-weight: bold; padding: 10px; border:none; }
    .stButton>button:hover { background-color: #166fe5; color: white; }
    div[data-testid="stToast"] { background-color: #fff; border-left: 5px solid #1877f2; color: #333; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { background-color: #f0f2f5; border-radius: 5px; }
    .stTabs [aria-selected="true"] { background-color: #e7f3ff; color: #1877f2; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. CORE LOGIC (LINK CLEANER)
# ==========================================
def resolve_link_logic(input_str):
    input_str = str(input_str).strip()
    if not input_str: return None, None, "Trống"
    final_url = input_str; post_id = "Không tìm thấy"; note = "OK"

    try:
        trigger_domains = ["share", "goo.gl", "bit.ly", "fb.me", "short", "fbook", "fb.watch", "facebook.com/share"]
        if any(d in input_str for d in trigger_domains):
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Sec-Fetch-Site': 'none', 'Upgrade-Insecure-Requests': '1'
            }
            try:
                response = requests.head(input_str, allow_redirects=True, headers=headers, timeout=12)
                final_url = response.url 
            except Exception as e: note = f"Lỗi Redirect: {str(e)}"

        final_url = unquote(final_url)
        final_url = final_url.replace("://m.facebook.com", "://www.facebook.com")
        
        if "?" in final_url:
            base_url = final_url.split("?")[0]
            params = final_url.split("?")[1]
            keep_params = ["id", "v", "set", "fbid", "comment_id", "reply_comment_id", "story_fbid"]
            clean_query = []
            for p in params.split("&"):
                key = p.split("=")[0]
                if key in keep_params: clean_query.append(p)
            if clean_query: final_url = f"{base_url}?{'&'.join(clean_query)}"
            else: final_url = base_url

        patterns = [
            r'/groups/[^/]+/posts/(\d+)', r'/groups/[^/]+/permalink/(\d+)', r'/posts/(\d+)',
            r'fbid=(\d+)', r'v=(\d+)', r'/videos/(\d+)', r'/reel/(\d+)',
            r'/stories/[a-zA-Z0-9.]+/(?P<id>\d+)', r'story_fbid=(\d+)', 
            r'multi_permalinks=(\d+)', r'group_id=(\d+)', r'id=(\d+)', r'/(\d+)/?$'
        ]
        
        if input_str.isdigit():
            post_id = input_str
            final_url = f"https://www.facebook.com/{post_id}"
        else:
            for pattern in patterns:
                match = re.search(pattern, final_url)
                if match:
                    try: post_id = match.group('id')
                    except: post_id = match.group(1)
                    break

        if post_id != "Không tìm thấy": return final_url, post_id, "Thành công"
        else:
            if "facebook.com" in final_url: return final_url, "ID Ẩn/Chữ", "Link Address Bar (ID ẩn)"
            return final_url, "Không tìm thấy ID", "Cảnh báo"
    except Exception as e: return input_str, "Lỗi Code", str(e)

# ==========================================
# 5. GIAO DIỆN CHÍNH
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ''
if 'role' not in st.session_state: st.session_state['role'] = ''

# --- LOGIN ---
if not st.session_state['logged_in']:
    st.title("🔐 Đăng Nhập")
    c1, c2 = st.columns(2)
    with c1:
        u = st.text_input("Tài khoản")
        p = st.text_input("Mật khẩu", type='password')
        if st.button("Đăng Nhập"):
            res = login(u, make_hashes(p))
            if res:
                st.session_state['logged_in'] = True; st.session_state['username'] = u; st.session_state['role'] = res[0][2]
                st.toast(f"Xin chào {u}!", icon="👋"); time.sleep(0.5); st.rerun()
            else: st.error("Sai thông tin!")

# --- APP ---
else:
    with st.sidebar:
        st.header(f"👤 {st.session_state['username']}")
        st.caption(f"Quyền: {st.session_state['role'].upper()}")
        if st.button("🚪 Đăng Xuất"):
            st.session_state['logged_in'] = False; st.rerun()

    st.title("💎 Hệ Thống Lấy Link Chuẩn")

    if st.session_state['role'] == 'admin':
        tabs = st.tabs(["🚀 TOOL ĐỔI LINK", "📂 KHO BÁO CÁO", "📊 QUẢN TRỊ ADMIN"])
    else:
        tabs = st.tabs(["🚀 TOOL ĐỔI LINK", "📤 NỘP BÁO CÁO", "📊 LỊCH SỬ"])

    # --- TAB 1: TOOL ---
    with tabs[0]:
        st.info("💡 Copy link -> Tool sẽ trả về Link chuẩn Address Bar.")
        file_in = st.file_uploader("📂 Upload File (Excel/TXT)", type=['xlsx', 'txt'])
        txt_in = st.text_area("📝 Nhập thủ công:", height=100)
        c1, c2 = st.columns([1, 4])
        with c1: btn_run = st.button("▶ BẮT ĐẦU CHẠY")
        with c2: 
            if st.button("🗑️ XÓA"): st.session_state['data'] = []; st.session_state['in_type'] = None; st.rerun()

        if 'data' not in st.session_state: st.session_state['data'] = []

        if btn_run:
            in_lines = []
            st.session_state['in_type'] = 'manual'
            if file_in:
                st.session_state['in_type'] = 'file'; st.session_state['f_name'] = file_in.name
                if file_in.name.endswith('.xlsx'):
                    df_u = pd.read_excel(file_in); in_lines = df_u[df_u.columns[0]].astype(str).tolist(); st.session_state['df_up'] = df_u
                else: in_lines = [x for x in file_in.getvalue().decode("utf-8").split('\n') if x.strip()]
            elif txt_in.strip(): in_lines = [x for x in txt_in.split('\n') if x.strip()]

            if in_lines:
                tot = len(in_lines)
                log_history(st.session_state['username'], "Chạy Tool", tot)
                st.toast(f"Đang xử lý {tot} link...", icon="🚀")
                prog = st.progress(0); stt = st.empty(); res = [None]*tot
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as exc:
                    f_map = {exc.submit(resolve_link_logic, l): i for i, l in enumerate(in_lines)}
                    don = 0
                    for fut in concurrent.futures.as_completed(f_map):
                        idx = f_map[fut]
                        try: l, i, n = fut.result(); res[idx] = {"Gốc": in_lines[idx], "Link Address Bar": l, "ID": i, "Note": n}
                        except: res[idx] = {"Gốc": in_lines[idx], "Link Address Bar": "Lỗi", "ID": "Lỗi", "Note": "Lỗi"}
                        don+=1; prog.progress(don/tot); stt.text(f"Running... {don}/{tot}")
                
                st.session_state['data'] = res; st.toast("Xong!", icon="✅"); stt.empty()

        if st.session_state['data']:
            df_r = pd.DataFrame(st.session_state['data'])
            if 'Link Address Bar' not in df_r.columns: df_r['Link Address Bar'] = []
            # ĐÃ SỬA LỖI Ở DÒNG NÀY: XÓA width=None
            st.data_editor(df_r, column_config={"Link Address Bar": st.column_config.LinkColumn("Link Address Bar", display_text=None)}, use_container_width=True)
            
            out = BytesIO(); fn = "ket_qua.xlsx"
            if st.session_state.get('in_type') == 'file' and st.session_state.get('f_name', '').endswith('.xlsx'):
                df_root = st.session_state['df_up']; df_root['Link Address Bar (New)'] = df_r['Link Address Bar']; df_root['ID (New)'] = df_r['ID']
                with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_root.to_excel(w, index=False)
                fn = f"DONE_{st.session_state['f_name']}"
            else:
                with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_r.to_excel(w, index=False)
            
            t1, t2, t3, t4 = st.tabs(["COPY ALL", "COPY LINK", "COPY ID", "TẢI EXCEL"])
            with t1: st.code(df_r.to_csv(sep='\t', index=False), language="text")
            with t2: st.code("\n".join([str(x) for x in df_r["Link Address Bar"] if x]), language="text")
            with t3: st.code("\n".join([str(x) for x in df_r["ID"] if x and x!="Không tìm thấy"]), language="text")
            with t4: st.download_button("📥 Tải Excel", out.getvalue(), fn)

    # --- TAB 2 & 3 ---
    if st.session_state['role'] != 'admin':
        with tabs[1]:
            st.subheader("📤 Nộp Báo Cáo")
            with st.form("f_sub"):
                lnk = st.text_input("🔗 Link Google Sheet:"); nte = st.text_input("📝 Ghi chú:")
                if st.form_submit_button("Gửi"): 
                    if "http" in lnk: submit_report(st.session_state['username'], lnk, nte); st.success("Đã gửi!"); st.rerun()
                    else: st.error("Link lỗi!")
            mys = get_submissions(st.session_state['username'])
            if mys:
                for s in mys[:5]:
                    c1, c2 = st.columns([4, 1])
                    c1.markdown(f"📄 [{s[2]}]({s[2]}) ({s[4]})"); 
                    if c2.button("Hoàn tác", key=f"d_{s[0]}"): delete_submission(s[0]); st.rerun()

    else: # Admin
        with tabs[1]:
            st.subheader("📂 Kho Báo Cáo")
            users_res = get_all_users()
            users_list = ["Tất cả"] + [u[0] for u in users_res] if users_res else ["Tất cả"]
            sel_u = st.selectbox("Lọc User:", users_list)
            subs = get_submissions(sel_u)
            if subs:
                df_s = pd.DataFrame(subs, columns=["ID", "User", "Link", "Note", "Time", "IP", "Dev", "Loc", "Stat"])
                # Sửa lỗi width ở đây luôn
                st.data_editor(df_s[["User", "Link", "Note", "Time", "Loc"]], column_config={"Link": st.column_config.LinkColumn("Link", display_text="🔗 Mở")}, use_container_width=True)

        with tabs[2]:
            st.subheader("📊 Quản Trị")
            c1, c2 = st.columns(2)
            with c1:
                st.write("➕ **Thêm Mới**")
                with st.form("create_user_form", clear_on_submit=True):
                    ua = st.text_input("Tên đăng nhập mới")
                    pa = st.text_input("Mật khẩu mới", type="password")
                    ra = st.selectbox("Quyền", ["user", "admin"])
                    submitted = st.form_submit_button("Tạo Tài Khoản")
                    if submitted:
                        if not ua or not pa: st.error("⚠️ Thiếu thông tin!")
                        else:
                            success, msg = add_user(ua, make_hashes(pa), ra)
                            if success: st.success(f"✅ Đã tạo: {ua}"); time.sleep(1); st.rerun()
                            else: st.error(f"❌ {msg}")
            
            with c2:
                st.write("❌ **Xóa User**")
                users_res = get_all_users()
                users_list = [u[0] for u in users_res] if users_res else []
                with st.form("delete_user_form"):
                    ud = st.selectbox("Chọn User xóa", users_list)
                    del_submitted = st.form_submit_button("Xóa Ngay")
                    if del_submitted:
                        delete_user_db(ud); st.success(f"Đã xóa {ud}"); time.sleep(1); st.rerun()
