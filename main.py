import streamlit as st
import datetime
import math
import sqlite3
import calendar

# --- 1. ページ設定 ---
st.set_page_config(page_title="給料帳", layout="centered")

# --- 2. デザイン (ダークモード & コンパクト & シンプル) ---
st.markdown("""
    <style>
    /* 全体の背景をダークに固定 */
    .stApp {
        background-color: #0e1117;
        color: #fafafa;
    }
    
    /* コンテンツ余白 */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 4rem;
        max-width: 600px;
    }

    /* --- カレンダー (CSS Grid) --- */
    .calendar-grid {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 3px;
        margin-top: 5px;
    }
    
    /* 曜日ヘッダー */
    .cal-header {
        text-align: center;
        font-size: 10px;
        font-weight: bold;
        color: #aaa;
        padding-bottom: 2px;
    }

    /* 日付マス (ダーク) */
    .cal-day {
        background-color: #262730;
        border: 1px solid #333;
        border-radius: 4px;
        height: 50px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }
    .cal-num { font-size: 10px; color: #ccc; margin: 0; line-height: 1.2; }
    .cal-pay { 
        font-size: 8.5px; 
        font-weight: bold; 
        color: #4da6ff; 
        line-height: 1.2; 
        white-space: nowrap; 
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
        padding: 0 2px;
    }
    .cal-today { border: 1px solid #4da6ff; background-color: #1e2a3a; }
    .cal-empty { background-color: transparent; border: none; }

    /* --- 合計表示エリア --- */
    .total-area {
        text-align: center;
        padding: 10px;
        background-color: #262730;
        border-radius: 8px;
        border: 1px solid #444;
        color: #fff;
        margin-bottom: 15px;
    }
    .total-amount { font-size: 22px; font-weight: bold; color: #4da6ff; }
    .total-sub { font-size: 10px; color: #aaa; }

    /* --- 履歴リスト --- */
    .history-row {
        border-bottom: 1px solid #333;
        padding: 8px 0;
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: #eee;
    }
    .tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 5px; font-weight: normal; }
    .tag-work { background: #1c3a5e; color: #aaddff; }
    .tag-break { background: #4a1a1a; color: #ffaaaa; }
    .tag-drive { background: #1a4a3a; color: #aaffdd; }
    
    /* スライダー調整 */
    .stSlider { padding-bottom: 10px !important; }
    .stSlider label { font-size: 12px; color: #ddd !important; }
    </style>
""", unsafe_allow_html=True)

# --- 3. データベース管理 ---
DB_PATH = "salary_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_str TEXT, type TEXT,
            start_h INTEGER, start_m INTEGER,
            end_h INTEGER, end_m INTEGER,
            distance_km REAL, manual_pay INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_record(date_str, r_type, sh, sm, eh, em, dist, pay=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO records (date_str, type, start_h, start_m, end_h, end_m, distance_km, manual_pay) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (date_str, r_type, sh, sm, eh, em, dist, pay))
    conn.commit()
    conn.close()

def delete_record_by_id(record_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM records WHERE id = ?', (record_id,))
    conn.commit()
    conn.close()

def get_records_by_date(date_str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM records WHERE date_str = ? ORDER BY start_h, start_m', (date_str,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_records():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM records')
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_min_record_date():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT MIN(date_str) FROM records')
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        return datetime.datetime.strptime(row[0], '%Y-%m-%d').date()
    return datetime.date.today()

def save_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()

def load_setting(key, default_value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default_value

init_db()

# --- 4. 計算ロジック ---
NIGHT_START = 22 * 60
NIGHT_END = 28 * 60
OVERTIME_THRESHOLD = 8 * 60

def calculate_daily_total(records, base_wage):
    work_minutes = set()
    break_minutes = set()
    drive_pay_total = 0
    
    for r in records:
        if r['type'] == 'DRIVE':
            drive_pay_total += calculate_driving_allowance(r['distance_km'])
            s = r['start_h'] * 60 + r['start_m']
            e = r['end_h'] * 60 + r['end_m']
            for m in range(s, e): work_minutes.add(m)
        elif r['type'] == 'WORK':
            s = r['start_h'] * 60 + r['start_m']
            e = r['end_h'] * 60 + r['end_m']
            for m in range(s, e): work_minutes.add(m)
        elif r['type'] == 'BREAK':
            s = r['start_h'] * 60 + r['start_m']
            e = r['end_h'] * 60 + r['end_m']
            for m in range(s, e): break_minutes.add(m)
    
    actual_work = sorted(list(work_minutes - break_minutes))
    total_min = len(actual_work)
    
    base_min_rate = base_wage / 60
    total_work_pay = 0.0
    
    for i, m in enumerate(actual_work):
        rate = base_min_rate
        if NIGHT_START <= m < NIGHT_END:
            rate += (base_min_rate * 0.25)
        if i >= OVERTIME_THRESHOLD:
            rate += (base_min_rate * 0.25)
        total_work_pay += rate
        
    return math.floor(total_work_pay) + drive_pay_total, total_min

def calculate_driving_allowance(km):
    if km < 0.1: return 0
    if km < 10: return 150
    if km >= 340: return 3300
    return 300 + (math.floor((km - 10) / 30) * 300)

def format_time_label(h, m):
    prefix = "翌" if h >= 24 else ""
    disp_h = h - 24 if h >= 24 else h
    return f"{prefix}{disp_h:02}:{m:02}"

# --- 5. セッション ---
if 'base_wage' not in st.session_state:
    st.session_state.base_wage = int(load_setting('base_wage', '1190'))

today = datetime.date.today()
if 'view_year' not in st.session_state: st.session_state.view_year = today.year
if 'view_month' not in st.session_state: st.session_state.view_month = today.month

def change_month(amount):
    m = st.session_state.view_month + amount
    y = st.session_state.view_year
    if m > 12: m = 1; y += 1
    elif m < 1: m = 12; y -= 1
    st.session_state.view_month = m
    st.session_state.view_year = y

def get_calendar_summary(wage):
    all_r = get_all_records()
    grouped = {}
    for r in all_r:
        d = r['date_str']
        if d not in grouped: grouped[d] = []
        grouped[d].append(r)
    
    summary = {}
    for d, recs in grouped.items():
        pay, mins = calculate_daily_total(recs, wage)
        summary[d] = {'pay': pay, 'min': mins}
    return summary

# --- 6. メイン表示 ---
tab_input, tab_calendar, tab_setting = st.tabs(["日次入力", "カレンダー", "設定"])

# ==========================================
# TAB: 設定
# ==========================================
with tab_setting:
    st.write("")
    st.subheader("設定")
    new_wage = st.number_input("基本時給 (円)", value=st.session_state.base_wage, step=10)
    if new_wage != st.session_state.base_wage:
        st.session_state.base_wage = new_wage
        save_setting('base_wage', new_wage)
        st.success("保存しました")
        st.rerun()
    
    st.markdown("""
    <div style='font-size:12px; color:#aaa; margin-top:10px;'>
    ・日中: 基本給<br>
    ・夜勤 (22:00-28:00): 1.25倍<br>
    ・残業 (8時間超): 1.25倍<br>
    ・運転手当: 距離に応じて加算
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# TAB: 日次入力
# ==========================================
with tab_input:
    st.write("")
    
    input_date = st.date_input("日付", value=datetime.date.today())
    input_date_str = input_date.strftime("%Y-%m-%d")
    
    st.markdown("---")
    record_type = st.radio("タイプ", ["勤務", "休憩", "運転"], horizontal=True, label_visibility="collapsed")
    
    def time_sliders(label, kh, km, dh, dm):
        curr_h = st.session_state.get(kh, dh)
        curr_m = st.session_state.get(km, dm)
        st.markdown(f"<div style='font-size:11px; font-weight:bold; color:#aaa;'>{label}: <span style='color:#4da6ff;'>{format_time_label(curr_h, curr_m)}</span></div>", unsafe_allow_html=True)
        c1, c2 = st.columns([1.3, 1])
        with c1: vh = st.slider("時", 0, 33, dh, key=kh, label_visibility="collapsed")
        with c2: vm = st.slider("分", 0, 59, dm, key=km, step=1, label_visibility="collapsed")
        return vh, vm

    sh, sm = time_sliders("開始", "sh_in", "sm_in", 9, 0)
    eh, em = time_sliders("終了", "eh_in", "em_in", 18, 0)
    
    dist_km = 0
    if "運転" in record_type:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        
        # 現在のシークバーの値を取得
        curr_km = st.session_state.get('d_km', 0.0)
        # リアルタイムで手当を計算
        curr_allowance = calculate_driving_allowance(curr_km)
        
        # 距離と手当を横並びで表示
        st.markdown(f"""
            <div style='display:flex; justify-content:space-between; align-items:end; margin-bottom:2px;'>
                <div style='font-size:11px; font-weight:bold; color:#55bb88;'>距離: {curr_km} km</div>
                <div style='font-size:11px; font-weight:bold; color:#55bb88;'>手当: ¥{curr_allowance:,}</div>
            </div>
        """, unsafe_allow_html=True)
        
        dist_km = st.slider("km", 0.0, 350.0, 0.0, 0.1, key="d_km", label_visibility="collapsed")
    
    st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
    
    if st.button("追加", type="primary", use_container_width=True):
        if (sh*60+sm) >= (eh*60+em):
            st.error("開始 < 終了 にしてください")
        elif "運転" in record_type and dist_km == 0:
            st.error("距離を入力してください")
        else:
            r_code = "DRIVE" if "運転" in record_type else "BREAK" if "休憩" in record_type else "WORK"
            add_record(input_date_str, r_code, sh, sm, eh, em, dist_km)
            st.rerun()
            
    st.markdown("<div style='font-size:12px; font-weight:bold; color:#888; margin-top:20px; margin-bottom:5px;'>登録済みリスト</div>", unsafe_allow_html=True)
    
    day_recs = get_records_by_date(input_date_str)
    day_pay, day_min = calculate_daily_total(day_recs, st.session_state.base_wage)
    
    if not day_recs:
        st.caption("なし")
    else:
        for r in day_recs:
            c1, c2 = st.columns([5, 1])
            with c1:
                time_str = f"{format_time_label(r['start_h'], r['start_m'])} ~ {format_time_label(r['end_h'], r['end_m'])}"
                if r['type'] == "DRIVE":
                    html = f"<div class='history-row'><div><span class='tag tag-drive'>運転</span> <span style='font-size:12px;'>{time_str} ({r['distance_km']}km)</span></div></div>"
                elif r['type'] == "BREAK":
                    html = f"<div class='history-row'><div><span class='tag tag-break'>休憩</span> <span style='font-size:12px;'>{time_str}</span></div></div>"
                else:
                    html = f"<div class='history-row'><div><span class='tag tag-work'>勤務</span> <span style='font-size:12px;'>{time_str}</span></div></div>"
                st.markdown(html, unsafe_allow_html=True)
            with c2:
                st.write("") 
                if st.button("✕", key=f"del_{r['id']}"):
                    delete_record_by_id(r['id'])
                    st.rerun()
        
        st.markdown(f"""
            <div class="total-area" style="margin-top:10px; background-color:#1f2933;">
                <div class="total-sub">実働 {day_min//60}時間{day_min%60}分</div>
                <div class="total-amount">計 ¥{day_pay:,}</div>
            </div>
        """, unsafe_allow_html=True)

# ==========================================
# TAB: カレンダー (Grid Layout)
# ==========================================
with tab_calendar:
    
    min_record_date = get_min_record_date()
    min_date_limit = min_record_date.replace(day=1)
    current_date_obj = datetime.date.today()
    max_date_limit = current_date_obj.replace(day=1)
    view_date = datetime.date(st.session_state.view_year, st.session_state.view_month, 1)
    
    can_go_prev = view_date > min_date_limit
    can_go_next = view_date < max_date_limit

    c1, c2, c3 = st.columns([1, 3, 1])
    with c1: 
        if st.button("◀", use_container_width=True, disabled=not can_go_prev): 
            change_month(-1); st.rerun()
    with c2:
        st.markdown(f"<div style='text-align:center; font-weight:bold; padding-top:5px; color:#bbb;'>{st.session_state.view_year}年 {st.session_state.view_month}月</div>", unsafe_allow_html=True)
    with c3:
        if st.button("▶", use_container_width=True, disabled=not can_go_next): 
            change_month(1); st.rerun()
    
    st.write("")
    summary = get_calendar_summary(st.session_state.base_wage)
    
    total_pay = 0
    total_min = 0
    s_date = datetime.date(st.session_state.view_year, st.session_state.view_month, 1)
    e_date = datetime.date(st.session_state.view_year, st.session_state.view_month, calendar.monthrange(st.session_state.view_year, st.session_state.view_month)[1])
    curr = s_date
    while curr <= e_date:
        d_str = curr.strftime("%Y-%m-%d")
        if d_str in summary:
            total_pay += summary[d_str]['pay']
            total_min += summary[d_str]['min']
        curr += datetime.timedelta(days=1)

    st.markdown(f"""
    <div class="total-area">
        <div class="total-sub">今月の支給予定額</div>
        <div class="total-amount">¥ {total_pay:,}</div>
        <div class="total-sub" style="margin-top:5px;">総稼働: {total_min//60}時間{total_min%60}分</div>
    </div>
    """, unsafe_allow_html=True)

    html_parts = []
    html_parts.append('<div class="calendar-grid">')
    
    for w in ["日", "月", "火", "水", "木", "金", "土"]:
        color = "#ff6666" if w=="日" else "#4da6ff" if w=="土" else "#aaa"
        html_parts.append(f'<div class="cal-header" style="color:{color}">{w}</div>')
    
    cal_obj = calendar.Calendar(firstweekday=6)
    month_days = cal_obj.monthdayscalendar(st.session_state.view_year, st.session_state.view_month)
    today_d = datetime.date.today()

    for week in month_days:
        for day in week:
            if day == 0:
                html_parts.append('<div class="cal-day cal-empty"></div>')
            else:
                curr_d = datetime.date(st.session_state.view_year, st.session_state.view_month, day)
                d_str = curr_d.strftime("%Y-%m-%d")
                pay_val = summary.get(d_str, {'pay': 0})['pay']
                
                extra_cls = "cal-today" if curr_d == today_d else ""
                pay_disp = f"¥{pay_val:,}" if pay_val > 0 else ""
                pay_div = f'<div class="cal-pay">{pay_disp}</div>' if pay_disp else ""
                
                html_parts.append(f'<div class="cal-day {extra_cls}"><div class="cal-num">{day}</div>{pay_div}</div>')
                
    html_parts.append('</div>') 
    st.markdown("".join(html_parts), unsafe_allow_html=True)