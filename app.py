import streamlit as st
import pandas as pd
import requests
import re
import time
import sqlite3
import hashlib
import concurrent.futures
from io import BytesIO
from datetime import datetime
from streamlit.web.server.websocket_headers import _get_websocket_headers

# ==========================================
# 1. CẤU HÌNH & HÀM HỖ TRỢ (TRACKING)
# ==========================================
st.set_page_config(
    page_title="Hệ Thống Quản Lý Link & Báo Cáo Pro",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- LẤY IP & THIẾT BỊ ---
def get_remote_ip():
    try:
        headers = _get_websocket_headers()
        if "X-Forwarded-For" in headers: return headers["X-Forwarded-For"].split(",")[0]
        return headers.get("Remote-Addr", "Unknown")
    except: return "Unknown"

def get_user_agent():
    try:
        headers = _get_websocket_headers()
        ua = headers.get("User-Agent", "Unknown")
        if "iPhone" in ua: return "iPhone"
        elif "Android" in ua: return "Android Mobile"
        elif "Windows" in ua: return "Windows PC"
        elif "Macintosh" in ua: return "Macbook"
        elif "Linux" in ua: return "Linux PC"
        return "Other Device"
    except: return "Unknown Device"

def get_location_from_ip(ip):
    if ip in ["127.0.0.1", "::1", "Unknown"]: return "Localhost", "VN", 0, 0
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=2).json()
        if r['status'] == 'success': return r.get('city', 'Unknown'), r.get('country', 'Unknown'), r.get('lat', 0), r.get('lon', 0)
    except: pass
    return "Unknown", "Unknown", 0, 0

# ==========================================
# 2. DATABASE (SQLITE)
# ==========================================
conn = sqlite3.connect('data_v6_full.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    # 1. Bảng User
    c.execute('CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, password TEXT, role TEXT)')
    
    # 2. Bảng History (Log chi tiết có vị trí)
    c.execute('''CREATE TABLE IF NOT EXISTS history(
        username TEXT, action TEXT, count INTEGER, timestamp TEXT, 
        ip TEXT, device TEXT, city TEXT, country TEXT, lat REAL, lon REAL)''')
    
    # 3. Bảng Nộp Báo Cáo (Submissions)
    c.execute('''CREATE TABLE IF NOT EXISTS submissions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        report_link TEXT,      -- Link Google Sheet
        note TEXT,             -- Ghi chú
        timestamp TEXT,
        ip TEXT, device TEXT, location TEXT,
        status TEXT            -- Active/Deleted
    )''')
    conn.commit()

def add_user(u, p, r):
    try:
        c.execute('INSERT INTO users VALUES (?,?,?)', (u, p, r))
        conn.commit(); return True
    except: return False

def login(u, p):
    c.execute('SELECT * FROM users WHERE username=? AND password=?', (u, p))
    return c.fetchall()

def log_history(u, act, count):
    ip = get_remote_ip()
    dev = get_user_agent()
    city, country, lat, lon = get_location_from_ip(ip)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?,?,?,?)', 
              (u, act, count, ts, ip, dev, city, country, lat, lon))
    conn.commit()

# --- HÀM NỘP BÁO CÁO ---
def submit_report(username, link, note):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ip = get_remote_ip()
    dev = get_user_agent()
    city, country, _, _ = get_location_from_ip(ip)
    loc_str = f"{city} - {country}"
    c.execute('''INSERT INTO submissions (username, report_link, note, timestamp, ip, device, location, status)
                 VALUES (?,?,?,?,?,?,?,?)''', (username, link, note, ts, ip, dev, loc_str, "Active"))
    conn.commit()

def get_submissions(username=None, from_d=None, to_d=None):
    query = "SELECT * FROM submissions WHERE status='Active'"
    params = []
    if username and username != "Tất cả":
        query += " AND username=?"
        params.append(username)
    if from_d and to_d:
        query += " AND timestamp BETWEEN ? AND ?"
        params.append(f"{from_d} 00:00:00"); params.append(f"{to_d} 23:59:59")
    query += " ORDER BY id DESC"
    c.execute(query, tuple(params))
    return c.fetchall()

def delete_submission(sub_id):
    c.execute("UPDATE submissions SET status='Deleted' WHERE id=?", (sub_id,))
    conn.commit()

def get_history_stats(username=None, from_d=None, to_d=None):
    query = "SELECT * FROM history WHERE 1=1"
    params = []
    if username and username != "Tất cả":
        query += " AND username=?"
        params.append(username)
    if from_d and to_d:
        query += " AND timestamp BETWEEN ? AND ?"
        params.append(f"{from_d} 00:00:00"); params.append(f"{to_d} 23:59:59")
    query += " ORDER BY timestamp DESC"
    c.execute(query, tuple(params))
    return c.fetchall()

def get_all_users():
    c.execute('SELECT username, role FROM users')
    return c.fetchall()

def delete_user_db(u):
    c.execute('DELETE FROM users WHERE username=?', (u,)); conn.commit()

def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()

init_db()
try: add_user("admin", make_hashes("admin123"), "admin")
except: pass

# ==========================================
# 3. CSS GIAO DIỆN (UI/UX)
# ==========================================
st.markdown("""
<style>
    .stButton>button { width: 100%; background-color: #1877f2; color: white; border-radius: 6px; font-weight: bold; padding: 10px; border:none; transition: 0.3s; }
    .stButton>button:hover { background-color: #166fe5; box-shadow: 0 4px 10px rgba(0,0,0,0.1); color: white; }
    div[data-testid="stToast"] { background-color: #fff; border-left: 5px solid #1877f2; color: #333; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { background-color: #f0f2f5; border-radius: 5px; }
    .stTabs [aria-selected="true"] { background-color: #e7f3ff; color: #1877f2; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. CORE LOGIC (XỬ LÝ LINK - V2 FINAL)
# ==========================================
def resolve_link_logic(input_str):
    input_str = str(input_str).strip()
    if not input_str: return None, None, "Trống"
    final_url = input_str
    post_id = "Không tìm thấy"
    note = "OK"
    try:
        short_domains = ["share", "goo.gl", "bit.ly", "fb.me", "short", "fbook", "fb.watch"]
        if any(d in input_str for d in short_domains):
            headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X)'}
            try:
                response = requests.head(input_str, allow_redirects=True, headers=headers, timeout=8)
                final_url = response.url
            except Exception as e: return input_str, "Error", f"Lỗi mạng: {str(e)}"
        
        final_url = final_url.replace("://m.facebook.com", "://www.facebook.com")
        if "?" in final_url:
            keep = ["permalink.php", "/watch", "profile.php", "story.php", "photo.php", "set=", "v="]
            if not any(k in final_url for k in keep): final_url = final_url.split("?")[0]
            else:
                for t in ["&mibextid=", "&fbclid=", "?mibextid=", "?fbclid="]: 
                    if t in final_url: final_url = final_url.split(t)[0]

        patterns = [r'fbid=(\d+)', r'v=(\d+)', r'/posts/(\d+)', r'/videos/(\d+)', r'/reel/(\d+)',
                    r'/stories/[a-zA-Z0-9.]+/(?P<id>\d+)', r'story_fbid=(\d+)', r'multi_permalinks=(\d+)',
                    r'group_id=(\d+)', r'/groups/[^/]+/permalink/(\d+)', r'id=(\d+)', r'/(\d+)$']
        
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
        else: return final_url, "Không tìm thấy ID", "Cảnh báo"
    except Exception as e: return input_str, "Lỗi Code", str(e)

# ==========================================
# 5. GIAO DIỆN CHÍNH
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ''
if 'role' not in st.session_state: st.session_state['role'] = ''

# --- MÀN HÌNH ĐĂNG NHẬP ---
if not st.session_state['logged_in']:
    st.title("🔐 Đăng Nhập Hệ Thống")
    c1, c2 = st.columns(2)
    with c1:
        u = st.text_input("Tài khoản")
        p = st.text_input("Mật khẩu", type='password')
        if st.button("Đăng Nhập"):
            res = login(u, make_hashes(p))
            if res:
                st.session_state['logged_in'] = True
                st.session_state['username'] = u
                st.session_state['role'] = res[0][2]
                log_history(u, "Đăng Nhập", 0)
                st.toast(f"Xin chào {u}!", icon="👋")
                time.sleep(0.5); st.rerun()
            else: st.error("Sai tài khoản hoặc mật khẩu")

# --- MÀN HÌNH LÀM VIỆC ---
else:
    with st.sidebar:
        st.header(f"👤 {st.session_state['username']}")
        st.caption(f"Quyền: {st.session_state['role'].upper()}")
        st.markdown("---")
        if st.button("🚪 Đăng Xuất"):
            log_history(st.session_state['username'], "Đăng Xuất", 0)
            st.session_state['logged_in'] = False
            st.rerun()

    st.title("💎 Hệ Thống Quản Lý Link & CTV")

    # --- PHÂN QUYỀN HIỂN THỊ ---
    if st.session_state['role'] == 'admin':
        tabs = st.tabs(["🚀 TOOL ĐỔI LINK", "📂 KHO BÁO CÁO (ADMIN)", "📊 QUẢN TRỊ & XUẤT FILE"])
    else:
        tabs = st.tabs(["🚀 TOOL ĐỔI LINK", "📤 NỘP BÁO CÁO", "📊 THỐNG KÊ CÁ NHÂN"])

    # ==================================================
    # TAB 1: TOOL ĐỔI LINK (DÙNG CHUNG CHO TẤT CẢ)
    # ==================================================
    with tabs[0]:
        st.info("💡 Hỗ trợ: Nhập thủ công HOẶC Upload File Excel/TXT (Tool tự ghép kết quả vào file).")
        
        file_input = st.file_uploader("📂 Upload File (Excel/TXT)", type=['xlsx', 'txt'])
        if file_input: st.success(f"Đã nhận file: {file_input.name}")
        
        raw_input = st.text_area("📝 Hoặc nhập thủ công (Mỗi dòng 1 link):", height=100)

        c1, c2 = st.columns([1, 4])
        with c1: start_btn = st.button("▶ BẮT ĐẦU CHẠY")
        with c2: 
            if st.button("🗑️ RESET / XÓA"): 
                st.session_state['data'] = []; st.session_state['input_type'] = None; st.rerun()

        if 'data' not in st.session_state: st.session_state['data'] = []

        if start_btn:
            input_lines = []
            st.session_state['input_type'] = 'manual'
            
            # Ưu tiên xử lý File
            if file_input:
                st.session_state['input_type'] = 'file'
                st.session_state['file_name'] = file_input.name
                if file_input.name.endswith('.xlsx'):
                    df_up = pd.read_excel(file_input)
                    input_lines = df_up[df_up.columns[0]].astype(str).tolist()
                    st.session_state['uploaded_df'] = df_up
                else:
                    input_lines = [x for x in file_input.getvalue().decode("utf-8").split('\n') if x.strip()]
            elif raw_input.strip():
                input_lines = [x for x in raw_input.split('\n') if x.strip()]

            if input_lines:
                total = len(input_lines)
                log_history(st.session_state['username'], "Chạy Tool", total)
                st.toast(f"Đang xử lý {total} dòng...", icon="🚀")
                
                prog = st.progress(0); stt = st.empty(); res = [None]*total
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    f_map = {executor.submit(resolve_link_logic, l): i for i, l in enumerate(input_lines)}
                    done = 0
                    for future in concurrent.futures.as_completed(f_map):
                        idx = f_map[future]
                        try:
                            l, i, n = future.result()
                            res[idx] = {"Link Gốc": input_lines[idx], "Link Chuẩn": l, "Post ID": i, "Ghi chú": n}
                        except: res[idx] = {"Link Gốc": input_lines[idx], "Link Chuẩn": "Lỗi", "Post ID": "Lỗi", "Ghi chú": "Lỗi"}
                        done += 1; prog.progress(done/total); stt.text(f"Đang chạy... {done}/{total}")
                
                st.session_state['data'] = res
                st.toast("Hoàn thành!", icon="✅"); stt.empty()
            else:
                st.toast("Chưa có dữ liệu đầu vào!", icon="⚠️")

        # HIỂN THỊ KẾT QUẢ
        if st.session_state['data']:
            df_res = pd.DataFrame(st.session_state['data'])
            
            # Bảng Link Clickable (Hiện Full URL)
            st.data_editor(
                df_res,
                column_config={
                    "Link Chuẩn": st.column_config.LinkColumn(
                        "Link Chuẩn (Click mở)", display_text=None, validate="^https://.*", width="large"
                    )
                },
                disabled=True, use_container_width=True
            )
            
            # --- COPY & EXPORT ---
            st.markdown("---")
            st.markdown("### 📥 Thao Tác Nhanh")
            
            txt_all = df_res.to_csv(sep='\t', index=False)
            txt_links = "\n".join([str(x) for x in df_res["Link Chuẩn"] if x])
            txt_ids = "\n".join([str(x) for x in df_res["Post ID"] if x and x != "Không tìm thấy"])

            # Xử lý File Excel thông minh (Ghép cột)
            out = BytesIO()
            fname = "ket_qua.xlsx"
            if st.session_state.get('input_type') == 'file' and st.session_state.get('file_name', '').endswith('.xlsx'):
                df_root = st.session_state['uploaded_df']
                df_root['Link Chuẩn (Mới)'] = df_res['Link Chuẩn']
                df_root['Post ID (Mới)'] = df_res['Post ID']
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer: df_root.to_excel(writer, index=False)
                fname = f"DONE_{st.session_state['file_name']}"
                st.info("ℹ️ File tải xuống sẽ bao gồm dữ liệu cũ của bạn + Cột kết quả mới.")
            else:
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer: df_res.to_excel(writer, index=False)

            t1, t2, t3, t4 = st.tabs(["COPY ALL", "COPY LINK", "COPY ID", "TẢI EXCEL"])
            with t1: st.code(txt_all, language="text")
            with t2: st.code(txt_links, language="text")
            with t3: st.code(txt_ids, language="text")
            with t4:
                st.download_button("📥 Tải File Kết Quả (.xlsx)", out.getvalue(), fname, on_click=lambda: st.toast("Đã tải file!", icon="📂"))

    # ==================================================
    # LOGIC RIÊNG CHO USER (CTV)
    # ==================================================
    if st.session_state['role'] != 'admin':
        # TAB 2: NỘP BÁO CÁO
        with tabs[1]:
            st.subheader("📤 Nộp Link Báo Cáo (Google Sheets)")
            st.info("Dán link Google Sheet hoặc Drive vào đây. Admin sẽ nhận được ngay lập tức.")
            
            with st.form("sub_form"):
                lnk = st.text_input("🔗 Link Google Sheet:")
                nte = st.text_input("📝 Ghi chú:")
                if st.form_submit_button("Gửi Báo Cáo"):
                    if "http" in lnk:
                        submit_report(st.session_state['username'], lnk, nte)
                        st.toast("Đã nộp thành công!", icon="📩"); st.success("Đã gửi cho Admin!")
                    else: st.error("Link không hợp lệ!")
            
            st.markdown("---")
            st.write("🕒 **Lịch sử nộp (Trong phiên này)**")
            my_subs = get_submissions(st.session_state['username'])
            if my_subs:
                for sub in my_subs[:5]:
                    c1, c2, c3 = st.columns([4, 2, 1])
                    c1.markdown(f"📄 [{sub[2]}]({sub[2]}) ({sub[3]})")
                    c2.write(f"{sub[4]}")
                    if c3.button("Hoàn tác", key=f"d_{sub[0]}"):
                        delete_submission(sub[0])
                        st.toast("Đã thu hồi!", icon="↩️"); time.sleep(0.5); st.rerun()
            else: st.info("Chưa nộp báo cáo nào.")

        # TAB 3: THỐNG KÊ CÁ NHÂN
        with tabs[2]:
            st.subheader(f"📊 Thống Kê Của {st.session_state['username']}")
            hist = get_history_stats(st.session_state['username'])
            if hist:
                df_h = pd.DataFrame(hist, columns=["User", "Hành động", "SL Link", "Time", "IP", "Dev", "City", "Country", "Lat", "Lon"])
                m1, m2 = st.columns(2)
                m1.metric("Lần chạy tool", len(df_h[df_h['Hành động']=="Chạy Tool"]))
                m2.metric("Tổng Link xử lý", df_h[df_h['Hành động']=="Chạy Tool"]['SL Link'].sum())
                st.dataframe(df_h[["Time", "Hành động", "SL Link"]], use_container_width=True)

    # ==================================================
    # LOGIC RIÊNG CHO ADMIN
    # ==================================================
    else:
        # TAB 2: KHO BÁO CÁO
        with tabs[1]:
            st.subheader("📂 Kho Báo Cáo (Google Sheets)")
            users_list = ["Tất cả"] + [u[0] for u in get_all_users()]
            f_u = st.selectbox("Lọc nhân viên:", users_list)
            
            subs = get_submissions(f_u)
            if subs:
                df_s = pd.DataFrame(subs, columns=["ID", "User", "Report Link", "Note", "Time", "IP", "Dev", "Loc", "Status"])
                df_s.insert(0, "STT", range(1, 1+len(df_s)))
                
                st.data_editor(
                    df_s[["STT", "User", "Report Link", "Note", "Time", "IP", "Dev", "Loc"]],
                    column_config={
                        "Report Link": st.column_config.LinkColumn("Link Báo Cáo", display_text="🔗 Mở Sheet", width="medium"),
                        "User": st.column_config.TextColumn("Nhân viên", width="small")
                    },
                    hide_index=True, use_container_width=True, disabled=True
                )
            else: st.warning("Chưa có báo cáo nào.")

        # TAB 3: QUẢN TRỊ & XUẤT FILE
        with tabs[2]:
            st.subheader("📊 Quản Trị Hệ Thống")
            
            # 1. Bộ lọc xuất file
            c1, c2, c3 = st.columns(3)
            with c1: fd = st.date_input("Từ ngày")
            with c2: td = st.date_input("Đến ngày")
            with c3: tu = st.selectbox("Chọn User xuất file", users_list)
            
            if st.button("🚀 XUẤT DỮ LIỆU HỆ THỐNG (FULL)"):
                # Lấy dữ liệu
                raw_h = get_history_stats(tu, fd, td)
                df_h = pd.DataFrame(raw_h, columns=["User", "Hành động", "SL Link", "Time", "IP", "Dev", "City", "Country", "Lat", "Lon"])
                
                raw_s = get_submissions(tu, fd, td)
                df_s = pd.DataFrame(raw_s, columns=["ID", "User", "Link", "Note", "Time", "IP", "Dev", "Loc", "Status"])
                
                # Tính lương (KPI)
                kpi = df_h[df_h['Hành động']=="Chạy Tool"].groupby("User")['SL Link'].sum().reset_index()
                
                out_ad = BytesIO()
                with pd.ExcelWriter(out_ad, engine='xlsxwriter') as writer:
                    kpi.to_excel(writer, sheet_name='KPI_Tong', index=False)
                    df_h.to_excel(writer, sheet_name='Lich_Su_Chi_Tiet', index=False)
                    df_s.to_excel(writer, sheet_name='DS_Nop_Bao_Cao', index=False)
                
                st.download_button("📥 TẢI BÁO CÁO ADMIN (.xlsx)", out_ad.getvalue(), f"Admin_Report_{fd}_{td}.xlsx")
                st.success("Đã tạo báo cáo thành công!")

            st.divider()
            
            # 2. Biểu đồ & Map
            
            c_map, c_chart = st.columns([1, 1])
            with c_map:
                st.write("🌍 **Bản Đồ Hoạt Động**")
                raw_all = get_history_stats(tu)
                if raw_all:
                    df_all = pd.DataFrame(raw_all, columns=["User", "Act", "Count", "Time", "IP", "Dev", "City", "Country", "lat", "lon"])
                    map_data = df_all[df_all['lat'] != 0][['lat', 'lon']]
                    st.map(map_data)
            
            with c_chart:
                st.write("📊 **Top Năng Suất**")
                if raw_all:
                    chart_data = df_all[df_all['Act']=="Chạy Tool"].groupby("User")['Count'].sum().sort_values(ascending=False)
                    st.bar_chart(chart_data)

            # 3. Quản lý User
            st.divider()
            with st.expander("⚙️ QUẢN LÝ TÀI KHOẢN (THÊM/XÓA)"):
                c_a, c_b = st.columns(2)
                with c_a:
                    nu = st.text_input("User Mới"); np = st.text_input("Pass Mới", type="password")
                    nr = st.selectbox("Role", ["user", "admin"])
                    if st.button("Tạo User"): 
                        if add_user(nu, make_hashes(np), nr): st.success("OK"); st.rerun()
                        else: st.error("Trùng tên!")
                with c_b:
                    users_del = [u[0] for u in get_all_users()]
                    du = st.selectbox("Xóa User", users_del)
                    if st.button("Xóa Ngay"):
                        delete_user_db(du); st.rerun()
