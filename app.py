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
from datetime import datetime, timedelta
from urllib.parse import unquote, urlparse, parse_qs
from streamlit.web.server.websocket_headers import _get_websocket_headers

# ==========================================
# 1. CẤU HÌNH & CSS TỐI ƯU GIAO DIỆN
# ==========================================
st.set_page_config(
    page_title="Hệ Thống Xử Lý Link Pro",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS tùy chỉnh
st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; padding: 0.5rem; transition: 0.3s; }
    .stButton>button:hover { transform: scale(1.02); }
    section[data-testid="stSidebar"] { background-color: #f8f9fa; }
    div[data-testid="stDataFrame"] { width: 100%; }
    div[data-testid="stToast"] { background-color: #fff; border-left: 5px solid #1877f2; color: #333; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

db_lock = threading.Lock()

# ==========================================
# 2. DATABASE & HÀM HỖ TRỢ (WAL MODE)
# ==========================================
DB_NAME = 'data_system_final_v13_1.db'

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
        return headers.get("User-Agent", "Unknown Device")
    except: return "Unknown Device"

def get_location_from_ip(ip):
    if ip in ["127.0.0.1", "::1", "Unknown"]: return "Localhost", "VN"
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=2).json()
        if r['status'] == 'success': return r.get('city', 'Unknown'), r.get('country', 'Unknown')
    except: pass
    return "Unknown", "Unknown"

def run_query_safe(query, params=(), is_write=False):
    max_retries = 10
    for i in range(max_retries):
        conn = None
        try:
            conn = sqlite3.connect(DB_NAME, timeout=15, check_same_thread=False)
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
                time.sleep(random.uniform(0.1, 0.5))
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

# --- CÁC HÀM XỬ LÝ DATABASE ---
def add_user(u, p, r):
    check = run_query_safe('SELECT * FROM users WHERE username=?', (u,))
    if check: return False, "Tài khoản tồn tại!"
    res = run_query_safe('INSERT INTO users VALUES (?,?,?)', (u, p, r), is_write=True)
    if res: return True, "OK"
    return False, "Lỗi DB"

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

# --- QUAN TRỌNG: ĐÃ THÊM LẠI HÀM NÀY ĐỂ SỬA LỖI NAME ERROR ---
def get_submissions(u=None):
    q = "SELECT * FROM submissions WHERE status='Active'"
    p = []
    if u and u != "Tất cả": q += " AND username=?"; p.append(u)
    q += " ORDER BY id DESC"
    return run_query_safe(q, tuple(p))

def get_submissions_filter(user=None, start_date=None, end_date=None):
    query = "SELECT * FROM submissions WHERE status='Active'"
    params = []
    if user and user != "Tất cả":
        query += " AND username=?"
        params.append(user)
    if start_date and end_date:
        query += " AND timestamp BETWEEN ? AND ?"
        params.append(f"{start_date} 00:00:00")
        params.append(f"{end_date} 23:59:59")
    query += " ORDER BY id DESC"
    return run_query_safe(query, tuple(params))

def get_history_filter(user=None, start_date=None, end_date=None):
    query = "SELECT * FROM history WHERE 1=1"
    params = []
    if user and user != "Tất cả":
        query += " AND username=?"
        params.append(user)
    if start_date and end_date:
        query += " AND timestamp BETWEEN ? AND ?"
        params.append(f"{start_date} 00:00:00")
        params.append(f"{end_date} 23:59:59")
    query += " ORDER BY timestamp DESC"
    return run_query_safe(query, tuple(params))

def delete_submission(sid): 
    run_query_safe("UPDATE submissions SET status='Deleted' WHERE id=?", (sid,), is_write=True)

def get_all_users(): return run_query_safe('SELECT username, role FROM users')
def delete_user_db(u): run_query_safe('DELETE FROM users WHERE username=?', (u,), is_write=True)
def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()

init_db()
if not run_query_safe("SELECT * FROM users WHERE username='admin'"):
    add_user("admin", make_hashes("admin123"), "admin")

# ==========================================
# 3. LOGIC XỬ LÝ LINK
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

        final_url = unquote(final_url).replace("://m.facebook.com", "://www.facebook.com")
        if "?" in final_url:
            base, params = final_url.split("?")[0], final_url.split("?")[1]
            keep = ["id", "v", "set", "fbid", "comment_id", "reply_comment_id", "story_fbid"]
            clean_q = [p for p in params.split("&") if p.split("=")[0] in keep]
            final_url = f"{base}?{'&'.join(clean_q)}" if clean_q else base

        patterns = [
            r'/groups/[^/]+/posts/(\d+)', r'/groups/[^/]+/permalink/(\d+)', r'/posts/(\d+)',
            r'fbid=(\d+)', r'v=(\d+)', r'/videos/(\d+)', r'/reel/(\d+)',
            r'/stories/[a-zA-Z0-9.]+/(?P<id>\d+)', r'story_fbid=(\d+)', 
            r'multi_permalinks=(\d+)', r'group_id=(\d+)', r'id=(\d+)', r'/(\d+)/?$'
        ]
        
        if input_str.isdigit():
            post_id = input_str; final_url = f"https://www.facebook.com/{post_id}"
        else:
            for p in patterns:
                m = re.search(p, final_url)
                if m:
                    try: post_id = m.group('id')
                    except: post_id = m.group(1)
                    break
        
        if post_id != "Không tìm thấy": return final_url, post_id, "Thành công"
        else:
            if "facebook.com" in final_url: return final_url, "ID Ẩn/Chữ", "Link Address Bar (ID ẩn)"
            return final_url, "Không tìm thấy ID", "Cảnh báo"
    except Exception as e: return input_str, "Lỗi Code", str(e)

# ==========================================
# 4. GIAO DIỆN CHÍNH
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ''
if 'role' not in st.session_state: st.session_state['role'] = ''

# --- LOGIN SCREEN ---
if not st.session_state['logged_in']:
    st.title("🔐 Đăng Nhập Hệ Thống")
    c1, c2 = st.columns(2)
    with c1:
        u = st.text_input("Tài khoản")
        p = st.text_input("Mật khẩu", type='password')
        if st.button("Đăng Nhập"):
            res = login(u, make_hashes(p))
            if res:
                st.session_state['logged_in'] = True; st.session_state['username'] = u; st.session_state['role'] = res[0][2]
                st.toast(f"Chào {u}!", icon="👋"); time.sleep(0.5); st.rerun()
            else: st.error("Sai tài khoản hoặc mật khẩu")

# --- MAIN APP ---
else:
    # --- SIDEBAR NAV ---
    with st.sidebar:
        st.title("🛠️ MENU")
        st.info(f"👤 **{st.session_state['username']}**\n\nQuyền: {st.session_state['role'].upper()}")
        
        menu_options = ["🚀 Tool Đổi Link", "📤 Nộp Báo Cáo", "📊 Thống Kê & Admin"]
        selected_menu = st.radio("Chức năng:", menu_options)
        
        st.markdown("---")
        if st.button("🚪 Đăng Xuất"):
            st.session_state['logged_in'] = False
            st.session_state['data'] = [] 
            st.rerun()

    # --- MENU 1: TOOL ĐỔI LINK ---
    if selected_menu == "🚀 Tool Đổi Link":
        st.header("🚀 Công Cụ Xử Lý Link Facebook")
        st.caption("Tự động lấy link Address Bar chuẩn, loại bỏ rác tracking.")
        
        file_in = st.file_uploader("📂 Tải lên file Excel/TXT (Nhiều dòng)", type=['xlsx', 'txt'])
        txt_in = st.text_area("📝 Hoặc dán link vào đây (Mỗi dòng 1 link):", height=120)
        
        c1, c2 = st.columns([1, 1])
        with c1: btn_run = st.button("▶ BẮT ĐẦU CHẠY", type="primary")
        with c2: 
            if st.button("🗑️ XÓA TẤT CẢ (RESET)", type="secondary"):
                st.session_state['data'] = []
                st.session_state['in_type'] = None
                st.toast("Đã xóa sạch dữ liệu!", icon="🗑️")
                time.sleep(0.5); st.rerun()

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
                        try: l, i, n = fut.result(); res[idx] = {"Link Gốc": in_lines[idx], "Link Address Bar": l, "ID": i, "Note": n}
                        except: res[idx] = {"Link Gốc": in_lines[idx], "Link Address Bar": "Lỗi", "ID": "Lỗi", "Note": "Lỗi"}
                        don+=1; prog.progress(don/tot); stt.text(f"Đang chạy... {don}/{tot}")
                
                st.session_state['data'] = res; st.toast("Hoàn thành!", icon="✅"); stt.empty()
            else:
                st.warning("Vui lòng nhập dữ liệu!")

        if st.session_state['data']:
            df_r = pd.DataFrame(st.session_state['data'])
            st.write("### 📋 Kết Quả Xử Lý")
            st.data_editor(df_r, column_config={"Link Address Bar": st.column_config.LinkColumn("Link Address Bar", display_text=None)}, use_container_width=True)
            
            out = BytesIO(); fn = "ket_qua_facebook.xlsx"
            if st.session_state.get('in_type') == 'file' and st.session_state.get('f_name', '').endswith('.xlsx'):
                df_root = st.session_state['df_up']
                df_root['Link Address Bar (New)'] = df_r['Link Address Bar']
                df_root['ID (New)'] = df_r['ID']
                with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_root.to_excel(w, index=False)
                fn = f"DONE_{st.session_state['f_name']}"
            else:
                with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_r.to_excel(w, index=False)
            
            st.download_button("📥 TẢI FILE EXCEL KẾT QUẢ", out.getvalue(), fn, type="primary", use_container_width=True)

    # --- MENU 2: NỘP BÁO CÁO ---
    elif selected_menu == "📤 Nộp Báo Cáo":
        st.header("📤 Nộp Báo Cáo Kết Quả")
        
        with st.form("submit_form", clear_on_submit=True):
            st.info("Dán link Google Sheet/Drive chứa kết quả vào đây.")
            lnk = st.text_input("🔗 Link Báo Cáo:")
            nte = st.text_input("📝 Ghi chú:")
            if st.form_submit_button("Gửi Báo Cáo Ngay"):
                if "http" in lnk: 
                    submit_report(st.session_state['username'], lnk, nte)
                    st.success("✅ Đã gửi báo cáo!"); time.sleep(1); st.rerun()
                else: st.error("⚠️ Link không hợp lệ")

        st.subheader("🕒 Lịch sử nộp (Của bạn)")
        # Sửa lại gọi hàm get_submissions_filter cho user view
        mys = get_submissions_filter(user=st.session_state['username'])
        if mys:
            df_my = pd.DataFrame(mys, columns=["ID", "User", "Link", "Note", "Time", "IP", "Dev", "Loc", "Status"])
            for idx, row in df_my.iterrows():
                with st.container():
                    c1, c2, c3 = st.columns([5, 2, 1])
                    c1.markdown(f"📄 **[{row['Link']}]({row['Link']})**")
                    c1.caption(f"Ghi chú: {row['Note']}")
                    c2.text(f"🕒 {row['Time']}")
                    if c3.button("Hoàn tác", key=f"del_{row['ID']}"):
                        delete_submission(row['ID'])
                        st.toast("Đã thu hồi!"); time.sleep(0.5); st.rerun()
                    st.divider()
        else: st.info("Chưa có lịch sử nộp.")

    # --- MENU 3: ADMIN ---
    elif selected_menu == "📊 Thống Kê & Admin":
        curr_role = st.session_state['role']
        if curr_role != 'admin':
            st.warning("Bạn không có quyền truy cập trang này.")
        else:
            st.header("👑 Quản Trị Viên (Admin)")
            tab_export, tab_users = st.tabs(["📥 XUẤT BÁO CÁO", "👥 QUẢN LÝ USER"])
            
            with tab_export:
                st.subheader("Trích Xuất Dữ Liệu")
                with st.form("admin_export_form"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        all_u = get_all_users()
                        u_list = ["Tất cả"] + [x[0] for x in all_u]
                        target_u = st.selectbox("1. Nhân Viên:", u_list)
                    with c2:
                        d_range = st.date_input("2. Thời Gian:", [datetime.now() - timedelta(days=7), datetime.now()])
                    with c3:
                        data_type = st.selectbox("3. Loại Dữ Liệu:", ["Lịch sử Hoạt động (KPI)", "Danh sách Nộp Báo Cáo"])
                    
                    if st.form_submit_button("🚀 Xuất Excel"):
                        if len(d_range) != 2: st.error("Chọn đủ ngày.")
                        else:
                            s_date, e_date = d_range
                            output_admin = BytesIO()
                            file_name_admin = f"Report_{data_type}_{s_date}_{e_date}.xlsx"
                            has_data = False
                            
                            if data_type == "Danh sách Nộp Báo Cáo":
                                raw = get_submissions_filter(target_u, s_date, e_date)
                                if raw:
                                    df_ex = pd.DataFrame(raw, columns=["ID", "User", "Link", "Note", "Time", "IP", "Dev", "Loc", "Status"])
                                    with pd.ExcelWriter(output_admin, engine='xlsxwriter') as w: df_ex.to_excel(w, index=False)
                                    has_data = True
                            else:
                                raw = get_history_filter(target_u, s_date, e_date)
                                if raw:
                                    df_ex = pd.DataFrame(raw, columns=["User", "Action", "Count", "Time", "IP", "Dev", "City", "Country", "Lat", "Lon"])
                                    with pd.ExcelWriter(output_admin, engine='xlsxwriter') as w: df_ex.to_excel(w, index=False)
                                    has_data = True
                            
                            if has_data:
                                st.success("✅ Thành công!")
                                st.download_button(f"⬇️ Tải {file_name_admin}", output_admin.getvalue(), file_name_admin)
                            else: st.warning("Không có dữ liệu.")
            
            with tab_users:
                st.subheader("Danh Sách User")
                st.table(pd.DataFrame(all_u, columns=["Tên đăng nhập", "Quyền"]))
                c_add, c_del = st.columns(2)
                with c_add:
                    st.write("➕ **Thêm Mới**")
                    with st.form("add_user_f", clear_on_submit=True):
                        nu = st.text_input("Username")
                        np = st.text_input("Password", type="password")
                        nr = st.selectbox("Role", ["user", "admin"])
                        if st.form_submit_button("Tạo"):
                            if nu and np:
                                ok, m = add_user(nu, make_hashes(np), nr)
                                if ok: st.success(f"Đã tạo {nu}"); time.sleep(1); st.rerun()
                                else: st.error(m)
                            else: st.warning("Điền đủ thông tin!")
                with c_del:
                    st.write("❌ **Xóa User**")
                    with st.form("del_user_f"):
                        du = st.selectbox("Chọn User", [x[0] for x in all_u])
                        if st.form_submit_button("Xóa Vĩnh Viễn"):
                            delete_user_db(du)
                            st.success(f"Đã xóa {du}"); time.sleep(1); st.rerun()
