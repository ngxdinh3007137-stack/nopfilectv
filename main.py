import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import time
import re
import pytz
import gspread
import concurrent.futures
import threading
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from io import BytesIO

# =================================================================
# 1. CẤU HÌNH HỆ THỐNG & UI (Giao diện Mobile-Responsive)
# =================================================================
st.set_page_config(
    page_title="Hệ Thống Quản Lý KPI & Link Facebook V18.0",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
db_lock = threading.Lock()

def get_now_vn(): return datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
def get_today_vn(): return datetime.now(VN_TZ).strftime("%Y-%m-%d")

# CSS Cao cấp cho UI chuyên nghiệp
st.markdown("""
<style>
    .main { background-color: #f4f7f6; }
    .stButton>button { border-radius: 12px; height: 3em; font-weight: bold; width: 100%; transition: 0.3s; }
    .stButton>button:hover { background-color: #1877f2; color: white; border: none; }
    .report-card { 
        background: white; padding: 20px; border-radius: 15px; 
        margin-bottom: 12px; border-left: 8px solid #1877f2;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .status-ok { color: #ffffff; background: #28a745; padding: 5px 15px; border-radius: 20px; font-size: 13px; font-weight: bold; }
    .status-wait { color: #ffffff; background: #ffc107; padding: 5px 15px; border-radius: 20px; font-size: 13px; font-weight: bold; }
    [data-testid="stMetricValue"] { color: #1877f2; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# =================================================================
# 2. MODULE GOOGLE SHEETS (Đồng bộ dữ liệu)
# =================================================================
def sync_to_gsheet(data_row, sheet_name="KPI_Data"):
    """Đồng bộ dữ liệu thời gian thực lên Google Sheets"""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        # File service_account.json phải có trong thư mục gốc
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open("Quan_Ly_Vận_Hành").worksheet(sheet_name)
        sheet.append_row(data_row)
    except:
        pass # Tránh lỗi web khi chưa cấu hình Sheet

# =================================================================
# 3. DATABASE ENGINE (SQLite Đa Truy Cập)
# =================================================================
DB_NAME = 'system_core_v18.db'

def run_query(query, params=(), is_write=False):
    with db_lock:
        with sqlite3.connect(DB_NAME, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                if is_write:
                    conn.commit()
                    return True
                return cursor.fetchall()
            except Exception as e:
                st.error(f"SQL Error: {e}")
                return None

def init_db():
    # Bảng Users: Quản lý CTV và Thông tin liên hệ Telegram
    run_query('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT, 
        fullname TEXT, telegram TEXT, created_at TEXT)''', is_write=True)
    
    # Bảng Submissions: Quản lý link và Check đạt (is_verified)
    run_query('''CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, 
        post_id TEXT, report_link TEXT, note TEXT, 
        timestamp TEXT, is_verified INTEGER DEFAULT 0, verified_at TEXT)''', is_write=True)

    # Khởi tạo Admin mặc định
    if not run_query("SELECT 1 FROM users WHERE username='admin'"):
        admin_pw = hashlib.sha256("admin123".encode()).hexdigest()
        run_query("INSERT INTO users VALUES (?,?,?,?,?,?)", 
                 ("admin", admin_pw, "admin", "Administrator", "@admin_kpi", get_now_vn()), is_write=True)

init_db()

# =================================================================
# 4. MODULE XỬ LÝ LINK FACEBOOK & BÓC TÁCH ID
# =================================================================
def extract_id_logic(url):
    """Trái tim của hệ thống: Chuyển mọi loại link về ID Post duy nhất"""
    url = str(url).strip()
    if url.isdigit(): return url
    # Các mẫu Regex bao quát Page, Group, Reel, Video, Story
    patterns = [
        r'posts/(\d+)', r'permalink/(\d+)', r'fbid=(\d+)', 
        r'v=(\d+)', r'videos/(\d+)', r'reel/(\d+)',
        r'story_fbid=(\d+)', r'id=(\d+)', r'/(\d+)/?$'
    ]
    for p in patterns:
        m = re.search(p, url)
        if m: return m.group(1)
    return None

def process_bulk_links(links):
    """Xử lý hàng loạt link bằng Multi-threading để web không bị treo"""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(extract_id_logic, url): url for url in links}
        for future in concurrent.futures.as_completed(future_to_url):
            results.append(future.result())
    return results

# =================================================================
# 5. GIAO DIỆN CHÍNH (LOGIN/USER/ADMIN)
# =================================================================
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    # Màn hình đăng nhập/đăng ký tích hợp
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.title("🔐 HỆ THỐNG KPI V18")
        tab_login, tab_reg = st.tabs(["Đăng Nhập", "Đăng Ký CTV Mới"])
        
        with tab_login:
            with st.form("f_login"):
                u = st.text_input("Tài khoản")
                p = st.text_input("Mật khẩu", type="password")
                if st.form_submit_button("VÀO HỆ THỐNG"):
                    pw = hashlib.sha256(p.encode()).hexdigest()
                    res = run_query("SELECT * FROM users WHERE username=? AND password=?", (u, pw))
                    if res:
                        st.session_state.update({'logged_in': True, 'username': u, 'role': res[0][2], 'fullname': res[0][3]})
                        st.rerun()
                    else: st.error("Sai tài khoản hoặc mật khẩu!")
        
        with tab_reg:
            with st.form("f_reg"):
                nu = st.text_input("Username (viết liền không dấu)")
                np = st.text_input("Password", type="password")
                nf = st.text_input("Họ và Tên Thật")
                nt = st.text_input("Telegram (@username)")
                if st.form_submit_button("XÁC NHẬN ĐĂNG KÝ"):
                    if nu and np and nt:
                        pw = hashlib.sha256(np.encode()).hexdigest()
                        if run_query("INSERT INTO users VALUES (?,?,?,?,?,?)", (nu, pw, 'user', nf, nt, get_now_vn()), is_write=True):
                            st.success("Đăng ký thành công! Hãy quay lại tab Đăng nhập.")
                        else: st.error("Tên tài khoản đã tồn tại trên hệ thống!")

else:
    # Sidebar Điều hướng
    with st.sidebar:
        st.header(f"👋 {st.session_state.fullname}")
        st.caption(f"Role: {st.session_state.role.upper()}")
        st.divider()
        menu = ["🚀 Tool Xử Lý Link", "📤 Nộp Báo Cáo", "💰 Thu Nhập & KPI"]
        if st.session_state.role == 'admin':
            menu.append("👑 Admin Dashboard")
        choice = st.radio("CHỨC NĂNG", menu)
        if st.button("🚪 Đăng Xuất"):
            st.session_state.logged_in = False
            st.rerun()

    # --- CHỨC NĂNG 1: TOOL XỬ LÝ (Multi-threading) ---
    if choice == "🚀 Tool Xử Lý Link":
        st.header("🚀 Tool Chuyển Đổi Link Hàng Loạt")
        txt_input = st.text_area("Dán danh sách link share (Mỗi dòng 1 link):", height=200)
        if st.button("BẮT ĐẦU CHUYỂN ĐỔI"):
            links = [l.strip() for l in txt_input.split('\n') if l.strip()]
            if links:
                ids = process_bulk_links(links)
                df_res = pd.DataFrame({"Link Gốc": links, "ID Bóc Tách": ids})
                st.dataframe(df_res, use_container_width=True)
                st.download_button("📥 Tải Kết Quả Excel", df_res.to_csv().encode('utf-8'), "ketqua.csv")
            else: st.warning("Vui lòng nhập link!")

    # --- CHỨC NĂNG 2: NỘP BÁO CÁO (Chống trùng ID 3 lần) ---
    elif choice == "📤 Nộp Báo Cáo":
        st.header("📤 Nộp Báo Cáo Link Đã Làm")
        with st.form("f_submit", clear_on_submit=True):
            r_link = st.text_input("Dán link Post Facebook:")
            r_note = st.text_input("Ghi chú (Tên page/nhóm):")
            if st.form_submit_button("XÁC NHẬN NỘP"):
                pid = extract_id_logic(r_link)
                if pid:
                    # Logic Chống Trùng ID Post 3 lần
                    existing = run_query("SELECT COUNT(*) FROM submissions WHERE post_id=?", (pid,))[0][0]
                    if existing >= 3:
                        st.error(f"❌ ID Post này ({pid}) đã được nộp đủ 3 lần bởi người khác. Không tính thêm!")
                    else:
                        now = get_now_vn()
                        run_query("INSERT INTO submissions (username, post_id, report_link, note, timestamp) VALUES (?,?,?,?,?)",
                                 (st.session_state.username, pid, r_link, r_note, now), is_write=True)
                        # Đồng bộ Sheet LOG
                        sync_to_gsheet([now, st.session_state.username, pid, r_link, r_note, "Pending"], "LOG_SUBMISSIONS")
                        st.success(f"✅ Đã nhận báo cáo! ID: {pid}")
                else: st.error("Link không hợp lệ!")

    # --- CHỨC NĂNG 3: THU NHẬP CTV ---
    elif choice == "💰 Thu Nhập & KPI":
        st.header("💰 Bảng Lương & Hiệu Suất Cá Nhân")
        c1, c2 = st.columns(2)
        total_n = run_query("SELECT COUNT(*) FROM submissions WHERE username=?", (st.session_state.username,))[0][0]
        total_v = run_query("SELECT COUNT(*) FROM submissions WHERE username=? AND is_verified=1", (st.session_state.username,))[0][0]
        
        c1.metric("Tổng link đã nộp", f"{total_n} link")
        c2.metric("Số link ĐẠT (Tính lương)", f"{total_v} link")
        
        st.write("### 🕒 Lịch sử nộp gần đây")
        logs = run_query("SELECT report_link, is_verified, timestamp FROM submissions WHERE username=? ORDER BY id DESC LIMIT 10", (st.session_state.username,))
        for l in logs:
            st.markdown(f"""
            <div class="report-card">
                {'<span class="status-ok">✅ ĐẠT</span>' if l[1]==1 else '<span class="status-wait">⏳ CHỜ DUYỆT</span>'}
                <br><br><b>Link:</b> {l[0]}<br><small>Nộp lúc: {l[2]}</small>
            </div>
            """, unsafe_allow_html=True)

    # --- CHỨC NĂNG 4: ADMIN DASHBOARD (Đối soát & Thống kê) ---
    elif choice == "👑 Admin Dashboard":
        st.title("👑 Tổng Quản Trị Hệ Thống")
        t1, t2, t3 = st.tabs(["📊 Thống Kê Tổng", "✅ Duyệt Đạt Hàng Loạt", "👥 CTV & Lương"])
        
        with t1:
            today = get_today_vn()
            st.subheader(f"Dữ liệu ngày {today}")
            col_a, col_b, col_c = st.columns(3)
            
            n_today = run_query("SELECT COUNT(*) FROM submissions WHERE timestamp LIKE ?", (f"{today}%",))[0][0]
            v_today = run_query("SELECT COUNT(*) FROM submissions WHERE is_verified=1 AND verified_at LIKE ?", (f"{today}%",))[0][0]
            
            col_a.metric("CTV Nộp Hôm Nay", f"{n_today}")
            col_b.metric("Đã Duyệt Đạt", f"{v_today}")
            col_c.metric("Chưa Xử Lý", f"{n_today - v_today}")
            
            st.write("### 🥇 Top CTV Năng Suất (Link Đạt)")
            top_ctv = run_query("SELECT username, COUNT(*) FROM submissions WHERE is_verified=1 GROUP BY username ORDER BY COUNT(*) DESC")
            if top_ctv:
                st.bar_chart(pd.DataFrame(top_ctv, columns=["CTV", "Số Link Đạt"]).set_index("CTV"))

        with t2:
            st.subheader("✅ Đối Soát Kết Quả Từ Tool Quét")
            st.caption("Dán danh sách ID Post đã quét Comment thành công vào đây để hệ thống tự động 'Check Đạt' cho CTV.")
            id_list_input = st.text_area("Danh sách ID Post đạt (Mỗi dòng 1 ID):", height=200)
            if st.button("🚀 XÁC NHẬN ĐẠT CHO CTV"):
                list_ids = [i.strip() for i in id_list_input.split('\n') if i.strip()]
                now = get_now_vn()
                count_ok = 0
                for pid in list_ids:
                    # Duyệt đạt cho tất cả submissions có post_id này
                    res = run_query("UPDATE submissions SET is_verified=1, verified_at=? WHERE post_id=? AND is_verified=0", 
                                   (now, pid), is_write=True)
                    if res: count_ok += 1
                st.success(f"Đã cập nhật trạng thái ĐẠT cho các CTV nộp {count_ok} ID tương ứng.")
                st.rerun()

        with t3:
            st.subheader("👥 Quản lý Nhân sự & Telegram")
            ctv_list = run_query("SELECT username, fullname, telegram, created_at FROM users WHERE role='user'")
            df_ctv = pd.DataFrame(ctv_list, columns=["Username", "Họ Tên", "Telegram", "Ngày Tham Gia"])
            st.dataframe(df_ctv, use_container_width=True)
            
            # Xuất bảng lương Excel
            if st.button("📥 XUẤT BẢNG LƯƠNG TỔNG (EXCEL)"):
                salary_data = run_query("""SELECT username, COUNT(*) FROM submissions 
                                        WHERE is_verified=1 GROUP BY username""")
                df_salary = pd.DataFrame(salary_data, columns=["CTV", "Số Link Đạt"])
                st.download_button("Tải File Excel", df_salary.to_csv().encode('utf-8'), "bang_luong.csv")
