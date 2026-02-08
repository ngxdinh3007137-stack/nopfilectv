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
# 1. CẤU HÌNH & CSS (GIAO DIỆN PC/MOBILE)
# ==========================================
st.set_page_config(
    page_title="Hệ Thống Xử Lý Link V14",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS: Tối ưu nút bấm và bảng
st.markdown("""
<style>
    /* Nút bấm to, rõ */
    .stButton>button { border-radius: 8px; font-weight: bold; height: 3em; }
    /* Sidebar màu sáng sủa */
    section[data-testid="stSidebar"] { background-color: #f0f2f6; }
    /* Tab Admin to rõ */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { background-color: #ffffff; border-radius: 5px; padding: 10px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .stTabs [aria-selected="true"] { background-color: #e7f3ff; color: #1877f2; border: 1px solid #1877f2; }
</style>
""", unsafe_allow_html=True)

db_lock = threading.Lock()

# ==========================================
# 2. DATABASE & HÀM HỖ TRỢ (WAL MODE)
# ==========================================
DB_NAME = 'data_system_v14_final.db'

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

# --- DB FUNCTIONS ---
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
# 4. GIAO DIỆN CHÍNH (LAYOUT SIDEBAR TRÁI)
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ''
if 'role' not in st.session_state: st.session_state['role'] = ''

# --- MÀN HÌNH ĐĂNG NHẬP ---
if not st.session_state['logged_in']:
    st.title("🔐 Đăng Nhập Hệ Thống V14")
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

# --- MÀN HÌNH CHÍNH (SAU KHI LOGIN) ---
else:
    # ----------------------------------------------------
    # SIDEBAR: CHỨA TOÀN BỘ 3 TAB CHỨC NĂNG
    # ----------------------------------------------------
    with st.sidebar:
        st.subheader("🛠️ MENU ĐIỀU KHIỂN")
        st.info(f"👤 **{st.session_state['username']}** | {st.session_state['role'].upper()}")
        
        # SỬ DỤNG RADIO ĐỂ CHUYỂN TAB Ở BÊN TRÁI
        menu_options = ["🚀 Tool Đổi Link", "📤 Nộp Báo Cáo"]
        if st.session_state['role'] == 'admin':
            menu_options.append("👑 Quản Trị Viên") # Tab Admin riêng
        
        selected_menu = st.radio("Chọn chức năng:", menu_options)
        
        st.markdown("---")
        if st.button("🚪 Đăng Xuất"):
            st.session_state['logged_in'] = False
            st.session_state['data'] = [] 
            st.rerun()

    # ----------------------------------------------------
    # NỘI DUNG CHÍNH (THAY ĐỔI THEO MENU SIDEBAR)
    # ----------------------------------------------------

    # --- MENU 1: TOOL ĐỔI LINK ---
    if selected_menu == "🚀 Tool Đổi Link":
        st.title("🚀 Tool Xử Lý Link Facebook")
        
        # Nút xóa nằm ngay trên cùng cho dễ thấy
        col_act1, col_act2 = st.columns([3, 1])
        with col_act2:
            if st.button("🗑️ RESET TOÀN BỘ", type="secondary", help="Xóa sạch dữ liệu đang làm"):
                st.session_state['data'] = []
                st.session_state['in_type'] = None
                st.toast("Đã Reset sạch sẽ!", icon="🧹")
                time.sleep(0.5); st.rerun()

        file_in = st.file_uploader("📂 Tải lên Excel/TXT", type=['xlsx', 'txt'])
        txt_in = st.text_area("📝 Hoặc dán link (Mỗi dòng 1 link):", height=150)
        
        if st.button("▶ BẮT ĐẦU CHẠY", type="primary"):
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
                
                st.session_state['data'] = res; st.toast("Xong!", icon="✅"); stt.empty()
            else:
                st.warning("Chưa có dữ liệu đầu vào!")

        if 'data' in st.session_state and st.session_state['data']:
            df_r = pd.DataFrame(st.session_state['data'])
            st.divider()
            st.write("### 📋 Kết Quả")
            st.data_editor(df_r, column_config={"Link Address Bar": st.column_config.LinkColumn("Link Address Bar", display_text=None)}, use_container_width=True)
            
            out = BytesIO(); fn = "ket_qua.xlsx"
            if st.session_state.get('in_type') == 'file' and st.session_state.get('f_name', '').endswith('.xlsx'):
                df_root = st.session_state['df_up']
                df_root['Link Address Bar (New)'] = df_r['Link Address Bar']
                df_root['ID (New)'] = df_r['ID']
                with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_root.to_excel(w, index=False)
                fn = f"DONE_{st.session_state['f_name']}"
            else:
                with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_r.to_excel(w, index=False)
            
            st.download_button("📥 TẢI EXCEL", out.getvalue(), fn, type="primary", use_container_width=True)

    # --- MENU 2: NỘP BÁO CÁO ---
    elif selected_menu == "📤 Nộp Báo Cáo":
        st.title("📤 Nộp Báo Cáo")
        
        # Phần user thường: Xem lịch sử của chính mình
        st.subheader("Lịch sử hoạt động của bạn")
        # Lấy thống kê KPI
        h_data = get_history_filter(user=st.session_state['username'])
        if h_data:
            df_h = pd.DataFrame(h_data, columns=["User", "Action", "Count", "Time", "IP", "Dev", "City", "Country", "Lat", "Lon"])
            total_kpi = df_h[df_h['Action'] == 'Chạy Tool']['Count'].sum()
            st.metric("Tổng Link Đã Xử Lý (KPI)", total_kpi)
        
        st.divider()
        st.write("### Gửi link báo cáo")
        with st.form("submit_form", clear_on_submit=True):
            lnk = st.text_input("🔗 Link Google Sheet/Drive:")
            nte = st.text_input("📝 Ghi chú:")
            if st.form_submit_button("Gửi Ngay"):
                if "http" in lnk: 
                    submit_report(st.session_state['username'], lnk, nte)
                    st.success("✅ Đã gửi!"); time.sleep(1); st.rerun()
                else: st.error("⚠️ Link sai định dạng")

        # Lịch sử nộp
        mys = get_submissions_filter(user=st.session_state['username'])
        if mys:
            st.write("### Các lần nộp gần đây")
            df_my = pd.DataFrame(mys, columns=["ID", "User", "Link", "Note", "Time", "IP", "Dev", "Loc", "Status"])
            st.dataframe(df_my[["Time", "Link", "Note", "Status"]], use_container_width=True)

    # --- MENU 3: ADMIN CENTER (DÀNH RIÊNG CHO QTV) ---
    elif selected_menu == "👑 Quản Trị Viên":
        st.title("👑 Trung Tâm Quản Trị")
        
        # ĐÂY LÀ PHẦN BẠN YÊU CẦU: TAB RIÊNG CHO TỪNG CHỨC NĂNG
        tab1, tab2, tab3 = st.tabs(["📊 THỐNG KÊ", "📥 XUẤT BÁO CÁO (EXCEL)", "👥 QUẢN LÝ USER"])
        
        # --- TAB 1: DASHBOARD ---
        with tab1:
            st.subheader("Tổng Quan Hệ Thống")
            all_users = get_all_users()
            total_users = len(all_users)
            st.metric("Tổng Nhân Viên", total_users)
            st.info("Dùng Tab 'Xuất Báo Cáo' để tải file chi tiết.")

        # --- TAB 2: EXPORT EXCEL (THEO YÊU CẦU CỦA BẠN) ---
        with tab2:
            st.subheader("📥 Trích Xuất Dữ Liệu Ra Excel")
            st.markdown("Chọn điều kiện bên dưới để tải file:")
            
            with st.form("admin_export_form"):
                col_a, col_b, col_c = st.columns(3)
                
                with col_a:
                    st.markdown("**1. Chọn Người:**")
                    all_u_raw = get_all_users()
                    u_list = ["Tất cả"] + [x[0] for x in all_u_raw]
                    target_u = st.selectbox("Nhân viên:", u_list)
                
                with col_b:
                    st.markdown("**2. Chọn Ngày:**")
                    d_range = st.date_input("Khoảng thời gian:", [datetime.now() - timedelta(days=7), datetime.now()])
                
                with col_c:
                    st.markdown("**3. Loại Dữ Liệu:**")
                    data_type = st.selectbox("Cần lấy gì?", ["Lịch sử KPI (Số lượng)", "Danh sách Nộp Báo Cáo"])
                
                btn_export = st.form_submit_button("🚀 TẠO FILE EXCEL")
                
                if btn_export:
                    if len(d_range) != 2:
                        st.error("Vui lòng chọn đủ ngày bắt đầu và kết thúc.")
                    else:
                        s_date, e_date = d_range
                        out_file = BytesIO()
                        f_name = f"Report_{s_date}_{e_date}.xlsx"
                        has_data = False
                        
                        if data_type == "Danh sách Nộp Báo Cáo":
                            raw = get_submissions_filter(target_u, s_date, e_date)
                            if raw:
                                df_ex = pd.DataFrame(raw, columns=["ID", "User", "Link", "Note", "Time", "IP", "Dev", "Loc", "Status"])
                                with pd.ExcelWriter(out_file, engine='xlsxwriter') as w: df_ex.to_excel(w, index=False)
                                has_data = True
                        else: # KPI
                            raw = get_history_filter(target_u, s_date, e_date)
                            if raw:
                                df_ex = pd.DataFrame(raw, columns=["User", "Action", "Count", "Time", "IP", "Dev", "City", "Country", "Lat", "Lon"])
                                with pd.ExcelWriter(out_file, engine='xlsxwriter') as w: df_ex.to_excel(w, index=False)
                                has_data = True
                        
                        if has_data:
                            st.success("✅ Đã tạo file thành công!")
                            st.download_button(f"⬇️ Tải xuống {f_name}", out_file.getvalue(), f_name)
                        else:
                            st.warning("⚠️ Không có dữ liệu nào trong khoảng thời gian này.")

        # --- TAB 3: USER MANAGEMENT ---
        with tab3:
            st.subheader("👥 Quản Lý Tài Khoản")
            
            c_add, c_del = st.columns(2)
            with c_add:
                with st.expander("➕ Thêm Nhân Viên Mới", expanded=True):
                    with st.form("add_user_form", clear_on_submit=True):
                        nu = st.text_input("Tên đăng nhập")
                        np = st.text_input("Mật khẩu", type="password")
                        nr = st.selectbox("Quyền hạn", ["user", "admin"])
                        if st.form_submit_button("Tạo Tài Khoản"):
                            if nu and np:
                                ok, m = add_user(nu, make_hashes(np), nr)
                                if ok: st.success(f"Đã tạo: {nu}"); time.sleep(1); st.rerun()
                                else: st.error(m)
                            else: st.warning("Điền đủ thông tin!")
            
            with c_del:
                with st.expander("❌ Xóa Nhân Viên", expanded=True):
                    all_users_list = [x[0] for x in get_all_users()]
                    with st.form("del_user_form"):
                        du = st.selectbox("Chọn người cần xóa:", all_users_list)
                        if st.form_submit_button("Xóa Vĩnh Viễn"):
                            delete_user_db(du)
                            st.success(f"Đã xóa {du}"); time.sleep(1); st.rerun()
            
            st.markdown("---")
            st.write("### Danh sách hiện tại")
            st.table(pd.DataFrame(get_all_users(), columns=["Username", "Role"]))
