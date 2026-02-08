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
from urllib.parse import unquote, urlparse, parse_qs
from streamlit.web.server.websocket_headers import _get_websocket_headers

# ==========================================
# 1. CẤU HÌNH & HÀM HỖ TRỢ
# ==========================================
st.set_page_config(
    page_title="Hệ Thống Lấy Link Address Bar V9",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- TRACKING ---
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
        return "Other Device"
    except: return "Unknown Device"

def get_location_from_ip(ip):
    if ip in ["127.0.0.1", "::1", "Unknown"]: return "Localhost", "VN"
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=2).json()
        if r['status'] == 'success': return r.get('city', 'Unknown'), r.get('country', 'Unknown')
    except: pass
    return "Unknown", "Unknown"

# ==========================================
# 2. DATABASE (SQLITE)
# ==========================================
conn = sqlite3.connect('data_v9_final.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, password TEXT, role TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS submissions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, report_link TEXT, note TEXT, timestamp TEXT,
        ip TEXT, device TEXT, location TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history(
        username TEXT, action TEXT, count INTEGER, timestamp TEXT, 
        ip TEXT, device TEXT, city TEXT, country TEXT, lat REAL, lon REAL)''')
    conn.commit()

def add_user(u, p, r):
    try: c.execute('INSERT INTO users VALUES (?,?,?)', (u, p, r)); conn.commit(); return True
    except: return False

def login(u, p):
    c.execute('SELECT * FROM users WHERE username=? AND password=?', (u, p))
    return c.fetchall()

def submit_report(u, l, n):
    ip = get_remote_ip(); ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dev = get_user_agent(); city, country = get_location_from_ip(ip)
    c.execute('INSERT INTO submissions (username, report_link, note, timestamp, ip, device, location, status) VALUES (?,?,?,?,?,?,?,?)',
              (u, l, n, ts, ip, dev, f"{city}-{country}", "Active")); conn.commit()

def log_history(u, act, count):
    ip = get_remote_ip(); dev = get_user_agent(); city, country = get_location_from_ip(ip)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Lưu ý: Hàm này dùng để vẽ bản đồ nếu cần (bỏ qua lat/lon để đơn giản hóa code này)
    c.execute('INSERT INTO history (username, action, count, timestamp, ip, device, city, country, lat, lon) VALUES (?,?,?,?,?,?,?,?,?,?)', 
              (u, act, count, ts, ip, dev, city, country, 0, 0)); conn.commit()

def get_submissions(u=None):
    q = "SELECT * FROM submissions WHERE status='Active'"
    p = []
    if u and u != "Tất cả": q += " AND username=?"; p.append(u)
    q += " ORDER BY id DESC"
    c.execute(q, tuple(p)); return c.fetchall()

def delete_submission(sid): c.execute("UPDATE submissions SET status='Deleted' WHERE id=?", (sid,)); conn.commit()
def get_all_users(): c.execute('SELECT username, role FROM users'); return c.fetchall()
def delete_user_db(u): c.execute('DELETE FROM users WHERE username=?', (u,)); conn.commit()
def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()

init_db()
try: add_user("admin", make_hashes("admin123"), "admin")
except: pass

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
# 4. CORE LOGIC V9.0 (UPDATE CHO LINK GROUP)
# ==========================================
def resolve_link_logic(input_str):
    """
    Logic V9: Xử lý link share/p trong Group và trả về link Address Bar chuẩn nhất.
    """
    input_str = str(input_str).strip()
    if not input_str: return None, None, "Trống"
    
    final_url = input_str
    post_id = "Không tìm thấy"
    note = "OK"

    try:
        # 1. GIẢ LẬP TRÌNH DUYỆT (FOLLOW REDIRECT)
        trigger_domains = ["share", "goo.gl", "bit.ly", "fb.me", "short", "fbook", "fb.watch", "facebook.com/share"]
        
        if any(d in input_str for d in trigger_domains):
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Sec-Fetch-Site': 'none',
                'Upgrade-Insecure-Requests': '1'
            }
            try:
                # Bắt buộc allow_redirects=True để nó nhảy từ share -> groups/posts
                response = requests.head(input_str, allow_redirects=True, headers=headers, timeout=12)
                final_url = response.url 
            except Exception as e:
                note = f"Lỗi Redirect: {str(e)}"

        # 2. CLEAN URL
        final_url = unquote(final_url)
        final_url = final_url.replace("://m.facebook.com", "://www.facebook.com")
        
        # Cắt bỏ tham số rác (mibextid, ref, etc.)
        if "?" in final_url:
            base_url = final_url.split("?")[0]
            params = final_url.split("?")[1]
            
            # Chỉ giữ lại các tham số quan trọng
            keep_params = ["id", "v", "set", "fbid", "comment_id", "reply_comment_id", "story_fbid"]
            clean_query = []
            
            for p in params.split("&"):
                key = p.split("=")[0]
                if key in keep_params:
                    clean_query.append(p)
            
            if clean_query:
                final_url = f"{base_url}?{'&'.join(clean_query)}"
            else:
                final_url = base_url

        # 3. TRÍCH XUẤT ID (ƯU TIÊN LINK GROUP POST)
        patterns = [
            r'/groups/[^/]+/posts/(\d+)',           # <--- ƯU TIÊN 1: Link bài viết trong Group
            r'/groups/[^/]+/permalink/(\d+)',       # Link group permalink cũ
            r'/posts/(\d+)',                        # Bài viết thường
            r'fbid=(\d+)',                          # Link ảnh/cũ
            r'v=(\d+)',                             # Link video tham số
            r'/videos/(\d+)',                       # Link video path
            r'/reel/(\d+)',                         # Reels
            r'/stories/[a-zA-Z0-9.]+/(?P<id>\d+)',  # Story
            r'story_fbid=(\d+)', 
            r'multi_permalinks=(\d+)', 
            r'group_id=(\d+)', 
            r'id=(\d+)', 
            r'/(\d+)/?$'                            # ID cuối cùng
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

        if post_id != "Không tìm thấy":
            return final_url, post_id, "Thành công"
        else:
            if "facebook.com" in final_url:
                return final_url, "ID Ẩn/Chữ", "Link Address Bar (ID ẩn)"
            return final_url, "Không tìm thấy ID", "Cảnh báo"

    except Exception as e:
        return input_str, "Lỗi Code", str(e)


# ==========================================
# 5. GIAO DIỆN CHÍNH
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ''
if 'role' not in st.session_state: st.session_state['role'] = ''

# --- LOGIN ---
if not st.session_state['logged_in']:
    st.title("🔐 Đăng Nhập Hệ Thống V9")
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

    st.title("💎 Hệ Thống Lấy Link Chuẩn (Address Bar)")

    if st.session_state['role'] == 'admin':
        tabs = st.tabs(["🚀 TOOL ĐỔI LINK", "📂 KHO BÁO CÁO", "📊 QUẢN TRỊ ADMIN"])
    else:
        tabs = st.tabs(["🚀 TOOL ĐỔI LINK", "📤 NỘP BÁO CÁO", "📊 LỊCH SỬ"])

    # --- TAB 1: TOOL ---
    with tabs[0]:
        st.info("💡 Copy link (kể cả link Share trong Group) -> Tool sẽ trả về Link chuẩn Address Bar.")
        
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
                st.toast(f"Đang giả lập trình duyệt lấy {tot} link...", icon="🚀")
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
            st.data_editor(df_r, column_config={"Link Address Bar": st.column_config.LinkColumn("Link Address Bar", display_text=None)}, use_container_width=True)
            
            # Xuất File (Ghép cột nếu input là Excel)
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

    # --- TAB 2 & 3: GIỐNG CŨ (QUẢN LÝ) ---
    if st.session_state['role'] != 'admin':
        with tabs[1]:
            st.subheader("📤 Nộp Báo Cáo")
            with st.form("f_sub"):
                lnk = st.text_input("🔗 Link Google Sheet:"); nte = st.text_input("📝 Ghi chú:")
                if st.form_submit_button("Gửi"): 
                    if "http" in lnk: submit_report(st.session_state['username'], lnk, nte); st.success("Đã gửi!"); st.rerun()
                    else: st.error("Link lỗi!")
            
            st.write("🕒 **Lịch sử nộp phiên này**")
            mys = get_submissions(st.session_state['username'])
            if mys:
                for s in mys[:5]:
                    c1, c2 = st.columns([4, 1])
                    c1.markdown(f"📄 [{s[2]}]({s[2]}) ({s[4]})"); 
                    if c2.button("Hoàn tác", key=f"d_{s[0]}"): delete_submission(s[0]); st.rerun()

    else: # Admin
        with tabs[1]:
            st.subheader("📂 Kho Báo Cáo")
            sel_u = st.selectbox("Lọc User:", ["Tất cả"] + [u[0] for u in get_all_users()])
            subs = get_submissions(sel_u)
            if subs:
                df_s = pd.DataFrame(subs, columns=["ID", "User", "Link", "Note", "Time", "IP", "Dev", "Loc", "Stat"])
                st.data_editor(df_s[["User", "Link", "Note", "Time", "Loc"]], column_config={"Link": st.column_config.LinkColumn("Link", display_text="🔗 Mở")}, use_container_width=True)

        with tabs[2]:
            st.subheader("📊 Quản Trị")
            with st.expander("Thêm/Xóa User"):
                ua = st.text_input("New User"); pa = st.text_input("Pass", type="password"); ra = st.selectbox("Role", ["user", "admin"])
                if st.button("Tạo"): 
                    if add_user(ua, make_hashes(pa), ra): st.success("OK"); st.rerun()
                ud = st.selectbox("Del User", [u[0] for u in get_all_users()])
                if st.button("Xóa"): delete_user_db(ud); st.rerun()
